"""生成分维度、确定性的 catalog 审计报告。"""

from __future__ import annotations

from collections import Counter, defaultdict

from .io import read_json, read_jsonl, write_json
from .paths import REPORTS_ROOT, OVERLAYS_ROOT, CANONICAL_ROOT, MANIFESTS_ROOT, ASSERTIONS_ROOT
from .reconcile import assertion_conflicts
from .semantics import scan_hif_required_semantics


def report_catalog() -> dict:
    characters = read_json(CANONICAL_ROOT / "characters.json")
    idols = read_jsonl(CANONICAL_ROOT / "produce_idol_cards.jsonl")
    skills = read_jsonl(CANONICAL_ROOT / "skill_cards.jsonl")
    drinks = read_jsonl(CANONICAL_ROOT / "drinks.jsonl")
    effects = read_jsonl(CANONICAL_ROOT / "effect_versions.jsonl")
    aliases = read_jsonl(CANONICAL_ROOT / "aliases.jsonl")
    assertions = []
    for path in sorted(ASSERTIONS_ROOT.glob("*.jsonl")):
        assertions.extend(read_jsonl(path))
    overlay = read_json(OVERLAYS_ROOT / "hif.json")

    wiki_skills = [item for item in skills if any(key.get("source_id") == "source:seesaawiki-skill-cards-2026-07-01" for key in item["source_keys"])]
    translated_wiki = sum("zh-CN" in item["names"] for item in wiki_skills)
    parse_counts = Counter(item["parse_status"] for item in effects)
    unknown_nodes = sum(node.get("op") == "unknown" for item in effects for node in item["ast"])
    support_counts = Counter(item["runtime_support"] for item in overlay["entries"])

    coverage = {
        "schema_version": "2.0",
        "entities": {"characters": len(characters), "produce_idol_cards": len(idols), "skill_cards": len(skills), "wiki_skill_cards": len(wiki_skills), "drinks": len(drinks)},
        "field_facts": {"assertions": len(assertions), "produce_cards_with_stat_profile": sum(bool(item["stat_profiles"]) for item in idols), "produce_cards_with_legacy_shared_bonus": sum("legacy_shared_bonus" in item["stat_profiles"][0] for item in idols)},
    }
    parsing = {"schema_version": "2.0", "effect_versions": len(effects), "parse_status": dict(sorted(parse_counts.items())), "unknown_nodes": unknown_nodes, "unmatched_fragments": sum(len(item["unmatched_fragments"]) for item in effects)}
    translations = {"schema_version": "2.0", "wiki_skill_cards": len(wiki_skills), "wiki_skill_translated_zh_cn": translated_wiki, "wiki_skill_translation_missing": sorted(item["names"]["ja-JP"] for item in wiki_skills if "zh-CN" not in item["names"]), "drink_translation_zh_cn": sum("zh-CN" in item["names"] for item in drinks)}
    ocr = _ocr_report(aliases)
    hif = {"schema_version": "2.0", "entries": len(overlay["entries"]), "runtime_support": dict(sorted(support_counts.items())), "required_semantics": len(overlay["required_semantics"]), "executable_effect_versions": sum(item["runtime_support"] == "executable" for item in effects)}
    required = {"schema_version": "2.0", "generated_from_code": True, "items": [{"semantic_type": item.semantic_type, "key": item.key, "required_support": item.required_support, "sources": list(item.sources)} for item in scan_hif_required_semantics()]}
    conflicts = {"schema_version": "2.0", "conflicts": assertion_conflicts(assertions)}
    freshness = {"schema_version": "2.0", "sources": [read_json(path) for path in sorted(MANIFESTS_ROOT.glob("*.json"))], "reason_codes": []}
    compatibility = read_json(REPORTS_ROOT / "compatibility_diff.json") if (REPORTS_ROOT / "compatibility_diff.json").is_file() else {"differences": [{"reason_code": "compatibility_not_checked"}]}

    reports = {
        "coverage.json": coverage,
        "parsing.json": parsing,
        "translations.json": translations,
        "ocr.json": ocr,
        "hif_support.json": hif,
        "required_semantics.json": required,
        "conflicts.json": conflicts,
        "freshness.json": freshness,
    }
    for name, payload in reports.items():
        write_json(REPORTS_ROOT / name, payload)
    summary = {
        "schema_version": "2.0",
        "coverage": coverage["entities"],
        "conflicts": len(conflicts["conflicts"]),
        "parse_status": parsing["parse_status"],
        "unknown_nodes": unknown_nodes,
        "translations": {"wiki_skill_zh_cn": f"{translated_wiki}/{len(wiki_skills)}", "drink_zh_cn": f"{translations['drink_translation_zh_cn']}/{len(drinks)}"},
        "ocr_collisions": len(ocr["collisions"]),
        "hif_runtime_support": hif["runtime_support"],
        "compatibility_differences": len(compatibility["differences"]),
        "required_semantics": len(required["items"]),
    }
    write_json(REPORTS_ROOT / "summary.json", summary)
    return summary


def _ocr_report(aliases: list[dict]) -> dict:
    profile = [item for item in aliases if item.get("profile") == "hif-ja"]
    grouped: dict[str, set[str]] = defaultdict(set)
    for item in profile:
        grouped[item["match_key"]].add(item["target_entity_id"])
    collisions = [{"match_key": key, "target_entity_ids": sorted(values)} for key, values in sorted(grouped.items()) if len(values) > 1]
    return {"schema_version": "2.0", "profile": "hif-ja", "aliases": len(profile), "unique_match_keys": len(grouped), "collisions": collisions}
