"""HIF 用户预设的纯数据与候选排序逻辑。

覆盖链（grill 2026-08-15 定案）：GUI 输入（custom_action_param 平铺参数）
> decision_override.json 文件 > 倾向基准 > preset 默认；点名覆盖语义（只改点名项）。
"""

from __future__ import annotations

import json
from typing import Any, Iterable
from pathlib import Path
from dataclasses import replace, dataclass

from agent.hif.decisions.scoring import ScoringParams


@dataclass(frozen=True, slots=True)
class HIFPreset:
    """首版 HIF 安全执行预设 + 用户覆盖字段（全 0/空 = 不覆盖）。"""

    preset_id: str
    schedule_priority: tuple[str, ...]
    daily_schedule_priorities: tuple[tuple[int, tuple[str, ...]], ...]
    requires_day_schedule: bool
    class_option_priority: tuple[str, ...]
    public_lesson_priority: tuple[str, ...]
    drink_name_priority: tuple[str, ...]
    skill_reward_names: tuple[str, ...]
    select_change_target_names: tuple[str, ...]
    select_change_source_names: tuple[str, ...]
    select_change_reroll_limit: int
    reward_reroll_limit: int
    consult_policy: str
    entry_mode: str
    round1_mode: str
    # 培育倾向:决定三选一效果关键词评分表(good_condition/focus/balanced)
    preference: str = "good_condition"
    # ---- 用户覆盖（GUI > 文件；0/空 = 不覆盖，用上方 preset 值） ----
    card_priority: tuple[str, ...] = ()  # 命中卡名直接选,优先于评分
    drink_priority: tuple[str, ...] = ()  # 命中饮料名直接选,优先于评分
    good_weight: float = 0.0  # 好調Nターン 分值(絶好調按 +2 差值联动)
    focus_weight: float = 0.0  # 集中 分值
    stamina_recover_weight: float = 0.0  # 体力回復 分值
    accept_threshold: float = 0.0  # 重抽阈值
    select_change_reroll_override: int = 0  # 変卡重抽上限
    reward_reroll_override: int = 0  # 奖励重抽上限
    low_health_percent: int = 0  # 低体力阈值百分比(强制外出)
    daily_override: tuple[tuple[int, tuple[str, ...]], ...] = ()  # 逐日日程覆盖
    consult_policy_override: str = ""  # 相談策略覆盖
    class_option_policy_override: str = ""  # 授業选项策略覆盖
    # ---- 评分模型旋钮(B4;0/None = 不覆盖,用 scoring.ScoringParams 默认) ----
    scoring_scale: float = 0.0  # 缩放系数(量级对齐,默认 0.53 → 好調7T ≈8 分)
    endgame_weight: float | None = None  # 终盘权重(None=默认 1.0;0=关闭终盘衰减)


SAFE_DEFAULT_PRESET = HIFPreset(
    preset_id="safe_default",
    schedule_priority=("Da", "Vi", "Vo", "gift", "consult", "go_out"),
    # Day1(剩余6日)授業 Vo 优先(用户指定 2026-08-15);其余日走全局序
    daily_schedule_priorities=((6, ("Vo", "Da", "Vi")),),
    requires_day_schedule=False,
    class_option_priority=("good_condition", "first_safe"),
    # 公開レッスン按属性序选卡;SP 当日随机不可选(seesaawiki 2026-08-15 调研)
    public_lesson_priority=("Da", "Vi", "Vo"),
    drink_name_priority=("センブリソーダ",),
    skill_reward_names=("始まりの合図",),
    select_change_target_names=("始まりの合図",),
    select_change_source_names=("大胆不敵", "始まりの合図"),
    # 実機観察: 変卡(授業場景)重抽上限 3 回、差し入れ/P item 奖励重抽上限 2 回,兩場景次數不同
    select_change_reroll_limit=3,
    reward_reroll_limit=2,
    consult_policy="finish_without_purchase",
    entry_mode="finals",
    round1_mode="observe_and_stop",
)

RINAMI_GOOD_CONDITION_SAFE = HIFPreset(
    preset_id="rinami_good_condition_safe",
    schedule_priority=SAFE_DEFAULT_PRESET.schedule_priority,
    daily_schedule_priorities=(
        (6, ("Vo", "Da", "Vi")),
        (5, ("Da", "Vi", "Vo")),
        (4, ("gift", "go_out")),
        (3, ("Vi", "Da", "Vo")),
        (2, ("Da", "Vi", "Vo")),
        (1, ("consult",)),
    ),
    requires_day_schedule=True,
    class_option_priority=SAFE_DEFAULT_PRESET.class_option_priority,
    public_lesson_priority=SAFE_DEFAULT_PRESET.public_lesson_priority,
    drink_name_priority=SAFE_DEFAULT_PRESET.drink_name_priority,
    skill_reward_names=SAFE_DEFAULT_PRESET.skill_reward_names,
    select_change_target_names=SAFE_DEFAULT_PRESET.select_change_target_names,
    select_change_source_names=SAFE_DEFAULT_PRESET.select_change_source_names,
    select_change_reroll_limit=SAFE_DEFAULT_PRESET.select_change_reroll_limit,
    reward_reroll_limit=SAFE_DEFAULT_PRESET.reward_reroll_limit,
    consult_policy=SAFE_DEFAULT_PRESET.consult_policy,
    entry_mode=SAFE_DEFAULT_PRESET.entry_mode,
    round1_mode=SAFE_DEFAULT_PRESET.round1_mode,
)

_PRESETS = {preset.preset_id: preset for preset in (SAFE_DEFAULT_PRESET, RINAMI_GOOD_CONDITION_SAFE)}

_KEYWORD_PREFERENCES = ("good_condition", "focus", "balanced")

# GUI 数值旋钮 → 关键词表词名（好調句式与 keywords 表同步）
_GOOD_TURN = "好調[0-9０-９]*ターン"
_ZGOOD_TURN = "絶好調[0-9０-９]*ターン"


def _to_float(value: Any) -> float:
    """GUI 传参容错：合法正数返回，否则 0（不覆盖）。"""
    try:
        num = float(value)
        return num if num > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        num = int(value)
        return num if num > 0 else 0
    except (TypeError, ValueError):
        return 0


def _split_names(value: Any) -> tuple[str, ...]:
    """逗号/顿号分隔名单 → 去空元组。"""
    if not isinstance(value, str):
        return ()
    return tuple(s.strip() for s in value.replace("、", ",").split(",") if s.strip())


def _parse_daily_override(payload: dict) -> tuple[tuple[int, tuple[str, ...]], ...]:
    """GUI dayN_order 字段（"Da,Vi,Vo"）→ ((day_remaining, order), ...)。

    日数语义与 daily_schedule_priorities 一致：day_remaining = 7 - Day 编号
    （Day1 对应 6、Day6 对应 1）。
    """
    entries: list[tuple[int, tuple[str, ...]]] = []
    for day in range(1, 7):
        order = _split_names(payload.get(f"day{day}_order", ""))
        if order:
            entries.append((7 - day, order))
    return tuple(entries)


def parse_hif_preset(raw: str | None) -> HIFPreset:
    """从 MaaFramework 的 custom_action_param 读取预设与 GUI 覆盖参数。

    覆盖容错（grill 定案）：非法值忽略并回落 preset 默认，部分生效。
    """
    try:
        payload: Any = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return SAFE_DEFAULT_PRESET

    if not isinstance(payload, dict):
        return SAFE_DEFAULT_PRESET
    preset = _PRESETS.get(payload.get("preset_id"), SAFE_DEFAULT_PRESET)

    updates: dict[str, Any] = {}
    preference = payload.get("preference")
    if preference in _KEYWORD_PREFERENCES and preference != preset.preference:
        updates["preference"] = preference
    for field_name in ("card_priority", "drink_priority"):
        names = _split_names(payload.get(f"{field_name}_str", ""))
        if names:
            updates[field_name] = names
    for field_name in ("good_weight", "focus_weight", "stamina_recover_weight", "accept_threshold"):
        value = _to_float(payload.get(field_name))
        if value:
            updates[field_name] = value
    for field_name in ("select_change_reroll_override", "reward_reroll_override", "low_health_percent"):
        value = _to_int(payload.get(field_name))
        if value:
            updates[field_name] = value
    daily = _parse_daily_override(payload)
    if daily:
        updates["daily_override"] = daily
    scoring_scale = _to_float(payload.get("scoring_scale"))
    if scoring_scale:
        updates["scoring_scale"] = scoring_scale
    # GUI 模板注入恒为字符串;0=关闭终盘衰减为有效值,不能走 0 哨兵,解析失败才不覆盖
    try:
        updates["endgame_weight"] = float(payload.get("endgame_weight"))
    except (TypeError, ValueError):
        pass
    for field_name in ("consult_policy_override", "class_option_policy_override"):
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            updates[field_name] = value.strip()

    return replace(preset, **updates) if updates else preset


def build_gui_keyword_overrides(preset: HIFPreset) -> dict:
    """把 preset 的 GUI 数值旋钮转成 load_keyword_tables 的 overrides 结构。"""
    weights: dict[str, float] = {}
    if preset.good_weight:
        weights[_GOOD_TURN] = preset.good_weight
        weights[_ZGOOD_TURN] = preset.good_weight + 2  # 保持基准差值关系
    if preset.focus_weight:
        weights["集中"] = preset.focus_weight
    if preset.stamina_recover_weight:
        weights["体力回復"] = preset.stamina_recover_weight
    overrides: dict = {}
    if weights:
        overrides["keyword_weights"] = weights
    if preset.accept_threshold:
        overrides["accept_threshold"] = preset.accept_threshold
    return overrides


def build_scoring_params(preset: HIFPreset) -> ScoringParams:
    """preset 的评分模型旋钮(B4 GUI:缩放系数/终盘权重)→ ScoringParams 点名覆盖。

    其余参数留给 C 阶段校准定值,不暴露 GUI。
    """
    params = ScoringParams()
    if preset.scoring_scale > 0:
        params = replace(params, global_scale=preset.scoring_scale)
    if preset.endgame_weight is not None:
        params = replace(params, endgame_weight=preset.endgame_weight)
    return params


_OVERRIDE_PATH = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "decision_override.json"


def apply_file_overrides(preset: HIFPreset, path: Path = _OVERRIDE_PATH) -> HIFPreset:
    """把 decision_override.json 的非评分项(名单/重抽/低体力/逐日/策略)合并进 preset。

    评分词与阈值由 rewards.load_keyword_tables 在 KeywordTable 层合并,此处不重复;
    `_=0/空` 视为未配置;文件缺失/语法错静默忽略(评分层已警告)。
    """
    if not path.exists():
        return preset
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return preset
    if not isinstance(payload, dict):
        return preset
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}

    updates: dict[str, Any] = {}
    for field_name, key in (("card_priority", "card_priority"), ("drink_priority", "drink_priority")):
        names = payload.get(key)
        if isinstance(names, list) and names and not preset.__getattribute__(field_name):
            updates[field_name] = tuple(str(n).strip() for n in names if str(n).strip())
    for field_name, key in (
        ("select_change_reroll_override", "select_change_reroll_limit"),
        ("reward_reroll_override", "reward_reroll_limit"),
        ("low_health_percent", "low_health_percent"),
    ):
        value = _to_int(payload.get(key))
        if value and not preset.__getattribute__(field_name):
            updates[field_name] = value
    daily = payload.get("daily_schedule")
    if isinstance(daily, dict) and daily and not preset.daily_override:
        entries = []
        for key, order in daily.items():
            try:
                day = int(key)
            except (TypeError, ValueError):
                continue
            names = _split_names(order if isinstance(order, str) else "")
            if names:
                entries.append((day, names))
        if entries:
            updates["daily_override"] = tuple(entries)
    for field_name, key in (("consult_policy_override", "consult_policy"), ("class_option_policy_override", "class_option_policy")):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and not preset.__getattribute__(field_name):
            updates[field_name] = value.strip()
    return replace(preset, **updates) if updates else preset


def choose_first_matching(candidates: Iterable[str], priority: Iterable[str]) -> str | None:
    """按预设顺序选择已识别候选，绝不回退到未知候选。"""

    candidate_set = set(candidates)
    return next((name for name in priority if name in candidate_set), None)


def choose_schedule_priority(preset: HIFPreset, day_remaining: int | None) -> tuple[str, ...] | None:
    """返回当前剩余日数的日程优先级（GUI daily_override > preset daily 表 > 全局序）。"""

    if day_remaining is not None:
        for day, order in preset.daily_override:
            if day == day_remaining:
                return order
        for day, priority in preset.daily_schedule_priorities:
            if day == day_remaining:
                return priority
    return None if preset.requires_day_schedule else preset.schedule_priority
