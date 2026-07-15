"""从当前 HIF 代码与配置生成运行时必需语义清单。

本模块只做静态读取，不导入 ``agent``，因此不会触发 MaaFramework 或运行时
数据加载。清单以代码中的白名单、精确选卡规则和奖励配置为准，而不是复制
计划文档中的人工列表。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from collections.abc import Mapping, Iterable

_SUPPORT_RANK = {"unsupported": 0, "recognizable": 1, "modeled": 2, "executable": 3}


@dataclass(frozen=True, slots=True, order=True)
class RequiredSemantic:
    """一项由当前运行时代码实际引用的 HIF 语义。"""

    semantic_type: str
    key: str
    required_support: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True, order=True)
class SemanticGateIssue:
    """HIF 发布门槛中的稳定、可机器判断的问题。"""

    reason_code: str
    semantic_type: str
    key: str
    detail: str


def scan_hif_required_semantics(project_root: str | Path | None = None) -> tuple[RequiredSemantic, ...]:
    """扫描仓库当前代码/配置并返回确定性排序的 HIF 必需语义。"""

    root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[2]
    found: dict[tuple[str, str], tuple[str, set[str]]] = {}

    def add(semantic_type: str, key: object, support: str, source: str) -> None:
        if not isinstance(key, str) or not key or support not in _SUPPORT_RANK:
            return
        identity = semantic_type, key
        previous = found.get(identity)
        if previous is None:
            found[identity] = support, {source}
            return
        previous_support, sources = previous
        strongest = support if _SUPPORT_RANK[support] > _SUPPORT_RANK[previous_support] else previous_support
        sources.add(source)
        found[identity] = strongest, sources

    _scan_route_scoring(root, add)
    _scan_exact_card_rules(root, add)
    _scan_reward_priorities(root, add)
    _scan_machine_tags(root, add)

    return tuple(
        RequiredSemantic(kind, key, support, tuple(sorted(sources)))
        for (kind, key), (support, sources) in sorted(found.items())
    )


def validate_hif_semantic_gate(
    requirements: Iterable[RequiredSemantic],
    runtime_support: Mapping[tuple[str, str] | str, str],
    *,
    match_keys: Mapping[tuple[str, str] | str, str] | None = None,
) -> tuple[SemanticGateIssue, ...]:
    """校验 required 语义的支持度，以及目标 profile 内的归一化碰撞。

    ``unsupported`` 是有意保留的安全停止项，不要求提升。其余项目缺失、支持
    状态未知或低于门槛时均失败。``match_keys`` 只比较同一实体类型，避免技能
    卡与饮料同名被误报为碰撞。
    """

    ordered = tuple(sorted(requirements))
    issues: list[SemanticGateIssue] = []
    for requirement in ordered:
        if requirement.required_support == "unsupported":
            continue
        identity = requirement.semantic_type, requirement.key
        actual = _mapping_get(runtime_support, identity)
        if actual not in _SUPPORT_RANK:
            issues.append(
                SemanticGateIssue(
                    "required_semantic_unknown",
                    requirement.semantic_type,
                    requirement.key,
                    f"runtime_support={actual!r}",
                )
            )
        elif _SUPPORT_RANK[actual] < _SUPPORT_RANK[requirement.required_support]:
            issues.append(
                SemanticGateIssue(
                    "required_semantic_insufficient",
                    requirement.semantic_type,
                    requirement.key,
                    f"required={requirement.required_support},actual={actual}",
                )
            )

    if match_keys:
        collisions: dict[tuple[str, str], set[str]] = defaultdict(set)
        for requirement in ordered:
            if requirement.semantic_type not in {"skill_card", "drink"}:
                continue
            identity = requirement.semantic_type, requirement.key
            normalized = _mapping_get(match_keys, identity)
            if isinstance(normalized, str) and normalized:
                collisions[(requirement.semantic_type, normalized)].add(requirement.key)
        for (semantic_type, normalized), keys in sorted(collisions.items()):
            if len(keys) > 1:
                issues.append(
                    SemanticGateIssue(
                        "normalization_collision",
                        semantic_type,
                        normalized,
                        ",".join(sorted(keys)),
                    )
                )
    return tuple(sorted(issues))


def _scan_route_scoring(root: Path, add) -> None:
    path = root / "agent" / "hif" / "route_scoring" / "catalog.py"
    tree = _parse(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "CardSpec":
            continue
        arguments = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        card_id_node = arguments.get("card_id", node.args[0] if node.args else None)
        effect = arguments.get("effect", node.args[7] if len(node.args) >= 8 else None)
        card_id = _literal(card_id_node)
        if effect is None:
            continue
        support = "unsupported" if isinstance(effect, ast.Constant) and effect.value is None else "executable"
        add("skill_card_effect", card_id, support, _source(root, path, node.lineno))


def _scan_exact_card_rules(root: Path, add) -> None:
    path = root / "agent" / "hif" / "decisions" / "round1_fallback.py"
    tree = _parse(path)
    constants = _module_constants(tree)
    for name, value in constants.items():
        if name.endswith("_HAND") or name == "_OBSERVED_RECOVERY_HAND":
            for card_name in _strings(value):
                add("skill_card", card_name, "recognizable", _source(root, path, value.lineno))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "CardAction" or len(node.args) < 2:
            continue
        selected = _resolve_string(node.args[1], constants)
        add("skill_card", selected, "executable", _source(root, path, node.lineno))


def _scan_reward_priorities(root: Path, add) -> None:
    python_paths = (
        root / "agent" / "hif" / "route_planner.py",
        root / "agent" / "hif" / "presets.py",
    )
    for path in python_paths:
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                names = _assignment_names(node)
                value = node.value
                for name in names:
                    if "SKILL_PRIORITY" in name:
                        for item in _strings(value):
                            add("skill_card", item, "modeled", _source(root, path, node.lineno))
                    elif "DRINK_PRIORITY" in name:
                        for item in _strings(value):
                            add("drink", item, "modeled", _source(root, path, node.lineno))
            if isinstance(node, ast.Call) and _call_name(node.func) == "HIFPreset":
                for keyword in node.keywords:
                    semantic_type = {"skill_reward_names": "skill_card", "drink_name_priority": "drink"}.get(keyword.arg)
                    if semantic_type:
                        for item in _strings(keyword.value):
                            add(semantic_type, item, "modeled", _source(root, path, keyword.value.lineno))

    profile_dir = root / "assets" / "data" / "hif" / "profiles"
    for path in sorted(profile_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for drink_name in payload.get("p_drink_priority", []):
            add("drink", drink_name, "modeled", _source(root, path))


def _scan_machine_tags(root: Path, add) -> None:
    path = root / "agent" / "hif" / "route_planner.py"
    tree = _parse(path)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        names = _assignment_names(node)
        if not any("TAG" in name or name == "tag_weights" for name in names):
            continue
        if isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                tag = _literal(key) if key is not None else None
                add("machine_tag", tag, "modeled", _source(root, path, node.lineno))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_constants(tree: ast.Module) -> dict[str, ast.AST]:
    result: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in _assignment_names(node):
                result[name] = node.value
    return result


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return tuple(target.id for target in targets if isinstance(target, ast.Name))


def _strings(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Call) and _call_name(node.func) in {"frozenset", "set", "tuple", "list"} and node.args:
        return _strings(node.args[0])
    value = _literal(node)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _literal(node: ast.AST | None):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _resolve_string(node: ast.AST, constants: Mapping[str, ast.AST]) -> str | None:
    direct = _literal(node)
    if isinstance(direct, str):
        return direct
    if isinstance(node, ast.Name) and node.id in constants:
        value = _literal(constants[node.id])
        return value if isinstance(value, str) else None
    return None


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _mapping_get(mapping: Mapping[tuple[str, str] | str, str], identity: tuple[str, str]) -> str | None:
    if identity in mapping:
        return mapping[identity]
    return mapping.get(f"{identity[0]}:{identity[1]}")


def _source(root: Path, path: Path, line: int | None = None) -> str:
    relative = path.relative_to(root).as_posix()
    return f"{relative}:{line}" if line is not None else relative
