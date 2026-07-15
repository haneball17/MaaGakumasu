"""冻结计划第 7 节的纯领域契约。

本模块不读取画面、不写日志、不控制设备，也不实现搜索算法。所有容器均不可变，
从而可独立序列化、哈希和离线复算。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, TypeAlias
from decimal import Decimal
from hashlib import sha256
from dataclasses import field, dataclass

from .serialization import sha256_hex

SCHEMA_VERSION = "1.0.0"


class BattleRound(StrEnum):
    ROUND1 = "round1"
    ROUND2 = "round2"


class PlanningStatus(StrEnum):
    SELECTED = "selected"
    DEGRADED = "degraded"
    STOPPED = "stopped"


class PlanningReason(StrEnum):
    VERSION_MISMATCH = "version_mismatch"
    SOFT_BUDGET_REACHED = "soft_budget_reached"
    HARD_BUDGET_REACHED = "hard_budget_reached"
    NO_COMPLETE_BATCH = "no_complete_batch"
    NO_LEGAL_ACTION = "no_legal_action"
    CANDIDATE_NOT_SEPARABLE = "candidate_not_separable"
    MODEL_UNSUPPORTED = "model_unsupported"
    SAFE_FALLBACK_USED = "safe_fallback_used"
    STATE_INCOMPLETE = "state_incomplete"
    STATE_CONFLICT = "state_conflict"


class ActionType(StrEnum):
    PLAY_CARD = "play_card"
    USE_DRINK = "use_drink"
    DRAW = "draw"
    SWAP_HAND = "swap_hand"
    END_TURN = "end_turn"


class ActionRejectionReason(StrEnum):
    CARD_DISABLED = "card_disabled"
    RESOURCE_INSUFFICIENT = "resource_insufficient"
    EFFECT_UNSUPPORTED = "effect_unsupported"
    PRECONDITION_FAILED = "precondition_failed"
    ZERO_PROGRESS = "zero_progress"


class CandidateStatus(StrEnum):
    COMPLETE = "complete"
    PRUNED = "pruned"
    DEGRADED = "degraded"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class ExecutionMode(StrEnum):
    SHADOW = "shadow"
    SINGLE_STEP = "single_step"
    BOUNDED = "bounded"


class ResolutionReason(StrEnum):
    TARGET_NOT_UNIQUE = "target_not_unique"
    TARGET_NOT_FOUND = "target_not_found"
    PAGE_MISMATCH = "page_mismatch"


DecimalMetric: TypeAlias = Decimal


@dataclass(frozen=True, slots=True, order=True)
class FixedPoint:
    """带显式 scale 的倍率等定点整数。"""

    value: int
    scale: int

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError("scale 必须为正整数")


@dataclass(frozen=True, slots=True, order=True)
class EvidenceRef:
    evidence_id: str
    kind: str
    path: str
    sha256: str


@dataclass(frozen=True, slots=True, order=True)
class CardSpec:
    card_id: str
    upgrade_level: int
    effect_version: str

    def __post_init__(self) -> None:
        if not self.card_id or self.upgrade_level < 0 or not self.effect_version:
            raise ValueError("CardSpec 字段无效")


@dataclass(frozen=True, slots=True, order=True)
class CardCount:
    spec: CardSpec
    count: int

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("卡牌数量必须为正数")


@dataclass(frozen=True, slots=True, order=True)
class ManifestEntry:
    spec: CardSpec
    count: int
    source: str
    evidence: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if self.count <= 0 or not self.source or not self.evidence:
            raise ValueError("Manifest 条目必须包含正数量、来源和证据")
        object.__setattr__(self, "evidence", tuple(sorted(self.evidence)))


@dataclass(frozen=True, slots=True)
class DeckManifest:
    total_count: int
    entries: tuple[ManifestEntry, ...]

    def __post_init__(self) -> None:
        entries = tuple(sorted(self.entries, key=lambda item: item.spec))
        if self.total_count <= 0 or sum(item.count for item in entries) != self.total_count:
            raise ValueError("DeckManifest.total_count 与条目数量不一致")
        object.__setattr__(self, "entries", entries)


@dataclass(frozen=True, slots=True, order=True)
class CardInstance:
    deck_card_id: str
    spec: CardSpec
    state: str = "available"

    def __post_init__(self) -> None:
        if not self.deck_card_id or not self.state:
            raise ValueError("卡牌实例字段不能为空")
        expected_prefix = f"{self.spec.card_id}:{self.spec.upgrade_level}:"
        copy_index = self.deck_card_id.removeprefix(expected_prefix)
        if not self.deck_card_id.startswith(expected_prefix) or not copy_index.isdecimal():
            raise ValueError("deck_card_id 必须为 <card_id>:<upgrade_level>:<copy_index>")


@dataclass(frozen=True, slots=True, order=True)
class NamedCount:
    name: str
    count: int

    def __post_init__(self) -> None:
        if not self.name or self.count < 0:
            raise ValueError("命名计数字段无效")


@dataclass(frozen=True, slots=True)
class BattleState:
    schema_version: str
    battle_round: BattleRound
    turn: int
    remaining_turns: int
    score: int
    stage_attribute: str
    stage_multiplier: FixedPoint
    stamina: int
    focus: int
    good_condition: int
    statuses: tuple[NamedCount, ...]
    hand: tuple[CardInstance, ...]
    draw_pile: tuple[CardCount, ...]
    discard_pile: tuple[CardCount, ...]
    exile_pile: tuple[CardCount, ...]
    manifest: DeckManifest
    usage_counts: tuple[NamedCount, ...]
    key_card_flags: tuple[str, ...]
    drinks: tuple[NamedCount, ...]
    items: tuple[NamedCount, ...]
    draw_resources: tuple[NamedCount, ...]
    swap_resources: tuple[NamedCount, ...]
    cross_round_resources: tuple[NamedCount, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("不支持的 BattleState schema_version")
        if self.turn < 0 or self.remaining_turns < 0 or self.score < 0 or self.stamina < 0:
            raise ValueError("牌局离散量不能为负")
        for name in (
            "statuses",
            "hand",
            "draw_pile",
            "discard_pile",
            "exile_pile",
            "usage_counts",
            "drinks",
            "items",
            "draw_resources",
            "swap_resources",
            "cross_round_resources",
        ):
            object.__setattr__(self, name, tuple(sorted(getattr(self, name))))
        object.__setattr__(self, "key_card_flags", tuple(sorted(self.key_card_flags)))


@dataclass(frozen=True, slots=True)
class ObjectiveSnapshot:
    schema_version: str
    realtime_target: int | None
    realtime_confidence: DecimalMetric | None
    realtime_source: str | None
    historical_p95: int
    historical_profile: str
    historical_sample_count: int
    base_target: int
    safety_margin: int
    safety_target: int
    cvar_alpha: DecimalMetric
    score_formula_version: str

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("不支持的 ObjectiveSnapshot schema_version")
        if min(self.historical_p95, self.historical_sample_count, self.base_target, self.safety_margin, self.safety_target) < 0:
            raise ValueError("目标字段不能为负")
        if self.realtime_confidence is not None and not Decimal(0) <= self.realtime_confidence <= Decimal(1):
            raise ValueError("实时目标置信度必须位于 [0, 1]")
        if not Decimal(0) < self.cvar_alpha <= Decimal(1):
            raise ValueError("CVaR alpha 必须位于 (0, 1]")


@dataclass(frozen=True, slots=True, order=True)
class BatchSpec:
    batch_no: int
    start_index: int
    scenario_count: int
    depth: int

    def __post_init__(self) -> None:
        if min(self.batch_no, self.start_index, self.scenario_count, self.depth) < 0 or self.scenario_count == 0:
            raise ValueError("批次字段无效")


@dataclass(frozen=True, slots=True)
class OnlineBudget:
    soft_limit_ms: int = 12_000
    hard_limit_ms: int = 16_000
    initial_scenarios: int = 128
    base_scenarios: int = 256
    batch_size: int = 64
    max_scenarios: int = 1_024
    standard_depth: int = 3
    selective_depth: int = 4

    def __post_init__(self) -> None:
        values = (
            self.soft_limit_ms,
            self.hard_limit_ms,
            self.initial_scenarios,
            self.base_scenarios,
            self.batch_size,
            self.max_scenarios,
            self.standard_depth,
            self.selective_depth,
        )
        if min(values) <= 0 or self.soft_limit_ms > self.hard_limit_ms:
            raise ValueError("在线预算必须为正数且软限制不得超过硬限制")
        if not self.initial_scenarios <= self.base_scenarios <= self.max_scenarios:
            raise ValueError("情景数量必须满足 initial <= base <= max")


@dataclass(frozen=True, slots=True)
class ReplayBudget:
    batches: tuple[BatchSpec, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "batches", tuple(sorted(self.batches)))


@dataclass(frozen=True, slots=True)
class SeedMaterial:
    state_hash: str
    algorithm_version: str
    rules_version: str
    config_version: str
    scenario_generator_version: str


@dataclass(frozen=True, slots=True)
class VersionSnapshot:
    algorithm: str
    rules: str
    card_catalog: str
    evaluator: str
    weights: str
    scenario_generator: str
    config: str


@dataclass(frozen=True, slots=True)
class PlanningRequest:
    schema_version: str
    state: BattleState
    objective: ObjectiveSnapshot
    budget: OnlineBudget | ReplayBudget
    seed_material: SeedMaterial
    decision_seed: str
    versions: VersionSnapshot

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("不支持的 PlanningRequest schema_version")
        if self.seed_material.state_hash != sha256_hex(self.state):
            raise ValueError("SeedMaterial.state_hash 与 BattleState 不一致")
        if self.decision_seed != sha256_hex(self.seed_material):
            raise ValueError("decision_seed 与 SeedMaterial 不一致")
        expected_versions = (
            self.seed_material.algorithm_version,
            self.seed_material.rules_version,
            self.seed_material.config_version,
            self.seed_material.scenario_generator_version,
        )
        actual_versions = (self.versions.algorithm, self.versions.rules, self.versions.config, self.versions.scenario_generator)
        if actual_versions != expected_versions:
            raise ValueError("SeedMaterial 与 VersionSnapshot 不一致")


@dataclass(frozen=True, slots=True)
class PostconditionSpec:
    deterministic_assertions: tuple[str, ...]
    allowed_random_outcomes: tuple[str, ...]
    conservation_assertions: tuple[str, ...]
    forbidden_outcomes: tuple[str, ...]
    verification_timeout_ms: int

    def __post_init__(self) -> None:
        if self.verification_timeout_ms <= 0:
            raise ValueError("后验验证超时必须为正数")


@dataclass(frozen=True, slots=True)
class ResourceCost:
    resource_id: str
    amount: int

    def __post_init__(self) -> None:
        if not self.resource_id or self.amount < 0:
            raise ValueError("资源消耗字段无效")


@dataclass(frozen=True, slots=True)
class _ActionBase:
    precondition_state_hash: str
    resource_costs: tuple[ResourceCost, ...]
    postcondition: PostconditionSpec
    action_key: str = field(default="", compare=True)

    @property
    def action_type(self) -> ActionType:
        raise NotImplementedError

    def payload(self) -> dict[str, object]:
        raise NotImplementedError

    def _finalize(self) -> None:
        expected = derive_action_key(self.precondition_state_hash, self.action_type, self.payload())
        if self.action_key and self.action_key != expected:
            raise ValueError("action_key 与规范动作 payload 不一致")
        object.__setattr__(self, "action_key", expected)
        object.__setattr__(self, "resource_costs", tuple(sorted(self.resource_costs, key=lambda item: (item.resource_id, item.amount))))


@dataclass(frozen=True, slots=True)
class PlayCardAction(_ActionBase):
    card_instance_id: str = ""
    expected_cost: int = 0

    @property
    def action_type(self) -> ActionType:
        return ActionType.PLAY_CARD

    def payload(self) -> dict[str, object]:
        return {"card_instance_id": self.card_instance_id, "expected_cost": self.expected_cost}

    def __post_init__(self) -> None:
        if not self.card_instance_id or self.expected_cost < 0:
            raise ValueError("出牌动作字段无效")
        self._finalize()


@dataclass(frozen=True, slots=True)
class UseDrinkAction(_ActionBase):
    resource_instance_id: str = ""

    @property
    def action_type(self) -> ActionType:
        return ActionType.USE_DRINK

    def payload(self) -> dict[str, object]:
        return {"resource_instance_id": self.resource_instance_id}

    def __post_init__(self) -> None:
        if not self.resource_instance_id:
            raise ValueError("饮料实例不能为空")
        self._finalize()


@dataclass(frozen=True, slots=True)
class DrawAction(_ActionBase):
    source_ability_id: str = ""

    @property
    def action_type(self) -> ActionType:
        return ActionType.DRAW

    def payload(self) -> dict[str, object]:
        return {"source_ability_id": self.source_ability_id}

    def __post_init__(self) -> None:
        if not self.source_ability_id:
            raise ValueError("抽牌能力不能为空")
        self._finalize()


@dataclass(frozen=True, slots=True)
class SwapHandAction(_ActionBase):
    source_ability_id: str = ""
    card_instance_ids: tuple[str, ...] = ()

    @property
    def action_type(self) -> ActionType:
        return ActionType.SWAP_HAND

    def payload(self) -> dict[str, object]:
        return {"card_instance_ids": tuple(sorted(self.card_instance_ids)), "source_ability_id": self.source_ability_id}

    def __post_init__(self) -> None:
        if not self.source_ability_id or not self.card_instance_ids:
            raise ValueError("换手动作字段无效")
        object.__setattr__(self, "card_instance_ids", tuple(sorted(self.card_instance_ids)))
        self._finalize()


@dataclass(frozen=True, slots=True)
class EndTurnAction(_ActionBase):
    reason_code: str = ""

    @property
    def action_type(self) -> ActionType:
        return ActionType.END_TURN

    def payload(self) -> dict[str, object]:
        return {"reason_code": self.reason_code}

    def __post_init__(self) -> None:
        if not self.reason_code:
            raise ValueError("结束行动原因不能为空")
        self._finalize()


BattleAction: TypeAlias = PlayCardAction | UseDrinkAction | DrawAction | SwapHandAction | EndTurnAction


@dataclass(frozen=True, slots=True, order=True)
class ScoreComponent:
    name: str
    value: DecimalMetric


@dataclass(frozen=True, slots=True, order=True)
class ResourceProjection:
    resource_id: str
    remaining: int


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    action: BattleAction
    rank: int
    scenario_count: int
    mean: DecimalMetric
    median: DecimalMetric
    p10: DecimalMetric
    cvar10: DecimalMetric
    win_probability: DecimalMetric
    failure_probability: DecimalMetric
    safety_violation_probability: DecimalMetric
    safety_margin: DecimalMetric
    confidence_interval: tuple[DecimalMetric, DecimalMetric]
    score_components: tuple[ScoreComponent, ...]
    resource_projection: tuple[ResourceProjection, ...]
    completed_depth: int
    status: CandidateStatus
    reason_code: str | None

    def __post_init__(self) -> None:
        probabilities = (self.win_probability, self.failure_probability, self.safety_violation_probability)
        if any(not Decimal(0) <= value <= Decimal(1) for value in probabilities):
            raise ValueError("候选概率必须位于 [0, 1]")


@dataclass(frozen=True, slots=True)
class RejectedAction:
    action: BattleAction
    reason_code: ActionRejectionReason


@dataclass(frozen=True, slots=True)
class SearchSummary:
    completed_batches: tuple[BatchSpec, ...]
    completed_depth: int
    scenario_count: int
    soft_budget_reached: bool
    hard_budget_reached: bool
    elapsed_ms: int
    stop_reason: str


@dataclass(frozen=True, slots=True)
class ScenarioGenerationInfo:
    generator_version: str
    namespaces: tuple[str, ...]
    deck_hash: str


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    state_hash: str
    decision_seed: str
    objective: ObjectiveSnapshot
    versions: VersionSnapshot
    completed_batches: tuple[BatchSpec, ...]
    scenario_generation: ScenarioGenerationInfo
    root_action_keys: tuple[str, ...]
    records: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningResult:
    schema_version: str
    status: PlanningStatus
    selected_action: BattleAction | None
    candidates: tuple[CandidateEvaluation, ...]
    rejected_actions: tuple[RejectedAction, ...]
    search_summary: SearchSummary
    trace: DecisionTrace
    reason_code: PlanningReason | None
    planned_state_hash: str
    planned_round: BattleRound
    planned_turn: int
    versions: VersionSnapshot

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("不支持的 PlanningResult schema_version")
        if self.status is PlanningStatus.SELECTED and self.selected_action is None:
            raise ValueError("SELECTED 结果必须包含动作")
        if self.status is PlanningStatus.STOPPED and self.selected_action is not None:
            raise ValueError("STOPPED 结果不得包含动作")
        if self.trace.state_hash != self.planned_state_hash or self.trace.versions != self.versions:
            raise ValueError("PlanningResult 与 DecisionTrace 不一致")
        if self.selected_action is not None and self.selected_action.precondition_state_hash != self.planned_state_hash:
            raise ValueError("获选动作没有绑定规划状态")


@dataclass(frozen=True, slots=True)
class DecisionCorrelation:
    """仅用于日志层关联；不进入请求、动作哈希或种子。"""

    run_id: str
    decision_id: str
    action_attempt_id: str | None


@dataclass(frozen=True, slots=True)
class ObservedBattleSnapshot:
    schema_version: str
    fields: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class VerifiedRunKnowledge:
    schema_version: str
    manifest: DeckManifest
    last_verified_state_hash: str | None


@dataclass(frozen=True, slots=True)
class StateDiff:
    from_state_hash: str | None
    to_state_hash: str
    changes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InvariantReport:
    valid: bool
    assertions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StateReady:
    state: BattleState
    state_hash: str
    diff: StateDiff
    invariants: InvariantReport


@dataclass(frozen=True, slots=True)
class StateRejected:
    missing_fields: tuple[str, ...]
    conflicts: tuple[str, ...]
    unknown_entities: tuple[str, ...]
    reason_code: PlanningReason
    reread_worthwhile: bool


@dataclass(frozen=True, slots=True)
class ScenarioRandomInput:
    scenario_id: str
    random_tape: tuple[int, ...]
    probability_weight: DecimalMetric

    def __post_init__(self) -> None:
        if not Decimal(0) < self.probability_weight <= Decimal(1):
            raise ValueError("情景真实概率权重必须位于 (0, 1]")


@dataclass(frozen=True, slots=True)
class StateTransition:
    state: BattleState
    state_hash: str
    invariants: InvariantReport


@dataclass(frozen=True, slots=True)
class LeafEvaluation:
    total: DecimalMetric
    components: tuple[ScoreComponent, ...]


@dataclass(frozen=True, slots=True)
class ContinuationEvaluation:
    total: DecimalMetric
    risk: DecimalMetric
    resource_shadow_prices: tuple[ScoreComponent, ...]


@dataclass(frozen=True, slots=True)
class ScenarioBatch:
    spec: BatchSpec
    scenarios: tuple[ScenarioRandomInput, ...]


@dataclass(frozen=True, slots=True)
class ExecutionPolicyDecision:
    approved: bool
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class LatestExecutionObservation:
    state_hash: str
    page: str


@dataclass(frozen=True, slots=True)
class RevalidationResult:
    valid: bool
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class ActionObservation:
    state_hash: str
    page: str
    target_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    action: BattleAction
    controller_command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionResolutionRejected:
    reason_code: ResolutionReason


@dataclass(frozen=True, slots=True)
class SafetyApproval:
    approved: bool
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    action_attempt_id: str
    command_sent: bool
    controller_result: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    after_state: BattleState | None
    state_hash: str | None
    diff: StateDiff | None
    assertions: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]


def derive_action_key(precondition_state_hash: str, action_type: ActionType, payload: object) -> str:
    return sha256_hex({"action_type": action_type, "payload": payload, "precondition_state_hash": precondition_state_hash})


class DecisionSeedFactory:
    @staticmethod
    def create(material: SeedMaterial) -> str:
        return sha256_hex(material)

    @staticmethod
    def derive_scenario_seed(decision_seed: str, namespace: str, scenario_index: int) -> str:
        if not namespace or scenario_index < 0:
            raise ValueError("情景命名空间不能为空且索引不能为负")
        material = f"{decision_seed}{namespace}{scenario_index}".encode()
        return sha256(material).hexdigest()


class DecisionBackend(Protocol):
    def plan(self, request: PlanningRequest) -> PlanningResult: ...


class BattleStateAssembler(Protocol):
    def build(self, observed: ObservedBattleSnapshot, knowledge: VerifiedRunKnowledge) -> StateReady | StateRejected: ...


class BattleModel(Protocol):
    def legal_actions(self, state: BattleState) -> tuple[BattleAction, ...]: ...

    def apply(self, state: BattleState, action: BattleAction, random_input: ScenarioRandomInput) -> StateTransition: ...


class StateEvaluator(Protocol):
    def evaluate_leaf(self, state: BattleState, objective: ObjectiveSnapshot) -> LeafEvaluation: ...


class ContinuationValueModel(Protocol):
    def evaluate_continuation(
        self, state: BattleState, cross_round_resources: tuple[NamedCount, ...], objective: ObjectiveSnapshot
    ) -> ContinuationEvaluation: ...


class ScenarioGenerator(Protocol):
    def generate_batch(self, seed: str, batch: BatchSpec, strata: tuple[str, ...], deck_hash: str) -> ScenarioBatch: ...


class MonotonicClock(Protocol):
    def now_ns(self) -> int: ...


class DecisionExecutionPolicy(Protocol):
    def evaluate(self, result: PlanningResult, mode: ExecutionMode) -> ExecutionPolicyDecision: ...


class PlanningResultRevalidator(Protocol):
    def revalidate(self, result: PlanningResult, latest: LatestExecutionObservation) -> RevalidationResult: ...


class BattleActionResolver(Protocol):
    def resolve(self, action: BattleAction, observation: ActionObservation) -> ResolvedAction | ActionResolutionRejected: ...


class ExecutionSafetyGate(Protocol):
    def approve(
        self,
        action: BattleAction,
        observation: LatestExecutionObservation,
        objective: ObjectiveSnapshot,
        postcondition_supported: bool,
        audit_committed: bool,
    ) -> SafetyApproval: ...


class BattleActionExecutor(Protocol):
    def execute(self, action: ResolvedAction) -> CommandReceipt: ...


class BattlePostconditionVerifier(Protocol):
    def verify(
        self,
        before_state: BattleState,
        action: BattleAction,
        postcondition: PostconditionSpec,
        observation: ObservedBattleSnapshot,
    ) -> VerificationResult: ...
