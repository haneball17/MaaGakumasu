"""路线评分器的数据契约；不包含 UI、坐标或 Session 状态。"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass


class BattleRound(str, Enum):
    ROUND1 = "round1"
    ROUND2 = "round2"


class UpgradeLevel(str, Enum):
    BASE = "base"
    PLUS = "plus"


class RouteDecisionStatus(str, Enum):
    SELECTED = "selected"
    REJECTED = "rejected"


class RejectionCode(str, Enum):
    UNTRUSTED_STATE = "untrusted_state"
    STALE_STATE = "stale_state"
    MISSING_STATE_FIELD = "missing_state_field"
    INVALID_STATE = "invalid_state"
    UNSUPPORTED_ROUTE = "unsupported_route"
    EMPTY_HAND = "empty_hand"
    DUPLICATE_TARGET_ID = "duplicate_target_id"
    NON_UNIQUE_TITLE = "non_unique_title"
    GRAY_CARD = "gray_card"
    UNKNOWN_CARD = "unknown_card"
    UNSUPPORTED_CARD_EFFECT = "unsupported_card_effect"
    ALREADY_USED = "already_used"
    INSUFFICIENT_STAMINA = "insufficient_stamina"
    INSUFFICIENT_FOCUS = "insufficient_focus"
    NO_LEGAL_CANDIDATE = "no_legal_candidate"
    SCORE_TIE = "score_tie"


@dataclass(frozen=True, slots=True)
class CardEffect:
    """当前路线已实证卡面的确定性效果子集。"""

    parameter_gain: int = 0
    good_condition_turns: int = 0
    excellent_condition_turns: int = 0
    fixed_guard_on_future_active: int = 0


@dataclass(frozen=True, slots=True)
class CardSpec:
    card_id: str
    title: str
    upgrade: UpgradeLevel
    stamina_cost: int
    focus_cost: int
    lesson_once: bool
    effect_version: str
    effect: CardEffect | None
    source: str

    @property
    def key(self) -> tuple[str, UpgradeLevel]:
        return self.card_id, self.upgrade


@dataclass(frozen=True, slots=True)
class HandCard:
    """同一最新画面中、已绑定唯一观察目标的手牌。"""

    target_id: str
    card_id: str
    title: str
    upgrade: UpgradeLevel
    playable: bool

    @property
    def spec_key(self) -> tuple[str, UpgradeLevel]:
        return self.card_id, self.upgrade


@dataclass(frozen=True, slots=True)
class RouteBattleState:
    """评分所需的最小可信状态。

    字段允许 ``None`` 仅为了承载读取失败并返回稳定拒绝码；评分前全部会被硬门禁。
    """

    route_id: str
    battle_round: BattleRound | None
    turn: int | None
    total_turns: int | None
    current_score: int | None
    stage_multiplier_percent: int | None
    stamina: int | None
    focus: int | None
    good_condition_turns: int | None
    reprise_count: int | None
    deck_size: int | None
    trusted: bool | None
    fresh: bool | None
    hand: tuple[HandCard, ...]
    used_card_specs: frozenset[tuple[str, UpgradeLevel]] = frozenset()


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    name: str
    raw_value: int
    weight: int
    value: int
    explanation: str


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    target_id: str
    card_id: str
    title: str
    upgrade: UpgradeLevel
    total_score: int | None
    components: tuple[ScoreComponent, ...]
    rejection_code: RejectionCode | None = None
    rejection_detail: str | None = None

    @property
    def is_legal(self) -> bool:
        return self.rejection_code is None


@dataclass(frozen=True, slots=True)
class RouteDecision:
    status: RouteDecisionStatus
    selected_target_id: str | None
    selected_card_id: str | None
    selected_title: str | None
    selected_upgrade: UpgradeLevel | None
    candidates: tuple[CandidateEvaluation, ...]
    rejection_code: RejectionCode | None = None
    rejection_detail: str | None = None

