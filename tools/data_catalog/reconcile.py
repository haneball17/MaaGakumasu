"""生成候选资料与 canonical 之间可审计、确定性的字段差异。"""

from __future__ import annotations

import json
import hashlib
from typing import Any, Iterable


def reconcile_records(
    current: Iterable[dict[str, Any]],
    candidates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按 ``entity_id`` 比较记录，保留新增、删除及所有叶字段变化。"""

    old = {str(item["entity_id"]): item for item in current}
    new = {str(item["entity_id"]): item for item in candidates}
    changes: list[dict[str, Any]] = []
    for entity_id in sorted(old.keys() | new.keys()):
        if entity_id not in old:
            changes.append(_change(entity_id, "/", None, new[entity_id], "entity_added"))
            continue
        if entity_id not in new:
            changes.append(_change(entity_id, "/", old[entity_id], None, "entity_removed"))
            continue
        before = dict(_leaf_values(old[entity_id]))
        after = dict(_leaf_values(new[entity_id]))
        for field_path in sorted(before.keys() | after.keys()):
            if before.get(field_path) == after.get(field_path):
                continue
            changes.append(
                _change(
                    entity_id,
                    field_path,
                    before.get(field_path),
                    after.get(field_path),
                    _category(field_path, before.get(field_path), after.get(field_path)),
                )
            )
    return changes


def assertion_conflicts(assertions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """报告同一实体字段的不同断言；不按来源时间静默选胜者。"""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for assertion in assertions:
        key = (str(assertion.get("entity_id")), str(assertion.get("field_path")))
        grouped.setdefault(key, []).append(assertion)
    conflicts = []
    for (entity_id, field_path), items in sorted(grouped.items()):
        values: dict[str, Any] = {}
        for item in items:
            token = json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            values[token] = item.get("value")
        if len(values) > 1:
            conflicts.append(
                {
                    "entity_id": entity_id,
                    "field_path": field_path,
                    "reason_code": "conflicting_assertions",
                    "assertion_ids": sorted(str(item.get("assertion_id")) for item in items),
                    "values": [values[key] for key in sorted(values)],
                }
            )
    return conflicts


def _change(entity_id: str, path: str, before: Any, after: Any, category: str) -> dict[str, Any]:
    payload = json.dumps([entity_id, path, before, after], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "change_id": f"change:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}",
        "entity_id": entity_id,
        "field_path": path,
        "before": before,
        "after": after,
        "category": category,
        "requires_promotion": True,
    }


def _category(path: str, before: Any, after: Any) -> str:
    if path.endswith("parse_status") and before == "complete" and after != "complete":
        return "parse_regression"
    if path.startswith("/source_keys"):
        return "source_key"
    if path.startswith("/names") or isinstance(before, str) or isinstance(after, str):
        return "text"
    if "/ast" in path or "/effect" in path:
        return "ast"
    if isinstance(before, (int, float)) or isinstance(after, (int, float)):
        return "numeric"
    return "field"


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
