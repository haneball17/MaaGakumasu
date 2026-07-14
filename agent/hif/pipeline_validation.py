"""HIF Pipeline 的离线结构校验。

MaaFramework 会在运行时解析 Pipeline；此模块在没有 Maa 工具链时提前发现
断开的跳转和未注册的 Custom Action。它只校验静态引用，不把通过校验等同于
页面识别或实机执行成功。
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from collections.abc import Mapping, Iterable

_CUSTOM_ACTION_PATTERN = re.compile(r'@AgentServer\.custom_action\(["\']([^"\']+)["\']\)')
_CUSTOM_RECOGNITION_PATTERN = re.compile(r'@AgentServer\.custom_recognition\(["\']([^"\']+)["\']\)')
_JUMP_PREFIX = "[JumpBack]"
_COVERAGE_CATEGORIES = frozenset({"legacy_entry", "router", "observation", "transition", "stateful_choice", "terminal"})
_COVERAGE_EVIDENCE = frozenset({"observed", "derived", "unobserved"})
_COVERAGE_TERMINATIONS = frozenset({"safe_stop", "return_router_or_safe_stop", "action_internal_stop", "terminal_stop"})
_REQUIRED_COVERAGE_SCENARIOS = frozenset({"success", "refusal", "postcondition_failure"})


def load_pipeline_nodes(pipeline_root: str | Path) -> dict[str, dict]:
    """加载目录内所有 Pipeline 节点，名称重复即拒绝。"""

    root = Path(pipeline_root)
    nodes: dict[str, dict] = {}
    for path in sorted(root.glob("*.json")):
        payload = _load_jsonc(path)
        if not isinstance(payload, dict):
            raise ValueError(f"Pipeline 文件必须是对象: {path}")
        for name, node in payload.items():
            if not isinstance(name, str) or not isinstance(node, dict):
                raise ValueError(f"Pipeline 节点无效: {path}:{name}")
            if name in nodes:
                raise ValueError(f"Pipeline 节点重名: {name}")
            nodes[name] = node
    return nodes


def load_hif_coverage_manifest(path: str | Path) -> dict:
    """加载 HIF 节点覆盖矩阵；其数据只用于离线测试和审计。"""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"HIF 覆盖矩阵无效: {path}")
    return payload


def load_registered_custom_actions(action_root: str | Path) -> frozenset[str]:
    """从 Python 装饰器提取已注册 Custom Action 名称。"""

    root = Path(action_root)
    names: set[str] = set()
    for path in root.rglob("*.py"):
        names.update(_CUSTOM_ACTION_PATTERN.findall(path.read_text(encoding="utf-8")))
    return frozenset(names)


def load_registered_custom_recognitions(recognition_root: str | Path) -> frozenset[str]:
    """从 Python 装饰器提取已注册 Custom Recognition 名称。"""

    root = Path(recognition_root)
    names: set[str] = set()
    for path in root.rglob("*.py"):
        names.update(_CUSTOM_RECOGNITION_PATTERN.findall(path.read_text(encoding="utf-8")))
    return frozenset(names)


def validate_hif_pipeline(
    hif_nodes: Mapping[str, object],
    *,
    known_nodes: Iterable[str],
    registered_custom_actions: Iterable[str],
    registered_custom_recognitions: Iterable[str] = (),
) -> tuple[str, ...]:
    """返回所有静态问题；空元组表示结构引用完整。"""

    known = set(known_nodes)
    registered = set(registered_custom_actions)
    registered_recognitions = set(registered_custom_recognitions)
    issues: list[str] = []
    for node_name, node in hif_nodes.items():
        if not isinstance(node_name, str) or not isinstance(node, Mapping):
            issues.append(f"invalid_node:{node_name}")
            continue
        action = node.get("action")
        if isinstance(action, Mapping) and action.get("type") == "Custom":
            param = action.get("param")
            custom_name = param.get("custom_action") if isinstance(param, Mapping) else None
            if not isinstance(custom_name, str) or not custom_name:
                issues.append(f"{node_name}:missing_custom_action")
            elif custom_name not in registered:
                issues.append(f"{node_name}:unregistered_custom_action:{custom_name}")
        recognition = node.get("recognition")
        if isinstance(recognition, Mapping) and recognition.get("type") == "Custom":
            param = recognition.get("param")
            custom_name = param.get("custom_recognition") if isinstance(param, Mapping) else None
            if not isinstance(custom_name, str) or not custom_name:
                issues.append(f"{node_name}:missing_custom_recognition")
            elif custom_name not in registered_recognitions:
                issues.append(f"{node_name}:unregistered_custom_recognition:{custom_name}")
        for target in _node_targets(node.get("next")):
            resolved = target.removeprefix(_JUMP_PREFIX)
            if resolved and resolved not in known:
                issues.append(f"{node_name}:missing_next_target:{target}")
        for target in _node_targets(node.get("on_error")):
            resolved = target.removeprefix(_JUMP_PREFIX)
            if resolved and resolved not in known:
                issues.append(f"{node_name}:missing_on_error_target:{target}")
    return tuple(issues)


def validate_hif_coverage_manifest(hif_nodes: Mapping[str, object], manifest: Mapping[str, object]) -> tuple[str, ...]:
    """检查覆盖矩阵与当前 HIF 节点集合严格一致且每项都声明三类场景。"""

    issues: list[str] = []
    if manifest.get("schema_version") != 1:
        return ("manifest:unsupported_schema_version",)
    matrix = manifest.get("coverage_matrix")
    if not isinstance(matrix, list) or not matrix:
        return ("manifest:missing_coverage_matrix",)

    declared: set[str] = set()
    for index, group in enumerate(matrix):
        label = f"matrix[{index}]"
        if not isinstance(group, Mapping):
            issues.append(f"{label}:invalid_group")
            continue
        category = group.get("category")
        if category not in _COVERAGE_CATEGORIES:
            issues.append(f"{label}:invalid_category:{category}")
        evidence = group.get("evidence")
        if evidence not in _COVERAGE_EVIDENCE:
            issues.append(f"{label}:invalid_evidence:{evidence}")
        termination = group.get("termination")
        if termination not in _COVERAGE_TERMINATIONS:
            issues.append(f"{label}:invalid_termination:{termination}")
        scenarios = group.get("scenarios")
        if not isinstance(scenarios, Mapping):
            issues.append(f"{label}:invalid_scenarios")
        else:
            missing_scenarios = _REQUIRED_COVERAGE_SCENARIOS - set(scenarios)
            for scenario in sorted(missing_scenarios):
                issues.append(f"{label}:missing_scenario:{scenario}")
            for scenario in _REQUIRED_COVERAGE_SCENARIOS & set(scenarios):
                if not _valid_coverage_scenario(scenarios[scenario]):
                    issues.append(f"{label}:invalid_scenario:{scenario}")
        test_modules = group.get("test_modules")
        if not isinstance(test_modules, list) or not all(isinstance(item, str) and item.startswith("tests/") for item in test_modules):
            issues.append(f"{label}:invalid_test_modules")
        nodes = group.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            issues.append(f"{label}:invalid_nodes")
            continue
        for node_name in nodes:
            if not isinstance(node_name, str) or not node_name:
                issues.append(f"{label}:invalid_node_name")
                continue
            if node_name in declared:
                issues.append(f"manifest:duplicate_node:{node_name}")
            declared.add(node_name)

    expected = set(hif_nodes)
    for node_name in sorted(expected - declared):
        issues.append(f"manifest:missing_node:{node_name}")
    for node_name in sorted(declared - expected):
        issues.append(f"manifest:unknown_node:{node_name}")
    return tuple(issues)


def validate_hif_recognition_contracts(
    hif_nodes: Mapping[str, object],
    *,
    image_root: str | Path,
    frame_size: tuple[int, int] = (720, 1280),
) -> tuple[str, ...]:
    """校验 HIF OCR/模板识别的离线契约，不执行 Maa 识别。"""

    root = Path(image_root)
    issues: list[str] = []
    for node_name, node in hif_nodes.items():
        if not isinstance(node_name, str) or not isinstance(node, Mapping):
            continue
        recognition = node.get("recognition")
        if not isinstance(recognition, Mapping):
            continue
        kind = recognition.get("type")
        param = recognition.get("param")
        if not isinstance(param, Mapping):
            continue
        roi = param.get("roi")
        if roi is not None and not _valid_roi(roi, frame_size):
            issues.append(f"{node_name}:invalid_roi")
        if kind == "OCR":
            expected = param.get("expected")
            patterns = expected if isinstance(expected, list) else [expected]
            if not patterns or not all(isinstance(pattern, str) and pattern for pattern in patterns):
                issues.append(f"{node_name}:invalid_ocr_expected")
            else:
                for pattern in patterns:
                    try:
                        re.compile(pattern)
                    except re.error:
                        issues.append(f"{node_name}:invalid_ocr_pattern:{pattern}")
        if kind == "TemplateMatch":
            templates = param.get("template")
            values = templates if isinstance(templates, list) else [templates]
            if not values or not all(isinstance(template, str) and template for template in values):
                issues.append(f"{node_name}:invalid_template")
            else:
                for template in values:
                    if not (root / template).is_file():
                        issues.append(f"{node_name}:missing_template:{template}")
    return tuple(issues)


def find_unreachable_hif_nodes(
    hif_nodes: Mapping[str, object],
    *,
    entry_nodes: Iterable[str],
    dynamic_targets: Iterable[str] = (),
) -> frozenset[str]:
    """返回从正式入口或声明的动态目标均不可达的 HIF 节点。"""

    known = set(hif_nodes)
    reachable = {name for name in (*entry_nodes, *dynamic_targets) if name in known}
    pending = list(reachable)
    while pending:
        node_name = pending.pop()
        node = hif_nodes.get(node_name)
        if not isinstance(node, Mapping):
            continue
        for target in (*_node_targets(node.get("next")), *_node_targets(node.get("on_error"))):
            resolved = target.removeprefix(_JUMP_PREFIX)
            if resolved in known and resolved not in reachable:
                reachable.add(resolved)
                pending.append(resolved)
    return frozenset(known - reachable)


def _node_targets(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    values = raw if isinstance(raw, list) else [raw]
    targets: list[str] = []
    for value in values:
        if isinstance(value, str):
            targets.append(value)
        elif isinstance(value, Mapping) and isinstance(value.get("name"), str):
            targets.append(value["name"])
    return tuple(targets)


def _valid_coverage_scenario(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, Mapping) and isinstance(value.get("na"), str) and bool(value["na"].strip())


def _valid_roi(raw: object, frame_size: tuple[int, int]) -> bool:
    if not isinstance(raw, list) or len(raw) != 4:
        return False
    try:
        x, y, width, height = (int(value) for value in raw)
    except (TypeError, ValueError):
        return False
    return x >= 0 and y >= 0 and width > 0 and height > 0 and x + width <= frame_size[0] and y + height <= frame_size[1]


def _load_jsonc(path: Path) -> object:
    """读取仓库 Pipeline 使用的 JSONC（行/块注释与尾逗号）。"""

    source = path.read_text(encoding="utf-8")
    try:
        return json.loads(source)
    except json.JSONDecodeError:
        return json.loads(_remove_jsonc_trivia(source))


def _remove_jsonc_trivia(source: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if in_string:
            output.append(current)
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == '"':
                in_string = False
            index += 1
            continue
        if current == '"':
            in_string = True
            output.append(current)
            index += 1
            continue
        if current == "/" and following == "/":
            index = source.find("\n", index)
            if index < 0:
                break
            output.append("\n")
            index += 1
            continue
        if current == "/" and following == "*":
            closing = source.find("*/", index + 2)
            if closing < 0:
                raise ValueError("JSONC block comment is not closed")
            output.extend("\n" for char in source[index:closing + 2] if char == "\n")
            index = closing + 2
            continue
        output.append(current)
        index += 1

    without_comments = "".join(output)
    return re.sub(r",\s*([}\]])", r"\1", without_comments)
