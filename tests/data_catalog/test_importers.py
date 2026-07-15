from pathlib import Path

from tools.data_catalog.ids import stable_entity_id
from tools.data_catalog.schema import SchemaStore
from tools.data_catalog.importers import import_existing_data

DATA_ROOT = Path(__file__).resolve().parents[2] / "assets" / "data"


def test_import_frozen_baseline_without_silent_loss() -> None:
    result = import_existing_data(DATA_ROOT)

    assert len(result.records["produce_idol_cards"]) == 136
    assert len(result.records["characters"]) == 13
    assert len(result.records["skill_cards"]) == 122
    assert len(result.records["drinks"]) == 28
    assert len(result.records["legacy_skill_seeds"]) == 8
    assert len({item["entity_id"] for values in result.records.values() for item in values}) == 307


def test_missing_skill_translation_is_not_invented() -> None:
    result = import_existing_data(DATA_ROOT)
    card = next(item for item in result.records["skill_cards"] if item["names"]["ja-JP"]["canonical"] == "ハイテンション")
    assert card["names"]["zh-CN"]["canonical"] is None


def test_legacy_shared_bonus_and_relations_are_explicit() -> None:
    result = import_existing_data(DATA_ROOT)
    card = result.records["produce_idol_cards"][0]
    profile = card["stat_profiles"][0]

    assert card["character_id"].startswith("character:")
    assert card["strategy_annotations"][0]["fact_status"] == "strategy_only"
    assert profile["vo"]["bonus_percent"] is None
    assert profile["da"]["bonus_percent"] is None
    assert profile["vi"]["bonus_percent"] is None
    assert profile["legacy_shared_bonus"]["evidence_status"] == "legacy_shared"


def test_drink_unmatched_is_preserved_as_unknown() -> None:
    result = import_existing_data(DATA_ROOT)
    partial = [item for item in result.records["drinks"] if item["effect"]["parse_status"] == "partial"]

    assert len(partial) == 22
    assert all(item["effect"]["ast"][-1]["op"] == "unknown" for item in partial)
    assert all(item["effect"]["ast"][-1]["raw"] == item["effect"]["unmatched_fragments"][0] for item in partial)


def test_stable_entity_id_is_repeatable_and_source_scoped() -> None:
    first = stable_entity_id("drink", "source:a", "key")
    assert first == stable_entity_id("drink", "source:a", "key")
    assert first != stable_entity_id("drink", "source:b", "key")


def test_imported_assertions_and_canonical_adapters_match_v2_schemas() -> None:
    result = import_existing_data(DATA_ROOT)
    schemas = SchemaStore()

    for assertion in (result.assertions[0], result.assertions[-1]):
        schemas.validate("assertion", assertion)
    for schema_name, record_group in (
        ("character", "characters"),
        ("produce-idol-card", "produce_idol_cards"),
        ("skill-card", "skill_cards"),
        ("drink", "drinks"),
        ("effect-version", "effect_versions"),
    ):
        records = result.canonical_records[record_group]
        schemas.validate(schema_name, records[0])
        schemas.validate(schema_name, records[-1])
