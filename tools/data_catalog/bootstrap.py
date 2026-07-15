"""从冻结旧基线生成统一目录 v2 的首次人工晋升切片。"""

from __future__ import annotations

import hashlib
from typing import Any
from collections import defaultdict

from .io import read_json, write_json, write_jsonl
from .ids import stable_entity_id
from .paths import DATA_ROOT, REPORTS_ROOT, OVERLAYS_ROOT, CANONICAL_ROOT, DECISIONS_ROOT, ASSERTIONS_ROOT, ensure_catalog_dirs
from .effects import parse_effect_text, verified_hif_effect, modeled_hif_drink_effect
from .importers import import_existing_data
from .normalize import normalize_match_key
from .semantics import scan_hif_required_semantics

_TERM_NAMES = {
    "plan:sense": ("センス", "感性"),
    "plan:logic": ("ロジック", "理性"),
    "plan:anomaly": ("アノマリー", "非凡"),
    "plan:free": ("フリー", "通用"),
    "status:good_condition": ("好調", "好调"),
    "status:excellent_condition": ("絶好調", "绝好调"),
    "status:focus": ("集中", "集中"),
    "status:vitality": ("元気", "元气"),
    "effect:recover_stamina": ("体力回復", "恢复体力"),
    "effect:gain_vitality": ("元気増加", "增加元气"),
    "effect:draw_card": ("スキルカードを引く", "抽取技能卡"),
}


def bootstrap_catalog() -> dict[str, int]:
    """写入首次迁移产物；相同输入重复执行保持字节级一致。"""

    ensure_catalog_dirs()
    imported = import_existing_data(DATA_ROOT)
    assertions = list(imported.assertions)
    by_entity: dict[str, list[str]] = defaultdict(list)
    assertion_by_path: dict[tuple[str, str], str] = {}
    for item in assertions:
        by_entity[item["entity_id"]].append(item["assertion_id"])
        assertion_by_path[(item["entity_id"], item["field_path"])] = item["assertion_id"]

    canonical = imported.canonical_records
    decision_payload = read_json(DATA_ROOT / "produce_decision_data.json")
    decision_by_legacy_id = {item["idol_card_id"]: (index, item) for index, item in enumerate(decision_payload["idol_cards"])}
    for card in canonical["produce_idol_cards"]:
        legacy_id = card["legacy_ids"][0]
        order, row = decision_by_legacy_id[legacy_id]
        card["compatibility"] = {"decision_row": row, "source_order": order}
    _add_observed_cards(canonical, assertions, by_entity)
    skills = canonical["skill_cards"]
    effects = canonical["effect_versions"]
    rich_skills = {item["entity_id"]: item for item in imported.records["skill_cards"]}
    effect_by_id = {item["entity_id"]: item for item in effects}
    requirement_support = {
        item.key: item.required_support
        for item in scan_hif_required_semantics()
        if item.semantic_type in {"skill_card", "skill_card_effect"}
    }
    raw_skill_payload = read_json(DATA_ROOT / "hif" / "skill_cards_master.json")
    raw_skill_by_id = {item["wiki_id"]: (index, item) for index, item in enumerate(raw_skill_payload["cards"])}
    raw_translation_payload = read_json(DATA_ROOT / "hif" / "skill_cards_zh.json")
    translation_by_name = {item["name_jp"]: (index, item) for index, item in enumerate(raw_translation_payload["cards"])}
    for skill in skills:
        if skill["entity_id"] not in rich_skills:
            continue
        rich = rich_skills[skill["entity_id"]]
        name = skill["names"].get("ja-JP", "")
        wiki_id = skill["source_keys"][0]["key"]
        skill_order, raw_skill = raw_skill_by_id[wiki_id]
        translation = translation_by_name.get(name)
        skill["compatibility"] = {
            "raw_record": raw_skill,
            "source_order": skill_order,
            "translation_row": translation[1] if translation else None,
            "translation_order": translation[0] if translation else None,
        }
        for tier_index, (tier, effect_id) in enumerate(zip(rich["tiers"], skill["effect_version_ids"], strict=True)):
            raw = tier["effect"]["raw_text"]
            parsed = verified_hif_effect(name, tier["tier"], raw) or parse_effect_text(raw)
            effect = effect_by_id[effect_id]
            effect_assertion = assertion_by_path.get((skill["entity_id"], f"/tiers/{tier_index}/effect/raw_text"))
            if effect_assertion:
                effect["source_assertion_ids"] = [effect_assertion]
            effect["ast"] = list(parsed.ast)
            effect["unmatched_fragments"] = list(parsed.unmatched)
            effect["parse_status"] = parsed.parse_status
            support = requirement_support.get(name, "recognizable")
            if name == "眠気":
                support = "unsupported"
            if support == "executable" and parsed.parse_status != "complete":
                support = "recognizable"
            effect["runtime_support"] = support
            effect["implementation_version"] = "hif-effect-v1" if support == "executable" else None

    rich_drinks = {item["entity_id"]: item for item in imported.records["drinks"]}
    raw_drink_payload = read_json(DATA_ROOT / "hif" / "drinks.json")
    raw_drink_by_id = {item["wiki_id"]: (index, item) for index, item in enumerate(raw_drink_payload["drinks"])}
    for drink in canonical["drinks"]:
        name = drink["names"].get("ja-JP", "")
        drink_order, raw_drink = raw_drink_by_id[drink["source_keys"][0]["key"]]
        drink["compatibility"] = {"raw_record": raw_drink, "source_order": drink_order}
        effect = effect_by_id[drink["effect_version_ids"][0]]
        effect_assertion = assertion_by_path.get((drink["entity_id"], "/effect/raw_text"))
        if effect_assertion:
            effect["source_assertion_ids"] = [effect_assertion]
        modeled = modeled_hif_drink_effect(name, rich_drinks[drink["entity_id"]]["effect"]["raw_text"])
        if modeled is not None:
            effect["ast"] = list(modeled.ast)
            effect["unmatched_fragments"] = []
            effect["parse_status"] = "complete"
            effect["runtime_support"] = "modeled"

    aliases: list[dict[str, Any]] = []
    for entity_type in ("characters", "produce_idol_cards", "skill_cards", "drinks"):
        for record in canonical[entity_type]:
            for locale, value in sorted(record.get("names", {}).items()):
                alias_type = "official_name" if locale == "ja-JP" else "translation"
                aliases.append(_alias(record["entity_id"], alias_type, value, locale, by_entity[record["entity_id"]]))
            for legacy_id in record.get("legacy_ids", []):
                aliases.append(_alias(record["entity_id"], "legacy_key", legacy_id, "und", by_entity[record["entity_id"]]))

    terms: list[dict[str, Any]] = []
    for code, (ja, zh) in sorted(_TERM_NAMES.items()):
        entity_id = stable_entity_id("term", "project:controlled-vocabulary", code)
        assertion = _synthetic_assertion(entity_id, "/code", code, "source:project-controlled-vocabulary", "terms/v1", "modeled")
        assertions.append(assertion)
        terms.append(
            {
                "schema_version": "2.0",
                "entity_id": entity_id,
                "code": code,
                "names": {"ja-JP": ja, "zh-CN": zh},
                "source_keys": [{"source_id": "source:project-controlled-vocabulary", "key": code}],
                "canonical_assertion_ids": [assertion["assertion_id"]],
            }
        )

    requirements = scan_hif_required_semantics()
    entity_by_name = {
        (kind, item["names"].get("ja-JP")): item["entity_id"]
        for kind, collection in (("skill_card", skills), ("drink", canonical["drinks"]))
        for item in collection
    }
    support_by_name = {
        (kind, item["names"].get("ja-JP")): (
            "recognizable" if kind == "skill_card" and item["names"].get("ja-JP") == "眠気" else _record_support(item, effect_by_id)
        )
        for kind, collection in (("skill_card", skills), ("drink", canonical["drinks"]))
        for item in collection
    }
    overlay_entries = []
    for (kind, name), entity_id in sorted(entity_by_name.items()):
        overlay_entries.append(
            {
                "entity_id": entity_id,
                "scenario_available": True,
                "runtime_support": support_by_name[(kind, name)],
                "evidence_assertion_ids": sorted(by_entity[entity_id])[:8],
            }
        )
    overlay = {
        "schema_version": "2.0",
        "scenario_code": "hif",
        "required_semantics": [f"{item.semantic_type}:{item.key}:{item.required_support}" for item in requirements],
        "entries": overlay_entries,
    }

    # legacy seed 仅用于兼容派生，明确保持 unsupported；P 道具同理保留旧记录。
    legacy_p_items = _legacy_records(DATA_ROOT / "p_items_master.json", "records")
    write_json(CANONICAL_ROOT / "characters.json", canonical["characters"])
    for name in ("produce_idol_cards", "skill_cards", "drinks", "effect_versions"):
        write_jsonl(CANONICAL_ROOT / f"{name}.jsonl", canonical[name])
    write_jsonl(CANONICAL_ROOT / "terms.jsonl", terms)
    write_jsonl(CANONICAL_ROOT / "aliases.jsonl", aliases)
    write_jsonl(CANONICAL_ROOT / "strategy_annotations.jsonl", canonical["strategy_annotations"])
    write_jsonl(CANONICAL_ROOT / "legacy_skill_seeds.jsonl", imported.records["legacy_skill_seeds"])
    write_jsonl(CANONICAL_ROOT / "legacy_p_items.jsonl", legacy_p_items)
    write_json(
        CANONICAL_ROOT / "compatibility_metadata.json",
        {
            "schema_version": "2.0",
            "skill_cards_master": {key: value for key, value in raw_skill_payload.items() if key != "cards"},
            "skill_cards_zh": {key: value for key, value in raw_translation_payload.items() if key != "cards"},
            "drinks": {key: value for key, value in raw_drink_payload.items() if key != "drinks"},
            "produce_decision_data": {key: value for key, value in decision_payload.items() if key not in {"idol_cards", "skill_cards", "p_items"}},
            "skill_cards_compact": read_json(DATA_ROOT / "skill_cards_compact.json"),
        },
    )
    write_jsonl(ASSERTIONS_ROOT / "initial_import.jsonl", assertions)
    write_json(OVERLAYS_ROOT / "hif.json", overlay)
    write_json(REPORTS_ROOT / "migration_map.json", {"schema_version": "2.0", "legacy_ids": imported.legacy_id_map})
    selected = sorted(item["assertion_id"] for item in assertions)
    decision = {
        "schema_version": "2.0",
        "decision_id": "decision:initial-catalog-v2-import",
        "decided_at": "2026-07-15T00:00:00+08:00",
        "reviewer": "locked-plan-initial-migration",
        "reason": "按冻结计划晋升 136/122/28 基线；保留 partial/unknown，不采用刷新来源自动覆盖",
        "selected_assertion_ids": selected,
        "rejected_assertion_ids": [],
        "entity_operations": [],
    }
    write_json(DECISIONS_ROOT / "initial-import.json", decision)
    digest = hashlib.sha256("\n".join(selected).encode("utf-8")).hexdigest()
    write_json(
        DECISIONS_ROOT / "initial-import.promotion.json",
        {**decision, "promotion_id": f"promotion:{digest}", "affected_derived": ["hif-runtime-json", "produce-decision-data"]},
    )
    return {
        "characters": len(canonical["characters"]),
        "produce_idol_cards": len(canonical["produce_idol_cards"]),
        "skill_cards": len(skills),
        "drinks": len(canonical["drinks"]),
        "assertions": len(assertions),
        "effect_versions": len(effects),
        "aliases": len(aliases),
    }


def _record_support(record: dict[str, Any], effects: dict[str, dict[str, Any]]) -> str:
    rank = {"unsupported": 0, "display_only": 0, "recognizable": 1, "modeled": 2, "executable": 3}
    values = [effects[item]["runtime_support"] for item in record.get("effect_version_ids", [])]
    return max(values, key=lambda item: rank[item], default="recognizable")


def _add_observed_cards(canonical: dict[str, list[dict[str, Any]]], assertions: list[dict[str, Any]], by_entity: dict[str, list[str]]) -> None:
    observed = (
        (
            "仕切り直し",
            "+",
            "体力消費2 手札をすべて引き直す 消費体力減少 スキルカード使用数追加+1",
            [
                {"op": "redraw_hand", "target": "self", "trigger": "on_use", "condition": None, "value": 0, "unit": "hand", "duration": None, "times": 1, "source_span": "手札をすべて引き直す"},
                {"op": "add_status", "target": "self", "trigger": "on_use", "condition": None, "value": 1, "unit": "stack", "duration": None, "times": 1, "status": "status:stamina_cost_reduction", "source_span": "消費体力減少"},
                {"op": "add_card_uses", "target": "self", "trigger": "on_use", "condition": None, "value": 1, "unit": "count", "duration": None, "times": 1, "source_span": "スキルカード使用数追加+1"},
            ],
            "executable",
        ),
        (
            "アイドル宣言",
            "+",
            "消費0 スキルカード使用数追加+1 スキルカードを2枚引く 消費体力減少",
            [
                {"op": "add_card_uses", "target": "self", "trigger": "on_use", "condition": None, "value": 1, "unit": "count", "duration": None, "times": 1, "source_span": "スキルカード使用数追加+1"},
                {"op": "draw_card", "target": "self", "trigger": "on_use", "condition": None, "value": 2, "unit": "card", "duration": None, "times": 1, "source_span": "スキルカードを2枚引く"},
                {"op": "add_status", "target": "self", "trigger": "on_use", "condition": None, "value": 1, "unit": "stack", "duration": None, "times": 1, "status": "status:stamina_cost_reduction", "source_span": "消費体力減少"},
            ],
            "executable",
        ),
        ("眠気", "base", "HIF実机灰卡；效果未采证", [{"op": "unknown", "raw": "HIF実机灰卡；效果未采证", "reason_code": "missing_in_game_effect_evidence"}], "unsupported"),
    )
    for name, tier, raw, ast, support in observed:
        entity_id = stable_entity_id("skill_card", "in_game:hif-round1", name)
        name_assertion = _synthetic_assertion(entity_id, "/names/ja-JP", name, "source:in-game-hif-round1", f"round1/{name}", support)
        effect_assertion = _synthetic_assertion(entity_id, f"/tiers/{tier}/effect", raw, "source:in-game-hif-round1", f"round1/{name}/effect", support)
        assertions.extend((name_assertion, effect_assertion))
        by_entity[entity_id].extend((name_assertion["assertion_id"], effect_assertion["assertion_id"]))
        effect_id = stable_entity_id("effect_version", "in_game:hif-round1", f"{name}:{tier}:2026-07-15")
        canonical["effect_versions"].append(
            {
                "schema_version": "2.0",
                "entity_id": effect_id,
                "raw_text": raw,
                "ast": ast,
                "unmatched_fragments": [raw] if support == "unsupported" else [],
                "parse_status": "partial" if support == "unsupported" else "complete",
                "parser_version": "hif-observed-round1/1",
                "runtime_support": support,
                "source_assertion_ids": [effect_assertion["assertion_id"]],
                "effective_from": "2026-07-15",
                "effective_to": None,
                "implementation_version": "hif-round1-fallback-v1" if support == "executable" else None,
            }
        )
        canonical["skill_cards"].append(
            {
                "schema_version": "2.0",
                "entity_id": entity_id,
                "legacy_ids": [],
                "names": {"ja-JP": name},
                "source_keys": [{"source_id": "source:in-game-hif-round1", "key": name}],
                "source_category": "scenario" if name != "眠気" else "trouble",
                "plan": "sense",
                "rarity": "",
                "tiers": [tier],
                "effect_version_ids": [effect_id],
                "canonical_assertion_ids": [name_assertion["assertion_id"], effect_assertion["assertion_id"]],
            }
        )


def _alias(target: str, alias_type: str, value: str, locale: str, evidence: list[str]) -> dict[str, Any]:
    key = f"{target}\0{alias_type}\0{locale}\0{value}"
    return {
        "schema_version": "2.0",
        "entity_id": stable_entity_id("alias", "catalog:initial-import", key),
        "target_entity_id": target,
        "alias_type": alias_type,
        "value": value,
        "match_key": normalize_match_key(value),
        "locale": locale,
        "profile": "hif-ja" if locale == "ja-JP" else None,
        "evidence_assertion_ids": sorted(evidence)[:8],
    }


def _synthetic_assertion(entity_id: str, path: str, value: Any, source: str, locator: str, support: str) -> dict[str, Any]:
    payload = f"{entity_id}\0{path}\0{value!r}\0{source}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "schema_version": "2.0",
        "assertion_id": f"assertion:{digest}",
        "entity_id": entity_id,
        "field_path": path,
        "value": value,
        "raw_value": value,
        "source_id": source,
        "source_locator": locator,
        "observed_at": "2026-07-15T00:00:00+08:00",
        "effective_from": None,
        "source_confidence": "project_controlled",
        "parse_status": "complete",
        "verification_status": "corroborated",
        "runtime_support": support,
        "parser_version": "data-catalog-v2-bootstrap/1",
        "content_hash": f"sha256:{digest}",
    }


def _legacy_records(path, key: str) -> list[dict[str, Any]]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"schema_version": "2.0", "runtime_support": "unsupported", "source_order": index, "legacy_payload": item}
        for index, item in enumerate(payload.get(key, []))
    ]
