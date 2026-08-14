import re
import sys
import json
from types import SimpleNamespace
from pathlib import Path
from importlib import import_module

import numpy as np
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
from agent.hif.presets import parse_hif_preset, choose_first_matching, choose_schedule_priority
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


def test_hif_pipeline_routes_round1_to_observe_stop_not_generic_card_action():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert payload["ProduceHIFRound1Flag"]["next"] == ["ProduceHIFRound1ObserveFlag"]
    assert payload["ProduceHIFRound1ObserveFlag"]["action"]["param"]["custom_action"] == "ProduceHIFRound1Observe"
    assert payload["ProduceHIFRound1ReachedStop"]["action"]["type"] == "StopTask"
    assert "ProduceCardsFlag" not in payload["ProduceHIFRound1Flag"]["next"]


def test_hif_pipeline_sends_unsupported_pages_to_safe_stop():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert payload["ProduceHIFIntervalFlag"]["next"] == ["ProduceHIFUnknownStop"]
    assert payload["ProduceHIFScoreSettlementFlag"]["next"] == ["ProduceHIFUnknownStop"]
    assert payload["ProduceHIFMemoryFlag"]["next"] == ["ProduceHIFUnknownStop"]


def test_hif_preset_option_injects_the_same_preset_into_round1_and_event_actions():
    task_payload = json.loads(Path("assets/tasks/produce.json").read_text(encoding="utf-8"))
    cases = task_payload["option"]["HIF预设"]["cases"]
    override = cases[1]["pipeline_override"]

    expected_actions = {
        "ProduceChooseHIFEventFlag",
        "ProduceHIFClassOptionFlag",
        "ProduceHIFDrinkRewardFlag",
        "ProduceHIFSkillRewardFlag",
        "ProduceHIFSelectChangeTargetFlag",
        "ProduceHIFSelectChangeSourceFlag",
        "ProduceHIFConsultFlag",
        "ProduceHIFRound1ObserveFlag",
    }
    assert set(override) == expected_actions
    assert all(value["custom_action_param"]["preset_id"] == "rinami_good_condition_safe" for value in override.values())
    assert override["ProduceHIFRound1ObserveFlag"]["custom_action_param"]["round1_mode"] == "observe_and_stop"


def test_hif_selection_mode_does_not_fall_back_to_generic_button():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert "ProduceHIFButton" not in payload["ProduceHIFSelectionModeFlag"]["next"]
    button = payload["ProduceHIFSelectionModeContinueButton"]
    assert button["recognition"]["param"]["template"] == ["next.png", "produce/decide.png"]
    assert button["recognition"]["param"]["roi"] == [200, 1000, 320, 160]


def test_hif_idol_select_flag_routes_before_selection_mode_to_avoid_misrouting():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    prep_routing = payload["ProduceHIFPrepRoot"]["next"]

    assert prep_routing.index("[JumpBack]ProduceHIFIdolSelectFlag") < prep_routing.index("[JumpBack]ProduceHIFSelectionModeFlag")
    flag = payload["ProduceHIFIdolSelectFlag"]
    assert flag["recognition"]["param"]["expected"] == [".*アイドル選択.*"]
    assert flag["action"]["param"]["custom_action"] == "ProduceHIFChooseIdolAuto"


def test_hif_pipeline_uses_segmented_roots_with_error_chaining():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    main_root = payload["ProduceEntryHIF"]["next"]
    assert "[JumpBack]ProduceHIFPrepRoot" in main_root
    assert "ProduceHIFUnknownStop" not in main_root
    assert "ProduceHIFButton" not in payload
    assert "ProduceHIFGenerationFlag" not in payload

    prep_root = payload["ProduceHIFPrepRoot"]
    assert prep_root["on_error"] == ["ProduceHIFScheduleRoot"]
    schedule_root = payload["ProduceHIFScheduleRoot"]
    assert schedule_root["on_error"] == ["ProduceHIFUnknownStop"]
    assert schedule_root["timeout"] >= 30000

    schedule_next = schedule_root["next"]
    assert schedule_next[0] == "[JumpBack]ProduceHIFRound1Flag"
    assert "[JumpBack]ProduceHIFSelectChangeDoneFlag" in schedule_next
    assert "ProduceHIFUnknownStop" not in schedule_next


def test_hif_round1_flag_anchors_on_remaining_turn_counter():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    flag = payload["ProduceHIFRound1Flag"]["recognition"]["param"]
    assert flag["expected"] == [".*残りターン.*"]
    assert flag["roi"] == [13, 43, 120, 128]


def test_hif_event_flag_uses_gradient_card_template_with_exact_method():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    param = payload["ProduceChooseHIFEventFlag"]["recognition"]["param"]
    assert "produce/hif_event_card.png" in param["template"]
    assert param["method"] == 10001
    assert Path("assets/resource/base/image/produce/hif_event_card.png").exists()
    for legacy in ("hif_lesson_vo.png", "hif_lesson_da.png", "hif_lesson_vi.png"):
        assert legacy not in json.dumps(param)


def test_hif_attribute_card_scan_classifies_vo_da_vi_by_fan_color():
    sys.path.insert(0, str(Path("agent").resolve()))
    action_cls = import_module("custom.action.produce_hif").ProduceChooseHIFEventAuto

    canvas = np.zeros((1280, 720, 3), dtype=np.uint8)
    canvas[:] = 240
    fans = {
        "Vo": (119, (208, 144, 207)),
        "Da": (285, (99, 185, 245)),
        "Vi": (448, (213, 203, 161)),
    }
    fan_dx, fan_y, fan_w, fan_h = action_cls.FAN_REGION
    band = canvas[action_cls.GRADIENT_BAND]
    for _, (card_x, rgb) in fans.items():
        canvas[fan_y : fan_y + fan_h, card_x + fan_dx : card_x + fan_dx + fan_w] = rgb
        grad_slice = band[:, card_x + 10 : card_x + 100]
        grad_slice[:, :, 0] = 146
        grad_slice[:, :, 1] = 143
        grad_slice[:, :, 2] = 250

    cards = action_cls._scan_attribute_cards(action_cls, canvas)
    assert [card["name"] for card in cards] == ["Vo", "Da", "Vi"]
    for card in cards:
        assert card["box"][2:] == [1, 1] and card["box"][1] == 1000


def test_hif_drink_overflow_and_select_change_done_have_live_actions():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert payload["ProduceHIFDrinkOverflowFlag"]["action"]["param"]["custom_action"] == "ProduceChooseHIFDrinkOverflowAuto"
    assert payload["ProduceHIFDrinkOverflowFlag"].get("next") is None
    done = payload["ProduceHIFSelectChangeDoneFlag"]
    assert done["action"]["param"]["custom_action"] == "ProduceHIFSelectChangeDoneAuto"
    assert done["recognition"]["param"]["expected"] == [".*チェンジしました.*"]


def test_hif_preset_splits_reroll_limits_by_scene():
    from agent.hif.presets import SAFE_DEFAULT_PRESET

    assert SAFE_DEFAULT_PRESET.select_change_reroll_limit == 3
    assert SAFE_DEFAULT_PRESET.reward_reroll_limit == 2


def test_hif_pipeline_ocr_patterns_are_valid_regular_expressions():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    for node in payload.values():
        expected = node.get("recognition", {}).get("param", {}).get("expected", [])
        for pattern in expected if isinstance(expected, list) else [expected]:
            if isinstance(pattern, str):
                re.compile(pattern)


def test_hif_task_skips_generic_difficulty_ocr_and_enters_hif_routing():
    for task_path in (Path("assets/tasks/produce.json"), Path("assets/tasks/produce_cn.json")):
        task_payload = json.loads(task_path.read_text(encoding="utf-8"))
        hif_case = next(case for case in task_payload["option"]["培育难度"]["cases"] if case["name"] == "HIF")
        mode_override = hif_case["pipeline_override"]["ProduceChooseDifficulty"]

        assert mode_override["recognition"]["type"] == "DirectHit"
        assert mode_override["action"]["type"] == "DoNothing"
        assert mode_override["next"] == "ProduceEntryHIF"


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

    assert action.run(object(), SimpleNamespace(custom_action_param='{"preset_id":"safe_default"}'))
    assert stop_reasons == [("consult_shop", "finish_button_click_failed")]
