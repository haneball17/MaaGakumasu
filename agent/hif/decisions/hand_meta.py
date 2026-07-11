"""卡牌元数据查表（HIF 技能卡消耗查询）。

从原 Maa-gakumas-bot 仓库 app/data/card_meta.py 移植：
- 数据源为本仓库 ``assets/data/hif/skill_cards_master.json``（121 张卡）
- 决策大脑据此查询卡牌消耗，避免关键卡手工表与 OCR 词典发生漂移
- lru_cache 避免重复读盘；模糊匹配兜底档位符号（+ / 無印）

本模块零 maafw 依赖，仅依赖标准库，可离线单测。
"""

from __future__ import annotations

from functools import lru_cache
from dataclasses import dataclass

from agent.hif.catalog import load_hif_catalog


@dataclass(slots=True, frozen=True)
class CardMeta:
    """单张卡的元数据（从 skill_cards.json 查表得到）。"""

    name: str
    base_name: str
    is_lesson_once: bool
    stamina_cost: int | None
    focus_cost: int | None
    effect_summary: str


@lru_cache(maxsize=1)
def _load_skill_cards() -> dict[str, dict]:
    """从 HIF 统一主数据建立卡牌元数据表。

    旧实现只读取三张关键卡，导致 OCR 词典和奖励决策与主数据脱节。现在统一
    使用 ``skill_cards_master.json`` 的 121 张卡；缺失的卡仍由调用方按 None 降级。
    """

    table: dict[str, dict] = {}
    for card in load_hif_catalog().skill_cards.values():
        table[card.name_jp] = {
            "name": card.name_jp,
            "base_name": card.name_jp,
            "is_lesson_once": card.is_lesson_once,
            "stamina_cost": card.stamina_cost,
            "focus_cost": card.focus_cost,
            "effect_summary": card.effect_text,
        }
    return table


def get_card_meta(card_name: str) -> CardMeta | None:
    """按卡名查元数据。未命中返回 None（调用方应处理 None，回退默认值）。

    Args:
        card_name: 卡名（如「お姉さんの感覚」「自然体の魅力」），可含档位符号。
    """
    table = _load_skill_cards()
    card = table.get(card_name)
    if card is None:
        # 尝试按 base_name 模糊匹配（去掉档位符号）。
        base = card_name.rstrip("+")
        for k, v in table.items():
            if v.get("base_name") == base:
                card = v
                break
    if card is None:
        return None
    return CardMeta(
        name=card["name"],
        base_name=card.get("base_name", card["name"]),
        is_lesson_once=card.get("is_lesson_once", False),
        stamina_cost=card.get("stamina_cost"),
        focus_cost=card.get("focus_cost"),
        effect_summary=card.get("effect_summary", ""),
    )


def get_stamina_cost(card_name: str) -> int | None:
    """便捷查询：该卡的体力消耗。未命中返回 None。"""
    meta = get_card_meta(card_name)
    return meta.stamina_cost if meta else None


def get_focus_cost(card_name: str) -> int | None:
    """便捷查询：该卡的集中消耗。未命中返回 None。"""
    meta = get_card_meta(card_name)
    return meta.focus_cost if meta else None
