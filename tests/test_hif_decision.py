import re
import sys
import json
from types import SimpleNamespace
from pathlib import Path
from importlib import import_module

import pytest

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
from agent.hif.decisions.state import ExamRound, ExamState, HandSummary
from agent.hif.decisions.round1_fallback import (
    choose_observed_round1_recovery_card,
    choose_high_good_condition_topic_card,
    choose_observed_round1_post_topic_card,
    choose_observed_round1_post_shikirinaoshi_card,
)


def _observed_round1_recovery_state() -> ExamState:
    return ExamState(
        round=ExamRound.HONSEN_R1,
        turn=7,
        total_turns=9,
        current_flow="Vi",
        good_condition_turns=40,
        focus=4,
        stamina=30,
        hand=HandSummary(False, False, False, 2, False, False),
        reprise_count=2,
        cards_played=0,
        deck_size=21,
        oneesan_used=True,
        natural_finisher_used=False,
        available_p_drinks=[],
    )


def test_observed_round1_recovery_hand_prefers_tenbu_for_focus_and_deck_setup():
    action = choose_observed_round1_recovery_card(_observed_round1_recovery_state(), ["天賦の才", "シュプレヒコール"])

    assert action is not None
    assert action.target_card == "天賦の才"


def test_observed_round1_recovery_rule_refuses_any_unobserved_candidate_set():
    assert choose_observed_round1_recovery_card(_observed_round1_recovery_state(), ["天賦の才"]) is None


def test_high_good_condition_topic_card_is_unique_and_zero_cost():
    action = choose_high_good_condition_topic_card(_observed_round1_recovery_state(), ["話題沸騰", "始まりの合図"])

    assert action is not None
    assert action.target_card == "話題沸騰"


def test_high_good_condition_topic_card_refuses_the_card_below_its_gate():
    state = _observed_round1_recovery_state()
    state.good_condition_turns = 7

    assert choose_high_good_condition_topic_card(state, ["話題沸騰"]) is None


def test_observed_post_topic_hand_prefers_low_cost_shikirinaoshi_only_for_exact_state():
    state = _observed_round1_recovery_state()
    state.turn = 6
    state.good_condition_turns = 47
    state.focus = 5
    state.stamina = 33
    action = choose_observed_round1_post_topic_card(
        state, ["鳴り止まない拍手", "夏夜に咲く思い出", "仕切り直し", "始まりの合図"]
    )

    assert action is not None
    assert action.target_card == "仕切り直し"
    state.focus = 4
    assert choose_observed_round1_post_topic_card(state, ["鳴り止まない拍手", "夏夜に咲く思い出", "仕切り直し", "始まりの合図"]) is None


def test_observed_post_shikirinaoshi_hand_prefers_zero_cost_idol_declaration_only_for_exact_state():
    state = _observed_round1_recovery_state()
    state.turn = 6
    state.good_condition_turns = 47
    state.focus = 5
    state.stamina = 33

    action = choose_observed_round1_post_shikirinaoshi_card(
        state, ["アイドル宣言", "演出計画", "存在感", "眠気", "祝福"]
    )

    assert action is not None
    assert action.target_card == "アイドル宣言"
    state.stamina = 32
    assert choose_observed_round1_post_shikirinaoshi_card(
        state, ["アイドル宣言", "演出計画", "存在感", "眠気", "祝福"]
    ) is None
from agent.hif.journal import HIFJournal, load_hif_journal, audit_hif_journal
from agent.hif.presets import parse_hif_preset, choose_first_matching, choose_schedule_priority
from agent.hif.session import get_runtime_hif_session, reset_runtime_hif_session
from agent.hif.simulator import replay_hif_case, build_initial_state
from agent.hif.observed_case import (
    load_observed_hif_case,
    build_route_steps_from_observed_case,
    build_initial_state_from_observed_case,
)


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


def test_load_observed_hif_case_fixture():
    case_path = Path("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")
    case = load_observed_hif_case(case_path)

    assert case.case_id == "rinami_garakuta_road_20260709"
    assert case.profile["idol_name_jp"] == "姫崎 莉波"
    assert len(case.steps) >= 7
    assert case.steps[0].step_id == "finals_day6_class_select_change"
    assert case.steps[-1].metadata["screen_state"] == "memory_preview"
    assert case.observed_random_events[0].event_type == "drink_overflow_resolution"
    assert "interval_shop" in {hint.screen_state for hint in case.recognition_hints}


def test_observed_hif_case_recognition_hints_cover_key_screens():
    case = load_observed_hif_case("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")
    screen_states = {hint.screen_state for hint in case.recognition_hints}

    assert {
        "select_change_target",
        "select_change_source_deck",
        "drink_overflow",
        "interval_shop",
        "skill_deck_view",
        "skill_customize",
        "score_settlement",
        "memory_preview",
    }.issubset(screen_states)


def test_observed_hif_case_random_events_are_model_ready():
    case = load_observed_hif_case("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")
    events = {event.metadata["event_id"]: event for event in case.observed_random_events}

    drink_overflow = events["day3_drink_overflow"]
    assert drink_overflow.event_type == "drink_overflow_resolution"
    assert drink_overflow.metadata["drink_capacity"] == 4
    assert drink_overflow.metadata["new_drink_count"] == 2
    assert drink_overflow.metadata["selected_keep_count"] == 4
    assert drink_overflow.metadata["completion_prompt"] == "あと0個選択"

    select_change = events["day4_select_change"]
    assert select_change.event_type == "select_change"
    assert select_change.metadata["target_card"] == "始まりの合図"
    assert select_change.metadata["source_card"] == "始まりの合図"
    assert select_change.metadata["result"] == "始まりの合図 -> 始まりの合図"


def test_observed_hif_case_builds_route_steps_and_initial_state():
    case = load_observed_hif_case("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")

    initial_state = build_initial_state_from_observed_case(case)
    route_steps = build_route_steps_from_observed_case(case)

    assert initial_state.stamina == 22
    assert initial_state.max_stamina == 35
    assert initial_state.p_points == 330
    assert route_steps[0].step_id == "finals_day6_class_select_change"
    assert route_steps[0].candidates[0].action_id == "day1_select_good_condition"
    assert route_steps[-1].phase == "round2"


def test_replay_observed_hif_case_runs_to_memory_preview():
    scenario = build_default_scenario_config()
    profile = build_default_produce_profile(load_decision_data())

    result = replay_hif_case(
        scenario,
        profile,
        "assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json",
    )

    assert result["observed_case"]["case_id"] == "rinami_garakuta_road_20260709"
    assert result["observed_case"]["step_count"] == 7
    assert "drink_overflow_resolution" in result["observed_case"]["random_event_types"]
    assert "interval_shop" in result["observed_case"]["recognition_screen_states"]
    assert result["steps"][-1]["step_id"] == "memory_preview"
    assert result["final_state"]["memory_quality"] >= 20


def test_replay_observed_hif_case_syncs_observed_state_after():
    scenario = build_default_scenario_config()
    profile = build_default_produce_profile(load_decision_data())

    result = replay_hif_case(
        scenario,
        profile,
        "assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json",
    )

    final_state = result["final_state"]
    assert final_state["stamina"] == 34
    assert final_state["p_points"] == 260
    assert final_state["deck_size"] == 22
    assert final_state["snapshots"]["observed_state_after"]["memory_preview"]["memory_rank"] == "S4+"
    assert final_state["snapshots"]["observed_state_after"]["round2_manual"]["score"] == 4756391


def test_replay_observed_hif_case_forces_observed_selection(tmp_path):
    source = Path("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["steps"][0]["candidates"].append(
        {
            "action_id": "tempting_wrong_choice",
            "name": "高得点だが実測では選んでいない候補",
            "category": "class",
            "tags": ["wrong_observed_choice", "good_condition"],
            "p_point_delta": 999,
            "finals_readiness_delta": 999,
            "deck_quality_delta": 999,
        }
    )
    case_path = tmp_path / "multi_candidate_case.json"
    case_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    scenario = build_default_scenario_config()
    profile = build_default_produce_profile(load_decision_data())
    result = replay_hif_case(scenario, profile, case_path)

    first_decision = result["steps"][0]["decision"]
    assert first_decision["selected_action"]["action_id"] == "day1_select_good_condition"
    assert "observed_replay_forced_choice" in first_decision["rule_hits"]


def test_load_observed_hif_case_rejects_missing_selected_candidate(tmp_path):
    source = Path("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["steps"][0]["selected_action_id"] = "missing_candidate"
    case_path = tmp_path / "invalid_case.json"
    case_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="missing_candidate"):
        load_observed_hif_case(case_path)


def test_hif_safe_preset_uses_observed_priority_and_never_falls_back_to_unknown():
    preset = parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}')

    assert preset.schedule_priority == ("Da", "Vi", "Vo", "gift", "consult", "go_out")
    assert choose_first_matching(["Vo", "Da", "Vi"], preset.schedule_priority) == "Da"
    assert choose_first_matching(["unknown"], preset.schedule_priority) is None


def test_hif_preset_rejects_invalid_json_and_unknown_preset():
    assert parse_hif_preset("not-json").preset_id == "safe_default"
    assert parse_hif_preset('{"preset_id":"unknown"}').preset_id == "safe_default"


def test_hif_observed_select_change_source_prefers_daitan_before_same_name_card():
    preset = parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}')

    assert choose_first_matching(["始まりの合図", "大胆不敵"], preset.select_change_source_names) == "大胆不敵"


def test_rinami_hif_preset_uses_daily_schedule_observed_in_finals_log():
    preset = parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}')

    assert choose_schedule_priority(preset, 6) == ("Vo", "Da", "Vi")
    assert choose_schedule_priority(preset, 5) == ("Da", "Vi", "Vo")
    assert choose_schedule_priority(preset, 4) == ("gift", "go_out")
    assert choose_schedule_priority(preset, 3) == ("Vi", "Da", "Vo")
    assert choose_schedule_priority(preset, 2) == ("Da", "Vi", "Vo")
    assert choose_schedule_priority(preset, 1) == ("consult",)
    assert choose_schedule_priority(preset, None) is None


def test_hif_pipeline_routes_rounds_to_the_dedicated_card_action_not_generic_card_action():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert "ProduceExit" not in payload["ProduceEntryHIF"]["next"]
    assert payload["ProduceHIFRound1Flag"]["next"] == ["ProduceHIFRound1ActionFlag"]
    assert payload["ProduceHIFRound2Flag"]["next"] == ["ProduceHIFRound2ActionFlag"]
    assert payload["ProduceHIFRound1ActionFlag"]["action"]["param"]["custom_action"] == "ProduceCardsHIF"
    assert payload["ProduceHIFRound2ActionFlag"]["action"]["param"]["custom_action"] == "ProduceCardsHIF"
    assert payload["ProduceHIFRound1ActionFlag"]["action"]["param"]["custom_action_param"]["execution_mode"] == "observe_and_stop"
    assert ".*残りターン.*" in payload["ProduceHIFRound1Flag"]["recognition"]["param"]["expected"]
    assert payload["ProduceHIFRound1Flag"]["recognition"]["param"]["roi"] == [8, 0, 170, 48]
    assert payload["ProduceHIFRound1ReachedStop"]["action"]["type"] == "StopTask"
    assert "ProduceCardsFlag" not in payload["ProduceHIFRound1Flag"]["next"]


def test_hif_pipeline_keeps_unknown_overflow_safe_but_routes_supported_interval_and_memory_pages():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert payload["ProduceHIFDrinkOverflowFlag"]["next"] == ["ProduceHIFDrinkOverflowObserveFlag"]
    assert payload["ProduceHIFDrinkOverflowObserveFlag"]["action"]["param"]["custom_action"] == "ProduceHIFDrinkOverflowObserve"
    assert payload["ProduceHIFIntervalFlag"]["next"] == ["ProduceHIFIntervalActionFlag"]
    assert payload["ProduceHIFIntervalActionFlag"]["action"]["param"]["custom_action"] == "ProduceHIFIntervalAuto"
    assert payload["ProduceHIFScoreSettlementFlag"]["next"] == ["ProduceHIFSettlementContinueFlag"]
    assert payload["ProduceHIFMemoryFlag"]["action"]["param"]["custom_action"] == "ProduceHIFMemoryGenerate"


def test_hif_preset_option_injects_the_same_preset_into_round1_and_event_actions():
    task_payload = json.loads(Path("assets/tasks/produce.json").read_text(encoding="utf-8"))
    cases = task_payload["option"]["HIF预设"]["cases"]
    override = cases[1]["pipeline_override"]

    expected_actions = {
        "ProduceChooseHIFEventFlag",
        "ProduceChooseHIFPItemFlag",
        "ProduceHIFClassOptionFlag",
        "ProduceHIFDrinkRewardFlag",
        "ProduceHIFSkillRewardFlag",
        "ProduceHIFSelectChangeTargetFlag",
        "ProduceHIFSelectChangeSourceFlag",
        "ProduceHIFConsultFlag",
        "ProduceHIFRound1ActionFlag",
    }
    assert set(override) == expected_actions
    assert all(value["action"]["param"]["custom_action_param"]["preset_id"] == "rinami_good_condition_safe" for value in override.values())
    assert override["ProduceHIFRound1ActionFlag"]["action"]["param"]["custom_action_param"]["round1_mode"] == "observe_and_stop"


def test_hif_selection_mode_does_not_fall_back_to_generic_button():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert "ProduceHIFButton" not in payload["ProduceHIFSelectionModeFlag"]["next"]
    assert payload["ProduceHIFSelectionModeFlag"]["next"] == ["ProduceHIFSelectionObserveFlag"]
    assert payload["ProduceHIFSelectionObserveFlag"]["action"]["param"]["custom_action"] == "ProduceHIFSelectionObserve"
    button = payload["ProduceHIFSelectionModeContinueButton"]
    assert button["recognition"]["param"]["template"] == ["next.png", "produce/decide.png"]
    assert button["recognition"]["param"]["roi"] == [200, 1000, 320, 160]


def test_hif_pipeline_ocr_patterns_are_valid_regular_expressions():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    for node in payload.values():
        expected = node.get("recognition", {}).get("param", {}).get("expected", [])
        for pattern in expected if isinstance(expected, list) else [expected]:
            if isinstance(pattern, str):
                re.compile(pattern)


def test_hif_final_mode_does_not_match_the_remaining_days_banner():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    patterns = payload["ProduceHIFFinalModeFlag"]["recognition"]["param"]["expected"]

    assert any(re.fullmatch(pattern, "H.I.F 本戦モード") for pattern in patterns)
    assert not any(re.fullmatch(pattern, "H.I.F本戦まで 6日") for pattern in patterns)


def test_hif_task_uses_the_preset_final_mode_action_instead_of_the_generic_difficulty_ocr():
    for task_path in (Path("assets/tasks/produce.json"), Path("assets/tasks/produce_cn.json")):
        task_payload = json.loads(task_path.read_text(encoding="utf-8"))
        hif_case = next(case for case in task_payload["option"]["培育难度"]["cases"] if case["name"] == "HIF")
        mode_override = hif_case["pipeline_override"]["ProduceChooseDifficulty"]

        assert mode_override["recognition"]["type"] == "DirectHit"
        assert mode_override["action"]["param"]["custom_action"] == "ProduceHIFChooseFinalModeAuto"


def test_hif_mode_owns_post_selection_route_and_skip_idol_only_overrides_generic_route():
    for task_path in (Path("assets/tasks/produce.json"), Path("assets/tasks/produce_cn.json")):
        task_payload = json.loads(task_path.read_text(encoding="utf-8"))
        hif_case = next(case for case in task_payload["option"]["培育难度"]["cases"] if case["name"] == "HIF")
        hif_override = hif_case["pipeline_override"]["ProduceChooseDifficulty"]

        assert hif_override["next"] == ["ProduceAfterChooseDifficulty"]
        assert hif_case["pipeline_override"]["ProduceAfterChooseDifficulty"]["next"] == ["ProduceLackAP", "ProduceChooseIdolNext"]
        assert hif_case["pipeline_override"]["ProduceChooseIdolNext"]["next"] == [
            "ProduceHIFStartConfirmFlag",
            "ProduceChooseSupport",
        ]

    task_payload = json.loads(Path("assets/tasks/produce.json").read_text(encoding="utf-8"))
    for case in task_payload["option"]["跳过选择偶像"]["cases"]:
        override = case["pipeline_override"]
        assert "ProduceChooseDifficulty" not in override
        assert "ProduceAfterChooseDifficulty" in override


def test_hif_execution_mode_defaults_to_observe_and_exposes_only_single_step_experiment():
    for task_path in (Path("assets/tasks/produce.json"), Path("assets/tasks/produce_cn.json")):
        task_payload = json.loads(task_path.read_text(encoding="utf-8"))
        option = task_payload["option"]["HIF执行模式"]
        single_step = next(case for case in option["cases"] if case["name"] == "单步执行（实验）")

        assert option["default_case"] == "观测（默认）"
        assert {
            "ProduceChooseDifficulty",
            "ProduceHIFStartConfirmFlag",
            "ProduceChooseHIFEventFlag",
            "ProduceHIFClassOptionFlag",
            "ProduceHIFSelectChangeTargetFlag",
            "ProduceHIFGiftBagsFlag",
            "ProduceHIFGiftRewardResultFlag",
            "ProduceHIFSafeAdvanceFlag",
            "ProduceHIFDrinkRewardFlag",
            "ProduceHIFDrinkRewardRevealFlag",
            "ProduceHIFRewardConfirmFlag",
        }.issubset(single_step["pipeline_override"])
        for node_name in (
            "ProduceChooseDifficulty",
            "ProduceHIFStartConfirmFlag",
            "ProduceChooseHIFEventFlag",
            "ProduceHIFClassOptionFlag",
            "ProduceHIFSelectChangeTargetFlag",
            "ProduceHIFGiftBagsFlag",
            "ProduceHIFGiftRewardResultFlag",
            "ProduceHIFSafeAdvanceFlag",
            "ProduceHIFDrinkRewardFlag",
            "ProduceHIFDrinkRewardRevealFlag",
            "ProduceHIFRewardConfirmFlag",
        ):
            action_param = single_step["pipeline_override"][node_name]["action"]["param"]
            assert action_param["custom_action_param"]["execution_mode"] == "single_step"
        assert "ProduceHIFSkillRewardFlag" not in single_step["pipeline_override"]
        assert "ProduceHIFRound1ActionFlag" not in single_step["pipeline_override"]
        assert "ProduceHIFRound2ActionFlag" not in single_step["pipeline_override"]


def test_hif_pipeline_custom_actions_are_exported_by_the_agent_package():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        action_package = import_module("agent.custom.action")
    finally:
        sys.path.remove(agent_path)

    referenced = {
        node["action"]["param"]["custom_action"]
        for node in payload.values()
        if node.get("action", {}).get("type") == "Custom"
    }
    assert referenced <= set(action_package.__all__)


def test_hif_test_pipeline_hands_card_change_back_to_the_formal_router_without_placeholders():
    payload = json.loads(Path("assets/resource/base/pipeline/test/TEST_HIF.json").read_text(encoding="utf-8"))
    custom_actions = [
        node.get("action", {}).get("param", {}).get("custom_action", "")
        for node in payload.values()
    ]

    assert payload["produce_hif_cardchange_enter_flag"]["next"] == ["ProduceEntryHIF"]
    assert not any("Placeholder" in action for action in custom_actions)


def test_hif_preparation_pipeline_uses_existing_templates_before_entering_hif_router():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert payload["ProduceHIFPreparationEntry"]["next"] == ["ProduceHIFMainEventButton", "ProduceHIFUnknownStop"]
    assert payload["ProduceHIFMainEventButton"]["recognition"]["param"]["template"] == ["produce/HIF/button_hif_mainevent.png"]
    assert payload["ProduceHIFProduceStartButton"]["recognition"]["param"]["template"] == ["produce/HIF/button_hif_producestart.png"]
    assert payload["ProduceHIFMainEventEntranceFlag"]["next"] == ["ProduceEntryHIF"]


def test_hif_router_runs_device_preflight_before_page_routing():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert payload["ProduceEntryHIF"]["action"]["param"]["custom_action"] == "ProduceHIFValidateDevice"


def test_hif_lesson_accent_classifier_requires_a_unique_calibrated_color():
    import numpy as np

    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        action = import_module("agent.custom.action.produce_hif").ProduceChooseHIFEventAuto()
    finally:
        sys.path.remove(agent_path)

    image = np.zeros((1280, 720, 3), dtype=np.uint8)
    image[1008:1063, 205:260] = (146, 65, 244)  # BGR: Vo 粉色角标
    image[1008:1063, 369:424] = (237, 147, 23)  # BGR: Da 蓝色角标
    image[1008:1063, 534:589] = (41, 184, 253)  # BGR: Vi 黄色角标
    schedule_roi = [84, 920, 552, 196]

    assert action._lesson_category_from_accent(image, (168, 1062, 56, 32), schedule_roi) == "Vo"
    assert action._lesson_category_from_accent(image, (332, 1062, 55, 32), schedule_roi) == "Da"
    assert action._lesson_category_from_accent(image, (494, 1062, 54, 32), schedule_roi) == "Vi"
    assert action._lesson_category_from_accent(np.zeros_like(image), (168, 1062, 56, 32), schedule_roi) is None


def test_hif_public_lesson_ocr_preserves_vo_da_vi_categories_for_daily_priority():
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        action = import_module("agent.custom.action.produce_hif").ProduceChooseHIFEventAuto()
    finally:
        sys.path.remove(agent_path)

    reco_detail = SimpleNamespace(
        filtered_results=(
            SimpleNamespace(text="Vo.公開レッスン", box=[86, 1077, 167, 30], score=0.994),
            SimpleNamespace(text="Da.公開レッスン", box=[273, 1079, 165, 27], score=0.999),
            SimpleNamespace(text="Vi.公開レッスン", box=[457, 1072, 172, 38], score=0.981),
        ),
        all_results=(),
    )

    events = action._events_from_schedule_ocr(reco_detail, object(), [84, 920, 552, 196])

    assert [(event["name"], event["category"], event["source"]) for event in events] == [
        ("Vo", "Vo", "ocr_public_lesson"),
        ("Da", "Da", "ocr_public_lesson"),
        ("Vi", "Vi", "ocr_public_lesson"),
    ]


def test_hif_safe_advance_rejects_known_interactive_page_before_click(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    from agent.hif.journal import HIFFrameEvidence

    records = []
    journal = SimpleNamespace(
        capture=lambda image, label: HIFFrameEvidence(label, 720, 1280, "frame", None, "test"),
        record=lambda *args, **kwargs: records.append((args, kwargs)),
    )
    action = module.ProduceHIFSafeAdvanceAuto()
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: journal)
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: SimpleNamespace(safe_advance_count=0))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"frame")
    monkeypatch.setattr(action, "_detect_screen_profile", lambda context, image: "class_options")
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: pytest.fail("已知交互页不得空白点击"))
    stop_reasons = []
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(object(), SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert stop_reasons == [("unknown_hif_transition", "safe_advance_blocked_by_known_page:class_options")]
    assert records[-1][0][1:3] == ("safe_advance", "rejected")


def test_hif_class_option_accepts_all_three_attribute_variants_for_the_same_verified_change_effect():
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        action = import_module("agent.custom.action.produce_hif").ProduceChooseHIFClassOptionAuto()
    finally:
        sys.path.remove(agent_path)

    shared = ("180", "トラブルカード以外", "好調関係", "セレクトチェンジ")
    for attribute in ("ボーカル上昇", "ダンス上昇", "ビジュアル上昇"):
        assert action._is_good_condition_change_preview((attribute, *shared))
    assert not action._is_good_condition_change_preview(("ビジュアル上昇", "180", "トラブルカード以外", "好調関係"))


def test_hif_class_option_resumes_a_verified_preview_with_one_confirm_click(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFClassOptionAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    screenshots = iter((b"preview", b"target"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(
        action,
        "_matches_screen_profile",
        lambda context, image, screen: (screen == "class_options" and image == b"preview")
        or (screen == "select_change_target" and image == b"target"),
    )
    monkeypatch.setattr(action, "_find_class_option_candidate", lambda context, image: ({"name": "top", "box": [52, 650, 616, 90]}, ("top",)))
    monkeypatch.setattr(
        action,
        "_read_class_preview_texts",
        lambda context, image: ("ビジュアル上昇", "180", "トラブルカード以外", "好調関係", "セレクトチェンジ"),
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)

    assert action.run(SimpleNamespace(run_task=lambda task: None), SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","execution_mode":"single_step"}'))
    assert clicks == [([52, 650, 616, 90], False)]
    assert any(record[0][1:3] == ("resume_class_option_preview", "verified") for record in records)
    assert records[-1][0][1:3] == ("confirm_class_option", "verified")


def test_hif_class_option_uses_complete_preview_before_second_confirmation(monkeypatch, tmp_path):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFClassOptionAuto()
    action.ACTION_DELAY = 0
    journal = HIFJournal(root=tmp_path, session_id="class-preview")
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: journal)
    monkeypatch.setattr(
        action,
        "_find_class_option_candidate",
        lambda context, image: ({"name": "飲食物のチェック", "box": [119, 679, 255, 36], "source": "top_option_preview"}, ("飲食物のチェック", "基礎の確認", "声の細かいチェック")),
    )
    monkeypatch.setattr(
        action,
        "_read_class_preview_texts",
        lambda context, image: ()
        if image == b"before"
        else (
            "ボーカル上昇+180",
            "トラブルカード以外のスキルカードを選択して",
            "異なる好調関係のスキルカードにセレクトチェンジ",
        ),
    )
    monkeypatch.setattr(
        action,
        "_matches_screen_profile",
        lambda context, image, screen: (screen == "class_options" and image in {b"before", b"preview"})
        or (screen == "select_change_target" and image == b"target"),
    )
    screenshots = iter((b"before", b"preview", b"target"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","execution_mode":"single_step"}'))
    assert clicks == [([119, 679, 255, 36], False), ([119, 679, 255, 36], False)]
    assert tasks == []
    audit = audit_hif_journal(load_hif_journal(journal.path))
    assert audit.ok
    assert audit.verified_execution_count == 2


def test_hif_class_option_stops_after_preview_when_effect_tokens_are_incomplete(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFClassOptionAuto()
    action.ACTION_DELAY = 0
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: SimpleNamespace(capture=lambda image, label: SimpleNamespace(fingerprint=image), record=lambda *args, **kwargs: None))
    monkeypatch.setattr(
        action,
        "_find_class_option_candidate",
        lambda context, image: ({"name": "飲食物のチェック", "box": [119, 679, 255, 36], "source": "top_option_preview"}, ("飲食物のチェック",)),
    )
    monkeypatch.setattr(action, "_read_class_preview_texts", lambda context, image: ("ボーカル上昇+180",))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "class_options")
    screenshots = iter((b"before", b"preview"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    stop_reasons = []
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(object(), SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","execution_mode":"single_step"}'))
    assert clicks == [([119, 679, 255, 36], False)]
    assert stop_reasons == [("hif_class_options", "good_condition_preview_not_confirmed")]


def test_hif_select_change_target_enumerates_slots_then_advances_only_after_exact_target(monkeypatch, tmp_path):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeTargetAuto()
    reset_runtime_hif_session()
    action.ACTION_DELAY = 0
    journal = HIFJournal(root=tmp_path, session_id="target-enumeration")
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: journal)
    images = iter((b"initial", b"left", b"center", b"right", b"target-selected", b"source"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(images))
    monkeypatch.setattr(
        action,
        "_matches_screen_profile",
        lambda context, image, screen: (screen == "select_change_target" and image != b"source")
        or (screen == "select_change_source_deck" and image == b"source"),
    )
    details = {
        b"left": {"name": "静かな意志", "target_name": None, "ocr_texts": ("静かな意志",), "confidence": 0.99},
        b"center": {"name": "始まりの合図", "target_name": "始まりの合図", "ocr_texts": ("始まりの合図",), "confidence": 0.99},
        b"right": {"name": "大声援", "target_name": None, "ocr_texts": ("大声援",), "confidence": 0.99},
        b"target-selected": {"name": "始まりの合図", "target_name": "始まりの合図", "ocr_texts": ("始まりの合図",), "confidence": 0.99},
    }
    monkeypatch.setattr(action, "_read_target_details", lambda context, image, target_names: dict(details[image]))
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda context, image, phrases, roi: SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[230, 1052, 260, 84]))
        if phrases == ("次へ",)
        else None,
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","execution_mode":"single_step"}'))
    assert [box for box, _ in clicks] == [
        [158, 837, 127, 128],
        [297, 837, 127, 128],
        [436, 837, 127, 128],
        [297, 837, 127, 128],
        [230, 1052, 260, 84],
    ]
    assert tasks == []
    assert get_runtime_hif_session().pending_select_change is not None
    assert get_runtime_hif_session().pending_select_change.target_name == "始まりの合図"
    audit = audit_hif_journal(load_hif_journal(journal.path))
    assert audit.ok
    assert audit.verified_execution_count == 5


def test_hif_select_change_target_probe_enumerates_once_without_reroll_or_advance(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeTargetAuto()
    action.ACTION_DELAY = 0
    images = iter((b"initial", b"left", b"center", b"right"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(images))
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen: image)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "select_change_target")
    details = iter(
        (
            {"name": "軽い足取り", "target_name": "軽い足取り", "ocr_texts": ("軽い足取り",), "confidence": 0.99},
            {"name": "祝福", "target_name": "祝福", "ocr_texts": ("祝福",), "confidence": 0.99},
            {"name": "スタンドプレー", "target_name": "スタンドプレー", "ocr_texts": ("スタンドプレー",), "confidence": 0.99},
        )
    )
    monkeypatch.setattr(action, "_read_target_details", lambda context, image, target_names: dict(next(details)))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append(list(box)) or True)
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    stop_reasons = []
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen, reason: stop_reasons.append((screen, reason)) or True,
    )

    assert action.run(
        object(),
        SimpleNamespace(
            custom_action_param=(
                '{"preset_id":"rinami_good_condition_safe","execution_mode":"single_step",'
                '"select_change_target_probe":"enumerate_candidates"}'
            )
        ),
    )
    assert clicks == [[158, 837, 127, 128], [297, 837, 127, 128], [436, 837, 127, 128]]
    assert stop_reasons == [("select_change_target", "target_candidate_probe_complete_stop")]
    summary = next(record for record in records if record[0][1:3] == ("enumerate_target_candidates", "observed"))
    assert [candidate["name"] for candidate in summary[1]["details"]["candidates"]] == ["軽い足取り", "祝福", "スタンドプレー"]


def test_hif_select_change_reroll_requires_counter_to_decrement(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeTargetAuto()
    action.ACTION_DELAY = 0
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: SimpleNamespace(capture=lambda image, label: SimpleNamespace(fingerprint=image), record=lambda *args, **kwargs: None))
    counts = iter((3, 2))
    monkeypatch.setattr(action, "_read_reroll_count", lambda context, image: next(counts))
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda context, image, phrases, roi: SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[555, 1072, 112, 58])),
    )
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"after-reroll")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "select_change_target")
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)

    assert action._reroll_targets(object(), b"before-reroll", 1) == b"after-reroll"
    assert clicks == [([555, 1072, 112, 58], False)]


def test_hif_select_change_final_reroll_accepts_hidden_zero_only_when_reroll_button_is_gone(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeTargetAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(capture=lambda image, label: SimpleNamespace(fingerprint=image), record=lambda *args, **kwargs: records.append((args, kwargs))),
    )
    counts = iter((1, None))
    monkeypatch.setattr(action, "_read_reroll_count", lambda context, image: next(counts))
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda context, image, phrases, roi: SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[555, 1072, 112, 58]))
        if image == b"before-reroll"
        else None,
    )
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"after-reroll")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "select_change_target")
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: True)

    assert action._reroll_targets(object(), b"before-reroll", 2) == b"after-reroll"
    verified = [entry for entry in records if entry[0][1:3] == ("reroll_target", "verified")]
    assert verified
    assert verified[0][1]["details"]["after_count"] == 0
    assert verified[0][1]["details"]["exhausted_by_hidden_controls"] is True


def test_hif_select_change_stops_with_explicit_exhaustion_when_resumed_without_reroll_controls(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeTargetAuto()
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(capture=lambda image, label: SimpleNamespace(fingerprint=image), record=lambda *args, **kwargs: records.append((args, kwargs))),
    )
    monkeypatch.setattr(action, "_read_reroll_count", lambda context, image: None)
    monkeypatch.setattr(action, "_find_text_option", lambda *args, **kwargs: None)
    stop_reasons = []
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen, reason: stop_reasons.append((screen, reason)) or True)

    assert action._reroll_targets(object(), b"exhausted", 1) is True
    assert stop_reasons == [("select_change_target", "reroll_unavailable_after_target_enumeration")]
    rejected = [entry for entry in records if entry[0][1:3] == ("reroll_target", "rejected")]
    assert rejected[0][1]["details"]["reason"] == "reroll_controls_hidden_after_exhaustion"


def test_hif_consult_stops_safely_when_the_recognized_finish_button_cannot_be_clicked(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        action = import_module("agent.custom.action.produce_hif").ProduceHIFConsultAuto()
    finally:
        sys.path.remove(agent_path)
    stop_reasons = []
    button = SimpleNamespace(best_result=SimpleNamespace(box=[]))

    monkeypatch.setattr(action, "_get_screenshot", lambda context: object())
    monkeypatch.setattr(action, "_find_text_option", lambda *args: button)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: False)
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True)

    assert action.run(object(), SimpleNamespace(custom_action_param='{"preset_id":"safe_default","execution_mode":"single_step"}'))
    assert stop_reasons == [("consult_shop", "finish_button_click_failed")]


def test_hif_page_action_defaults_to_observe_and_never_clicks(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        action = import_module("agent.custom.action.produce_hif").ProduceHIFConsultAuto()
    finally:
        sys.path.remove(agent_path)
    stop_reasons = []
    button = SimpleNamespace(best_result=SimpleNamespace(box=[560, 1045, 155, 84]))

    monkeypatch.setattr(action, "_get_screenshot", lambda context: object())
    monkeypatch.setattr(action, "_find_text_option", lambda *args: button)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: pytest.fail("默认观察模式不应点击"))
    monkeypatch.setattr(action, "_stop_unsupported", lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True)

    assert action.run(object(), SimpleNamespace(custom_action_param='{"preset_id":"safe_default"}'))
    assert stop_reasons == [("consult_shop", "page_execution_mode_not_single_step")]


def test_hif_cards_observe_mode_never_clicks_and_single_step_rejects_incomplete_state(monkeypatch):
    """Round 出牌入口必须先影子记录；未校准数值时单步模式也不能点击。"""
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    from agent.hif.journal import HIFFrameEvidence
    from agent.hif.decisions.state import ActionKind, CardAction

    records = []

    class _Journal:
        def capture(self, image, label):
            del image
            return HIFFrameEvidence(label, 720, 1280, None, None, "test")

        def record(self, *args, **kwargs):
            records.append((args, kwargs))

    observation = SimpleNamespace(
        state=SimpleNamespace(oneesan_used=False, natural_finisher_used=False),
        detections=[],
        missing_fields=("hand", "turn", "flow"),
        screen_confidence=0.0,
    )
    reader = SimpleNamespace(read_exam_observation=lambda *args: observation)
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: _Journal())
    monkeypatch.setattr(module.ExamStateReader, "from_context", classmethod(lambda cls, context: reader))
    monkeypatch.setattr(
        module,
        "GarakutaRinamiStrategy",
        lambda payload: SimpleNamespace(decide=lambda state: CardAction(ActionKind.PLAY_CARD, "自然体の魅力", "test")),
    )

    action = module.ProduceCardsHIF()
    monkeypatch.setattr(action, "_get_screenshot", lambda context: SimpleNamespace(size=(720, 1280)))
    monkeypatch.setattr(action, "_get_health", lambda context, image: None)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","round":"round1","execution_mode":"observe_and_stop"}'),
    )
    assert tasks == ["ProduceHIFRound1ReachedStop"]
    assert records[-1][0][2] == "observed"

    tasks.clear()
    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","round":"round1","execution_mode":"single_step"}'),
    )
    assert tasks == ["ProduceHIFUnknownStop"]
    assert any(args[2] == "rejected" for args, _ in records)


def test_hif_verified_deck_swipe_records_changed_frames(monkeypatch, tmp_path):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    from agent.hif.journal import HIFJournal, load_hif_journal, audit_hif_journal

    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    action._configure_page_execution(SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    action.ACTION_DELAY = 0
    journal = HIFJournal(root=tmp_path, session_id="swipe")
    monkeypatch.setattr(module, "get_runtime_hif_journal", lambda: journal)
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"after")
    controller = SimpleNamespace(post_swipe=lambda *args, **kwargs: SimpleNamespace(wait=lambda: None))
    context = SimpleNamespace(tasker=SimpleNamespace(controller=controller), run_task=lambda task: None)

    assert action._swipe_with_verification(
        context,
        b"before",
        "select_change_source_deck",
        "scroll_deck",
        (360, 1040),
        (360, 680),
        duration=300,
    )
    assert audit_hif_journal(load_hif_journal(journal.path)).ok


def test_hif_select_change_source_deck_always_stops_after_recording_and_never_clicks(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"source-deck")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen_id: image)
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: pytest.fail("源卡页不应点击"))
    monkeypatch.setattr(action, "_swipe_with_verification", lambda *args, **kwargs: pytest.fail("源卡页不应滚动"))
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert tasks == ["ProduceHIFUnknownStop"]
    assert records[0][0][1:3] == ("observe_source_deck", "observed")
    assert records[-1][0][1:3] == ("safe_stop", "stopped")
    assert records[-1][1]["details"] == {"reason": "source_card_selection_not_authorized"}


def test_hif_source_deck_probe_clicks_only_first_visible_slot_then_stops(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    screenshots = iter((b"before", b"after"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen_id: image)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: True)
    monkeypatch.setattr(
        action,
        "_source_detail_snapshot",
        lambda context, image: {
            "name_texts": ("大胆不敵",),
            "matched_name": "大胆不敵",
            "effect_texts": ("パラメータ+",),
            "confidence": 0.99,
            "name_confidence": 0.99,
            "effect_confidence": 0.99,
        },
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step","source_deck_probe":true}'))
    assert clicks == [([80, 638, 120, 120], False)]
    assert tasks == ["ProduceHIFUnknownStop"]
    assert records[-2][0][1:3] == ("probe_source_card", "observed")
    assert records[-2][1]["details"]["name_texts"] == ("大胆不敵",)
    assert records[-1][1]["details"] == {"reason": "source_deck_probe_complete_stop"}


def test_hif_source_deck_visible_enumeration_only_clicks_calibrated_visible_slots(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    screenshots = iter((b"before", *(f"after-{index}".encode() for index in range(12))))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen_id: image)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: True)
    monkeypatch.setattr(
        action,
        "_source_detail_snapshot",
        lambda context, image: {
            "name_texts": (f"card-{image!r}",),
            "matched_name": f"card-{image!r}",
            "effect_texts": ("effect",),
            "confidence": 0.99,
            "name_confidence": 0.99,
            "effect_confidence": 0.99,
        },
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step","source_deck_probe":"visible_grid"}'))
    assert [box for box, _ in clicks] == list(action.VISIBLE_SLOT_FALLBACKS)
    assert tasks == ["ProduceHIFUnknownStop"]
    assert len([record for record in records if record[0][1:3] == ("probe_source_card", "observed")]) == 12
    assert records[-1][1]["details"] == {"reason": "source_deck_visible_enumeration_complete_stop"}


def test_hif_source_deck_visible_enumeration_records_an_unreadable_slot_and_continues(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"after")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: True)
    monkeypatch.setattr(
        action,
        "_source_detail_snapshot",
        lambda context, image: {
            "name_texts": ("partial",),
            "matched_name": None,
            "effect_texts": ("effect",),
            "confidence": 0.2,
            "name_confidence": 0.0,
            "effect_confidence": 0.9,
        },
    )
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: True)

    assert action._probe_source_slot(object(), b"before", "visible_slot_r1c1", [80, 638, 120, 120], allow_unreadable_details=True) == b"after"
    observed = next(record for record in records if record[0][1:3] == ("probe_source_card", "observed"))
    assert observed[1]["details"]["name_readable"] is False
    assert observed[1]["details"]["reason"] == "source_deck_probe_detail_unreadable"


def test_hif_source_deck_scroll_enumeration_performs_exactly_one_verified_swipe_before_visible_slots(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    screenshots = iter((b"before", b"after-scroll", *(f"after-{index}".encode() for index in range(12))))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen_id: image)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: True)
    monkeypatch.setattr(
        action,
        "_source_detail_snapshot",
        lambda context, image: {
            "name_texts": (f"card-{image!r}",),
            "matched_name": f"card-{image!r}",
            "effect_texts": ("effect",),
            "confidence": 0.99,
            "name_confidence": 0.99,
            "effect_confidence": 0.99,
        },
    )
    swipes = []
    monkeypatch.setattr(
        action,
        "_swipe_with_verification",
        lambda context, image, screen, event, start, end, **kwargs: swipes.append((screen, event, start, end, kwargs)) or True,
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step","source_deck_probe":"visible_grid_after_one_scroll"}'))
    assert swipes == [
        ("select_change_source_deck", "scroll_source_deck_once", (360, 1040), (360, 680), {"duration": 300, "details": {"direction": "up", "max_scrolls": 1}})
    ]
    assert [box for box, _ in clicks] == list(action.VISIBLE_SLOT_FALLBACKS)
    assert tasks == ["ProduceHIFUnknownStop"]
    assert records[-1][1]["details"] == {"reason": "source_deck_visible_enumeration_after_scroll_complete_stop"}


def test_hif_source_deck_confirmation_requires_exact_source_then_completion_text(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    reset_runtime_hif_session()
    get_runtime_hif_session().set_pending_select_change("スポットライト")
    action.ACTION_DELAY = 0
    action.CLICK_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    screenshots = iter((b"before", b"selected", b"completed"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen_id: image)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: screen_id == "select_change_source_deck")
    monkeypatch.setattr(
        action,
        "_source_detail_snapshot",
        lambda context, image: {
            "name_texts": ("大胆不敵",),
            "matched_name": "大胆不敵",
            "effect_texts": ("好調3ターン",),
            "confidence": 0.99,
            "name_confidence": 0.99,
            "effect_confidence": 0.99,
        },
    )
    monkeypatch.setattr(action, "_read_change_completion_texts", lambda context, image: ("大胆不敵をスポットライトにチェンジしました",))
    change_button = SimpleNamespace(hit=True, best_result=SimpleNamespace(box=[373, 1119, 255, 82]))
    monkeypatch.setattr(action, "_find_text_option", lambda *args: change_button)
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"preset_id":"rinami_good_condition_safe","execution_mode":"single_step","source_deck_probe":"confirm_source_card","source_card_name":"大胆不敵"}'),
    )
    assert clicks == [([374, 786, 120, 120], False), ([373, 1119, 255, 82], False)]
    assert tasks == ["ProduceHIFUnknownStop"]
    assert records[-2][0][1:3] == ("confirm_select_change", "verified")
    assert records[-2][1]["details"]["completion_texts"] == ("大胆不敵をスポットライトにチェンジしました",)
    assert records[-1][1]["details"] == {"reason": "select_change_result_observed_stop"}
    assert get_runtime_hif_session().pending_select_change is None


def test_hif_change_completion_accepts_observed_mi_to_cjk_three_ocr_confusion():
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        action = import_module("agent.custom.action.produce_hif").ProduceChooseHIFSelectChangeSourceAuto()
    finally:
        sys.path.remove(agent_path)

    assert action._is_change_completion(
        ("タイ三ングの基本を始まりの合図にチェ", "ンジしました"),
        "タイミングの基本",
        "始まりの合図",
    )


def test_hif_source_deck_confirmation_rejects_hardcoded_target_without_selected_target_state(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    reset_runtime_hif_session()
    action = module.ProduceChooseHIFSelectChangeSourceAuto()
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"source-deck")
    monkeypatch.setattr(action, "_wait_for_screen_profile", lambda context, image, screen_id: image)
    stop_reasons = []
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )

    assert action.run(
        object(),
        SimpleNamespace(
            custom_action_param=(
                '{"preset_id":"rinami_good_condition_safe","execution_mode":"single_step",'
                '"source_deck_probe":"confirm_source_card","source_card_name":"大胆不敵",'
                '"target_card_name":"スポットライト"}'
            )
        ),
    )
    assert stop_reasons == [("select_change_source_deck", "selected_target_card_missing_or_invalid")]


def test_hif_public_lesson_result_uses_the_restricted_safe_point_after_page_confirmation(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceHIFPublicLessonResultAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    screenshots = iter((b"before", b"after"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image == b"before")
    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: "finals_prepare")
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [([341, 204, 0, 3], False)]
    assert tasks == []
    assert records[-1][0][1:3] == ("advance_public_lesson_result", "verified")


def test_hif_public_lesson_result_allows_multiple_verified_result_panels_before_exit(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceHIFPublicLessonResultAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    screenshots = iter((b"before", b"middle", b"after"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen_id: image in {b"before", b"middle"})
    monkeypatch.setattr(action, "_detect_confirmed_hif_transition", lambda context, image: "finals_prepare")
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [([341, 204, 0, 3], False), ([341, 204, 0, 3], False)]
    assert tasks == []
    assert any(record[0][1:3] == ("advance_public_lesson_result", "observed") for record in records)
    assert records[-1][1]["details"]["attempts"] == 2


def test_hif_drink_reward_accepts_an_already_selected_known_slot_without_reclicking_resource_button(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFDrinkRewardAuto()
    action.ACTION_DELAY = 0
    action._configure_page_execution(SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=image),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"selected")
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: True)
    monkeypatch.setattr(action, "_matches_profile_anchors", lambda context, image, screen_id: False)
    monkeypatch.setattr(
        action,
        "_read_drink_details",
        lambda context, image: {"name": "初星黒酢", "effect": "test", "confidence": 0.99, "ocr_text": "初星黒酢"},
    )
    monkeypatch.setattr(action, "_has_receive_button", lambda context, image: True)
    context = SimpleNamespace(run_task=lambda task: None)

    selected = action._select_and_read_slot(context, b"selected", "candidate_left", [158, 822, 127, 127], "enumerate_drink_candidate")

    assert selected == (
        {"name": "初星黒酢", "effect": "test", "confidence": 0.99, "ocr_text": "初星黒酢", "slot": "candidate_left"},
        b"selected",
    )
    assert records[-1][1]["details"]["selection_already_active"] is True


def test_hif_drink_reward_reveal_stops_when_animation_ends_on_an_unknown_page(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceHIFDrinkRewardRevealAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    monkeypatch.setattr(
        module,
        "detect_drink_reward_reveal_page",
        lambda context, image: SimpleNamespace(name="パワフル漢方ドリンク") if image == b"reveal" else None,
    )
    screenshots = iter((b"reveal", b"bags"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append((list(box), double)) or True)
    monkeypatch.setattr(action, "_detect_screen_profile", lambda context, image: None)
    stop_reasons = []
    monkeypatch.setattr(
        action,
        "_stop_unsupported",
        lambda context, screen_state, reason: stop_reasons.append((screen_state, reason)) or True,
    )
    context = SimpleNamespace()

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == []
    assert stop_reasons == [("hif_drink_reward_reveal", "reveal_next_page_not_confirmed")]
    assert records[-1][0][1:3] == ("wait_revealed_drink_reward", "unverified")


def test_hif_reward_confirm_keeps_pending_reward_until_the_reveal_confirmation_reaches_skill_reward(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceHIFRewardConfirmAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    pending = SimpleNamespace(kind="drink", name="パワフル漢方ドリンク", slot="candidate_left")
    cleared = []
    session = SimpleNamespace(pending_reward=pending, clear_pending_reward=lambda: cleared.append(True))
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: session)
    screenshots = iter((b"selected", b"reveal"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(
        module,
        "detect_drink_reward_page",
        lambda context, image: SimpleNamespace(state="selected_detail", name="パワフル漢方ドリンク") if image == b"selected" else None,
    )
    monkeypatch.setattr(
        module,
        "detect_drink_reward_reveal_page",
        lambda context, image: SimpleNamespace(name="パワフル漢方ドリンク") if image == b"reveal" else None,
    )
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda context, image, phrases, roi: SimpleNamespace(best_result=SimpleNamespace(box=[230, 1052, 260, 84])),
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False: clicks.append((list(box), double)) or True)
    monkeypatch.setattr(module, "frame_changed", lambda before, after: before.fingerprint != after.fingerprint)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: False)
    context = SimpleNamespace(run_task=lambda task: pytest.fail(f"不应安全停止: {task}"))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == [([230, 1052, 260, 84], False)]
    assert cleared == []
    assert records[-1][0][1:3] == ("confirm_reward", "verified")
    assert records[-1][1]["details"] == {
        "reward": "パワフル漢方ドリンク",
        "slot": "candidate_left",
        "click_count": 1,
        "next_screen": "drink_reward_reveal",
    }


def test_hif_skill_reward_observation_clears_the_verified_pending_drink_without_touching_cards(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSkillRewardAuto()
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    cleared = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_session",
        lambda: SimpleNamespace(
            pending_reward=SimpleNamespace(kind="drink", name="パワフル漢方ドリンク"),
            clear_pending_reward=lambda: cleared.append(True),
        ),
    )
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"skill")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: image == b"skill" and screen == "skill_reward")
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param=""))
    assert cleared == [True]
    assert tasks == ["ProduceHIFUnknownStop"]
    assert records[-2][1]["details"]["received_drink"] == "パワフル漢方ドリンク"


def test_hif_skill_reward_probe_only_selects_each_candidate_then_stops(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSkillRewardAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    monkeypatch.setattr(
        module,
        "get_runtime_hif_session",
        lambda: SimpleNamespace(pending_reward=None, clear_pending_reward=lambda: pytest.fail("不应清除不存在的奖励")),
    )
    screenshots = iter((b"before", b"after-left", b"after-center", b"after-right"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "skill_reward")
    monkeypatch.setattr(
        action,
        "_read_skill_reward_detail",
        lambda context, image: {
            "name": f"card-{image.decode()}",
            "name_texts": (f"card-{image.decode()}",),
            "effect_text": "verified detail",
            "confidence": 0.99,
            "name_confidence": 0.99,
            "detail_confidence": 0.99,
        },
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step","skill_reward_probe":"enumerate_candidates"}'))
    assert clicks == [([158, 821, 127, 128], False), ([297, 821, 127, 128], False), ([436, 821, 127, 128], False)]
    assert tasks == ["ProduceHIFUnknownStop"]
    enumeration = next(record for record in records if record[0][1:3] == ("enumerate_skill_reward_candidates", "observed"))
    assert [candidate["slot"] for candidate in enumeration[1]["details"]["candidates"]] == [
        "candidate_left",
        "candidate_center",
        "candidate_right",
    ]
    assert records[-1][1]["details"] == {"reason": "skill_reward_probe_complete_stop"}


def test_hif_skill_reward_probe_reads_the_known_selected_slot_without_reclicking_it(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSkillRewardAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: SimpleNamespace(pending_reward=None))
    monkeypatch.setattr(module, "detect_skill_reward_selected_page", lambda context, image: SimpleNamespace(name="意地"))
    screenshots = iter((b"selected-left", b"after-center", b"after-right"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "skill_reward")
    monkeypatch.setattr(
        action,
        "_read_skill_reward_detail",
        lambda context, image: {
            "name": f"card-{image.decode()}",
            "name_texts": (f"card-{image.decode()}",),
            "effect_text": "verified detail",
            "confidence": 0.99,
            "name_confidence": 0.99,
            "detail_confidence": 0.99,
        },
    )
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    context = SimpleNamespace(run_task=lambda task: None)

    assert action.run(
        context,
        SimpleNamespace(
            custom_action_param='{"execution_mode":"single_step","skill_reward_probe":"enumerate_candidates","skill_reward_initial_slot":"candidate_left"}'
        ),
    )
    assert clicks == [([297, 821, 127, 128], False), ([436, 821, 127, 128], False)]
    first_candidate = next(record for record in records if record[0][1:3] == ("probe_skill_reward_candidate", "observed"))
    assert first_candidate[1]["details"]["slot"] == "candidate_left"
    assert first_candidate[1]["details"]["selection_already_active"] is True


def test_hif_skill_reward_decision_records_a_unique_target_without_receiving(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSkillRewardAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: SimpleNamespace(pending_reward=None))
    monkeypatch.setattr(module, "detect_skill_reward_selected_page", lambda context, image: SimpleNamespace(name="祝福"))
    screenshots = iter((b"selected-right", b"after-left", b"after-center"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "skill_reward")
    details = iter((
        {"name": "祝福", "name_texts": ("祝福",), "effect_text": "体力消費4 パラメータ+26 好調1ターン レッスン中1回", "confidence": 0.99, "name_confidence": 0.99, "detail_confidence": 0.99},
        {"name": "意地", "name_texts": ("意地",), "effect_text": "元気+3 集中+4 レッスン中1回", "confidence": 0.99, "name_confidence": 0.99, "detail_confidence": 0.99},
        {"name": "トークタイム", "name_texts": ("トークタイム",), "effect_text": "好調状態の場合、使用可 パラメータ+27 レッスン中1回", "confidence": 0.99, "name_confidence": 0.99, "detail_confidence": 0.99},
    ))
    monkeypatch.setattr(action, "_read_skill_reward_detail", lambda context, image: next(details))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(
        context,
        SimpleNamespace(
            custom_action_param='{"execution_mode":"single_step","skill_reward_probe":"decide_candidates","skill_reward_initial_slot":"candidate_right"}'
        ),
    )
    assert clicks == [([158, 821, 127, 128], False), ([297, 821, 127, 128], False)]
    assert tasks == ["ProduceHIFUnknownStop"]
    decision = next(record for record in records if record[0][1:3] == ("decide_skill_reward", "selected"))
    assert decision[1]["details"]["target"] == "祝福"
    assert decision[1]["details"]["next_action"] == "no_click_pending_receipt_implementation"


def test_hif_skill_reward_receive_rechecks_the_unique_target_before_setting_pending_reward(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSkillRewardAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    pending = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_session",
        lambda: SimpleNamespace(pending_reward=None, set_pending_reward=lambda *args: pending.append(args)),
    )
    monkeypatch.setattr(module, "detect_skill_reward_selected_page", lambda context, image: SimpleNamespace(name="祝福"))
    screenshots = iter((b"selected-right", b"after-left", b"after-center", b"after-right"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "skill_reward")
    details = iter((
        {"name": "祝福", "name_texts": ("祝福",), "effect_text": "体力消費4 パラメータ+26 好調1ターン レッスン中1回", "confidence": 0.99, "name_confidence": 0.99, "detail_confidence": 0.99},
        {"name": "意地", "name_texts": ("意地",), "effect_text": "元気+3 集中+4 レッスン中1回", "confidence": 0.99, "name_confidence": 0.99, "detail_confidence": 0.99},
        {"name": "トークタイム", "name_texts": ("トークタイム",), "effect_text": "好調状態の場合、使用可 パラメータ+27 レッスン中1回", "confidence": 0.99, "name_confidence": 0.99, "detail_confidence": 0.99},
        {"name": "祝福", "name_texts": ("祝福",), "effect_text": "体力消費4 パラメータ+26 好調1ターン レッスン中1回", "confidence": 0.99, "name_confidence": 0.99, "detail_confidence": 0.99},
    ))
    monkeypatch.setattr(action, "_read_skill_reward_detail", lambda context, image: next(details))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(
        context,
        SimpleNamespace(
            custom_action_param='{"execution_mode":"single_step","skill_reward_probe":"receive_selected","skill_reward_receive_authorized":true,"skill_reward_initial_slot":"candidate_right"}'
        ),
    )
    assert clicks == [([158, 821, 127, 128], False), ([297, 821, 127, 128], False), ([436, 821, 127, 128], False)]
    assert pending == [("skill", "祝福", "candidate_right")]
    assert tasks == []
    assert any(record[0][1:3] == ("prepare_skill_reward_receipt", "selected") for record in records)


def test_hif_skill_reward_receive_mode_stops_before_candidate_clicks_without_explicit_authorization(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceChooseHIFSkillRewardAuto()
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: None,
        ),
    )
    monkeypatch.setattr(module, "get_runtime_hif_session", lambda: SimpleNamespace(pending_reward=None))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"skill")
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: screen == "skill_reward")
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: clicks.append(args) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step","skill_reward_probe":"receive_selected"}'))
    assert clicks == []
    assert tasks == ["ProduceHIFUnknownStop"]


def test_hif_skill_reward_confirm_requires_explicit_authorization_and_round1_postcheck(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceHIFRewardConfirmAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    cleared = []
    pending = SimpleNamespace(kind="skill", name="祝福", slot="candidate_right")
    monkeypatch.setattr(
        module,
        "get_runtime_hif_session",
        lambda: SimpleNamespace(pending_reward=pending, clear_pending_reward=lambda: cleared.append(True)),
    )
    monkeypatch.setattr(module, "detect_skill_reward_selected_page", lambda context, image: SimpleNamespace(name="祝福"))
    screenshots = iter((b"selected", b"round1"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda context, image, screen: image == b"round1" and screen == "round1")
    monkeypatch.setattr(action, "_find_text_option", lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[230, 1052, 260, 84])))
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"execution_mode":"single_step","skill_reward_receive_authorized":true}'),
    )
    assert clicks == [([230, 1052, 260, 84], False)]
    assert cleared == [True]
    assert tasks == []
    assert records[-1][0][1:3] == ("confirm_skill_reward", "verified")
    assert records[-1][1]["details"]["next_screen"] == "round1"


def test_hif_skill_reward_confirm_stops_before_receiving_without_explicit_authorization(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceHIFRewardConfirmAuto()
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: None,
        ),
    )
    pending = SimpleNamespace(kind="skill", name="祝福", slot="candidate_right")
    monkeypatch.setattr(
        module,
        "get_runtime_hif_session",
        lambda: SimpleNamespace(pending_reward=pending, clear_pending_reward=lambda: pytest.fail("不应清除待领取奖励")),
    )
    monkeypatch.setattr(module, "detect_skill_reward_selected_page", lambda context, image: SimpleNamespace(name="祝福"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: b"selected")
    clicks = []
    monkeypatch.setattr(action, "_click_box_center", lambda *args, **kwargs: clicks.append(args) or True)
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(context, SimpleNamespace(custom_action_param='{"execution_mode":"single_step"}'))
    assert clicks == []
    assert tasks == ["ProduceHIFUnknownStop"]


def test_hif_skill_reward_confirm_preserves_pending_reward_for_the_verified_reveal_page(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceHIFRewardConfirmAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    cleared = []
    pending = SimpleNamespace(kind="skill", name="祝福", slot="candidate_right")
    monkeypatch.setattr(
        module,
        "get_runtime_hif_session",
        lambda: SimpleNamespace(pending_reward=pending, clear_pending_reward=lambda: cleared.append(True)),
    )
    monkeypatch.setattr(module, "detect_skill_reward_selected_page", lambda context, image: SimpleNamespace(name="祝福"))
    monkeypatch.setattr(module, "detect_skill_reward_reveal_page", lambda context, image: SimpleNamespace(name="祝福"))
    screenshots = iter((b"selected", b"reveal"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(action, "_matches_screen_profile", lambda *args: False)
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[230, 1052, 260, 84])),
    )
    clicks = []
    monkeypatch.setattr(
        action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True
    )
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"execution_mode":"single_step","skill_reward_receive_authorized":true}'),
    )
    assert clicks == [([230, 1052, 260, 84], False)]
    assert cleared == []
    assert tasks == []
    assert records[-1][1]["details"]["next_screen"] == "skill_reward_reveal"


def test_hif_skill_reward_reveal_confirms_only_the_expected_card_and_round1(monkeypatch):
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        module = import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)

    action = module.ProduceHIFSkillRewardRevealAuto()
    action.ACTION_DELAY = 0
    records = []
    monkeypatch.setattr(
        module,
        "get_runtime_hif_journal",
        lambda: SimpleNamespace(
            capture=lambda image, label: SimpleNamespace(fingerprint=f"{label}:{image}"),
            record=lambda *args, **kwargs: records.append((args, kwargs)),
        ),
    )
    cleared = []
    pending = SimpleNamespace(kind="skill", name="祝福", slot="candidate_right")
    monkeypatch.setattr(
        module,
        "get_runtime_hif_session",
        lambda: SimpleNamespace(pending_reward=pending, clear_pending_reward=lambda: cleared.append(True)),
    )
    monkeypatch.setattr(module, "detect_skill_reward_reveal_page", lambda context, image: SimpleNamespace(name="祝福"))
    screenshots = iter((b"reveal", b"round1"))
    monkeypatch.setattr(action, "_get_screenshot", lambda context: next(screenshots))
    monkeypatch.setattr(module, "frame_changed", lambda before, after: True)
    monkeypatch.setattr(
        action, "_matches_screen_profile", lambda context, image, screen: image == b"round1" and screen == "round1"
    )
    monkeypatch.setattr(
        action,
        "_find_text_option",
        lambda *args, **kwargs: SimpleNamespace(best_result=SimpleNamespace(box=[230, 1052, 260, 84])),
    )
    clicks = []
    monkeypatch.setattr(
        action, "_click_box_center", lambda context, box, double=False, **kwargs: clicks.append((list(box), double)) or True
    )
    tasks = []
    context = SimpleNamespace(run_task=lambda task: tasks.append(task))

    assert action.run(
        context,
        SimpleNamespace(custom_action_param='{"execution_mode":"single_step","skill_reward_receive_authorized":true}'),
    )
    assert clicks == [([230, 1052, 260, 84], False)]
    assert cleared == [True]
    assert tasks == []
    assert records[-1][0][1:3] == ("confirm_skill_reward_reveal", "verified")
