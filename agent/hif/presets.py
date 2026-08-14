"""HIF 用户预设的纯数据与候选排序逻辑。"""

from __future__ import annotations

import json
from typing import Any, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HIFPreset:
    """首版 HIF 安全执行预设。"""

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


SAFE_DEFAULT_PRESET = HIFPreset(
    preset_id="safe_default",
    schedule_priority=("Da", "Vi", "Vo", "gift", "consult", "go_out"),
    daily_schedule_priorities=(),
    requires_day_schedule=False,
    class_option_priority=("good_condition", "first_safe"),
    public_lesson_priority=("Da_sp", "Vi_sp", "Vo_sp"),
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


def parse_hif_preset(raw: str | None) -> HIFPreset:
    """从 MaaFramework 的 custom_action_param 读取预设。"""

    try:
        payload: Any = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return SAFE_DEFAULT_PRESET

    if not isinstance(payload, dict):
        return SAFE_DEFAULT_PRESET
    return _PRESETS.get(payload.get("preset_id"), SAFE_DEFAULT_PRESET)


def choose_first_matching(candidates: Iterable[str], priority: Iterable[str]) -> str | None:
    """按预设顺序选择已识别候选，绝不回退到未知候选。"""

    candidate_set = set(candidates)
    return next((name for name in priority if name in candidate_set), None)


def choose_schedule_priority(preset: HIFPreset, day_remaining: int | None) -> tuple[str, ...] | None:
    """返回当前剩余日数的日程优先级，实验预设拒绝缺失日数。"""

    if day_remaining is not None:
        for day, priority in preset.daily_schedule_priorities:
            if day == day_remaining:
                return priority
    return None if preset.requires_day_schedule else preset.schedule_priority
