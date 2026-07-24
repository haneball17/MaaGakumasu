import json
from pathlib import Path

from agent.hif.pipeline_validation import (
    load_pipeline_nodes,
    _remove_jsonc_trivia,
    validate_hif_pipeline,
    find_unreachable_hif_nodes,
    load_hif_coverage_manifest,
    load_registered_custom_actions,
    validate_hif_coverage_manifest,
    validate_hif_recognition_contracts,
    load_registered_custom_recognitions,
)


def test_hif_pipeline_references_existing_nodes_and_registered_actions():
    pipeline_root = Path("assets/resource/base/pipeline")
    all_nodes = load_pipeline_nodes(pipeline_root)
    hif_nodes = json.loads((pipeline_root / "ProduceHIF.json").read_text(encoding="utf-8"))

    issues = validate_hif_pipeline(
        hif_nodes,
        known_nodes=all_nodes,
        registered_custom_actions=load_registered_custom_actions("agent/custom/action"),
        registered_custom_recognitions=load_registered_custom_recognitions("agent/custom/reco"),
    )

    assert issues == ()


def test_hif_coverage_matrix_covers_every_current_pipeline_node_and_declares_all_scenarios():
    pipeline_path = Path("assets/resource/base/pipeline/ProduceHIF.json")
    pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
    manifest = load_hif_coverage_manifest("assets/data/hif/pipeline_coverage.json")

    assert validate_hif_coverage_manifest(pipeline, manifest) == ()


def test_hif_recognition_contracts_reference_existing_templates_and_valid_rois():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert validate_hif_recognition_contracts(
        pipeline,
        image_root="assets/resource/base/image",
    ) == ()


def test_hif_task_overrides_match_between_locales_reference_existing_nodes_and_default_to_observe():
    produce = json.loads(Path("assets/tasks/produce.json").read_text(encoding="utf-8"))
    produce_cn = json.loads(Path("assets/tasks/produce_cn.json").read_text(encoding="utf-8"))
    all_nodes = load_pipeline_nodes("assets/resource/base/pipeline")

    def option_case(payload, option_name, case_name):
        option = payload["option"][option_name]
        return next(case for case in option["cases"] if case["name"] == case_name)

    hif = option_case(produce, "培育难度", "HIF")
    hif_cn = option_case(produce_cn, "培育难度", "HIF")
    assert hif["pipeline_override"] == hif_cn["pipeline_override"]
    assert hif["pipeline_override"]["ProduceEntryFlag"]["next"] == "ProduceEntryHIF"
    assert "ProduceHIFStartConfirmFlag" in hif["pipeline_override"]["ProduceChooseIdolNext"]["next"]
    assert hif["pipeline_override"]["ProduceLoop"]["next"][0] == "ProduceHIFFinalsPrepareResumeFlag"

    for node_name in hif["pipeline_override"]:
        assert node_name in all_nodes

    for payload in (produce, produce_cn):
        execution = payload["option"]["HIF执行模式"]
        assert execution["default_case"] == "观测（默认）"
        observe_case = option_case(payload, "HIF执行模式", "观测（默认）")
        assert "pipeline_override" not in observe_case
        single_step = option_case(payload, "HIF执行模式", "单步执行（实验）")
        for node_name, override in single_step["pipeline_override"].items():
            assert node_name in all_nodes
            params = override.get("action", {}).get("param", {}).get("custom_action_param")
            if params is not None:
                assert params["execution_mode"] == "single_step"


def test_hif_resume_anchor_only_routes_confirmed_finals_prepare_to_schedule_selection():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    resume = pipeline["ProduceHIFFinalsPrepareResumeFlag"]

    assert resume["recognition"] == {
        "type": "And",
        "param": {
            "all_of": [
                {
                    "recognition": {
                        "type": "OCR",
                        "param": {
                            "expected": [".*H\\.?I\\.?F\\s*本[戦战].*(?:まで|还有|剩余).*"],
                            "roi": [32, 25, 160, 60],
                        },
                    },
                },
                {
                    "recognition": {
                        "type": "OCR",
                        "param": {"expected": [".*[1-6]\\s*日.*"], "roi": [55, 85, 110, 75]},
                    },
                },
            ],
            "box_index": 0,
        },
    }
    assert resume["action"]["type"] == "DoNothing"
    assert resume["next"] == ["ProduceChooseHIFEventFlag", "ProduceHIFUnknownStop"]


def test_hif_formal_router_reachability_keeps_only_declared_legacy_or_dynamic_nodes_outside_the_root_graph():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    unreachable = find_unreachable_hif_nodes(
        pipeline,
        entry_nodes=("ProduceEntryHIF", "ProduceHIFStartConfirmFlag", "ProduceHIFAfterChooseFinalMode", "ProduceHIFFinalsPrepareResumeFlag"),
        dynamic_targets=("ProduceHIFRound1ReachedStop", "ProduceHIFRound2ReachedStop", "ProduceHIFIntervalReachedStop"),
    )

    manifest = load_hif_coverage_manifest("assets/data/hif/pipeline_coverage.json")
    legacy_nodes = {
        node_name
        for group in manifest["coverage_matrix"]
        if group["category"] == "legacy_entry"
        for node_name in group["nodes"]
    }
    assert legacy_nodes <= unreachable
    assert unreachable - legacy_nodes == {
        "ProduceHIFButton",
        "ProduceHIFGenerationFlag",
        "ProduceHIFKnownNextButton",
        "ProduceHIFRound1ActionFlag",
        "ProduceHIFSafeAdvanceFlag",
        "ProduceHIFSelectionModeContinueButton",
    }


def test_hif_result_page_clicks_are_routed_through_verified_custom_actions():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert pipeline["ProduceHIFRewardConfirmFlag"]["action"]["param"]["custom_action"] == "ProduceHIFRewardConfirmAuto"
    assert pipeline["ProduceHIFKnownNextButton"]["action"]["param"]["custom_action"] == "ProduceHIFKnownNextAuto"
    assert pipeline["ProduceHIFPublicLessonResultFlag"]["action"]["param"]["custom_action"] == "ProduceHIFPublicLessonResultAuto"


def test_hif_day2_preview_test_pipeline_records_each_course_with_native_recognition_detail():
    pipeline = json.loads(_remove_jsonc_trivia(Path("assets/resource/base/pipeline/test/TEST_HIF_2.json").read_text(encoding="utf-8")))

    schedule = pipeline["test_hif_day2_schedule_flag"]["recognition"]["param"]
    assert schedule["template"] == ["produce/HIF/hif_day2_flag_2.png"]
    assert pipeline["test_hif_day2_schedule_flag"]["next"] == ["test_hif_day2_no_selection"]
    no_selection = pipeline["test_hif_day2_no_selection"]
    assert no_selection["recognition"]["param"]["custom_recognition"] == "HIFPublicLessonPreviewNoSelection"
    assert no_selection["next"] == ["test_hif_day2_select_vo"]
    for candidate, target in (("vo", [168, 1000]), ("da", [360, 1000]), ("vi", [552, 1000])):
        select = pipeline[f"test_hif_day2_select_{candidate}"]["recognition"]
        assert select == {"type": "DirectHit", "param": {}}
        assert pipeline[f"test_hif_day2_select_{candidate}"]["action"]["param"]["target"] == target
        read = pipeline[f"test_hif_day2_read_{candidate}_preview"]
        assert read["recognition"]["type"] == "Custom"
        assert read["recognition"]["param"]["custom_recognition"] == "HIFPublicLessonPreviewDetail"
        assert read["recognition"]["param"]["custom_recognition_param"] == {"candidate": candidate.title()}
        assert read["action"]["type"] == "DoNothing"


def test_hif_day1_change_entry_round_trips_to_scene3_before_stopping():
    pipeline = json.loads(_remove_jsonc_trivia(Path("assets/resource/base/pipeline/test/TEST_HIF_day1.json").read_text(encoding="utf-8")))

    assert pipeline["hif_day1_场景3_标志"]["next"] == ["TestHIFDay1ChangeDeckEntry"]
    entry = pipeline["TestHIFDay1ChangeDeckEntry"]
    assert entry["recognition"]["type"] == "And"
    assert entry["recognition"]["param"]["all_of"][0] == "hif_day1_场景3_标志"
    assert entry["recognition"]["param"]["all_of"][1]["recognition"]["param"] == {
        "template": ["produce/HIF/hif_change_deck_entry.png"],
        "roi": [618, 1166, 82, 82],
        "threshold": 0.9,
    }
    assert entry["action"] == {"type": "Custom", "param": {"custom_action": "ProduceHIFDay1ChangeDeckRoundTrip"}}
    assert entry["next"] == ["TestHIFDay1ChangeDeckReturned"]
    assert entry["on_error"] == ["unknownstop"]
    assert entry["max_hit"] == 1
    assert pipeline["TestHIFDay1ChangeDeckReturned"] == {
        "recognition": {
            "type": "And",
            "param": {
                "all_of": [
                    "hif_day1_场景3_标志",
                    {
                        "recognition": {
                            "type": "TemplateMatch",
                            "param": {
                                "template": ["produce/HIF/hif_change_deck_entry.png"],
                                "roi": [618, 1166, 82, 82],
                                "threshold": 0.9,
                            },
                        }
                    },
                ],
                "box_index": 1,
            },
        },
        "action": {"type": "DoNothing"},
        "on_error": ["unknownstop"],
    }
    assert pipeline["TestHIFDay1ChangeDeckRecover"]["action"] == {
        "type": "Custom",
        "param": {"custom_action": "ProduceHIFDay1ChangeDeckCloseRecover"},
    }
    assert pipeline["TestHIFDay1ChangeDeckVSCodeEntry"]["action"]["param"] == {
        "custom_action": "ProduceHIFDay1ChangeDeckRoundTrip",
        "custom_action_param": {"execution_mode": "single_step"},
    }


def test_hif_day1_daily_log_recovery_is_template_bound_and_returns_to_change_candidates():
    pipeline = json.loads(_remove_jsonc_trivia(Path("assets/resource/base/pipeline/test/TEST_HIF_day1.json").read_text(encoding="utf-8")))

    close = pipeline["TestHIFDay1DailyLogClose"]
    assert close["recognition"]["type"] == "And"
    assert close["recognition"]["param"]["all_of"][1]["recognition"]["param"] == {
        "template": ["produce/HIF/hif_day1_daily_log_close.png"],
        "roi": [319, 1120, 82, 82],
        "threshold": 0.9,
    }
    assert close["action"] == {"type": "Click"}
    assert close["next"] == ["hif_day1_场景3_标志"]
    assert close["on_error"] == ["unknownstop"]


def test_hif_day1_candidate_slot_one_observes_its_title_before_stopping():
    pipeline = json.loads(_remove_jsonc_trivia(Path("assets/resource/base/pipeline/test/TEST_HIF_day1.json").read_text(encoding="utf-8")))

    assert pipeline["浏览待选卡牌_点击槽位1"]["action"] == {
        "type": "Click",
        "param": {"target": [219, 899, 1, 1]},
    }
    assert pipeline["浏览待选卡牌_点击槽位1"]["next"] == ["TestHIFDay1ChangeCandidateSlot1Title"]
    assert pipeline["TestHIFDay1ChangeCandidateSlot1Title"] == {
        "recognition": {"type": "OCR", "param": {"expected": [], "roi": [180, 500, 360, 60]}},
        "action": {"type": "DoNothing"},
        "next": ["unknownstop"],
        "on_error": ["unknownstop"],
    }


def test_hif_day3_test_entry_observes_the_four_days_schedule_without_clicking():
    pipeline = json.loads(_remove_jsonc_trivia(Path("assets/resource/base/pipeline/test/TEST_HIF_2.json").read_text(encoding="utf-8")))

    assert pipeline["test_hif_day3_entry"]["next"] == ["test_hif_day3_schedule_flag"]
    schedule = pipeline["test_hif_day3_schedule_flag"]["recognition"]
    assert schedule == {
        "type": "And",
        "param": {"all_of": ["test_hif_day3_title_flag", "test_hif_day3_remaining_days_flag"], "box_index": 0},
    }
    assert pipeline["test_hif_day3_title_flag"]["recognition"]["param"]["expected"] == [".*H\\.I\\.F本戦まで.*"]
    assert pipeline["test_hif_day3_remaining_days_flag"]["recognition"]["param"]["expected"] == [".*4日.*"]
    observe = pipeline["test_hif_day3_observe_schedule"]
    assert observe["recognition"] == {"type": "DirectHit", "param": {}}
    assert observe["action"]["param"] == {
        "custom_action": "ProduceChooseHIFEventAuto",
        "custom_action_param": {"execution_mode": "observe"},
    }
    assert observe["next"] == ["test_hif_observe_stop"]

    gift_select = pipeline["test_hif_day3_gift_select_once"]
    assert pipeline["test_hif_day3_gift_select_entry"]["next"] == ["test_hif_day3_gift_schedule_flag"]
    assert gift_select["action"]["param"] == {
        "custom_action": "ProduceChooseHIFEventAuto",
        "custom_action_param": {"preset_id": "rinami_good_condition_safe", "execution_mode": "single_step"},
    }
    assert gift_select["next"] == ["test_hif_observe_stop"]
    gift_confirm = pipeline["test_hif_day3_gift_confirm_once"]
    assert pipeline["test_hif_day3_gift_confirm_entry"]["next"] == ["test_hif_day3_gift_selected_flag"]
    assert pipeline["test_hif_day3_gift_selected_flag"]["recognition"]["param"]["all_of"][1] == {
        "recognition": {"type": "OCR", "param": {"expected": [".*SELEC.*"], "roi": [360, 1080, 160, 70]}}
    }
    assert gift_confirm["action"]["param"] == gift_select["action"]["param"]
    assert gift_confirm["next"] == ["test_hif_observe_stop"]


def test_hif_finals_day_and_round1_observation_entries_are_zero_input_checkpoints():
    pipeline = json.loads(_remove_jsonc_trivia(Path("assets/resource/base/pipeline/test/TEST_HIF_2.json").read_text(encoding="utf-8")))

    for day, remaining_days in ((1, 6), (4, 3), (5, 2), (6, 1)):
        entry = pipeline[f"test_hif_day{day}_entry"]
        schedule = pipeline[f"test_hif_day{day}_schedule_flag"]
        remaining = pipeline[f"test_hif_day{day}_remaining_days_flag"]
        assert entry["next"] == [f"test_hif_day{day}_schedule_flag"]
        assert remaining["recognition"]["param"]["expected"] == [f".*{remaining_days}日.*"]
        assert schedule["recognition"]["param"]["all_of"] == ["test_hif_day3_title_flag", f"test_hif_day{day}_remaining_days_flag"]
        assert schedule["action"]["type"] == "DoNothing"
        assert schedule["next"] == ["test_hif_observe_stop"]

    assert pipeline["test_hif_ranking_flag"]["recognition"]["param"] == {
        "expected": [".*タップして次へ.*"],
        "roi": [245, 1140, 250, 80],
    }
    assert pipeline["test_hif_round1_flag"]["recognition"]["param"]["roi"] == [8, 0, 170, 48]
    assert pipeline["test_hif_round1_observe"]["action"]["param"]["custom_action"] == "ProduceHIFRound1Observe"
    for node_name in (
        "test_hif_class_options_observe",
        "test_hif_public_lesson_result_observe",
        "test_hif_gift_bags_observe",

        "test_hif_gift_reward_result_observe",
        "test_hif_drink_reward_observe",
        "test_hif_skill_reward_observe",
        "test_hif_drink_overflow_observe",
        "test_hif_select_change_target_observe",
        "test_hif_select_change_source_observe",
        "test_hif_consult_observe",
    ):
        assert pipeline[node_name]["action"]["type"] == "DoNothing"
        assert pipeline[node_name]["next"] == ["test_hif_observe_stop"]
    assert pipeline["test_hif_gift_bags_advance_entry"]["action"]["param"] == {
        "custom_action": "ProduceHIFSafeAdvanceAuto",
        "custom_action_param": {"source": "gift_bags", "execution_mode": "single_step"},
    }
    assert pipeline["test_hif_gift_reward_result_advance_entry"]["action"]["param"] == {
        "custom_action": "ProduceHIFSafeAdvanceAuto",
        "custom_action_param": {"source": "gift_reward_result", "execution_mode": "single_step"},
    }
    for slot, target in (("left", [221, 885]), ("center", [360, 885]), ("right", [499, 885])):
        preview = pipeline[f"test_hif_drink_reward_preview_{slot}"]
        assert preview["recognition"] == {"type": "Custom", "param": {"custom_recognition": "ProduceHIFDrinkRewardPage"}}
        assert preview["action"]["param"]["target"] == target
        assert preview["next"] == ["test_hif_drink_reward_observe"]
    receive = pipeline["test_hif_drink_reward_receive_black_vinegar_entry"]
    assert receive["recognition"]["param"]["all_of"] == [
        {"recognition": {"type": "OCR", "param": {"expected": [".*初星黒酢.*"], "roi": [118, 506, 500, 230]}}},
        {"recognition": {"type": "OCR", "param": {"expected": [".*受け取る.*"], "roi": [230, 1052, 260, 84]}}},
    ]
    assert receive["action"]["param"]["target"] == [360, 1094]
    assert receive["next"] == ["test_hif_drink_reward_reveal_observe"]
    reveal_wait = pipeline["test_hif_drink_reward_reveal_wait_10s"]
    assert reveal_wait["action"]["type"] == "DoNothing"
    assert reveal_wait["post_delay"] == 10000
    assert pipeline["test_hif_drink_reward_reveal_wait_entry"]["action"]["param"] == {
        "custom_action": "ProduceHIFDrinkRewardRevealAuto",
        "custom_action_param": {"execution_mode": "single_step"},
    }
    reveal_confirm = pipeline["test_hif_drink_reward_reveal_confirm_entry"]
    assert reveal_confirm["action"]["param"]["target"] == [360, 1094]
    assert reveal_confirm["next"] == ["test_hif_skill_reward_observe"]
    assert pipeline["test_hif_observe_stop"]["action"]["type"] == "StopTask"

    assert (
        validate_hif_pipeline(
            pipeline,
            known_nodes=pipeline,
            registered_custom_actions=load_registered_custom_actions("agent/custom/action"),
            registered_custom_recognitions=load_registered_custom_recognitions("agent/custom/reco"),
        )
        == ()
    )


def test_hif_drink_reward_flags_route_selected_and_revealed_states_via_registered_custom_recognitions():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    recognition = pipeline["ProduceHIFDrinkRewardFlag"]["recognition"]
    reveal = pipeline["ProduceHIFDrinkRewardRevealFlag"]

    assert recognition == {
        "type": "Custom",
        "param": {"custom_recognition": "ProduceHIFDrinkRewardPage"},
    }
    assert reveal["recognition"] == {
        "type": "Custom",
        "param": {"custom_recognition": "ProduceHIFDrinkRewardRevealPage"},
    }
    assert reveal["action"]["param"]["custom_action"] == "ProduceHIFDrinkRewardRevealAuto"
    assert "ProduceHIFDrinkRewardPage" in load_registered_custom_recognitions("agent/custom/reco")
    assert "ProduceHIFDrinkRewardRevealPage" in load_registered_custom_recognitions("agent/custom/reco")
    route = pipeline["ProduceEntryHIF"]["next"]
    assert route.index("[JumpBack]ProduceHIFDrinkRewardRevealFlag") < route.index("[JumpBack]ProduceHIFDrinkRewardFlag")


def test_hif_skill_reward_prompt_tolerates_the_observed_single_character_ocr_confusion():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    recognition = pipeline["ProduceHIFSkillRewardFlag"]["recognition"]

    assert recognition["param"]["expected"] == [".*受[けは]取るスキルカードを選んでください.*"]
    assert recognition["param"]["roi"] == [100, 570, 540, 100]


def test_hif_skill_reward_selected_detail_routes_before_unknown_stop():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    selected = pipeline["ProduceHIFSkillRewardSelectedFlag"]
    route = pipeline["ProduceEntryHIF"]["next"]

    assert selected["recognition"] == {
        "type": "Custom",
        "param": {"custom_recognition": "ProduceHIFSkillRewardSelectedPage"},
    }
    assert selected["action"]["param"]["custom_action"] == "ProduceChooseHIFSkillRewardAuto"
    assert "ProduceHIFSkillRewardSelectedPage" in load_registered_custom_recognitions("agent/custom/reco")
    assert route.index("[JumpBack]ProduceHIFSkillRewardSelectedFlag") < route.index("ProduceHIFUnknownStop")


def test_hif_incremental_pipeline_routes_actions_back_and_limits_safe_advance():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert pipeline["ProduceHIFSafeAdvanceFlag"]["action"]["param"]["custom_action"] == "ProduceHIFSafeAdvanceAuto"
    assert pipeline["ProduceHIFStartConfirmFlag"]["action"]["param"]["custom_action"] == "ProduceHIFStartProduceAuto"
    assert "ProduceHIFSafeAdvanceFlag" not in pipeline["ProduceEntryHIF"]["next"]
    assert pipeline["ProduceHIFGiftBagsFlag"]["action"]["param"]["custom_action"] == "ProduceHIFSafeAdvanceAuto"
    for node_name in (
        "ProduceChooseHIFEventFlag",
        "ProduceHIFStartConfirmFlag",
        "ProduceChooseHIFPItemFlag",
        "ProduceHIFSkillEnhancedResultFlag",
        "ProduceHIFClassOptionFlag",
        "ProduceHIFDrinkRewardRevealFlag",
        "ProduceHIFRewardConfirmFlag",
        "ProduceHIFSelectChangeTargetFlag",
        "ProduceHIFSelectChangeSourceFlag",
        "ProduceHIFConsultFlag",
        "ProduceHIFPublicLessonResultFlag",
        "ProduceHIFKnownNextButton",
    ):
        assert pipeline[node_name]["next"] == ["[JumpBack]ProduceEntryHIF", "ProduceHIFUnknownStop"]


def test_hif_schedule_route_uses_visible_text_before_the_safe_advance_fallback():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    schedule = pipeline["ProduceChooseHIFEventFlag"]["recognition"]

    assert schedule["type"] == "OCR"
    assert ".*授業.*" in schedule["param"]["expected"]
    assert schedule["param"]["roi"] == [84, 920, 552, 196]


def test_hif_unknown_lesson_options_are_guarded_before_unknown_stop():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    class_options = pipeline["ProduceHIFClassOptionFlag"]["recognition"]

    assert class_options["type"] == "OCR"
    assert class_options["param"]["expected"] == [".*授業.*"]
    assert class_options["param"]["roi"] == [32, 36, 160, 105]
    assert pipeline["ProduceEntryHIF"]["next"].index("[JumpBack]ProduceHIFClassOptionFlag") < pipeline["ProduceEntryHIF"]["next"].index(
        "ProduceHIFUnknownStop"
    )


def test_hif_source_deck_flag_uses_the_stable_page_title_before_action_level_dual_anchor_validation():
    pipeline = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))
    source_flag = pipeline["ProduceHIFSelectChangeSourceFlag"]["recognition"]

    assert source_flag["type"] == "OCR"
    assert source_flag["param"]["expected"] == [".*チェンジ.*"]
    assert source_flag["param"]["roi"] == [0, 28, 285, 58]


def test_hif_pipeline_validation_reports_missing_action_and_target():
    issues = validate_hif_pipeline(
        {
            "Node": {
                "action": {"type": "Custom", "param": {"custom_action": "MissingAction"}},
                "next": ["[JumpBack]MissingNode"],
            },
            "RecognitionNode": {
                "recognition": {"type": "Custom", "param": {"custom_recognition": "MissingRecognition"}},
            },
        },
        known_nodes={"Node"},
        registered_custom_actions=(),
        registered_custom_recognitions=(),
    )

    assert issues == (
        "Node:unregistered_custom_action:MissingAction",
        "Node:missing_next_target:[JumpBack]MissingNode",
        "RecognitionNode:unregistered_custom_recognition:MissingRecognition",
    )


def test_hif_recognition_contract_validation_reports_bad_regex_roi_and_missing_template(tmp_path):
    issues = validate_hif_recognition_contracts(
        {
            "BadOCR": {
                "recognition": {"type": "OCR", "param": {"expected": ["["], "roi": [0, 0, 721, 1]}},
            },
            "BadTemplate": {
                "recognition": {"type": "TemplateMatch", "param": {"template": ["missing.png"], "roi": [0, 0, 1, 1]}},
            },
        },
        image_root=tmp_path,
    )

    assert issues == (
        "BadOCR:invalid_roi",
        "BadOCR:invalid_ocr_pattern:[",
        "BadTemplate:missing_template:missing.png",
    )


def test_pipeline_jsonc_reader_preserves_comment_markers_inside_strings():
    payload = json.loads(_remove_jsonc_trivia('{"url":"https://example.invalid/a//b", /* note */ "items":[1,],}'))

    assert payload == {"url": "https://example.invalid/a//b", "items": [1]}
