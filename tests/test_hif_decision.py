from agent.hif import (
    load_decision_data,
    simulate_hif_route,
    simulate_hif_rewards,
    build_sample_hif_case,
    build_hif_evaluation_report,
    build_default_produce_profile,
    build_default_scenario_config,
    build_default_hif_evaluation_config,
)
from agent.hif.simulator import build_initial_state


def test_can_load_rinami_garakuta_profile():
    data = load_decision_data()
    profile = build_default_produce_profile(data)
    assert profile.idol_name_jp == "姫崎莉波"
    assert "ガラクタロード" in profile.card_name_jp
    assert profile.build == "好調"


def test_route_simulation_generates_snapshot_and_memory():
    data = load_decision_data()
    profile = build_default_produce_profile(data)
    scenario = build_default_scenario_config()
    result = simulate_hif_route(scenario, profile, build_sample_hif_case(data, profile))

    assert result["steps"]
    assert result["selection_snapshot"]["star_value"] >= 0
    assert "selection_memory_profile" in result
    assert result["selection_memory_profile"]["deck_size"] >= 0


def test_low_stamina_route_prefers_outing_or_forced_step():
    data = load_decision_data()
    profile = build_default_produce_profile(data)
    scenario = build_default_scenario_config()
    initial_state = build_initial_state()
    initial_state.stamina = 6
    result = simulate_hif_route(scenario, profile, build_sample_hif_case(data, profile), initial_state=initial_state)

    first_choice = result["steps"][0]["decision"]["selected_action"]["name"]
    assert first_choice in {"おでかけ", "選抜試験", "Round1", "Round2"}


def test_reward_simulation_can_rank_delete_targets():
    data = load_decision_data()
    profile = build_default_produce_profile(data)
    result = simulate_hif_rewards(profile, data, "skill_delete", limit=8)

    assert result["selected_option"] is not None
    assert result["ranked_options"][0]["score"] >= result["ranked_options"][-1]["score"]


def test_hif_evaluation_config_ratios_are_correct():
    config = build_default_hif_evaluation_config()
    assert config.base_ratio == round(600 / 1100, 4)
    assert config.flex_ratio == round(500 / 1100, 4)
    assert config.round1_ratio == round(1.2 / 2.2, 4)
    assert config.round2_ratio == round(1.0 / 2.2, 4)


def test_hif_evaluation_report_contains_expected_fields():
    data = load_decision_data()
    profile = build_default_produce_profile(data)
    scenario = build_default_scenario_config()
    route_result = simulate_hif_route(scenario, profile, build_sample_hif_case(data, profile))
    report = build_hif_evaluation_report(build_default_hif_evaluation_config(), route_result, scenario)

    assert report["selection_evaluation"]["base_ratio"] > 0
    assert report["selection_evaluation"]["flex_ratio"] > 0
    assert report["finals_evaluation"]["round1_ratio"] > 0
    assert report["finals_evaluation"]["round2_ratio"] > 0
    assert "star_evaluation" in report
    assert report["star_evaluation"]["current_star_value"] >= 0
    assert report["overall_assessment"]["strengths"]
    assert report["overall_assessment"]["notes"]
