from pathlib import Path

import pytest

from tools import hif_live_runner


def test_live_runner_defaults_to_the_formal_hif_router_and_requires_adb_contract():
    args = hif_live_runner.parse_args(["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe"])

    assert args.task == "ProduceEntryHIF"
    assert not args.single_step


def test_live_runner_single_step_override_excludes_round_and_skill_card_actions():
    override = hif_live_runner.single_step_override()

    assert "ProduceHIFDrinkRewardFlag" in override
    assert "ProduceHIFDrinkRewardRevealFlag" in override
    assert "ProduceHIFRewardConfirmFlag" in override
    assert "ProduceChooseDifficulty" in override
    assert "ProduceHIFStartConfirmFlag" in override
    assert "ProduceHIFClassOptionFlag" in override
    assert "ProduceHIFPublicLessonResultFlag" in override
    assert "ProduceHIFSkillEnhancedResultFlag" in override
    assert "ProduceHIFSelectChangeTargetFlag" in override
    assert "ProduceHIFConsultFlag" in override
    assert "ProduceHIFSkillRewardFlag" not in override
    assert "ProduceHIFRound1ActionFlag" not in override
    assert "ProduceHIFRound2ActionFlag" not in override


def test_skill_reward_enumeration_requires_an_explicit_single_step_switch():
    args = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--single-step", "--skill-reward-enumerate"]
    )
    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSkillRewardFlag"]["action"]["param"]["custom_action_param"]
    assert params == {
        "preset_id": "rinami_good_condition_safe",
        "execution_mode": "single_step",
        "skill_reward_probe": "enumerate_candidates",
    }
    assert override["ProduceHIFSkillRewardSelectedFlag"]["action"]["param"]["custom_action_param"] == params
    assert override["ProduceEntryHIF"]["next"] == [
        "[JumpBack]ProduceHIFSkillRewardSelectedFlag",
        "[JumpBack]ProduceHIFSkillRewardFlag",
        "ProduceHIFUnknownStop",
    ]
    assert "ProduceHIFRound1ActionFlag" not in override
    assert "ProduceHIFRound2ActionFlag" not in override

    unsafe_args = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--skill-reward-enumerate"]
    )
    with pytest.raises(ValueError, match="技能卡候选枚举"):
        hif_live_runner.runtime_override(unsafe_args)


def test_skill_reward_enumeration_can_skip_a_known_already_selected_slot():
    args = hif_live_runner.parse_args(
        [
            "--adb",
            "127.0.0.1:16416",
            "--adb-path",
            "D:/MuMu/adb.exe",
            "--single-step",
            "--skill-reward-enumerate",
            "--skill-reward-initial-slot",
            "left",
        ]
    )

    override = hif_live_runner.runtime_override(args)

    params = override["ProduceHIFSkillRewardFlag"]["action"]["param"]["custom_action_param"]
    assert params["skill_reward_initial_slot"] == "candidate_left"


def test_skill_reward_decision_is_explicit_and_cannot_grant_receipt_permission():
    args = hif_live_runner.parse_args(
        [
            "--adb",
            "127.0.0.1:16416",
            "--adb-path",
            "D:/MuMu/adb.exe",
            "--single-step",
            "--skill-reward-decide",
            "--skill-reward-initial-slot",
            "right",
        ]
    )

    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSkillRewardFlag"]["action"]["param"]["custom_action_param"]
    assert params["skill_reward_probe"] == "decide_candidates"
    assert params["skill_reward_initial_slot"] == "candidate_right"
    assert override["ProduceHIFRewardConfirmFlag"]["action"]["param"]["custom_action_param"].get("skill_reward_receive_authorized") is None
    assert "ProduceHIFRound1ActionFlag" not in override


def test_skill_reward_receive_grants_confirmation_only_to_the_explicit_receive_mode():
    args = hif_live_runner.parse_args(
        [
            "--adb",
            "127.0.0.1:16416",
            "--adb-path",
            "D:/MuMu/adb.exe",
            "--single-step",
            "--skill-reward-receive",
            "--skill-reward-initial-slot",
            "right",
        ]
    )

    override = hif_live_runner.runtime_override(args)

    assert override is not None
    for node_name in ("ProduceHIFSkillRewardFlag", "ProduceHIFSkillRewardSelectedFlag"):
        params = override[node_name]["action"]["param"]["custom_action_param"]
        assert params["skill_reward_probe"] == "receive_selected"
        assert params["skill_reward_initial_slot"] == "candidate_right"
        assert params["skill_reward_receive_authorized"] is True
    confirm_params = override["ProduceHIFRewardConfirmFlag"]["action"]["param"]["custom_action_param"]
    assert confirm_params["skill_reward_receive_authorized"] is True
    assert override["ProduceHIFSkillRewardRevealFlag"]["action"]["param"]["custom_action_param"]["skill_reward_receive_authorized"] is True
    assert override["ProduceEntryHIF"]["next"][0] == "[JumpBack]ProduceHIFSkillRewardRevealFlag"
    assert "ProduceHIFRound1ActionFlag" not in override


def test_skill_reward_enumeration_and_decision_cannot_be_combined():
    args = hif_live_runner.parse_args(
        [
            "--adb",
            "127.0.0.1:16416",
            "--adb-path",
            "D:/MuMu/adb.exe",
            "--single-step",
            "--skill-reward-enumerate",
            "--skill-reward-decide",
        ]
    )

    with pytest.raises(ValueError, match="技能卡枚举、纯决策与受限领取模式不能同时启用"):
        hif_live_runner.runtime_override(args)


def test_source_deck_probe_requires_single_step_and_only_overrides_the_source_deck_action():
    args = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--single-step", "--source-deck-probe"]
    )
    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSelectChangeSourceFlag"]["action"]["param"]["custom_action_param"]
    assert params["source_deck_probe"] is True
    assert params["execution_mode"] == "single_step"
    assert "ProduceHIFRound1ActionFlag" not in override

    unsafe_args = hif_live_runner.parse_args(["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--source-deck-probe"])
    with pytest.raises(ValueError, match="源卡牌库探针"):
        hif_live_runner.runtime_override(unsafe_args)


def test_source_deck_visible_enumeration_is_explicit_and_never_grants_scroll_or_confirmation():
    args = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--single-step", "--source-deck-enumerate-visible"]
    )
    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSelectChangeSourceFlag"]["action"]["param"]["custom_action_param"]
    assert params["source_deck_probe"] == "visible_grid"
    assert set(override) >= {"ProduceHIFSelectChangeSourceFlag", "ProduceHIFSelectChangeTargetFlag"}
    assert "ProduceHIFRound1ActionFlag" not in override


def test_source_deck_scroll_enumeration_is_a_separate_explicit_mode():
    args = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--single-step", "--source-deck-scroll-enumerate-visible"]
    )
    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSelectChangeSourceFlag"]["action"]["param"]["custom_action_param"]
    assert params["source_deck_probe"] == "visible_grid_after_one_scroll"
    assert not args.source_deck_enumerate_visible


def test_source_deck_confirmation_is_explicit_and_binds_the_observed_source_card_name():
    args = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--single-step", "--source-deck-confirm-target"]
    )
    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSelectChangeSourceFlag"]["action"]["param"]["custom_action_param"]
    assert params["source_deck_probe"] == "confirm_source_card"
    assert params["source_card_name"] == "大胆不敵"
    assert "target_card_name" not in params


def test_explicit_source_card_confirmation_binds_user_selected_target_and_calibrated_slot():
    args = hif_live_runner.parse_args(
        [
            "--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--single-step",
            "--source-deck-confirm-target", "--select-change-target-name", "成就",
            "--source-deck-confirm-name", "タイミングの基本", "--source-deck-confirm-slot", "r3c1",
        ]
    )

    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSelectChangeSourceFlag"]["action"]["param"]["custom_action_param"]
    assert params["source_card_name"] == "タイミングの基本"
    assert params["source_card_slot"] == "visible_slot_r3c1"
    assert params["selected_target_name"] == "成就"
    assert params["explicit_source_authorized"] is True


def test_explicit_select_change_target_is_limited_to_single_step_and_does_not_mutate_the_default_preset():
    args = hif_live_runner.parse_args(
        [
            "--adb",
            "127.0.0.1:16416",
            "--adb-path",
            "D:/MuMu/adb.exe",
            "--single-step",
            "--select-change-target-name",
            "成就",
        ]
    )

    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSelectChangeTargetFlag"]["action"]["param"]["custom_action_param"]
    assert params["select_change_target_names"] == ["成就"]

    unsafe_args = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--select-change-target-name", "成就"]
    )
    with pytest.raises(ValueError, match="指定变卡目标"):
        hif_live_runner.runtime_override(unsafe_args)


def test_live_runner_loads_the_formal_hif_task_override_for_home_entry():
    override = hif_live_runner.hif_from_home_override()

    assert override["ProduceEntryFlag"]["next"] == "ProduceEntryHIF"
    assert override["ProduceChooseDifficulty"]["action"]["param"]["custom_action"] == "ProduceHIFChooseFinalModeAuto"
    assert override["ProduceChooseDifficulty"]["next"] == ["ProduceAfterChooseDifficulty"]
    assert override["ProduceAfterChooseDifficulty"]["next"] == ["ProduceLackAP", "ProduceChooseIdolNext"]
    assert override["ProduceChooseIdolNext"]["next"] == ["ProduceHIFStartConfirmFlag", "ProduceChooseSupport"]


def test_runtime_override_combines_home_entry_and_safe_single_step_without_round_permissions():
    args = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--hif-from-home", "--single-step"]
    )
    override = hif_live_runner.runtime_override(args)

    assert override is not None
    assert "ProduceChooseScenario" in override
    assert "ProduceHIFDrinkRewardFlag" in override
    assert "ProduceHIFRound1ActionFlag" not in override
    difficulty = override["ProduceChooseDifficulty"]
    assert difficulty["recognition"]["type"] == "DirectHit"
    assert difficulty["action"]["param"]["custom_action"] == "ProduceHIFChooseFinalModeAuto"
    assert difficulty["action"]["param"]["custom_action_param"]["execution_mode"] == "single_step"


def test_home_to_round1_receipt_keeps_the_formal_router_until_the_skill_reward_page():
    args = hif_live_runner.parse_args(
        [
            "--adb",
            "127.0.0.1:16416",
            "--adb-path",
            "D:/MuMu/adb.exe",
            "--hif-from-home",
            "--single-step",
            "--skill-reward-receive",
        ]
    )

    override = hif_live_runner.runtime_override(args)

    assert override is not None
    assert override["ProduceEntryFlag"]["next"] == "ProduceEntryHIF"
    assert "ProduceEntryHIF" not in override
    skill_params = override["ProduceHIFSkillRewardFlag"]["action"]["param"]["custom_action_param"]
    assert skill_params["skill_reward_probe"] == "receive_selected"
    confirm_params = override["ProduceHIFRewardConfirmFlag"]["action"]["param"]["custom_action_param"]
    assert confirm_params["skill_reward_receive_authorized"] is True
    assert "ProduceHIFRound1ActionFlag" not in override


def test_skill_reward_reveal_confirmation_is_limited_to_the_explicit_card_name():
    args = hif_live_runner.parse_args(
        [
            "--adb",
            "127.0.0.1:16416",
            "--adb-path",
            "D:/MuMu/adb.exe",
            "--single-step",
            "--skill-reward-reveal-confirm",
            "--skill-reward-reveal-name",
            "祝福",
        ]
    )

    override = hif_live_runner.runtime_override(args)

    assert override is not None
    params = override["ProduceHIFSkillRewardRevealFlag"]["action"]["param"]["custom_action_param"]
    assert params["skill_reward_reveal_expected_name"] == "祝福"
    assert params["skill_reward_receive_authorized"] is True
    assert override["ProduceEntryHIF"]["next"] == ["[JumpBack]ProduceHIFSkillRewardRevealFlag", "ProduceHIFUnknownStop"]

    missing_name = hif_live_runner.parse_args(
        ["--adb", "127.0.0.1:16416", "--adb-path", "D:/MuMu/adb.exe", "--single-step", "--skill-reward-reveal-confirm"]
    )
    with pytest.raises(ValueError, match="展示层确认必须提供"):
        hif_live_runner.runtime_override(missing_name)


def test_live_runner_persists_explicit_evidence_artifacts_only_under_debug():
    assert Path(hif_live_runner.ROOT, "debug", "hif-live").is_relative_to(hif_live_runner.ROOT)
