"""将仓库现有资料无损转换为 data catalog v2 候选记录。

本模块只读取调用方提供的文件，不写 canonical，也不访问网络。旧资料中的
不确定信息会显式标记为 ``legacy_shared``、``partial`` 或 ``unknown``。
"""

from __future__ import annotations

import json
import hashlib
from typing import Any, Iterable
from pathlib import Path
from dataclasses import dataclass

from .ids import stable_entity_id


@dataclass(frozen=True, slots=True)
class ImportResult:
    """一次旧资料导入的内存结果。"""

    records: dict[str, list[dict[str, Any]]]
    canonical_records: dict[str, list[dict[str, Any]]]
    assertions: list[dict[str, Any]]
    legacy_id_map: dict[str, str]


def import_existing_data(data_root: str | Path) -> ImportResult:
    """导入计划冻结的 136/122/121/28/8 seed 基线。"""

    root = Path(data_root)
    records: dict[str, list[dict[str, Any]]] = {
        "characters": [],
        "produce_idol_cards": [],
        "skill_cards": [],
        "drinks": [],
        "legacy_skill_seeds": [],
    }
    legacy_id_map: dict[str, str] = {}

    idols = _load_json(root / "idols_master.json").get("records", [])
    character_by_name: dict[str, str] = {}
    for raw in idols:
        names = raw.get("names", {})
        idol_jp = str(names.get("idol_jp", ""))
        if idol_jp not in character_by_name:
            character_id = stable_entity_id("character", "legacy:idols-master", idol_jp)
            character_by_name[idol_jp] = character_id
            records["characters"].append(
                {
                    "schema_version": "2.0",
                    "entity_id": character_id,
                    "source_keys": {"legacy_idol_name_jp": idol_jp},
                    "identity_status": "provisional_name_key",
                    "names": {
                        "ja-JP": {"canonical": idol_jp},
                        "zh-CN": {"canonical": names.get("idol_zh") or None},
                    },
                }
            )

        legacy_id = str(raw.get("idol_card_id", ""))
        source_key = str(raw.get("source_keys", {}).get("card_name_jp") or legacy_id)
        entity_id = stable_entity_id("produce_idol_card", "legacy:idols-master", source_key)
        legacy_id_map[f"idol_card:{legacy_id}"] = entity_id
        stats = raw.get("stats", {})
        shared_bonus = stats.get("bonus")
        record = {
            "schema_version": "2.0",
            "entity_id": entity_id,
            "legacy_ids": [legacy_id] if legacy_id else [],
            "source_keys": {"legacy_card_name_jp": source_key},
            "character_id": character_by_name[idol_jp],
            "names": {
                "ja-JP": {"canonical": names.get("card_jp") or None},
                "zh-CN": {"canonical": names.get("card_zh") or None},
            },
            "idol_names": {"ja-JP": idol_jp, "zh-CN": names.get("idol_zh") or None},
            "song_names": {"ja-JP": names.get("song_jp") or None, "zh-CN": names.get("song_zh") or None},
            "rarity": raw.get("rarity"),
            "debut_date": raw.get("debut_date") or None,
            "stat_profiles": [
                {
                    "profile_id": "legacy_default",
                    "context": {"enhancement": "unknown", "source_format": "legacy_snapshot"},
                    "vo": {"value": stats.get("Vo"), "bonus_percent": None},
                    "da": {"value": stats.get("Da"), "bonus_percent": None},
                    "vi": {"value": stats.get("Vi"), "bonus_percent": None},
                    "stamina": stats.get("stamina"),
                    "legacy_shared_bonus": {
                        "value": shared_bonus,
                        "applies_to": ["vo", "da", "vi"],
                        "evidence_status": "legacy_shared",
                    },
                }
            ],
            "unique_skill_card_id": None,
            "p_item_id": None,
            "strategy_annotations": [
                {
                    "kind": "recommended_effect",
                    "text": raw.get("recommended_effect", {}).get("jp") or "",
                    "translations": {"zh-CN": raw.get("recommended_effect", {}).get("zh") or ""},
                    "fact_status": "strategy_only",
                }
            ],
        }
        records["produce_idol_cards"].append(record)

    skill_translations = {
        row.get("name_jp"): row.get("name_zh")
        for row in _load_json(root / "hif" / "skill_cards_zh.json").get("cards", [])
        if row.get("name_jp")
    }
    for raw in _load_json(root / "hif" / "skill_cards_master.json").get("cards", []):
        wiki_id = str(raw.get("wiki_id", ""))
        entity_id = stable_entity_id("skill_card", "seesaawiki:skill-cards", wiki_id)
        tiers = []
        for tier_name, tier in raw.get("tiers", {}).items():
            tiers.append(
                {
                    "tier": tier_name,
                    "cost": {
                        "stamina": tier.get("stamina_cost"),
                        "focus": tier.get("focus_cost"),
                        "raw": tier.get("cost_raw") or "",
                    },
                    "effect": {
                        "raw_text": tier.get("effect_raw") or "",
                        "ast": [],
                        "parse_status": "partial",
                        "runtime_support": "display_only",
                    },
                }
            )
        records["skill_cards"].append(
            {
                "schema_version": "2.0",
                "entity_id": entity_id,
                "source_keys": {"seesaawiki_id": wiki_id},
                "legacy_ids": [],
                "names": {
                    "ja-JP": {"canonical": raw.get("name_jp")},
                    "zh-CN": {"canonical": skill_translations.get(raw.get("name_jp"))},
                },
                "source_category": raw.get("page_category"),
                "is_lesson_once": bool(raw.get("is_lesson_once")),
                "note_raw": raw.get("note_raw") or "",
                "tiers": tiers,
            }
        )

    for raw in _load_json(root / "hif" / "drinks.json").get("drinks", []):
        wiki_id = str(raw.get("wiki_id", ""))
        entity_id = stable_entity_id("drink", "seesaawiki:p-drinks", wiki_id)
        ast = [dict(node) for node in raw.get("effects", []) if isinstance(node, dict)]
        unmatched = raw.get("unmatched")
        if isinstance(unmatched, str) and unmatched.strip():
            ast.append({"op": "unknown", "raw": unmatched, "reason_code": "unsupported_grammar"})
        records["drinks"].append(
            {
                "schema_version": "2.0",
                "entity_id": entity_id,
                "legacy_ids": [raw.get("drink_id")] if raw.get("drink_id") else [],
                "source_keys": {"seesaawiki_id": wiki_id},
                "names": {
                    "ja-JP": {"canonical": raw.get("name_jp")},
                    "zh-CN": {"canonical": raw.get("name_zh")},
                },
                "plan": raw.get("plan"),
                "rarity": raw.get("rarity"),
                "unlock_plv": raw.get("unlock_plv"),
                "cost": {"consultation": raw.get("cost", {}).get("consultation"), "use": None},
                "effect": {
                    "raw_text": raw.get("raw_text") or "",
                    "ast": ast,
                    "unmatched_fragments": [unmatched] if isinstance(unmatched, str) and unmatched.strip() else [],
                    "parse_status": "partial" if unmatched else "complete",
                },
            }
        )

    for raw in _load_json(root / "skill_cards_master.json").get("records", []):
        legacy_id = str(raw.get("skill_card_id", ""))
        entity_id = stable_entity_id("legacy_skill_seed", "manual_seed:hif-skill-cards", legacy_id)
        legacy_id_map[f"skill_card_seed:{legacy_id}"] = entity_id
        records["legacy_skill_seeds"].append(
            {
                "schema_version": "2.0",
                "entity_id": entity_id,
                "legacy_ids": [legacy_id],
                "source_keys": dict(raw.get("source_keys", {})),
                "names": dict(raw.get("names", {})),
                "effect_text": raw.get("effect_text") or "",
                "legacy_payload": raw,
                "source_status": "legacy_seed",
                "runtime_support": "unsupported",
            }
        )

    assertions: list[dict[str, Any]] = []
    for entity_type, items in records.items():
        for record in items:
            assertions.extend(_record_assertions(entity_type, record))
    return ImportResult(
        records=records,
        canonical_records=_adapt_schema_records(records, assertions),
        assertions=assertions,
        legacy_id_map=legacy_id_map,
    )


def _record_assertions(entity_type: str, record: dict[str, Any]) -> Iterable[dict[str, Any]]:
    entity_id = record["entity_id"]
    for path, value in _leaf_values(record):
        if path in {"/schema_version", "/entity_id"}:
            continue
        payload = json.dumps([entity_id, path, value], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        assertion_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        yield {
            "assertion_id": f"assertion:{assertion_hash}",
            "entity_id": entity_id,
            "schema_version": "2.0",
            "field_path": path,
            "value": value,
            "raw_value": value,
            "source_id": _source_for_record(entity_type, record),
            "source_locator": f"legacy:{path}",
            "observed_at": _observed_at_for_record(entity_type),
            "effective_from": None,
            "source_confidence": "legacy_snapshot",
            "parse_status": "partial" if entity_type == "legacy_skill_seeds" else "complete",
            "verification_status": "unverified",
            "runtime_support": record.get("runtime_support", "display_only"),
            "parser_version": "data-catalog-v2-import/1",
            "content_hash": f"sha256:{assertion_hash}",
        }


def _leaf_values(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key in sorted(value):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from _leaf_values(value[key], f"{path}/{escaped}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaf_values(item, f"{path}/{index}")
    else:
        yield path or "/", value


def _source_for_record(entity_type: str, record: dict[str, Any]) -> str:
    if entity_type in {"characters", "produce_idol_cards"}:
        return "source:legacy-idols-master-2026-05-18"
    if entity_type == "skill_cards":
        return "source:seesaawiki-skill-cards-2026-07-01"
    if entity_type == "drinks":
        return "source:seesaawiki-p-drinks-2026-06-30"
    return "source:legacy-skill-seed-2026-05-18"


def _observed_at_for_record(entity_type: str) -> str:
    if entity_type in {"characters", "produce_idol_cards", "legacy_skill_seeds"}:
        return "2026-05-18T13:34:54+00:00"
    if entity_type == "skill_cards":
        return "2026-07-01T08:28:14+00:00"
    return "2026-06-30T13:04:38+00:00"


def _adapt_schema_records(
    records: dict[str, list[dict[str, Any]]], assertions: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """把无损候选投影为当前 JSON Schema 可校验的 canonical 候选。"""

    assertion_ids: dict[str, list[str]] = {}
    for assertion in assertions:
        assertion_ids.setdefault(assertion["entity_id"], []).append(assertion["assertion_id"])

    output: dict[str, list[dict[str, Any]]] = {
        "characters": [],
        "produce_idol_cards": [],
        "skill_cards": [],
        "drinks": [],
        "effect_versions": [],
        "strategy_annotations": [],
    }
    for raw in records["characters"]:
        names = {
            locale: value["canonical"]
            for locale, value in raw["names"].items()
            if isinstance(value.get("canonical"), str) and value["canonical"]
        }
        output["characters"].append(
            {
                "schema_version": "2.0",
                "entity_id": raw["entity_id"],
                "legacy_ids": [],
                "names": names,
                "source_keys": [
                    {"source_id": "source:legacy-idols-master-2026-05-18", "key": raw["source_keys"]["legacy_idol_name_jp"]}
                ],
                "canonical_assertion_ids": assertion_ids[raw["entity_id"]],
            }
        )
    for raw in records["produce_idol_cards"]:
        profile = raw["stat_profiles"][0]
        shared_bonus = profile["legacy_shared_bonus"]["value"]
        names = {
            locale: value["canonical"]
            for locale, value in raw["names"].items()
            if isinstance(value.get("canonical"), str) and value["canonical"]
        }
        output["produce_idol_cards"].append(
            {
                "schema_version": "2.0",
                "entity_id": raw["entity_id"],
                "character_id": raw["character_id"],
                "legacy_ids": raw["legacy_ids"],
                "names": names,
                "rarity": raw["rarity"],
                "source_keys": [
                    {"source_id": "source:legacy-idols-master-2026-05-18", "key": raw["source_keys"]["legacy_card_name_jp"]}
                ],
                "stat_profiles": [
                    {
                        "context": "legacy_snapshot;bonus_scope=legacy_shared",
                        "vo": {"value": profile["vo"]["value"], "bonus_percent": None},
                        "da": {"value": profile["da"]["value"], "bonus_percent": None},
                        "vi": {"value": profile["vi"]["value"], "bonus_percent": None},
                        "stamina": profile["stamina"],
                        "legacy_shared_bonus": {"value": shared_bonus, "applies_to": ["vo", "da", "vi"], "evidence_status": "legacy_shared"},
                    }
                ],
                "unique_skill_card_ids": [],
                "p_item_ids": [],
                "canonical_assertion_ids": assertion_ids[raw["entity_id"]],
            }
        )
        output["strategy_annotations"].append(
            {
                "schema_version": "2.0",
                "entity_id": raw["entity_id"],
                **raw["strategy_annotations"][0],
            }
        )
    category_map = {"sense": "general", "support": "support", "rinami": "produce_idol", "hif_observed": "scenario"}
    for raw in records["skill_cards"]:
        names = {
            locale: value["canonical"]
            for locale, value in raw["names"].items()
            if isinstance(value.get("canonical"), str) and value["canonical"]
        }
        effect_ids: list[str] = []
        tier_names: list[str] = []
        for tier in raw["tiers"]:
            tier_name = "base" if tier["tier"] == "無印" else tier["tier"]
            tier_names.append(tier_name)
            effect_id = stable_entity_id("effect_version", "legacy:hif-skill-tier", f"{raw['entity_id']}:{tier_name}")
            effect_ids.append(effect_id)
            output["effect_versions"].append(
                {
                    "schema_version": "2.0",
                    "entity_id": effect_id,
                    "raw_text": tier["effect"]["raw_text"],
                    "ast": [],
                    "unmatched_fragments": [tier["effect"]["raw_text"]] if tier["effect"]["raw_text"] else [],
                    "parse_status": "partial",
                    "parser_version": "data-catalog-v2-import/1",
                    "runtime_support": "display_only",
                    "source_assertion_ids": assertion_ids[raw["entity_id"]],
                    "effective_from": None,
                    "effective_to": None,
                    "implementation_version": None,
                }
            )
        output["skill_cards"].append(
            {
                "schema_version": "2.0",
                "entity_id": raw["entity_id"],
                "legacy_ids": [],
                "names": names,
                "source_keys": [{"source_id": "source:seesaawiki-skill-cards-2026-07-01", "key": raw["source_keys"]["seesaawiki_id"]}],
                "source_category": category_map.get(raw["source_category"], "unknown"),
                "plan": "sense" if raw["source_category"] == "sense" else "unknown",
                "rarity": "",
                "tiers": tier_names,
                "effect_version_ids": effect_ids,
                "canonical_assertion_ids": assertion_ids[raw["entity_id"]],
            }
        )
    for raw in records["drinks"]:
        effect_id = stable_entity_id("effect_version", "legacy:hif-drink", raw["entity_id"])
        names = {
            locale: value["canonical"]
            for locale, value in raw["names"].items()
            if isinstance(value.get("canonical"), str) and value["canonical"]
        }
        effect = raw["effect"]
        output["effect_versions"].append(
            {
                "schema_version": "2.0",
                "entity_id": effect_id,
                "raw_text": effect["raw_text"],
                "ast": effect["ast"],
                "unmatched_fragments": effect["unmatched_fragments"],
                "parse_status": effect["parse_status"],
                "parser_version": "data-catalog-v2-import/1",
                "runtime_support": "display_only",
                "source_assertion_ids": assertion_ids[raw["entity_id"]],
                "effective_from": None,
                "effective_to": None,
                "implementation_version": None,
            }
        )
        output["drinks"].append(
            {
                "schema_version": "2.0",
                "entity_id": raw["entity_id"],
                "names": names,
                "source_keys": [{"source_id": "source:seesaawiki-p-drinks-2026-06-30", "key": raw["source_keys"]["seesaawiki_id"]}],
                "plan": raw["plan"] if raw["plan"] in {"sense", "logic", "anomaly", "free"} else "unknown",
                "rarity": raw["rarity"],
                "consultation_cost": raw["cost"]["consultation"],
                "use_cost": raw["cost"]["use"],
                "effect_version_ids": [effect_id],
                "canonical_assertion_ids": assertion_ids[raw["entity_id"]],
            }
        )
    return output


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"预期 JSON object：{path}")
    return value
