"""HIF 奖励页面的只读双态识别。

P 饮料页在点击一个槽位后会将提示文本替换为详情。该状态仍是可领取的
资源选择页，必须同时确认已收录的饮料名称和唯一的“受け取る”按钮，不能
仅凭页面变化或单一按钮推断。
"""

from __future__ import annotations

import re
from typing import Any
from dataclasses import dataclass

from agent.hif.catalog import load_hif_catalog
from agent.hif.screen_profiles import load_hif_screen_profiles


@dataclass(frozen=True, slots=True)
class HIFDrinkRewardPageMatch:
    """P 饮料领取页的可信识别结果。"""

    state: str
    name: str | None
    box: tuple[int, int, int, int] | None


@dataclass(frozen=True, slots=True)
class HIFSkillRewardPageMatch:
    """技能卡领取页在候选被选中后的可信详情态。"""

    name: str
    box: tuple[int, int, int, int] | None


def _run_ocr(context: Any, image: Any, name: str, expected: list[str], roi: list[int]):
    return context.run_recognition(
        name,
        image,
        pipeline_override={name: {"recognition": "OCR", "expected": expected, "roi": roi}},
    )


def _result_box(reco_detail: Any) -> tuple[int, int, int, int] | None:
    best_result = getattr(reco_detail, "best_result", None)
    raw_box = getattr(best_result, "box", None)
    try:
        box = tuple(int(value) for value in raw_box)
    except (TypeError, ValueError):
        return None
    return box if len(box) == 4 else None


def detect_drink_reward_page(context: Any, image: Any) -> HIFDrinkRewardPageMatch | None:
    """识别提示态，或“已知饮料详情 + 领取按钮”的已选中态。"""

    profile = load_hif_screen_profiles().get("drink_reward")
    if profile is None:
        return None
    prompt = profile.anchors[0]
    prompt_reco = _run_ocr(
        context,
        image,
        "ProduceRecognitionHIFDrinkRewardPrompt",
        [prompt.pattern],
        list(prompt.roi),
    )
    if prompt_reco and prompt_reco.hit:
        return HIFDrinkRewardPageMatch("prompt", None, _result_box(prompt_reco))

    details_roi = profile.regions.get("details")
    receive = profile.buttons.get("receive")
    if details_roi is None or receive is None:
        return None
    receive_reco = _run_ocr(
        context,
        image,
        "ProduceRecognitionHIFDrinkRewardReceive",
        [f".*{re.escape(receive.text)}.*"],
        list(receive.roi),
    )
    if not (receive_reco and receive_reco.hit):
        return None

    for drink_name in _known_drink_names():
        detail_reco = _run_ocr(
            context,
            image,
            "ProduceRecognitionHIFDrinkRewardKnownDetail",
            [f".*{re.escape(drink_name)}.*"],
            list(details_roi),
        )
        if detail_reco and detail_reco.hit:
            return HIFDrinkRewardPageMatch("selected_detail", drink_name, _result_box(detail_reco))
    return None


def detect_drink_reward_reveal_page(context: Any, image: Any) -> HIFDrinkRewardPageMatch | None:
    """识别首次领取后出现的饮料展示确认页。

    该页面的饮料名会再次出现在已采样的金色展示条中；它必须与同页的
    ``受け取る`` 按钮同时命中，避免把普通三槽详情页误当作展示确认页。
    """

    profile = load_hif_screen_profiles().get("drink_reward")
    if profile is None:
        return None
    reveal_name_roi = profile.regions.get("reveal_name")
    receive = profile.buttons.get("receive")
    if reveal_name_roi is None or receive is None:
        return None
    receive_reco = _run_ocr(
        context,
        image,
        "ProduceRecognitionHIFDrinkRewardRevealReceive",
        [f".*{re.escape(receive.text)}.*"],
        list(receive.roi),
    )
    if not (receive_reco and receive_reco.hit):
        return None
    for drink_name in _known_drink_names():
        name_reco = _run_ocr(
            context,
            image,
            "ProduceRecognitionHIFDrinkRewardRevealName",
            [f".*{re.escape(drink_name)}.*"],
            list(reveal_name_roi),
        )
        if name_reco and name_reco.hit:
            return HIFDrinkRewardPageMatch("reveal", drink_name, _result_box(name_reco))
    return None


def detect_skill_reward_selected_page(context: Any, image: Any) -> HIFSkillRewardPageMatch | None:
    """确认候选选中后的技能卡详情态，避免把提示态消失误判为离开奖励页。"""

    profile = load_hif_screen_profiles().get("skill_reward")
    if profile is None:
        return None
    detail_name_roi = profile.regions.get("detail_name")
    receive = profile.buttons.get("receive")
    if detail_name_roi is None or receive is None:
        return None
    receive_reco = _run_ocr(
        context,
        image,
        "ProduceRecognitionHIFSkillRewardReceive",
        [f".*{re.escape(receive.text)}.*"],
        list(receive.roi),
    )
    if not (receive_reco and receive_reco.hit):
        return None
    known_names = _known_skill_names()
    detail_reco = _run_ocr(
        context,
        image,
        "ProduceRecognitionHIFSkillRewardKnownDetail",
        [f".*{re.escape(name)}.*" for name in known_names],
        list(detail_name_roi),
    )
    if not (detail_reco and detail_reco.hit):
        return None
    raw_text = str(getattr(getattr(detail_reco, "best_result", None), "text", ""))
    name = next((candidate for candidate in known_names if candidate in raw_text), None)
    return HIFSkillRewardPageMatch(name, _result_box(detail_reco)) if name else None


def detect_skill_reward_reveal_page(context: Any, image: Any) -> HIFSkillRewardPageMatch | None:
    """识别技能卡领取后覆盖在候选页上的展示层。"""

    profile = load_hif_screen_profiles().get("skill_reward")
    if profile is None:
        return None
    reveal_name_roi = profile.regions.get("reveal_name")
    receive = profile.buttons.get("receive")
    if reveal_name_roi is None or receive is None:
        return None
    receive_reco = _run_ocr(
        context,
        image,
        "ProduceRecognitionHIFSkillRewardRevealReceive",
        [f".*{re.escape(receive.text)}.*"],
        list(receive.roi),
    )
    if not (receive_reco and receive_reco.hit):
        return None
    for skill_name in _known_skill_names():
        name_reco = _run_ocr(
            context,
            image,
            "ProduceRecognitionHIFSkillRewardRevealName",
            [f".*{re.escape(skill_name)}.*"],
            list(reveal_name_roi),
        )
        if name_reco and name_reco.hit:
            return HIFSkillRewardPageMatch(skill_name, _result_box(name_reco))
    return None


def _known_drink_names() -> list[str]:
    return sorted(load_hif_catalog().drink_names, key=len, reverse=True)


def _known_skill_names() -> list[str]:
    return sorted(load_hif_catalog().skill_names, key=len, reverse=True)
