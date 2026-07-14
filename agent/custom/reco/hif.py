"""HIF 页面识别器。"""

from __future__ import annotations

from typing import Union, Optional

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
