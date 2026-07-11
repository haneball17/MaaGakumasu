"""HIF Pipeline 的离线结构校验。

MaaFramework 会在运行时解析 Pipeline；此模块在没有 Maa 工具链时提前发现
断开的跳转和未注册的 Custom Action。它只校验静态引用，不把通过校验等同于
页面识别或实机执行成功。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from collections.abc import Iterable, Mapping


_CUSTOM_ACTION_PATTERN = re.compile(r'@AgentServer\.custom_action\(["\']([^"\']+)["\']\)')
_JUMP_PREFIX = "[JumpBack]"


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


def load_registered_custom_actions(action_root: str | Path) -> frozenset[str]:
    """从 Python 装饰器提取已注册 Custom Action 名称。"""

    root = Path(action_root)
    names: set[str] = set()
    for path in root.rglob("*.py"):
        names.update(_CUSTOM_ACTION_PATTERN.findall(path.read_text(encoding="utf-8")))
    return frozenset(names)


def validate_hif_pipeline(
    hif_nodes: Mapping[str, object],
    *,
    known_nodes: Iterable[str],
    registered_custom_actions: Iterable[str],
) -> tuple[str, ...]:
    """返回所有静态问题；空元组表示结构引用完整。"""

    known = set(known_nodes)
    registered = set(registered_custom_actions)
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
        for target in _node_targets(node.get("next")):
            resolved = target.removeprefix(_JUMP_PREFIX)
            if resolved and resolved not in known:
                issues.append(f"{node_name}:missing_next_target:{target}")
        for target in _node_targets(node.get("on_error")):
            resolved = target.removeprefix(_JUMP_PREFIX)
            if resolved and resolved not in known:
                issues.append(f"{node_name}:missing_on_error_target:{target}")
    return tuple(issues)


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
