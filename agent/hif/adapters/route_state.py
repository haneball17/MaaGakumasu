"""把同一次出牌观察组装为当前路线评分器输入。"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass

from agent.hif.route_scoring import HandCard, BattleRound, UpgradeLevel, RouteBattleState
from agent.hif.adapters.exam_reader import ReadStatus, CardDetection, ExamStateObservation


class RouteStateIssueCode(str, Enum):
    MISSING = "missing"
    CONFLICT = "conflict"
    PLAYABILITY_UNVERIFIED = "playability_unverified"
    UNSUPPORTED_ROUND = "unsupported_round"
    UNSUPPORTED_UPGRADE = "unsupported_upgrade"


@dataclass(frozen=True, slots=True)
class RouteStateIssue:
    field: str
    code: RouteStateIssueCode
    detail: str = ""


class RouteStateRejected(ValueError):
    def __init__(self, issues: tuple[RouteStateIssue, ...]) -> None:
        self.issues = issues
        super().__init__(",".join(f"{issue.field}:{issue.code.value}" for issue in issues))


@dataclass(frozen=True, slots=True)
class RouteStateReady:
    state: RouteBattleState
    targets: dict[str, CardDetection]


_NUMERIC_FIELDS = {
    "turn": "turn",
    "good_condition": "good_condition_turns",
    "focus": "focus",
    "stamina": "stamina",
    "deck_size": "deck_size",
}


def assemble_route_state(
    observation: ExamStateObservation,
    *,
    route_id: str,
    round_key: str,
    total_turns: int,
) -> RouteStateReady:
    """只要求评分器真正读取的字段；无关的旧 ``ExamState`` 字段不阻塞。"""

    issues: list[RouteStateIssue] = []
    numeric_values: dict[str, int] = {}
    for source, target in _NUMERIC_FIELDS.items():
        reading = observation.numerics.get(source)
        if reading is None or reading.value is None:
            code = RouteStateIssueCode.CONFLICT if reading and reading.status is ReadStatus.CONFLICT else RouteStateIssueCode.MISSING
            issues.append(RouteStateIssue(source, code, repr(reading.samples) if reading else ""))
        else:
            numeric_values[target] = reading.value

    metrics = observation.round_metrics
    if metrics.current_score is None:
        issues.append(RouteStateIssue("current_score", _metric_issue_code(observation, "current_score")))
    if metrics.stage_multiplier is None:
        issues.append(RouteStateIssue("stage_multiplier", _metric_issue_code(observation, "stage_multiplier")))

    round_map = {"round1": BattleRound.ROUND1, "round2": BattleRound.ROUND2}
    battle_round = round_map.get(round_key)
    if battle_round is None:
        issues.append(RouteStateIssue("battle_round", RouteStateIssueCode.UNSUPPORTED_ROUND, round_key))

    active = sorted(
        (detection for detection in observation.detections if not detection.suppressed_reason),
        key=lambda detection: detection.box[0],
    )
    hand: list[HandCard] = []
    targets: dict[str, CardDetection] = {}
    for index, detection in enumerate(active, start=1):
        target_id = f"hand-{index}"
        if not detection.card_name:
            issues.append(RouteStateIssue(target_id, RouteStateIssueCode.MISSING, "card_name"))
            continue
        if detection.playable is None:
            issues.append(RouteStateIssue(target_id, RouteStateIssueCode.PLAYABILITY_UNVERIFIED, detection.card_name))
            continue
        raw_name = detection.raw_card_name or detection.card_name
        suffix_length = len(raw_name) - len(raw_name.rstrip("+"))
        if suffix_length > 1:
            issues.append(RouteStateIssue(target_id, RouteStateIssueCode.UNSUPPORTED_UPGRADE, raw_name))
            continue
        upgrade = UpgradeLevel.PLUS if suffix_length == 1 else UpgradeLevel.BASE
        hand.append(HandCard(target_id, detection.card_name, detection.card_name, upgrade, detection.playable))
        targets[target_id] = detection

    if not active:
        issues.append(RouteStateIssue("hand", RouteStateIssueCode.MISSING))
    if issues:
        raise RouteStateRejected(tuple(issues))

    assert battle_round is not None
    assert metrics.current_score is not None
    assert metrics.stage_multiplier is not None
    reprise_read = observation.numerics.get("reprise")
    return RouteStateReady(
        RouteBattleState(
            route_id=route_id,
            battle_round=battle_round,
            turn=numeric_values["turn"],
            total_turns=total_turns,
            current_score=metrics.current_score,
            stage_multiplier_percent=round(metrics.stage_multiplier * 100),
            stamina=numeric_values["stamina"],
            focus=numeric_values["focus"],
            good_condition_turns=numeric_values["good_condition_turns"],
            reprise_count=reprise_read.value if reprise_read is not None else None,
            deck_size=numeric_values["deck_size"],
            trusted=True,
            fresh=True,
            hand=tuple(hand),
        ),
        targets,
    )


def _metric_issue_code(observation: ExamStateObservation, field: str) -> RouteStateIssueCode:
    issue = next((item for item in observation.round_metrics.issues if item.field == field), None)
    if issue is not None and issue.code.value == "conflict":
        return RouteStateIssueCode.CONFLICT
    return RouteStateIssueCode.MISSING
