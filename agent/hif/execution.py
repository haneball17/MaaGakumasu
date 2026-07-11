"""HIF 点击执行的纯安全门控。"""

from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass


class HIFExecutionMode(StrEnum):
    """用户可见的 HIF 出牌执行级别。"""

    OBSERVE = "observe_and_stop"
    SINGLE_STEP = "single_step"
    CONTINUOUS = "continuous"


@dataclass(frozen=True, slots=True)
class HIFExecutionApproval:
    """一次点击是否满足安全前置条件。"""

    should_execute: bool
    reason: str
    missing_fields: tuple[str, ...] = ()


def parse_execution_mode(value: str | None) -> HIFExecutionMode:
    """解析未知输入时回退观测模式，不能意外打开自动点击。"""

    try:
        return HIFExecutionMode(value or HIFExecutionMode.OBSERVE)
    except (TypeError, ValueError):
        return HIFExecutionMode.OBSERVE


def approve_card_execution(
    mode: HIFExecutionMode,
    *,
    screen_confidence: float,
    missing_fields: tuple[str, ...],
    target_count: int,
    postcondition_supported: bool,
    minimum_confidence: float = 0.9,
) -> HIFExecutionApproval:
    """批准一张牌的点击，任何不确定性都转为安全停止。"""

    if mode is HIFExecutionMode.OBSERVE:
        return HIFExecutionApproval(False, "observe_mode")
    if missing_fields:
        return HIFExecutionApproval(False, "missing_required_state", missing_fields)
    if screen_confidence < minimum_confidence:
        return HIFExecutionApproval(False, "screen_confidence_too_low")
    if target_count != 1:
        return HIFExecutionApproval(False, "card_target_not_unique")
    if not postcondition_supported:
        return HIFExecutionApproval(False, "postcondition_not_supported")
    return HIFExecutionApproval(True, "approved")
