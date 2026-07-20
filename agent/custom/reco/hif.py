"""HIF 页面识别器。"""

from __future__ import annotations

import re
import json
from typing import Union, Optional

from loguru import logger
from maa.define import RectType
from maa.context import Context
from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition

from agent.hif.reward_pages import (
    detect_drink_reward_page,
    detect_drink_reward_reveal_page,
    detect_skill_reward_reveal_page,
    detect_skill_reward_selected_page,
)


@AgentServer.custom_recognition("HIFPublicLessonPreviewDetail")
class HIFPublicLessonPreviewDetail(CustomRecognition):
    """读取已选中公开课的预览收益，并写入 Maa 原生识别详情。"""

    SELECT_ROIS = {
        "Vo": [84, 1050, 150, 100],
        "Da": [282, 1050, 150, 100],
        "Vi": [480, 1050, 150, 100],
    }
    STAMINA_ROI = [180, 42, 120, 54]
    GAIN_ROIS = {
        "star": [12, 504, 126, 70],
        "vo": [158, 504, 126, 70],
        "da": [302, 504, 126, 70],
        "vi": [446, 504, 126, 70],
    }

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        try:
            candidate = json.loads(argv.custom_recognition_param).get("candidate")
        except (TypeError, json.JSONDecodeError):
            candidate = None
        if candidate not in self.SELECT_ROIS:
            return CustomRecognition.AnalyzeResult(box=None, detail={"verified": False, "reason": "invalid_candidate"})
        if not self._is_selected(context, argv.image, candidate):
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"candidate": candidate, "verified": False, "reason": "candidate_not_selected"},
            )

        stamina = self._read_number(context, argv.image, "Stamina", self.STAMINA_ROI, r"-(\d+)", required=True)
        if stamina is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"candidate": candidate, "verified": False, "reason": "stamina_unreadable"},
            )
        gains = {"candidate": candidate, "stamina": -stamina}
        for attribute, roi in self.GAIN_ROIS.items():
            value = self._read_number(context, argv.image, attribute.title(), roi, r"\+(\d+)", required=False)
            if value is None:
                return CustomRecognition.AnalyzeResult(
                    box=None,
                    detail={"candidate": candidate, "verified": False, "reason": f"{attribute}_unreadable"},
                )
            gains[attribute] = value
        gains["verified"] = True
        logger.info(f"HIF 公开课预览: {gains}")
        return CustomRecognition.AnalyzeResult(box=[0, 0, 1, 1], detail=gains)

    def _is_selected(self, context: Context, image, candidate: str) -> bool:
        detail = context.run_recognition(
            "HIFPublicLessonPreviewSelected",
            image,
            pipeline_override={
                "HIFPublicLessonPreviewSelected": {
                    "recognition": "OCR",
                    "expected": [".*SELEC.*"],
                    "roi": self.SELECT_ROIS[candidate],
                }
            },
        )
        if detail and detail.hit:
            return True
        selected_color = context.run_recognition(
            "HIFPublicLessonPreviewSelectedColor",
            image,
            pipeline_override={
                "HIFPublicLessonPreviewSelectedColor": {
                    "recognition": "ColorMatch",
                    "method": 40,
                    "lower": [15, 100, 180],
                    "upper": [45, 255, 255],
                    "count": 100,
                    "roi": [self.SELECT_ROIS[candidate][0], 1090, self.SELECT_ROIS[candidate][2], 50],
                }
            },
        )
        return bool(selected_color and selected_color.hit)

    @staticmethod
    def _read_number(context: Context, image, field: str, roi: list[int], pattern: str, *, required: bool) -> int | None:
        name = f"HIFPublicLessonPreview{field}"
        detail = context.run_recognition(
            name,
            image,
            pipeline_override={name: {"recognition": "OCR", "expected": [f".*{pattern}.*"], "roi": roi}},
        )
        if not (detail and detail.hit):
            return None if required else 0
        matched = re.search(pattern, str(getattr(detail.best_result, "text", "")))
        return int(matched.group(1)) if matched else None


@AgentServer.custom_recognition("HIFPublicLessonPreviewNoSelection")
class HIFPublicLessonPreviewNoSelection(CustomRecognition):
    """仅在三张公开课均未选中时允许开始预览采集，避免二次点击直接结算课程。"""

    SELECT_ROIS = HIFPublicLessonPreviewDetail.SELECT_ROIS

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        for candidate, roi in self.SELECT_ROIS.items():
            detail = context.run_recognition(
                f"HIFPublicLessonPreview{candidate}SelectedColor",
                argv.image,
                pipeline_override={
                    f"HIFPublicLessonPreview{candidate}SelectedColor": {
                        "recognition": "ColorMatch",
                        "method": 40,
                        "lower": [15, 100, 180],
                        "upper": [45, 255, 255],
                        "count": 100,
                        "roi": [roi[0], 1090, roi[2], 50],
                    }
                },
            )
            if detail and detail.hit:
                return CustomRecognition.AnalyzeResult(box=None, detail={"verified": False, "reason": f"{candidate}_already_selected"})
        return CustomRecognition.AnalyzeResult(box=[0, 0, 1, 1], detail={"verified": True})


@AgentServer.custom_recognition("ProduceHIFDrinkRewardPage")
class ProduceHIFDrinkRewardPage(CustomRecognition):
    """识别 P 饮料页的提示态或已选中详情态，不执行任何点击。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        match = detect_drink_reward_page(context, argv.image)
        if match is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"detail": "未确认 P 饮料领取页"})
        box = list(match.box) if match.box else [0, 0, 1, 1]
        return CustomRecognition.AnalyzeResult(
            box=box,
            detail={"detail": "确认 P 饮料领取页", "state": match.state, "drink_name": match.name},
        )


@AgentServer.custom_recognition("ProduceHIFDrinkRewardRevealPage")
class ProduceHIFDrinkRewardRevealPage(CustomRecognition):
    """识别首次领取后的饮料展示确认页，不执行任何点击。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        match = detect_drink_reward_reveal_page(context, argv.image)
        if match is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"detail": "未确认 P 饮料展示确认页"})
        box = list(match.box) if match.box else [0, 0, 1, 1]
        return CustomRecognition.AnalyzeResult(
            box=box,
            detail={"detail": "确认 P 饮料展示确认页", "drink_name": match.name},
        )


@AgentServer.custom_recognition("ProduceHIFSkillRewardSelectedPage")
class ProduceHIFSkillRewardSelectedPage(CustomRecognition):
    """识别候选已选中后的技能卡详情态；不执行任何点击。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        match = detect_skill_reward_selected_page(context, argv.image)
        if match is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"detail": "未确认技能卡奖励详情态"})
        box = list(match.box) if match.box else [0, 0, 1, 1]
        return CustomRecognition.AnalyzeResult(
            box=box,
            detail={"detail": "确认技能卡奖励详情态", "skill_name": match.name},
        )


@AgentServer.custom_recognition("ProduceHIFSkillRewardRevealPage")
class ProduceHIFSkillRewardRevealPage(CustomRecognition):
    """识别领取技能卡后覆盖在候选页上的展示层，不执行任何点击。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        match = detect_skill_reward_reveal_page(context, argv.image)
        if match is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"detail": "未确认技能卡奖励展示层"})
        box = list(match.box) if match.box else [0, 0, 1, 1]
        return CustomRecognition.AnalyzeResult(
            box=box,
            detail={"detail": "确认技能卡奖励展示层", "skill_name": match.name},
        )
