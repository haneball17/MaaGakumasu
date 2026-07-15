"""效果文本的保守解析与 HIF 白名单状态转移。

解析器遵循失败关闭：未被完整理解的文本一定保留为 ``unknown``，不会仅凭
关键词生成可执行语义。当前执行器只覆盖现有 HIF 单步白名单所需的节点。
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from dataclasses import dataclass

_SPACE = re.compile(r"[\s・]+")
_PARAMETER = re.compile(r"パラメータ\s*\+\s*(\d+)")
_STATUS = {
    "好調": "status:good_condition",
    "絶好調": "status:excellent_condition",
    "集中": "status:focus",
    "元気": "status:vitality",
}
EXECUTABLE_OPS = frozenset({"add_parameter", "gain_vitality", "add_status", "register_trigger", "add_card_uses", "draw_card", "move_card", "redraw_hand"})


@dataclass(frozen=True, slots=True)
class EffectParseResult:
    ast: tuple[dict[str, Any], ...]
    parse_status: str
    unmatched: tuple[str, ...]


def _node(op: str, source_span: str, **values: Any) -> dict[str, Any]:
    return {
        "op": op,
        "target": "self",
        "trigger": "on_use",
        "condition": None,
        "value": values.pop("value", None),
        "unit": values.pop("unit", None),
        "duration": values.pop("duration", None),
        "times": values.pop("times", 1),
        "source_span": source_span,
        **values,
    }


def parse_effect_text(raw: str) -> EffectParseResult:
    """保守提取通用片段，其余原文作为一个 unknown 节点保留。"""

    text = str(raw or "").strip()
    if not text:
        unknown = {"op": "unknown", "raw": "", "reason_code": "empty_source_text"}
        return EffectParseResult((unknown,), "failed", ("",))

    nodes: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    for match in _PARAMETER.finditer(text):
        nodes.append(_node("add_parameter", match.group(0), value=int(match.group(1)), unit="flat"))
        spans.append(match.span())

    for marker, status_code in _STATUS.items():
        pattern = re.compile(rf"{marker}\s*\+?\s*(\d+)(?:\s*ターン)?")
        for match in pattern.finditer(text):
            value = int(match.group(1))
            if marker == "元気":
                nodes.append(_node("gain_vitality", match.group(0), value=value, unit="flat"))
            else:
                duration = value if "ターン" in match.group(0) else None
                nodes.append(_node("add_status", match.group(0), value=value, unit="stack" if duration is None else "turn", duration=duration, status=status_code))
            spans.append(match.span())

    for match in re.finditer(r"スキルカード使用数追加\s*\+\s*(\d+)", text):
        nodes.append(_node("add_card_uses", match.group(0), value=int(match.group(1)), unit="count"))
        spans.append(match.span())

    remainder = list(text)
    for start, end in spans:
        remainder[start:end] = " " * (end - start)
    unmatched_text = _SPACE.sub("", "".join(remainder))
    # 只把纯分隔和明确的连接词视为已消费；任何实质语义均保留。
    unmatched_text = unmatched_text.strip("、。()（）+-：:")
    unmatched: list[str] = []
    if unmatched_text:
        unmatched.append(unmatched_text)
        nodes.append({"op": "unknown", "raw": unmatched_text, "reason_code": "unsupported_grammar"})
    return EffectParseResult(tuple(nodes), "partial" if unmatched else "complete", tuple(unmatched))


def verified_hif_effect(name: str, tier: str, raw: str) -> EffectParseResult | None:
    """返回当前实机/严格评分白名单已验证的效果，不扩大白名单。"""

    normalized = _SPACE.sub("", raw)
    blessing = {"無印": 26, "+": 40}
    if name == "祝福" and tier in blessing:
        expected = f"パラメータ+{blessing[tier]}好調1ターン"
        if normalized != expected:
            return None
        ast = (
            _node("add_parameter", f"パラメータ+{blessing[tier]}", value=blessing[tier], unit="flat"),
            _node("add_status", "好調 1ターン", value=1, unit="turn", duration=1, status="status:good_condition"),
        )
        return EffectParseResult(ast, "complete", ())
    if name == "演出計画" and tier == "無印":
        if "絶好調3ターン" not in normalized or "アクティブスキルカード使用時" not in normalized or "固定元気+2" not in normalized:
            return None
        ast = (
            _node("add_status", "絶好調 3ターン", value=3, unit="turn", duration=3, status="status:excellent_condition"),
            _node(
                "register_trigger",
                "以降、アクティブスキルカード使用時、固定元気+2",
                value=2,
                unit="flat",
                trigger="after_active_card",
                effect="effect:gain_fixed_vitality",
                duration="rest_of_lesson",
            ),
        )
        return EffectParseResult(ast, "complete", ())
    if name == "話題沸騰" and tier == "+":
        if "好調が8ターン以上の場合、使用可" not in normalized or "パラメータ+50" not in normalized or "2.5倍適用" not in normalized:
            return None
        condition = {"status": "status:good_condition", "minimum": 8}
        ast = (
            {**_node("add_parameter", "パラメータ+50（好調効果を2.5倍適用）", value=50, unit="flat", modifier={"status": "status:good_condition", "multiplier": 2.5}), "condition": condition},
            _node("add_status", "パラメータ上昇量増加30%（1ターン）", value=30, unit="percent", duration=1, status="status:parameter_gain_up"),
        )
        return EffectParseResult(ast, "complete", ())
    if name == "天賦の才" and tier == "無印":
        markers = ("好調3ターン", "集中+2", "スキルカード（SSR）3枚を山札の一番上に移動", "次のターン、スキルカード使用数追加+1")
        if any(marker not in normalized for marker in markers):
            return None
        ast = (
            _node("add_status", "好調 3ターン", value=3, unit="turn", duration=3, status="status:good_condition"),
            _node("add_status", "集中 +2", value=2, unit="stack", status="status:focus"),
            _node("move_card", "SSR 3枚を山札の一番上に移動", value=3, unit="card", source_zone="deck_or_discard", destination_zone="deck_top", card_filter={"rarity": "SSR"}, selection="random"),
            _node("add_card_uses", "次のターン、使用数追加 +1", value=1, unit="count", trigger="next_turn_start"),
        )
        return EffectParseResult(ast, "complete", ())
    return None


def modeled_hif_drink_effect(name: str, raw: str) -> EffectParseResult | None:
    """当前奖励排序实际依赖的三种饮料效果，保持 modeled 而非 executable。"""

    normalized = _SPACE.sub("", raw)
    if name == "パワフル漢方ドリンク" and "固有スキルカード1枚を手札に移動" in normalized:
        return EffectParseResult(
            (
                _node("move_card", "固有スキルカード1枚を手札に移動", value=1, unit="card", source_zone="deck_or_discard", destination_zone="hand", card_filter={"source_category": "produce_idol"}, selection="random"),
                _node("add_status", "消費体力減少 3ターン", value=1, unit="stack", duration=3, status="status:stamina_cost_reduction"),
            ),
            "complete",
            (),
        )
    if name == "センブリソーダ" and "スキルカードを2枚引く" in normalized and "5ターン" in normalized:
        return EffectParseResult(
            (
                _node("add_status", "パラメータ上昇量増加10%（5ターン）", value=10, unit="percent", duration=5, status="status:parameter_gain_up"),
                _node("draw_card", "スキルカードを2枚引く", value=2, unit="card"),
                _node("register_trigger", "5ターンの間、ターン開始後、スキルカードを引く", value=1, unit="card", trigger="turn_start", effect="effect:draw_card", duration=5),
            ),
            "complete",
            (),
        )
    if name == "初星黒酢" and "スキルカードを選択し、手札に移動" in normalized and "消費体力を0にする（2回）" in normalized:
        return EffectParseResult(
            (
                _node("move_card", "スキルカードを選択し、手札に移動", value=1, unit="card", source_zone="deck_or_discard", destination_zone="hand", selection="chosen"),
                _node("set_next_card_cost", "次に使用したスキルカードの消費体力を0にする（2回）", value=0, unit="stamina", times=2),
                _node("add_status", "消費体力増加 1ターン", value=1, unit="stack", duration=1, status="status:stamina_cost_increase"),
            ),
            "complete",
            (),
        )
    return None


def apply_executable_ast(state: dict[str, Any], ast: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """执行已支持 AST；条件拒绝、边界钳制和未知节点均失败关闭。"""

    result = deepcopy(state)
    result.setdefault("parameter", 0)
    result.setdefault("vitality", 0)
    result.setdefault("statuses", {})
    result.setdefault("triggers", [])
    for node in ast:
        condition = node.get("condition")
        if condition and not _condition_matches(result, condition):
            raise ValueError("effect_condition_rejected")
        op = node.get("op")
        value = node.get("value")
        if not isinstance(value, int) or value < 0:
            raise ValueError("invalid_effect_value")
        if op == "add_parameter":
            result["parameter"] += value
        elif op == "gain_vitality":
            result["vitality"] += value
        elif op == "add_status":
            status = node.get("status")
            if not isinstance(status, str) or not status:
                raise ValueError("invalid_status_code")
            result["statuses"][status] = result["statuses"].get(status, 0) + value
        elif op == "register_trigger":
            result["triggers"].append({key: node[key] for key in ("trigger", "effect", "value", "duration")})
        elif op == "add_card_uses":
            if node.get("trigger") == "next_turn_start":
                result["triggers"].append({"trigger": "next_turn_start", "effect": "effect:add_card_uses", "value": value, "duration": None})
            else:
                result["card_uses"] = result.get("card_uses", 0) + value
        elif op == "draw_card":
            deck = result.setdefault("deck", [])
            hand = result.setdefault("hand", [])
            drawn = deck[:value]
            del deck[: len(drawn)]
            hand.extend(drawn)
        elif op == "redraw_hand":
            deck = result.setdefault("deck", [])
            hand = result.setdefault("hand", [])
            discard = result.setdefault("discard", [])
            count = len(hand)
            discard.extend(hand)
            hand.clear()
            drawn = deck[:count]
            del deck[: len(drawn)]
            hand.extend(drawn)
        elif op == "move_card":
            _move_cards(result, node, value)
        else:
            raise ValueError(f"unsupported_effect_op:{op}")
    return result


def _condition_matches(state: dict[str, Any], condition: dict[str, Any]) -> bool:
    code = condition.get("status")
    minimum = condition.get("minimum")
    return isinstance(code, str) and isinstance(minimum, int) and state.get("statuses", {}).get(code, 0) >= minimum


def _move_cards(state: dict[str, Any], node: dict[str, Any], count: int) -> None:
    source_zone = node.get("source_zone")
    destination = node.get("destination_zone")
    zones = ["deck", "discard"] if source_zone == "deck_or_discard" else [str(source_zone)]
    candidates: list[tuple[str, Any]] = []
    rarity = node.get("card_filter", {}).get("rarity")
    category = node.get("card_filter", {}).get("source_category")
    for zone in zones:
        for card in state.setdefault(zone, []):
            if rarity and (not isinstance(card, dict) or card.get("rarity") != rarity):
                continue
            if category and (not isinstance(card, dict) or card.get("source_category") != category):
                continue
            candidates.append((zone, card))
    chosen = candidates[:count]
    if len(chosen) < count:
        raise ValueError("insufficient_move_candidates")
    moved = []
    for zone, card in chosen:
        state[zone].remove(card)
        moved.append(card)
    if destination == "deck_top":
        state.setdefault("deck", [])[0:0] = moved
    elif destination == "hand":
        state.setdefault("hand", []).extend(moved)
    else:
        raise ValueError(f"unsupported_destination_zone:{destination}")
