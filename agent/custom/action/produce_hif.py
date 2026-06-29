import time
from typing import Any, Dict, List, Optional

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger


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

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        logger.success("事件: HIF 选择日程")
        image = self._get_screenshot(context)
        health_data = self._get_health(context, image) or {"current": 34, "max": 34, "ratio": 1.0}
        events = self._get_available_events(context, image)

        if not events:
            logger.warning("未识别到 HIF 可选日程，保持当前状态")
            return True

        best_event = self._choose_best_event(health_data, events)
        if not best_event:
            logger.warning("HIF 日程未命中优先级，回退到第一个可用日程")
            best_event = events[0]

        logger.info(f"HIF 选择事件: {best_event['name']}")
        return self._execute_event(context, best_event)

    def _choose_best_event(self, health_data: dict, events: list[dict]) -> Optional[dict]:
        current_health = health_data["current"]
        ratio_health = health_data["ratio"]

        if current_health <= self.LOW_HEALTH_VALUE or ratio_health <= self.LOW_HEALTH_RATIO:
            go_out = self._find_event(events, "おでかけ")
            if go_out:
                return go_out
            logger.info("HIF 低体力，回退到休息")
            return {"name": "rest", "box": [0, 0, 0, 0], "run_task": "ProduceChooseRest"}

        priority = [
            "おでかけ",
            "相談",
            "Vo",
            "Da",
            "Vi",
            "课程",
            "活动",
        ]
        for name in priority:
            event = self._find_event(events, name)
            if event:
                return event
        return None

    def _find_event(self, events: list[dict], target_name: str) -> Optional[dict]:
        for event in events:
            if event["name"] == target_name:
                return event
        return None

    def _execute_event(self, context: Context, event: dict) -> bool:
        run_task = event.get("run_task", "")
        if run_task == "ProduceChooseRest":
            logger.info("执行休息流程")
            context.run_task(run_task)
            return True

        if not self._click_box_center(context, event["box"]):
            return self._stop_unknown(context, f"???? HIF ??: {event.get('name', 'unknown')}")

        time.sleep(self.ACTION_DELAY)
        if run_task:
            logger.info(f"执行任务 {run_task}")
            context.run_task(run_task)
        return True

    def _get_available_events(self, context: Context, image) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        log_names: List[str] = []
        roi = [0, 840, 720, 280]

        for event_name, template in self.EVENT_CONFIG.items():
            reco_detail = self._run_template(context, image, "ProduceRecognitionHIFEvent", template, roi, threshold=0.78)
            if reco_detail and reco_detail.hit:
                run_task = "ProduceShoppingEntry" if event_name == "相談" else ""
                event = {"name": event_name, "box": reco_detail.best_result.box, "run_task": run_task}
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
            self._click_box_center(context, recommend, double=False, y_offset=80)
            time.sleep(self.ACTION_DELAY)
            return True

        keyword_hit = self._find_keyword_option(context, image)
        if keyword_hit:
            logger.info(f"按关键词选择 HIF P 道具: {keyword_hit['name']}")
            self._click_box_center(context, keyword_hit["box"], double=False)
            time.sleep(self.ACTION_DELAY)
            return True

        logger.warning("未识别到推荐或关键词，回退选择第一个默认 P 道具")
        first_box = self.OPTION_CANDIDATES[0]
        context.tasker.controller.post_click(first_box[0], first_box[1]).wait()
        time.sleep(self.ACTION_DELAY)
        return True

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
