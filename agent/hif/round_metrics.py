"""HIF Round 与结算分数的纯解析模型。

本模块不接触 MaaFramework。ROI/OCR 适配层只负责提供原始文本，解析失败或
字段不完整时保留 ``None``，从而避免把参考倍率或局内动画中的残缺数字当成
可用于决策的实时分数。
"""

from __future__ import annotations

import re
from enum import Enum
from dataclasses import dataclass

from agent.hif.decisions.state import ParamSet


class MetricIssueCode(str, Enum):
    MISSING = "missing"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class MetricIssue:
    field: str
    code: MetricIssueCode


@dataclass(frozen=True, slots=True)
class RoundMetrics:
    """Round 画面可用于审计的参数、局内分数和当前倍率。"""

    params: ParamSet | None
    current_score: int | None
    stage_multiplier: float | None
    missing_fields: tuple[str, ...]
    issues: tuple[MetricIssue, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields


@dataclass(frozen=True, slots=True)
class SettlementMetrics:
    """结算页首名分数与动态加分。

    ``effective_multiplier`` 只在基础分和加分同时可读时计算；它不是游戏规则的
    常量，也不等同于任何预设中的参考倍率。
    """

    base_score: int | None
    bonus_score: int | None
    final_score: int | None
    effective_multiplier: float | None
    missing_fields: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields


def parse_integer(raw: str) -> int | None:
    """解析带千位分隔符的正整数；不从混合文本中猜测多个数字。"""

    compact = raw.replace(",", "").replace("，", "").replace(" ", "")
    if not compact or not re.fullmatch(r"\d+", compact):
        return None
    value = int(compact)
    return value if value >= 0 else None


def parse_stage_multiplier(raw: str) -> float | None:
    """解析 ``120%`` / ``1.2倍`` 等明确倍率文本为因子。"""

    normalized = raw.replace("％", "%").replace("×", "x").replace(",", "").strip()
    percent = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", normalized)
    if percent:
        value = float(percent.group(1)) / 100
        return value if value > 0 else None
    multiple = re.fullmatch(r"(?:x\s*)?(\d+(?:\.\d+)?)\s*倍", normalized)
    if multiple:
        value = float(multiple.group(1))
        return value if value > 0 else None
    return None


def build_round_metrics(reads: dict[str, str], *, conflicting_fields: frozenset[str] = frozenset()) -> RoundMetrics:
    """由稳定 OCR 原文构建 Round 指标；缺任一字段即标记为不可完整使用。"""

    values = {key: parse_integer(reads.get(key, "")) for key in ("param_vo", "param_da", "param_vi", "current_score")}
    multiplier = parse_stage_multiplier(reads.get("stage_multiplier", ""))
    missing = tuple(key for key, value in (*values.items(), ("stage_multiplier", multiplier)) if value is None)
    param_values = (values["param_vo"], values["param_da"], values["param_vi"])
    params = ParamSet(*param_values) if all(value is not None for value in param_values) else None
    return RoundMetrics(
        params=params,
        current_score=values["current_score"],
        stage_multiplier=multiplier,
        missing_fields=missing,
        issues=tuple(
            MetricIssue(key, MetricIssueCode.CONFLICT if key in conflicting_fields else MetricIssueCode.MISSING) for key in missing
        ),
    )


def parse_settlement_score(raw: str) -> tuple[int | None, int | None]:
    """解析结算页的 ``基础分+加分``；只接受一个显式 ``+`` 的完整文本。"""

    normalized = raw.replace("＋", "+").replace("，", ",").replace(" ", "")
    match = re.fullmatch(r"([\d,]+)\+([\d,]+)", normalized)
    if match is None:
        return None, None
    return parse_integer(match.group(1)), parse_integer(match.group(2))


def build_settlement_metrics(raw_score: str, raw_multiplier: str = "") -> SettlementMetrics:
    """构建结算指标，优先使用结算页实际的基础分与加分关系。"""

    base_score, bonus_score = parse_settlement_score(raw_score)
    final_score = base_score + bonus_score if base_score is not None and bonus_score is not None else None
    observed_multiplier = parse_stage_multiplier(raw_multiplier)
    effective_multiplier = observed_multiplier
    if effective_multiplier is None and base_score and final_score is not None:
        effective_multiplier = final_score / base_score
    missing = []
    if base_score is None:
        missing.append("settlement_base_score")
    if bonus_score is None:
        missing.append("settlement_bonus_score")
    if effective_multiplier is None:
        missing.append("settlement_multiplier")
    return SettlementMetrics(base_score, bonus_score, final_score, effective_multiplier, tuple(missing))
