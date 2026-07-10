from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Literal, Iterable
from pathlib import Path
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


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_decision_data(path: str | Path | None = None) -> HIFDecisionData:
    decision_path = Path(path) if path else (_project_root() / "assets" / "data" / "produce_decision_data.json")
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    return HIFDecisionData(
        schema_version=payload["schema_version"],
        updated_at=payload["updated_at"],
        idol_cards=payload.get("idol_cards", []),
        skill_cards=payload.get("skill_cards", []),
        p_items=payload.get("p_items", []),
    )


def build_default_scenario_config() -> ScenarioConfig:
    return ScenarioConfig(
        scenario_name="HIF",
        selection_days=20,
        selection_trial_days=[7, 14, 20],
        finals_preparation_days=6,
        phases=["selection", "selection_exam", "selection_item", "finals_prepare", "round1", "interval", "round2"],
        beam_width=4,
        lookahead_depth=3,
        score_weights={
            "stamina": 0.4,
            "p_points": 0.35,
            "star_value": 0.7,
            "trial_readiness": 0.9,
            "memory_quality": 0.75,
            "deck_quality": 0.65,
            "finals_readiness": 0.85,
            "interval_budget": 0.8,
            "support_progress": 0.5,
            "deck_size": 0.2,
        },
        selection_targets={
            "trial_readiness": 78,
            "star_value": 40,
            "memory_quality": 48,
            "deck_quality": 44,
            "support_event_progress": 8,
            "deck_size": 22,
        },
        finals_targets={
            "finals_readiness": 52,
            "star_value": 48,
            "deck_quality": 52,
            "memory_quality": 55,
            "deck_size": 22,
        },
        interval_targets={
            "interval_budget": 80,
            "p_points": 110,
            "star_value": 52,
        },
    )


def build_default_hif_evaluation_config() -> HIFEvaluationConfig:
    base_attribute_total = 600
    flex_attribute_total = 500
    selection_attribute_total = 1100
    round1_weight = 1.2
    round2_weight = 1.0
    total_round_weight = round1_weight + round2_weight
    return HIFEvaluationConfig(
        scenario_name="HIF",
        base_attribute_total=base_attribute_total,
        flex_attribute_total=flex_attribute_total,
        selection_attribute_total=selection_attribute_total,
        base_ratio=round(base_attribute_total / selection_attribute_total, 4),
        flex_ratio=round(flex_attribute_total / selection_attribute_total, 4),
        round1_weight=round1_weight,
        round2_weight=round2_weight,
        round1_ratio=round(round1_weight / total_round_weight, 4),
        round2_ratio=round(round2_weight / total_round_weight, 4),
        selection_star_reward_cap=260,
        selection_star_reward_cap_with_bonus=390,
        public_lesson_star_total=160,
        hif_wappen_star_cap=200,
        low_attribute_penalty_note="低属性会影响整体试验分数加成，首版仅作为说明，不直接进入主评分器。",
        attribute_adaptation_note="属性贡献不是固定 33/33/33，而是受当场审查基准倍率影响。",
    )


def build_default_produce_profile(data: HIFDecisionData) -> ProduceProfile:
    record = next(
        (
            row
            for row in data.idol_cards
            if row.get("idol_name_jp") == "姫崎莉波" and "ガラクタロード" in row.get("card_name_jp", "")
        ),
        None,
    )
    if record is None:
        raise ValueError("未在 produce_decision_data.json 中找到 姫崎莉波(ガラクタロード)")

    return ProduceProfile(
        profile_name="rinami_garakuta_kansei_good_condition",
        idol_card_id=record["idol_card_id"],
        idol_name_jp=record["idol_name_jp"],
        idol_name_zh=record.get("idol_name_zh", record["idol_name_jp"]),
        card_name_jp=record["card_name_jp"],
        recommended_effect=record["recommended_effect"],
        plan="センス",
        build="好調",
        first=record["first"],
        second=record["second"],
        support_deck={"locked_core": [], "flex_slots": []},
        preferred_skill_tags={
            "buff_main": 3.0,
            "loop_core": 2.8,
            "draw_cycle": 2.6,
            "score_main": 2.2,
            "basic": 1.0,
            "trouble": -4.0,
        },
        preferred_p_item_tags={
            "star_synergy": 3.0,
            "card_gain": 2.4,
            "ppoint_gain": 2.1,
            "consult_discount": 1.7,
            "drink_gain": 1.2,
        },
        reward_priorities={
            "skill_acquire": 1.0,
            "skill_upgrade": 0.9,
            "skill_delete": 0.85,
            "p_item": 0.95,
        },
    )


def load_scenario_config(path: str | Path) -> ScenarioConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ScenarioConfig(**payload)


def load_produce_profile(path: str | Path) -> ProduceProfile:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ProduceProfile(**payload)


def build_sample_hif_case(data: HIFDecisionData, profile: ProduceProfile) -> list[RouteStep]:
    primary = profile.first.lower()
    secondary = profile.second.lower()
    p_items = build_reward_options_from_data(data, "p_item")
    p_item_actions = [
        CandidateAction(
            action_id=f"pitem:{option.option_id}",
            name=option.name,
            category="p_item",
            phase="selection_item",
            tags=option.tags,
            star_delta=3 if "star_synergy" in option.tags else 0,
            p_point_delta=12 if "ppoint_gain" in option.tags else 0,
            memory_quality_delta=2 if "card_gain" in option.tags else 0,
            deck_quality_delta=2 if "card_gain" in option.tags else 0,
            add_p_item_tags={tag: 1 for tag in option.tags},
            risk=0.1,
            metadata={"source_option_id": option.option_id},
        )
        for option in p_items[:3]
    ]

    def lesson_action(day: int, stat: str, weight: int) -> CandidateAction:
        is_primary = stat == primary
        return CandidateAction(
            action_id=f"{stat}_lesson_day_{day}",
            name=f"{stat.upper()} lesson",
            category="lesson",
            phase="selection",
            tags=[f"{stat}_lesson", "good_condition" if is_primary else "steady_growth"],
            stamina_delta=-(6 if is_primary else 5),
            trial_readiness_delta=8 if is_primary else 6,
            finals_readiness_delta=6 if is_primary else 5,
            deck_quality_delta=4 if is_primary else 3,
            star_delta=2 if is_primary else 1,
            support_progress_delta=1 if weight % 2 == 0 else 0,
            risk=0.6 if is_primary else 0.45,
        )

    def consult_action(day: int) -> CandidateAction:
        return CandidateAction(
            action_id=f"consult_day_{day}",
            name="相談",
            category="consult",
            phase="selection",
            tags=["consult", "ppoint_gain"],
            stamina_delta=-2,
            p_point_delta=32,
            deck_quality_delta=4,
            support_progress_delta=1,
            risk=0.25,
        )

    def outing_action(day: int) -> CandidateAction:
        return CandidateAction(
            action_id=f"outing_day_{day}",
            name="おでかけ",
            category="outing",
            phase="selection",
            tags=["recovery", "memory_support"],
            stamina_delta=18,
            memory_quality_delta=6,
            support_progress_delta=1,
            risk=0.1,
        )

    def event_action(day: int) -> CandidateAction:
        return CandidateAction(
            action_id=f"event_day_{day}",
            name="特別指導",
            category="event",
            phase="selection",
            tags=["star_gain", "memory_support"],
            stamina_delta=-3,
            star_delta=9,
            memory_quality_delta=7,
            finals_readiness_delta=2,
            risk=0.35,
        )

    steps: list[RouteStep] = []
    for day in range(1, 21):
        if day in {7, 14, 20}:
            steps.append(
                RouteStep(
                    step_id=f"selection_exam_{day}",
                    label=f"選抜試験 Day {day}",
                    phase="selection_exam",
                    day_number=day,
                    candidates=[
                        CandidateAction(
                            action_id=f"exam_day_{day}",
                            name="選抜試験",
                            category="exam",
                            phase="selection_exam",
                            tags=["exam"],
                            trial_readiness_delta=4,
                            finals_readiness_delta=2,
                            forced=True,
                            risk=0.05,
                        )
                    ],
                )
            )
            continue

        if day in {6, 13, 19}:
            steps.append(
                RouteStep(
                    step_id=f"selection_item_{day}",
                    label=f"カスタムPアイテム Day {day}",
                    phase="selection_item",
                    day_number=day,
                    candidates=deepcopy(p_item_actions),
                )
            )
            continue

        steps.append(
            RouteStep(
                step_id=f"selection_{day}",
                label=f"選抜日程 Day {day}",
                phase="selection",
                day_number=day,
                candidates=[
                    lesson_action(day, primary, day),
                    lesson_action(day, secondary, day),
                    consult_action(day),
                    outing_action(day),
                    event_action(day),
                ],
            )
        )

    for offset in range(1, 7):
        day = 20 + offset
        steps.append(
            RouteStep(
                step_id=f"finals_prepare_{offset}",
                label=f"本戦準備 Day {offset}",
                phase="finals_prepare",
                day_number=day,
                candidates=[
                    CandidateAction(
                        action_id=f"finals_primary_{offset}",
                        name=f"{profile.first} 仕上げ",
                        category="finals_lesson",
                        phase="finals_prepare",
                        tags=["good_condition", "score_main"],
                        stamina_delta=-5,
                        finals_readiness_delta=8,
                        deck_quality_delta=4,
                        star_delta=3,
                        risk=0.4,
                    ),
                    CandidateAction(
                        action_id=f"finals_consult_{offset}",
                        name="本戦相談",
                        category="finals_consult",
                        phase="finals_prepare",
                        tags=["consult", "ppoint_gain"],
                        stamina_delta=-2,
                        p_point_delta=24,
                        deck_quality_delta=3,
                        support_progress_delta=1,
                        finals_readiness_delta=3,
                        risk=0.2,
                    ),
                    CandidateAction(
                        action_id=f"finals_event_{offset}",
                        name="本戦イベント",
                        category="finals_event",
                        phase="finals_prepare",
                        tags=["memory_support", "star_gain"],
                        stamina_delta=-3,
                        memory_quality_delta=4,
                        star_delta=6,
                        finals_readiness_delta=4,
                        risk=0.25,
                    ),
                    CandidateAction(
                        action_id=f"finals_recover_{offset}",
                        name="本戦休息",
                        category="outing",
                        phase="finals_prepare",
                        tags=["recovery", "memory_support"],
                        stamina_delta=14,
                        memory_quality_delta=2,
                        finals_readiness_delta=1,
                        risk=0.05,
                    ),
                ],
            )
        )

    steps.extend(
        [
            RouteStep(
                step_id="round1",
                label="Round1",
                phase="round1",
                day_number=27,
                candidates=[
                    CandidateAction(
                        action_id="round1_exam",
                        name="Round1",
                        category="round_exam",
                        phase="round1",
                        tags=["exam", "round1"],
                        finals_readiness_delta=3,
                        forced=True,
                        risk=0.05,
                    )
                ],
            ),
            RouteStep(
                step_id="interval",
                label="Interval",
                phase="interval",
                day_number=28,
                candidates=[
                    CandidateAction(
                        action_id="interval_safe",
                        name="Interval: safe budget",
                        category="interval_budget",
                        phase="interval",
                        tags=["interval", "ppoint_gain"],
                        p_point_delta=18,
                        interval_budget_delta=26,
                        finals_readiness_delta=2,
                        risk=0.1,
                    ),
                    CandidateAction(
                        action_id="interval_balanced",
                        name="Interval: balanced",
                        category="interval_budget",
                        phase="interval",
                        tags=["interval", "star_gain"],
                        p_point_delta=8,
                        interval_budget_delta=18,
                        star_delta=6,
                        finals_readiness_delta=4,
                        risk=0.15,
                    ),
                    CandidateAction(
                        action_id="interval_aggressive",
                        name="Interval: aggressive",
                        category="interval_budget",
                        phase="interval",
                        tags=["interval", "score_main"],
                        p_point_delta=-10,
                        interval_budget_delta=10,
                        finals_readiness_delta=8,
                        deck_quality_delta=3,
                        risk=0.45,
                    ),
                ],
            ),
            RouteStep(
                step_id="round2",
                label="Round2",
                phase="round2",
                day_number=29,
                candidates=[
                    CandidateAction(
                        action_id="round2_exam",
                        name="Round2",
                        category="round_exam",
                        phase="round2",
                        tags=["exam", "round2"],
                        finals_readiness_delta=4,
                        forced=True,
                        risk=0.05,
                    )
                ],
            ),
        ]
    )
    return steps


def build_reward_options_from_data(data: HIFDecisionData, reward_kind: RewardKind) -> list[RewardOption]:
    if reward_kind == "p_item":
        return [
            RewardOption(
                option_id=item["p_item_id"],
                name=item["name_jp"],
                kind="p_item",
                tags=item.get("tags", []),
                metadata={"scenario": item.get("scenario", "")},
            )
            for item in data.p_items
        ]

    options = []
    for card in data.skill_cards:
        options.append(
            RewardOption(
                option_id=card["skill_card_id"],
                name=card["name_jp"],
                kind=reward_kind,
                tags=card.get("tags", []),
                metadata={
                    "type": card.get("type", ""),
                    "upgrade_priority": card.get("upgrade_priority", 0),
                    "delete_priority": card.get("delete_priority", 0),
                },
            )
        )
    return options


class PhaseResolver:
    @staticmethod
    def resolve(step: RouteStep) -> RoutePhase:
        return step.phase


class CandidateBuilder:
    def build(self, step: RouteStep, state: SimulationState) -> list[CandidateAction]:
        del state
        return deepcopy(step.candidates)


class HardGate:
    def check(self, state: SimulationState, step: RouteStep, candidate: CandidateAction) -> HardGateResult:
        forced = [action for action in step.candidates if action.forced]
        if forced and not candidate.forced:
            return HardGateResult(False, "当前步骤存在强制行动")

        interval_categories = {
            "interval_budget",
            "shop_purchase",
            "select_change",
            "drink",
            "skill_upgrade",
            "skill_customize",
            "stamina_recover",
            "finish_interval",
        }
        if step.phase == "interval" and candidate.category not in interval_categories:
            return HardGateResult(False, "Interval 仅允许预算决策")

        if state.stamina <= 10 and candidate.stamina_delta < 0 and candidate.category not in {"outing", "exam", "round_exam"}:
            return HardGateResult(False, "低体力禁止高风险推进")

        if candidate.category == "p_item" and step.phase != "selection_item":
            return HardGateResult(False, "当前阶段不允许 P 道具选择")

        return HardGateResult(True)


class SoftGate:
    def __init__(self, scenario: ScenarioConfig, profile: ProduceProfile):
        self.scenario = scenario
        self.profile = profile

    def apply(self, state: SimulationState, candidate: CandidateAction) -> SoftGateAdjustment:
        bias = 0.0
        reasons: list[str] = []

        if self.profile.build == "好調" and ("good_condition" in candidate.tags or "buff_main" in candidate.tags):
            bias += 5.0
            reasons.append("好调路线偏好")

        if f"{self.profile.first.lower()}_lesson" in candidate.tags:
            bias += 3.8
            reasons.append("主属性推进")
        elif f"{self.profile.second.lower()}_lesson" in candidate.tags:
            bias += 2.0
            reasons.append("副属性补足")

        if state.p_points < self.scenario.interval_targets["p_points"] and "ppoint_gain" in candidate.tags:
            bias += 2.6
            reasons.append("补 P 点缺口")

        if state.star_value < self.scenario.selection_targets["star_value"] and "star_gain" in candidate.tags:
            bias += 3.2
            reasons.append("补星性缺口")

        if state.deck_size > self.scenario.selection_targets["deck_size"] and candidate.category in {"consult", "finals_consult"}:
            bias += 1.5
            reasons.append("牌组偏厚时优先调整资源")

        return SoftGateAdjustment(bias_score=bias, bias_reasons=reasons)


class ImmediateScorer:
    def __init__(self, scenario: ScenarioConfig):
        self.scenario = scenario

    def score(
        self,
        state: SimulationState,
        step: RouteStep,
        candidate: CandidateAction,
        soft_gate: SoftGateAdjustment,
    ) -> ImmediateScore:
        weights = self.scenario.score_weights
        immediate_value = (
            candidate.stamina_delta * weights["stamina"]
            + candidate.p_point_delta * weights["p_points"]
            + candidate.star_delta * weights["star_value"]
            + candidate.trial_readiness_delta * weights["trial_readiness"]
            + candidate.memory_quality_delta * weights["memory_quality"]
            + candidate.deck_quality_delta * weights["deck_quality"]
            + candidate.finals_readiness_delta * weights["finals_readiness"]
            + candidate.interval_budget_delta * weights["interval_budget"]
            + candidate.support_progress_delta * weights["support_progress"]
            + candidate.deck_size_delta * weights["deck_size"]
        )

        target_gap_score = self._score_target_gap(state, step.phase, candidate)
        synergy_score = soft_gate.bias_score + self._score_existing_synergy(state, candidate)
        risk_penalty = candidate.risk * 5.0

        projected_stamina = max(0, min(state.max_stamina, state.stamina + candidate.stamina_delta))
        if projected_stamina < 8 and candidate.category not in {"outing", "exam", "round_exam"}:
            risk_penalty += 8.0

        total = immediate_value + target_gap_score + synergy_score - risk_penalty
        return ImmediateScore(
            immediate_value=round(immediate_value, 2),
            target_gap_score=round(target_gap_score, 2),
            synergy_score=round(synergy_score, 2),
            risk_penalty=round(risk_penalty, 2),
            total_score=round(total, 2),
        )

    def _score_target_gap(self, state: SimulationState, phase: RoutePhase, candidate: CandidateAction) -> float:
        if phase in {"selection", "selection_exam", "selection_item"}:
            targets = self.scenario.selection_targets
            deltas = {
                "trial_readiness": candidate.trial_readiness_delta,
                "star_value": candidate.star_delta,
                "memory_quality": candidate.memory_quality_delta,
                "deck_quality": candidate.deck_quality_delta,
                "support_event_progress": candidate.support_progress_delta,
            }
        elif phase == "interval":
            targets = self.scenario.interval_targets
            deltas = {
                "interval_budget": candidate.interval_budget_delta,
                "p_points": candidate.p_point_delta,
                "star_value": candidate.star_delta,
            }
        else:
            targets = self.scenario.finals_targets
            deltas = {
                "finals_readiness": candidate.finals_readiness_delta,
                "star_value": candidate.star_delta,
                "memory_quality": candidate.memory_quality_delta,
                "deck_quality": candidate.deck_quality_delta,
            }

        score = 0.0
        for metric, delta in deltas.items():
            current = getattr(state, metric, 0)
            target = targets.get(metric, current)
            before_gap = max(0, target - current)
            after_gap = max(0, target - (current + delta))
            score += (before_gap - after_gap) * 0.9
        return score

    @staticmethod
    def _score_existing_synergy(state: SimulationState, candidate: CandidateAction) -> float:
        score = 0.0
        for tag in candidate.tags:
            if tag in state.skill_tag_counts:
                score += min(2.0, state.skill_tag_counts[tag] * 0.5)
            if tag in state.p_item_tag_counts:
                score += min(1.8, state.p_item_tag_counts[tag] * 0.4)
        return score


class StateReducer:
    def apply(self, state: SimulationState, step: RouteStep, candidate: CandidateAction) -> SimulationState:
        next_state = deepcopy(state)
        next_state.step_index += 1
        next_state.stamina = max(0, min(next_state.max_stamina, next_state.stamina + candidate.stamina_delta))
        next_state.p_points = max(0, next_state.p_points + candidate.p_point_delta)
        next_state.star_value = max(0, next_state.star_value + candidate.star_delta)
        next_state.trial_readiness = max(0, next_state.trial_readiness + candidate.trial_readiness_delta)
        next_state.memory_quality = max(0, next_state.memory_quality + candidate.memory_quality_delta)
        next_state.deck_quality = max(0, next_state.deck_quality + candidate.deck_quality_delta)
        next_state.finals_readiness = max(0, next_state.finals_readiness + candidate.finals_readiness_delta)
        next_state.interval_budget = max(0, next_state.interval_budget + candidate.interval_budget_delta)
        next_state.support_event_progress = max(0, next_state.support_event_progress + candidate.support_progress_delta)
        next_state.deck_size = max(0, next_state.deck_size + candidate.deck_size_delta)

        for tag, count in candidate.add_skill_tags.items():
            next_state.skill_tag_counts[tag] = next_state.skill_tag_counts.get(tag, 0) + count
        for tag, count in candidate.remove_skill_tags.items():
            next_state.skill_tag_counts[tag] = max(0, next_state.skill_tag_counts.get(tag, 0) - count)
        for tag, count in candidate.add_p_item_tags.items():
            next_state.p_item_tag_counts[tag] = next_state.p_item_tag_counts.get(tag, 0) + count

        if candidate.category == "p_item":
            next_state.change_count += 1
        if candidate.category == "skill_delete":
            next_state.delete_count += 1
        if candidate.category in {"consult", "finals_consult"}:
            next_state.refresh_count += 1

        self._apply_observed_state_after(next_state, step, candidate)

        next_state.decision_history.append(
            {
                "step_id": step.step_id,
                "label": step.label,
                "phase": step.phase,
                "selected_action": candidate.name,
                "tags": candidate.tags,
            }
        )
        return next_state

    @staticmethod
    def _apply_observed_state_after(state: SimulationState, step: RouteStep, candidate: CandidateAction) -> None:
        observed = candidate.metadata.get("observed_state_after")
        if not isinstance(observed, dict):
            return

        observed_int_fields = {
            "stamina",
            "max_stamina",
            "p_points",
            "star_value",
            "deck_size",
            "trial_readiness",
            "memory_quality",
            "deck_quality",
            "finals_readiness",
            "interval_budget",
            "support_event_progress",
        }
        for field_name in observed_int_fields:
            value = observed.get(field_name)
            if isinstance(value, int | float):
                setattr(state, field_name, max(0, int(value)))

        state.stamina = min(state.max_stamina, state.stamina)
        state.snapshots.setdefault("observed_state_after", {})[step.step_id] = deepcopy(observed)


class SnapshotBuilder:
    @staticmethod
    def build(state: SimulationState) -> SelectionSnapshot:
        return SelectionSnapshot(
            final_skill_tags=deepcopy(state.skill_tag_counts),
            final_p_item_tags=deepcopy(state.p_item_tag_counts),
            star_value=state.star_value,
            deck_size=state.deck_size,
            support_event_progress=state.support_event_progress,
            change_count=state.change_count,
            delete_count=state.delete_count,
            refresh_count=state.refresh_count,
            trial_readiness=state.trial_readiness,
            memory_quality=state.memory_quality,
            deck_quality=state.deck_quality,
            p_points=state.p_points,
            stamina=state.stamina,
        )


class MemoryProjector:
    @staticmethod
    def build(snapshot: SelectionSnapshot) -> SelectionMemoryProfile:
        key_skill_tags = {
            tag: count
            for tag, count in snapshot.final_skill_tags.items()
            if tag in {"buff_main", "loop_core", "draw_cycle", "score_main", "trouble"}
        }
        key_p_item_tags = {
            tag: count
            for tag, count in snapshot.final_p_item_tags.items()
            if tag in {"star_synergy", "card_gain", "ppoint_gain", "consult_discount"}
        }
        return SelectionMemoryProfile(
            star_value=snapshot.star_value,
            deck_size=snapshot.deck_size,
            key_skill_tags=key_skill_tags,
            key_p_item_tags=key_p_item_tags,
            pending_support_events=max(0, 10 - snapshot.support_event_progress),
            deck_quality=snapshot.deck_quality,
            memory_quality=snapshot.memory_quality,
        )


class BeamPlanner:
    def __init__(
        self,
        scenario: ScenarioConfig,
        profile: ProduceProfile,
        builder: CandidateBuilder,
        hard_gate: HardGate,
        soft_gate: SoftGate,
        scorer: ImmediateScorer,
        reducer: StateReducer,
    ):
        self.scenario = scenario
        self.profile = profile
        self.builder = builder
        self.hard_gate = hard_gate
        self.soft_gate = soft_gate
        self.scorer = scorer
        self.reducer = reducer

    def choose(self, steps: list[RouteStep], state: SimulationState) -> DecisionResult:
        step = steps[state.step_index]
        candidates = self.builder.build(step, state)
        evaluations = self._evaluate_candidates(steps, state, step, candidates)
        allowed = [item for item in evaluations if item.hard_gate.allowed]
        if not allowed:
            return DecisionResult(
                selected_action={"action_id": "", "name": "", "phase": step.phase},
                candidate_scores=[self._serialize_candidate_score(item) for item in evaluations],
                rule_hits=[item.hard_gate.blocked_reason for item in evaluations if item.hard_gate.blocked_reason],
                top_reasons=["没有可执行候选"],
                confidence=0.0,
                unknown_factors=["all_candidates_blocked"],
                fallback_reason="全部候选被 HardGate 阻断",
            )

        observed_action_id = step.metadata.get("observed_selected_action_id")
        observed_evaluation = next((item for item in allowed if item.action.action_id == observed_action_id), None)
        if observed_evaluation is not None:
            return DecisionResult(
                selected_action={
                    "action_id": observed_evaluation.action.action_id,
                    "name": observed_evaluation.action.name,
                    "category": observed_evaluation.action.category,
                    "phase": observed_evaluation.action.phase,
                },
                candidate_scores=[self._serialize_candidate_score(item) for item in evaluations],
                rule_hits=[
                    "observed_replay_forced_choice",
                    *[reason for item in evaluations for reason in ([item.hard_gate.blocked_reason] if item.hard_gate.blocked_reason else [])],
                ],
                top_reasons=["真实观测回放强制选择", *observed_evaluation.top_reasons],
                confidence=1.0,
                unknown_factors=observed_evaluation.unknown_factors,
            )

        allowed.sort(key=lambda item: item.total_score, reverse=True)
        best = allowed[0]
        second = allowed[1].total_score if len(allowed) > 1 else best.total_score - 5.0
        confidence = max(0.15, min(0.99, 0.55 + (best.total_score - second) / 25.0))

        return DecisionResult(
            selected_action={
                "action_id": best.action.action_id,
                "name": best.action.name,
                "category": best.action.category,
                "phase": best.action.phase,
            },
            candidate_scores=[self._serialize_candidate_score(item) for item in evaluations],
            rule_hits=[reason for item in evaluations for reason in ([item.hard_gate.blocked_reason] if item.hard_gate.blocked_reason else [])],
            top_reasons=best.top_reasons,
            confidence=round(confidence, 2),
            unknown_factors=best.unknown_factors,
        )

    def _evaluate_candidates(
        self,
        steps: list[RouteStep],
        state: SimulationState,
        step: RouteStep,
        candidates: list[CandidateAction],
    ) -> list[Any]:
        evaluations = []
        for candidate in candidates:
            hard = self.hard_gate.check(state, step, candidate)
            soft = self.soft_gate.apply(state, candidate)
            immediate = self.scorer.score(state, step, candidate, soft)
            future_score = 0.0
            if hard.allowed:
                next_state = self.reducer.apply(state, step, candidate)
                future_score = self._beam_score(
                    steps,
                    next_state,
                    self.scenario.lookahead_depth - 1,
                )

            total_score = immediate.total_score + future_score
            reasons = self._build_reasons(candidate, hard, soft, immediate)
            unknown = self._build_unknown_factors(candidate)
            evaluations.append(
                _BeamEvaluation(
                    action=candidate,
                    hard_gate=hard,
                    soft_gate=soft,
                    immediate_score=immediate,
                    total_score=round(total_score, 2),
                    top_reasons=reasons,
                    confidence=0.0,
                    unknown_factors=unknown,
                )
            )
        return evaluations

    def _beam_score(self, steps: list[RouteStep], state: SimulationState, depth: int) -> float:
        if depth <= 0 or state.step_index >= len(steps):
            return 0.0

        step = steps[state.step_index]
        candidates = self.builder.build(step, state)
        scored: list[float] = []
        for candidate in candidates:
            hard = self.hard_gate.check(state, step, candidate)
            if not hard.allowed:
                continue
            soft = self.soft_gate.apply(state, candidate)
            immediate = self.scorer.score(state, step, candidate, soft)
            next_state = self.reducer.apply(state, step, candidate)
            future = self._beam_score(steps, next_state, depth - 1)
            scored.append(immediate.total_score + future * 0.85)

        if not scored:
            return 0.0
        scored.sort(reverse=True)
        top = scored[: self.scenario.beam_width]
        return top[0]

    @staticmethod
    def _build_reasons(
        candidate: CandidateAction,
        hard_gate: HardGateResult,
        soft_gate: SoftGateAdjustment,
        immediate: ImmediateScore,
    ) -> list[str]:
        if not hard_gate.allowed:
            return [hard_gate.blocked_reason]

        reasons = []
        reasons.extend(soft_gate.bias_reasons[:2])
        if immediate.target_gap_score > 0:
            reasons.append("补阶段目标差距")
        if immediate.immediate_value > 0:
            reasons.append("即时收益为正")
        if candidate.category == "p_item":
            reasons.append("推进剧本道具协同")
        return reasons[:3] or ["默认安全推进"]

    @staticmethod
    def _build_unknown_factors(candidate: CandidateAction) -> list[str]:
        unknown = []
        if not candidate.tags:
            unknown.append("missing_tags")
        if candidate.category == "p_item" and not candidate.metadata.get("source_option_id"):
            unknown.append("missing_p_item_source")
        return unknown

    @staticmethod
    def _serialize_candidate_score(result: Any) -> dict[str, Any]:
        payload = asdict(result.immediate_score)
        return {
            "action_id": result.action.action_id,
            "action_name": result.action.name,
            "category": result.action.category,
            "total_score": result.total_score,
            "hard_gate": asdict(result.hard_gate),
            "soft_gate": asdict(result.soft_gate),
            "immediate_score": payload,
            "top_reasons": result.top_reasons,
            "unknown_factors": result.unknown_factors,
        }


@dataclass(slots=True)
class _BeamEvaluation:
    action: CandidateAction
    hard_gate: HardGateResult
    soft_gate: SoftGateAdjustment
    immediate_score: ImmediateScore
    total_score: float
    top_reasons: list[str]
    confidence: float
    unknown_factors: list[str]


class RewardScorer:
    def __init__(self, profile: ProduceProfile):
        self.profile = profile

    def score(self, reward_kind: RewardKind, options: Iterable[RewardOption]) -> dict[str, Any]:
        ranked = []
        for option in options:
            tag_score = sum(self._tag_weight(tag, reward_kind) for tag in option.tags)
            if reward_kind in {"skill_acquire", "skill_upgrade", "skill_delete"}:
                tag_score += option.metadata.get("upgrade_priority", 0) * (1.2 if reward_kind != "skill_delete" else -0.4)
                tag_score += option.metadata.get("delete_priority", 0) * (1.6 if reward_kind == "skill_delete" else -0.5)
            if reward_kind == "p_item":
                tag_score += sum(self.profile.preferred_p_item_tags.get(tag, 0.0) for tag in option.tags)

            reasons = []
            if any(tag in self.profile.preferred_skill_tags for tag in option.tags):
                reasons.append("命中技能偏好标签")
            if any(tag in self.profile.preferred_p_item_tags for tag in option.tags):
                reasons.append("命中 P 道具偏好标签")
            if "trouble" in option.tags and reward_kind == "skill_delete":
                reasons.append("麻烦牌删除优先")
            elif "trouble" in option.tags:
                reasons.append("麻烦牌不宜拿取")

            confidence = 0.55 if option.tags else 0.35
            ranked.append(
                {
                    "option_id": option.option_id,
                    "name": option.name,
                    "kind": reward_kind,
                    "tags": option.tags,
                    "score": round(tag_score * self.profile.reward_priorities.get(reward_kind, 1.0), 2),
                    "top_reasons": reasons[:3] or ["保守默认评分"],
                    "confidence": round(confidence, 2),
                    "unknown_factors": [] if option.tags else ["missing_tags"],
                }
            )

        ranked.sort(key=lambda item: item["score"], reverse=True)
        return {
            "reward_kind": reward_kind,
            "selected_option": ranked[0] if ranked else None,
            "ranked_options": ranked,
        }

    def _tag_weight(self, tag: str, reward_kind: RewardKind) -> float:
        if reward_kind == "p_item":
            return self.profile.preferred_p_item_tags.get(tag, 0.0)
        return self.profile.preferred_skill_tags.get(tag, 0.0)


def build_initial_state() -> SimulationState:
    return SimulationState(
        step_index=0,
        phase="selection",
        day_number=1,
        stamina=34,
        max_stamina=34,
        p_points=0,
        star_value=0,
        deck_size=22,
        trial_readiness=0,
        memory_quality=0,
        deck_quality=0,
        finals_readiness=0,
        interval_budget=0,
        support_event_progress=0,
        skill_tag_counts={"basic": 3},
        p_item_tag_counts={},
    )


def simulate_hif_route(
    scenario: ScenarioConfig,
    profile: ProduceProfile,
    route_steps: list[RouteStep],
    initial_state: SimulationState | None = None,
) -> dict[str, Any]:
    builder = CandidateBuilder()
    hard_gate = HardGate()
    soft_gate = SoftGate(scenario, profile)
    scorer = ImmediateScorer(scenario)
    reducer = StateReducer()
    planner = BeamPlanner(scenario, profile, builder, hard_gate, soft_gate, scorer, reducer)

    state = deepcopy(initial_state or build_initial_state())
    step_results: list[dict[str, Any]] = []

    while state.step_index < len(route_steps):
        step = route_steps[state.step_index]
        state.phase = PhaseResolver.resolve(step)
        state.day_number = step.day_number
        decision = planner.choose(route_steps, state)
        selected_action = decision.selected_action
        if not selected_action["action_id"]:
            step_results.append(
                {
                    "step_id": step.step_id,
                    "label": step.label,
                    "phase": step.phase,
                    "decision": asdict(decision),
                    "state_after": asdict(state),
                }
            )
            break

        action = next(candidate for candidate in step.candidates if candidate.action_id == selected_action["action_id"])
        state = reducer.apply(state, step, action)

        step_results.append(
            {
                "step_id": step.step_id,
                "label": step.label,
                "phase": step.phase,
                "decision": asdict(decision),
                "state_after": asdict(state),
            }
        )

        if step.phase == "selection_exam" and step.day_number == scenario.selection_days:
            snapshot = SnapshotBuilder.build(state)
            memory = MemoryProjector.build(snapshot)
            state.snapshots["selection_snapshot"] = asdict(snapshot)
            state.snapshots["selection_memory_profile"] = asdict(memory)

    snapshot_dict = state.snapshots.get("selection_snapshot")
    memory_dict = state.snapshots.get("selection_memory_profile")
    if not snapshot_dict:
        snapshot = SnapshotBuilder.build(state)
        memory = MemoryProjector.build(snapshot)
        snapshot_dict = asdict(snapshot)
        memory_dict = asdict(memory)

    return {
        "scenario": asdict(scenario),
        "profile": asdict(profile),
        "steps": step_results,
        "selection_snapshot": snapshot_dict,
        "selection_memory_profile": memory_dict,
        "final_state": asdict(state),
    }


def simulate_hif_rewards(
    profile: ProduceProfile,
    data: HIFDecisionData,
    reward_kind: RewardKind,
    limit: int = 5,
) -> dict[str, Any]:
    options = build_reward_options_from_data(data, reward_kind)[:limit]
    scorer = RewardScorer(profile)
    return scorer.score(reward_kind, options)


def build_hif_evaluation_report(
    evaluation_config: HIFEvaluationConfig,
    simulation_result: dict[str, Any],
    scenario: ScenarioConfig,
) -> dict[str, Any]:
    selection_snapshot = simulation_result["selection_snapshot"]
    selection_memory = simulation_result["selection_memory_profile"]
    final_state = simulation_result["final_state"]

    selection_evaluation = SelectionEvaluationBreakdown(
        base_attribute_total=evaluation_config.base_attribute_total,
        flex_attribute_total=evaluation_config.flex_attribute_total,
        selection_attribute_total=evaluation_config.selection_attribute_total,
        base_ratio=evaluation_config.base_ratio,
        flex_ratio=evaluation_config.flex_ratio,
        star_completion=_completion_ratio(selection_snapshot["star_value"], evaluation_config.selection_star_reward_cap),
        trial_readiness_completion=_completion_ratio(
            selection_snapshot["trial_readiness"], scenario.selection_targets["trial_readiness"]
        ),
        memory_quality_completion=_completion_ratio(
            selection_snapshot["memory_quality"], scenario.selection_targets["memory_quality"]
        ),
        deck_quality_completion=_completion_ratio(
            selection_snapshot["deck_quality"], scenario.selection_targets["deck_quality"]
        ),
        support_progress_completion=_completion_ratio(
            selection_snapshot["support_event_progress"], scenario.selection_targets["support_event_progress"]
        ),
    )

    finals_evaluation = FinalsEvaluationBreakdown(
        round1_weight=evaluation_config.round1_weight,
        round2_weight=evaluation_config.round2_weight,
        round1_ratio=evaluation_config.round1_ratio,
        round2_ratio=evaluation_config.round2_ratio,
        interval_budget_target=scenario.interval_targets["interval_budget"],
        interval_budget_completion=_completion_ratio(
            final_state["interval_budget"], scenario.interval_targets["interval_budget"]
        ),
        finals_readiness_completion=_completion_ratio(
            final_state["finals_readiness"], scenario.finals_targets["finals_readiness"]
        ),
        star_completion=_completion_ratio(final_state["star_value"], scenario.finals_targets["star_value"]),
        deck_quality_completion=_completion_ratio(
            final_state["deck_quality"], scenario.finals_targets["deck_quality"]
        ),
        memory_quality_completion=_completion_ratio(
            final_state["memory_quality"], scenario.finals_targets["memory_quality"]
        ),
    )

    major_sources_total = (
        evaluation_config.selection_star_reward_cap
        + evaluation_config.public_lesson_star_total
        + evaluation_config.hif_wappen_star_cap
    )
    star_evaluation = StarEvaluationBreakdown(
        current_star_value=final_state["star_value"],
        selection_star_reward_cap=evaluation_config.selection_star_reward_cap,
        selection_star_reward_cap_with_bonus=evaluation_config.selection_star_reward_cap_with_bonus,
        public_lesson_star_total=evaluation_config.public_lesson_star_total,
        hif_wappen_star_cap=evaluation_config.hif_wappen_star_cap,
        relative_to_selection_cap=_completion_ratio(
            final_state["star_value"], evaluation_config.selection_star_reward_cap
        ),
        relative_to_bonus_cap=_completion_ratio(
            final_state["star_value"], evaluation_config.selection_star_reward_cap_with_bonus
        ),
        relative_to_major_sources=_completion_ratio(final_state["star_value"], major_sources_total),
        level=_star_level(final_state["star_value"], evaluation_config),
    )

    overall_assessment = {
        "strengths": _build_strengths(selection_evaluation, finals_evaluation, star_evaluation),
        "weaknesses": _build_weaknesses(selection_evaluation, finals_evaluation, star_evaluation),
        "notes": [
            "当前报表中的完成度是代理指标，不是官方最终总评公式。",
            evaluation_config.low_attribute_penalty_note,
            evaluation_config.attribute_adaptation_note,
            f"SelectionMemoryProfile 当前主保留字段：star={selection_memory['star_value']} deck={selection_memory['deck_size']}",
        ],
    }

    report = HIFEvaluationReport(
        evaluation_config=asdict(evaluation_config),
        selection_evaluation=selection_evaluation,
        finals_evaluation=finals_evaluation,
        star_evaluation=star_evaluation,
        overall_assessment=overall_assessment,
    )
    return {
        "evaluation_config": report.evaluation_config,
        "selection_evaluation": asdict(report.selection_evaluation),
        "finals_evaluation": asdict(report.finals_evaluation),
        "star_evaluation": asdict(report.star_evaluation),
        "overall_assessment": report.overall_assessment,
    }


def replay_hif_case(
    scenario: ScenarioConfig,
    profile: ProduceProfile,
    case_file: str | Path,
    initial_state: SimulationState | None = None,
) -> dict[str, Any]:
    from agent.hif.observed_case import (  # noqa: I001 延迟导入避免与 observed_case 的循环依赖
        build_initial_state_from_observed_case,
        build_route_steps_from_observed_case,
        load_observed_hif_case,
    )

    case = load_observed_hif_case(case_file)
    route_steps = build_route_steps_from_observed_case(case)
    replay_initial_state = initial_state or build_initial_state_from_observed_case(case)
    result = simulate_hif_route(scenario, profile, route_steps, initial_state=replay_initial_state)
    result["observed_case"] = {
        "case_id": case.case_id,
        "profile": case.profile,
        "step_count": len(case.steps),
        "random_event_types": [event.event_type for event in case.observed_random_events],
        "recognition_screen_states": [hint.screen_state for hint in case.recognition_hints],
        "open_questions": case.open_questions,
    }
    return result


def _completion_ratio(current: int | float, target: int | float) -> float:
    if target <= 0:
        return 0.0
    return round(current / target, 4)


def _star_level(current_star: int, config: HIFEvaluationConfig) -> str:
    if current_star < config.selection_star_reward_cap * 0.4:
        return "偏低"
    if current_star < config.selection_star_reward_cap * 0.8:
        return "达标"
    return "偏高"


def _build_strengths(
    selection: SelectionEvaluationBreakdown,
    finals: FinalsEvaluationBreakdown,
    star: StarEvaluationBreakdown,
) -> list[str]:
    strengths = []
    if selection.trial_readiness_completion >= 1.0:
        strengths.append("选拔试验准备度达标")
    if selection.deck_quality_completion >= 1.0:
        strengths.append("选拔阶段牌组质量达标")
    if finals.finals_readiness_completion >= 1.0:
        strengths.append("本战准备度达标")
    if star.level == "偏高":
        strengths.append("当前星性处于偏高区间")
    if finals.interval_budget_completion >= 1.0:
        strengths.append("Interval 预算达标")
    return strengths or ["当前样本已形成基础可通关框架"]


def _build_weaknesses(
    selection: SelectionEvaluationBreakdown,
    finals: FinalsEvaluationBreakdown,
    star: StarEvaluationBreakdown,
) -> list[str]:
    weaknesses = []
    if selection.memory_quality_completion < 1.0:
        weaknesses.append("选拔阶段记忆质量仍未达目标")
    if finals.memory_quality_completion < 1.0:
        weaknesses.append("本战记忆质量仍偏低")
    if star.level == "偏低":
        weaknesses.append("当前星性偏低，后续应提高星性获取效率")
    if finals.star_completion < 1.0:
        weaknesses.append("本战阶段星性未达到目标线")
    return weaknesses or ["当前报表未发现明显硬短板，但仍需实机验证"]
