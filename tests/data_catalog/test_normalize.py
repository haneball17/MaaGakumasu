from tools.data_catalog.normalize import normalize_name, normalize_match_key, normalization_collisions


def test_normalization_preserves_raw_and_splits_enhancement_suffix():
    result = normalize_name(" ★ 月明かり ＋＋ ")

    assert result.raw == " ★ 月明かり ＋＋ "
    assert result.match_key == "月明かり++"
    assert result.base_match_key == "月明かり"
    assert result.enhancement == "++"


def test_normalization_does_not_translate_or_merge_distinct_spellings():
    assert normalize_match_key("月明り") != normalize_match_key("月明かり")
    assert normalize_match_key("好調") != normalize_match_key("こうちょう")


def test_collision_report_reports_but_never_merges_identities():
    collisions = normalization_collisions(
        [
            {"entity_id": "skill_card:a", "value": "カード ＋"},
            {"entity_id": "skill_card:b", "value": "カード+"},
            {"entity_id": "skill_card:a", "value": "カード＋"},
        ]
    )

    assert collisions == [
        {
            "match_key": "カード+",
            "candidates": [
                {"entity_id": "skill_card:a", "raw": "カード ＋"},
                {"entity_id": "skill_card:a", "raw": "カード＋"},
                {"entity_id": "skill_card:b", "raw": "カード+"},
            ],
        }
    ]
