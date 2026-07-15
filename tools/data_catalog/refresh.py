"""把当前 P 偶像卡来源提取为断言与待审差异，不自动晋升。"""

from __future__ import annotations

import hashlib
from collections import Counter

from .io import read_json, write_json, write_jsonl
from .paths import DATA_ROOT, CACHE_ROOT, REPORTS_ROOT, DECISIONS_ROOT, ASSERTIONS_ROOT
from .extract import extract_idol_cards_html
from .importers import import_existing_data


def extract_cached_idol_refresh() -> dict:
    manifest = read_json(DATA_ROOT / "catalog" / "manifests" / "seesaa-idols-2026-07-15.json")
    html_path = CACHE_ROOT / "idol_cards_source.html"
    if not html_path.is_file():
        raise FileNotFoundError("缺少缓存来源；先执行 fetch --source seesaa-idols")
    extracted = extract_idol_cards_html(
        html_path.read_text(encoding="utf-8"),
        observed_at=manifest["observed_at"],
        content_hash=manifest["content_hash"],
    )
    imported = import_existing_data(DATA_ROOT)
    baseline = {item["source_keys"]["legacy_card_name_jp"]: item for item in imported.records["produce_idol_cards"]}
    candidates = {item["provisional_match_key"]: item for item in extracted["records"]}
    added = sorted(candidates.keys() - baseline.keys())
    removed = sorted(baseline.keys() - candidates.keys())
    matched = sorted(candidates.keys() & baseline.keys())
    canonical_by_candidate = {candidates[key]["entity_id"]: baseline[key]["entity_id"] for key in matched}
    assertions = [_remap_assertion(item, canonical_by_candidate.get(item["entity_id"])) for item in extracted["assertions"]]

    changes: Counter[str] = Counter()
    changed_keys: list[str] = []
    for key in matched:
        before = baseline[key]
        after = candidates[key]
        before_profile = before["stat_profiles"][0]
        after_profile = after["stat_profiles"][0]
        changed = False
        for stat in ("vo", "da", "vi"):
            if before_profile[stat]["value"] != after_profile[stat]["value"]:
                changes[f"{stat}_value"] += 1
                changed = True
            if after_profile[stat]["bonus_percent"] is not None:
                changes[f"{stat}_independent_bonus_observed"] += 1
        if before_profile["stamina"] != after_profile["stamina"]:
            changes["stamina"] += 1
            changed = True
        if before["debut_date"] != after["debut_date"]:
            changes["debut_date"] += 1
            changed = True
        if changed:
            changed_keys.append(key)

    write_jsonl(ASSERTIONS_ROOT / "seesaa_idols_2026-07-15.jsonl", assertions)
    report = {
        "schema_version": "2.0",
        "source_id": "source:seesaawiki-idol-cards",
        "baseline_snapshot": "2026-05-18",
        "observed_at": manifest["observed_at"],
        "source_item_count": len(candidates),
        "matched": len(matched),
        "added": len(added),
        "removed": len(removed),
        "added_provisional_keys": added,
        "removed_legacy_keys": removed,
        "changed_existing_keys": changed_keys,
        "change_counts": dict(sorted(changes.items())),
        "assertions": len(assertions),
        "warnings": extracted["warnings"],
        "promotion_status": "deferred",
        "reason_codes": ["missing_stable_source_id", "new_entries_missing_rarity_context", "manual_identity_review_required"],
    }
    write_json(REPORTS_ROOT / "seesaa_idols_refresh_2026-07-15.json", report)
    write_json(
        DECISIONS_ROOT / "seesaa-idols-2026-07-15.review.json",
        {
            "schema_version": "2.0",
            "decision_id": "decision:seesaa-idols-2026-07-15-deferred",
            "decided_at": "2026-07-15T23:34:56+08:00",
            "disposition": "deferred",
            "reason": "当前页面未提供稳定条目 ID，新增项缺失稀有度上下文；保留断言和三属性独立加成，禁止按名称自动晋升或合并",
            "affected_assertion_ids": sorted(item["assertion_id"] for item in assertions),
            "entity_operations": [],
        },
    )
    return report


def _remap_assertion(assertion: dict, entity_id: str | None) -> dict:
    if entity_id is None:
        return assertion
    output = dict(assertion)
    output["entity_id"] = entity_id
    payload = f"{entity_id}\0{output['field_path']}\0{output['value']!r}\0{output['content_hash']}"
    output["assertion_id"] = f"assertion:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
    return output
