import re
import json
import time
from typing import Any, Dict, List, Optional

from utils import logger
from maa.context import Context
from maa.custom_action import CustomAction
from maa.agent.agent_server import AgentServer

from agent.hif.domain import HIFCandidate
from agent.hif.ui_map import load_hif_ui_map
from agent.hif.journal import HIFFrameEvidence, frame_changed, get_runtime_hif_journal
from agent.hif.presets import HIFPreset, parse_hif_preset
from agent.hif.runtime import validate_hif_frame
from agent.hif.session import get_runtime_hif_session, reset_runtime_hif_session
from agent.hif.execution import HIFExecutionMode, parse_execution_mode, approve_card_execution
from agent.hif.calibration import load_hif_roi_calibration
from agent.hif.route_planner import HIFRoutePlanner
from agent.hif.decisions.play import GarakutaRinamiStrategy
from agent.hif.decisions.state import ExamRound, ActionKind, CardAction
from agent.hif.screen_profiles import load_hif_screen_profiles
from agent.hif.decisions.config import ProfilePayload
from agent.hif.adapters.card_dict import normalize_card_name, is_good_condition_card
from agent.hif.adapters.exam_reader import CardDetection, ExamStateReader
from agent.hif.adapters.hif_state_reader import HIFStateReader


class _ProduceHIFActionBase(CustomAction):
    CLICK_DELAY = 0.4
    ACTION_DELAY = 2.0

    @staticmethod
    def _observed_button_roi(screen_state: str, button_id: str, fallback: List[int]) -> List[int]:
        """优先使用已观察案例记录的 ROI；缺少证据时保留调用方显式回退。"""

        roi = load_hif_ui_map().button_roi(screen_state, button_id)
        return list(roi) if roi is not None else fallback

    @staticmethod
    def _profile_region(screen_state: str, region_id: str, fallback: List[int]) -> List[int]:
        """优先使用已审阅页面配置中的区域，缺少时保留显式回退。"""

        profile = load_hif_screen_profiles().get(screen_state)
        roi = profile.regions.get(region_id) if profile else None
        return list(roi) if roi is not None else fallback

    @staticmethod
    def _get_screenshot(context: Context):
        return context.tasker.controller.post_screencap().wait().get()

    def _get_screenshot_or_stop(self, context: Context, screen_state: str):
        """控制器断连时统一记录原因并结束当前 HIF 动作。"""

        try:
            return self._get_screenshot(context)
        except Exception as error:
            self._stop_unsupported(context, screen_state, f"screencap_failed:{error}")
            return None

    @staticmethod
    def _click_box_center(context: Context, box: List[int], double: bool = True, y_offset: int = 0) -> bool:
        if not box or len(box) < 4:
            return False

        x = box[0] + box[2] // 2
        y = box[1] + box[3] // 2 + y_offset
        context.tasker.controller.post_click(x, y).wait()
        if double:
            time.sleep(_ProduceHIFActionBase.CLICK_DELAY)
            context.tasker.controller.post_click(x, y).wait()
        return True

    @staticmethod
    def _run_ocr(context: Context, image, name: str, expected: list[str] | str, roi: list[int]):
        return context.run_recognition(
            name,
            image,
            pipeline_override={name: {"recognition": "OCR", "expected": expected, "roi": roi}},
        )

    @staticmethod
    def _run_template(context: Context, image, name: str, template: list[str] | str, roi: list[int], threshold: float = 0.8):
        return context.run_recognition(
            name,
            image,
            pipeline_override={name: {"recognition": "TemplateMatch", "template": template, "roi": roi, "threshold": threshold}},
        )

    @staticmethod
    def _stop_unknown(context: Context, reason: str) -> bool:
        logger.warning(f"HIF ??: {reason}")
        context.run_task("ProduceHIFUnknownStop")
        return True

    def _configure_page_execution(self, argv: CustomAction.RunArg) -> HIFExecutionMode:
        """页面动作默认观察；只有显式 single_step 才能触发验证型点击。"""

        mode = parse_execution_mode(self._get_action_params(argv).get("execution_mode"))
        self._page_execution_mode = mode
        return mode

    def _get_preset(self, argv: CustomAction.RunArg) -> HIFPreset:
        self._configure_page_execution(argv)
        return parse_hif_preset(argv.custom_action_param)

    @staticmethod
    def _get_action_params(argv: CustomAction.RunArg) -> dict[str, Any]:
        """读取 Custom Action 参数；格式异常时只保留安全默认值。"""

        try:
            payload = json.loads(argv.custom_action_param or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _capture_evidence(image, label: str) -> HIFFrameEvidence:
        return get_runtime_hif_journal().capture(image, label)

    @staticmethod
    def _record_journal(
        screen_state: str,
        event: str,
        outcome: str,
        *,
        details: dict[str, Any] | None = None,
        before: HIFFrameEvidence | None = None,
        after: HIFFrameEvidence | None = None,
    ) -> None:
        get_runtime_hif_journal().record(
            screen_state,
            event,
            outcome,
            details=details,
            before=before,
            after=after,
        )

    def _stop_unsupported(self, context: Context, screen_state: str, reason: str) -> bool:
        logger.warning(f"HIF 安全停止: screen_state={screen_state}, reason={reason}")
        self._record_journal(screen_state, "safe_stop", "stopped", details={"reason": reason})
        context.run_task("ProduceHIFUnknownStop")
        return True

    def _find_text_option(self, context: Context, image, phrases: tuple[str, ...], roi: list[int]):
        for phrase in phrases:
            reco_detail = self._run_ocr(
                context,
                image,
                "ProduceRecognitionHIFTextOption",
                [f".*{re.escape(phrase)}.*"],
                roi,
            )
            if reco_detail and reco_detail.hit:
                return reco_detail
        return None

    def _click_text_with_verification(
        self,
        context: Context,
        image,
        screen_state: str,
        event: str,
        phrases: tuple[str, ...],
        roi: list[int],
        *,
        y_offset: int = 0,
    ) -> bool:
        """点击唯一 OCR 文案，并以新截图指纹验证页面已变化。"""

        before = self._capture_evidence(image, f"{screen_state}_{event}_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                screen_state,
                event,
                "observed",
                details={"reason": "page_execution_mode_not_single_step", "mode": mode.value, "phrases": phrases},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "page_execution_mode_not_single_step")
        reco_detail = self._find_text_option(context, image, phrases, roi)
        if not reco_detail:
            self._record_journal(
                screen_state,
                event,
                "rejected",
                details={"reason": "button_text_not_found", "phrases": phrases},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "button_text_not_found")
        if not self._click_box_center(context, reco_detail.best_result.box, double=False, y_offset=y_offset):
            self._record_journal(
                screen_state,
                event,
                "failed",
                details={"reason": "button_click_failed", "text": reco_detail.best_result.text},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "button_click_failed")

        time.sleep(self.ACTION_DELAY)
        try:
            after_image = self._get_screenshot(context)
        except Exception as error:
            self._record_journal(
                screen_state,
                event,
                "unverified",
                details={"reason": f"post_screencap_failed:{error}", "text": reco_detail.best_result.text},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, f"post_screencap_failed:{error}")
        after = self._capture_evidence(after_image, f"{screen_state}_{event}_after")
        if not frame_changed(before, after):
            self._record_journal(
                screen_state,
                event,
                "unverified",
                details={"reason": "post_click_frame_unchanged", "text": reco_detail.best_result.text},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, screen_state, "post_click_frame_unchanged")

        self._record_journal(
            screen_state,
            event,
            "verified",
            details={"text": reco_detail.best_result.text},
            before=before,
            after=after,
        )
        return True

    def _click_box_with_verification(
        self,
        context: Context,
        image,
        screen_state: str,
        event: str,
        box: List[int],
        *,
        details: dict[str, Any] | None = None,
        y_offset: int = 0,
        click_failure_reason: str = "candidate_click_failed",
    ) -> bool:
        """点击已由上层唯一识别的候选框，并记录点击前后的页面证据。"""

        before = self._capture_evidence(image, f"{screen_state}_{event}_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                screen_state,
                event,
                "observed",
                details={**(details or {}), "reason": "page_execution_mode_not_single_step", "mode": mode.value},
                before=before,
            )
            self._stop_unsupported(context, screen_state, "page_execution_mode_not_single_step")
            return False
        if not self._click_box_center(context, box, double=False, y_offset=y_offset):
            self._record_journal(
                screen_state,
                event,
                "failed",
                details={**(details or {}), "reason": click_failure_reason},
                before=before,
            )
            self._stop_unsupported(context, screen_state, click_failure_reason)
            return False
        time.sleep(self.ACTION_DELAY)
        try:
            after_image = self._get_screenshot(context)
        except Exception as error:
            self._record_journal(
                screen_state,
                event,
                "unverified",
                details={**(details or {}), "reason": f"post_screencap_failed:{error}"},
                before=before,
            )
            self._stop_unsupported(context, screen_state, f"post_screencap_failed:{error}")
            return False
        after = self._capture_evidence(after_image, f"{screen_state}_{event}_after")
        if not frame_changed(before, after):
            self._record_journal(
                screen_state,
                event,
                "unverified",
                details={**(details or {}), "reason": "post_click_frame_unchanged"},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, screen_state, "post_click_frame_unchanged")
            return False
        self._record_journal(screen_state, event, "verified", details=details, before=before, after=after)
        return True

    def _swipe_with_verification(
        self,
        context: Context,
        image,
        screen_state: str,
        event: str,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        duration: int,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """执行一次已校准的滑动，并以帧变化证明页面确实响应。"""

        before = self._capture_evidence(image, f"{screen_state}_{event}_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                screen_state,
                event,
                "observed",
                details={**(details or {}), "reason": "page_execution_mode_not_single_step", "mode": mode.value},
                before=before,
            )
            self._stop_unsupported(context, screen_state, "page_execution_mode_not_single_step")
            return False
        try:
            context.tasker.controller.post_swipe(*start, *end, duration=duration).wait()
        except Exception as error:
            self._record_journal(
                screen_state,
                event,
                "failed",
                details={**(details or {}), "reason": f"swipe_failed:{error}"},
                before=before,
            )
            self._stop_unsupported(context, screen_state, f"swipe_failed:{error}")
            return False
        time.sleep(self.ACTION_DELAY)
        try:
            after_image = self._get_screenshot(context)
        except Exception as error:
            self._record_journal(
                screen_state,
                event,
                "unverified",
                details={**(details or {}), "reason": f"post_screencap_failed:{error}"},
                before=before,
            )
            self._stop_unsupported(context, screen_state, f"post_screencap_failed:{error}")
            return False
        after = self._capture_evidence(after_image, f"{screen_state}_{event}_after")
        if not frame_changed(before, after):
            self._record_journal(
                screen_state,
                event,
                "unverified",
                details={**(details or {}), "reason": "post_swipe_frame_unchanged"},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, screen_state, "post_swipe_frame_unchanged")
            return False
        self._record_journal(screen_state, event, "verified", details=details, before=before, after=after)
        return True

    @staticmethod
    def _get_health(context: Context, image) -> Optional[dict]:
        reco_detail = context.run_recognition("ProduceRecognitionHealth", image)
        if not (reco_detail and reco_detail.hit):
            return None

        try:
            health_parts = reco_detail.best_result.text.split("/")
            current_health = int(health_parts[0])
            max_health = int(health_parts[1])
            ratio = current_health / max_health
            logger.info(f"体力: {current_health}/{max_health} ({ratio:.2%})")
            return {"current": current_health, "max": max_health, "ratio": ratio}
        except (ValueError, IndexError, ZeroDivisionError):
            logger.warning("体力数据解析失败")
            return None

    def _get_day_remaining(self, context: Context, image) -> Optional[int]:
        reco_detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFRemainingDay",
            [".*[1-6]日.*"],
            [30, 25, 160, 145],
        )
        if not (reco_detail and reco_detail.hit):
            return None

        digits = "".join(char for char in reco_detail.best_result.text if char.isdigit())
        day_remaining = int(digits) if digits else None
        logger.info(f"HIF 剩余日数: {day_remaining}")
        return day_remaining


@AgentServer.custom_action("ProduceHIFValidateDevice")
class ProduceHIFValidateDevice(_ProduceHIFActionBase):
    """在每次 HIF 路由前验证控制器截图坐标契约。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        del argv
        try:
            image = self._get_screenshot(context)
        except Exception as error:  # 控制器绑定会抛出版本相关异常，必须安全终止。
            return self._stop_unsupported(context, "device_preflight", f"screencap_failed:{error}")

        validation = validate_hif_frame(image)
        if not validation.ok:
            self._record_journal(
                "device_preflight",
                "validate_frame",
                "rejected",
                details={"reason": validation.reason, "width": validation.width, "height": validation.height},
            )
            return self._stop_unsupported(context, "device_preflight", validation.reason)

        self._record_journal(
            "device_preflight",
            "validate_frame",
            "validated",
            details={"width": validation.width, "height": validation.height},
        )
        logger.debug(f"HIF 设备预检通过: {validation.width}x{validation.height}")
        return True


@AgentServer.custom_action("ProduceHIFSelectionObserve")
class ProduceHIFSelectionObserve(_ProduceHIFActionBase):
    """选拔模式尚未取得完整实机候选池前，只采集证据并停止。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        del argv
        image = self._get_screenshot_or_stop(context, "selection_mode")
        if image is None:
            return True
        before = self._capture_evidence(image, "selection_mode_before")
        validation = validate_hif_frame(image)
        self._record_journal(
            "selection_mode",
            "selection_observe",
            "observed" if validation.ok else "rejected",
            details={"reason": validation.reason, "width": validation.width, "height": validation.height},
            before=before,
        )
        return self._stop_unsupported(context, "selection_mode", "selection_candidate_pool_not_calibrated")


@AgentServer.custom_action("ProduceHIFDrinkOverflowObserve")
class ProduceHIFDrinkOverflowObserve(_ProduceHIFActionBase):
    """饮料满仓候选格尚未校准时记录现场，不盲选或丢弃饮料。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        del argv
        image = self._get_screenshot_or_stop(context, "drink_overflow")
        if image is None:
            return True
        before = self._capture_evidence(image, "drink_overflow_before")
        self._record_journal(
            "drink_overflow",
            "resolve_drink_overflow",
            "observed",
            details={"reason": "drink_overflow_candidate_grid_not_calibrated"},
            before=before,
        )
        return self._stop_unsupported(context, "drink_overflow", "drink_overflow_candidate_grid_not_calibrated")


@AgentServer.custom_action("ProduceChooseHIFEventAuto")
class ProduceChooseHIFEventAuto(_ProduceHIFActionBase):
    EVENT_CONFIG = {
        "相談": "produce/chat.png",
        "おでかけ": "produce/go_out.png",
        "课程": "produce/lesson.png",
        "活动": "produce/event.png",
        "Vo": "produce/Vo.png",
        "Da": "produce/Da.png",
        "Vi": "produce/Vi.png",
    }
    EVENT_PRESET_KEYS = {
        "相談": "consult",
        "おでかけ": "go_out",
        "课程": "lesson",
        "活动": "gift",
        "Vo": "Vo",
        "Da": "Da",
        "Vi": "Vi",
    }

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        logger.success("事件: HIF 选择日程")
        image = self._get_screenshot(context)
        reading = HIFStateReader.from_context(context, image).read_finals_prepare_state()
        page = reading.page_observation
        if page is None or not page.is_unique or page.screen_id != "finals_prepare":
            return self._stop_unsupported(context, "finals_action_select", "finals_prepare_page_not_confirmed")
        if reading.missing_fields:
            return self._stop_unsupported(context, "finals_action_select", f"state_unreadable:{','.join(reading.missing_fields)}")
        events = self._get_available_events(context, image)

        if not events:
            return self._stop_unsupported(context, "finals_action_select", "no_schedule_candidates")

        preset = self._get_preset(argv)
        decision = HIFRoutePlanner().choose_schedule(
            reading.state,
            [HIFCandidate(event["name"], event["name"], event["category"]) for event in events],
            preset,
        )
        if decision.should_stop:
            return self._stop_unsupported(context, "finals_action_select", decision.stop_reason or "schedule_decision_unavailable")
        best_event = next((event for event in events if event["name"] == decision.candidate_id), None)
        if best_event is None:
            return self._stop_unsupported(context, "finals_action_select", "selected_schedule_not_visible")

        logger.info(f"HIF 选择事件: {best_event['name']}，理由={' / '.join(decision.reasons)}")
        self._record_journal(
            "finals_action_select",
            "choose_schedule",
            "selected",
            details={
                "candidate": best_event["name"],
                "reasons": decision.reasons,
                "confidence": decision.confidence,
                "page": page.screen_id,
                "page_confidence": page.confidence,
            },
        )
        return self._execute_event(context, image, best_event)

    def _execute_event(self, context: Context, image, event: dict) -> bool:
        return self._click_box_with_verification(
            context,
            image,
            "finals_action_select",
            "select_schedule",
            event["box"],
            details={"candidate": event.get("name", "unknown")},
        )

    def _get_available_events(self, context: Context, image) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        log_names: List[str] = []
        roi = [0, 840, 720, 280]

        for event_name, template in self.EVENT_CONFIG.items():
            reco_detail = self._run_template(context, image, "ProduceRecognitionHIFEvent", template, roi, threshold=0.78)
            if reco_detail and reco_detail.hit:
                event = {
                    "name": event_name,
                    "category": self.EVENT_PRESET_KEYS[event_name],
                    "box": reco_detail.best_result.box,
                }
                events.append(event)
                log_names.append(event_name)

        if log_names:
            logger.info(f"HIF 可用日程: {', '.join(log_names)}")
        return events


@AgentServer.custom_action("ProduceChooseHIFPItemAuto")
class ProduceChooseHIFPItemAuto(_ProduceHIFActionBase):
    OPTION_ROI = [40, 300, 640, 760]
    OPTION_CANDIDATES = [
        [360, 610, 1, 1],
        [360, 790, 1, 1],
        [360, 970, 1, 1],
    ]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        logger.success("事件: HIF 选择 P 道具")
        image = self._get_screenshot(context)

        preset = self._get_preset(argv)
        planner = HIFRoutePlanner()
        session = get_runtime_hif_session()
        first_stage = session.latest_p_item(1)
        preferred = tuple(
            item.name
            for item in planner.custom_p_item_search_order(
                preset,
                stage=2 if first_stage else 1,
                parent=first_stage,
            )
        )
        if preferred:
            preferred_hit = self._find_text_option(context, image, preferred, self.OPTION_ROI)
            if preferred_hit:
                selected_name = next((name for name in preferred if name in preferred_hit.best_result.text), None)
                if selected_name is None:
                    return self._stop_unsupported(context, "hif_p_item_select", "preferred_p_item_name_unverified")
                logger.info(f"命中 HIF 预设 P 道具: {selected_name}")
                if not self._click_box_with_verification(
                    context,
                    image,
                    "hif_p_item_select",
                    "select_p_item",
                    preferred_hit.best_result.box,
                    details={"name": selected_name, "parent": first_stage},
                ):
                    return True
                item = planner.catalog.custom_p_items.get(selected_name)
                if item is None:
                    return self._stop_unsupported(context, "hif_p_item_select", "selected_p_item_missing_from_catalog")
                session.record_p_item(item.name_jp, item.stage)
                return True

        if preset.preset_id == "rinami_good_condition_safe":
            return self._stop_unsupported(context, "hif_p_item_select", "p_item_stage_candidate_not_found")

        recommend = self._find_recommend(context, image)
        if recommend:
            logger.info("命中推荐 P 道具")
            return self._click_box_with_verification(
                context,
                image,
                "hif_p_item_select",
                "select_recommended_p_item",
                recommend,
                y_offset=80,
                details={"selection": "recommend"},
            )

        keyword_hit = self._find_keyword_option(context, image)
        if keyword_hit:
            logger.info(f"按关键词选择 HIF P 道具: {keyword_hit['name']}")
            return self._click_box_with_verification(
                context,
                image,
                "hif_p_item_select",
                "select_keyword_p_item",
                keyword_hit["box"],
                details={"selection": keyword_hit["name"]},
            )

        return self._stop_unsupported(context, "hif_p_item_select", "preset_p_item_not_found")

    def _find_recommend(self, context: Context, image) -> Optional[List[int]]:
        reco_detail = self._run_template(
            context,
            image,
            "ProduceRecognitionHIFRecommend",
            ["produce/recommend.png", "produce/event_recommend.png"],
            self.OPTION_ROI,
            threshold=0.78,
        )
        if reco_detail and reco_detail.hit:
            return reco_detail.best_result.box
        return None

    def _find_keyword_option(self, context: Context, image) -> Optional[Dict[str, Any]]:
        keyword_order = [
            ("Pポイント", [".*Pポイント.*"]),
            ("相談", [".*相談.*"]),
            ("Pドリンク", [".*Pドリンク.*", ".*ドリンク.*"]),
        ]
        for name, expected in keyword_order:
            reco_detail = self._run_ocr(context, image, f"ProduceRecognitionHIFPItem{name}", expected, self.OPTION_ROI)
            if reco_detail and reco_detail.hit:
                return {"name": name, "box": reco_detail.best_result.box}
        return None


@AgentServer.custom_action("ProduceChooseHIFClassOptionAuto")
class ProduceChooseHIFClassOptionAuto(_ProduceHIFActionBase):
    """选择已在实机记录中确认的好调授業选项。"""

    OPTION_ROI = [40, 620, 640, 360]
    GOOD_CONDITION_OPTIONS = ("余裕です！", "長い道のりでした")

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if "good_condition" not in preset.class_option_priority:
            return self._stop_unsupported(context, "hif_class_options", "preset_no_class_option_policy")

        image = self._get_screenshot_or_stop(context, "hif_class_options")
        if image is None:
            return True
        reco_detail = self._find_text_option(
            context,
            image,
            self.GOOD_CONDITION_OPTIONS,
            self._profile_region("class_options", "options", self.OPTION_ROI),
        )
        if not reco_detail:
            return self._stop_unsupported(context, "hif_class_options", "good_condition_option_not_found")
        return self._click_box_with_verification(
            context,
            image,
            "hif_class_options",
            "select_good_condition_option",
            reco_detail.best_result.box,
            details={"options": self.GOOD_CONDITION_OPTIONS},
        )


class _ProduceHIFRewardChoiceAction(_ProduceHIFActionBase):
    OPTION_ROI = [80, 760, 560, 260]
    REROLL_ROI = [530, 1000, 180, 140]

    def _choose_named_reward(
        self,
        context: Context,
        names: tuple[str, ...],
        reroll_limit: int,
        screen_state: str,
    ) -> bool:
        profile_screen = {
            "hif_drink_reward": "drink_reward",
            "hif_skill_reward": "skill_reward",
            "select_change_target": "select_change_target",
        }.get(screen_state)
        profile = load_hif_screen_profiles().get(profile_screen) if profile_screen else None
        option_roi = list(profile.regions["candidates"]) if profile and "candidates" in profile.regions else self.OPTION_ROI
        reroll_roi = list(profile.buttons["reroll"].roi) if profile and "reroll" in profile.buttons else self.REROLL_ROI
        for _ in range(reroll_limit + 1):
            image = self._get_screenshot(context)
            reco_detail = self._find_text_option(context, image, names, option_roi)
            if reco_detail:
                return self._click_box_with_verification(
                    context,
                    image,
                    screen_state,
                    "select_reward",
                    reco_detail.best_result.box,
                    details={"reward": reco_detail.best_result.text},
                )

            reroll = self._find_text_option(context, image, ("再抽選",), reroll_roi)
            if not reroll:
                break
            if not self._click_box_with_verification(
                context,
                image,
                screen_state,
                "reroll_reward",
                reroll.best_result.box,
                details={"attempt": _ + 1},
            ):
                return False

        logger.warning(f"HIF 奖励未命中预设: screen_state={screen_state}")
        return False

    @staticmethod
    def _reward_search_names(reward_kind: str, preset: HIFPreset) -> tuple[str, ...]:
        ranked = HIFRoutePlanner().reward_search_order(reward_kind, preset)
        return tuple(item.name for item in ranked)


@AgentServer.custom_action("ProduceChooseHIFDrinkRewardAuto")
class ProduceChooseHIFDrinkRewardAuto(_ProduceHIFRewardChoiceAction):
    """按预设领取已识别的 P 饮料。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        chosen = self._choose_named_reward(
            context,
            self._reward_search_names("drink", preset),
            reroll_limit=0,
            screen_state="hif_drink_reward",
        )
        return chosen or self._stop_unsupported(context, "hif_drink_reward", "preset_drink_not_found")


@AgentServer.custom_action("ProduceChooseHIFSkillRewardAuto")
class ProduceChooseHIFSkillRewardAuto(_ProduceHIFRewardChoiceAction):
    """按预设领取技能卡，且只在明确识别到再抽选时重抽。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        chosen = self._choose_named_reward(
            context,
            self._reward_search_names("skill", preset),
            reroll_limit=preset.reroll_limit,
            screen_state="hif_skill_reward",
        )
        return chosen or self._stop_unsupported(context, "hif_skill_reward", "preset_skill_not_found")


@AgentServer.custom_action("ProduceChooseHIFSelectChangeTargetAuto")
class ProduceChooseHIFSelectChangeTargetAuto(_ProduceHIFRewardChoiceAction):
    """在变卡第一阶段选择预设目标卡，并推进到牌库选择。"""

    NEXT_ROI = [200, 1010, 320, 130]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if not self._choose_named_reward(
            context,
            preset.select_change_target_names,
            reroll_limit=preset.reroll_limit,
            screen_state="select_change_target",
        ):
            return self._stop_unsupported(context, "select_change_target", "preset_target_card_not_found")

        image = self._get_screenshot_or_stop(context, "select_change_target")
        if image is None:
            return True
        next_button = self._find_text_option(
            context,
            image,
            ("次へ",),
            self._observed_button_roi("select_change_target", "next", self.NEXT_ROI),
        )
        if not next_button:
            return self._stop_unsupported(context, "select_change_target", "next_button_not_found")
        return self._click_box_with_verification(
            context,
            image,
            "select_change_target",
            "advance_select_change",
            next_button.best_result.box,
        )


@AgentServer.custom_action("ProduceChooseHIFSelectChangeSourceAuto")
class ProduceChooseHIFSelectChangeSourceAuto(_ProduceHIFActionBase):
    """在变卡第二阶段选择预设源卡并确认。"""

    DECK_ROI = [60, 600, 600, 500]
    CHANGE_ROI = [350, 1080, 320, 140]
    MAX_DECK_SCROLLS = 4

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        source = None
        source_image = None
        for scroll_index in range(self.MAX_DECK_SCROLLS + 1):
            image = self._get_screenshot_or_stop(context, "select_change_source_deck")
            if image is None:
                return True
            source = self._find_text_option(
                context,
                image,
                preset.select_change_source_names,
                self._profile_region("select_change_source_deck", "deck_grid", self.DECK_ROI),
            )
            if source:
                source_image = image
                break
            if scroll_index < self.MAX_DECK_SCROLLS:
                if not self._swipe_with_verification(
                    context,
                    image,
                    "select_change_source_deck",
                    "scroll_deck",
                    (360, 1040),
                    (360, 680),
                    duration=300,
                    details={"attempt": scroll_index + 1},
                ):
                    return True
        if not source:
            return self._stop_unsupported(context, "select_change_source_deck", "preset_source_card_not_found")
        if source_image is None:
            return self._stop_unsupported(context, "select_change_source_deck", "source_frame_not_available")
        if not self._click_box_with_verification(
            context,
            source_image,
            "select_change_source_deck",
            "select_change_source",
            source.best_result.box,
        ):
            return True

        image = self._get_screenshot_or_stop(context, "select_change_source_deck")
        if image is None:
            return True
        change_button = self._find_text_option(
            context,
            image,
            ("チェンジ",),
            self._observed_button_roi("select_change_source_deck", "change", self.CHANGE_ROI),
        )
        if not change_button:
            return self._stop_unsupported(context, "select_change_source_deck", "change_button_not_found")
        return self._click_box_with_verification(
            context,
            image,
            "select_change_source_deck",
            "confirm_select_change",
            change_button.best_result.box,
        )


@AgentServer.custom_action("ProduceHIFConsultAuto")
class ProduceHIFConsultAuto(_ProduceHIFActionBase):
    """首版仅支持保留 P 点并结束咨询商店。"""

    FINISH_ROI = [530, 1000, 190, 150]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        if self._get_preset(argv).consult_policy != "finish_without_purchase":
            return self._stop_unsupported(context, "consult_shop", "consult_policy_not_supported")

        image = self._get_screenshot_or_stop(context, "consult_shop")
        if image is None:
            return True
        finish_button = self._find_text_option(
            context,
            image,
            ("終了",),
            self._observed_button_roi("consult_shop", "finish", self.FINISH_ROI),
        )
        if not finish_button:
            return self._stop_unsupported(context, "consult_shop", "finish_button_not_found")
        self._click_box_with_verification(
            context,
            image,
            "consult_shop",
            "finish_consult",
            finish_button.best_result.box,
            click_failure_reason="finish_button_click_failed",
        )
        # _click_box_with_verification 已在失败时触发安全停止；对 Maa Custom
        # Action 返回成功，避免框架将安全停止误报为动作异常。
        return True


@AgentServer.custom_action("ProduceHIFRewardConfirmAuto")
class ProduceHIFRewardConfirmAuto(_ProduceHIFActionBase):
    """确认已由奖励选择 Action 唯一选中的领取项。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "hif_reward_confirm")
        if image is None:
            return True
        return self._click_text_with_verification(
            context,
            image,
            "hif_reward_confirm",
            "confirm_reward",
            ("受け取る",),
            self._observed_button_roi("drink_reward", "receive", [230, 1052, 260, 84]),
        )


@AgentServer.custom_action("ProduceHIFKnownNextAuto")
class ProduceHIFKnownNextAuto(_ProduceHIFActionBase):
    """仅在已识别的无资源结果页点击唯一的“次へ”。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "hif_known_result")
        if image is None:
            return True
        return self._click_text_with_verification(
            context,
            image,
            "hif_known_result",
            "continue_result",
            ("次へ",),
            self._observed_button_roi("public_lesson_result", "next", [180, 1000, 360, 180]),
        )


@AgentServer.custom_action("ProduceHIFChooseFinalModeAuto")
class ProduceHIFChooseFinalModeAuto(_ProduceHIFActionBase):
    """在已识别的 HIF 入口按预设进入本战模式。"""

    FINAL_MODE_BUTTON = [360, 824, 360, 171]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        if self._get_preset(argv).entry_mode != "finals":
            return self._stop_unsupported(context, "hif_mode_select", "entry_mode_not_supported")
        image = self._get_screenshot_or_stop(context, "hif_mode_select")
        if image is None:
            return True
        validation = validate_hif_frame(image)
        if not validation.ok:
            return self._stop_unsupported(context, "hif_mode_select", validation.reason)
        if not self._click_box_with_verification(
            context,
            image,
            "hif_mode_select",
            "select_final_mode",
            self.FINAL_MODE_BUTTON,
            details={"entry_mode": "finals"},
        ):
            return True
        reset_runtime_hif_session()
        logger.success("HIF 入口：按预设选择本战模式")
        return True


@AgentServer.custom_action("ProduceCardsHIF")
class ProduceCardsHIF(_ProduceHIFActionBase):
    """HIF 本战单步出牌执行器。

    默认只记录策略建议并停止；``single_step`` 仅在手牌、数值和点击后画面
    变化均可验证时点击一张明确目标卡。连续模式在实机校准和跨回合状态持久化
    完成前始终安全停止，避免把未验证策略放大成整局连点。
    """

    ROUND_CONFIG: dict[str, tuple[ExamRound, int, str]] = {
        "round1": (ExamRound.HONSEN_R1, 9, "round1"),
        "round2": (ExamRound.HONSEN_R2, 12, "round2"),
    }

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = self._get_action_params(argv)
        round_key = str(params.get("round", "round1"))
        config = self.ROUND_CONFIG.get(round_key)
        if config is None:
            return self._stop_unsupported(context, "hif_card_play", f"unknown_round:{round_key}")
        round_, total_turns, screen_state = config
        preset = self._get_preset(argv)
        mode = parse_execution_mode(
            params.get("execution_mode") or params.get(f"{round_key}_mode") or preset.round1_mode
        )

        try:
            before_image = self._get_screenshot(context)
        except Exception as error:
            return self._stop_unsupported(context, screen_state, f"screencap_failed:{error}")
        before = self._capture_evidence(before_image, f"{screen_state}_before")
        validation = validate_hif_frame(before_image)
        if not validation.ok:
            self._record_journal(
                screen_state,
                "card_decision",
                "rejected",
                details={"reason": validation.reason, "mode": mode.value},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, validation.reason)

        if mode is not HIFExecutionMode.OBSERVE and preset.preset_id != "rinami_good_condition_safe":
            self._record_journal(
                screen_state,
                "card_decision",
                "rejected",
                details={"reason": "card_strategy_profile_not_supported", "mode": mode.value, "preset": preset.preset_id},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "card_strategy_profile_not_supported")

        health = self._get_health(context, before_image)
        observation = ExamStateReader.from_context(context).read_exam_observation(
            round_,
            total_turns,
            health["current"] if health else None,
        )
        session = get_runtime_hif_session()
        observation.state.oneesan_used = session.card_was_played(round_key, "お姉さんの感覚")
        observation.state.natural_finisher_used = session.card_was_played(round_key, "自然体の魅力")
        card_action = GarakutaRinamiStrategy(ProfilePayload.default()).decide(observation.state)
        action_details = {
            "mode": mode.value,
            "round": round_.value,
            "decision_kind": card_action.kind.value,
            "target_card": card_action.target_card,
            "reason": card_action.reason,
            "screen_confidence": observation.screen_confidence,
            "missing_fields": observation.missing_fields,
            "detected_cards": [d.card_name for d in observation.detections if d.card_name],
        }

        if mode is HIFExecutionMode.OBSERVE:
            self._record_journal(screen_state, "card_decision", "observed", details=action_details, before=before)
            logger.success(f"HIF {screen_state} 影子决策: {card_action.kind.value} {card_action.target_card or ''} {card_action.reason}")
            return self._finish_observation(context, round_key)

        if mode is HIFExecutionMode.CONTINUOUS:
            self._record_journal(
                screen_state,
                "card_decision",
                "rejected",
                details={**action_details, "reason": "continuous_mode_requires_live_validation"},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "continuous_mode_requires_live_validation")

        calibration = load_hif_roi_calibration()
        if not calibration.is_exam_execution_ready:
            self._record_journal(
                screen_state,
                "card_decision",
                "rejected",
                details={
                    **action_details,
                    "reason": "exam_roi_calibration_not_execution_ready",
                    "calibration_device_id": calibration.device_id,
                    "calibration_updated_at": calibration.updated_at,
                },
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "exam_roi_calibration_not_execution_ready")

        targets = self._find_play_card_targets(card_action, observation.detections)
        approval = approve_card_execution(
            mode,
            screen_confidence=observation.screen_confidence,
            missing_fields=observation.missing_fields,
            target_count=len(targets),
            postcondition_supported=True,
        )
        if card_action.kind is not ActionKind.PLAY_CARD:
            approval_reason = f"action_kind_not_supported:{card_action.kind.value}"
        else:
            approval_reason = approval.reason
        if not approval.should_execute or card_action.kind is not ActionKind.PLAY_CARD:
            self._record_journal(
                screen_state,
                "card_decision",
                "rejected",
                details={**action_details, "reason": approval_reason, "target_count": len(targets)},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, approval_reason)

        target = targets[0]
        if not self._click_box_center(context, list(target.box), double=False):
            self._record_journal(
                screen_state,
                "play_card",
                "failed",
                details={**action_details, "reason": "card_click_failed", "card": target.card_name},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "card_click_failed")

        time.sleep(self.ACTION_DELAY)
        try:
            after_image = self._get_screenshot(context)
        except Exception as error:
            self._record_journal(
                screen_state,
                "play_card",
                "unverified",
                details={**action_details, "reason": f"post_screencap_failed:{error}", "card": target.card_name},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, f"post_screencap_failed:{error}")
        after = self._capture_evidence(after_image, f"{screen_state}_after")
        if not frame_changed(before, after):
            self._record_journal(
                screen_state,
                "play_card",
                "unverified",
                details={**action_details, "reason": "post_click_frame_unchanged", "card": target.card_name},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, screen_state, "post_click_frame_unchanged")

        self._record_journal(
            screen_state,
            "play_card",
            "verified",
            details={**action_details, "card": target.card_name},
            before=before,
            after=after,
        )
        session.record_card(round_key, target.card_name)
        logger.success(f"HIF {screen_state} 单步出牌已验证: {target.card_name}")
        return True

    @staticmethod
    def _find_play_card_targets(card_action: CardAction, detections: list[CardDetection]) -> list[CardDetection]:
        """将策略动作收窄为一个可验证的手牌框，默认策略绝不猜多张好调卡。"""

        if card_action.kind is not ActionKind.PLAY_CARD:
            return []
        target_name = normalize_card_name(card_action.target_card) if card_action.target_card else ""
        if target_name:
            return [detection for detection in detections if normalize_card_name(detection.card_name) == target_name]
        return [
            detection
            for detection in detections
            if detection.card_name and is_good_condition_card(normalize_card_name(detection.card_name))
        ]

    @staticmethod
    def _finish_observation(context: Context, round_key: str) -> bool:
        context.run_task("ProduceHIFRound1ReachedStop" if round_key == "round1" else "ProduceHIFRound2ReachedStop")
        return True


@AgentServer.custom_action("ProduceHIFIntervalAuto")
class ProduceHIFIntervalAuto(_ProduceHIFActionBase):
    """Round 间隔页的受控入口。

    未读取完整 P 点和体力时不会离开页面。默认观测并停止；当前唯一允许的
    自动操作是明确选择 ``结束``，它不购买、刷新或消耗 P 点。
    """

    END_ROI = [565, 1045, 155, 84]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        screen_state = "interval"
        image = self._get_screenshot_or_stop(context, screen_state)
        if image is None:
            return True
        before = self._capture_evidence(image, "interval_before")
        validation = validate_hif_frame(image)
        if not validation.ok:
            self._record_journal(screen_state, "interval", "rejected", details={"reason": validation.reason}, before=before)
            return self._stop_unsupported(context, screen_state, validation.reason)
        reading = HIFStateReader.from_context(context, image).read_interval_state()
        page = reading.page_observation
        if page is None or not page.is_unique or page.screen_id != "interval_shop":
            self._record_journal(
                screen_state,
                "interval",
                "rejected",
                details={"reason": "interval_page_not_confirmed", "matched": page.matched_screen_ids if page else ()},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "interval_page_not_confirmed")
        if reading.missing_fields:
            self._record_journal(
                screen_state,
                "interval",
                "rejected",
                details={"reason": "state_unreadable", "missing_fields": reading.missing_fields, "raw": reading.raw},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, f"state_unreadable:{','.join(reading.missing_fields)}")

        self._configure_page_execution(argv)
        mode = str(self._get_action_params(argv).get("interval_mode", "observe_and_stop"))
        details = {
            "mode": mode,
            "stamina": reading.state.stamina,
            "max_stamina": reading.state.max_stamina,
            "p_points": reading.state.p_points,
            "page": page.screen_id,
            "page_confidence": page.confidence,
        }
        if mode == "observe_and_stop":
            self._record_journal(screen_state, "interval", "observed", details=details, before=before)
            context.run_task("ProduceHIFIntervalReachedStop")
            return True
        if mode != "finish_without_purchase":
            self._record_journal(screen_state, "interval", "rejected", details={**details, "reason": "interval_mode_not_supported"}, before=before)
            return self._stop_unsupported(context, screen_state, "interval_mode_not_supported")
        return self._click_text_with_verification(
            context,
            image,
            screen_state,
            "finish_interval",
            ("終了",),
            self._observed_button_roi("interval_shop", "finish", self.END_ROI),
        )


@AgentServer.custom_action("ProduceHIFSettlementContinueAuto")
class ProduceHIFSettlementContinueAuto(_ProduceHIFActionBase):
    """本战获胜结算只点击中部“次へ”，不会误触左侧再挑战。"""

    NEXT_ROI = [230, 1094, 258, 82]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "settlement")
        if image is None:
            return True
        return self._click_text_with_verification(
            context,
            image,
            "settlement",
            "continue_settlement",
            ("次へ",),
            self._observed_button_roi("score_settlement", "next", self.NEXT_ROI),
        )


@AgentServer.custom_action("ProduceHIFLiveObserve")
class ProduceHIFLiveObserve(_ProduceHIFActionBase):
    """Live 演出默认观察；显式实验参数才尝试一次已记录的快进区域。"""

    SKIP_ROI = [535, 468, 155, 38]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "live")
        if image is None:
            return True
        before = self._capture_evidence(image, "live_before")
        mode = str(self._get_action_params(argv).get("live_mode", "observe_and_stop"))
        if mode == "skip_once":
            return self._click_box_with_verification(
                context,
                image,
                "live",
                "skip_live",
                self._profile_region("live", "skip", self.SKIP_ROI),
                details={"mode": mode, "source": "finals-daily-log"},
            )
        self._record_journal(
            "live",
            "skip_live",
            "observed",
            details={"reason": "live_skip_template_not_calibrated", "mode": mode},
            before=before,
        )
        return self._stop_unsupported(context, "live", "live_skip_template_not_calibrated")


class _ProduceHIFMemoryAction(_ProduceHIFActionBase):
    """回忆生成链路中可由明确文字唯一定位的无资源按钮。"""

    def _click_memory_button(
        self,
        context: Context,
        screen_state: str,
        event: str,
        phrases: tuple[str, ...],
        roi: list[int],
    ) -> bool:
        image = self._get_screenshot_or_stop(context, screen_state)
        if image is None:
            return True
        return self._click_text_with_verification(context, image, screen_state, event, phrases, roi)


@AgentServer.custom_action("ProduceHIFMemoryPhotoNext")
class ProduceHIFMemoryPhotoNext(_ProduceHIFMemoryAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        return self._click_memory_button(
            context,
            "memory_photo_select",
            "photo_next",
            ("次へ",),
            self._observed_button_roi("memory_photo_select", "next", [240, 1120, 242, 82]),
        )


@AgentServer.custom_action("ProduceHIFMemoryPhotoConfirm")
class ProduceHIFMemoryPhotoConfirm(_ProduceHIFMemoryAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        return self._click_memory_button(
            context,
            "memory_photo_confirm",
            "photo_confirm",
            ("決定",),
            self._observed_button_roi("memory_photo_confirm", "confirm", [373, 1137, 255, 70]),
        )


@AgentServer.custom_action("ProduceHIFMemoryGenerate")
class ProduceHIFMemoryGenerate(_ProduceHIFMemoryAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        return self._click_memory_button(
            context,
            "memory_generate",
            "generate_memory",
            ("生成",),
            self._observed_button_roi("memory_generate", "generate", [275, 900, 170, 170]),
        )


@AgentServer.custom_action("ProduceHIFMemoryPreviewNext")
class ProduceHIFMemoryPreviewNext(_ProduceHIFMemoryAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        return self._click_memory_button(
            context,
            "memory_preview",
            "confirm_memory",
            ("次へ",),
            self._observed_button_roi("memory_preview", "next", [240, 1118, 242, 82]),
        )


@AgentServer.custom_action("ProduceHIFRound1Observe")
class ProduceHIFRound1Observe(_ProduceHIFActionBase):
    """记录 Round1 初始手牌，首版不执行出牌。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if preset.round1_mode != "observe_and_stop":
            return self._stop_unsupported(context, "round1_initial", "round1_mode_not_supported")

        hand = ExamStateReader.from_context(context).read_hand()
        logger.success(
            "HIF 已到达 Round1："
            f"good_condition_cards={hand.good_condition_card_count}, "
            f"shizen={hand.has_shizen_no_miryoku}, oneesan={hand.has_oneesan_no_kankaku}"
        )
        context.run_task("ProduceHIFRound1ReachedStop")
        return True
