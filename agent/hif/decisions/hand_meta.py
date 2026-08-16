"""卡牌元数据查表（HIF 技能卡消耗/效果查询）。

数据源两层（実機 2026-08-15 接线：121 卡 master 表上线）：
1. assets/data/hif/skill_cards.json——莉波关键 3 卡（含人工校对 effect_summary，优先）
2. assets/data/hif/skill_cards_master.json——seesaawiki 121 卡全表（name_jp + 四档
   tiers{stamina_cost/focus_cost/effect_raw}），未命中小表时按档位符号查 tier

决策大脑（play.py）据此查询「お姉さんの感覚=6体力」等；lru_cache 避免重复读盘；
模糊匹配兜底档位符号（+ / 無印）。

本模块零 maafw 依赖，仅依赖标准库，可离线单测。
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass

# 数据文件相对仓库根路径（hand_meta.py 位于 agent/hif/decisions/，上溯 4 级）。
_DATA_DIR = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif"
_KEY_CARDS_PATH = _DATA_DIR / "skill_cards.json"
_MASTER_PATH = _DATA_DIR / "skill_cards_master.json"
_EFFECTS_POOL_PATH = _DATA_DIR / "skill_card_effects.json"

# 卡名尾缀的档位符号 → master tiers 键。
_TIER_KEYS = {"": "無印", "+": "+", "++": "++", "+++": "+++"}


def _norm_key(name: str) -> str:
    """查表键 NFKC 归一(与 card_dict 词典同空间,全半角&差异统一)。"""
    return unicodedata.normalize("NFKC", name)


@dataclass(slots=True, frozen=True)
class CardMeta:
    """单张卡的元数据（查表得到；master 表来源时按档位 tier 取消耗）。"""

    name: str
    base_name: str
    is_lesson_once: bool
    stamina_cost: int | None
    focus_cost: int | None
    effect_summary: str


@lru_cache(maxsize=1)
def _load_skill_cards() -> dict[str, dict]:
    """加载 skill_cards.json，返回 {卡名: 原始dict}。

    数据文件缺失时返回空表（如测试环境无数据），调用方应处理 None 回退默认值。
    """
    if not _KEY_CARDS_PATH.exists():
        return {}
    raw = json.loads(_KEY_CARDS_PATH.read_text(encoding="utf-8"))
    # 用 name 做主键（含档位符号的完整名），同时建 base_name 索引方便按基础名查。
    table: dict[str, dict] = {}
    for card in raw:
        table[_norm_key(card["name"])] = card
    return table


@lru_cache(maxsize=1)
def _load_skill_master() -> dict[str, dict]:
    """加载 skill_cards_master.json（121 卡），返回 {name_jp: 原始dict}。

    键做 NFKC 归一（wiki 半角& 与 diff 全角＆ 统一到半角），与 card_dict 词典同一命名空间。
    """
    if not _MASTER_PATH.exists():
        return {}
    raw = json.loads(_MASTER_PATH.read_text(encoding="utf-8"))
    return {_norm_key(card["name_jp"]): card for card in raw.get("cards", [])}


@lru_cache(maxsize=1)
def _load_effects_pool() -> dict[str, dict]:
    """加载 skill_card_effects.json（流派过滤池，A1 产物），返回 {基础名: 原始dict}。

    池口径（设计文档 5.5）：planType ∈ {Plan1, Common} 且剔除 is_idol_exclusive
    （非莉波偶像固有卡；hrnm 莉波固有与 s_card 支援卡固有保留）。
    每卡含四档 tiers 的结构化效果数值（tag/value/turn），OCR 词典与评分模型共同消费。
    键做 NFKC 归一（diff 侧全角＆ → 半角&），与 card_dict 词典同一命名空间。
    """
    if not _EFFECTS_POOL_PATH.exists():
        return {}
    raw = json.loads(_EFFECTS_POOL_PATH.read_text(encoding="utf-8"))
    return {
        _norm_key(card["name_jp"]): card
        for card in raw.get("cards", [])
        if not card.get("is_idol_exclusive")
    }


def _split_tier_suffix(card_name: str) -> tuple[str, str]:
    """拆分卡名的档位尾缀：'始まりの合図++' -> ('始まりの合図', '++')。"""
    base = card_name.rstrip("+")
    suffix = card_name[len(base):]
    return base, suffix if suffix in _TIER_KEYS else ""


def _meta_from_master(card_name: str) -> CardMeta | None:
    """按 master 表查卡；档位符号选 tier，消耗/效果取该档值。"""
    master = _load_skill_master()
    base, suffix = _split_tier_suffix(card_name)
    card = master.get(base)
    if card is None:
        return None
    tier = card.get("tiers", {}).get(_TIER_KEYS[suffix]) or card.get("tiers", {}).get("無印", {})
    return CardMeta(
        name=card_name,
        base_name=base,
        is_lesson_once=card.get("is_lesson_once", False),
        stamina_cost=tier.get("stamina_cost"),
        focus_cost=tier.get("focus_cost"),
        effect_summary=tier.get("effect_raw", ""),
    )


def get_card_meta(card_name: str) -> CardMeta | None:
    """按卡名查元数据。未命中返回 None（调用方应处理 None，回退默认值）。

    Args:
        card_name: 卡名（如「お姉さんの感覚」「始まりの合図++」），可含档位符号。
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
    if card is not None:
        return CardMeta(
            name=card["name"],
            base_name=card.get("base_name", card["name"]),
            is_lesson_once=card.get("is_lesson_once", False),
            stamina_cost=card.get("stamina_cost"),
            focus_cost=card.get("focus_cost"),
            effect_summary=card.get("effect_summary", ""),
        )
    # 小表未命中 → 121 卡 master 表（含档位 tier）。
    return _meta_from_master(card_name)


def get_stamina_cost(card_name: str) -> int | None:
    """便捷查询：该卡的体力消耗。未命中返回 None。"""
    meta = get_card_meta(card_name)
    return meta.stamina_cost if meta else None


def get_focus_cost(card_name: str) -> int | None:
    """便捷查询：该卡的集中消耗。未命中返回 None。"""
    meta = get_card_meta(card_name)
    return meta.focus_cost if meta else None
