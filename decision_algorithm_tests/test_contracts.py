from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from collections.abc import Callable

import pytest

from agent.decision_algorithm.contracts import (
    SCHEMA_VERSION,
    CardSpec,
    BatchSpec,
    ActionType,
    FixedPoint,
    BattleRound,
    BattleState,
    EvidenceRef,
    CardInstance,
    DeckManifest,
    OnlineBudget,
    ResourceCost,
    SeedMaterial,
    DecimalMetric,
    DecisionTrace,
    ManifestEntry,
    SearchSummary,
    PlanningReason,
    PlanningResult,
    PlanningStatus,
    PlayCardAction,
    ScoreComponent,
    UseDrinkAction,
    CandidateStatus,
    DecisionBackend,
    PlanningRequest,
    VersionSnapshot,
    ObjectiveSnapshot,
    PostconditionSpec,
    CandidateEvaluation,
    DecisionCorrelation,
    DecisionSeedFactory,
    ScenarioGenerationInfo,
    derive_action_key,
)
from agent.decision_algorithm.serialization import (
    SchemaValidationError,
    sha256_hex,
    validate_schema,
    canonical_json_data,
    canonical_json_text,
)


def _versions() -> VersionSnapshot:
    return VersionSnapshot("algo-1", "rules-1", "cards-1", "eval-1", "weights-1", "scenario-1", "config-1")


def _state() -> BattleState:
    card = CardSpec("blessing", 1, "effect-1")
    evidence = EvidenceRef("evidence-1", "deck_manifest", "evidence/deck.json", "a" * 64)
    return BattleState(
        schema_version=SCHEMA_VERSION,
        battle_round=BattleRound.ROUND1,
        turn=7,
        remaining_turns=6,
        score=116_611,
        stage_attribute="visual",
        stage_multiplier=FixedPoint(3_807, 100),
        stamina=33,
        focus=10,
        good_condition=47,
        statuses=(),
        hand=(CardInstance("blessing:1:0", card),),
        draw_pile=(),
        discard_pile=(),
        exile_pile=(),
        manifest=DeckManifest(1, (ManifestEntry(card, 1, "verified_deck_scan", (evidence,)),)),
        usage_counts=(),
        key_card_flags=(),
        drinks=(),
        items=(),
        draw_resources=(),
        swap_resources=(),
        cross_round_resources=(),
    )


def _objective() -> ObjectiveSnapshot:
    return ObjectiveSnapshot(
        SCHEMA_VERSION,
        300_000,
        DecimalMetric(Decimal("0.95")),
        "current_screen",
        290_000,
        "rinami_garakuta_road-v1",
        40,
        300_000,
        50_000,
        350_000,
        DecimalMetric(Decimal("0.10")),
        "1.2*S1+S2-v1",
    )


def _postcondition() -> PostconditionSpec:
    return PostconditionSpec(("turn_progressed",), (), ("deck_conserved",), ("failure_page",), 3_000)


def _play_action(state_hash: str) -> PlayCardAction:
    return PlayCardAction(state_hash, (ResourceCost("stamina", 0),), _postcondition(), card_instance_id="blessing:1:0", expected_cost=0)


def _drink_action(state_hash: str) -> UseDrinkAction:
    return UseDrinkAction(state_hash, (ResourceCost("drink:focus", 1),), _postcondition(), resource_instance_id="drink:focus:0")


def _request() -> PlanningRequest:
    state = _state()
    state_hash = sha256_hex(state)
    material = SeedMaterial(state_hash, "algo-1", "rules-1", "config-1", "scenario-1")
    return PlanningRequest(SCHEMA_VERSION, state, _objective(), OnlineBudget(), material, DecisionSeedFactory.create(material), _versions())


def _trace(request: PlanningRequest, batches: tuple[BatchSpec, ...], action_keys: tuple[str, ...] = ()) -> DecisionTrace:
    return DecisionTrace(
        request.seed_material.state_hash,
        request.decision_seed,
        request.objective,
        request.versions,
        batches,
        ScenarioGenerationInfo("scenario-1", ("draw", "shuffle", "effect"), "b" * 64),
        action_keys,
        (),
    )


def _selected_result(action: PlayCardAction, request: PlanningRequest) -> PlanningResult:
    batch = BatchSpec(0, 0, 128, 3)
    candidate = CandidateEvaluation(
        action,
        1,
        128,
        DecimalMetric(Decimal("400000")),
        DecimalMetric(Decimal("398000")),
        DecimalMetric(Decimal("355000")),
        DecimalMetric(Decimal("360000")),
        DecimalMetric(Decimal("0.96")),
        DecimalMetric(Decimal("0.04")),
        DecimalMetric(Decimal("0.01")),
        DecimalMetric(Decimal("10000")),
        (DecimalMetric(Decimal("390000")), DecimalMetric(Decimal("410000"))),
        (ScoreComponent("score", DecimalMetric(Decimal("400000"))),),
        (),
        3,
        CandidateStatus.COMPLETE,
        None,
    )
    return PlanningResult(
        SCHEMA_VERSION,
        PlanningStatus.SELECTED,
        action,
        (candidate,),
        (),
        SearchSummary((batch,), 3, 128, False, False, 900, "candidate_separated"),
        _trace(request, (batch,), (action.action_key,)),
        None,
        request.seed_material.state_hash,
        BattleRound.ROUND1,
        7,
        request.versions,
    )


def _stopped_result(request: PlanningRequest, reason: PlanningReason) -> PlanningResult:
    return PlanningResult(
        SCHEMA_VERSION,
        PlanningStatus.STOPPED,
        None,
        (),
        (),
        SearchSummary((), 0, 0, False, False, 0, reason.value),
        _trace(request, ()),
        reason,
        request.seed_material.state_hash,
        BattleRound.ROUND1,
        7,
        request.versions,
    )


def test_contract_objects_are_immutable_and_backend_is_structural() -> None:
    request = _request()
    with pytest.raises(AttributeError):
        request.decision_seed = "changed"  # type: ignore[misc]

    class Backend:
        def plan(self, request: PlanningRequest) -> PlanningResult:
            return _stopped_result(request, PlanningReason.MODEL_UNSUPPORTED)

    assert hasattr(DecisionBackend, "plan")
    assert Backend().plan(request).status is PlanningStatus.STOPPED


def test_canonical_json_and_hash_are_stable() -> None:
    first = {"z": Decimal("1.230000"), "a": 2}
    second = {"a": 2, "z": Decimal("1.23")}
    assert canonical_json_text(first) == '{"a":2,"z":"1.23"}'
    assert sha256_hex(first) == sha256_hex(second)
    with pytest.raises(TypeError, match="二进制浮点"):
        canonical_json_text({"invalid": 0.1})
    with pytest.raises(ValueError, match="最多允许"):
        canonical_json_text({"invalid": Decimal("0.1234567")})


def test_request_and_result_json_round_trip() -> None:
    request = _request()
    result = _selected_result(_play_action(request.seed_material.state_hash), request)
    for document in (request, result):
        data = canonical_json_data(document)
        assert json.loads(canonical_json_text(document)) == data
    assert canonical_json_data(request.objective)["cvar_alpha"] == "0.1"


def test_action_key_is_payload_stable_and_attempt_id_is_separate() -> None:
    state_hash = "a" * 64
    first = _play_action(state_hash)
    second = _play_action(state_hash)
    expected = derive_action_key(state_hash, ActionType.PLAY_CARD, {"card_instance_id": "blessing:1:0", "expected_cost": 0})
    assert first.action_key == second.action_key == expected
    assert "action_attempt_id" not in canonical_json_data(first)
    assert DecisionCorrelation("run-a", "decision-a", "attempt-random").action_attempt_id == "attempt-random"


def test_seed_derivation_is_stable_and_excludes_logging_ids() -> None:
    request = _request()
    seed = request.decision_seed
    assert seed == DecisionSeedFactory.create(request.seed_material)
    assert DecisionSeedFactory.derive_scenario_seed(seed, "draw", 7) == sha256(f"{seed}draw7".encode()).hexdigest()
    assert "run_id" not in canonical_json_data(request.seed_material)
    assert "decision_id" not in canonical_json_data(request.seed_material)


def test_all_five_schemas_accept_legal_contracts() -> None:
    request = _request()
    action = _play_action(request.seed_material.state_hash)
    validate_schema(request.state, "battle-state.schema.json")
    validate_schema(action, "battle-action.schema.json")
    validate_schema(_drink_action(request.seed_material.state_hash), "battle-action.schema.json")
    validate_schema(request.objective, "objective-snapshot.schema.json")
    validate_schema(request, "planning-request.schema.json")
    validate_schema(_selected_result(action, request), "planning-result.schema.json")


def test_degraded_timeout_and_safe_stop_are_legal_results() -> None:
    request = _request()
    stopped = _stopped_result(request, PlanningReason.HARD_BUDGET_REACHED)
    degraded = PlanningResult(
        stopped.schema_version,
        PlanningStatus.DEGRADED,
        None,
        stopped.candidates,
        stopped.rejected_actions,
        SearchSummary((), 0, 0, False, True, 16_000, "hard_budget_reached"),
        stopped.trace,
        PlanningReason.HARD_BUDGET_REACHED,
        stopped.planned_state_hash,
        stopped.planned_round,
        stopped.planned_turn,
        stopped.versions,
    )
    validate_schema(degraded, "planning-result.schema.json")
    validate_schema(_stopped_result(request, PlanningReason.STATE_INCOMPLETE), "planning-result.schema.json")
    validate_schema(_stopped_result(request, PlanningReason.VERSION_MISMATCH), "planning-result.schema.json")


@pytest.mark.parametrize(
    ("schema_name", "document", "mutation"),
    [
        ("battle-state.schema.json", lambda: canonical_json_data(_state()), lambda data: data.pop("manifest")),
        ("battle-action.schema.json", lambda: canonical_json_data(_play_action("a" * 64)), lambda data: data.update(expected_cost="zero")),
        ("objective-snapshot.schema.json", lambda: canonical_json_data(_objective()), lambda data: data.update(schema_version="2.0.0")),
        ("planning-request.schema.json", lambda: canonical_json_data(_request()), lambda data: data.pop("decision_seed")),
        (
            "planning-result.schema.json",
            lambda: canonical_json_data(_stopped_result(_request(), PlanningReason.STATE_INCOMPLETE)),
            lambda data: data.update(planned_turn="seven"),
        ),
    ],
)
def test_all_five_schemas_reject_invalid_contracts(
    schema_name: str, document: Callable[[], dict[str, object]], mutation: Callable[[dict[str, object]], object]
) -> None:
    data = deepcopy(document())
    mutation(data)
    with pytest.raises(SchemaValidationError):
        validate_schema(data, schema_name)
