"""P 饮料解析(drink_effects.json → 引擎可执行视图)。

饮料与技能卡效果同构(同一 ProduceExamEffect 行结构),统一走 engine.execute_effects;
区别:无成本/不占使用数/不移动牌区。A3 假设:P 饮料为 produce 级资源跨 Round 持有。
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from functools import lru_cache

from agent.hif.roundsim.deck import CardSpec

_DRINKS_PATH = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "drink_effects.json"


@lru_cache(maxsize=1)
def _load_drinks() -> dict[str, dict]:
    if not _DRINKS_PATH.exists():
        return {}
    raw = json.loads(_DRINKS_PATH.read_text(encoding="utf-8"))
    return {unicodedata.normalize("NFKC", d["name_jp"]): d for d in raw.get("drinks", []) if d.get("in_pool")}


def resolve_drink(name: str) -> CardSpec:
    """饮料名 → CardSpec 视图(仅 effects 有意义;预检在执行时由 engine 支持面看守)。"""
    drink = _load_drinks().get(unicodedata.normalize("NFKC", name))
    if drink is None:
        raise KeyError(f"P 饮料「{name}」不在效果池(drink_effects.json)")
    return CardSpec(
        name=drink["name_jp"],
        tier="無印",
        card_id=drink.get("drink_id", ""),
        stamina=0,
        force_stamina=0,
        cost_type=None,
        cost_value=None,
        effects=tuple(drink.get("effects") or []),
        move_position="Grave",
        is_lesson_once=False,
        rarity=drink.get("rarity", ""),
    )
