"""从 v2 canonical 离线生成旧运行时兼容产物。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from pathlib import Path

from .io import read_json, read_jsonl, write_json
from .paths import DATA_ROOT, CACHE_ROOT, REPORTS_ROOT, CANONICAL_ROOT

_TARGETS = {
    "skill_cards_master": DATA_ROOT / "hif" / "skill_cards_master.json",
    "skill_cards_zh": DATA_ROOT / "hif" / "skill_cards_zh.json",
    "drinks": DATA_ROOT / "hif" / "drinks.json",
    "produce_decision_data": DATA_ROOT / "produce_decision_data.json",
    "skill_cards_compact": DATA_ROOT / "skill_cards_compact.json",
}


def build_derived() -> dict[str, Any]:
    metadata = read_json(CANONICAL_ROOT / "compatibility_metadata.json")
    skills = read_jsonl(CANONICAL_ROOT / "skill_cards.jsonl")
    drinks = read_jsonl(CANONICAL_ROOT / "drinks.jsonl")
    idol_cards = read_jsonl(CANONICAL_ROOT / "produce_idol_cards.jsonl")
    legacy_p_items = read_jsonl(CANONICAL_ROOT / "legacy_p_items.jsonl")

    skill_rows = sorted(
        (item["compatibility"] for item in skills if item.get("compatibility", {}).get("raw_record")),
        key=lambda item: item["source_order"],
    )
    translations = sorted(
        (item["compatibility"] for item in skills if item.get("compatibility", {}).get("translation_row")),
        key=lambda item: item["translation_order"],
    )
    drink_rows = sorted((item["compatibility"] for item in drinks), key=lambda item: item["source_order"])
    decision_idols = [
        item["compatibility"]["decision_row"]
        for item in sorted(idol_cards, key=lambda item: item["compatibility"]["source_order"])
    ]
    compact = metadata["skill_cards_compact"]
    p_items = []
    for wrapper in sorted(legacy_p_items, key=lambda item: item["source_order"]):
        raw = wrapper["legacy_payload"]
        p_items.append(
            {
                "p_item_id": raw.get("p_item_id", ""),
                "name_jp": raw.get("names", {}).get("jp", ""),
                "name_zh": raw.get("names", {}).get("zh", ""),
                "scenario": raw.get("scenario", ""),
                "tags": raw.get("derived_tags", []) or [],
            }
        )
    return {
        "skill_cards_master": {**metadata["skill_cards_master"], "cards": [item["raw_record"] for item in skill_rows]},
        "skill_cards_zh": {**metadata["skill_cards_zh"], "cards": [item["translation_row"] for item in translations]},
        "drinks": {**metadata["drinks"], "drinks": [item["raw_record"] for item in drink_rows]},
        "produce_decision_data": {
            **metadata["produce_decision_data"],
            "idol_cards": decision_idols,
            "skill_cards": compact,
            "p_items": p_items,
        },
        "skill_cards_compact": compact,
    }


def derive_catalog(*, check: bool = False, write_runtime: bool = False) -> list[dict[str, str]]:
    """始终写确定性预览；可选语义校验或更新运行时产物。"""

    generated = build_derived()
    preview_root = CACHE_ROOT / "derived"
    for name, payload in generated.items():
        write_json(preview_root / f"{name}.json", payload)
    differences: list[dict[str, str]] = []
    for name, target in _TARGETS.items():
        expected = generated[name]
        actual = read_json(target)
        if _without_dynamic(actual) != _without_dynamic(expected):
            differences.append({"reason_code": "derived_semantic_difference", "artifact": name, "detail": str(target)})
        elif write_runtime:
            write_json(target, expected)
    report = {
        "schema_version": "2.0",
        "dynamic_metadata_allowlist": ["/updated_at", "/保存时间"],
        "differences": differences,
        "artifacts": sorted(generated),
    }
    write_json(REPORTS_ROOT / "compatibility_diff.json", report)
    if check:
        return differences
    return differences


def _without_dynamic(value: Any) -> Any:
    value = deepcopy(value)
    if isinstance(value, dict):
        value.pop("updated_at", None)
        value.pop("保存时间", None)
    return value
