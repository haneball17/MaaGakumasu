from __future__ import annotations

from typing import Any, Literal
from dataclasses import field, asdict, dataclass

RoutePhase = Literal["selection", "selection_exam", "selection_item", "finals_prepare", "round1", "interval", "round2"]
RewardKind = Literal["skill_acquire", "skill_upgrade", "skill_delete", "p_item"]


@dataclass(slots=True)
class HIFDecisionData:
    schema_version: int
    updated_at: str
    idol_cards: list[dict[str, Any]]
    skill_cards: list[dict[str, Any]]
    p_items: list[dict[str, Any]]


@dataclass(slots=True)
class ScenarioConfig:
    scenario_name: str
    selection_days: int
    selection_trial_days: list[int]
    finals_preparation_days: int
    phases: list[str]
    beam_width: int
    lookahead_depth: int
    score_weights: dict[str, float]
    selection_targets: dict[str, int]
    finals_targets: dict[str, int]
    interval_targets: dict[str, int]


@dataclass(slots=True)
class HIFEvaluationConfig:
    scenario_name: str
    base_attribute_total: int
    flex_attribute_total: int
    selection_attribute_total: int
    base_ratio: float
    flex_ratio: float
    round1_weight: float
    round2_weight: float
    round1_ratio: float
    round2_ratio: float
    selection_star_reward_cap: int
    selection_star_reward_cap_with_bonus: int
    public_lesson_star_total: int
    hif_wappen_star_cap: int
    low_attribute_penalty_note: str
    attribute_adaptation_note: str


@dataclass(slots=True)
class ProduceProfile:
    profile_name: str
    idol_card_id: str
    idol_name_jp: str
    idol_name_zh: str
    card_name_jp: str
    recommended_effect: str
    plan: str
    build: str
    first: str
    second: str
    support_deck: dict[str, list[str]]
    preferred_skill_tags: dict[str, float]
    preferred_p_item_tags: dict[str, float]
    reward_priorities: dict[str, float]


@dataclass(slots=True)
class CandidateAction:
    action_id: str
    name: str
    category: str
    phase: RoutePhase
    tags: list[str] = field(default_factory=list)
    stamina_delta: int = 0
    p_point_delta: int = 0
    star_delta: int = 0
    trial_readiness_delta: int = 0
    memory_quality_delta: int = 0
    deck_quality_delta: int = 0
    finals_readiness_delta: int = 0
    interval_budget_delta: int = 0
    support_progress_delta: int = 0
    deck_size_delta: int = 0
    add_skill_tags: dict[str, int] = field(default_factory=dict)
    add_p_item_tags: dict[str, int] = field(default_factory=dict)
    remove_skill_tags: dict[str, int] = field(default_factory=dict)
    forced: bool = False
    risk: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HardGateResult:
    allowed: bool
    blocked_reason: str = ""


@dataclass(slots=True)
class SoftGateAdjustment:
    bias_score: float
    bias_reasons: list[str]


@dataclass(slots=True)
class ImmediateScore:
    immediate_value: float
    target_gap_score: float
    synergy_score: float
    risk_penalty: float
    total_score: float


@dataclass(slots=True)
class CandidateScore:
    action_id: str
    action_name: str
    total_score: float
    immediate_score: ImmediateScore
    hard_gate: HardGateResult
    soft_gate: SoftGateAdjustment
    top_reasons: list[str]
    confidence: float
    unknown_factors: list[str]


@dataclass(slots=True)
class DecisionResult:
    selected_action: dict[str, Any]
    candidate_scores: list[dict[str, Any]]
    rule_hits: list[str]
    top_reasons: list[str]
    confidence: float
    unknown_factors: list[str]
    fallback_reason: str = ""


@dataclass(slots=True)
class SelectionSnapshot:
    final_skill_tags: dict[str, int]
    final_p_item_tags: dict[str, int]
    star_value: int
    deck_size: int
    support_event_progress: int
    change_count: int
    delete_count: int
    refresh_count: int
    trial_readiness: int
    memory_quality: int
    deck_quality: int
    p_points: int
    stamina: int


@dataclass(slots=True)
class SelectionMemoryProfile:
    star_value: int
    deck_size: int
    key_skill_tags: dict[str, int]
    key_p_item_tags: dict[str, int]
    pending_support_events: int
    deck_quality: int
    memory_quality: int


@dataclass(slots=True)
class SelectionEvaluationBreakdown:
    base_attribute_total: int
    flex_attribute_total: int
    selection_attribute_total: int
    base_ratio: float
    flex_ratio: float
    star_completion: float
    trial_readiness_completion: float
    memory_quality_completion: float
    deck_quality_completion: float
    support_progress_completion: float


@dataclass(slots=True)
class FinalsEvaluationBreakdown:
    round1_weight: float
    round2_weight: float
    round1_ratio: float
    round2_ratio: float
    interval_budget_target: int
    interval_budget_completion: float
    finals_readiness_completion: float
    star_completion: float
    deck_quality_completion: float
    memory_quality_completion: float


@dataclass(slots=True)
class StarEvaluationBreakdown:
    current_star_value: int
    selection_star_reward_cap: int
    selection_star_reward_cap_with_bonus: int
    public_lesson_star_total: int
    hif_wappen_star_cap: int
    relative_to_selection_cap: float
    relative_to_bonus_cap: float
    relative_to_major_sources: float
    level: str


@dataclass(slots=True)
class HIFEvaluationReport:
    evaluation_config: dict[str, Any]
    selection_evaluation: SelectionEvaluationBreakdown
    finals_evaluation: FinalsEvaluationBreakdown
    star_evaluation: StarEvaluationBreakdown
    overall_assessment: dict[str, Any]


@dataclass(slots=True)
class SimulationState:
    step_index: int
    phase: RoutePhase
    day_number: int
    stamina: int
    max_stamina: int
    p_points: int
    star_value: int
    deck_size: int
    trial_readiness: int
    memory_quality: int
    deck_quality: int
    finals_readiness: int
    interval_budget: int
    support_event_progress: int
    skill_tag_counts: dict[str, int] = field(default_factory=dict)
    p_item_tag_counts: dict[str, int] = field(default_factory=dict)
    change_count: int = 0
    delete_count: int = 0
    refresh_count: int = 0
    decision_history: list[dict[str, Any]] = field(default_factory=list)
    snapshots: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RewardOption:
    option_id: str
    name: str
    kind: RewardKind
    tags: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RouteStep:
    step_id: str
    label: str
    phase: RoutePhase
    day_number: int
    candidates: list[CandidateAction]
    metadata: dict[str, Any] = field(default_factory=dict)
