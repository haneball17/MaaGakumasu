from copy import deepcopy

import pytest
from jsonschema import ValidationError

from tools.data_catalog.schema import SchemaStore, UnsupportedSchemaVersion

UUID = "00000000-0000-5000-8000-000000000001"
HASH = "sha256:" + "0" * 64
SOURCE_KEY = {"source_id": "source:wiki", "key": "1"}


VALID_INSTANCES = {
    "source-manifest": {
        "schema_version": "2.0",
        "source_id": "source:wiki",
        "url": "https://example.com/data",
        "observed_at": "2026-07-15T00:00:00Z",
        "content_hash": HASH,
        "parser_version": "1",
        "status": "complete",
    },
    "assertion": {
        "schema_version": "2.0",
        "assertion_id": "assertion:1",
        "entity_id": f"skill_card:{UUID}",
        "field_path": "/names/ja-JP/canonical",
        "value": "月明かり",
        "raw_value": "月明かり",
        "source_id": "source:wiki",
        "source_locator": "table:1/name",
        "observed_at": "2026-07-15T00:00:00Z",
        "source_confidence": "community_structured",
        "parse_status": "complete",
        "verification_status": "unverified",
        "runtime_support": "display_only",
        "parser_version": "1",
        "content_hash": HASH,
    },
    "character": {
        "schema_version": "2.0",
        "entity_id": f"character:{UUID}",
        "names": {"ja-JP": "姫崎莉波"},
        "source_keys": [SOURCE_KEY],
        "canonical_assertion_ids": ["assertion:1"],
    },
    "produce-idol-card": {
        "schema_version": "2.0",
        "entity_id": f"produce_idol_card:{UUID}",
        "character_id": f"character:{UUID}",
        "names": {"ja-JP": "ガラクタロード"},
        "rarity": "SSR",
        "source_keys": [SOURCE_KEY],
        "stat_profiles": [{"context": "level_1", "vo": {"value": 100, "bonus_percent": 10}, "da": {"value": 90, "bonus_percent": 20}, "vi": {"value": 80, "bonus_percent": 30}, "stamina": 30}],
        "canonical_assertion_ids": ["assertion:1"],
    },
    "skill-card": {
        "schema_version": "2.0",
        "entity_id": f"skill_card:{UUID}",
        "names": {"ja-JP": "お姉さんの感覚"},
        "source_keys": [SOURCE_KEY],
        "source_category": "produce_idol",
        "plan": "sense",
        "tiers": ["base", "+"],
        "effect_version_ids": [f"effect_version:{UUID}"],
        "canonical_assertion_ids": ["assertion:1"],
    },
    "drink": {
        "schema_version": "2.0",
        "entity_id": f"drink:{UUID}",
        "names": {"ja-JP": "ブーストエキス"},
        "source_keys": [SOURCE_KEY],
        "plan": "free",
        "consultation_cost": 75,
        "use_cost": 2,
        "effect_version_ids": [f"effect_version:{UUID}"],
        "canonical_assertion_ids": ["assertion:1"],
    },
    "term": {
        "schema_version": "2.0",
        "entity_id": f"term:{UUID}",
        "code": "status:good_condition",
        "names": {"ja-JP": "好調"},
        "source_keys": [SOURCE_KEY],
        "canonical_assertion_ids": ["assertion:1"],
    },
    "alias": {
        "schema_version": "2.0",
        "entity_id": f"alias:{UUID}",
        "target_entity_id": f"skill_card:{UUID}",
        "alias_type": "ocr_error",
        "value": "月明り",
        "match_key": "月明り",
        "locale": "ja-JP",
        "profile": "mumu-1280x720",
        "evidence_assertion_ids": ["assertion:1"],
    },
    "effect-version": {
        "schema_version": "2.0",
        "entity_id": f"effect_version:{UUID}",
        "raw_text": "元気+11",
        "ast": [{"op": "add_status", "value": 11}],
        "unmatched_fragments": [],
        "parse_status": "complete",
        "parser_version": "1",
        "runtime_support": "modeled",
        "source_assertion_ids": ["assertion:1"],
    },
    "scenario-overlay": {
        "schema_version": "2.0",
        "scenario_code": "hif",
        "required_semantics": ["effect:add_status"],
        "entries": [{"entity_id": f"skill_card:{UUID}", "scenario_available": True, "runtime_support": "executable", "evidence_assertion_ids": ["assertion:1"]}],
    },
}


@pytest.mark.parametrize("schema_name", sorted(VALID_INSTANCES))
def test_each_schema_accepts_a_positive_fixture(schema_name):
    SchemaStore().validate(schema_name, VALID_INSTANCES[schema_name])


@pytest.mark.parametrize("schema_name", sorted(VALID_INSTANCES))
def test_each_schema_rejects_a_negative_fixture(schema_name):
    invalid = deepcopy(VALID_INSTANCES[schema_name])
    invalid.pop("schema_version")

    with pytest.raises(ValidationError):
        SchemaStore().validate(schema_name, invalid)


def test_unknown_schema_major_version_is_rejected_before_processing():
    invalid = deepcopy(VALID_INSTANCES["character"])
    invalid["schema_version"] = "3.0"

    with pytest.raises(UnsupportedSchemaVersion, match="主版本 3"):
        SchemaStore().validate("character", invalid)


def test_unknown_effect_node_must_preserve_raw_fragment_and_reason():
    invalid = deepcopy(VALID_INSTANCES["effect-version"])
    invalid["ast"] = [{"op": "unknown"}]

    with pytest.raises(ValidationError):
        SchemaStore().validate("effect-version", invalid)
