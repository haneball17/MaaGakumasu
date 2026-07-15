"""消费显式人工裁决，生成新的内存 canonical 与晋升审计记录。"""

from __future__ import annotations

import copy
import json
import hashlib
from typing import Any, Iterable


def promote_assertions(
    records: Iterable[dict[str, Any]],
    assertions: Iterable[dict[str, Any]],
    decision: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """应用一份显式裁决；不接受隐式“采用全部最新”。"""

    reason = decision.get("reason")
    decided_at = decision.get("decided_at")
    selected = list(decision.get("selected_assertion_ids", []))
    rejected = list(decision.get("rejected_assertion_ids", []))
    if not isinstance(reason, str) or not reason.strip() or not isinstance(decided_at, str) or not decided_at:
        raise ValueError("晋升裁决必须包含非空 reason 和 decided_at")
    if not selected:
        raise ValueError("晋升裁决必须显式选择至少一个 assertion")
    if set(selected) & set(rejected):
        raise ValueError("同一 assertion 不能同时 selected 和 rejected")

    assertion_map = {str(item.get("assertion_id")): item for item in assertions}
    unknown = sorted((set(selected) | set(rejected)) - assertion_map.keys())
    if unknown:
        raise ValueError(f"裁决引用未知 assertion：{unknown}")
    chosen_by_field: dict[tuple[str, str], dict[str, Any]] = {}
    for assertion_id in selected:
        assertion = assertion_map[assertion_id]
        key = (str(assertion.get("entity_id")), str(assertion.get("field_path")))
        if key in chosen_by_field:
            raise ValueError(f"同一实体字段只能选择一个 assertion：{key}")
        chosen_by_field[key] = assertion

    output = [copy.deepcopy(item) for item in records]
    record_map = {str(item.get("entity_id")): item for item in output}
    for (entity_id, field_path), assertion in chosen_by_field.items():
        if entity_id not in record_map:
            raise ValueError(f"canonical 中不存在实体：{entity_id}")
        _set_pointer(record_map[entity_id], field_path, copy.deepcopy(assertion.get("value")))

    audit_body = {
        "decision_id": decision.get("decision_id"),
        "selected_assertion_ids": sorted(selected),
        "rejected_assertion_ids": sorted(rejected),
        "reason": reason,
        "decided_at": decided_at,
        "reviewer": decision.get("reviewer"),
        "entity_operations": decision.get("entity_operations", []),
    }
    digest = hashlib.sha256(
        json.dumps(audit_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    audit_body["promotion_id"] = f"promotion:{digest}"
    return output, audit_body


def _set_pointer(document: dict[str, Any], pointer: str, value: Any) -> None:
    if not pointer.startswith("/") or pointer == "/":
        raise ValueError(f"晋升只支持具体 JSON Pointer 字段：{pointer}")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    target: Any = document
    for part in parts[:-1]:
        if isinstance(target, list):
            target = target[int(part)]
        elif isinstance(target, dict):
            if part not in target:
                target[part] = {}
            target = target[part]
        else:
            raise ValueError(f"JSON Pointer 中间节点不是容器：{pointer}")
    last = parts[-1]
    if isinstance(target, list):
        target[int(last)] = value
    elif isinstance(target, dict):
        target[last] = value
    else:
        raise ValueError(f"JSON Pointer 目标父节点不是容器：{pointer}")
