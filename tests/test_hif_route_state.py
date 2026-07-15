import pytest

from agent.hif.round_metrics import build_round_metrics
from agent.hif.route_scoring import UpgradeLevel
from agent.hif.adapters.exam_reader import ReadStatus, NumericRead, CardDetection, ExamStateObservation
from agent.hif.adapters.route_state import RouteStateRejected, RouteStateIssueCode, assemble_route_state


def _observation(*, resolve_playability: bool) -> ExamStateObservation:
    detections = [
        CardDetection("cards", (19, 884, 178, 248), "演出計画", "演出計画", playable=True if resolve_playability else None),
        CardDetection("cards", (192, 884, 175, 252), "眠気", "眠気", playable=False if resolve_playability else None),
        CardDetection("cards", (349, 884, 174, 248), "祝福", "祝福", playable=True if resolve_playability else None),
        CardDetection("cards", (513, 884, 167, 250), "祝福", "祝福+", playable=True if resolve_playability else None),
    ]
    numerics = {
        "turn": NumericRead("turn", "6", 6),
        "good_condition": NumericRead("good_condition", "47", 47),
        "focus": NumericRead("focus", "10", 10),
        "stamina": NumericRead("stamina", "33", 33),
        "reprise": NumericRead("reprise", "2", 2),
        "deck_size": NumericRead("deck_size", "22", 22),
    }
    return ExamStateObservation(
        state=None,
        detections=detections,
        numerics=numerics,
        round_metrics=build_round_metrics({"current_score": "116611", "stage_multiplier": "3807%"}),
        missing_fields=("param_vo", "param_da", "param_vi"),
        screen_confidence=0.75,
    )


def test_route_state_uses_only_current_scorer_dependencies() -> None:
    ready = assemble_route_state(
        _observation(resolve_playability=True),
        route_id="rinami_garakuta_road",
        round_key="round1",
        total_turns=9,
    )

    assert ready.state.deck_size == 22
    assert ready.state.current_score == 116611
    assert ready.state.stage_multiplier_percent == 3807
    assert ready.state.hand[-1].upgrade is UpgradeLevel.PLUS
    assert ready.targets["hand-4"].raw_card_name == "祝福+"


def test_route_state_rejects_unverified_playability_before_scoring() -> None:
    with pytest.raises(RouteStateRejected) as caught:
        assemble_route_state(
            _observation(resolve_playability=False),
            route_id="rinami_garakuta_road",
            round_key="round1",
            total_turns=9,
        )

    assert {issue.code for issue in caught.value.issues} == {RouteStateIssueCode.PLAYABILITY_UNVERIFIED}


def test_route_state_distinguishes_conflicting_numeric_read() -> None:
    observation = _observation(resolve_playability=True)
    observation.numerics["deck_size"] = NumericRead(
        "deck_size",
        "",
        None,
        status=ReadStatus.CONFLICT,
        samples=("21", "22", "23"),
    )

    with pytest.raises(RouteStateRejected) as caught:
        assemble_route_state(observation, route_id="rinami_garakuta_road", round_key="round1", total_turns=9)

    issue = next(issue for issue in caught.value.issues if issue.field == "deck_size")
    assert issue.code is RouteStateIssueCode.CONFLICT
