"""Day1 换卡测试的无副作用配对决策。"""

from typing import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChangePairDecision:
    """冻结的 UI 槽位决策；卡名由执行层点击后的 OCR 回填并验证。"""

    candidate_slot: str
    source_slot: str
    tie_break_fallback: bool


@dataclass(frozen=True, slots=True)
class ObservedChangeCandidate:
    """候选换入卡的已验证观察事实。"""

    slot: str
    name: str
    metadata_known: bool
    score: float | None = None


@dataclass(frozen=True, slots=True)
class ObservedSourceCard:
    """牌库源卡的已验证观察事实；同名卡以槽位区分。"""

    slot: str
    name: str
    metadata_known: bool
    score: float | None = None


@dataclass(frozen=True, slots=True)
class TargetDecision:
    """候选阶段的明确决策，或必须停止的原因。"""

    candidate_slot: str | None
    candidate_name: str | None
    reason: str
    rejected_reasons: tuple[str, ...] = ()
    unknown_factors: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.candidate_slot is not None and self.candidate_name is not None


@dataclass(frozen=True, slots=True)
class SourceDecision:
    """源卡阶段的明确决策，或必须停止的原因。"""

    source_slot: str | None
    source_name: str | None
    reason: str
    rejected_reasons: tuple[str, ...] = ()
    unknown_factors: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.source_slot is not None and self.source_name is not None


def choose_change_pair(candidate_slots: Iterable[str], source_slots: Iterable[str]) -> ChangePairDecision | None:
    """机械链路回归专用：以稳定顺序选取配对，不得用于生产决策。"""

    candidates = tuple(candidate_slots)
    sources = tuple(source_slots)
    if not candidates or not sources:
        return None
    return ChangePairDecision(
        candidate_slot=candidates[0],
        source_slot=sources[0],
        tie_break_fallback=len(candidates) > 1 or len(sources) > 1,
    )


def decide_change_target(candidates: Iterable[ObservedChangeCandidate]) -> TargetDecision:
    """只接受元数据完整且最高分唯一的候选换入卡。"""

    observed = tuple(candidates)
    if not observed:
        return TargetDecision(None, None, "no_change_candidate")
    unknown = tuple(candidate.name for candidate in observed if not candidate.metadata_known)
    if unknown:
        return TargetDecision(None, None, "unknown_change_candidate", unknown_factors=unknown)
    unscored = tuple(candidate.name for candidate in observed if candidate.score is None)
    if unscored:
        return TargetDecision(None, None, "change_candidate_score_missing", unknown_factors=unscored)
    highest_score = max(candidate.score for candidate in observed if candidate.score is not None)
    best = tuple(candidate for candidate in observed if candidate.score == highest_score)
    if len(best) != 1:
        return TargetDecision(
            None,
            None,
            "change_candidate_score_tied",
            rejected_reasons=tuple(candidate.name for candidate in best),
        )
    chosen = best[0]
    return TargetDecision(chosen.slot, chosen.name, "unique_highest_score")


def decide_change_source(cards: Iterable[ObservedSourceCard]) -> SourceDecision:
    """只接受元数据完整且最高分唯一的牌库源卡。"""

    observed = tuple(cards)
    if not observed:
        return SourceDecision(None, None, "no_change_source")
    unknown = tuple(card.name for card in observed if not card.metadata_known)
    if unknown:
        return SourceDecision(None, None, "unknown_change_source", unknown_factors=unknown)
    unscored = tuple(card.name for card in observed if card.score is None)
    if unscored:
        return SourceDecision(None, None, "change_source_score_missing", unknown_factors=unscored)
    highest_score = max(card.score for card in observed if card.score is not None)
    best = tuple(card for card in observed if card.score == highest_score)
    if len(best) != 1:
        return SourceDecision(
            None,
            None,
            "change_source_score_tied",
            rejected_reasons=tuple(card.name for card in best),
        )
    chosen = best[0]
    return SourceDecision(chosen.slot, chosen.name, "unique_highest_score")
