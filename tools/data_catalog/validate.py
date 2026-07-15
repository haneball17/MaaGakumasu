"""统一目录 ingest 与 HIF release 校验。"""

from __future__ import annotations

import json
from typing import Any
from pathlib import Path
from collections import defaultdict

from .io import read_json, read_jsonl
from .paths import SCHEMAS_ROOT, OVERLAYS_ROOT, CANONICAL_ROOT, ASSERTIONS_ROOT
from .schema import require_supported_schema_version
from .effects import EXECUTABLE_OPS
from .semantics import validate_hif_semantic_gate, scan_hif_required_semantics

_FILES = {
    "character": (CANONICAL_ROOT / "characters.json", "json"),
    "produce-idol-card": (CANONICAL_ROOT / "produce_idol_cards.jsonl", "jsonl"),
    "skill-card": (CANONICAL_ROOT / "skill_cards.jsonl", "jsonl"),
    "drink": (CANONICAL_ROOT / "drinks.jsonl", "jsonl"),
    "term": (CANONICAL_ROOT / "terms.jsonl", "jsonl"),
    "alias": (CANONICAL_ROOT / "aliases.jsonl", "jsonl"),
    "effect-version": (CANONICAL_ROOT / "effect_versions.jsonl", "jsonl"),
    "assertion": (ASSERTIONS_ROOT / "initial_import.jsonl", "jsonl"),
    "scenario-overlay": (OVERLAYS_ROOT / "hif.json", "single"),
}


def validate_catalog(profile: str = "ingest") -> list[dict[str, str]]:
    if profile not in {"ingest", "hif-release"}:
        raise ValueError(f"未知校验 profile：{profile}")
    issues: list[dict[str, str]] = []
    loaded: dict[str, list[dict[str, Any]]] = {}
    validators = _validators()
    for schema_name, (path, mode) in _FILES.items():
        paths = sorted(ASSERTIONS_ROOT.glob("*.jsonl")) if schema_name == "assertion" else [path]
        if not paths:
            issues.append(_issue("missing_catalog_file", str(path), "required file is absent"))
            continue
        values: list[dict[str, Any]] = []
        locations: list[str] = []
        for current_path in paths:
            if not current_path.is_file():
                issues.append(_issue("missing_catalog_file", str(current_path), "required file is absent"))
                continue
            current_values = [read_json(current_path)] if mode == "single" else (read_json(current_path) if mode == "json" else read_jsonl(current_path))
            if not isinstance(current_values, list):
                current_values = [current_values]
            values.extend(current_values)
            locations.extend(f"{current_path}:{index + 1}" for index in range(len(current_values)))
        loaded[schema_name] = values
        validator = validators[schema_name]
        for index, value in enumerate(values):
            try:
                require_supported_schema_version(value)
                errors = sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
            except Exception as exc:  # 未知主版本也统一进入稳定报告
                issues.append(_issue("schema_version_rejected", locations[index], str(exc)))
                continue
            for error in errors:
                pointer = "/".join(map(str, error.absolute_path))
                issues.append(_issue("schema_validation_failed", f"{locations[index]}/{pointer}", error.message))
    if issues:
        return sorted(issues, key=_issue_key)
    issues.extend(_reference_issues(loaded))
    issues.extend(_collision_issues(loaded["alias"]))
    issues.extend(_baseline_issues(loaded))
    if profile == "hif-release":
        issues.extend(_hif_release_issues(loaded))
    return sorted(issues, key=_issue_key)


def _validators():
    from jsonschema import Draft202012Validator

    schemas = {path.name.removesuffix(".schema.json"): json.loads(path.read_text(encoding="utf-8")) for path in SCHEMAS_ROOT.glob("*.schema.json")}
    return {name: Draft202012Validator(schema) for name, schema in schemas.items()}


def _reference_issues(loaded: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    characters = {item["entity_id"] for item in loaded["character"]}
    effects = {item["entity_id"] for item in loaded["effect-version"]}
    entities = characters | effects
    for kind in ("produce-idol-card", "skill-card", "drink"):
        entities.update(item["entity_id"] for item in loaded[kind])
    assertions = {item["assertion_id"] for item in loaded["assertion"]}
    for item in loaded["produce-idol-card"]:
        if item["character_id"] not in characters:
            issues.append(_issue("broken_character_reference", item["entity_id"], item["character_id"]))
    for kind in ("skill-card", "drink"):
        for item in loaded[kind]:
            for effect_id in item["effect_version_ids"]:
                if effect_id not in effects:
                    issues.append(_issue("broken_effect_reference", item["entity_id"], effect_id))
    for kind in ("character", "produce-idol-card", "skill-card", "drink", "term"):
        for item in loaded[kind]:
            missing = sorted(set(item.get("canonical_assertion_ids", ())) - assertions)
            for assertion_id in missing:
                issues.append(_issue("broken_assertion_reference", item["entity_id"], assertion_id))
    for alias in loaded["alias"]:
        if alias["target_entity_id"] not in entities:
            issues.append(_issue("broken_alias_target", alias["entity_id"], alias["target_entity_id"]))
    return issues


def _collision_issues(aliases: list[dict[str, Any]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str | None, str], set[str]] = defaultdict(set)
    for alias in aliases:
        if alias["alias_type"] == "ocr_error" or alias.get("profile") == "hif-ja":
            grouped[(alias["locale"], alias.get("profile"), alias["match_key"])].add(alias["target_entity_id"])
    return [
        _issue("ocr_alias_collision", ":".join(str(part) for part in key), ",".join(sorted(targets)))
        for key, targets in sorted(grouped.items())
        if len(targets) > 1
    ]


def _baseline_issues(loaded: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    seesaa_skills = sum(any(key.get("source_id") == "source:seesaawiki-skill-cards-2026-07-01" for key in item["source_keys"]) for item in loaded["skill-card"])
    expected = {"produce-idol-card": 136, "drink": 28}
    issues = [
        _issue("baseline_count_regression", kind, f"expected>={count},actual={len(loaded[kind])}")
        for kind, count in expected.items()
        if len(loaded[kind]) < count
    ]
    if seesaa_skills != 122:
        issues.append(_issue("baseline_count_regression", "seesaa-skill-card", f"expected=122,actual={seesaa_skills}"))
    return issues


def _hif_release_issues(loaded: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    effects = {item["entity_id"]: item for item in loaded["effect-version"]}
    rank = {"unsupported": 0, "display_only": 0, "recognizable": 1, "modeled": 2, "executable": 3}
    runtime: dict[tuple[str, str], str] = {}
    match_keys: dict[tuple[str, str], str] = {}
    for kind, records in (("skill_card", loaded["skill-card"]), ("drink", loaded["drink"])):
        for item in records:
            name = item["names"].get("ja-JP")
            supports = [effects[effect_id]["runtime_support"] for effect_id in item["effect_version_ids"]]
            support = max(supports, key=lambda value: rank[value])
            runtime[(kind, name)] = "recognizable" if kind == "skill_card" and name == "眠気" else support
            runtime[("skill_card_effect", name)] = support
            match_keys[(kind, name)] = next((alias["match_key"] for alias in loaded["alias"] if alias["target_entity_id"] == item["entity_id"] and alias["locale"] == "ja-JP"), name)
    for requirement in scan_hif_required_semantics():
        if requirement.semantic_type == "machine_tag":
            runtime[("machine_tag", requirement.key)] = "modeled"
    issues = [
        _issue(item.reason_code, f"{item.semantic_type}:{item.key}", item.detail)
        for item in validate_hif_semantic_gate(scan_hif_required_semantics(), runtime, match_keys=match_keys)
    ]
    required_executable = {
        requirement.key
        for requirement in scan_hif_required_semantics()
        if requirement.semantic_type in {"skill_card", "skill_card_effect"} and requirement.required_support == "executable"
    }
    for item in loaded["skill-card"]:
        if item["names"].get("ja-JP") not in required_executable:
            continue
        versions = [effects[effect_id] for effect_id in item["effect_version_ids"] if effects[effect_id]["runtime_support"] == "executable"]
        if not versions or any(version["parse_status"] != "complete" or any(node.get("op") == "unknown" for node in version["ast"]) for version in versions):
            issues.append(_issue("required_effect_incomplete", item["entity_id"], item["names"].get("ja-JP", "")))
        for version in versions:
            unsupported_ops = sorted({node.get("op") for node in version["ast"] if node.get("op") not in EXECUTABLE_OPS})
            if unsupported_ops:
                issues.append(_issue("executable_ast_op_unimplemented", version["entity_id"], ",".join(map(str, unsupported_ops))))
    return issues


def _issue(reason: str, location: str, detail: str) -> dict[str, str]:
    return {"reason_code": reason, "location": location, "detail": detail}


def _issue_key(item: dict[str, str]) -> tuple[str, str, str]:
    return item["reason_code"], item["location"], item["detail"]
