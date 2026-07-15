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
from agent.hif.catalog import load_hif_catalog
from agent.hif.journal import HIFFrameEvidence, frame_changed, get_runtime_hif_journal
from agent.hif.presets import HIFPreset, parse_hif_preset
from agent.hif.runtime import validate_hif_frame
from agent.hif.session import get_runtime_hif_session, reset_runtime_hif_session
from agent.hif.execution import HIFExecutionMode, parse_execution_mode, approve_card_execution
from agent.hif.calibration import load_hif_roi_calibration
from agent.hif.reward_pages import (
    detect_drink_reward_page,
    detect_drink_reward_reveal_page,
    detect_skill_reward_reveal_page,
    detect_skill_reward_selected_page,
)
from agent.hif.round_metrics import build_round_metrics
from agent.hif.route_planner import HIFRoutePlanner
from agent.hif.route_scoring import RouteDecisionStatus, RinamiGarakutaRouteScorer
from agent.hif.decisions.state import ExamRound, ActionKind, CardAction
from agent.hif.screen_profiles import load_hif_screen_profiles
from agent.hif.adapters.card_dict import normalize_card_name, build_card_name_dict, is_good_condition_card
from agent.hif.adapters.exam_reader import (
    NumericRead,
    CardDetection,
    ExamStateReader,
    build_hand_summary,
    infer_card_playability,
)
from agent.hif.adapters.route_state import RouteStateRejected, assemble_route_state
from agent.hif.adapters.active_effects import parse_active_effects
from agent.hif.adapters.hif_state_reader import HIFStateReader
from agent.hif.decisions.round1_fallback import (
    choose_observed_round1_recovery_card,
    choose_high_good_condition_topic_card,
    choose_observed_round1_post_topic_card,
    choose_observed_round1_post_shikirinaoshi_card,
)
from agent.hif.route_scoring.postconditions import verify_blessing_plus


class _ProduceHIFActionBase(CustomAction):
    CLICK_DELAY = 0.4
    ACTION_DELAY = 2.0
    # 这些页面已有正式 Pipeline 识别节点，但尚未形成 OCR screen profile。动作后
    # 只能把它们当作已知过渡目标，绝不能仅因画面变化而继续。
    _KNOWN_TRANSITION_RECOGNITIONS = {
        "gift_bags": "ProduceHIFGiftBagsFlag",
        "gift_reward_result": "ProduceHIFGiftRewardResultFlag",
        "skill_enhanced_result": "ProduceHIFSkillEnhancedResultFlag",
        "selection_mode": "ProduceHIFSelectionModeFlag",
        "final_mode": "ProduceHIFFinalModeFlag",
        "finished": "ProduceHIFFinishedFlag",
    }

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

    @staticmethod
    def _ocr_text_entries(reco_detail) -> tuple[dict[str, Any], ...]:
        """提取 OCR 的去重文本、框和置信度，按阅读顺序稳定排序。"""

        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, tuple[int, int, int, int]]] = set()
        for result in tuple(getattr(reco_detail, "filtered_results", ()) or ()) + tuple(getattr(reco_detail, "all_results", ()) or ()):
            text = str(getattr(result, "text", "")).strip()
            try:
                box = tuple(int(value) for value in result.box)
            except (AttributeError, TypeError, ValueError):
                continue
            if not text or len(box) != 4 or box[2] <= 0 or box[3] <= 0:
                continue
            key = (text, box)
            if key in seen:
                continue
            seen.add(key)
            raw_score = getattr(result, "score", 0.0)
            score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
            entries.append({"text": text, "box": box, "score": score})
        return tuple(sorted(entries, key=lambda entry: (entry["box"][1], entry["box"][0])))

    def _matches_profile_anchors(self, context: Context, image, screen_id: str) -> bool:
        """以页面配置中的所有 OCR 锚点确认当前页面。"""

        profile = load_hif_screen_profiles().get(screen_id)
        if profile is None:
            return False
        for anchor in profile.anchors:
            reco_detail = self._run_ocr(
                context,
                image,
                f"ProduceRecognitionHIFScreen_{screen_id}_{anchor.anchor_id}",
                [anchor.pattern],
                list(anchor.roi),
            )
            if not (reco_detail and reco_detail.hit):
                return False
        return True

    def _matches_screen_profile(self, context: Context, image, screen_id: str) -> bool:
        """确认配置页；P 饮料额外接受经双锚点验证的已选中详情态。"""

        if self._matches_profile_anchors(context, image, screen_id):
            return True
        if screen_id == "drink_reward":
            return detect_drink_reward_page(context, image) is not None
        return screen_id == "skill_reward" and detect_skill_reward_selected_page(context, image) is not None

    def _wait_for_screen_profile(self, context: Context, image, screen_id: str, attempts: int = 2):
        """弹窗刚出现时有限重取截图；不能确认页面就返回 None，绝不猜测。"""

        candidate = image
        for attempt in range(max(1, attempts + 1)):
            if self._matches_screen_profile(context, candidate, screen_id):
                return candidate
            if attempt >= attempts:
                break
            time.sleep(self.CLICK_DELAY)
            candidate = self._get_screenshot_or_stop(context, screen_id)
            if candidate is None:
                return None
        return None

    def _detect_screen_profile(
        self,
        context: Context,
        image,
        screen_ids: tuple[str, ...] | None = None,
        *,
        exclude: tuple[str, ...] = (),
    ) -> str | None:
        """只返回唯一命中的已知页面，歧义时交给上层安全停止。"""

        profiles = load_hif_screen_profiles()
        candidates = screen_ids or tuple(profiles.profiles)
        matched = tuple(
            screen_id
            for screen_id in candidates
            if screen_id not in exclude and self._matches_screen_profile(context, image, screen_id)
        )
        return matched[0] if len(matched) == 1 else None

    def _detect_confirmed_hif_transition(self, context: Context, image) -> str | None:
        """返回已知页面配置或已注册过渡节点，未知帧一律不视为成功。"""

        screen_id = self._detect_screen_profile(context, image)
        if screen_id is not None:
            return screen_id
        run_recognition = getattr(context, "run_recognition", None)
        if not callable(run_recognition):
            return None
        for transition_id, recognition_name in self._KNOWN_TRANSITION_RECOGNITIONS.items():
            try:
                recognition = run_recognition(recognition_name, image)
            except Exception:
                continue
            if recognition and recognition.hit:
                return transition_id
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
        allowed_next_screens: tuple[str, ...] | None = None,
        postcondition_failure_reason: str | None = None,
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

        next_screen = None
        if allowed_next_screens is not None:
            next_screen = self._detect_confirmed_hif_transition(context, after_image)
            if next_screen not in allowed_next_screens:
                reason = postcondition_failure_reason or f"{event}_next_page_not_confirmed"
                self._record_journal(
                    screen_state,
                    event,
                    "unverified",
                    details={"reason": reason, "text": reco_detail.best_result.text, "next_screen": next_screen},
                    before=before,
                    after=after,
                )
                return self._stop_unsupported(context, screen_state, reason)

        self._record_journal(
            screen_state,
            event,
            "verified",
            details={"text": reco_detail.best_result.text, **({"next_screen": next_screen} if next_screen else {})},
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
    """饮料满仓默认只读；已校准的单项恢复必须逐步验证。"""

    _REMAINING_ONE = ("あと\\s*1個選択",)
    _REMAINING_TWO = ("あと\\s*2個選択",)
    _REMAINING_ZERO = ("あと\\s*0個選択",)
    _ULONG_EFFECT = ("元気\\s*\\+\\s*7",)
    _BLACK_VINEGAR_EFFECT = ("次に使用したスキルカードの消費体力",)

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        mode = self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "drink_overflow")
        if image is None:
            return True
        before = self._capture_evidence(image, "drink_overflow_before")
        params = self._get_action_params(argv)
        if params.get("drink_overflow_keep") == "初星黒酢":
            if mode is not HIFExecutionMode.SINGLE_STEP:
                self._record_journal(
                    "drink_overflow",
                    "resolve_drink_overflow",
                    "observed",
                    details={"reason": "page_execution_mode_not_single_step", "mode": mode.value},
                    before=before,
                )
                return self._stop_unsupported(context, "drink_overflow", "page_execution_mode_not_single_step")
            return self._keep_black_vinegar(context, image, before)
        self._record_journal(
            "drink_overflow",
            "resolve_drink_overflow",
            "observed",
            details={"reason": "drink_overflow_candidate_grid_not_calibrated"},
            before=before,
        )
        return self._stop_unsupported(context, "drink_overflow", "drink_overflow_candidate_grid_not_calibrated")

    def _remaining_prompt(self, context: Context, image, expected: tuple[str, ...]):
        return self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFDrinkOverflowRemaining",
            list(expected),
            self._profile_region("drink_overflow", "remaining_prompt", [290, 1196, 145, 34]),
        )

    def _keep_black_vinegar(self, context: Context, image, before: HIFFrameEvidence) -> bool:
        """只处理已采样的“保留初星黒酢”状态，并能恢复一次误取消烏龍茶。"""

        if not self._matches_screen_profile(context, image, "drink_overflow"):
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_page_not_confirmed")
        current_image = image
        current = before
        if (remaining := self._remaining_prompt(context, current_image, self._REMAINING_ZERO)) and remaining.hit:
            return self._commit_preselected_drinks(context, current_image, current)
        if (remaining := self._remaining_prompt(context, current_image, self._REMAINING_TWO)) and remaining.hit:
            ulong = self._run_ocr(
                context, current_image, "ProduceRecognitionHIFDrinkOverflowUlong", list(self._ULONG_EFFECT),
                self._profile_region("drink_overflow", "held_drinks", [54, 713, 612, 350]),
            )
            if not (ulong and ulong.hit and getattr(ulong, "best_result", None)) or not self._click_box_center(context, list(ulong.best_result.box), double=False):
                return self._stop_unsupported(context, "drink_overflow", "drink_overflow_ulong_restore_failed")
            time.sleep(self.ACTION_DELAY)
            current_image = self._get_screenshot_or_stop(context, "drink_overflow")
            if current_image is None:
                return True
            current = self._capture_evidence(current_image, "drink_overflow_ulong_restored")
            if not self._remaining_prompt(context, current_image, self._REMAINING_ONE).hit:
                return self._stop_unsupported(context, "drink_overflow", "drink_overflow_ulong_restore_unverified")
        elif not ((remaining := self._remaining_prompt(context, current_image, self._REMAINING_ONE)) and remaining.hit):
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_remaining_count_unsupported")
        black_vinegar = self._run_ocr(
            context, current_image, "ProduceRecognitionHIFDrinkOverflowBlackVinegar", list(self._BLACK_VINEGAR_EFFECT),
            self._profile_region("drink_overflow", "new_drinks", [54, 367, 612, 410]),
        )
        if not (black_vinegar and black_vinegar.hit and getattr(black_vinegar, "best_result", None)):
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_black_vinegar_effect_not_found")
        black_vinegar_box = list(black_vinegar.best_result.box)
        # 奖励项的文字区域本身不可点，右侧复选框与识别文本共享纵向中心。
        checkbox = [600, max(367, black_vinegar_box[1] - 20), 60, black_vinegar_box[3] + 40]
        if not self._click_box_center(context, checkbox, double=False):
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_black_vinegar_click_failed")
        time.sleep(self.ACTION_DELAY)
        selected_image = self._get_screenshot_or_stop(context, "drink_overflow")
        if selected_image is None:
            return True
        selected = self._capture_evidence(selected_image, "drink_overflow_black_vinegar_selected")
        if not frame_changed(current, selected) or not self._remaining_prompt(context, selected_image, self._REMAINING_ZERO).hit:
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_black_vinegar_selection_unverified")
        keep = self._find_text_option(
            context,
            selected_image,
            ("残す",),
            self._observed_button_roi("drink_overflow", "keep", [230, 1116, 260, 84]),
        )
        if not keep:
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_keep_button_not_found")
        if not self._click_box_center(context, list(keep.best_result.box), double=False):
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_keep_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "drink_overflow")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "drink_overflow_after_keep")
        next_screen = self._post_overflow_screen(context, after_image)
        if not frame_changed(selected, after) or next_screen is None:
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_post_keep_not_routable")
        self._record_journal(
            "drink_overflow",
            "resolve_drink_overflow",
            "verified",
            details={"kept": "初星黒酢", "matched_effect": "消費体力を0にする", "next_screen": next_screen},
            before=before,
            after=after,
        )
        return True

    def _commit_preselected_drinks(self, context: Context, image, before: HIFFrameEvidence) -> bool:
        """仅提交已完成的保留集合，要求可见初星黒酢的已校准效果作为双锚点。"""

        current_image = image
        black_vinegar = self._run_ocr(
            context,
            current_image,
            "ProduceRecognitionHIFDrinkOverflowBlackVinegar",
            list(self._BLACK_VINEGAR_EFFECT),
            self._profile_region("drink_overflow", "held_drinks", [54, 713, 612, 350]),
        )
        if not (black_vinegar and black_vinegar.hit and getattr(black_vinegar, "best_result", None)):
            if not self._swipe_with_verification(
                context,
                current_image,
                "drink_overflow",
                "scroll_preselected_drinks_once",
                (360, 1020),
                (360, 780),
                duration=300,
                details={"direction": "up", "max_scrolls": 1, "reason": "reveal_black_vinegar_effect"},
            ):
                return True
            current_image = self._get_screenshot_or_stop(context, "drink_overflow")
            if current_image is None:
                return True
            if not self._matches_screen_profile(context, current_image, "drink_overflow"):
                return self._stop_unsupported(context, "drink_overflow", "drink_overflow_page_lost_after_preselected_scroll")
            remaining = self._remaining_prompt(context, current_image, self._REMAINING_ZERO)
            if not (remaining and remaining.hit):
                return self._stop_unsupported(context, "drink_overflow", "drink_overflow_selection_changed_after_preselected_scroll")
            black_vinegar = self._run_ocr(
                context,
                current_image,
                "ProduceRecognitionHIFDrinkOverflowBlackVinegar",
                list(self._BLACK_VINEGAR_EFFECT),
                self._profile_region("drink_overflow", "held_drinks", [54, 713, 612, 350]),
            )
        if not (black_vinegar and black_vinegar.hit and getattr(black_vinegar, "best_result", None)):
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_preselected_black_vinegar_not_found")
        keep = self._find_text_option(
            context,
            current_image,
            ("残す",),
            self._observed_button_roi("drink_overflow", "keep", [230, 1116, 260, 84]),
        )
        if not keep:
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_keep_button_not_found")
        if not self._click_box_center(context, list(keep.best_result.box), double=False):
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_keep_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "drink_overflow")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "drink_overflow_after_preselected_keep")
        next_screen = self._post_overflow_screen(context, after_image)
        if not frame_changed(before, after) or next_screen is None:
            return self._stop_unsupported(context, "drink_overflow", "drink_overflow_post_keep_not_routable")
        self._record_journal(
            "drink_overflow",
            "resolve_drink_overflow",
            "verified",
            details={"kept": "初星黒酢", "selection_state": "already_complete", "next_screen": next_screen},
            before=before,
            after=after,
        )
        return True

    def _post_overflow_screen(self, context: Context, image) -> str | None:
        """饮料提交后可进入展示层、Round，或回到正式行动页。"""

        for screen_id in ("drink_reward_reveal", "round1", "finals_prepare"):
            if self._matches_screen_profile(context, image, screen_id):
                return screen_id
        return None


@AgentServer.custom_action("ProduceHIFSafeAdvanceAuto")
class ProduceHIFSafeAdvanceAuto(_ProduceHIFActionBase):
    """受限地点击已实测的育成页空白区域，推进无按钮的过渡画面。"""

    SAFE_TARGET = [341, 204, 0, 3]
    MAX_ADVANCES = 4

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        screen_state = str(self._get_action_params(argv).get("source", "unknown_hif_transition"))
        image = self._get_screenshot_or_stop(context, screen_state)
        if image is None:
            return True
        before = self._capture_evidence(image, f"{screen_state}_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                screen_state,
                "safe_advance",
                "observed",
                details={"reason": "page_execution_mode_not_single_step", "mode": mode.value},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "page_execution_mode_not_single_step")

        session = get_runtime_hif_session()
        if session.safe_advance_count >= self.MAX_ADVANCES:
            return self._stop_unsupported(context, screen_state, "safe_advance_limit_reached")
        known_screen = self._detect_screen_profile(context, image)
        if known_screen is not None:
            self._record_journal(
                screen_state,
                "safe_advance",
                "rejected",
                details={"reason": "known_interactive_page", "screen": known_screen},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, f"safe_advance_blocked_by_known_page:{known_screen}")
        if not self._click_box_center(context, self.SAFE_TARGET, double=False):
            return self._stop_unsupported(context, screen_state, "safe_advance_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, screen_state)
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, f"{screen_state}_after")
        if not frame_changed(before, after):
            self._record_journal(
                screen_state,
                "safe_advance",
                "unverified",
                details={"reason": "post_click_frame_unchanged"},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, screen_state, "post_click_frame_unchanged")
        next_screen = self._detect_confirmed_hif_transition(context, after_image)
        if next_screen is None:
            self._record_journal(
                screen_state,
                "safe_advance",
                "unverified",
                details={"reason": "safe_advance_next_page_not_confirmed"},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, screen_state, "safe_advance_next_page_not_confirmed")
        if not session.record_safe_advance(after.fingerprint):
            return self._stop_unsupported(context, screen_state, "safe_advance_frame_cycle")

        self._record_journal(
            screen_state,
            "safe_advance",
            "verified",
            details={"attempt": session.safe_advance_count, "next_screen": next_screen},
            before=before,
            after=after,
        )
        session.reset_safe_advance()
        return True


@AgentServer.custom_action("ProduceHIFFinalsRankingContinueAuto")
class ProduceHIFFinalsRankingContinueAuto(_ProduceHIFActionBase):
    """从本战前当前順位展示页推进，且只接受进入 Round1。"""

    PROMPT_ROI = [245, 1140, 250, 80]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        screen_state = "finals_ranking_transition"
        image = self._get_screenshot_or_stop(context, screen_state)
        if image is None:
            return True
        if not self._matches_screen_profile(context, image, screen_state):
            return self._stop_unsupported(context, screen_state, "finals_ranking_transition_page_not_confirmed")
        return self._click_text_with_verification(
            context,
            image,
            screen_state,
            "continue_finals_ranking",
            ("タップして次へ",),
            self.PROMPT_ROI,
            allowed_next_screens=("round1",),
            postcondition_failure_reason="finals_ranking_round1_not_confirmed",
        )


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
    SCHEDULE_OCR_PATTERNS = ("授業", "公開レッスン", "おでかけ", "差し入れ", "相談")
    LESSON_SLOT_IDS = ("left", "center", "right")
    LESSON_ACCENT_REGION_IDS = {
        "left": "lesson_accent_left",
        "center": "lesson_accent_center",
        "right": "lesson_accent_right",
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
        screen_state = "finals_action_select"
        candidate = event.get("name", "unknown")
        before = self._capture_evidence(image, f"{screen_state}_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                screen_state,
                "select_schedule",
                "observed",
                details={"candidate": candidate, "reason": "page_execution_mode_not_single_step", "mode": mode.value},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "page_execution_mode_not_single_step")
        if not self._click_box_center(context, event["box"], double=False):
            return self._stop_unsupported(context, screen_state, "schedule_first_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_first_image = self._get_screenshot_or_stop(context, screen_state)
        if after_first_image is None:
            return True
        after_first = self._capture_evidence(after_first_image, f"{screen_state}_selected")
        if not frame_changed(before, after_first):
            self._record_journal(
                screen_state,
                "select_schedule",
                "unverified",
                details={"candidate": candidate, "reason": "first_click_frame_unchanged"},
                before=before,
                after=after_first,
            )
            return self._stop_unsupported(context, screen_state, "schedule_first_click_unverified")
        if not self._matches_screen_profile(context, after_first_image, "finals_prepare"):
            next_screen = self._detect_confirmed_hif_transition(context, after_first_image)
            if next_screen is None:
                self._record_journal(
                    screen_state,
                    "select_schedule",
                    "unverified",
                    details={"candidate": candidate, "reason": "schedule_first_click_next_page_not_confirmed"},
                    before=before,
                    after=after_first,
                )
                return self._stop_unsupported(context, screen_state, "schedule_first_click_next_page_not_confirmed")
            self._record_journal(
                screen_state,
                "select_schedule",
                "verified",
                details={"candidate": candidate, "click_count": 1, "transition": "direct", "next_screen": next_screen},
                before=before,
                after=after_first,
            )
            return True

        self._record_journal(
            screen_state,
            "select_schedule",
            "verified",
            details={"candidate": candidate, "click_count": 1, "transition": "selected_on_schedule_page"},
            before=before,
            after=after_first,
        )
        if not self._click_box_center(context, event["box"], double=False):
            return self._stop_unsupported(context, screen_state, "schedule_confirm_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_second_image = self._get_screenshot_or_stop(context, screen_state)
        if after_second_image is None:
            return True
        after_second = self._capture_evidence(after_second_image, f"{screen_state}_confirmed")
        if not frame_changed(after_first, after_second):
            self._record_journal(
                screen_state,
                "confirm_schedule",
                "unverified",
                details={"candidate": candidate, "reason": "second_click_frame_unchanged"},
                before=after_first,
                after=after_second,
            )
            return self._stop_unsupported(context, screen_state, "schedule_confirm_unverified")
        if self._matches_screen_profile(context, after_second_image, "finals_prepare"):
            return self._stop_unsupported(context, screen_state, "schedule_confirm_still_on_schedule_page")

        next_screen = self._detect_confirmed_hif_transition(context, after_second_image)
        if next_screen is None:
            self._record_journal(
                screen_state,
                "confirm_schedule",
                "unverified",
                details={"candidate": candidate, "reason": "schedule_confirm_next_page_not_confirmed"},
                before=after_first,
                after=after_second,
            )
            return self._stop_unsupported(context, screen_state, "schedule_confirm_next_page_not_confirmed")
        self._record_journal(
            screen_state,
            "confirm_schedule",
            "verified",
            details={"candidate": candidate, "click_count": 2, "next_screen": next_screen},
            before=after_first,
            after=after_second,
        )
        return True

    def _get_available_events(self, context: Context, image) -> List[Dict[str, Any]]:
        """读取日程文字；同为“授業”时以已校准的彩色角标区分属性。"""

        profile = load_hif_screen_profiles().get("finals_prepare")
        schedule_roi = list(profile.regions["schedule_candidates"]) if profile else [84, 920, 552, 196]
        ocr_detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFScheduleLabels",
            [f".*{re.escape(token)}.*" for token in self.SCHEDULE_OCR_PATTERNS],
            schedule_roi,
        )
        if ocr_detail and ocr_detail.hit:
            text_events = self._events_from_schedule_ocr(ocr_detail, image, schedule_roi)
            if text_events:
                logger.info(f"HIF 可用日程（OCR）: {', '.join(event['name'] for event in text_events)}")
                return text_events

        # 兼容旧截图：只有 OCR 没有可靠候选时才回退旧模板，绝不降低模板阈值猜测。
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

    def _events_from_schedule_ocr(self, reco_detail, image, schedule_roi: list[int]) -> List[Dict[str, Any]]:
        """把 Maa OCR 的全部候选转换为唯一、可点击的日程条目。"""

        seen: set[tuple[str, tuple[int, int, int, int]]] = set()
        events: List[Dict[str, Any]] = []
        for result in tuple(getattr(reco_detail, "filtered_results", ()) or ()) + tuple(getattr(reco_detail, "all_results", ()) or ()):
            text = str(getattr(result, "text", "")).replace(" ", "")
            try:
                box = tuple(int(value) for value in result.box)
            except (AttributeError, TypeError, ValueError):
                continue
            if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
                continue
            key = (text, box)
            if key in seen:
                continue
            seen.add(key)
            if "公開レッスン" in text:
                category = self._public_lesson_category_from_text(text)
                if category is None:
                    return []
                events.append({"name": category, "category": category, "box": list(box), "source": "ocr_public_lesson"})
            elif "おでかけ" in text:
                events.append({"name": "おでかけ", "category": "go_out", "box": list(box), "source": "ocr"})
            elif "差し入れ" in text:
                events.append({"name": "活动", "category": "gift", "box": list(box), "source": "ocr"})
            elif "相談" in text:
                events.append({"name": "相談", "category": "consult", "box": list(box), "source": "ocr"})
            elif "授業" in text:
                category = self._lesson_category_from_accent(image, box, schedule_roi)
                if category is None:
                    return []
                events.append({"name": category, "category": category, "box": list(box), "source": "ocr_accent"})

        categories = [str(event["category"]) for event in events]
        if not events or len(categories) != len(set(categories)):
            return []
        return events

    @staticmethod
    def _public_lesson_category_from_text(text: str) -> str | None:
        """公开课卡面已含属性前缀，必须精确读出 Vo/Da/Vi 后才允许路由。"""

        normalized = text.replace(" ", "")
        for category in ("Vo", "Da", "Vi"):
            if re.search(rf"(?:^|[^A-Za-z]){category}(?:\.|[^A-Za-z]|$)", normalized):
                return category
        return None

    def _lesson_category_from_accent(self, image, box: tuple[int, int, int, int], schedule_roi: list[int]) -> str | None:
        """按 OCR 标签所在列读取彩色角标；颜色不唯一或截图不合约时拒绝选择。"""

        shape = getattr(image, "shape", None)
        if not isinstance(shape, tuple) or len(shape) < 3 or shape[2] < 3:
            return None
        center_x = box[0] + box[2] // 2
        schedule_x, _, schedule_width, _ = schedule_roi
        if not (schedule_x <= center_x < schedule_x + schedule_width):
            return None
        slot_index = min(len(self.LESSON_SLOT_IDS) - 1, (center_x - schedule_x) * len(self.LESSON_SLOT_IDS) // schedule_width)
        slot_id = self.LESSON_SLOT_IDS[slot_index]
        profile = load_hif_screen_profiles().get("finals_prepare")
        accent_id = self.LESSON_ACCENT_REGION_IDS[slot_id]
        accent_roi = profile.regions.get(accent_id) if profile else None
        if accent_roi is None:
            return None
        x, y, width, height = accent_roi
        if x < 0 or y < 0 or x + width > shape[1] or y + height > shape[0]:
            return None

        counts = {"Vo": 0, "Da": 0, "Vi": 0}
        pixels = image[y : y + height, x : x + width]
        try:
            flat_pixels = pixels.reshape(-1, pixels.shape[-1])
        except (AttributeError, TypeError, ValueError):
            return None
        for pixel in flat_pixels:
            try:
                blue, green, red = (int(pixel[index]) for index in range(3))
            except (IndexError, TypeError, ValueError):
                return None
            if red > 180 and green < 150 and red - green > 70 and red - blue > 40:
                counts["Vo"] += 1
            if blue > 160 and red < 100 and blue - green > 50:
                counts["Da"] += 1
            if red > 180 and green > 100 and blue < 120 and green - blue > 70:
                counts["Vi"] += 1

        total = len(flat_pixels)
        if total <= 0:
            return None
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        best, next_best = ranked[0], ranked[1]
        if best[1] < total * 0.25 or best[1] == next_best[1]:
            return None
        return best[0]


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
    """先预览授業候选，只有完整命中好调变卡效果才二次确认。"""

    OPTION_ROI = [40, 620, 640, 360]
    PREVIEW_ROI = [52, 434, 616, 205]
    GOOD_CONDITION_OPTIONS = ("余裕です！", "長い道のりでした")
    PREVIEW_ATTRIBUTE_TOKENS = ("ボーカル上昇", "ダンス上昇", "ビジュアル上昇")
    PREVIEW_REQUIRED_TOKENS = ("180", "トラブルカード以外", "好調関係", "セレクトチェンジ")
    GENERIC_ROW_REGION_IDS = ("option_top", "option_middle", "option_bottom")
    RESULT_ADVANCE_TARGET = [341, 204, 0, 3]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if "good_condition" not in preset.class_option_priority:
            return self._stop_unsupported(context, "hif_class_options", "preset_no_class_option_policy")

        image = self._get_screenshot_or_stop(context, "hif_class_options")
        if image is None:
            return True
        before = self._capture_evidence(image, "hif_class_options_before")
        if not self._matches_screen_profile(context, image, "class_options"):
            if self._is_class_result_transition(context, image):
                return self._click_box_with_verification(
                    context,
                    image,
                    "hif_class_result",
                    "advance_class_result",
                    self.RESULT_ADVANCE_TARGET,
                    click_failure_reason="class_result_advance_failed",
                )
            return self._stop_unsupported(context, "hif_class_options", "class_options_page_not_confirmed")

        candidate, visible_options = self._find_class_option_candidate(context, image)
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                "hif_class_options",
                "observe_class_options",
                "observed",
                details={"mode": mode.value, "visible_options": visible_options},
                before=before,
            )
            return self._stop_unsupported(context, "hif_class_options", "page_execution_mode_not_single_step")
        if candidate is None:
            self._record_journal(
                "hif_class_options",
                "observe_unrecognized_class_options",
                "rejected",
                details={"reason": "good_condition_option_not_found", "visible_options": visible_options},
                before=before,
            )
            return self._stop_unsupported(context, "hif_class_options", "good_condition_option_not_found")

        # 任务可能在首击预览后中断。此时不能再把确认点击误当成一次新的预览；
        # 先验证现有详情，再只点击一次并要求进入变卡目标页。
        existing_preview_texts = self._read_class_preview_texts(context, image)
        if self._is_good_condition_change_preview(existing_preview_texts):
            self._record_journal(
                "hif_class_options",
                "resume_class_option_preview",
                "verified",
                details={"candidate": candidate, "preview_texts": existing_preview_texts},
                before=before,
            )
            return self._confirm_class_option(context, image, before, candidate)

        if not self._click_box_center(context, candidate["box"], double=False):
            return self._stop_unsupported(context, "hif_class_options", "class_option_preview_click_failed")
        time.sleep(self.ACTION_DELAY)
        preview_image = self._get_screenshot_or_stop(context, "hif_class_options")
        if preview_image is None:
            return True
        preview = self._capture_evidence(preview_image, "hif_class_options_preview")
        if not frame_changed(before, preview):
            self._record_journal(
                "hif_class_options",
                "preview_class_option",
                "unverified",
                details={"candidate": candidate, "reason": "preview_frame_unchanged"},
                before=before,
                after=preview,
            )
            return self._stop_unsupported(context, "hif_class_options", "class_option_preview_frame_unchanged")
        if not self._matches_screen_profile(context, preview_image, "class_options"):
            return self._stop_unsupported(context, "hif_class_options", "class_option_preview_page_lost")

        preview_texts = self._read_class_preview_texts(context, preview_image)
        if not self._is_good_condition_change_preview(preview_texts):
            self._record_journal(
                "hif_class_options",
                "preview_class_option",
                "rejected",
                details={
                    "candidate": candidate,
                    "reason": "good_condition_preview_not_confirmed",
                    "preview_texts": preview_texts,
                    "required_tokens": self.PREVIEW_REQUIRED_TOKENS,
                },
                before=before,
                after=preview,
            )
            return self._stop_unsupported(context, "hif_class_options", "good_condition_preview_not_confirmed")
        self._record_journal(
            "hif_class_options",
            "preview_class_option",
            "verified",
            details={"candidate": candidate, "preview_texts": preview_texts},
            before=before,
            after=preview,
        )

        return self._confirm_class_option(context, preview_image, preview, candidate)

    def _confirm_class_option(self, context: Context, image, before: HIFFrameEvidence, candidate: dict[str, Any]) -> bool:
        """确认已验证的课程预览，并以变卡目标页作为唯一后验。"""

        if not self._click_box_center(context, candidate["box"], double=False):
            return self._stop_unsupported(context, "hif_class_options", "class_option_confirm_click_failed")
        time.sleep(self.ACTION_DELAY)
        confirmed_image = self._get_screenshot_or_stop(context, "hif_class_options")
        if confirmed_image is None:
            return True
        confirmed = self._capture_evidence(confirmed_image, "hif_class_options_confirmed")
        if not frame_changed(before, confirmed):
            self._record_journal(
                "hif_class_options",
                "confirm_class_option",
                "unverified",
                details={"candidate": candidate, "reason": "confirm_frame_unchanged"},
                before=before,
                after=confirmed,
            )
            return self._stop_unsupported(context, "hif_class_options", "class_option_confirm_frame_unchanged")
        if self._matches_screen_profile(context, confirmed_image, "class_options"):
            return self._stop_unsupported(context, "hif_class_options", "class_option_confirm_still_visible")
        if self._matches_screen_profile(context, confirmed_image, "select_change_target"):
            self._record_journal(
                "hif_class_options",
                "confirm_class_option",
                "verified",
                details={"candidate": candidate, "next_screen": "select_change_target"},
                before=before,
                after=confirmed,
            )
            return True
        if self._is_class_result_transition(context, confirmed_image):
            self._record_journal(
                "hif_class_options",
                "confirm_class_option",
                "verified",
                details={"candidate": candidate, "next_screen": "class_result_transition"},
                before=before,
                after=confirmed,
            )
            return True
        return self._stop_unsupported(context, "hif_class_options", "class_option_confirm_target_page_not_confirmed")

    def _is_class_result_transition(self, context: Context, image) -> bool:
        """课程确认后会先显示结算对白；此页仍有“授業”标题但已无选项区。"""

        title = self._find_text_option(
            context,
            image,
            ("授業",),
            self._profile_region("class_options", "title", [32, 36, 160, 105]),
        )
        return bool(title) and not self._matches_screen_profile(context, image, "class_options")

    def _find_class_option_candidate(self, context: Context, image) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
        """优先保留旧文案兼容；否则只允许预览结构完整的顶部候选。"""

        options_roi = self._profile_region("class_options", "options", self.OPTION_ROI)
        reco_detail = self._find_text_option(context, image, self.GOOD_CONDITION_OPTIONS, options_roi)
        if reco_detail and reco_detail.hit:
            text = str(reco_detail.best_result.text)
            return {"name": text, "box": list(reco_detail.best_result.box), "source": "known_text"}, (text,)

        evidence = self._run_ocr(context, image, "ProduceRecognitionHIFClassOptionEvidence", [], options_roi)
        entries = self._ocr_entries(evidence)
        visible_options = tuple(entry["text"] for entry in entries)
        if not any("トラブル追加" in entry["text"] for entry in entries):
            return None, visible_options

        profile = load_hif_screen_profiles().get("class_options")
        if profile is None:
            return None, visible_options
        rows: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if entry["score"] < 0.8 or len(entry["text"]) < 4 or "トラブル追加" in entry["text"]:
                continue
            x, y, width, height = entry["box"]
            center_x = x + width // 2
            center_y = y + height // 2
            for index, region_id in enumerate(self.GENERIC_ROW_REGION_IDS):
                row = profile.regions.get(region_id)
                if row is None:
                    return None, visible_options
                row_x, row_y, row_width, row_height = row
                if row_x <= center_x < row_x + row_width and row_y <= center_y < row_y + row_height:
                    previous = rows.get(region_id)
                    if previous is None or (entry["score"], len(entry["text"])) > (previous["score"], len(previous["text"])):
                        rows[region_id] = entry
                    break
        if set(rows) != set(self.GENERIC_ROW_REGION_IDS):
            return None, visible_options
        top = rows["option_top"]
        return {"name": top["text"], "box": list(top["box"]), "source": "top_option_preview"}, visible_options

    def _read_class_preview_texts(self, context: Context, image) -> tuple[str, ...]:
        detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFClassPreviewEvidence",
            [],
            self._profile_region("class_options", "preview", self.PREVIEW_ROI),
        )
        entries = self._ocr_entries(detail)
        return tuple(entry["text"] for entry in entries)

    @staticmethod
    def _is_good_condition_change_preview(texts: tuple[str, ...]) -> bool:
        normalized = "".join(text.replace(" ", "") for text in texts)
        return any(token in normalized for token in ProduceChooseHIFClassOptionAuto.PREVIEW_ATTRIBUTE_TOKENS) and all(
            token in normalized for token in ProduceChooseHIFClassOptionAuto.PREVIEW_REQUIRED_TOKENS
        )

    @staticmethod
    def _ocr_entries(reco_detail) -> tuple[dict[str, Any], ...]:
        """保留 OCR 的文本、置信度和位置，并稳定排序以重建多行预览。"""

        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, tuple[int, int, int, int]]] = set()
        for result in tuple(getattr(reco_detail, "filtered_results", ()) or ()) + tuple(getattr(reco_detail, "all_results", ()) or ()):
            text = str(getattr(result, "text", "")).strip()
            try:
                box = tuple(int(value) for value in result.box)
            except (AttributeError, TypeError, ValueError):
                continue
            if not text or len(box) != 4 or box[2] <= 0 or box[3] <= 0:
                continue
            key = (text, box)
            if key in seen:
                continue
            seen.add(key)
            raw_score = getattr(result, "score", 0.0)
            score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
            entries.append({"text": text, "box": box, "score": score})
        return tuple(sorted(entries, key=lambda entry: (entry["box"][1], entry["box"][0])))


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
    """逐槽读取 P 饮料详情，只领取唯一评分最高的已知候选。"""

    SLOT_REGION_IDS = ("candidate_left", "candidate_center", "candidate_right")
    SLOT_FALLBACKS = ([158, 822, 127, 127], [297, 822, 127, 127], [436, 822, 127, 127])
    DETAILS_FALLBACK = [118, 506, 500, 230]
    RECEIVE_FALLBACK = [230, 1052, 260, 84]

    def _slot_boxes(self) -> tuple[tuple[str, list[int]], ...]:
        profile = load_hif_screen_profiles().get("drink_reward")
        return tuple(
            (
                region_id,
                list(profile.regions[region_id]) if profile and region_id in profile.regions else list(fallback),
            )
            for region_id, fallback in zip(self.SLOT_REGION_IDS, self.SLOT_FALLBACKS)
        )

    def _read_drink_details(self, context: Context, image) -> dict[str, Any] | None:
        planner = HIFRoutePlanner()
        profile = load_hif_screen_profiles().get("drink_reward")
        details_roi = list(profile.regions["details"]) if profile and "details" in profile.regions else self.DETAILS_FALLBACK
        reco_detail = self._find_text_option(context, image, planner.catalog.drink_names, details_roi)
        if not reco_detail:
            return None
        recognized_text = reco_detail.best_result.text
        name = next((candidate for candidate in planner.catalog.drink_names if candidate in recognized_text), None)
        if name is None:
            return None
        raw_confidence = getattr(reco_detail.best_result, "score", 1.0)
        confidence = float(raw_confidence) if isinstance(raw_confidence, (int, float)) else 1.0
        return {
            "name": name,
            "effect": planner.catalog.drinks[name].effect_text,
            "confidence": confidence,
            "ocr_text": recognized_text,
        }

    def _has_receive_button(self, context: Context, image) -> bool:
        return bool(
            self._find_text_option(
                context,
                image,
                ("受け取る",),
                self._observed_button_roi("drink_reward", "receive", self.RECEIVE_FALLBACK),
            )
        )

    def _is_drink_reward_page(self, context: Context, image, candidate: dict[str, Any] | None = None) -> bool:
        """未选中态用提示确认；已选中态用已知详情与领取按钮确认。"""

        if self._matches_profile_anchors(context, image, "drink_reward"):
            return True
        return candidate is not None and self._has_receive_button(context, image)

    def _select_and_read_slot(self, context: Context, image, slot: str, box: list[int], event: str):
        before = self._capture_evidence(image, f"hif_drink_reward_{slot}_before")
        if not self._click_box_center(context, box, double=False):
            self._stop_unsupported(context, "hif_drink_reward", "drink_slot_click_failed")
            return None
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "hif_drink_reward")
        if after_image is None:
            return None
        after = self._capture_evidence(after_image, f"hif_drink_reward_{slot}_after")
        if not frame_changed(before, after):
            candidate = self._read_drink_details(context, image)
            if candidate is not None and self._is_drink_reward_page(context, image, candidate):
                candidate["slot"] = slot
                self._record_journal(
                    "hif_drink_reward",
                    event,
                    "observed",
                    details={**candidate, "selection_already_active": True},
                    before=before,
                )
                return candidate, image
            self._record_journal(
                "hif_drink_reward",
                event,
                "unverified",
                details={"slot": slot, "reason": "slot_selection_frame_unchanged"},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, "hif_drink_reward", "drink_slot_selection_unverified")
            return None
        candidate = self._read_drink_details(context, after_image)
        if candidate is None:
            self._stop_unsupported(context, "hif_drink_reward", "drink_detail_name_unreadable")
            return None
        if not self._is_drink_reward_page(context, after_image, candidate):
            self._stop_unsupported(context, "hif_drink_reward", "drink_reward_page_lost_after_slot_selection")
            return None
        candidate["slot"] = slot
        self._record_journal(
            "hif_drink_reward",
            event,
            "verified",
            details=candidate,
            before=before,
            after=after,
        )
        return candidate, after_image

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        image = self._get_screenshot_or_stop(context, "hif_drink_reward")
        if image is None:
            return True
        before = self._capture_evidence(image, "hif_drink_reward_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                "hif_drink_reward",
                "enumerate_drink_candidates",
                "observed",
                details={"reason": "page_execution_mode_not_single_step", "mode": mode.value},
                before=before,
            )
            return self._stop_unsupported(context, "hif_drink_reward", "page_execution_mode_not_single_step")
        initial_candidate = self._read_drink_details(context, image)
        if not self._is_drink_reward_page(context, image, initial_candidate):
            return self._stop_unsupported(context, "hif_drink_reward", "drink_reward_page_not_confirmed")

        observed: list[dict[str, Any]] = []
        current_image = image
        for slot, box in self._slot_boxes():
            selected = self._select_and_read_slot(context, current_image, slot, box, "enumerate_drink_candidate")
            if selected is None:
                return True
            candidate, current_image = selected
            observed.append(candidate)

        planner = HIFRoutePlanner()
        decision = planner.choose_observed_reward("drink", (item["name"] for item in observed), preset)
        if decision.should_stop:
            self._record_journal(
                "hif_drink_reward",
                "choose_drink_reward",
                "rejected",
                details={"reason": decision.stop_reason, "candidates": observed, "unknown_factors": decision.unknown_factors},
            )
            return self._stop_unsupported(context, "hif_drink_reward", decision.stop_reason or "drink_decision_unavailable")
        target = next((item for item in observed if item["name"] == decision.candidate_id), None)
        if target is None:
            return self._stop_unsupported(context, "hif_drink_reward", "chosen_drink_not_in_observed_candidates")

        last_slot = observed[-1]["slot"]
        if target["slot"] != last_slot:
            target_box = next(box for slot, box in self._slot_boxes() if slot == target["slot"])
            selected = self._select_and_read_slot(context, current_image, target["slot"], target_box, "select_drink_reward")
            if selected is None:
                return True
            confirmed_target, _ = selected
            if confirmed_target["name"] != target["name"]:
                return self._stop_unsupported(context, "hif_drink_reward", "selected_drink_name_changed")

        get_runtime_hif_session().set_pending_reward("drink", target["name"], target["slot"])
        self._record_journal(
            "hif_drink_reward",
            "choose_drink_reward",
            "selected",
            details={"target": target, "reasons": decision.reasons, "confidence": decision.confidence, "candidates": observed},
        )
        return True


@AgentServer.custom_action("ProduceHIFDrinkRewardRevealAuto")
class ProduceHIFDrinkRewardRevealAuto(_ProduceHIFActionBase):
    """等待已验证的饮料展示动画自行结束，不重复点击瞬态控件。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "hif_drink_reward_reveal")
        if image is None:
            return True
        before = self._capture_evidence(image, "hif_drink_reward_reveal_before")
        reveal_match = detect_drink_reward_reveal_page(context, image)
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                "hif_drink_reward_reveal",
                "wait_revealed_drink_reward",
                "observed",
                details={
                    "reason": "page_execution_mode_not_single_step",
                    "mode": mode.value,
                    "reward": reveal_match.name if reveal_match else None,
                },
                before=before,
            )
            return self._stop_unsupported(context, "hif_drink_reward_reveal", "page_execution_mode_not_single_step")
        if reveal_match is None or reveal_match.name is None:
            self._record_journal(
                "hif_drink_reward_reveal",
                "wait_revealed_drink_reward",
                "observed",
                details={"reason": "reveal_transition_already_started"},
                before=before,
            )
            return True
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "hif_drink_reward_reveal")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "hif_drink_reward_reveal_after")
        if not frame_changed(before, after):
            self._record_journal(
                "hif_drink_reward_reveal",
                "wait_revealed_drink_reward",
                "unverified",
                details={"reason": "reveal_animation_frame_unchanged", "reward": reveal_match.name},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "hif_drink_reward_reveal", "reveal_animation_frame_unchanged")
        if detect_drink_reward_reveal_page(context, after_image) is not None:
            return self._stop_unsupported(context, "hif_drink_reward_reveal", "reveal_animation_still_visible")
        next_screen = self._detect_confirmed_hif_transition(context, after_image)
        if next_screen is None:
            self._record_journal(
                "hif_drink_reward_reveal",
                "wait_revealed_drink_reward",
                "unverified",
                details={"reason": "reveal_next_page_not_confirmed", "reward": reveal_match.name},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "hif_drink_reward_reveal", "reveal_next_page_not_confirmed")
        self._record_journal(
            "hif_drink_reward_reveal",
            "wait_revealed_drink_reward",
            "verified",
            details={"reward": reveal_match.name, "next_screen": next_screen},
            before=before,
            after=after,
        )
        return True


@AgentServer.custom_action("ProduceChooseHIFSkillRewardAuto")
class ProduceChooseHIFSkillRewardAuto(_ProduceHIFRewardChoiceAction):
    """技能卡奖励页默认只读停点；显式探针仅临时选中候选读取详情。"""

    SLOT_REGION_IDS = ("candidate_left", "candidate_center", "candidate_right")
    SLOT_FALLBACKS = ([158, 821, 127, 128], [297, 821, 127, 128], [436, 821, 127, 128])
    DETAIL_NAME_FALLBACK = [118, 500, 500, 60]
    DETAIL_TEXT_FALLBACK = [118, 555, 490, 185]

    @staticmethod
    def _normalized_effect_text(candidate: dict[str, Any]) -> str:
        effect_text = candidate.get("effect_text")
        return "".join(effect_text.split()) if isinstance(effect_text, str) else ""

    def _slot_boxes(self) -> tuple[tuple[str, list[int]], ...]:
        profile = load_hif_screen_profiles().get("skill_reward")
        return tuple(
            (
                region_id,
                list(profile.regions[region_id]) if profile and region_id in profile.regions else list(fallback),
            )
            for region_id, fallback in zip(self.SLOT_REGION_IDS, self.SLOT_FALLBACKS)
        )

    def _read_skill_reward_detail(self, context: Context, image) -> dict[str, Any] | None:
        catalog = load_hif_catalog()
        known_names = tuple(catalog.skill_names)
        name_detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSkillRewardCandidateName",
            [f".*{re.escape(name)}.*" for name in known_names],
            self._profile_region("skill_reward", "detail_name", self.DETAIL_NAME_FALLBACK),
        )
        detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSkillRewardCandidateDetail",
            [],
            self._profile_region("skill_reward", "details", self.DETAIL_TEXT_FALLBACK),
        )
        name_entries = self._ocr_text_entries(name_detail)
        detail_entries = self._ocr_text_entries(detail)
        raw_name = "".join(entry["text"] for entry in name_entries)
        matched_name = next((name for name in known_names if name in raw_name), None)
        effect_text = "\n".join(entry["text"] for entry in detail_entries)
        if matched_name is None or not effect_text:
            return None
        return {
            "name": matched_name,
            "name_texts": tuple(entry["text"] for entry in name_entries),
            "effect_text": effect_text,
            "confidence": max((entry["score"] for entry in name_entries + detail_entries), default=0.0),
            "name_confidence": max((entry["score"] for entry in name_entries), default=0.0),
            "detail_confidence": max((entry["score"] for entry in detail_entries), default=0.0),
        }

    def _select_and_read_skill_slot(
        self, context: Context, image, slot: str, box: list[int]
    ) -> tuple[dict[str, Any], Any] | None:
        before = self._capture_evidence(image, f"skill_reward_{slot}_before")
        if not self._click_box_center(context, box, double=False):
            self._stop_unsupported(context, "hif_skill_reward", "skill_reward_candidate_slot_click_failed")
            return None
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "hif_skill_reward")
        if after_image is None:
            return None
        after = self._capture_evidence(after_image, f"skill_reward_{slot}_after")
        if not frame_changed(before, after):
            self._record_journal(
                "hif_skill_reward",
                "probe_skill_reward_candidate",
                "unverified",
                details={"slot": slot, "reason": "skill_reward_slot_selection_frame_unchanged"},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, "hif_skill_reward", "skill_reward_slot_selection_unverified")
            return None
        if not self._matches_screen_profile(context, after_image, "skill_reward"):
            self._stop_unsupported(context, "hif_skill_reward", "skill_reward_page_lost_after_slot_selection")
            return None
        candidate = self._read_skill_reward_detail(context, after_image)
        if candidate is None:
            self._stop_unsupported(context, "hif_skill_reward", "skill_reward_candidate_detail_unreadable")
            return None
        candidate["slot"] = slot
        self._record_journal(
            "hif_skill_reward",
            "probe_skill_reward_candidate",
            "observed",
            details=candidate,
            before=before,
            after=after,
        )
        return candidate, after_image

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        params = self._get_action_params(argv)
        image = self._get_screenshot_or_stop(context, "hif_skill_reward")
        if image is None:
            return True
        before = self._capture_evidence(image, "hif_skill_reward_before")
        if not self._matches_screen_profile(context, image, "skill_reward"):
            return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_page_not_confirmed")
        session = get_runtime_hif_session()
        pending = session.pending_reward
        received_drink = pending.name if pending is not None and pending.kind == "drink" else None
        if received_drink is not None:
            session.clear_pending_reward()
        skill_reward_probe = params.get("skill_reward_probe")
        if skill_reward_probe in {"enumerate_candidates", "decide_candidates", "receive_selected"}:
            if mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_probe_requires_single_step")
            if skill_reward_probe == "receive_selected" and params.get("skill_reward_receive_authorized") is not True:
                return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_receipt_not_authorized")
            current_image = image
            candidates: list[dict[str, Any]] = []
            slots = self._slot_boxes()
            initial_slot = str(params.get("skill_reward_initial_slot", "")).strip()
            if initial_slot:
                known_slots = {slot for slot, _ in slots}
                if initial_slot not in known_slots:
                    return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_initial_slot_invalid")
                if detect_skill_reward_selected_page(context, current_image) is None:
                    return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_initial_slot_not_selected")
                candidate = self._read_skill_reward_detail(context, current_image)
                if candidate is None:
                    return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_initial_detail_unreadable")
                candidate["slot"] = initial_slot
                candidate["selection_already_active"] = True
                candidates.append(candidate)
                self._record_journal(
                    "hif_skill_reward",
                    "probe_skill_reward_candidate",
                    "observed",
                    details=candidate,
                )
                slots = tuple((slot, box) for slot, box in slots if slot != initial_slot)
            for slot, box in slots:
                selected = self._select_and_read_skill_slot(context, current_image, slot, box)
                if selected is None:
                    return True
                candidate, current_image = selected
                candidates.append(candidate)
            self._record_journal(
                "hif_skill_reward",
                "enumerate_skill_reward_candidates",
                "observed",
                details={"candidates": candidates, "received_drink": received_drink, "mode": mode.value},
            )
            if skill_reward_probe in {"decide_candidates", "receive_selected"}:
                planner = HIFRoutePlanner()
                preset = self._get_preset(argv)
                decision = planner.choose_observed_skill_reward(candidates, preset)
                if decision.should_stop:
                    self._record_journal(
                        "hif_skill_reward",
                        "decide_skill_reward",
                        "rejected",
                        details={
                            "reason": decision.stop_reason,
                            "candidates": candidates,
                            "unknown_factors": decision.unknown_factors,
                        },
                    )
                    return self._stop_unsupported(context, "hif_skill_reward", decision.stop_reason or "skill_reward_decision_unavailable")
                if skill_reward_probe == "receive_selected":
                    target = next((candidate for candidate in candidates if candidate["name"] == decision.candidate_id), None)
                    if target is None:
                        return self._stop_unsupported(context, "hif_skill_reward", "chosen_skill_not_in_observed_candidates")
                    target_box = next((box for slot, box in self._slot_boxes() if slot == target["slot"]), None)
                    if target_box is None:
                        return self._stop_unsupported(context, "hif_skill_reward", "chosen_skill_slot_not_found")
                    selected = self._select_and_read_skill_slot(context, current_image, target["slot"], target_box)
                    if selected is None:
                        return True
                    confirmed_target, _ = selected
                    if (
                        confirmed_target["name"] != target["name"]
                        or self._normalized_effect_text(confirmed_target) != self._normalized_effect_text(target)
                    ):
                        return self._stop_unsupported(context, "hif_skill_reward", "selected_skill_detail_changed")
                    rechecked_candidates = [
                        confirmed_target if candidate["slot"] == target["slot"] else candidate for candidate in candidates
                    ]
                    rechecked_decision = planner.choose_observed_skill_reward(rechecked_candidates, preset)
                    if rechecked_decision.should_stop or rechecked_decision.candidate_id != target["name"]:
                        return self._stop_unsupported(
                            context,
                            "hif_skill_reward",
                            rechecked_decision.stop_reason or "selected_skill_decision_changed",
                        )
                    session.set_pending_reward("skill", target["name"], target["slot"])
                    self._record_journal(
                        "hif_skill_reward",
                        "prepare_skill_reward_receipt",
                        "selected",
                        details={
                            "target": confirmed_target,
                            "confidence": rechecked_decision.confidence,
                            "reasons": rechecked_decision.reasons,
                            "candidates": rechecked_candidates,
                        },
                    )
                    return True
                self._record_journal(
                    "hif_skill_reward",
                    "decide_skill_reward",
                    "selected",
                    details={
                        "target": decision.candidate_id,
                        "confidence": decision.confidence,
                        "reasons": decision.reasons,
                        "candidates": candidates,
                        "next_action": "no_click_pending_receipt_implementation",
                    },
                )
                return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_decision_recorded_stop")
            return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_probe_complete_stop")
        self._record_journal(
            "hif_skill_reward",
            "observe_skill_reward",
            "observed",
            details={
                "reason": "skill_reward_selection_not_enabled",
                "mode": mode.value,
                "received_drink": received_drink,
            },
            before=before,
        )
        return self._stop_unsupported(context, "hif_skill_reward", "skill_reward_selection_not_enabled")


@AgentServer.custom_action("ProduceChooseHIFSelectChangeTargetAuto")
class ProduceChooseHIFSelectChangeTargetAuto(_ProduceHIFRewardChoiceAction):
    """逐槽读取变卡目标详情；仅在命中预设目标后进入牌库选择。"""

    SLOT_REGION_IDS = ("candidate_left", "candidate_center", "candidate_right")
    SLOT_FALLBACKS = ([158, 837, 127, 128], [297, 837, 127, 128], [436, 837, 127, 128])
    DETAIL_NAME_FALLBACK = [180, 500, 360, 60]
    NEXT_ROI = [230, 1052, 260, 84]
    REROLL_ROI = [555, 1072, 112, 58]
    REROLL_COUNT_ROI = [559, 1042, 102, 40]

    def _slot_boxes(self) -> tuple[tuple[str, list[int]], ...]:
        profile = load_hif_screen_profiles().get("select_change_target")
        return tuple(
            (
                region_id,
                list(profile.regions[region_id]) if profile and region_id in profile.regions else list(fallback),
            )
            for region_id, fallback in zip(self.SLOT_REGION_IDS, self.SLOT_FALLBACKS)
        )

    def _detail_name_roi(self) -> list[int]:
        return self._profile_region("select_change_target", "detail_name", self.DETAIL_NAME_FALLBACK)

    def _read_target_details(self, context: Context, image, target_names: tuple[str, ...]) -> dict[str, Any] | None:
        detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectChangeTargetDetails",
            [],
            self._detail_name_roi(),
        )
        entries = self._ocr_text_entries(detail)
        texts = tuple(entry["text"] for entry in entries)
        raw_text = "".join(texts)
        if not raw_text:
            return None
        target_name = next((name for name in target_names if name in raw_text), None)
        return {
            "name": target_name or raw_text,
            "target_name": target_name,
            "ocr_texts": texts,
            "confidence": max((entry["score"] for entry in entries), default=0.0),
        }

    def _select_and_read_slot(
        self,
        context: Context,
        image,
        slot: str,
        box: list[int],
        target_names: tuple[str, ...],
        event: str,
    ) -> tuple[dict[str, Any], Any] | None:
        before = self._capture_evidence(image, f"select_change_target_{slot}_before")
        if not self._click_box_center(context, box, double=False):
            self._stop_unsupported(context, "select_change_target", "target_slot_click_failed")
            return None
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "select_change_target")
        if after_image is None:
            return None
        after = self._capture_evidence(after_image, f"select_change_target_{slot}_after")
        if not frame_changed(before, after):
            self._record_journal(
                "select_change_target",
                event,
                "unverified",
                details={"slot": slot, "reason": "slot_selection_frame_unchanged"},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, "select_change_target", "target_slot_selection_unverified")
            return None
        if not self._matches_screen_profile(context, after_image, "select_change_target"):
            self._stop_unsupported(context, "select_change_target", "target_page_lost_after_slot_selection")
            return None
        candidate = self._read_target_details(context, after_image, target_names)
        if candidate is None:
            self._stop_unsupported(context, "select_change_target", "target_detail_name_unreadable")
            return None
        candidate["slot"] = slot
        self._record_journal(
            "select_change_target",
            event,
            "verified",
            details=candidate,
            before=before,
            after=after,
        )
        return candidate, after_image

    def _read_reroll_count(self, context: Context, image) -> int | None:
        detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectChangeRerollCount",
            [],
            self._profile_region("select_change_target", "reroll_count", self.REROLL_COUNT_ROI),
        )
        text = "".join(entry["text"] for entry in self._ocr_text_entries(detail))
        match = re.search(r"(\d+)", text)
        return int(match.group(1)) if match else None

    def _reroll_targets(self, context: Context, image, attempt: int) -> Any | None:
        before_count = self._read_reroll_count(context, image)
        if before_count is None:
            # 从中断恢复时没有本轮内存的重抽次数。若次数和按钮同时消失，
            # 这是游戏在次数耗尽后的稳定终态，直接以“无可用重抽”安全停止。
            unavailable = self._find_text_option(
                context,
                image,
                ("再抽選",),
                self._observed_button_roi("select_change_target", "reroll", self.REROLL_ROI),
            )
            if not unavailable:
                self._record_journal(
                    "select_change_target",
                    "reroll_target",
                    "rejected",
                    details={"attempt": attempt, "reason": "reroll_controls_hidden_after_exhaustion"},
                )
                return self._stop_unsupported(context, "select_change_target", "reroll_unavailable_after_target_enumeration")
            return self._stop_unsupported(context, "select_change_target", "reroll_count_unreadable")
        if before_count <= 0:
            self._stop_unsupported(context, "select_change_target", "reroll_count_unreadable_or_exhausted")
            return None
        reroll = self._find_text_option(
            context,
            image,
            ("再抽選",),
            self._observed_button_roi("select_change_target", "reroll", self.REROLL_ROI),
        )
        if not reroll:
            self._stop_unsupported(context, "select_change_target", "reroll_button_not_found")
            return None
        before = self._capture_evidence(image, "select_change_target_reroll_before")
        if not self._click_box_center(context, reroll.best_result.box, double=False):
            self._stop_unsupported(context, "select_change_target", "reroll_click_failed")
            return None
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "select_change_target")
        if after_image is None:
            return None
        after = self._capture_evidence(after_image, "select_change_target_reroll_after")
        if not frame_changed(before, after):
            self._record_journal(
                "select_change_target",
                "reroll_target",
                "unverified",
                details={"attempt": attempt, "reason": "reroll_frame_unchanged"},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, "select_change_target", "reroll_frame_unchanged")
            return None
        if not self._matches_screen_profile(context, after_image, "select_change_target"):
            self._stop_unsupported(context, "select_change_target", "target_page_lost_after_reroll")
            return None
        after_count = self._read_reroll_count(context, after_image)
        # 最后一次重抽会直接隐藏次数和“再抽選”控件。只有重抽前已确认剩 1 次，
        # 且重抽后按钮也确实消失时，才把缺失次数解释为 0；其他 OCR 缺失仍必须停止。
        exhausted_by_hidden_controls = False
        if after_count is None and before_count == 1:
            after_reroll = self._find_text_option(
                context,
                after_image,
                ("再抽選",),
                self._observed_button_roi("select_change_target", "reroll", self.REROLL_ROI),
            )
            if not after_reroll:
                after_count = 0
                exhausted_by_hidden_controls = True
        if after_count != before_count - 1:
            self._record_journal(
                "select_change_target",
                "reroll_target",
                "unverified",
                details={"attempt": attempt, "before_count": before_count, "after_count": after_count},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, "select_change_target", "reroll_count_not_decremented")
            return None
        self._record_journal(
            "select_change_target",
            "reroll_target",
            "verified",
            details={
                "attempt": attempt,
                "before_count": before_count,
                "after_count": after_count,
                "exhausted_by_hidden_controls": exhausted_by_hidden_controls,
            },
            before=before,
            after=after,
        )
        return after_image

    def _advance_to_source_deck(self, context: Context, image, target: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
        next_button = self._find_text_option(
            context,
            image,
            ("次へ",),
            self._observed_button_roi("select_change_target", "next", self.NEXT_ROI),
        )
        if not next_button:
            return self._stop_unsupported(context, "select_change_target", "next_button_not_found")
        before = self._capture_evidence(image, "select_change_target_next_before")
        if not self._click_box_center(context, next_button.best_result.box, double=False):
            return self._stop_unsupported(context, "select_change_target", "next_button_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "select_change_target")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "select_change_target_next_after")
        if not frame_changed(before, after):
            self._record_journal(
                "select_change_target",
                "advance_select_change",
                "unverified",
                details={"target": target, "reason": "next_frame_unchanged"},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "select_change_target", "next_frame_unchanged")
        if self._wait_for_screen_profile(context, after_image, "select_change_source_deck") is None:
            return self._stop_unsupported(context, "select_change_target", "source_deck_page_not_confirmed_after_next")
        # 源卡确认必须使用本轮真实枚举并二次确认过的目标，绝不能回退到预设首选。
        get_runtime_hif_session().set_pending_select_change(str(target["target_name"]))
        self._record_journal(
            "select_change_target",
            "advance_select_change",
            "verified",
            details={"target": target, "candidates": candidates, "next_screen": "select_change_source_deck"},
            before=before,
            after=after,
        )
        return True

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        params = self._get_action_params(argv)
        target_probe = params.get("select_change_target_probe")
        configured_names = params.get("select_change_target_names")
        if target_probe == "enumerate_candidates":
            target_names = load_hif_catalog().skill_names
        elif configured_names is None:
            target_names = preset.select_change_target_names
        elif isinstance(configured_names, (list, tuple)) and configured_names and all(
            isinstance(name, str) and name for name in configured_names
        ):
            # 仅供显式单步实机授权使用；不修改预设的常规决策优先级。
            target_names = tuple(configured_names)
        else:
            return self._stop_unsupported(context, "select_change_target", "configured_target_names_invalid")
        image = self._get_screenshot_or_stop(context, "select_change_target")
        if image is None:
            return True
        before = self._capture_evidence(image, "select_change_target_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                "select_change_target",
                "enumerate_target_candidates",
                "observed",
                details={"reason": "page_execution_mode_not_single_step", "mode": mode.value},
                before=before,
            )
            return self._stop_unsupported(context, "select_change_target", "page_execution_mode_not_single_step")
        image = self._wait_for_screen_profile(context, image, "select_change_target")
        if image is None:
            return self._stop_unsupported(context, "select_change_target", "target_page_not_confirmed")

        current_image = image
        for reroll_attempt in range(preset.reroll_limit + 1):
            candidates: list[dict[str, Any]] = []
            for slot, box in self._slot_boxes():
                selected = self._select_and_read_slot(
                    context,
                    current_image,
                    slot,
                    box,
                    target_names,
                    "enumerate_target_candidate",
                )
                if selected is None:
                    return True
                candidate, current_image = selected
                candidates.append(candidate)

            if target_probe == "enumerate_candidates":
                self._record_journal(
                    "select_change_target",
                    "enumerate_target_candidates",
                    "observed",
                    details={"candidates": candidates, "reroll_attempt": reroll_attempt},
                )
                return self._stop_unsupported(context, "select_change_target", "target_candidate_probe_complete_stop")

            matches = [candidate for candidate in candidates if candidate["target_name"] is not None]
            if len(matches) > 1:
                return self._stop_unsupported(context, "select_change_target", "multiple_target_cards_observed")
            if len(matches) == 1:
                target = matches[0]
                if target["slot"] != candidates[-1]["slot"]:
                    target_box = next(box for slot, box in self._slot_boxes() if slot == target["slot"])
                    selected = self._select_and_read_slot(
                        context,
                        current_image,
                        target["slot"],
                        target_box,
                        target_names,
                        "select_target_candidate",
                    )
                    if selected is None:
                        return True
                    confirmed_target, current_image = selected
                    if confirmed_target["target_name"] != target["target_name"]:
                        return self._stop_unsupported(context, "select_change_target", "selected_target_name_changed")
                    target = confirmed_target
                self._record_journal(
                    "select_change_target",
                    "choose_target_card",
                    "selected",
                    details={"target": target, "candidates": candidates, "reroll_attempt": reroll_attempt},
                )
                return self._advance_to_source_deck(context, current_image, target, candidates)

            if reroll_attempt >= preset.reroll_limit:
                self._record_journal(
                    "select_change_target",
                    "choose_target_card",
                    "rejected",
                    details={"reason": "preset_target_card_not_found", "candidates": candidates, "reroll_attempt": reroll_attempt},
                )
                return self._stop_unsupported(context, "select_change_target", "preset_target_card_not_found")
            rerolled_image = self._reroll_targets(context, current_image, reroll_attempt + 1)
            if rerolled_image is None:
                return True
            current_image = rerolled_image
        return self._stop_unsupported(context, "select_change_target", "target_reroll_loop_exhausted")


@AgentServer.custom_action("ProduceChooseHIFSelectChangeSourceAuto")
class ProduceChooseHIFSelectChangeSourceAuto(_ProduceHIFActionBase):
    """默认只记录牌库；显式探针仅可采样一张卡详情，不能确认或滚动。"""

    FIRST_VISIBLE_SLOT_ROI = [80, 638, 120, 120]
    VISIBLE_SLOT_REGION_IDS = (
        "visible_slot_r1c1",
        "visible_slot_r1c2",
        "visible_slot_r1c3",
        "visible_slot_r1c4",
        "visible_slot_r2c1",
        "visible_slot_r2c2",
        "visible_slot_r2c3",
        "visible_slot_r2c4",
        "visible_slot_r3c1",
        "visible_slot_r3c2",
        "visible_slot_r3c3",
        "visible_slot_r3c4",
    )
    VISIBLE_SLOT_FALLBACKS = (
        [80, 638, 120, 120],
        [227, 638, 120, 120],
        [374, 638, 120, 120],
        [521, 638, 120, 120],
        [80, 786, 120, 120],
        [227, 786, 120, 120],
        [374, 786, 120, 120],
        [521, 786, 120, 120],
        [80, 933, 120, 120],
        [227, 933, 120, 120],
        [374, 933, 120, 120],
        [521, 933, 120, 120],
    )
    DETAIL_NAME_ROI = [190, 270, 410, 44]
    DETAIL_TEXT_ROI = [190, 318, 475, 190]
    COMPLETION_TEXT_ROI = [56, 960, 610, 112]

    def _source_detail_snapshot(self, context: Context, image) -> dict[str, Any]:
        card_name_patterns = [f".*{re.escape(name)}.*" for name in build_card_name_dict()]
        name_detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectChangeSourcePreviewName",
            card_name_patterns,
            self.DETAIL_NAME_ROI,
        )
        effect_detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectChangeSourcePreviewEffect",
            [],
            self.DETAIL_TEXT_ROI,
        )
        name_entries = self._ocr_text_entries(name_detail)
        effect_entries = self._ocr_text_entries(effect_detail)
        best_name = getattr(name_detail, "best_result", None) if name_detail and name_detail.hit else None
        matched_name = normalize_card_name(str(getattr(best_name, "text", "")).rstrip("+").strip()) if best_name else None
        return {
            "name_texts": tuple(entry["text"] for entry in name_entries),
            "matched_name": matched_name,
            "effect_texts": tuple(entry["text"] for entry in effect_entries),
            "confidence": min(
                (entry["score"] for entry in name_entries + effect_entries),
                default=0.0,
            ),
            "name_confidence": float(getattr(best_name, "score", 0.0)) if best_name else 0.0,
            "effect_confidence": min((entry["score"] for entry in effect_entries), default=0.0),
        }

    @staticmethod
    def _source_detail_is_readable(details: dict[str, Any]) -> bool:
        return bool(details["matched_name"] and details["effect_texts"] and details["name_confidence"] > 0 and details["effect_confidence"] > 0)

    def _visible_source_slots(self) -> tuple[tuple[str, list[int]], ...]:
        return tuple(
            (
                region_id,
                self._profile_region("select_change_source_deck", region_id, fallback),
            )
            for region_id, fallback in zip(self.VISIBLE_SLOT_REGION_IDS, self.VISIBLE_SLOT_FALLBACKS)
        )

    def _probe_source_slot(
        self, context: Context, image, slot_id: str, slot_roi: list[int], *, allow_unreadable_details: bool = False
    ):
        before = self._capture_evidence(image, f"select_change_source_deck_{slot_id}_before")
        if not self._click_box_center(context, slot_roi, double=False):
            self._stop_unsupported(context, "select_change_source_deck", "source_deck_probe_click_failed")
            return None
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "select_change_source_deck")
        if after_image is None:
            return None
        after = self._capture_evidence(after_image, f"select_change_source_deck_{slot_id}_after")
        if not frame_changed(before, after):
            # 允许把已经选中的首卡作为只读样本，但不把无变化的点击当作已验证执行。
            details = self._source_detail_snapshot(context, image)
            if self._source_detail_is_readable(details):
                self._record_journal(
                    "select_change_source_deck",
                    "probe_source_card",
                    "observed",
                    details={"slot": slot_id, "slot_roi": slot_roi, "selection_already_active": True, **details},
                    before=before,
                )
                return image
            self._record_journal(
                "select_change_source_deck",
                "probe_source_card",
                "unverified",
                details={"slot": slot_id, "reason": "source_deck_probe_frame_unchanged"},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, "select_change_source_deck", "source_deck_probe_frame_unchanged")
            return None
        if not self._matches_screen_profile(context, after_image, "select_change_source_deck"):
            self._stop_unsupported(context, "select_change_source_deck", "source_deck_page_lost_after_probe")
            return None
        details = self._source_detail_snapshot(context, after_image)
        if not self._source_detail_is_readable(details):
            if allow_unreadable_details:
                self._record_journal(
                    "select_change_source_deck",
                    "probe_source_card",
                    "observed",
                    details={
                        "slot": slot_id,
                        "slot_roi": slot_roi,
                        "name_readable": False,
                        "reason": "source_deck_probe_detail_unreadable",
                        **details,
                    },
                    before=before,
                    after=after,
                )
                return after_image
            self._record_journal(
                "select_change_source_deck",
                "probe_source_card",
                "unverified",
                details={"slot": slot_id, "reason": "source_deck_probe_detail_unreadable", **details},
                before=before,
                after=after,
            )
            self._stop_unsupported(context, "select_change_source_deck", "source_deck_probe_detail_unreadable")
            return None
        self._record_journal(
            "select_change_source_deck",
            "probe_source_card",
            "observed",
            details={"slot": slot_id, "slot_roi": slot_roi, **details},
            before=before,
            after=after,
        )
        return after_image

    def _read_change_completion_texts(self, context: Context, image) -> tuple[str, ...]:
        detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectChangeCompletion",
            [],
            self.COMPLETION_TEXT_ROI,
        )
        return tuple(entry["text"] for entry in self._ocr_text_entries(detail))

    @staticmethod
    def _is_change_completion(texts: tuple[str, ...], source_name: str, target_name: str) -> bool:
        merged = "".join(texts).replace(" ", "")
        # 实机 OCR 会把片假名“ミ”稳定误读成汉字“三”；只对已知卡名做这一种受限容错。
        source_variants = {source_name, source_name.replace("ミ", "三")}
        target_variants = {target_name, target_name.replace("ミ", "三")}
        return any(name in merged for name in source_variants) and any(name in merged for name in target_variants) and "チェンジしました" in merged

    def _confirm_source_card_change(
        self,
        context: Context,
        image,
        source_name: str,
        target_name: str,
        preset: HIFPreset,
        *,
        source_slot_id: str | None = None,
        explicit_source_authorized: bool = False,
    ) -> bool:
        if source_name not in preset.select_change_source_names and not explicit_source_authorized:
            return self._stop_unsupported(context, "select_change_source_deck", "source_card_not_in_preset")
        if source_slot_id not in {slot_id for slot_id, _ in self._visible_source_slots()}:
            source_slot_id = "visible_slot_r2c3"
        source_slot = self._profile_region(
            "select_change_source_deck",
            source_slot_id,
            [374, 786, 120, 120],
        )
        selected = self._probe_source_slot(context, image, "confirm_source", source_slot)
        if selected is None:
            return True
        source_details = self._source_detail_snapshot(context, selected)
        if source_details["matched_name"] != source_name or source_details["name_confidence"] < 0.98:
            self._record_journal(
                "select_change_source_deck",
                "select_source_card_for_confirmation",
                "rejected",
                details={"expected_source": source_name, "slot_roi": source_slot, **source_details},
            )
            return self._stop_unsupported(context, "select_change_source_deck", "source_card_confirmation_target_not_confirmed")

        change_button = self._find_text_option(
            context,
            selected,
            ("チェンジ",),
            self._observed_button_roi("select_change_source_deck", "change", [373, 1119, 255, 82]),
        )
        if not change_button:
            return self._stop_unsupported(context, "select_change_source_deck", "change_button_not_found")
        before = self._capture_evidence(selected, "select_change_source_deck_confirm_before")
        if not self._click_box_center(context, change_button.best_result.box, double=False):
            return self._stop_unsupported(context, "select_change_source_deck", "change_button_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "select_change_result")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "select_change_source_deck_confirm_after")
        if not frame_changed(before, after):
            self._record_journal(
                "select_change_source_deck",
                "confirm_select_change",
                "unverified",
                details={"source": source_name, "reason": "change_confirmation_frame_unchanged"},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "select_change_source_deck", "change_confirmation_frame_unchanged")

        completion_image = after_image
        completion_texts = self._read_change_completion_texts(context, completion_image)
        for _ in range(2):
            if self._is_change_completion(completion_texts, source_name, target_name):
                break
            time.sleep(self.CLICK_DELAY)
            completion_image = self._get_screenshot_or_stop(context, "select_change_result")
            if completion_image is None:
                return True
            completion_texts = self._read_change_completion_texts(context, completion_image)
        if not self._is_change_completion(completion_texts, source_name, target_name):
            self._record_journal(
                "select_change_result",
                "confirm_select_change",
                "unverified",
                details={"source": source_name, "target": target_name, "completion_texts": completion_texts},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "select_change_result", "change_completion_text_not_confirmed")
        self._record_journal(
            "select_change_result",
            "confirm_select_change",
            "verified",
            details={"source": source_name, "target": target_name, "completion_texts": completion_texts},
            before=before,
            after=after,
        )
        get_runtime_hif_session().clear_pending_select_change()
        return self._stop_unsupported(context, "select_change_result", "select_change_result_observed_stop")

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        image = self._get_screenshot_or_stop(context, "select_change_source_deck")
        if image is None:
            return True
        image = self._wait_for_screen_profile(context, image, "select_change_source_deck")
        if image is None:
            return self._stop_unsupported(context, "select_change_source_deck", "source_deck_page_not_confirmed")
        evidence = self._capture_evidence(image, "select_change_source_deck_observed")
        self._record_journal(
            "select_change_source_deck",
            "observe_source_deck",
            "observed",
            details={
                "reason": "source_card_selection_not_authorized",
                "source_preview_roi": self._profile_region("select_change_source_deck", "source_preview", [168, 96, 144, 144]),
                "target_preview_roi": self._profile_region("select_change_source_deck", "target_preview", [407, 96, 144, 144]),
                "deck_grid_roi": self._profile_region("select_change_source_deck", "deck_grid", [80, 623, 560, 485]),
            },
            before=evidence,
        )

        params = self._get_action_params(argv)
        probe_mode = params.get("source_deck_probe")
        if not probe_mode:
            return self._stop_unsupported(context, "select_change_source_deck", "source_card_selection_not_authorized")
        if getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE) is not HIFExecutionMode.SINGLE_STEP:
            return self._stop_unsupported(context, "select_change_source_deck", "source_deck_probe_requires_single_step")

        if probe_mode == "cancel_to_target":
            cancel = self._find_text_option(
                context,
                image,
                ("キャンセル",),
                [70, 1100, 300, 110],
            )
            if not cancel:
                return self._stop_unsupported(context, "select_change_source_deck", "source_deck_cancel_button_not_found")
            before = self._capture_evidence(image, "select_change_source_deck_cancel_before")
            if not self._click_box_center(context, cancel.best_result.box, double=False):
                return self._stop_unsupported(context, "select_change_source_deck", "source_deck_cancel_click_failed")
            time.sleep(self.ACTION_DELAY)
            after_image = self._get_screenshot_or_stop(context, "select_change_target")
            if after_image is None:
                return True
            after = self._capture_evidence(after_image, "select_change_source_deck_cancel_after")
            if not frame_changed(before, after) or not self._matches_screen_profile(context, after_image, "select_change_target"):
                return self._stop_unsupported(context, "select_change_source_deck", "source_deck_cancel_target_page_not_confirmed")
            self._record_journal(
                "select_change_source_deck",
                "cancel_source_deck",
                "verified",
                details={"next_screen": "select_change_target"},
                before=before,
                after=after,
            )
            return True

        if probe_mode == "confirm_source_card":
            source_name = params.get("source_card_name")
            if not isinstance(source_name, str) or not source_name:
                return self._stop_unsupported(context, "select_change_source_deck", "source_card_name_missing")
            pending_change = get_runtime_hif_session().pending_select_change
            target_name = pending_change.target_name if pending_change is not None else None
            explicit_source_authorized = params.get("explicit_source_authorized") is True
            explicit_target_authorized = params.get("explicit_target_authorized") is True
            if not isinstance(target_name, str) or (
                target_name not in preset.select_change_target_names and not explicit_target_authorized
            ):
                return self._stop_unsupported(context, "select_change_source_deck", "selected_target_card_missing_or_invalid")
            if params.get("source_card_scroll_once") is True:
                if not self._swipe_with_verification(
                    context,
                    image,
                    "select_change_source_deck",
                    "scroll_source_deck_before_confirm",
                    (360, 1040),
                    (360, 680),
                    duration=300,
                    details={"direction": "up", "max_scrolls": 1},
                ):
                    return True
                image = self._get_screenshot_or_stop(context, "select_change_source_deck")
                if image is None:
                    return True
                if not self._matches_screen_profile(context, image, "select_change_source_deck"):
                    return self._stop_unsupported(context, "select_change_source_deck", "source_deck_page_lost_after_confirm_scroll")
            return self._confirm_source_card_change(
                context,
                image,
                source_name,
                target_name,
                preset,
                source_slot_id=params.get("source_card_slot") if isinstance(params.get("source_card_slot"), str) else None,
                explicit_source_authorized=explicit_source_authorized,
            )

        if probe_mode is True:
            slots = (("first_visible", self._profile_region("select_change_source_deck", "first_visible_slot", self.FIRST_VISIBLE_SLOT_ROI)),)
            stop_reason = "source_deck_probe_complete_stop"
        elif probe_mode == "visible_grid":
            slots = self._visible_source_slots()
            stop_reason = "source_deck_visible_enumeration_complete_stop"
        elif probe_mode == "visible_grid_after_one_scroll":
            if not self._swipe_with_verification(
                context,
                image,
                "select_change_source_deck",
                "scroll_source_deck_once",
                (360, 1040),
                (360, 680),
                duration=300,
                details={"direction": "up", "max_scrolls": 1},
            ):
                return True
            image = self._get_screenshot_or_stop(context, "select_change_source_deck")
            if image is None:
                return True
            if not self._matches_screen_profile(context, image, "select_change_source_deck"):
                return self._stop_unsupported(context, "select_change_source_deck", "source_deck_page_lost_after_scroll")
            slots = self._visible_source_slots()
            stop_reason = "source_deck_visible_enumeration_after_scroll_complete_stop"
        else:
            return self._stop_unsupported(context, "select_change_source_deck", "source_deck_probe_mode_unsupported")

        current_image = image
        for slot_id, slot_roi in slots:
            current_image = self._probe_source_slot(
                context,
                current_image,
                slot_id,
                slot_roi,
                allow_unreadable_details=probe_mode in {"visible_grid", "visible_grid_after_one_scroll"},
            )
            if current_image is None:
                return True
        return self._stop_unsupported(context, "select_change_source_deck", stop_reason)


@AgentServer.custom_action("ProduceHIFConsultAuto")
class ProduceHIFConsultAuto(_ProduceHIFActionBase):
    """首版仅支持保留 P 点并结束咨询商店。"""

    FINISH_ROI = [530, 1000, 190, 150]
    ENHANCE_ROI = [50, 920, 310, 100]
    DELETE_ROI = [365, 920, 310, 100]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        probe = str(self._get_action_params(argv).get("consult_probe", ""))
        if probe in {"enhance", "delete"}:
            return self._open_consult_manage_page(context, probe)
        if preset.consult_policy != "finish_without_purchase":
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

    def _open_consult_manage_page(self, context: Context, probe: str) -> bool:
        """只读采样咨询的强化/删除页；不选择卡片或提交任何变更。"""

        image = self._get_screenshot_or_stop(context, "consult_shop")
        if image is None:
            return True
        label, roi = ("強化", self.ENHANCE_ROI) if probe == "enhance" else ("削除", self.DELETE_ROI)
        before = self._capture_evidence(image, f"consult_{probe}_before")
        if not self._click_text_with_verification(context, image, "consult_shop", f"open_{probe}", (label,), roi):
            return True
        after_image = self._get_screenshot_or_stop(context, f"consult_{probe}")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, f"consult_{probe}_opened")
        self._record_journal(
            "consult_shop",
            f"observe_{probe}_page",
            "observed",
            details={"probe": probe, "submission": "none"},
            before=before,
            after=after,
        )
        return self._stop_unsupported(context, f"consult_{probe}", "consult_manage_page_observed_stop")


@AgentServer.custom_action("ProduceHIFRewardConfirmAuto")
class ProduceHIFRewardConfirmAuto(_ProduceHIFActionBase):
    """确认已由奖励选择 Action 唯一选中的领取项。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "hif_reward_confirm")
        if image is None:
            return True
        session = get_runtime_hif_session()
        pending = session.pending_reward
        if pending is None:
            return self._stop_unsupported(context, "hif_reward_confirm", "pending_drink_reward_missing")
        if pending.kind == "skill":
            return self._confirm_skill_reward(context, argv, image, session, pending)
        if pending.kind != "drink":
            return self._stop_unsupported(context, "hif_reward_confirm", "unsupported_pending_reward_kind")
        page_match = detect_drink_reward_page(context, image)
        if page_match is None:
            return self._stop_unsupported(context, "hif_reward_confirm", "drink_reward_page_not_confirmed")
        if page_match.state != "selected_detail" or page_match.name != pending.name:
            return self._stop_unsupported(context, "hif_reward_confirm", "pending_drink_reward_not_selected")

        before = self._capture_evidence(image, "hif_reward_confirm_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                "hif_reward_confirm",
                "confirm_reward",
                "observed",
                details={"reason": "page_execution_mode_not_single_step", "mode": mode.value, "reward": pending.name},
                before=before,
            )
            return self._stop_unsupported(context, "hif_reward_confirm", "page_execution_mode_not_single_step")
        receive = self._find_text_option(
            context,
            image,
            ("受け取る",),
            self._observed_button_roi("drink_reward", "receive", [230, 1052, 260, 84]),
        )
        if not receive:
            return self._stop_unsupported(context, "hif_reward_confirm", "receive_button_not_found")
        if not self._click_box_center(context, receive.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_reward_confirm", "receive_button_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "hif_reward_confirm")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "hif_reward_confirm_after")
        if not frame_changed(before, after):
            self._record_journal(
                "hif_reward_confirm",
                "confirm_reward",
                "unverified",
                details={"reason": "post_receive_frame_unchanged", "reward": pending.name},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "hif_reward_confirm", "post_receive_frame_unchanged")
        if self._matches_screen_profile(context, after_image, "skill_reward"):
            session.clear_pending_reward()
            self._record_journal(
                "hif_reward_confirm",
                "confirm_reward",
                "verified",
                details={
                    "reward": pending.name,
                    "slot": pending.slot,
                    "page_state": page_match.state,
                    "selected_name": page_match.name,
                    "click_count": 1,
                    "next_screen": "skill_reward",
                },
                before=before,
                after=after,
            )
            return True

        reveal_match = detect_drink_reward_reveal_page(context, after_image)
        reveal_name_confirmed = reveal_match is not None and reveal_match.name == pending.name
        if not reveal_name_confirmed:
            profile = load_hif_screen_profiles().get("drink_reward")
            reveal_name_roi = list(profile.regions.get("reveal_name", (72, 840, 576, 76))) if profile else [72, 840, 576, 76]
            reveal_name = self._run_ocr(
                context,
                after_image,
                "ProduceRecognitionHIFDrinkRewardRevealPendingName",
                [f".*{re.escape(pending.name)}.*"],
                reveal_name_roi,
            )
            reveal_name_confirmed = bool(reveal_name and reveal_name.hit)
        if not reveal_name_confirmed:
            return self._stop_unsupported(context, "hif_reward_confirm", "drink_reward_reveal_not_confirmed_after_receive")
        self._record_journal(
            "hif_reward_confirm",
            "confirm_reward",
            "verified",
            details={"reward": pending.name, "slot": pending.slot, "click_count": 1, "next_screen": "drink_reward_reveal"},
            before=before,
            after=after,
        )

        # 实机证据表明展示条上的“受け取る”是短暂动画，而非第二个稳定的
        # 资源提交控件。保留 pending，交由展示等待节点和技能卡页后验完成闭环。
        return True

    def _confirm_skill_reward(self, context: Context, argv: CustomAction.RunArg, image, session, pending) -> bool:
        page_match = detect_skill_reward_selected_page(context, image)
        if page_match is None:
            return self._stop_unsupported(context, "hif_reward_confirm", "skill_reward_page_not_confirmed")
        if page_match.name != pending.name:
            return self._stop_unsupported(context, "hif_reward_confirm", "pending_skill_reward_not_selected")

        before = self._capture_evidence(image, "hif_skill_reward_confirm_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                "hif_reward_confirm",
                "confirm_skill_reward",
                "observed",
                details={"reason": "page_execution_mode_not_single_step", "mode": mode.value, "reward": pending.name},
                before=before,
            )
            return self._stop_unsupported(context, "hif_reward_confirm", "page_execution_mode_not_single_step")
        if self._get_action_params(argv).get("skill_reward_receive_authorized") is not True:
            return self._stop_unsupported(context, "hif_reward_confirm", "skill_reward_receipt_not_authorized")
        receive = self._find_text_option(
            context,
            image,
            ("受け取る",),
            self._observed_button_roi("skill_reward", "receive", [230, 1052, 260, 84]),
        )
        if not receive:
            return self._stop_unsupported(context, "hif_reward_confirm", "skill_reward_receive_button_not_found")
        if not self._click_box_center(context, receive.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_reward_confirm", "skill_reward_receive_button_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "hif_reward_confirm")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "hif_skill_reward_confirm_after")
        if not frame_changed(before, after):
            self._record_journal(
                "hif_reward_confirm",
                "confirm_skill_reward",
                "unverified",
                details={"reason": "post_skill_receive_frame_unchanged", "reward": pending.name},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "hif_reward_confirm", "post_skill_receive_frame_unchanged")
        if self._matches_screen_profile(context, after_image, "round1"):
            session.clear_pending_reward()
            self._record_journal(
                "hif_reward_confirm",
                "confirm_skill_reward",
                "verified",
                details={
                    "reward": pending.name,
                    "slot": pending.slot,
                    "selected_name": page_match.name,
                    "click_count": 1,
                    "next_screen": "round1",
                },
                before=before,
                after=after,
            )
            return True
        reveal_match = detect_skill_reward_reveal_page(context, after_image)
        if reveal_match is None or reveal_match.name != pending.name:
            return self._stop_unsupported(context, "hif_reward_confirm", "skill_reward_round1_not_confirmed_after_receive")
        self._record_journal(
            "hif_reward_confirm",
            "confirm_skill_reward",
            "verified",
            details={
                "reward": pending.name,
                "slot": pending.slot,
                "selected_name": page_match.name,
                "click_count": 1,
                "next_screen": "skill_reward_reveal",
            },
            before=before,
            after=after,
        )
        return True


@AgentServer.custom_action("ProduceHIFSkillRewardRevealAuto")
class ProduceHIFSkillRewardRevealAuto(_ProduceHIFActionBase):
    """确认已领取的技能卡展示层，并仅以 Round1 作为关闭后的成功后验。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "hif_skill_reward_reveal")
        if image is None:
            return True
        before = self._capture_evidence(image, "hif_skill_reward_reveal_before")
        reveal_match = detect_skill_reward_reveal_page(context, image)
        if reveal_match is None:
            return self._stop_unsupported(context, "hif_skill_reward_reveal", "skill_reward_reveal_not_confirmed")
        pending = get_runtime_hif_session().pending_reward
        params = self._get_action_params(argv)
        expected_name = pending.name if pending is not None and pending.kind == "skill" else params.get("skill_reward_reveal_expected_name")
        if reveal_match.name != expected_name:
            return self._stop_unsupported(context, "hif_skill_reward_reveal", "skill_reward_reveal_name_not_expected")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            return self._stop_unsupported(context, "hif_skill_reward_reveal", "page_execution_mode_not_single_step")
        if params.get("skill_reward_receive_authorized") is not True:
            return self._stop_unsupported(context, "hif_skill_reward_reveal", "skill_reward_reveal_not_authorized")
        receive = self._find_text_option(
            context,
            image,
            ("受け取る",),
            self._observed_button_roi("skill_reward", "receive", [230, 1052, 260, 84]),
        )
        if not receive:
            return self._stop_unsupported(context, "hif_skill_reward_reveal", "skill_reward_reveal_receive_button_not_found")
        if not self._click_box_center(context, receive.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_skill_reward_reveal", "skill_reward_reveal_receive_button_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "hif_skill_reward_reveal")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "hif_skill_reward_reveal_after")
        if not frame_changed(before, after):
            return self._stop_unsupported(context, "hif_skill_reward_reveal", "skill_reward_reveal_frame_unchanged")
        if not self._matches_screen_profile(context, after_image, "round1"):
            return self._stop_unsupported(context, "hif_skill_reward_reveal", "skill_reward_reveal_round1_not_confirmed")
        if pending is not None and pending.kind == "skill":
            get_runtime_hif_session().clear_pending_reward()
        self._record_journal(
            "hif_skill_reward_reveal",
            "confirm_skill_reward_reveal",
            "verified",
            details={"reward": reveal_match.name, "click_count": 1, "next_screen": "round1"},
            before=before,
            after=after,
        )
        return True


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


@AgentServer.custom_action("ProduceHIFPublicLessonResultAuto")
class ProduceHIFPublicLessonResultAuto(_ProduceHIFActionBase):
    """公开课结算动画页仅在已确认页面上用受限空白点继续。"""

    SAFE_TARGET = [341, 204, 0, 3]
    MAX_ADVANCES = 4

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "public_lesson_result")
        if image is None:
            return True
        before = self._capture_evidence(image, "public_lesson_result_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                "public_lesson_result",
                "advance_public_lesson_result",
                "observed",
                details={"reason": "page_execution_mode_not_single_step", "mode": mode.value},
                before=before,
            )
            return self._stop_unsupported(context, "public_lesson_result", "page_execution_mode_not_single_step")
        if not self._matches_screen_profile(context, image, "public_lesson_result"):
            return self._stop_unsupported(context, "public_lesson_result", "public_lesson_result_page_not_confirmed")
        current_evidence = before
        seen_fingerprints = {before.fingerprint}
        for attempt in range(1, self.MAX_ADVANCES + 1):
            if not self._click_box_center(context, self.SAFE_TARGET, double=False):
                return self._stop_unsupported(context, "public_lesson_result", "public_lesson_result_advance_click_failed")
            time.sleep(self.ACTION_DELAY)
            after_image = self._get_screenshot_or_stop(context, "public_lesson_result")
            if after_image is None:
                return True
            after = self._capture_evidence(after_image, f"public_lesson_result_after_{attempt}")
            if not frame_changed(current_evidence, after):
                self._record_journal(
                    "public_lesson_result",
                    "advance_public_lesson_result",
                    "unverified",
                    details={"attempt": attempt, "reason": "public_lesson_result_frame_unchanged"},
                    before=current_evidence,
                    after=after,
                )
                return self._stop_unsupported(context, "public_lesson_result", "public_lesson_result_frame_unchanged")
            if after.fingerprint in seen_fingerprints:
                return self._stop_unsupported(context, "public_lesson_result", "public_lesson_result_frame_cycle")
            seen_fingerprints.add(after.fingerprint)
            if not self._matches_screen_profile(context, after_image, "public_lesson_result"):
                next_screen = self._detect_confirmed_hif_transition(context, after_image)
                if next_screen is None:
                    self._record_journal(
                        "public_lesson_result",
                        "advance_public_lesson_result",
                        "unverified",
                        details={"attempt": attempt, "reason": "public_lesson_result_next_page_not_confirmed"},
                        before=current_evidence,
                        after=after,
                    )
                    return self._stop_unsupported(context, "public_lesson_result", "public_lesson_result_next_page_not_confirmed")
                self._record_journal(
                    "public_lesson_result",
                    "advance_public_lesson_result",
                    "verified",
                    details={"target": self.SAFE_TARGET, "attempts": attempt, "next_screen": next_screen},
                    before=before,
                    after=after,
                )
                return True
            self._record_journal(
                "public_lesson_result",
                "advance_public_lesson_result",
                "observed",
                details={"target": self.SAFE_TARGET, "attempt": attempt, "result_still_visible": True},
                before=current_evidence,
                after=after,
            )
            current_evidence = after
        return self._stop_unsupported(context, "public_lesson_result", "public_lesson_result_advance_limit_reached")


@AgentServer.custom_action("ProduceHIFStartProduceAuto")
class ProduceHIFStartProduceAuto(_ProduceHIFActionBase):
    """仅在已确认的 HIF 开始确认页启动本次培育。"""

    START_ROI = [210, 1030, 300, 105]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        self._configure_page_execution(argv)
        image = self._get_screenshot_or_stop(context, "hif_start_confirm")
        if image is None:
            return True
        before = self._capture_evidence(image, "hif_start_confirm_before")
        mode = getattr(self, "_page_execution_mode", HIFExecutionMode.OBSERVE)
        if mode is not HIFExecutionMode.SINGLE_STEP:
            self._record_journal(
                "hif_start_confirm",
                "start_produce",
                "observed",
                details={"reason": "page_execution_mode_not_single_step", "mode": mode.value},
                before=before,
            )
            return self._stop_unsupported(context, "hif_start_confirm", "page_execution_mode_not_single_step")
        if not self._matches_screen_profile(context, image, "hif_start_confirm"):
            return self._stop_unsupported(context, "hif_start_confirm", "start_confirm_page_not_confirmed")
        start = self._find_text_option(context, image, ("プロデュース開始",), self.START_ROI)
        if not start:
            return self._stop_unsupported(context, "hif_start_confirm", "start_produce_button_not_found")
        if not self._click_box_center(context, start.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_start_confirm", "start_produce_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, "hif_start_confirm")
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, "hif_start_confirm_after")
        if not frame_changed(before, after):
            self._record_journal(
                "hif_start_confirm",
                "start_produce",
                "unverified",
                details={"reason": "post_start_frame_unchanged"},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "hif_start_confirm", "post_start_frame_unchanged")
        if self._matches_screen_profile(context, after_image, "hif_start_confirm"):
            return self._stop_unsupported(context, "hif_start_confirm", "start_confirm_page_still_visible")
        next_screen = self._detect_confirmed_hif_transition(context, after_image)
        if next_screen is None:
            self._record_journal(
                "hif_start_confirm",
                "start_produce",
                "unverified",
                details={"reason": "start_next_page_not_confirmed"},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, "hif_start_confirm", "start_next_page_not_confirmed")
        self._record_journal(
            "hif_start_confirm",
            "start_produce",
            "verified",
            details={"next_screen": next_screen},
            before=before,
            after=after,
        )
        return True


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

    _DIRECT_CARD_EXECUTION_FIELDS = {"good_condition", "focus", "turn", "flow", "stamina"}
    POSTCONDITION_ATTEMPTS = 8
    POSTCONDITION_SETTLE_DELAY = 1.0

    @staticmethod
    def _infer_initial_reprise(observation, total_turns: int) -> bool:
        """仅在 Round 尚未消耗回合时，按机制确定再演发动次数为零。"""

        if "reprise" not in observation.missing_fields or observation.state.turn != total_turns:
            return False
        observation.numerics["reprise"] = NumericRead("reprise", "initial_round=0", 0)
        observation.state.reprise_count = 0
        observation.missing_fields = tuple(field for field in observation.missing_fields if field != "reprise")
        return True

    @staticmethod
    def _resolve_initial_default_target(card_action: CardAction, observation, total_turns: int) -> CardAction:
        """首回合默认分支唯一选择可支付的持续收益卡，其他回合保持安全停止。"""

        if card_action.kind is not ActionKind.PLAY_CARD or card_action.target_card or observation.state.turn != total_turns:
            return card_action
        active_names = {
            normalize_card_name(detection.card_name)
            for detection in observation.detections
            if detection.card_name and not detection.suppressed_reason and detection.label != "useless"
        }
        target_name = "至高のエンタメ"
        card = load_hif_catalog().skill_cards.get(target_name)
        focus_cost = card.focus_cost if card and card.focus_cost is not None else 3
        if target_name not in active_names or observation.state.focus < focus_cost:
            return card_action
        return CardAction(
            ActionKind.PLAY_CARD,
            target_name,
            f"首回合优先发动持续加分与次回合补抽；当前集中{observation.state.focus}可支付保守消耗{focus_cost}",
        )

    @staticmethod
    def _recover_reprise_after_entertainment(observation, session, round_key: str, total_turns: int) -> tuple[bool, str]:
        """按首牌前后实证恢复第 2 回合状态，不接受其他页面或手牌组合。"""

        if round_key != "round1":
            return False, "reprise_recovery_round_mismatch"
        if total_turns != 9:
            return False, "reprise_recovery_total_turns_mismatch"
        if observation.state.turn != 8:
            return False, "reprise_recovery_turn_mismatch"
        if "reprise" not in observation.missing_fields:
            return False, "reprise_recovery_not_missing"
        if set(observation.missing_fields) != {"reprise"}:
            return False, "reprise_recovery_other_fields_missing"
        active_names = {
            normalize_card_name(detection.card_name)
            for detection in observation.detections
            if detection.card_name and not detection.suppressed_reason
        }
        required = {"自然体の魅力", "お姉さんの感覚"}
        if not required.issubset(active_names):
            return False, "reprise_recovery_hand_evidence_missing"
        if "至高のエンタメ" in active_names:
            return False, "reprise_recovery_entertainment_still_in_hand"
        observation.numerics["reprise"] = NumericRead("reprise", "recovered_after_entertainment=0", 0)
        observation.state.reprise_count = 0
        observation.missing_fields = tuple(field for field in observation.missing_fields if field != "reprise")
        session.record_card(round_key, "至高のエンタメ")
        return True, "turn9_entertainment_played_without_shizen_in_pre_hand"

    def _read_card_postcondition(
        self,
        context: Context,
        after_image,
        screen_state: str,
        round_: ExamRound,
        total_turns: int,
        target: CardDetection,
        before_detections: list[CardDetection],
        *,
        before_state: Any | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """确认目标已生效；再演/动画中间态必须等到稳定手牌后再判定。"""

        state_fields = ("turn", "good_condition_turns", "focus", "stamina", "reprise_count", "deck_size")
        before_state_values = {
            name: value
            for name in state_fields
            if isinstance((value := getattr(before_state, name, None)), int)
        }
        stable_image = self._wait_for_screen_profile(context, after_image, screen_state, attempts=4)
        if stable_image is None:
            return False, {"reason": "round_page_not_confirmed_after_card"}
        before_names = [
            normalize_card_name(detection.card_name)
            for detection in before_detections
            if detection.card_name and not detection.suppressed_reason
        ]
        target_name = normalize_card_name(target.card_name)
        last_details: dict[str, Any] = {
            "target_card": target_name,
            "before_hand": before_names,
            "after_hand": [],
            "post_screen_confidence": 0.0,
        }
        post_hand_recovered = False
        for attempt in range(self.POSTCONDITION_ATTEMPTS):
            post_health = self._get_health(context, stable_image)
            post = ExamStateReader.from_context(context).read_exam_observation(
                round_,
                total_turns,
                post_health["current"] if post_health else None,
            )
            if "hand_names" in post.missing_fields and not post_hand_recovered:
                details = self._probe_round_hand_details(
                    context,
                    stable_image,
                    screen_state,
                    return_details=True,
                    post_execution=True,
                )
                if not isinstance(details, list):
                    return False, {"reason": "post_hand_detail_mapping_failed"}
                selected_image = self._get_screenshot_or_stop(context, screen_state)
                if selected_image is None:
                    return False, {"reason": "post_hand_screencap_failed"}
                deck_size, stable_image = self._probe_round_deck_size(context, selected_image, screen_state)
                if deck_size is None or stable_image is None:
                    return False, {"reason": "post_hand_deck_probe_failed"}
                post_health = self._get_health(context, stable_image)
                post = ExamStateReader.from_context(context).read_exam_observation(
                    round_, total_turns, post_health["current"] if post_health else None
                )
                post.numerics["deck_size"] = NumericRead("deck_size", str(deck_size), deck_size)
                post.state.deck_size = deck_size
                post.missing_fields = tuple(field for field in post.missing_fields if field != "deck_size")
                self._complete_current_run_hand_observation(post, get_runtime_hif_session())
                post_hand_recovered = True
            after_names = [
                normalize_card_name(detection.card_name)
                for detection in post.detections
                if detection.card_name and not detection.suppressed_reason
            ]
            post_state_values = {
                name: value
                for name in state_fields
                if isinstance((value := getattr(getattr(post, "state", None), name, None)), int)
            }
            last_details = {
                "target_card": target_name,
                "before_hand": before_names,
                "after_hand": after_names,
                "post_screen_confidence": post.screen_confidence,
                "post_hand_attempt": attempt + 1,
                "post_state": post_state_values,
            }
            if after_names and "hand" not in post.missing_fields and "hand_names" not in post.missing_fields:
                if target_name in after_names:
                    last_details["reason"] = "target_card_still_in_hand"
                elif before_names == after_names:
                    last_details["reason"] = "hand_not_changed_after_card"
                elif before_state is not None:
                    comparable_fields = before_state_values.keys() & post_state_values.keys()
                    if not comparable_fields:
                        last_details["reason"] = "post_state_not_readable"
                    else:
                        changed_fields = sorted(
                            name for name in comparable_fields if before_state_values[name] != post_state_values[name]
                        )
                        last_details["state_changed_fields"] = changed_fields or ["hand"]
                        return True, last_details
                else:
                    return True, last_details
            if attempt < self.POSTCONDITION_ATTEMPTS - 1:
                time.sleep(self.POSTCONDITION_SETTLE_DELAY)
                stable_image = self._get_screenshot_or_stop(context, screen_state)
                if stable_image is None or not self._matches_screen_profile(context, stable_image, screen_state):
                    return False, {**last_details, "reason": "round_page_lost_during_postcondition"}
        return False, {**last_details, "reason": last_details.get("reason", "post_hand_not_readable")}

    @staticmethod
    def _apply_current_run_hand_detail_names(detections: list[CardDetection], session) -> None:
        """只用同一次运行已验证的详情标题补齐空 OCR 名，框集合不匹配则不猜。"""

        for detection in detections:
            if detection.suppressed_reason or detection.card_name:
                continue
            verified = session.hand_detail_name(detection.box)
            if verified:
                detection.card_name = normalize_card_name(verified)
                detection.raw_card_name = verified
                detection.card_name_confidence = 1.0

    @classmethod
    def _complete_current_run_hand_observation(cls, observation, session) -> list[CardDetection]:
        """以本次详情映射补全手牌后，才恢复完整状态的置信度。"""

        cls._apply_current_run_hand_detail_names(observation.detections, session)
        active = [detection for detection in observation.detections if not detection.suppressed_reason]
        if active and all(detection.card_name for detection in active):
            observation.state.hand = build_hand_summary(observation.detections)
            observation.missing_fields = tuple(field for field in observation.missing_fields if field != "hand_names")
        if not observation.missing_fields:
            observation.screen_confidence = 1.0
        return active

    @staticmethod
    def _box_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
        left_x, left_y, left_width, left_height = left
        right_x, right_y, right_width, right_height = right
        overlap_width = max(0, min(left_x + left_width, right_x + right_width) - max(left_x, right_x))
        overlap_height = max(0, min(left_y + left_height, right_y + right_height) - max(left_y, right_y))
        overlap = overlap_width * overlap_height
        if overlap <= 0:
            return 0.0
        return overlap / (left_width * left_height + right_width * right_height - overlap)

    @staticmethod
    def _selected_marker_detection(marker, detections: list[CardDetection]) -> CardDetection | None:
        """用 SELECT 标记的横向位置唯一回配已选卡框；缺少几何证据时拒绝猜测。"""

        best = getattr(marker, "best_result", None)
        box = getattr(best, "box", None)
        try:
            marker_box = tuple(box)
        except TypeError:
            return None
        if len(marker_box) != 4:
            return None
        marker_center_x = marker_box[0] + marker_box[2] / 2
        matches = [
            detection
            for detection in detections
            if detection.box[0] <= marker_center_x <= detection.box[0] + detection.box[2]
        ]
        return matches[0] if len(matches) == 1 else None

    def _approve_round1_detail_mapped_topic_target(
        self,
        observation,
        details: list[dict[str, Any]],
        *,
        selected_at_start: bool,
        expected_card: str = "話題沸騰",
        expected_hand_size: int = 5,
    ) -> tuple[CardDetection | None, str]:
        """只接受本次五张详情与重建手牌一一对应的話題沸騰目标。"""

        if selected_at_start:
            return None, "round1_detail_requires_unselected_hand"
        raw_active = [detection for detection in observation.detections if not detection.suppressed_reason]
        active = []
        for detail in details:
            box = detail.get("box")
            if not isinstance(box, list | tuple) or len(box) != 4:
                return None, "round1_detail_title_unreadable"
            matches = [detection for detection in raw_active if self._box_iou(tuple(box), detection.box) >= 0.8]
            if len(matches) != 1:
                return None, "round1_detail_mapping_iou_conflict"
            active.append(matches[0])
        if len(details) != expected_hand_size:
            return None, "round1_detail_mapping_incomplete"
        if len(active) != expected_hand_size or len({id(detection) for detection in active}) != expected_hand_size:
            return None, "round1_detail_mapping_iou_conflict"
        mapped: set[int] = set()
        for detail in details:
            box = detail.get("box")
            title = normalize_card_name(str(detail.get("detail_title", "")))
            if not isinstance(box, list | tuple) or len(box) != 4 or not title:
                return None, "round1_detail_title_unreadable"
            matches = [
                index
                for index, detection in enumerate(active)
                if self._box_iou(tuple(box), detection.box) >= 0.8
            ]
            if len(matches) != 1:
                return None, "round1_detail_mapping_iou_conflict"
            index = matches[0]
            if index in mapped:
                return None, "round1_detail_mapping_iou_conflict"
            detection = active[index]
            if detection.card_name and normalize_card_name(detection.card_name) != title:
                if detection.card_name_confidence >= float(detail.get("detail_title_confidence", 0.0)):
                    return None, "round1_detail_title_conflict"
            detection.card_name = title
            detection.raw_card_name = str(detail.get("detail_title_raw") or detail["detail_title"])
            detection.card_name_confidence = 1.0
            mapped.add(index)
        if len(mapped) != expected_hand_size:
            return None, "round1_detail_mapping_incomplete"
        if observation.missing_fields:
            return None, "round1_detail_state_incomplete"
        if getattr(observation.state, "good_condition_turns", 0) < 8:
            return None, "round1_detail_good_condition_insufficient"
        targets = [
            detection
            for detection in active
            if detection.label != "useless" and normalize_card_name(detection.card_name) == expected_card
        ]
        if len(targets) != 1:
            return None, "round1_detail_topic_target_not_unique"
        return targets[0], "approved"

    def _card_selection_confirmed(self, context: Context, image, target_name: str) -> bool:
        """要求卡牌详情标题与 SELECT 标记同时存在，才允许第二次点击。"""

        title = None
        for roi in ([180, 430, 360, 90], [180, 500, 360, 90], [180, 570, 360, 90], [180, 640, 360, 90]):
            title = self._run_ocr(
                context,
                image,
                "ProduceRecognitionHIFSelectedCardTitle",
                [rf".*{re.escape(target_name)}.*"],
                roi,
            )
            if title and title.hit:
                break
        selected = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectedCardMarker",
            [r".*SELECT.*", r".*SELEC.*"],
            [0, 1080, 720, 100],
        )
        return bool(title and title.hit and selected and selected.hit)

    def _read_card_display_score(self, context: Context, image, target: CardDetection) -> int | None:
        """读取当前目标卡面显示的即时分数；混入其他文本或多个数字时拒绝。"""

        x, y, width, height = target.box
        roi = [x, y, width, min(90, height)]
        result = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectedRouteCardScore",
            [r"\d+"],
            roi,
        )
        best = getattr(result, "best_result", None) if result and result.hit else None
        raw = str(getattr(best, "text", "")).replace(",", "").strip() if best else ""
        return int(raw) if re.fullmatch(r"\d+", raw) else None

    def _verify_blessing_plus_postcondition(
        self,
        context: Context,
        image,
        screen_state: str,
        round_: ExamRound,
        total_turns: int,
        before_state,
        displayed_score: int,
    ) -> tuple[bool, dict[str, Any]]:
        """动作后重新读取牌库、分数和 Round 状态，验证 ``祝福+`` 的完整语义。"""

        stable_image = self._wait_for_screen_profile(context, image, screen_state, attempts=4)
        if stable_image is None:
            return False, {"reason": "round_page_not_confirmed_after_blessing_plus"}
        deck_size, returned_image = self._probe_round_deck_size(context, stable_image, screen_state)
        if deck_size is None or returned_image is None:
            return False, {"reason": "post_blessing_deck_probe_failed"}
        panel_result = self._probe_round_details_metrics(context, returned_image, screen_state, continue_after=True)
        if not isinstance(panel_result, tuple):
            return False, {"reason": "post_blessing_metrics_probe_failed"}
        score_raw, multiplier_raw, returned_image = panel_result
        health = self._get_health(context, returned_image)
        observation = ExamStateReader.from_context(context).read_exam_observation(
            round_, total_turns, health["current"] if health else None
        )
        observation.numerics["deck_size"] = NumericRead("deck_size", str(deck_size), deck_size)
        observation.round_metrics = build_round_metrics(
            {"current_score": score_raw, "stage_multiplier": multiplier_raw}
        )
        infer_card_playability(returned_image, observation.detections)
        try:
            ready = assemble_route_state(
                observation,
                route_id="rinami_garakuta_road",
                round_key="round1" if round_ is ExamRound.HONSEN_R1 else "round2",
                total_turns=total_turns,
            )
        except RouteStateRejected as error:
            return False, {
                "reason": "post_blessing_route_state_rejected",
                "issues": [
                    {"field": issue.field, "code": issue.code.value, "detail": issue.detail}
                    for issue in error.issues
                ],
            }
        result = verify_blessing_plus(before_state, ready.state, displayed_score=displayed_score)
        details = {
            "reason": "verified" if result.verified else "blessing_plus_semantic_postcondition_failed",
            "semantic_assertions": result.assertions,
            "failed_assertions": result.failed_assertions,
            "post_state": {
                "turn": ready.state.turn,
                "current_score": ready.state.current_score,
                "stamina": ready.state.stamina,
                "focus": ready.state.focus,
                "good_condition": ready.state.good_condition_turns,
                "reprise": ready.state.reprise_count,
                "deck_size": ready.state.deck_size,
            },
        }
        return result.verified, details

    def _read_selected_card_title(self, context: Context, image, card_dict: list[str]) -> tuple[str, str, float]:
        """从详情弹窗标题读取标准卡名；逐段搜索避免把效果正文误认成标题。"""

        expected = [*card_dict, *(f"{name}+" for name in card_dict), *(f"{name}++" for name in card_dict)]
        for index, roi in enumerate(([180, 430, 360, 90], [180, 500, 360, 90], [180, 570, 360, 90], [180, 640, 360, 90])):
            raw, confidence = ExamStateReader.from_context(context).ocr._run_ocr_with_confidence(
                f"ProduceRecognitionHIFSelectedCardTitleProbe{index}",
                expected,
                tuple(roi),
            )
            if not raw:
                continue
            candidate = raw.rstrip("+")
            normalized = normalize_card_name(candidate)
            if normalized in card_dict:
                return normalized, raw, confidence
        return "", "", 0.0

    def _probe_selected_hand_detail(self, context: Context, image, screen_state: str) -> bool:
        """只读取当前已选中手牌的详情标题，不发送任何控制器输入。"""

        if not self._matches_screen_profile(context, image, screen_state):
            return self._stop_unsupported(context, screen_state, "round_page_not_confirmed_before_selected_detail_probe")
        marker = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectedCardMarkerReadOnly",
            [r".*SELECT.*", r".*SELEC.*"],
            [0, 1080, 720, 100],
        )
        if not marker or not marker.hit:
            return self._stop_unsupported(context, screen_state, "selected_detail_probe_requires_selected_hand")
        reader = ExamStateReader.from_context(context)
        detections = [detection for detection in reader._read_detections() if not detection.suppressed_reason]
        title, raw_title, title_confidence = self._read_selected_card_title(context, image, build_card_name_dict())
        targets = [
            detection
            for detection in detections
            if normalize_card_name(detection.card_name.rstrip("+-")) == title
        ]
        if not title or len(targets) != 1:
            return self._stop_unsupported(context, screen_state, "selected_detail_probe_target_not_unique")
        target = targets[0]
        evidence = self._capture_evidence(image, f"{screen_state}_selected_hand_detail")
        self._record_journal(
            screen_state,
            "probe_selected_hand_detail",
            "verified",
            details={
                "box": list(target.box),
                "yolo_label": target.label,
                "yolo_confidence": target.confidence,
                "caption_raw": target.raw_card_name,
                "caption_confidence": target.card_name_confidence,
                "detail_title": title,
                "detail_title_raw": raw_title,
                "detail_title_confidence": title_confidence,
                "controller_inputs": 0,
            },
            before=evidence,
        )
        return self._finish_observation(context, screen_state)

    def _probe_turn_roi_candidates(self, context: Context, image, screen_state: str) -> bool:
        """零输入比较多组剩余回合 ROI，记录 OCR 原文后停止。"""

        if not self._matches_screen_profile(context, image, screen_state):
            return self._stop_unsupported(context, screen_state, "round_page_not_confirmed_before_turn_probe")
        candidates = (
            (13, 43, 120, 128),
            (25, 70, 100, 80),
            (35, 72, 80, 76),
            (43, 75, 60, 72),
            (50, 80, 45, 58),
        )
        reads = []
        for index, roi in enumerate(candidates):
            result = self._run_ocr(
                context,
                image,
                f"ProduceRecognitionHIFTurnRoiProbe{index}",
                [r".*\d+.*"],
                list(roi),
            )
            best = getattr(result, "best_result", None) if result and result.hit else None
            reads.append(
                {
                    "roi": list(roi),
                    "raw": str(getattr(best, "text", "")) if best else "",
                    "confidence": float(getattr(best, "score", 0.0)) if best else 0.0,
                    "box": list(getattr(best, "box", [])) if best else [],
                }
            )
        evidence = self._capture_evidence(image, f"{screen_state}_turn_roi_probe")
        self._record_journal(
            screen_state,
            "probe_turn_rois",
            "observed",
            details={"reads": reads, "controller_inputs": 0},
            before=evidence,
        )
        return self._finish_observation(context, screen_state)

    def _probe_counter_roi_candidates(self, context: Context, image, screen_state: str) -> bool:
        """零输入采集再演/技能卡使用次数的候选区域，不根据读数推导状态。"""

        if not self._matches_screen_profile(context, image, screen_state):
            return self._stop_unsupported(context, screen_state, "round_page_not_confirmed_before_counter_probe")
        candidates = {
            "good_condition_current": (14, 237, 160, 70),
            "good_condition_label_and_value": (52, 245, 130, 50),
            "good_condition_value_only": (60, 255, 110, 38),
            "good_condition_sweep_45": (45, 245, 140, 50),
            "good_condition_sweep_50": (50, 250, 135, 45),
            "focus_current": (14, 300, 150, 70),
            "focus_label_and_value": (52, 306, 90, 48),
            "focus_value_only": (58, 314, 50, 34),
            "focus_sweep_40": (40, 300, 80, 60),
            "focus_sweep_45": (45, 306, 70, 48),
            "focus_sweep_48": (48, 310, 60, 42),
            "focus_sweep_50": (50, 314, 55, 36),
            "current_score": (367, 119, 123, 45),
            "stage_multiplier": (65, 75, 150, 48),
            "right_skill_card_uses": (580, 235, 110, 75),
            "left_reprise_counter": (12, 638, 150, 100),
            "left_reprise_turn_limit": (8, 674, 180, 70),
        }
        reads = {}
        for name, roi in candidates.items():
            result = self._run_ocr(
                context,
                image,
                f"ProduceRecognitionHIFCounterRoiProbe_{name}",
                [r".*\d+.*"],
                list(roi),
            )
            best = getattr(result, "best_result", None) if result and result.hit else None
            reads[name] = {
                "roi": list(roi),
                "raw": str(getattr(best, "text", "")) if best else "",
                "confidence": float(getattr(best, "score", 0.0)) if best else 0.0,
                "box": list(getattr(best, "box", [])) if best else [],
            }
        evidence = self._capture_evidence(image, f"{screen_state}_counter_roi_probe")
        self._record_journal(
            screen_state,
            "probe_counter_rois",
            "observed",
            details={"reads": reads, "controller_inputs": 0},
            before=evidence,
        )
        return self._finish_observation(context, screen_state)

    def _probe_status_detail(self, context: Context, image, screen_state: str, slot: int) -> bool:
        """点击当前证据帧中的一个状态图标，记录 tooltip 后原位关闭。"""

        slot_centers = {3: 378, 4: 440, 5: 503, 6: 566, 7: 629, 8: 691, 9: 754}
        center_y = slot_centers.get(slot)
        if center_y is None:
            return self._stop_unsupported(context, screen_state, "status_detail_slot_not_supported")
        if not self._matches_screen_profile(context, image, screen_state):
            return self._stop_unsupported(context, screen_state, "round_page_not_confirmed_before_status_detail")
        before = self._capture_evidence(image, f"{screen_state}_status_{slot}_before")
        icon_roi = [15, center_y - 25, 55, 50]
        if not self._click_box_center(context, icon_roi, double=False):
            return self._stop_unsupported(context, screen_state, "status_detail_open_click_failed")
        time.sleep(self.CLICK_DELAY)
        detail_image = self._get_screenshot_or_stop(context, "status_detail")
        if detail_image is None:
            return True
        detail_evidence = self._capture_evidence(detail_image, f"{screen_state}_status_{slot}_opened")
        if not frame_changed(before, detail_evidence):
            return self._stop_unsupported(context, screen_state, "status_detail_not_opened")
        detail = self._run_ocr(
            context,
            detail_image,
            f"ProduceRecognitionHIFStatusDetail{slot}",
            [r".*"],
            [70, 160, 620, 920],
        )
        reads = []
        for result in getattr(detail, "all_results", ()) if detail else ():
            text = str(getattr(result, "text", "")).strip()
            if text:
                reads.append(
                    {
                        "text": text,
                        "score": float(getattr(result, "score", 0.0)),
                        "box": list(getattr(result, "box", [])),
                    }
                )
        self._record_journal(
            "status_detail",
            "probe_status_detail",
            "observed",
            details={"slot": slot, "icon_roi": icon_roi, "reads": reads, "controller_inputs": 1},
            before=before,
            after=detail_evidence,
        )
        close = self._run_ocr(
            context,
            detail_image,
            "ProduceRecognitionHIFStatusDetailClose",
            [r".*閉じる.*"],
            [180, 1080, 360, 140],
        )
        close_box = list(getattr(getattr(close, "best_result", None), "box", [])) if close and close.hit else []
        if len(close_box) != 4 or not self._click_box_center(context, close_box, double=False):
            return self._stop_unsupported(context, "status_detail", "status_detail_close_not_confirmed")
        time.sleep(self.CLICK_DELAY)
        returned_image = self._get_screenshot_or_stop(context, screen_state)
        if returned_image is None:
            return True
        returned = self._capture_evidence(returned_image, f"{screen_state}_status_{slot}_returned")
        if not frame_changed(detail_evidence, returned):
            return self._stop_unsupported(context, "status_detail", "round_page_not_changed_after_status_detail_close")
        if not self._matches_screen_profile(context, returned_image, screen_state):
            return self._close_status_detail(context, returned_image, screen_state)
        self._record_journal(
            "status_detail",
            "close_status_detail",
            "verified",
            details={"slot": slot, "icon_roi": icon_roi, "controller_inputs": 2},
            before=detail_evidence,
            after=returned,
        )
        return self._finish_observation(context, screen_state)

    def _close_status_detail(self, context: Context, image, screen_state: str) -> bool:
        """从已打开的效果详情弹窗走明确关闭按钮恢复 Round。"""

        title = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFStatusDetailTitleForClose",
            [r".*効果詳細.*"],
            [20, 100, 680, 120],
        )
        close = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFStatusDetailCloseRecovery",
            [r".*閉じる.*"],
            [180, 1080, 360, 140],
        )
        close_box = list(getattr(getattr(close, "best_result", None), "box", [])) if close and close.hit else []
        controller_inputs = 0
        current_image = image
        before = self._capture_evidence(image, "status_detail_close_recovery_before")
        if title and title.hit:
            if len(close_box) != 4 or not self._click_box_center(context, close_box, double=False):
                return self._stop_unsupported(context, "status_detail", "status_detail_close_recovery_click_failed")
            controller_inputs += 1
            time.sleep(self.CLICK_DELAY)
            current_image = self._get_screenshot_or_stop(context, "status_effect_list")
            if current_image is None:
                return True
        if self._matches_screen_profile(context, current_image, screen_state):
            returned = self._capture_evidence(current_image, "status_detail_close_recovery_after")
            self._record_journal(
                "status_detail",
                "close_status_detail_recovery",
                "verified",
                details={"close_box": close_box, "controller_inputs": controller_inputs},
                before=before,
                after=returned,
            )
            return self._finish_observation(context, screen_state)

        list_anchor = self._run_ocr(
            context,
            current_image,
            "ProduceRecognitionHIFStatusEffectList",
            [r".*お姉さんの感覚.*", r".*発動予約.*", r".*パラメータ上昇量増加.*"],
            [20, 20, 680, 720],
        )
        if not list_anchor or not list_anchor.hit:
            return self._stop_unsupported(context, "status_detail", "status_effect_list_not_confirmed")
        list_reads = []
        for result in getattr(list_anchor, "all_results", ()):
            text = str(getattr(result, "text", "")).strip()
            if text:
                list_reads.append(
                    {
                        "text": text,
                        "score": float(getattr(result, "score", 0.0)),
                        "box": list(getattr(result, "box", [])),
                    }
                )
        active_effects = parse_active_effects(read["text"] for read in list_reads)
        list_before = self._capture_evidence(current_image, "status_effect_list_before_close")
        list_close_roi = [320, 710, 80, 90]
        if not self._click_box_center(context, list_close_roi, double=False):
            return self._stop_unsupported(context, "status_detail", "status_effect_list_close_click_failed")
        controller_inputs += 1
        time.sleep(self.CLICK_DELAY)
        returned_image = self._get_screenshot_or_stop(context, screen_state)
        if returned_image is None:
            return True
        returned = self._capture_evidence(returned_image, "status_effect_list_closed")
        if not self._matches_screen_profile(context, returned_image, screen_state):
            return self._stop_unsupported(context, "status_detail", "status_effect_list_close_failed")
        self._record_journal(
            "status_detail",
            "close_status_effect_list",
            "verified",
            details={
                "detail_close_box": close_box,
                "list_close_roi": list_close_roi,
                "reads": list_reads,
                "active_effects": active_effects.to_journal(),
                "controller_inputs": controller_inputs,
            },
            before=list_before,
            after=returned,
        )
        return self._finish_observation(context, screen_state)

    def _probe_named_status_effect(self, context: Context, image, screen_state: str, effect_name: str) -> bool:
        """从已确认的状态图标进入效果列表，再按完整名称读取指定效果详情。"""

        if effect_name not in {"消費体力減少"}:
            return self._stop_unsupported(context, screen_state, "status_effect_name_not_authorized")
        if not self._matches_screen_profile(context, image, screen_state):
            return self._stop_unsupported(context, screen_state, "round_page_not_confirmed_before_named_status_probe")
        icon_roi = [15, 604, 55, 50]
        if not self._click_box_center(context, icon_roi, double=False):
            return self._stop_unsupported(context, screen_state, "named_status_initial_detail_open_failed")
        time.sleep(self.CLICK_DELAY)
        detail_image = self._get_screenshot_or_stop(context, "status_detail")
        if detail_image is None:
            return True
        close = self._run_ocr(
            context,
            detail_image,
            "ProduceRecognitionHIFNamedStatusInitialClose",
            [r".*閉じる.*"],
            [180, 1080, 360, 140],
        )
        close_box = list(getattr(getattr(close, "best_result", None), "box", [])) if close and close.hit else []
        if len(close_box) == 4:
            if not self._click_box_center(context, close_box, double=False):
                return self._stop_unsupported(context, "status_detail", "named_status_initial_close_failed")
            time.sleep(self.CLICK_DELAY)
            list_image = self._get_screenshot_or_stop(context, "status_effect_list")
            if list_image is None:
                return True
        else:
            list_anchor = self._run_ocr(
                context,
                detail_image,
                "ProduceRecognitionHIFNamedStatusListAnchor",
                [r".*お姉さんの感覚.*", r".*発動予約.*", r".*パラメータ上昇量増加.*"],
                [20, 20, 680, 720],
            )
            if not list_anchor or not list_anchor.hit:
                return self._stop_unsupported(context, "status_effect_list", "named_status_list_not_confirmed")
            list_image = detail_image
        target = self._run_ocr(
            context,
            list_image,
            "ProduceRecognitionHIFNamedStatusTarget",
            [rf".*{re.escape(effect_name)}.*"],
            [20, 20, 680, 740],
        )
        target_box = list(getattr(getattr(target, "best_result", None), "box", [])) if target and target.hit else []
        icon_target = [50, target_box[1] - 20, 90, 75] if len(target_box) == 4 else []
        if len(icon_target) != 4 or not self._click_box_center(context, icon_target, double=False):
            return self._stop_unsupported(context, "status_effect_list", "named_status_target_not_confirmed")
        time.sleep(self.CLICK_DELAY)
        named_image = self._get_screenshot_or_stop(context, "status_detail")
        if named_image is None:
            return True
        named_title = self._run_ocr(
            context,
            named_image,
            "ProduceRecognitionHIFNamedStatusDetailTitle",
            [r".*効果詳細.*"],
            [20, 100, 680, 120],
        )
        if not named_title or not named_title.hit:
            return self._stop_unsupported(context, "status_effect_list", "named_status_detail_not_opened")
        named_evidence = self._capture_evidence(named_image, f"status_effect_{effect_name}")
        detail = self._run_ocr(
            context,
            named_image,
            "ProduceRecognitionHIFNamedStatusDetail",
            [r".*"],
            [20, 100, 680, 1000],
        )
        reads = []
        for result in getattr(detail, "all_results", ()) if detail else ():
            text = str(getattr(result, "text", "")).strip()
            if text:
                reads.append(
                    {
                        "text": text,
                        "score": float(getattr(result, "score", 0.0)),
                        "box": list(getattr(result, "box", [])),
                    }
                )
        self._record_journal(
            "status_detail",
            "probe_named_status_effect",
            "observed",
            details={"effect_name": effect_name, "reads": reads, "controller_inputs": 3},
            before=named_evidence,
        )
        # 复用双层正式恢复：当前是单项详情，随后自动关闭效果列表。
        return self._close_status_detail(context, named_image, screen_state)

    def _probe_round_details_metrics(
        self,
        context: Context,
        image,
        screen_state: str,
        *,
        continue_after: bool = False,
    ) -> bool | tuple[str, str, Any]:
        """进入已采证的详情面板读取实时分数与倍率，再验证返回同一 Round。

        详情入口和关闭按钮均为只读 UI；本动作不触碰手牌、饮料、重抽或任何资源。
        参数三维值在该面板中并不显示，必须明确记为不可用，不能把排名卡数值代替。
        """

        if not self._matches_screen_profile(context, image, screen_state):
            return self._stop_unsupported(context, screen_state, "round_page_not_confirmed_before_details_probe")
        before = self._capture_evidence(image, f"{screen_state}_details_probe_before")
        details_button = [422, 1160, 76, 76]
        if not self._click_box_center(context, details_button, double=False):
            return self._stop_unsupported(context, screen_state, "round_details_open_click_failed")
        time.sleep(self.ACTION_DELAY)
        panel_image = self._get_screenshot_or_stop(context, "round_details")
        if panel_image is None:
            return True
        panel_evidence = self._capture_evidence(panel_image, "round_details_metrics_panel_opened")
        if not frame_changed(before, panel_evidence):
            return self._stop_unsupported(context, screen_state, "round_details_not_confirmed")

        # 2026-07-15 实机面板带“獲得スコア / 審査基準”双锚点。旧 screen
        # profile 的“手札情報確認”锚点只适用于另一种内容滚动位置，不能据此
        # 把当前可读指标页误判成未知页。
        score_anchor = self._run_ocr(
            context, panel_image, "ProduceRecognitionHIFRoundMetricsScoreAnchor", ("獲得スコア",), [32, 118, 220, 52]
        )
        judge_anchor = self._run_ocr(
            context, panel_image, "ProduceRecognitionHIFRoundMetricsJudgeAnchor", (r"審[査查]基準",), [520, 125, 160, 58]
        )
        if score_anchor and score_anchor.hit and judge_anchor and judge_anchor.hit:
            calibration = load_hif_roi_calibration()
            score_roi = calibration.roi_for_round_metric_panel("current_score")
            multiplier_roi = calibration.roi_for_round_metric("stage_multiplier")
            if score_roi is None or multiplier_roi is None:
                return self._stop_unsupported(context, "round_metrics_panel", "round_metrics_roi_not_calibrated")
            score_result = self._run_ocr(
                context,
                panel_image,
                "ProduceRecognitionHIFHandHistoryCurrentScore",
                [r"\d+"],
                list(score_roi),
            )
            score_best = getattr(score_result, "best_result", None) if score_result and score_result.hit else None
            multiplier_result = self._run_ocr(
                context,
                image,
                "ProduceRecognitionHIFRoundCurrentMultiplier",
                [r".*\d+.*%"],
                list(multiplier_roi),
            )
            multiplier_best = getattr(multiplier_result, "best_result", None) if multiplier_result and multiplier_result.hit else None
            self._record_journal(
                "round_metrics_panel",
                "observe_round_metrics",
                "observed",
                details={
                    "reads": {
                        "current_score": {
                            "roi": list(score_roi),
                            "raw": str(getattr(score_best, "text", "")) if score_best else "",
                            "confidence": float(getattr(score_best, "score", 0.0)) if score_best else 0.0,
                        },
                        "stage_multiplier": {
                            "roi": list(multiplier_roi),
                            "raw": str(getattr(multiplier_best, "text", "")) if multiplier_best else "",
                            "confidence": float(getattr(multiplier_best, "score", 0.0)) if multiplier_best else 0.0,
                        },
                    },
                    "params_available": False,
                    "controller_inputs": 1,
                },
                before=panel_evidence,
            )
            close = [314, 1118, 92, 92]
            if not self._click_box_center(context, close, double=False):
                return self._stop_unsupported(context, "round_metrics_panel", "round_metrics_panel_close_failed")
            time.sleep(self.ACTION_DELAY)
            returned_image = self._get_screenshot_or_stop(context, screen_state)
            if returned_image is None:
                return True
            returned = self._capture_evidence(returned_image, f"{screen_state}_after_hand_history_metrics")
            if not frame_changed(panel_evidence, returned) or not self._matches_screen_profile(context, returned_image, screen_state):
                return self._stop_unsupported(context, "round_metrics_panel", "round_page_not_restored_after_metrics")
            self._record_journal(
                "round_metrics_panel",
                "close_round_metrics",
                "verified",
                details={"close_roi": close, "controller_inputs": 2},
                before=panel_evidence,
                after=returned,
            )
            if continue_after:
                return (
                    str(getattr(score_best, "text", "")) if score_best else "",
                    str(getattr(multiplier_best, "text", "")) if multiplier_best else "",
                    returned_image,
                )
            return self._finish_observation(context, screen_state)
        if continue_after:
            return self._stop_unsupported(context, screen_state, "round_metrics_panel_not_supported_for_decision")
        # 早期样本中的“手札履历”仍按原契约处理；此处只接受两种已采证页面。
        if self._matches_screen_profile(context, panel_image, "hand_history_view"):
            return self._stop_unsupported(context, "hand_history_view", "legacy_hand_history_metrics_not_supported")
        if not self._matches_screen_profile(context, panel_image, "round_details"):
            return self._stop_unsupported(context, screen_state, "round_details_not_confirmed")

        details_image = panel_image
        details_evidence = self._capture_evidence(details_image, "round_details_metrics_observed")

        candidates = {
            "current_score": ((42, 140, 130, 52), [r"\\d+"]),
            "judge_threshold": ((528, 168, 120, 54), [r"\\d+"]),
            "stage_multiplier": ((230, 445, 230, 68), [r".*\\d+.*%"]),
        }
        reads: dict[str, dict[str, Any]] = {}
        for name, (roi, expected) in candidates.items():
            result = self._run_ocr(context, details_image, f"ProduceRecognitionHIFRoundDetails_{name}", expected, list(roi))
            best = getattr(result, "best_result", None) if result and result.hit else None
            reads[name] = {
                "roi": list(roi),
                "raw": str(getattr(best, "text", "")) if best else "",
                "confidence": float(getattr(best, "score", 0.0)) if best else 0.0,
                "box": list(getattr(best, "box", [])) if best else [],
            }
        self._record_journal(
            "round_details",
            "observe_round_details_metrics",
            "observed",
            details={"reads": reads, "params_available": False, "controller_inputs": 2},
            before=before,
            after=details_evidence,
        )

        profile = load_hif_screen_profiles().get("round_details")
        close = profile.regions.get("close") if profile else None
        if close is None or not self._click_box_center(context, list(close), double=False):
            return self._stop_unsupported(context, "round_details", "round_details_close_failed")
        time.sleep(self.ACTION_DELAY)
        returned_image = self._get_screenshot_or_stop(context, screen_state)
        if returned_image is None:
            return True
        returned = self._capture_evidence(returned_image, f"{screen_state}_details_probe_returned")
        if not frame_changed(details_evidence, returned) or not self._matches_screen_profile(context, returned_image, screen_state):
            return self._stop_unsupported(context, "round_details", "round_page_not_restored_after_details_probe")
        self._record_journal(
            "round_details",
            "close_round_details_metrics",
            "verified",
            details={"close_roi": list(close), "controller_inputs": 3},
            before=details_evidence,
            after=returned,
        )
        return self._finish_observation(context, screen_state)

    def _probe_round_hand_details(
        self,
        context: Context,
        image,
        screen_state: str,
        *,
        allow_selected_start: bool = False,
        return_details: bool = False,
        post_execution: bool = False,
    ) -> bool | list[dict[str, Any]]:
        """逐张打开手牌详情读取标题；只切换选中态，绝不点击同一张牌两次。"""

        if not self._matches_screen_profile(context, image, screen_state):
            return self._stop_unsupported(context, screen_state, "round_page_not_confirmed_before_hand_probe")
        selected = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSelectedCardMarkerProbePreflight",
            [r".*SELECT.*", r".*SELEC.*"],
            [0, 1080, 720, 100],
        )
        selected_at_start = bool(selected and selected.hit)
        if selected_at_start and not allow_selected_start:
            return self._stop_unsupported(context, screen_state, "round_hand_probe_requires_unselected_hand")
        if allow_selected_start and not selected_at_start:
            return self._stop_unsupported(context, screen_state, "round_hand_probe_requires_selected_hand")
        session = get_runtime_hif_session()
        probe_started = "round_post_hand_probe_started" if post_execution else "round_hand_probe_started"
        if getattr(session, probe_started):
            return self._stop_unsupported(context, screen_state, "round_hand_probe_already_started")
        setattr(session, probe_started, True)
        reader = ExamStateReader.from_context(context)
        detections = sorted(
            (detection for detection in reader._read_detections() if not detection.suppressed_reason),
            key=lambda detection: detection.box[0],
        )
        if len(detections) < 3 or len(detections) > 5:
            return self._stop_unsupported(context, screen_state, "round_hand_probe_card_count_not_supported")
        observed = []
        previous_box = None
        if selected_at_start:
            title, raw_title, title_confidence = self._read_selected_card_title(context, image, build_card_name_dict())
            selected_targets = [
                detection
                for detection in detections
                if normalize_card_name(detection.card_name.rstrip("+-")) == title
            ]
            selected_detection = selected_targets[0] if len(selected_targets) == 1 else self._selected_marker_detection(selected, detections)
            if not title or selected_detection is None:
                best = getattr(selected, "best_result", None)
                marker_box = getattr(best, "box", None)
                try:
                    marker_box = list(marker_box)
                except TypeError:
                    marker_box = []
                self._record_journal(
                    screen_state,
                    "probe_selected_hand_mapping",
                    "rejected",
                    details={
                        "detail_title": title,
                        "title_match_count": len(selected_targets),
                        "selected_marker_box": marker_box,
                        "detections": [
                            {"box": list(detection.box), "card_name": detection.card_name, "label": detection.label}
                            for detection in detections
                        ],
                    },
                )
                return self._stop_unsupported(context, screen_state, "round_hand_probe_selected_target_not_unique")
            selected_details = {
                "index": detections.index(selected_detection) + 1,
                "box": list(selected_detection.box),
                "yolo_label": selected_detection.label,
                "yolo_confidence": selected_detection.confidence,
                "caption_raw": selected_detection.raw_card_name,
                "caption_confidence": selected_detection.card_name_confidence,
                "detail_title": title,
                "detail_title_raw": raw_title,
                "detail_title_confidence": title_confidence,
                "already_selected": True,
            }
            observed.append(selected_details)
            session.record_hand_detail_name(selected_detection.box, title)
            selected_evidence = self._capture_evidence(image, f"{screen_state}_hand_probe_selected_start")
            self._record_journal(
                screen_state,
                "probe_hand_card_detail",
                "verified",
                details=selected_details,
                before=selected_evidence,
            )
            detections = [detection for detection in detections if detection is not selected_detection]

        for index, detection in enumerate(detections, start=1):
            if previous_box == detection.box:
                return self._stop_unsupported(context, screen_state, "round_hand_probe_duplicate_target")
            before = self._capture_evidence(image, f"{screen_state}_hand_probe_{index}_before")
            if not self._click_box_center(context, list(detection.box), double=False):
                return self._stop_unsupported(context, screen_state, "round_hand_probe_click_failed")
            previous_box = detection.box
            time.sleep(self.ACTION_DELAY)
            image = self._get_screenshot_or_stop(context, screen_state)
            if image is None:
                return True
            after = self._capture_evidence(image, f"{screen_state}_hand_probe_{index}_selected")
            if not frame_changed(before, after) or not self._matches_screen_profile(context, image, screen_state):
                return self._stop_unsupported(context, screen_state, "round_hand_probe_selection_not_confirmed")
            marker = None
            title = raw_title = ""
            title_confidence = 0.0
            for title_attempt in range(3):
                marker = self._run_ocr(
                    context,
                    image,
                    "ProduceRecognitionHIFSelectedCardMarkerProbe",
                    [r".*SELECT.*", r".*SELEC.*"],
                    [0, 1080, 720, 100],
                )
                title, raw_title, title_confidence = self._read_selected_card_title(context, image, build_card_name_dict())
                if marker and marker.hit and title:
                    break
                if title_attempt < 2:
                    time.sleep(self.CLICK_DELAY)
                    image = self._get_screenshot_or_stop(context, screen_state)
                    if image is None or not self._matches_screen_profile(context, image, screen_state):
                        return self._stop_unsupported(context, screen_state, "round_hand_probe_selection_lost_during_title_read")
            if not marker or not marker.hit or not title:
                return self._stop_unsupported(context, screen_state, "round_hand_probe_title_not_confirmed")
            details = {
                "index": index,
                "box": list(detection.box),
                "yolo_label": detection.label,
                "yolo_confidence": detection.confidence,
                "caption_raw": detection.raw_card_name,
                "caption_confidence": detection.card_name_confidence,
                "detail_title": title,
                "detail_title_raw": raw_title,
                "detail_title_confidence": title_confidence,
            }
            observed.append(details)
            session.record_hand_detail_name(detection.box, title)
            self._record_journal(screen_state, "probe_hand_card_detail", "verified", details=details, before=before, after=after)
        self._record_journal(
            screen_state,
            "probe_hand_details",
            "verified",
            details={"cards": observed, "leaves_last_card_selected": True},
        )
        if return_details:
            return observed
        return self._finish_observation(context, screen_state)

    def _confirm_preselected_card(
        self,
        context: Context,
        image,
        screen_state: str,
        round_: ExamRound,
        total_turns: int,
        round_key: str,
        target_name: str,
    ) -> bool:
        """恢复已通过首次点击选中的卡牌，仅执行绑定目标的第二次点击。"""

        before = self._capture_evidence(image, f"{screen_state}_preselected_before")
        if not self._matches_screen_profile(context, image, screen_state) or not self._card_selection_confirmed(context, image, target_name):
            return self._stop_unsupported(context, screen_state, "preselected_card_not_confirmed")
        reader = ExamStateReader.from_context(context)
        detections = reader._read_detections()
        targets = [
            detection
            for detection in detections
            if not detection.suppressed_reason
            and detection.label != "useless"
            and normalize_card_name(detection.card_name) == target_name
        ]
        if len(targets) != 1:
            return self._stop_unsupported(context, screen_state, "preselected_card_target_not_unique")
        target = targets[0]
        if not self._click_box_center(context, list(target.box), double=False):
            return self._stop_unsupported(context, screen_state, "preselected_card_click_failed")
        time.sleep(self.ACTION_DELAY)
        after_image = self._get_screenshot_or_stop(context, screen_state)
        if after_image is None:
            return True
        after = self._capture_evidence(after_image, f"{screen_state}_preselected_after")
        ok, details = self._read_card_postcondition(
            context,
            after_image,
            screen_state,
            round_,
            total_turns,
            target,
            detections,
        )
        if not ok:
            reason = str(details.get("reason", "preselected_card_postcondition_failed"))
            self._record_journal(
                screen_state,
                "confirm_selected_card",
                "unverified",
                details={**details, "reason": reason, "card": target_name},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, screen_state, reason)
        self._record_journal(
            screen_state,
            "confirm_selected_card",
            "verified",
            details={**details, "card": target_name},
            before=before,
            after=after,
        )
        get_runtime_hif_session().record_card(round_key, target_name)
        return self._finish_observation(context, round_key)

    def _probe_round_deck_size(self, context: Context, image, screen_state: str):
        """打开只读持有卡列表读取总数，关闭后必须回到同一 Round。"""

        initial = self._capture_evidence(image, f"{screen_state}_deck_probe_initial")

        if self._matches_screen_profile(context, image, "hand_history_view"):
            hand_evidence = self._capture_evidence(image, "hand_history_observed")
            self._record_journal(
                "hand_history_view",
                "observe_hand_history",
                "observed",
                details={"visible_hand_card_count": 3, "reason": "read_only_hand_evidence"},
                before=hand_evidence,
            )
            hand_close = self._find_text_option(
                context,
                image,
                ("閉じる",),
                self._observed_button_roi("hand_history_view", "close", [225, 1110, 275, 100]),
            )
            if hand_close is None or not self._click_box_center(context, hand_close.best_result.box, double=False):
                self._stop_unsupported(context, "hand_history_view", "hand_history_close_failed")
                return None, None
            time.sleep(self.ACTION_DELAY)
            image = self._get_screenshot_or_stop(context, "round_details")
            if image is None:
                return None, None
            details_after_hand = self._capture_evidence(image, "round_details_after_hand_history")
            if not frame_changed(hand_evidence, details_after_hand) or not self._matches_screen_profile(context, image, "round_details"):
                self._stop_unsupported(context, "hand_history_view", "round_details_not_restored_after_hand_history")
                return None, None
            self._record_journal(
                "hand_history_view",
                "close_hand_history",
                "verified",
                before=hand_evidence,
                after=details_after_hand,
            )

        if self._matches_screen_profile(context, image, "round_details"):
            details_before = self._capture_evidence(image, "round_details_before_close")
            details_profile = load_hif_screen_profiles().get("round_details")
            details_close = details_profile.regions.get("close") if details_profile else None
            if details_close is None or not self._click_box_center(context, list(details_close), double=False):
                self._stop_unsupported(context, "round_details", "round_details_close_failed")
                return None, None
            time.sleep(self.ACTION_DELAY)
            image = self._get_screenshot_or_stop(context, screen_state)
            if image is None:
                return None, None
            round_after_details = self._capture_evidence(image, f"{screen_state}_after_details")
            if not frame_changed(details_before, round_after_details) or not self._matches_screen_profile(context, image, screen_state):
                self._stop_unsupported(context, "round_details", "round_page_not_restored_after_details")
                return None, None
            self._record_journal(
                "round_details",
                "close_round_details",
                "verified",
                details={"close_roi": list(details_close)},
                before=details_before,
                after=round_after_details,
            )

        if not self._matches_screen_profile(context, image, screen_state):
            self._stop_unsupported(context, screen_state, "round_page_not_confirmed_before_deck_probe")
            return None, None
        profile = load_hif_screen_profiles().get(screen_state)
        deck_button = profile.regions.get("deck_button") if profile else None
        if deck_button is None:
            self._stop_unsupported(context, screen_state, "round_deck_button_not_calibrated")
            return None, None
        before = self._capture_evidence(image, f"{screen_state}_deck_probe_before")
        if not self._click_box_center(context, list(deck_button), double=False):
            self._stop_unsupported(context, screen_state, "round_deck_button_click_failed")
            return None, None
        time.sleep(self.ACTION_DELAY)
        deck_image = self._get_screenshot_or_stop(context, "skill_deck_view")
        if deck_image is None:
            return None, None
        deck_evidence = self._capture_evidence(deck_image, "skill_deck_view_opened")
        if not frame_changed(before, deck_evidence) or not self._matches_screen_profile(context, deck_image, "skill_deck_view"):
            self._stop_unsupported(context, screen_state, "skill_deck_view_not_confirmed")
            return None, None
        self._record_journal(
            screen_state,
            "open_skill_deck",
            "verified",
            details={"button_roi": list(deck_button)},
            before=before,
            after=deck_evidence,
        )
        deck_profile = load_hif_screen_profiles().get("skill_deck_view")
        tab_roi = list(deck_profile.regions["tab"]) if deck_profile and "tab" in deck_profile.regions else [27, 1010, 666, 74]
        count_read = self._run_ocr(
            context,
            deck_image,
            "ProduceRecognitionHIFRoundDeckCount",
            [r".*スキルカード.*\d+.*"],
            tab_roi,
        )
        count_text = str(getattr(getattr(count_read, "best_result", None), "text", "")) if count_read and count_read.hit else ""
        match = re.search(r"[（(](\d+)[）)]", count_text)
        if match is None:
            self._stop_unsupported(context, "skill_deck_view", "round_deck_count_not_readable")
            return None, None
        deck_size = int(match.group(1))
        close = self._find_text_option(
            context,
            deck_image,
            ("閉じる",),
            self._observed_button_roi("skill_deck_view", "close", [232, 1119, 256, 82]),
        )
        if close is None or not self._click_box_center(context, close.best_result.box, double=False):
            self._stop_unsupported(context, "skill_deck_view", "round_deck_close_failed")
            return None, None
        time.sleep(self.ACTION_DELAY)
        returned_image = self._get_screenshot_or_stop(context, screen_state)
        if returned_image is None:
            return None, None
        returned = self._capture_evidence(returned_image, f"{screen_state}_deck_probe_returned")
        if not self._matches_screen_profile(context, returned_image, screen_state):
            self._stop_unsupported(context, "skill_deck_view", "round_page_not_restored_after_deck_probe")
            return None, None
        self._record_journal(
            "skill_deck_view",
            "close_skill_deck",
            "verified",
            details={"deck_size": deck_size},
            before=deck_evidence,
            after=returned,
        )
        self._record_journal(
            screen_state,
            "probe_deck_size",
            "verified",
            details={"deck_size": deck_size},
            before=initial,
            after=returned,
        )
        return deck_size, returned_image

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

        confirm_selected_card = params.get("confirm_selected_card")
        if isinstance(confirm_selected_card, str) and confirm_selected_card:
            if mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, screen_state, "confirm_selected_card_requires_single_step")
            return self._confirm_preselected_card(
                context,
                before_image,
                screen_state,
                round_,
                total_turns,
                round_key,
                normalize_card_name(confirm_selected_card),
            )

        if params.get("round_probe") == "hand_details":
            probe_mode = parse_execution_mode(params.get("round_probe_execution_mode"))
            if probe_mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, screen_state, "round_hand_probe_requires_single_step")
            try:
                return self._probe_round_hand_details(context, before_image, screen_state)
            except Exception as error:
                reason = f"round_hand_probe_exception:{type(error).__name__}"
                self._record_journal(
                    screen_state,
                    "probe_hand_details",
                    "rejected",
                    details={"reason": reason, "error": str(error)},
                    before=before,
                )
                return self._stop_unsupported(context, screen_state, reason)
        if params.get("round_probe") in {
            "hand_details_map_observe",
            "hand_details_map_deck_observe",
            "hand_details_map_deck_observe_from_selected",
            "hand_details_map_deck_select_one_from_selected",
            "hand_details_map_deck_play_one",
            "hand_details_map_deck_select_explicit",
        }:
            probe_mode = parse_execution_mode(params.get("round_probe_execution_mode"))
            if probe_mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, screen_state, "round_hand_probe_requires_single_step")
            reader = ExamStateReader.from_context(context)
            health = self._get_health(context, before_image)
            observation = reader.read_exam_observation(round_, total_turns, health["current"] if health else None)
            initial_turn = observation.state.turn
            missing_before = observation.missing_fields
            try:
                details = self._probe_round_hand_details(
                    context,
                    before_image,
                    screen_state,
                    allow_selected_start=params.get("round_probe") == "hand_details_map_deck_observe_from_selected",
                    return_details=True,
                )
            except Exception as error:
                reason = f"round_hand_probe_exception:{type(error).__name__}"
                self._record_journal(
                    screen_state,
                    "probe_hand_details_map",
                    "rejected",
                    details={"reason": reason, "error": str(error)},
                    before=before,
                )
                return self._stop_unsupported(context, screen_state, reason)
            if not isinstance(details, list):
                return True
            session = get_runtime_hif_session()
            active = self._complete_current_run_hand_observation(observation, session)
            topic_action = None
            if params.get("round_probe") in {
                "hand_details_map_deck_observe",
                "hand_details_map_deck_observe_from_selected",
                "hand_details_map_deck_select_one_from_selected",
                "hand_details_map_deck_play_one",
                "hand_details_map_deck_select_explicit",
            }:
                selected_image = self._get_screenshot_or_stop(context, screen_state)
                if selected_image is None:
                    return True
                deck_size, returned_image = self._probe_round_deck_size(context, selected_image, screen_state)
                if deck_size is None or returned_image is None:
                    return True
                selected_marker = self._run_ocr(
                    context,
                    returned_image,
                    "ProduceRecognitionHIFSelectedCardMarkerAfterDeckProbe",
                    [r".*SELECT.*", r".*SELEC.*"],
                    [0, 1080, 720, 100],
                )
                if selected_marker and selected_marker.hit:
                    return self._stop_unsupported(context, screen_state, "deck_probe_did_not_clear_selected_hand")
                post_health = self._get_health(context, returned_image)
                observation = reader.read_exam_observation(round_, total_turns, post_health["current"] if post_health else None)
                if observation.state.turn <= 0 < initial_turn:
                    observation.state.turn = initial_turn
                    observation.numerics["turn"] = NumericRead("turn", f"retained_initial={initial_turn}", initial_turn)
                observation.numerics["deck_size"] = NumericRead("deck_size", str(deck_size), deck_size)
                observation.state.deck_size = deck_size
                observation.missing_fields = tuple(field for field in observation.missing_fields if field != "deck_size")
                active = self._complete_current_run_hand_observation(observation, session)
                verified_detail_names = [normalize_card_name(str(detail.get("detail_title", ""))) for detail in details]
                topic_action = choose_high_good_condition_topic_card(observation.state, verified_detail_names)
            if params.get("round_probe") in {
                "hand_details_map_deck_play_one",
                "hand_details_map_deck_select_one_from_selected",
                "hand_details_map_deck_select_explicit",
            }:
                explicit_card_name = normalize_card_name(str(params.get("explicit_card_name", "")))
                if params.get("round_probe") == "hand_details_map_deck_select_explicit":
                    if explicit_card_name != "存在感":
                        return self._stop_unsupported(context, screen_state, "round1_explicit_card_not_authorized")
                    strategy_action = CardAction(ActionKind.PLAY_CARD, explicit_card_name, "用户授权的存在感单次首次选择")
                else:
                    strategy_action = topic_action or choose_observed_round1_post_topic_card(
                        observation.state, verified_detail_names
                    )
                    strategy_action = strategy_action or choose_observed_round1_post_shikirinaoshi_card(
                        observation.state, verified_detail_names
                    )
                if strategy_action is None or strategy_action.kind is not ActionKind.PLAY_CARD:
                    self._record_journal(
                        screen_state,
                        "round1_exact_strategy",
                        "rejected",
                        details={
                            "mapped_hand": [normalize_card_name(detection.card_name) for detection in active],
                            "state": {
                                "turn": observation.state.turn,
                                "good_condition": observation.state.good_condition_turns,
                                "focus": observation.state.focus,
                                "stamina": observation.state.stamina,
                                "deck_size": observation.state.deck_size,
                            },
                        },
                    )
                    return self._stop_unsupported(context, screen_state, "round1_detail_exact_strategy_not_available")
                target, approval_reason = self._approve_round1_detail_mapped_topic_target(
                    observation,
                    details,
                    selected_at_start=False,
                    expected_card=normalize_card_name(strategy_action.target_card),
                    expected_hand_size=4 if normalize_card_name(strategy_action.target_card) == "仕切り直し" else 5,
                )
                if target is None:
                    return self._stop_unsupported(context, screen_state, approval_reason)
                if (
                    strategy_action is None
                    or strategy_action.kind is not ActionKind.PLAY_CARD
                    or normalize_card_name(strategy_action.target_card) != normalize_card_name(target.card_name)
                ):
                    return self._stop_unsupported(context, screen_state, "round1_detail_exact_strategy_not_topic")
                calibration = load_hif_roi_calibration()
                if not calibration.supports_exam_fields(self._DIRECT_CARD_EXECUTION_FIELDS):
                    return self._stop_unsupported(context, screen_state, "exam_roi_calibration_not_execution_ready")
                approval = approve_card_execution(
                    HIFExecutionMode.SINGLE_STEP,
                    screen_confidence=observation.screen_confidence,
                    missing_fields=observation.missing_fields,
                    target_count=1,
                    postcondition_supported=True,
                )
                if not approval.should_execute:
                    return self._stop_unsupported(context, screen_state, approval.reason)
                execution_before = self._capture_evidence(returned_image, f"{screen_state}_detail_map_play_before")
                if not self._click_box_center(context, list(target.box), double=False):
                    return self._stop_unsupported(context, screen_state, "card_click_failed")
                time.sleep(self.ACTION_DELAY)
                selected_image = self._get_screenshot_or_stop(context, screen_state)
                if selected_image is None:
                    return True
                selected_after = self._capture_evidence(selected_image, f"{screen_state}_detail_map_play_selected")
                if not frame_changed(execution_before, selected_after) or not self._card_selection_confirmed(
                    context, selected_image, normalize_card_name(target.card_name)
                ):
                    return self._stop_unsupported(context, screen_state, "round1_detail_selection_not_confirmed")
                if params.get("round_probe") in {
                    "hand_details_map_deck_select_one_from_selected",
                    "hand_details_map_deck_select_explicit",
                }:
                    self._record_journal(
                        screen_state,
                        "select_card",
                        "verified",
                        details={"card": target.card_name, "reason": strategy_action.reason, "confirmation_clicks": 0},
                        before=execution_before,
                        after=selected_after,
                    )
                    return self._finish_observation(context, round_key)
                if not self._click_box_center(context, list(target.box), double=False):
                    return self._stop_unsupported(context, screen_state, "selected_card_confirm_click_failed")
                time.sleep(self.ACTION_DELAY)
                after_image = self._get_screenshot_or_stop(context, screen_state)
                if after_image is None:
                    return True
                postcondition_ok, postcondition_details = self._read_card_postcondition(
                    context,
                    after_image,
                    screen_state,
                    round_,
                    total_turns,
                    target,
                    observation.detections,
                    before_state=observation.state,
                )
                if not postcondition_ok:
                    return self._stop_unsupported(
                        context, screen_state, str(postcondition_details.get("reason", "card_postcondition_failed"))
                    )
                self._record_journal(
                    screen_state,
                    "play_card",
                    "verified",
                    details={"card": target.card_name, **postcondition_details},
                    before=execution_before,
                    after=self._capture_evidence(after_image, f"{screen_state}_detail_map_play_after"),
                )
                session.record_card(round_key, target.card_name)
                return self._finish_observation(context, round_key)
            self._record_journal(
                screen_state,
                "probe_hand_details_map",
                "observed",
                details={
                    "cards": details,
                    "missing_before": missing_before,
                    "missing_after": observation.missing_fields,
                    "mapped_hand": [normalize_card_name(detection.card_name) for detection in active],
                    "state": {
                        "round": observation.state.round.value,
                        "turn": observation.state.turn,
                        "good_condition": observation.state.good_condition_turns,
                        "focus": observation.state.focus,
                        "stamina": observation.state.stamina,
                        "reprise": observation.state.reprise_count,
                        "deck_size": observation.state.deck_size,
                    },
                    "target_card": topic_action.target_card if topic_action else None,
                    "target_reason": topic_action.reason if topic_action else "",
                    "controller_inputs": len(details),
                },
                before=before,
            )
            return self._finish_observation(context, round_key)
        if params.get("round_probe") == "hand_details_selected":
            probe_mode = parse_execution_mode(params.get("round_probe_execution_mode"))
            if probe_mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, screen_state, "round_hand_probe_requires_single_step")
            try:
                return self._probe_round_hand_details(context, before_image, screen_state, allow_selected_start=True)
            except Exception as error:
                reason = f"round_hand_probe_exception:{type(error).__name__}"
                self._record_journal(
                    screen_state,
                    "probe_hand_details",
                    "rejected",
                    details={"reason": reason, "error": str(error)},
                    before=before,
                )
                return self._stop_unsupported(context, screen_state, reason)
        if params.get("round_probe") == "selected_hand_detail_read_only":
            return self._probe_selected_hand_detail(context, before_image, screen_state)
        if params.get("round_probe") == "turn_roi_candidates":
            return self._probe_turn_roi_candidates(context, before_image, screen_state)
        if params.get("round_probe") == "counter_roi_candidates":
            return self._probe_counter_roi_candidates(context, before_image, screen_state)
        if params.get("round_probe") == "status_detail":
            probe_mode = parse_execution_mode(params.get("round_probe_execution_mode"))
            if probe_mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, screen_state, "status_detail_probe_requires_single_step")
            return self._probe_status_detail(context, before_image, screen_state, int(params.get("status_slot", 0)))
        if params.get("round_probe") == "status_detail_close":
            return self._close_status_detail(context, before_image, screen_state)
        if params.get("round_probe") == "named_status_effect":
            probe_mode = parse_execution_mode(params.get("round_probe_execution_mode"))
            if probe_mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, screen_state, "named_status_effect_probe_requires_single_step")
            return self._probe_named_status_effect(
                context, before_image, screen_state, str(params.get("status_effect_name", ""))
            )
        if params.get("round_probe") == "details_metrics":
            probe_mode = parse_execution_mode(params.get("round_probe_execution_mode"))
            if probe_mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, screen_state, "round_details_probe_requires_single_step")
            return self._probe_round_details_metrics(context, before_image, screen_state)

        probed_deck_size = None
        if params.get("round_probe") == "deck_count":
            probe_mode = parse_execution_mode(params.get("round_probe_execution_mode"))
            if probe_mode is not HIFExecutionMode.SINGLE_STEP:
                return self._stop_unsupported(context, screen_state, "round_deck_probe_requires_single_step")
            probed_deck_size, returned_image = self._probe_round_deck_size(context, before_image, screen_state)
            if probed_deck_size is None or returned_image is None:
                return True
            before_image = returned_image
            before = self._capture_evidence(before_image, f"{screen_state}_before")

        if mode is not HIFExecutionMode.OBSERVE and preset.preset_id != "rinami_good_condition_safe":
            self._record_journal(
                screen_state,
                "card_decision",
                "rejected",
                details={"reason": "card_strategy_profile_not_supported", "mode": mode.value, "preset": preset.preset_id},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, "card_strategy_profile_not_supported")

        panel_reads: tuple[str, str] | None = None
        if mode is not HIFExecutionMode.OBSERVE:
            panel_result = self._probe_round_details_metrics(context, before_image, screen_state, continue_after=True)
            if not isinstance(panel_result, tuple):
                return panel_result
            score_raw, multiplier_raw, before_image = panel_result
            panel_reads = (score_raw, multiplier_raw)
            before = self._capture_evidence(before_image, f"{screen_state}_before_decision")

        health = self._get_health(context, before_image)
        observation = ExamStateReader.from_context(context).read_exam_observation(
            round_,
            total_turns,
            health["current"] if health else None,
        )
        if panel_reads is not None:
            observation.round_metrics = build_round_metrics(
                {"current_score": panel_reads[0], "stage_multiplier": panel_reads[1]}
            )
        infer_card_playability(before_image, observation.detections)
        if probed_deck_size is not None:
            observation.numerics["deck_size"] = NumericRead("deck_size", str(probed_deck_size), probed_deck_size)
            if observation.state is not None:
                observation.state.deck_size = probed_deck_size
            observation.missing_fields = tuple(field for field in observation.missing_fields if field != "deck_size")
        try:
            route_state = assemble_route_state(
                observation,
                route_id="rinami_garakuta_road",
                round_key=round_key,
                total_turns=total_turns,
            )
        except RouteStateRejected as error:
            rejection_details = {
                "mode": mode.value,
                "round": round_.value,
                "reason": "route_state_rejected",
                "route_state_issues": [
                    {
                        "field": issue.field,
                        "code": issue.code.value,
                        "detail": issue.detail,
                    }
                    for issue in error.issues
                ],
                "numeric_reads": {
                    name: {
                        "raw": reading.raw,
                        "value": reading.value,
                        "flow": reading.flow,
                        "status": reading.status.value if reading.status is not None else None,
                        "samples": reading.samples,
                        "confidence": reading.confidence,
                        "confidences": reading.confidences,
                    }
                    for name, reading in observation.numerics.items()
                },
            }
            self._record_journal(screen_state, "card_decision", "rejected", details=rejection_details, before=before)
            reason = ",".join(f"{issue.field}:{issue.code.value}" for issue in error.issues)
            if mode is HIFExecutionMode.OBSERVE:
                logger.warning(f"HIF {screen_state} 路线状态拒绝: {reason}")
                return self._finish_observation(context, round_key)
            return self._stop_unsupported(context, screen_state, f"route_state_rejected:{reason}")

        route_decision = RinamiGarakutaRouteScorer().decide(route_state.state)
        if route_decision.status is not RouteDecisionStatus.SELECTED or route_decision.selected_target_id is None:
            reason_code = route_decision.rejection_code.value if route_decision.rejection_code is not None else "unknown"
            rejection_details = {
                "mode": mode.value,
                "round": round_.value,
                "reason": "route_decision_rejected",
                "reason_code": reason_code,
                "reason_detail": route_decision.rejection_detail,
                "candidates": [
                    {
                        "target_id": candidate.target_id,
                        "title": candidate.title,
                        "upgrade": candidate.upgrade.value,
                        "score": candidate.total_score,
                        "rejection_code": candidate.rejection_code.value if candidate.rejection_code else None,
                    }
                    for candidate in route_decision.candidates
                ],
            }
            self._record_journal(screen_state, "card_decision", "rejected", details=rejection_details, before=before)
            if mode is HIFExecutionMode.OBSERVE:
                logger.warning(f"HIF {screen_state} 路线评分拒绝: {reason_code}")
                return self._finish_observation(context, round_key)
            return self._stop_unsupported(context, screen_state, f"route_decision_rejected:{reason_code}")

        target = route_state.targets[route_decision.selected_target_id]
        selected_display_name = target.raw_card_name or target.card_name
        display_score = self._read_card_display_score(context, before_image, target)
        # 当前实机证明祝福+会触发未建模的状态联动；在主动状态模型完成前保持关闭。
        postcondition_supported = False
        card_action = CardAction(ActionKind.PLAY_CARD, target.card_name, route_decision.rejection_detail or "当前路线确定性评分唯一最高")
        action_details = {
            "mode": mode.value,
            "round": round_.value,
            "decision_kind": card_action.kind.value,
            "target_card": selected_display_name,
            "target_id": route_decision.selected_target_id,
            "display_score": display_score,
            "reason": card_action.reason,
            "screen_confidence": 1.0,
            "missing_fields": (),
            "candidates": [
                {
                    "target_id": candidate.target_id,
                    "title": candidate.title,
                    "upgrade": candidate.upgrade.value,
                    "score": candidate.total_score,
                    "rejection_code": candidate.rejection_code.value if candidate.rejection_code else None,
                    "components": [
                        {
                            "name": component.name,
                            "raw_value": component.raw_value,
                            "weight": component.weight,
                            "value": component.value,
                        }
                        for component in candidate.components
                    ],
                }
                for candidate in route_decision.candidates
            ],
            "detected_cards": [
                {
                    "label": getattr(detection, "label", "cards"),
                    "box": list(detection.box),
                    "confidence": getattr(detection, "confidence", 0.0),
                    "card_name": detection.card_name,
                    "raw_card_name": getattr(detection, "raw_card_name", detection.card_name),
                    "card_name_confidence": getattr(detection, "card_name_confidence", 0.0),
                    "suppressed_reason": getattr(detection, "suppressed_reason", ""),
                    "playable": detection.playable,
                    "playability_gray_ratio": detection.playability_gray_ratio,
                    "playability_source": detection.playability_source,
                }
                for detection in observation.detections
            ],
            "numeric_reads": {
                name: {
                    "raw": reading.raw,
                    "value": reading.value,
                    "flow": reading.flow,
                    "confidence": reading.confidence,
                    "confidences": reading.confidences,
                }
                for name, reading in getattr(observation, "numerics", {}).items()
            },
        }

        if mode is HIFExecutionMode.OBSERVE:
            self._record_journal(screen_state, "card_decision", "observed", details=action_details, before=before)
            logger.success(f"HIF {screen_state} 影子决策: {card_action.kind.value} {selected_display_name} {card_action.reason}")
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
        if not calibration.supports_exam_fields(self._DIRECT_CARD_EXECUTION_FIELDS):
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

        approval = approve_card_execution(
            mode,
            screen_confidence=1.0,
            missing_fields=(),
            target_count=1,
            postcondition_supported=postcondition_supported,
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
                details={**action_details, "reason": approval_reason, "target_count": 1},
                before=before,
            )
            return self._stop_unsupported(context, screen_state, approval_reason)

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

        if self._card_selection_confirmed(context, after_image, selected_display_name):
            self._record_journal(
                screen_state,
                "select_card",
                "verified",
                details={**action_details, "card": target.card_name},
                before=before,
                after=after,
            )
            if not self._click_box_center(context, list(target.box), double=False):
                return self._stop_unsupported(context, screen_state, "selected_card_confirm_click_failed")
            time.sleep(self.ACTION_DELAY)
            after_image = self._get_screenshot_or_stop(context, screen_state)
            if after_image is None:
                return True
            after = self._capture_evidence(after_image, f"{screen_state}_after_confirm")

        assert display_score is not None
        postcondition_ok, postcondition_details = self._verify_blessing_plus_postcondition(
            context,
            after_image,
            screen_state,
            round_,
            total_turns,
            route_state.state,
            display_score,
        )
        if not postcondition_ok:
            reason = str(postcondition_details.get("reason", "card_postcondition_failed"))
            self._record_journal(
                screen_state,
                "play_card",
                "unverified",
                details={**action_details, **postcondition_details, "reason": reason, "card": target.card_name},
                before=before,
                after=after,
            )
            return self._stop_unsupported(context, screen_state, reason)

        self._record_journal(
            screen_state,
            "play_card",
            "verified",
            details={**action_details, **postcondition_details, "card": target.card_name},
            before=before,
            after=after,
        )
        get_runtime_hif_session().record_card(round_key, selected_display_name)
        logger.success(f"HIF {screen_state} 单步出牌已验证: {target.card_name}")
        return self._finish_observation(context, round_key)

    @staticmethod
    def _find_play_card_targets(card_action: CardAction, detections: list[CardDetection]) -> list[CardDetection]:
        """将策略动作收窄为一个可验证的手牌框，默认策略绝不猜多张好调卡。"""

        if card_action.kind is not ActionKind.PLAY_CARD:
            return []
        target_name = normalize_card_name(card_action.target_card) if card_action.target_card else ""
        if target_name:
            return [
                detection
                for detection in detections
                if not getattr(detection, "suppressed_reason", "")
                and getattr(detection, "label", "cards") != "useless"
                and normalize_card_name(detection.card_name) == target_name
            ]
        return [
            detection
            for detection in detections
            if detection.card_name
            and not getattr(detection, "suppressed_reason", "")
            and getattr(detection, "label", "cards") != "useless"
            and is_good_condition_card(normalize_card_name(detection.card_name))
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
            allowed_next_screens=("live", "memory_photo_select"),
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
            self._record_journal(
                "live",
                "skip_live",
                "observed",
                details={"reason": "live_skip_execution_not_supported", "mode": mode},
                before=before,
            )
            return self._stop_unsupported(context, "live", "live_skip_execution_not_supported")
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
        expected_next_screen: str,
    ) -> bool:
        image = self._get_screenshot_or_stop(context, screen_state)
        if image is None:
            return True
        return self._click_text_with_verification(
            context,
            image,
            screen_state,
            event,
            phrases,
            roi,
            allowed_next_screens=(expected_next_screen,),
        )


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
            "memory_photo_confirm",
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
            "memory_generate",
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
            "memory_preview",
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
            "finished",
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
