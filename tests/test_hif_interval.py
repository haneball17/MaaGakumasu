from agent.hif.domain import HIFPhase, HIFCandidate, HIFRuntimeState
from agent.hif.interval import HIFIntervalPlanner


def _candidate(candidate_id: str, category: str, *, cost: int | None = None, tags: tuple[str, ...] = ()) -> HIFCandidate:
    return HIFCandidate(candidate_id, candidate_id, category, frozenset(tags), cost)


def test_interval_planner_prioritizes_affordable_key_card_until_deck_target():
    state = HIFRuntimeState(phase=HIFPhase.INTERVAL, stamina=34, max_stamina=35, p_points=120, deck_size=20)
    decision = HIFIntervalPlanner().choose(
        state,
        [
            _candidate("basic", "skill_card", cost=50, tags=("basic",)),
            _candidate("core", "skill_card", cost=80, tags=("key_card", "good_condition")),
            _candidate("finish", "finish_interval"),
        ],
    )

    assert decision.candidate_id == "core"
    assert "牌库 20 张低于目标 22 张" in decision.reasons[0]


def test_interval_planner_never_spends_without_trusted_deck_count():
    state = HIFRuntimeState(phase=HIFPhase.INTERVAL, stamina=34, max_stamina=35, p_points=120)
    decision = HIFIntervalPlanner().choose(state, [_candidate("finish", "finish_interval")])

    assert decision.should_stop
    assert decision.stop_reason == "interval_deck_size_unknown"
