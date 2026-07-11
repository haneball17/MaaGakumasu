from agent.hif.domain import HIFPhase, HIFCandidate, HIFRuntimeState
from agent.hif.presets import parse_hif_preset
from agent.hif.route_planner import HIFRoutePlanner


def _candidate(category: str) -> HIFCandidate:
    return HIFCandidate(candidate_id=category, label=category, category=category)


def test_route_planner_uses_observed_rinami_schedule_priority():
    planner = HIFRoutePlanner()
    state = HIFRuntimeState(phase=HIFPhase.FINALS_PREPARE, day_remaining=4, stamina=20, max_stamina=35)
    decision = planner.choose_schedule(
        state,
        [_candidate("go_out"), _candidate("gift")],
        parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}'),
    )

    assert decision.candidate_id == "gift"
    assert not decision.should_stop


def test_route_planner_uses_fixed_schedule_for_safe_default():
    planner = HIFRoutePlanner()
    state = HIFRuntimeState(phase=HIFPhase.FINALS_PREPARE, day_remaining=4, stamina=20, max_stamina=35)
    decision = planner.choose_schedule(state, [_candidate("gift"), _candidate("go_out")], parse_hif_preset(None))

    assert decision.candidate_id == "go_out"
    assert "固定日程" in decision.reasons[0]


def test_route_planner_stops_when_strict_preset_candidate_is_missing():
    planner = HIFRoutePlanner()
    state = HIFRuntimeState(phase=HIFPhase.FINALS_PREPARE, day_remaining=1, stamina=20, max_stamina=35)
    decision = planner.choose_schedule(
        state,
        [_candidate("Da")],
        parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}'),
    )

    assert decision.should_stop
    assert decision.stop_reason == "preset_schedule_candidate_missing"


def test_route_planner_prioritizes_outing_when_stamina_is_low():
    planner = HIFRoutePlanner()
    state = HIFRuntimeState(phase=HIFPhase.FINALS_PREPARE, day_remaining=4, stamina=8, max_stamina=35)
    decision = planner.choose_schedule(state, [_candidate("gift"), _candidate("go_out")], parse_hif_preset(None))

    assert decision.candidate_id == "go_out"
    assert decision.confidence == 0.98


def test_route_planner_reward_order_combines_preset_profile_and_effect_tags():
    planner = HIFRoutePlanner()
    ranked = planner.reward_search_order("skill", parse_hif_preset(None))

    assert ranked[0].name == "始まりの合図"
    assert "国民的アイドル" in {item.name for item in ranked}
    assert "シュプレヒコール" in {item.name for item in ranked}


def test_route_planner_uses_custom_p_item_evidence_only_for_experimental_preset():
    planner = HIFRoutePlanner()

    experimental = planner.custom_p_item_search_order(parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}'))
    safe_default = planner.custom_p_item_search_order(parse_hif_preset(None))

    assert experimental[0].name == "もじゃ（黄）"
    assert safe_default == ()


def test_route_planner_can_follow_the_confirmed_first_stage_p_item_branch():
    planner = HIFRoutePlanner()
    ranked = planner.custom_p_item_search_order(
        parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}'),
        stage=2,
        parent="もじゃ（黄）",
    )

    assert tuple(item.name for item in ranked) == ("花もじゃ（黄）",)
