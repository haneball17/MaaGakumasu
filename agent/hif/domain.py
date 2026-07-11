"""HIF 实机与离线层共享的领域对象。"""

from __future__ import annotations

from enum import StrEnum
from dataclasses import field, dataclass


class HIFPhase(StrEnum):
    SELECTION = "selection"
    FINALS_PREPARE = "finals_prepare"
    ROUND1 = "round1"
    INTERVAL = "interval"
    ROUND2 = "round2"
    SETTLEMENT = "settlement"
    MEMORY = "memory"


@dataclass(frozen=True, slots=True)
class HIFCandidate:
    """页面上可见且已被识别的候选。"""

    candidate_id: str
    label: str
    category: str
    tags: frozenset[str] = frozenset()
    cost: int | None = None
    confidence: float = 1.0


@dataclass(slots=True)
class HIFRuntimeState:
    """一次单步决策所需的最小可信状态。

    未读出的字段保留 ``None``，上层据此降低置信度或安全停止，而不是伪造数值。
    """

    phase: HIFPhase
    day_remaining: int | None = None
    stamina: int | None = None
    max_stamina: int | None = None
    p_points: int | None = None
    star_value: int | None = None
    affinity_level: int | None = None
    hif_bonus_level: int | None = None
    attributes: dict[str, int] = field(default_factory=dict)
    attribute_bonuses: dict[str, float] = field(default_factory=dict)
    deck_size: int | None = None
    screen_confidence: float = 1.0

    @property
    def stamina_ratio(self) -> float | None:
        if self.stamina is None or self.max_stamina is None or self.max_stamina <= 0:
            return None
        return self.stamina / self.max_stamina


@dataclass(frozen=True, slots=True)
class HIFDecision:
    """供执行层消费的单步决策结果。"""

    candidate_id: str | None
    confidence: float
    reasons: tuple[str, ...]
    unknown_factors: tuple[str, ...] = ()
    stop_reason: str = ""

    @property
    def should_stop(self) -> bool:
        return self.candidate_id is None
