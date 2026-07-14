"""HIF 运行时统一数据目录。

实机 Action、OCR 词典、离线模拟器都应从这里读取相同的卡牌、饮料和日程资料，
避免旧 ``produce_decision_data.json`` 与 HIF 主数据发生漂移。
"""

from __future__ import annotations

import json
from typing import Any
from pathlib import Path
from functools import lru_cache
from dataclasses import field, dataclass


@dataclass(frozen=True, slots=True)
class HIFSkillCard:
    """用于决策与 OCR 的标准化技能卡资料。"""

    name_jp: str
    name_zh: str | None
    category: str
    is_lesson_once: bool
    stamina_cost: int | None
    focus_cost: int | None
    effect_text: str
    tags: frozenset[str]


@dataclass(frozen=True, slots=True)
class HIFDrink:
    """用于奖励与出牌决策的标准化 P 饮料资料。"""

    name_jp: str
    name_zh: str | None
    plan: str
    rarity: str
    consultation_cost: int | None
    effect_text: str
    tags: frozenset[str]


@dataclass(frozen=True, slots=True)
class HIFCustomPItem:
    """已验证名称的 HIF 自定义 P 道具阶段选项。"""

    name_jp: str
    plan: str
    stage: int
    priority: int
    tags: frozenset[str]
    note: str
    parents: frozenset[str] = frozenset()
    source_order: int = 0


@dataclass(frozen=True, slots=True)
class HIFScheduleDay:
    """本战准备阶段的一天固定骨架。``day_index`` 从 1 到 6。"""

    day_index: int
    action: str
    fallback: str | None
    constraint: str | None
    note: str


@dataclass(frozen=True, slots=True)
class HIFCatalog:
    """HIF 的版本化只读资料集合。"""

    skill_cards: dict[str, HIFSkillCard]
    drinks: dict[str, HIFDrink]
    custom_p_items: dict[str, HIFCustomPItem]
    schedule_days: dict[int, HIFScheduleDay]
    skill_source_updated_at: str
    drink_source_updated_at: str
    schedule_key: str

    @property
    def skill_names(self) -> tuple[str, ...]:
        return tuple(self.skill_cards)

    @property
    def drink_names(self) -> tuple[str, ...]:
        return tuple(self.drinks)

    def custom_p_item_names(
        self,
        plan: str,
        limit: int = 12,
        *,
        stage: int | None = None,
        parent: str | None = None,
    ) -> tuple[str, ...]:
        """按路线、阶段和来源顺序给出可 OCR 的 P 道具名称。

        ``priority`` 只能比较同一阶段、同一路线下的候选；不同阶段的道具
        不能按日文名称作为隐式决策规则。``parent`` 用于第二阶段根据第一
        阶段实际选择的分支收窄候选池。未提供 ``parent`` 时仍保留资料的
        人工排序，供只读 OCR 词典和影子模式使用。
        """

        items = (item for item in self.custom_p_items.values() if item.plan == plan)
        if stage is not None:
            items = (item for item in items if item.stage == stage)
        if parent is not None:
            items = (item for item in items if parent in item.parents)
        ranked = sorted(items, key=lambda item: (-item.priority, item.stage, item.source_order))
        return tuple(item.name_jp for item in ranked[:limit])

    def schedule_for_remaining_day(self, day_remaining: int | None) -> HIFScheduleDay | None:
        """将页面的“剩余 N 日”转换为从本战开始计数的日程日。"""

        if day_remaining is None or not 1 <= day_remaining <= 6:
            return None
        return self.schedule_days.get(7 - day_remaining)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def load_hif_catalog() -> HIFCatalog:
    """加载仓库随资源包发布的 HIF 数据，不联网、不隐式更新。"""

    data_root = project_root() / "assets" / "data"
    skills_payload = _load_json(data_root / "hif" / "skill_cards_master.json")
    translations_payload = _load_json(data_root / "hif" / "skill_cards_zh.json")
    drinks_payload = _load_json(data_root / "hif" / "drinks.json")
    p_items_payload = _load_json(data_root / "hif" / "custom_p_items.json")
    schedule_payload = _load_json(data_root / "scenarios" / "hif_schedule.json")

    translations = {
        row.get("name_jp", ""): row.get("name_zh")
        for row in translations_payload.get("cards", [])
        if row.get("name_jp")
    }
    skill_cards = {
        card.name_jp: card
        for raw in skills_payload.get("cards", [])
        if (card := _parse_skill_card(raw, translations.get(raw.get("name_jp", "")))) is not None
    }
    drinks = {
        drink.name_jp: drink
        for raw in drinks_payload.get("drinks", [])
        if (drink := _parse_drink(raw)) is not None
    }
    custom_p_items = {
        item.name_jp: item
        for source_order, raw in enumerate(p_items_payload.get("items", []))
        if (item := _parse_custom_p_item(raw, source_order)) is not None
    }
    schedule_days = {
        day.day_index: day
        for day_index, raw in schedule_payload.get("days", {}).items()
        if (day := _parse_schedule_day(day_index, raw)) is not None
    }

    if not skill_cards:
        raise ValueError("HIF 技能卡主数据为空")
    if not drinks:
        raise ValueError("HIF P 饮料主数据为空")
    if not custom_p_items:
        raise ValueError("HIF 自定义 P 道具数据为空")
    if set(schedule_days) != set(range(1, 7)):
        raise ValueError("HIF 本战日程必须覆盖第 1 至第 6 天")

    return HIFCatalog(
        skill_cards=skill_cards,
        drinks=drinks,
        custom_p_items=custom_p_items,
        schedule_days=schedule_days,
        skill_source_updated_at=str(skills_payload.get("updated_at", "")),
        drink_source_updated_at=str(drinks_payload.get("updated_at", "")),
        schedule_key=str(schedule_payload.get("scenario_key", "")),
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少 HIF 数据文件: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"HIF 数据文件根节点必须为对象: {path}")
    return payload


def _parse_skill_card(raw: Any, name_zh: str | None) -> HIFSkillCard | None:
    if not isinstance(raw, dict):
        return None
    name_jp = raw.get("name_jp")
    if not isinstance(name_jp, str) or not name_jp:
        return None

    tiers = raw.get("tiers", {})
    tier = tiers.get("無印") if isinstance(tiers, dict) else None
    if not isinstance(tier, dict) and isinstance(tiers, dict):
        tier = next((value for value in tiers.values() if isinstance(value, dict)), {})
    tier = tier if isinstance(tier, dict) else {}
    effect_text = str(tier.get("effect_raw", ""))
    return HIFSkillCard(
        name_jp=name_jp,
        name_zh=name_zh if isinstance(name_zh, str) else None,
        category=str(raw.get("page_category", "")),
        is_lesson_once=bool(raw.get("is_lesson_once", False)),
        stamina_cost=_int_or_none(tier.get("stamina_cost")),
        focus_cost=_int_or_none(tier.get("focus_cost")),
        effect_text=effect_text,
        tags=frozenset(_derive_tags(effect_text, name_jp)),
    )


def _parse_drink(raw: Any) -> HIFDrink | None:
    if not isinstance(raw, dict):
        return None
    name_jp = raw.get("name_jp")
    if not isinstance(name_jp, str) or not name_jp:
        return None
    effect_text = str(raw.get("raw_text", ""))
    cost = raw.get("cost", {})
    consultation_cost = cost.get("consultation") if isinstance(cost, dict) else None
    tags = set(_derive_tags(effect_text, name_jp))
    for effect in raw.get("effects", []):
        if isinstance(effect, dict) and isinstance(effect.get("tag"), str):
            tags.add(effect["tag"])
    return HIFDrink(
        name_jp=name_jp,
        name_zh=raw.get("name_zh") if isinstance(raw.get("name_zh"), str) else None,
        plan=str(raw.get("plan", "")),
        rarity=str(raw.get("rarity", "")),
        consultation_cost=_int_or_none(consultation_cost),
        effect_text=effect_text,
        tags=frozenset(tags),
    )


def _parse_custom_p_item(raw: Any, source_order: int) -> HIFCustomPItem | None:
    if not isinstance(raw, dict):
        return None
    name_jp = raw.get("name_jp")
    plan = raw.get("plan")
    if not isinstance(name_jp, str) or not name_jp or not isinstance(plan, str) or not plan:
        return None
    priority = _int_or_none(raw.get("priority"))
    stage = _int_or_none(raw.get("stage"))
    if priority is None or stage is None:
        return None
    tags = frozenset(tag for tag in raw.get("tags", []) if isinstance(tag, str))
    parents = frozenset(parent for parent in raw.get("parents", []) if isinstance(parent, str))
    return HIFCustomPItem(
        name_jp=name_jp,
        plan=plan,
        stage=stage,
        priority=priority,
        tags=tags,
        note=str(raw.get("note", "")),
        parents=parents,
        source_order=source_order,
    )


def _parse_schedule_day(day_index: Any, raw: Any) -> HIFScheduleDay | None:
    if not isinstance(raw, dict):
        return None
    try:
        parsed_day = int(day_index)
    except (TypeError, ValueError):
        return None
    action = raw.get("action")
    if not isinstance(action, str) or not action:
        return None
    fallback = raw.get("fallback")
    constraint = raw.get("constraint")
    return HIFScheduleDay(
        day_index=parsed_day,
        action=action,
        fallback=fallback if isinstance(fallback, str) else None,
        constraint=constraint if isinstance(constraint, str) else None,
        note=str(raw.get("note", "")),
    )


def _derive_tags(effect_text: str, name: str) -> set[str]:
    text = f"{name} {effect_text}"
    normalized_text = "".join(text.split())
    tags: set[str] = set()
    tag_rules = {
        "好調": "good_condition",
        "集中": "focus",
        "スキルカードを引く": "draw",
        "手札に移動": "draw",
        "使用数追加": "extra_play",
        "再演": "reprise",
        "体力回復": "recovery",
        "元気": "recovery",
        "パラメータ": "score",
        "消費体力": "stamina_cost",
        "カスタマイズ": "customize",
    }
    for marker, tag in tag_rules.items():
        if marker in text:
            tags.add(tag)
    if "好調" in normalized_text:
        tags.add("good_condition_grant" if "好調状態の場合、使用可" not in normalized_text else "good_condition_requirement")
    return tags


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
