"""卡牌元数据查表（HIF 技能卡消耗查询）。

从原 Maa-gakumas-bot 仓库 app/data/card_meta.py 移植：
- 数据源改为本仓库 assets/data/hif/skill_cards.json（3 张关键卡的消耗数据）
- 决策大脑（play.py）据此查询「お姉さんの感覚=6体力」「自然体の魅力=5集中」
- lru_cache 避免重复读盘；模糊匹配兜底档位符号（+ / 無印）

本模块零 maafw 依赖，仅依赖标准库，可离线单测。
"""

from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass

# assets/data/hif/skill_cards.json 相对仓库根的路径。
# hand_meta.py 位于 agent/hif/decisions/，上溯 4 级到仓库根，再进 assets/data/hif。
_DATA_PATH = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "skill_cards.json"


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
    """加载 skill_cards.json，返回 {卡名: 原始dict}（lru_cache 避免重复读盘）。

    数据文件缺失时返回空表（如测试环境无数据），调用方应处理 None 回退默认值。
    """
    if not _DATA_PATH.exists():
        return {}
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    # 用 name 做主键（含档位符号的完整名），同时建 base_name 索引方便按基础名查。
    table: dict[str, dict] = {}
    for card in raw:
        table[card["name"]] = card
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
