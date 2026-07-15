from tools.data_catalog.semantics import (
    RequiredSemantic,
    validate_hif_semantic_gate,
    scan_hif_required_semantics,
)


def test_runtime_scan_is_deterministic_and_covers_each_support_level():
    first = scan_hif_required_semantics()
    second = scan_hif_required_semantics()

    assert first == second
    assert first == tuple(sorted(first))
    assert {item.required_support for item in first} == {
        "executable",
        "modeled",
        "recognizable",
        "unsupported",
    }


def test_runtime_scan_follows_scoring_exact_choice_and_reward_sources():
    requirements = {(item.semantic_type, item.key): item for item in scan_hif_required_semantics()}

    assert requirements[("skill_card_effect", "祝福")].required_support == "executable"
    assert requirements[("skill_card_effect", "演出計画")].required_support == "executable"
    assert requirements[("skill_card_effect", "眠気")].required_support == "unsupported"
    assert requirements[("skill_card", "天賦の才")].required_support == "executable"
    assert requirements[("skill_card", "夏夜に咲く思い出")].required_support == "recognizable"
    assert requirements[("skill_card", "始まりの合図")].required_support == "modeled"
    assert requirements[("drink", "初星黒酢")].required_support == "modeled"
    assert requirements[("drink", "センブリソーダ")].required_support == "modeled"
    assert requirements[("machine_tag", "good_condition_grant")].required_support == "modeled"
    assert requirements[("machine_tag", "draw")].required_support == "modeled"
    assert all(item.sources for item in requirements.values())


def test_gate_rejects_unknown_insufficient_and_normalization_collision():
    requirements = (
        RequiredSemantic("skill_card", "甲", "executable", ("a.py:1",)),
        RequiredSemantic("skill_card", "乙", "recognizable", ("b.py:2",)),
        RequiredSemantic("skill_card", "灰卡", "unsupported", ("c.py:3",)),
        RequiredSemantic("drink", "饮料", "modeled", ("d.json",)),
    )
    issues = validate_hif_semantic_gate(
        requirements,
        {
            ("skill_card", "甲"): "modeled",
            ("skill_card", "乙"): "recognizable",
            ("drink", "饮料"): "unknown",
        },
        match_keys={
            ("skill_card", "甲"): "same",
            ("skill_card", "乙"): "same",
            ("skill_card", "灰卡"): "gray",
            ("drink", "饮料"): "same",
        },
    )

    assert {issue.reason_code for issue in issues} == {
        "required_semantic_insufficient",
        "required_semantic_unknown",
        "normalization_collision",
    }
    collision = next(issue for issue in issues if issue.reason_code == "normalization_collision")
    assert collision.semantic_type == "skill_card"
    assert collision.detail == "乙,甲"


def test_gate_accepts_stronger_support_and_intentional_unsupported():
    requirements = (
        RequiredSemantic("skill_card", "甲", "modeled", ("a.py:1",)),
        RequiredSemantic("skill_card", "灰卡", "unsupported", ("b.py:2",)),
    )

    assert validate_hif_semantic_gate(requirements, {"skill_card:甲": "executable"}) == ()
