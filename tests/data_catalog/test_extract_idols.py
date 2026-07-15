from pathlib import Path

from tools.data_catalog.extract import extract_idol_cards_html

FIXTURE = Path(__file__).with_name("fixtures") / "seesaa_idols_independent_bonus.html"


def test_extracts_independent_stat_bonuses_without_hardcoded_count() -> None:
    result = extract_idol_cards_html(FIXTURE.read_text(encoding="utf-8"), observed_at="2026-07-15T00:00:00+08:00")

    assert len(result["records"]) == 2
    first = result["records"][0]
    profile = first["stat_profiles"][0]
    assert first["character_source_key"] == "姫崎莉波"
    assert first["strategy_annotations"][0] == {
        "kind": "recommended_effect",
        "text": "センス好調",
        "fact_status": "strategy_only",
    }
    assert profile["vo"] == {"value": 100, "bonus_percent": 18}
    assert profile["da"] == {"value": 105, "bonus_percent": 22}
    assert profile["vi"] == {"value": 110, "bonus_percent": 27.5}
    assert "legacy_shared_bonus" not in profile


def test_extracts_inline_independent_bonuses() -> None:
    result = extract_idol_cards_html(FIXTURE.read_text(encoding="utf-8"), observed_at="2026-07-15T00:00:00+08:00")
    profile = result["records"][1]["stat_profiles"][0]

    assert [profile[key]["bonus_percent"] for key in ("vo", "da", "vi")] == [11, 12, 13]
    assert result["warnings"] == []
    assert any(item["field_path"] == "/stat_profiles/0/vi/bonus_percent" for item in result["assertions"])
