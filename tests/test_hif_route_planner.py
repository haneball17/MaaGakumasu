from agent.hif.domain import HIFPhase, HIFCandidate, HIFRuntimeState
from agent.hif.catalog import HIFDrink, HIFCatalog
from agent.hif.presets import parse_hif_preset
from agent.hif.route_planner import HIFRankedName, HIFRoutePlanner


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


def test_route_planner_selects_the_unique_best_observed_drink_candidate():
    decision = HIFRoutePlanner().choose_observed_reward(
        "drink",
        ("初星黒酢", "ミックススムージー", "ブーストエキス"),
        parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}'),
    )

    assert decision.candidate_id == "初星黒酢"
    assert not decision.should_stop


def test_route_planner_stops_for_unknown_or_duplicate_observed_rewards():
    planner = HIFRoutePlanner()
    preset = parse_hif_preset(None)

    unknown = planner.choose_observed_reward("drink", ("初星黒酢", "不存在"), preset)
    duplicate = planner.choose_observed_reward("drink", ("初星黒酢", "初星黒酢"), preset)

    assert unknown.stop_reason == "unknown_observed_reward_candidate"
    assert duplicate.stop_reason == "duplicate_observed_reward_candidates"


def test_route_planner_selects_the_verified_good_condition_granting_skill_reward():
    decision = HIFRoutePlanner().choose_observed_skill_reward(
        (
            {"name": "意地", "effect_text": "元気+3 集中+4 レッスン中1回", "name_confidence": 0.999, "detail_confidence": 0.999},
            {
                "name": "トークタイム",
                "effect_text": "好調状態の場合、使用可 パラメータ+27 レッスン中1回",
                "name_confidence": 0.999,
                "detail_confidence": 0.999,
            },
            {"name": "祝福", "effect_text": "体力消費4 パラメータ+26 好調1ターン レッスン中1回", "name_confidence": 0.999, "detail_confidence": 0.999},
        ),
        parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}'),
    )

    assert decision.candidate_id == "祝福"
    assert not decision.should_stop
    assert "直接提供好调回合" in decision.reasons


def test_route_planner_rejects_a_skill_candidate_when_observed_detail_lacks_its_structured_effect():
    decision = HIFRoutePlanner().choose_observed_skill_reward(
        ({"name": "祝福", "effect_text": "体力消費4 パラメータ+26", "name_confidence": 0.999, "detail_confidence": 0.999},),
        parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}'),
    )

    assert decision.should_stop
    assert decision.stop_reason == "observed_skill_reward_detail_mismatch"


def test_route_planner_stops_when_observed_reward_top_score_is_tied(monkeypatch):
    catalog = HIFCatalog(
        skill_cards={},
        drinks={
            "甲": HIFDrink("甲", None, "free", "SR", None, "", frozenset()),
            "乙": HIFDrink("乙", None, "free", "SR", None, "", frozenset()),
        },
        custom_p_items={},
        schedule_days={},
        skill_source_updated_at="",
        drink_source_updated_at="",
        schedule_key="",
    )
    planner = HIFRoutePlanner(catalog)
    monkeypatch.setattr(
        planner,
        "reward_search_order",
        lambda *args, **kwargs: (HIFRankedName("甲", 10.0, ("测试",)), HIFRankedName("乙", 10.0, ("测试",))),
    )

    decision = planner.choose_observed_reward("drink", ("甲", "乙"), parse_hif_preset(None))

    assert decision.stop_reason == "ambiguous_observed_reward_candidates"
