"""Day1 换卡测试的无副作用配对决策。"""

from typing import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChangePairDecision:
    """冻结的 UI 槽位决策；卡名由执行层点击后的 OCR 回填并验证。"""

    candidate_slot: str
    source_slot: str
    tie_break_fallback: bool


def choose_change_pair(candidate_slots: Iterable[str], source_slots: Iterable[str]) -> ChangePairDecision | None:
    """以稳定顺序选取唯一配对，不包含任何设备操作。"""

    candidates = tuple(candidate_slots)
    sources = tuple(source_slots)
    if not candidates or not sources:
        return None
    return ChangePairDecision(
        candidate_slot=candidates[0],
        source_slot=sources[0],
        tie_break_fallback=len(candidates) > 1 or len(sources) > 1,
    )
