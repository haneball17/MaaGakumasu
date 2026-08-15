import re
import json
import time
from typing import Any, Dict, List, Optional
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image
from utils import logger
from maa.context import Context
from maa.custom_action import CustomAction
from maa.agent.agent_server import AgentServer

from agent.hif.presets import (
    HIFPreset,
    parse_hif_preset,
    apply_file_overrides,
    choose_first_matching,
    choose_schedule_priority,
    build_gui_keyword_overrides,
)
from agent.hif.decisions.rewards import load_keyword_tables
from agent.hif.adapters.card_dict import normalize_card_name, build_card_name_dict
from agent.hif.decisions.schedule import classify_class_option
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
        logger.warning(f"HIF 安全停止: {reason}")
        # 返回 False 让节点动作失败终止任务;run_task(UnknownStop) 只能停子任务流,父管线会继续轮询
        return False

    @staticmethod
    def _get_preset(argv: CustomAction.RunArg) -> HIFPreset:
        # 覆盖链:GUI(custom_action_param) > decision_override.json(非评分项) > preset 默认
        return apply_file_overrides(parse_hif_preset(argv.custom_action_param))

    def _stop_unsupported(self, context: Context, screen_state: str, reason: str) -> bool:
        logger.warning(f"HIF 安全停止: screen_state={screen_state}, reason={reason}")
        return False

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

        low_ratio = (preset.low_health_percent / 100) if preset.low_health_percent else self.LOW_HEALTH_RATIO
        if current_health <= self.LOW_HEALTH_VALUE or ratio_health <= low_ratio:
            logger.info(f"HIF 低体力({current_health}, {ratio_health:.0%} ≤ {low_ratio:.0%}): 强制おでかけ")
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

    # HIF 公開レッスン候选卡(实机 hif_day2.png 校准):三卡底部彩色横条
    # 有固定文字「Vo./Da./Vi.公開レッスン」,OCR 前缀映射属性;SP 徽章与体力标记三卡相同不作区分
    PUBLIC_LESSON_ROI = [80, 1040, 570, 100]
    PUBLIC_LESSON_CLICK_Y = 1010
    PUBLIC_LESSON_PREFIXES = {"Vo.": "Vo", "Da.": "Da", "Vi.": "Vi"}

    def _get_available_events(self, context: Context, image) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        log_names: List[str] = []

        for event in self._scan_attribute_cards(image):
            events.append(event)
            log_names.append(event["name"])

        for event in self._scan_public_lessons(context, image):
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

    def _scan_public_lessons(self, context: Context, image) -> List[Dict[str, Any]]:
        """识别公開レッスン候选卡:OCR 底部横条固定文字,前缀映射 Vo/Da/Vi。"""
        reco_detail = self._run_ocr(
            context, image, "ProduceRecognitionHIFPublicLesson", [".*公開レッスン.*"], self.PUBLIC_LESSON_ROI
        )
        lessons: List[Dict[str, Any]] = []
        if not (reco_detail and reco_detail.all_results):
            return lessons
        for item in reco_detail.all_results:
            text = item.text.replace(" ", "")
            for prefix, name in self.PUBLIC_LESSON_PREFIXES.items():
                if prefix in text:
                    center_x = item.box[0] + item.box[2] // 2
                    lessons.append({"name": name, "box": [center_x, self.PUBLIC_LESSON_CLICK_Y, 1, 1]})
                    logger.info(f"HIF 公開レッスン候选: {name} @({center_x},{self.PUBLIC_LESSON_CLICK_Y}) text={text!r}")
                    break
        return lessons

    def _scan_attribute_cards(self, image) -> List[Dict[str, Any]]:
        """两步法识别 Vo/Da/Vi 授業候选:渐变带定位卡片列,扇形平均色分类属性。

        模板匹配对 50x38 纯色小扇形区分度不足(实测同源仅 0.55-0.65),
        颜色分类距离 <30,已对 hif_day1.png 三卡全中(9/11/14)。
        """
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[0] < self.FAN_REGION[1] + self.FAN_REGION[3]:
            logger.warning(f"HIF 色扫描: 图像形状异常 {None if not hasattr(arr, 'shape') else arr.shape}")
            return []
        # maafw post_screencap 返回 OpenCV BGR 序,属性色参考值为 RGB,需翻转
        if arr.shape[2] >= 3:
            arr = arr[..., :3][..., ::-1]

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
    """授業事件选项:好调文案优先,未命中时选最上方的非トラブル追加选项。

    选项文案随事件而变(实测 メンタルケア 事件文案与日志记录完全不同),
    无法穷举;页面锚用左上「授業」标题(Flag 侧),选项选择用两级策略。
    """

    OPTION_ROI = [40, 620, 640, 360]
    GOOD_CONDITION_OPTIONS = ("余裕です！", "長い道のりでした")
    TROUBLE_MARKER = "トラブル"
    # 选项文案至少含 2 个日文字符,排除「-50」等数字消耗标记与「T」等图标噪读
    OPTION_TEXT_PATTERN = re.compile(r"[ぁ-んァ-ヶ一-龯a-zA-Z]{2,}")

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        priority = self._get_preset(argv).class_option_priority
        if "good_condition" not in priority and "first_safe" not in priority:
            return self._stop_unsupported(context, "hif_class_options", "preset_no_class_option_policy")

        image = self._get_screenshot(context)
        if "good_condition" in priority:
            reco_detail = self._find_text_option(context, image, self.GOOD_CONDITION_OPTIONS, self.OPTION_ROI)
            if reco_detail:
                if not self._click_box_center(context, reco_detail.best_result.box, double=False):
                    return self._stop_unsupported(context, "hif_class_options", "good_condition_option_click_failed")
                logger.info(f"HIF 授業选项: 好调文案命中「{reco_detail.best_result.text}」")
                return True
        if "first_safe" not in priority:
            return self._stop_unsupported(context, "hif_class_options", "good_condition_option_not_found")
        return self._choose_first_safe_option(context, image)

    # 转场竞态防循环(実機 2026-08-15 Day4):変卡标题未渲染时 Flag 误命中残留「授業」标题,
    # 同一无效文本被反复点击;记录最近点击文本,重复时跳过换下一个候选
    _recent_option_texts: list[str] = []

    def _choose_first_safe_option(self, context: Context, image) -> bool:
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFClassOptions", [".*"], self.OPTION_ROI)
        if not (reco_detail and reco_detail.all_results):
            return self._stop_unsupported(context, "hif_class_options", "class_options_not_found")

        results = reco_detail.all_results
        trouble_ys = [item.box[1] + item.box[3] // 2 for item in results if self.TROUBLE_MARKER in item.text]
        candidates = [
            item
            for item in results
            if item.box[3] > 20
            and self.OPTION_TEXT_PATTERN.search(item.text.replace("ß", ""))
            and self.TROUBLE_MARKER not in item.text
            # 排除页面指令文案(実機 2026-08-15:「受け取るスキルカードを選んでください。」被误当选)
            and "ください" not in item.text
            and not any(abs(item.box[1] + item.box[3] // 2 - ty) < 40 for ty in trouble_ys)
        ]
        if not candidates:
            return self._stop_unsupported(context, "hif_class_options", "no_safe_option")

        # 固定表标记可见时(選択して獲得)优先获得类选项(seesaawiki 授業固定表),否则取最上方安全项
        acquire_candidates = [item for item in candidates if classify_class_option(item.text) == "acquire"]
        ordered = acquire_candidates + [c for c in candidates if c not in acquire_candidates]
        recent = type(self)._recent_option_texts
        target = next((c for c in ordered if c.text not in recent), ordered[0])
        # 全部候选都点过一轮仍停在原地 → 清空守卫重新开始(避免卡死)
        if target.text in recent:
            recent.clear()

        if not self._click_box_center(context, target.box, double=False):
            return self._stop_unsupported(context, "hif_class_options", "safe_option_click_failed")
        recent.append(target.text)
        del recent[:-3]
        logger.info(f"HIF 授業选项: 通用安全策略选择「{target.text}」")
        return True


class _ProduceHIFRewardChoiceAction(_ProduceHIFActionBase):
    """三选一奖励基类:逐张点选候选,读详情面板卡名+效果文本做关键词评分,选最高分确认。

    候选缩略图上无文字(実機 2026-08-15 确认),卡名与效果只在点选后的白色详情面板渲染;
    点选是选中而非确认(确认另有 受け取る/次へ 按钮),逐张读取安全。
    决策透明度(2026-08-15 grill):评分明细日志、截图存档、JSONL 落盘、确认后流转验证;
    名单优先:卡名命中 preset.card/drink_priority 直接选(用户指定 > 评分器)。
    """

    SELECT_DELAY = 1.2
    REROLL_ROI = [530, 1000, 180, 140]
    # 三个固定候选位(三列布局,列间距约 152px;[待実機校准] 第二/三列为对称推算)
    CANDIDATE_BOXES: list[list[int]] = []
    DETAIL_TEXT_ROI: list[int] = []
    # 详情面板卡名行(daily-log 実測 y512-560;此前 DETAIL_TEXT_ROI 从 y555 起漏读卡名 43px)
    CARD_NAME_ROI: list[int] = [120, 500, 480, 70]
    CONFIRM_TEXT: tuple[str, ...] = ()
    CONFIRM_ROI: list[int] = []
    # 本页标题锚(流转验证:确认后仍见此文本=未流转)
    ANCHOR_TEXT: tuple[str, ...] = ()
    ANCHOR_ROI: list[int] = []

    _CARD_DICT: list[str] | None = None

    def _read_all_text(self, context: Context, image, name: str, roi: list[int]) -> str:
        reco_detail = self._run_ocr(context, image, name, [".*"], roi)
        if not (reco_detail and reco_detail.all_results):
            return ""
        return " ".join(item.text for item in reco_detail.all_results)

    def _read_card_name(self, context: Context, image) -> str:
        """读详情面板卡名行;master 121 卡词典约束候选,normalize 修正误识。"""
        if _ProduceHIFRewardChoiceAction._CARD_DICT is None:
            _ProduceHIFRewardChoiceAction._CARD_DICT = build_card_name_dict()
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFCardName", self._CARD_DICT, self.CARD_NAME_ROI)
        if not (reco_detail and reco_detail.hit):
            return ""
        return normalize_card_name(reco_detail.best_result.text)

    def _archive_decision(self, image, screen_state: str, record: dict) -> None:
        """决策落盘:截图 debug/decisions/<ts>_<state>.png + session JSONL(含评分明细/override)。"""
        try:
            out_dir = Path("debug") / "decisions"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            img_path = out_dir / f"{ts}_{screen_state}.png"
            Image.fromarray(image).save(img_path)
            record["image"] = str(img_path)
            jsonl = out_dir / f"session-{time.strftime('%Y%m%d')}.jsonl"
            with jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as err:  # 存档失败不阻断决策
            logger.warning(f"HIF 决策存档失败: {err}")

    def _choose_keyword_reward(self, context: Context, preset: HIFPreset, reroll_limit: int, screen_state: str) -> bool:
        table = load_keyword_tables(overrides=build_gui_keyword_overrides(preset))[preset.preference]
        priority_names = preset.drink_priority if "drink" in screen_state else preset.card_priority
        best_box = None
        for round_index in range(reroll_limit + 1):
            candidates = []
            for label, box in enumerate(self.CANDIDATE_BOXES, start=1):
                self._click_box_center(context, box, double=False)
                time.sleep(self.SELECT_DELAY)
                image = self._get_screenshot(context)
                card_name = self._read_card_name(context, image)
                text = self._read_all_text(context, image, "ProduceRecognitionHIFRewardDetail", self.DETAIL_TEXT_ROI)
                score, breakdown = table.score_detail(text)
                candidates.append({"label": label, "box": box, "card": card_name, "text": text, "score": score, "breakdown": breakdown})
                detail_str = ",".join(f"{kw}{value:+g}" for kw, value in breakdown) or "无命中"
                logger.info(f"HIF 三选一[{screen_state}] 候选{label}: {card_name or '卡名未读'} score={score:.0f} [{detail_str}]")

            # 名单优先:用户点名的卡/饮料直接选(grill 定案:用户指定 > 评分器)
            chosen = next((c for c in candidates if c["card"] and c["card"] in priority_names), None)
            if chosen:
                logger.info(f"HIF 三选一[{screen_state}] 名单优先: 「{chosen['card']}」(跳过评分)")
            else:
                chosen = max(candidates, key=lambda c: c["score"])
                if table.accepts(chosen["score"]):
                    pass  # 达标直接确认
                else:
                    reroll = self._find_text_option(context, self._get_screenshot(context), ("再抽選",), self.REROLL_ROI)
                    if reroll and round_index < reroll_limit:
                        logger.info(
                            f"HIF 三选一[{screen_state}] 最高分 {chosen['score']:.0f} 未达阈值 {table.accept_threshold:.0f},重抽"
                        )
                        self._archive_decision(self._get_screenshot(context), screen_state, {
                            "ts": time.strftime("%H:%M:%S"), "screen": screen_state, "round": round_index,
                            "preference": preset.preference, "candidates": candidates, "action": "reroll",
                            "accept_threshold": table.accept_threshold,
                            "overrides": build_gui_keyword_overrides(preset) or None,
                        })
                        self._click_box_center(context, reroll.best_result.box, double=False)
                        time.sleep(self.ACTION_DELAY)
                        continue
            self._archive_decision(self._get_screenshot(context), screen_state, {
                "ts": time.strftime("%H:%M:%S"), "screen": screen_state, "round": round_index,
                "preference": preset.preference, "candidates": candidates, "action": "confirm",
                "chosen": chosen["label"], "chosen_card": chosen["card"] or None,
                "accept_threshold": table.accept_threshold,
                "overrides": build_gui_keyword_overrides(preset) or None,
            })
            return self._confirm_candidate(context, chosen["box"], screen_state)

        return self._confirm_candidate(context, best_box, screen_state)

    def _confirm_candidate(self, context: Context, box: List[int], screen_state: str) -> bool:
        self._click_box_center(context, box, double=False)
        time.sleep(self.CLICK_DELAY)
        confirm = self._find_text_option(context, self._get_screenshot(context), self.CONFIRM_TEXT, self.CONFIRM_ROI)
        if not confirm:
            return self._stop_unsupported(context, screen_state, "confirm_button_not_found")
        if not self._click_box_center(context, confirm.best_result.box, double=False):
            return self._stop_unsupported(context, screen_state, "confirm_button_click_failed")
        time.sleep(self.ACTION_DELAY)
        # 流转验证(grill 定案):确认后本页标题锚仍在=确认未生效,安全停止防同页重复决策
        if self.ANCHOR_TEXT:
            still = self._find_text_option(context, self._get_screenshot(context), self.ANCHOR_TEXT, self.ANCHOR_ROI)
            if still:
                return self._stop_unsupported(context, screen_state, "confirm_no_transition")
        return True


@AgentServer.custom_action("ProduceChooseHIFDrinkRewardAuto")
class ProduceChooseHIFDrinkRewardAuto(_ProduceHIFRewardChoiceAction):
    """P 饮料三选一:逐张点选读卡名+效果,名单(饮料名)优先,评分选最高分确认(无重抽)。"""

    CANDIDATE_BOXES = [[158, 822, 127, 127], [308, 822, 127, 127], [458, 822, 127, 127]]
    DETAIL_TEXT_ROI = [118, 506, 500, 230]
    CONFIRM_TEXT = ("受け取る", "次へ")
    CONFIRM_ROI = [150, 1000, 420, 200]
    ANCHOR_TEXT = ("受け取るPドリンク", "Pドリンクを選んで")
    ANCHOR_ROI = [80, 540, 560, 220]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        return self._choose_keyword_reward(context, self._get_preset(argv), reroll_limit=0, screen_state="hif_drink_reward")


@AgentServer.custom_action("ProduceChooseHIFSkillRewardAuto")
class ProduceChooseHIFSkillRewardAuto(_ProduceHIFRewardChoiceAction):
    """技能卡三选一:逐张点选读卡名+效果,名单(卡名)优先,评分;不达阈值且见「再抽選」才重抽。"""

    CANDIDATE_BOXES = [[156, 821, 128, 128], [308, 821, 128, 128], [460, 821, 128, 128]]
    DETAIL_TEXT_ROI = [118, 555, 490, 185]
    CONFIRM_TEXT = ("受け取る", "次へ")
    CONFIRM_ROI = [150, 1000, 420, 200]
    ANCHOR_TEXT = ("受け取るスキルカード", "スキルカードを選んで")
    ANCHOR_ROI = [80, 540, 560, 220]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        reroll = preset.reward_reroll_override or preset.reward_reroll_limit
        return self._choose_keyword_reward(context, preset, reroll_limit=reroll, screen_state="hif_skill_reward")


@AgentServer.custom_action("ProduceChooseHIFSelectChangeTargetAuto")
class ProduceChooseHIFSelectChangeTargetAuto(_ProduceHIFRewardChoiceAction):
    """変卡第一阶段:逐张点选候选读卡名+效果评分选最高分,确认后推进到牌库选择。"""

    CANDIDATE_BOXES = [[156, 837, 128, 128], [308, 837, 128, 128], [460, 837, 128, 128]]
    DETAIL_TEXT_ROI = [118, 555, 490, 185]
    CONFIRM_TEXT = ("次へ",)
    CONFIRM_ROI = [200, 1010, 320, 130]
    ANCHOR_TEXT = ("チェンジで獲得する",)
    ANCHOR_ROI = [60, 260, 600, 110]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        reroll = preset.select_change_reroll_override or preset.select_change_reroll_limit
        return self._choose_keyword_reward(context, preset, reroll_limit=reroll, screen_state="select_change_target")


@AgentServer.custom_action("ProduceChooseHIFSelectChangeSourceAuto")
class ProduceChooseHIFSelectChangeSourceAuto(_ProduceHIFActionBase):
    """在变卡第二阶段选择预设源卡并确认;预设未命中时回退选牌库第一格。"""

    DECK_ROI = [60, 600, 600, 500]
    CHANGE_ROI = [350, 1080, 320, 140]
    FIRST_DECK_CELL_BOX = [80, 623, 118, 118]
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
            logger.info("HIF 変卡: 预设源卡未命中,回退选择牌库第一格(首版推进策略)")
            if not self._click_box_center(context, self.FIRST_DECK_CELL_BOX, double=False):
                return self._stop_unsupported(context, "select_change_source_deck", "fallback_source_click_failed")
        elif not self._click_box_center(context, source.best_result.box, double=False):
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
        preset = self._get_preset(argv)
        if preset.consult_policy_override:
            if preset.consult_policy_override not in ("finish_without_purchase",):
                return self._stop_unsupported(context, "consult_shop", f"consult_policy_override_not_supported: {preset.consult_policy_override}")
        elif preset.consult_policy != "finish_without_purchase":
            return self._stop_unsupported(context, "consult_shop", "consult_policy_not_supported")

        finish_button = self._find_text_option(context, self._get_screenshot(context), ("終了",), self.FINISH_ROI)
        if not finish_button:
            return self._stop_unsupported(context, "consult_shop", "finish_button_not_found")
        if not self._click_box_center(context, finish_button.best_result.box, double=False):
            return self._stop_unsupported(context, "consult_shop", "finish_button_click_failed")
        return True


@AgentServer.custom_action("ProduceChooseHIFSPCardAuto")
class ProduceChooseHIFSPCardAuto(_ProduceHIFActionBase):
    """レッスン終了時効果选择页(4 张全宽卡,疑为 Pドリンク 选择,池 27 种)。

    点卡即执行无确认按钮(実機 2026-08-14),不能逐张点选;
    改为 OCR 页面文字行做关键词评分选最高分行点击,无文字可读时回退点第一张。
    页面文字布局[待実機校准]。
    """

    OPTION_ROI = [40, 600, 660, 560]
    FIRST_CARD_BOX = [360, 660, 1, 1]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        table = load_keyword_tables(overrides=build_gui_keyword_overrides(preset))[preset.preference]
        image = self._get_screenshot(context)
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFSPCardText", [".*"], self.OPTION_ROI)

        target_box = None
        if reco_detail and reco_detail.all_results:
            lines = [
                item
                for item in reco_detail.all_results
                if item.box[3] > 20 and re.search(r"[ぁ-んァ-ヶ一-龯]", item.text)
            ]
            if lines:
                scored = [(item, *table.score_detail(item.text)) for item in lines]
                best_item, best_score, best_breakdown = max(scored, key=lambda pair: pair[1])
                detail_str = ",".join(f"{kw}{value:+g}" for kw, value in best_breakdown) or "无命中"
                logger.info(f"HIF SP效果卡: 最高分 {best_score:.0f} [{detail_str}]「{best_item.text[:40]}」")
                target_box = best_item.box

        if target_box is None:
            logger.info("HIF SP效果卡: 无文字可读或全无命中,回退点击第一张")
            target_box = self.FIRST_CARD_BOX
        if not self._click_box_center(context, target_box, double=False):
            return self._stop_unsupported(context, "hif_sp_card_select", "card_click_failed")
        time.sleep(self.ACTION_DELAY)
        return True


@AgentServer.custom_action("ProduceChooseHIFDrinkOverflowAuto")
class ProduceChooseHIFDrinkOverflowAuto(_ProduceHIFActionBase):
    """P 饮料持有上限取舍:保持默认勾选,按剩余数补勾列表项后点「残す」。

    首版保守策略(SC-430 场景卡):新获得饮料默认已勾选;读「あとN個選択」,
    N>0 时点击手持列表首项补勾,N==0 时点「残す」提交。勾选交互细节待实机校准。
    """

    REMAIN_ROI = [260, 1180, 200, 50]
    KEEP_ROI = [210, 1090, 300, 110]
    # 勾选框 x 两种布局:実機 2026-08-14(Day3)x≈493、2026-08-15(Day5)x≈620,按 remain 反应自适应
    PICK_CHECKBOX_XS = (620, 493)
    PICK_ROWS_Y = (305, 445, 280, 353, 487, 587, 745, 885, 1025)
    SCROLL_ROUNDS = 2

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        remain = self._read_digits_text(context, self._get_screenshot(context))
        if remain is None:
            return self._stop_unsupported(context, "hif_drink_overflow", "remain_counter_not_found")

        # 点击是切换勾选:remain 下降=勾上了需要的项,上升=误取消已勾选项(立即撤销)
        active_x = self.PICK_CHECKBOX_XS[0]
        for scroll_round in range(self.SCROLL_ROUNDS):
            stagnant_taps = 0
            for row_y in self.PICK_ROWS_Y:
                while remain > 0 and stagnant_taps < 2:
                    context.tasker.controller.post_click(active_x, row_y).wait()
                    time.sleep(self.ACTION_DELAY)
                    new_remain = self._read_digits_text(context, self._get_screenshot(context))
                    if new_remain is None:
                        return self._stop_unsupported(context, "hif_drink_overflow", "remain_counter_lost_after_tap")
                    if new_remain > remain:
                        context.tasker.controller.post_click(active_x, row_y).wait()
                        time.sleep(self.ACTION_DELAY)
                        break
                    if new_remain == remain:
                        # 当前 x 无反应 → 换另一布局的勾选框 x 再试
                        alt_x = next((x for x in self.PICK_CHECKBOX_XS if x != active_x), None)
                        if alt_x:
                            active_x, alt_x = alt_x, active_x
                        stagnant_taps += 1
                        continue
                    stagnant_taps = 0
                    remain = new_remain
                if remain == 0:
                    break
            if remain == 0:
                break
            if scroll_round + 1 < self.SCROLL_ROUNDS:
                context.tasker.controller.post_swipe(360, 900, 360, 500, duration=300).wait()
                time.sleep(self.ACTION_DELAY)

        if remain != 0:
            return self._stop_unsupported(context, "hif_drink_overflow", f"pick_converge_failed: remain={remain}")

        image = self._get_screenshot(context)
        keep = self._find_text_option(context, image, ("残す",), self.KEEP_ROI)
        if not keep:
            return self._stop_unsupported(context, "hif_drink_overflow", "keep_button_not_found")
        if not self._click_box_center(context, keep.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_drink_overflow", "keep_button_click_failed")
        logger.success("HIF 饮料上限:取舍完成(remain=0,已提交残す)")
        time.sleep(self.ACTION_DELAY)
        return True

    def _read_digits_text(self, context: Context, image) -> Optional[int]:
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFDrinkRemain", [".*あと[0-9０-９]+個.*"], self.REMAIN_ROI)
        if not (reco_detail and reco_detail.hit):
            return None
        digits = "".join(char for char in reco_detail.best_result.text if char.isdigit())
        return int(digits) if digits else None


@AgentServer.custom_action("ProduceHIFSelectChangeDoneAuto")
class ProduceHIFSelectChangeDoneAuto(_ProduceHIFActionBase):
    """変卡完成提示页:点空白推进。

    注意「戻る」按钮是回退本次強化/チェンジ 的撤销键,绝不可点(用户确认 2026-08-15);
    空白点取横幅下方区(実機 2026-08-15 逐位试探:卡面 (360,640)/横幅行 (360,830) 均无效,(360,1000) 有效)。
    """

    BLANK_TAP = (360, 1000)

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

        # 底部中央大按钮:普通偶像页为「プロデュース開始」(box 约 [247,1059,225,33]);
        # True End 姫崎莉波页(実機 2026-08-15)首屏为「次へ」(box [351,1074,53,32]),按序找两者
        next_button = self._find_text_option(context, image, ("プロデュース開始", "次へ"), self.NEXT_BUTTON_ROI)
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
            f"shizen={hand.has_shizen_no_miryoku}, oneesan={hand.has_oneesan_no_kankaku}, "
            f"card_names={list(hand.card_names) or '未读到'}"
        )
        return True
