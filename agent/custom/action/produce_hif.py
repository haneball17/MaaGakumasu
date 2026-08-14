import json
import time
from typing import Any, Dict, List, Optional
from difflib import SequenceMatcher

import numpy as np
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
        # HIF 本战为竖屏 720x1280,体力在顶部中央 [285,16,150,85];不复用初培育横屏 ROI
        reco_detail = context.run_recognition(
            "ProduceRecognitionHealth",
            image,
            pipeline_override={"ProduceRecognitionHealth": {"roi": [285, 16, 150, 85]}},
        )
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

    # HIF 日程候选卡属性扫描(实机 hif_day1.png 720x1280 校准,场景卡 SC-201/501)
    # 卡片结构:左上紫蓝渐变 [146,143,255]±30,右下属性扇形(粉=Vo/蓝=Da/橙=Vi)
    GRADIENT_BAND = slice(940, 970)
    GRADIENT_COLOR = (146, 143, 255)
    GRADIENT_MIN_CLUSTER_WIDTH = 30
    CARD_TOP_LEFT_Y = 919
    CARD_CLICK_CENTER = (70, 1000 - 919)
    FAN_REGION = (74, 992, 50, 38)
    ATTRIBUTE_COLORS = {
        "Vo": (208, 144, 207),
        "Da": (99, 185, 245),
        "Vi": (213, 203, 161),
    }
    ATTRIBUTE_COLOR_MAX_DISTANCE = 60

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

        for event in self._scan_attribute_cards(image):
            events.append(event)
            log_names.append(event["name"])

        roi = [0, 840, 720, 280]
        for event_name, template in self.EVENT_CONFIG.items():
            reco_detail = self._run_template(context, image, "ProduceRecognitionHIFEvent", template, roi, threshold=0.78)
            if reco_detail and reco_detail.hit:
                events.append({"name": event_name, "box": reco_detail.best_result.box})
                log_names.append(event_name)

        if log_names:
            logger.info(f"HIF 可用日程: {', '.join(log_names)}")
        return events

    def _scan_attribute_cards(self, image) -> List[Dict[str, Any]]:
        """两步法识别 Vo/Da/Vi 授業候选:渐变带定位卡片列,扇形平均色分类属性。

        模板匹配对 50x38 纯色小扇形区分度不足(实测同源仅 0.55-0.65),
        颜色分类距离 <30,已对 hif_day1.png 三卡全中(9/11/14)。
        """
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[0] < self.FAN_REGION[1] + self.FAN_REGION[3]:
            return []

        band = arr[self.GRADIENT_BAND].astype(int)
        r, g, b = band[:, :, 0], band[:, :, 1], band[:, :, 2]
        gr, gg, gb = self.GRADIENT_COLOR
        gradient_mask = (np.abs(r - gr) < 30) & (np.abs(g - gg) < 30) & (b > 225)
        xs_sorted = np.sort(np.nonzero(gradient_mask)[1]) if gradient_mask.any() else np.array([], dtype=int)
        clusters: List[tuple[int, int]] = []
        start = prev = None
        for x in xs_sorted:
            if prev is None:
                start = prev = int(x)
                continue
            if x - prev > 20:
                clusters.append((start, prev))
                start = int(x)
            prev = int(x)
        if start is not None:
            clusters.append((start, prev))

        cards: List[Dict[str, Any]] = []
        for cluster_start, cluster_end in clusters:
            if cluster_end - cluster_start < self.GRADIENT_MIN_CLUSTER_WIDTH:
                continue
            fan_dx, fan_y, fan_w, fan_h = self.FAN_REGION
            fan = arr[fan_y : fan_y + fan_h, cluster_start + fan_dx : cluster_start + fan_dx + fan_w].astype(int)
            if fan.size == 0:
                continue
            avg = fan.reshape(-1, 3).mean(axis=0)
            best_name, best_distance = None, 1e9
            for name, ref in self.ATTRIBUTE_COLORS.items():
                distance = float(np.sqrt(((avg - np.array(ref)) ** 2).sum()))
                if distance < best_distance:
                    best_name, best_distance = name, distance
            if best_name is None or best_distance > self.ATTRIBUTE_COLOR_MAX_DISTANCE:
                logger.warning(f"HIF 候选卡属性色未识别: cluster_x={cluster_start}, RGB={avg.astype(int)}, d={best_distance:.0f}")
                continue
            card_x = cluster_start - 10
            center_x = card_x + self.CARD_CLICK_CENTER[0]
            center_y = self.CARD_TOP_LEFT_Y + self.CARD_CLICK_CENTER[1]
            cards.append({"name": best_name, "box": [center_x, center_y, 1, 1], "attribute_rgb": avg.astype(int).tolist()})
            logger.info(f"HIF 候选卡: {best_name} @({center_x},{center_y}) RGB={avg.astype(int).tolist()} d={best_distance:.0f}")
        return cards


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
            reroll_limit=preset.reward_reroll_limit,
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
            reroll_limit=preset.select_change_reroll_limit,
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


@AgentServer.custom_action("ProduceChooseHIFDrinkOverflowAuto")
class ProduceChooseHIFDrinkOverflowAuto(_ProduceHIFActionBase):
    """P 饮料持有上限取舍:保持默认勾选,按剩余数补勾列表项后点「残す」。

    首版保守策略(SC-430 场景卡):新获得饮料默认已勾选;读「あとN個選択」,
    N>0 时点击手持列表首项补勾,N==0 时点「残す」提交。勾选交互细节待实机校准。
    """

    REMAIN_ROI = [260, 1180, 200, 50]
    KEEP_ROI = [210, 1090, 300, 110]
    HAND_LIST_ROI = [54, 660, 612, 420]
    MAX_PICKS = 4
    PICK_ROW_OFFSETS = (0, 150)

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        for pick_index in range(self.MAX_PICKS + 1):
            image = self._get_screenshot(context)
            remain_text = self._read_digits_text(context, image)
            if remain_text is None:
                return self._stop_unsupported(context, "hif_drink_overflow", "remain_counter_not_found")

            if remain_text == 0:
                keep = self._find_text_option(context, image, ("残す",), self.KEEP_ROI)
                if not keep:
                    return self._stop_unsupported(context, "hif_drink_overflow", "keep_button_not_found")
                if not self._click_box_center(context, keep.best_result.box, double=False):
                    return self._stop_unsupported(context, "hif_drink_overflow", "keep_button_click_failed")
                logger.success(f"HIF 饮料上限:取舍完成(补勾 {pick_index} 项)")
                time.sleep(self.ACTION_DELAY)
                return True

            if pick_index >= self.MAX_PICKS:
                return self._stop_unsupported(context, "hif_drink_overflow", f"pick_limit_exceeded: remain={remain_text}")

            row = pick_index % len(self.PICK_ROW_OFFSETS)
            pick_x = self.HAND_LIST_ROI[0] + self.HAND_LIST_ROI[2] // 2
            pick_y = self.HAND_LIST_ROI[1] + 60 + self.PICK_ROW_OFFSETS[row]
            logger.info(f"HIF 饮料上限:remain={remain_text},点击列表项 ({pick_x},{pick_y})")
            context.tasker.controller.post_click(pick_x, pick_y).wait()
            time.sleep(self.ACTION_DELAY)

        return self._stop_unsupported(context, "hif_drink_overflow", "unreachable")

    def _read_digits_text(self, context: Context, image) -> Optional[int]:
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFDrinkRemain", [".*あと[0-9０-９]+個.*"], self.REMAIN_ROI)
        if not (reco_detail and reco_detail.hit):
            return None
        digits = "".join(char for char in reco_detail.best_result.text if char.isdigit())
        return int(digits) if digits else None


@AgentServer.custom_action("ProduceHIFSelectChangeDoneAuto")
class ProduceHIFSelectChangeDoneAuto(_ProduceHIFActionBase):
    """変卡完成提示页:点空白处推进(页面无按钮,日志确认为空白点击)。"""

    BLANK_TAP = (360, 640)

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        logger.info(f"HIF 変卡完成:点空白 ({self.BLANK_TAP[0]},{self.BLANK_TAP[1]}) 推进")
        context.tasker.controller.post_click(*self.BLANK_TAP).wait()
        time.sleep(self.ACTION_DELAY)
        return True


@AgentServer.custom_action("ProduceHIFChooseIdolAuto")
class ProduceHIFChooseIdolAuto(_ProduceHIFActionBase):
    """HIF 偶像选择页(步骤1)：校验当前选中偶像与预设一致后点击「プロデュース開始」。"""

    # ROI 实机校准自 MuMu 720x1280 偶像选择页(MaaFW OCR box: True End y76-96/名字 y154-211/卡名 y119-150)
    TRUE_END_ROI = [430, 70, 266, 35]
    IDOL_NAME_ROI_TRUE_END = [440, 140, 280, 80]
    IDOL_NAME_ROI_DEFAULT = [400, 98, 320, 64]
    SONG_NAME_ROI_TRUE_END = [380, 112, 320, 42]
    SONG_NAME_ROI_DEFAULT = [340, 60, 380, 45]
    NEXT_BUTTON_ROI = [150, 1000, 420, 200]
    IDOL_SIMILARITY_THRESHOLD = 0.9
    SONG_SIMILARITY_THRESHOLD = 0.7

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        # MaaFW 对未定义 custom_action_param 的节点传 "null" 字符串,loads 结果需兜底为空 dict
        params: Dict[str, Any] = json.loads(argv.custom_action_param) if argv.custom_action_param else {}
        if not isinstance(params, dict):
            params = {}
        expected_idol = params.get("idol_name", "")
        expected_song = params.get("song_name", "")

        image = self._get_screenshot(context)
        true_end_detail = self._run_ocr(context, image, "ProduceHIFIdolTrueEnd", ["True", "End"], self.TRUE_END_ROI)
        has_true_end = bool(true_end_detail and true_end_detail.hit)
        name_roi = self.IDOL_NAME_ROI_TRUE_END if has_true_end else self.IDOL_NAME_ROI_DEFAULT

        recognized_name = self._read_text(context, image, "ProduceHIFIdolName", name_roi)
        logger.info(f"HIF 偶像选择: true_end={has_true_end}, 当前偶像={recognized_name or '未识别'}")

        if expected_idol and recognized_name:
            similarity = SequenceMatcher(None, recognized_name, expected_idol).ratio()
            if similarity < self.IDOL_SIMILARITY_THRESHOLD:
                return self._stop_unsupported(
                    context, "hif_idol_select", f"idol_mismatch: got={recognized_name}, want={expected_idol}, ratio={similarity:.2f}"
                )

        if expected_song and recognized_name:
            song_roi = self.SONG_NAME_ROI_TRUE_END if has_true_end else self.SONG_NAME_ROI_DEFAULT
            recognized_song = self._read_text(context, image, "ProduceHIFIdolSong", song_roi)
            if recognized_song:
                similarity = SequenceMatcher(None, recognized_song, expected_song).ratio()
                if similarity < self.SONG_SIMILARITY_THRESHOLD:
                    return self._stop_unsupported(
                        context, "hif_idol_select", f"song_mismatch: got={recognized_song}, want={expected_song}, ratio={similarity:.2f}"
                    )

        # 底部中央大按钮实机 OCR 为「プロデュース開始」(box 约 [247,1059,225,33]),非「次へ」
        next_button = self._find_text_option(context, image, ("プロデュース開始",), self.NEXT_BUTTON_ROI)
        if not next_button:
            return self._stop_unsupported(context, "hif_idol_select", "next_button_not_found")
        if not self._click_box_center(context, next_button.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_idol_select", "next_button_click_failed")
        return True

    def _read_text(self, context: Context, image, name: str, roi: list[int]) -> str:
        reco_detail = self._run_ocr(context, image, name, [".*"], roi)
        if not (reco_detail and reco_detail.hit):
            return ""
        return "".join(item.text for item in reco_detail.all_results).replace(" ", "")


@AgentServer.custom_action("ProduceHIFStartConfirmAuto")
class ProduceHIFStartConfirmAuto(_ProduceHIFActionBase):
    """HIF 開始確認页(步骤2)：直接以页面默认编成点击「プロデュース開始」开始培育。"""

    START_BUTTON_ROI = [150, 1000, 420, 200]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        image = self._get_screenshot(context)
        start_button = self._find_text_option(context, image, ("プロデュース開始",), self.START_BUTTON_ROI)
        if not start_button:
            return self._stop_unsupported(context, "hif_start_confirm", "start_button_not_found")
        if not self._click_box_center(context, start_button.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_start_confirm", "start_button_click_failed")
        logger.success("HIF 開始確認：以默认编成开始培育")
        time.sleep(self.ACTION_DELAY)
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
