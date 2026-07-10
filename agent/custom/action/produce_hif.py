import time
from typing import Any, Dict, List, Optional

from utils import logger
from maa.context import Context
from maa.custom_action import CustomAction
from maa.agent.agent_server import AgentServer

from agent.hif.presets import HIFPreset, parse_hif_preset, choose_first_matching, choose_schedule_priority
from agent.hif.adapters.exam_reader import ExamStateReader


class _ProduceHIFActionBase(CustomAction):
    CLICK_DELAY = 0.4
    ACTION_DELAY = 2.0

    @staticmethod
    def _get_screenshot(context: Context):
        return context.tasker.controller.post_screencap().wait().get()

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

    @staticmethod
    def _get_preset(argv: CustomAction.RunArg) -> HIFPreset:
        return parse_hif_preset(argv.custom_action_param)

    def _stop_unsupported(self, context: Context, screen_state: str, reason: str) -> bool:
        logger.warning(f"HIF 安全停止: screen_state={screen_state}, reason={reason}")
        context.run_task("ProduceHIFUnknownStop")
        return True

    def _find_text_option(self, context: Context, image, phrases: tuple[str, ...], roi: list[int]):
        for phrase in phrases:
            reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFTextOption", [f".*{phrase}.*"], roi)
            if reco_detail and reco_detail.hit:
                return reco_detail
        return None

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


@AgentServer.custom_action("ProduceChooseHIFEventAuto")
class ProduceChooseHIFEventAuto(_ProduceHIFActionBase):
    LOW_HEALTH_RATIO = 0.35
    LOW_HEALTH_VALUE = 10

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
        health_data = self._get_health(context, image) or {"current": 34, "max": 34, "ratio": 1.0}
        events = self._get_available_events(context, image)

        if not events:
            logger.warning("未识别到 HIF 可选日程，保持当前状态")
            return True

        best_event = self._choose_best_event(health_data, events, self._get_preset(argv), self._get_day_remaining(context, image))
        if not best_event:
            return self._stop_unsupported(context, "finals_action_select", "preset_no_matching_event")

        logger.info(f"HIF 选择事件: {best_event['name']}")
        return self._execute_event(context, best_event)

    def _choose_best_event(
        self,
        health_data: dict,
        events: list[dict],
        preset: HIFPreset,
        day_remaining: int | None,
    ) -> Optional[dict]:
        current_health = health_data["current"]
        ratio_health = health_data["ratio"]

        if current_health <= self.LOW_HEALTH_VALUE or ratio_health <= self.LOW_HEALTH_RATIO:
            go_out = self._find_event(events, "おでかけ")
            if go_out:
                return go_out

        priority = choose_schedule_priority(preset, day_remaining)
        if priority is None:
            return None
        available = {self.EVENT_PRESET_KEYS[event["name"]]: event for event in events}
        selected_key = choose_first_matching(available, priority)
        return available.get(selected_key) if selected_key else None

    def _find_event(self, events: list[dict], target_name: str) -> Optional[dict]:
        for event in events:
            if event["name"] == target_name:
                return event
        return None

    def _execute_event(self, context: Context, event: dict) -> bool:
        if not self._click_box_center(context, event["box"]):
            return self._stop_unknown(context, f"???? HIF ??: {event.get('name', 'unknown')}")

        time.sleep(self.ACTION_DELAY)
        return True

    def _get_available_events(self, context: Context, image) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        log_names: List[str] = []
        roi = [0, 840, 720, 280]

        for event_name, template in self.EVENT_CONFIG.items():
            reco_detail = self._run_template(context, image, "ProduceRecognitionHIFEvent", template, roi, threshold=0.78)
            if reco_detail and reco_detail.hit:
                event = {"name": event_name, "box": reco_detail.best_result.box}
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

        recommend = self._find_recommend(context, image)
        if recommend:
            logger.info("命中推荐 P 道具")
            if not self._click_box_center(context, recommend, double=False, y_offset=80):
                return self._stop_unsupported(context, "hif_p_item_select", "recommend_click_failed")
            time.sleep(self.ACTION_DELAY)
            return True

        keyword_hit = self._find_keyword_option(context, image)
        if keyword_hit:
            logger.info(f"按关键词选择 HIF P 道具: {keyword_hit['name']}")
            if not self._click_box_center(context, keyword_hit["box"], double=False):
                return self._stop_unsupported(context, "hif_p_item_select", "keyword_click_failed")
            time.sleep(self.ACTION_DELAY)
            return True

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

        reco_detail = self._find_text_option(context, self._get_screenshot(context), self.GOOD_CONDITION_OPTIONS, self.OPTION_ROI)
        if not reco_detail:
            return self._stop_unsupported(context, "hif_class_options", "good_condition_option_not_found")
        if not self._click_box_center(context, reco_detail.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_class_options", "good_condition_option_click_failed")
        return True


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
        for _ in range(reroll_limit + 1):
            image = self._get_screenshot(context)
            reco_detail = self._find_text_option(context, image, names, self.OPTION_ROI)
            if reco_detail:
                return self._click_box_center(context, reco_detail.best_result.box, double=False)

            reroll = self._find_text_option(context, image, ("再抽選",), self.REROLL_ROI)
            if not reroll:
                break
            self._click_box_center(context, reroll.best_result.box, double=False)
            time.sleep(self.ACTION_DELAY)

        logger.warning(f"HIF 奖励未命中预设: screen_state={screen_state}")
        return False


@AgentServer.custom_action("ProduceChooseHIFDrinkRewardAuto")
class ProduceChooseHIFDrinkRewardAuto(_ProduceHIFRewardChoiceAction):
    """按预设领取已识别的 P 饮料。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        chosen = self._choose_named_reward(
            context,
            self._get_preset(argv).drink_name_priority,
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
            preset.skill_reward_names,
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

        time.sleep(self.ACTION_DELAY)
        next_button = self._find_text_option(context, self._get_screenshot(context), ("次へ",), self.NEXT_ROI)
        if not next_button:
            return self._stop_unsupported(context, "select_change_target", "next_button_not_found")
        if not self._click_box_center(context, next_button.best_result.box, double=False):
            return self._stop_unsupported(context, "select_change_target", "next_button_click_failed")
        return True


@AgentServer.custom_action("ProduceChooseHIFSelectChangeSourceAuto")
class ProduceChooseHIFSelectChangeSourceAuto(_ProduceHIFActionBase):
    """在变卡第二阶段选择预设源卡并确认。"""

    DECK_ROI = [60, 600, 600, 500]
    CHANGE_ROI = [350, 1080, 320, 140]
    MAX_DECK_SCROLLS = 4

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        source = None
        for scroll_index in range(self.MAX_DECK_SCROLLS + 1):
            source = self._find_text_option(context, self._get_screenshot(context), preset.select_change_source_names, self.DECK_ROI)
            if source:
                break
            if scroll_index < self.MAX_DECK_SCROLLS:
                context.tasker.controller.post_swipe(360, 1040, 360, 680, duration=300).wait()
                time.sleep(self.ACTION_DELAY)
        if not source:
            return self._stop_unsupported(context, "select_change_source_deck", "preset_source_card_not_found")
        if not self._click_box_center(context, source.best_result.box, double=False):
            return self._stop_unsupported(context, "select_change_source_deck", "source_card_click_failed")
        time.sleep(self.ACTION_DELAY)

        change_button = self._find_text_option(context, self._get_screenshot(context), ("チェンジ",), self.CHANGE_ROI)
        if not change_button:
            return self._stop_unsupported(context, "select_change_source_deck", "change_button_not_found")
        if not self._click_box_center(context, change_button.best_result.box, double=False):
            return self._stop_unsupported(context, "select_change_source_deck", "change_button_click_failed")
        return True


@AgentServer.custom_action("ProduceHIFConsultAuto")
class ProduceHIFConsultAuto(_ProduceHIFActionBase):
    """首版仅支持保留 P 点并结束咨询商店。"""

    FINISH_ROI = [530, 1000, 190, 150]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        if self._get_preset(argv).consult_policy != "finish_without_purchase":
            return self._stop_unsupported(context, "consult_shop", "consult_policy_not_supported")

        finish_button = self._find_text_option(context, self._get_screenshot(context), ("終了",), self.FINISH_ROI)
        if not finish_button:
            return self._stop_unsupported(context, "consult_shop", "finish_button_not_found")
        if not self._click_box_center(context, finish_button.best_result.box, double=False):
            return self._stop_unsupported(context, "consult_shop", "finish_button_click_failed")
        return True


@AgentServer.custom_action("ProduceHIFChooseFinalModeAuto")
class ProduceHIFChooseFinalModeAuto(_ProduceHIFActionBase):
    """在已识别的 HIF 入口按预设进入本战模式。"""

    FINAL_MODE_BUTTON = [360, 824, 360, 171]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        if self._get_preset(argv).entry_mode != "finals":
            return self._stop_unsupported(context, "hif_mode_select", "entry_mode_not_supported")
        if not self._click_box_center(context, self.FINAL_MODE_BUTTON, double=False):
            return self._stop_unsupported(context, "hif_mode_select", "final_mode_click_failed")
        logger.success("HIF 入口：按预设选择本战模式")
        time.sleep(self.ACTION_DELAY)
        return True


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
