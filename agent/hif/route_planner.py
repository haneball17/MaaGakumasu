"""HIF 本战准备、奖励和日程的纯决策服务。"""

from __future__ import annotations

from typing import Iterable
from dataclasses import dataclass

from agent.hif.domain import HIFPhase, HIFDecision, HIFCandidate, HIFRuntimeState
from agent.hif.catalog import HIFCatalog, load_hif_catalog
from agent.hif.presets import HIFPreset, choose_first_matching, choose_schedule_priority

_SCHEDULE_ACTION_PRIORITIES = {
    "授業": ("Da", "Vi", "Vo", "lesson"),
    "公開レッスン": ("Da", "Vi", "Vo", "lesson"),
    "おでかけ": ("go_out", "gift"),
    "相談": ("consult",),
}

_PUBLIC_LESSON_TOKEN = {
    "Da_sp": "Da",
    "Vi_sp": "Vi",
    "Vo_sp": "Vo",
}

_RINAMI_SKILL_PRIORITY = (
    "お姉さんの感覚",
    "自然体の魅力",
    "国民的アイドル",
    "至高のエンタメ",
    "シュプレヒコール",
    "存在感",
    "始まりの合図",
)

_RINAMI_DRINK_PRIORITY = (
    "初星黒酢",
    "センブリソーダ",
    "パワフル漢方ドリンク",
)


@dataclass(frozen=True, slots=True)
class HIFRankedName:
    name: str
    score: float
    reasons: tuple[str, ...]


class HIFRoutePlanner:
    """将可信状态、预设和候选转为可解释的单步决策。"""

    def __init__(self, catalog: HIFCatalog | None = None) -> None:
        self.catalog = catalog or load_hif_catalog()

    def choose_schedule(
        self,
        state: HIFRuntimeState,
        candidates: Iterable[HIFCandidate],
        preset: HIFPreset,
    ) -> HIFDecision:
        visible = tuple(candidates)
        if not visible:
            return HIFDecision(None, 0.0, ("未识别到可选日程",), stop_reason="no_schedule_candidates")
        if state.phase is not HIFPhase.FINALS_PREPARE:
            return HIFDecision(None, 0.0, ("当前不是本战准备阶段",), stop_reason="unsupported_schedule_phase")

        low_health = self._choose_low_health_candidate(state, visible)
        if low_health is not None:
            return HIFDecision(low_health.candidate_id, 0.98, ("体力低，优先外出恢复",))

        priority = choose_schedule_priority(preset, state.day_remaining)
        if preset.requires_day_schedule:
            if priority is None:
                return HIFDecision(None, 0.0, ("实验预设缺少剩余日数",), stop_reason="missing_preset_schedule_day")
            selected = self._choose_by_priority(visible, priority)
            if selected is not None:
                return HIFDecision(selected.candidate_id, 0.92, ("命中预设的日程优先级",))
            return HIFDecision(
                None,
                0.0,
                ("预设日程候选未出现",),
                ("visible=" + ",".join(candidate.category for candidate in visible),),
                "preset_schedule_candidate_missing",
            )

        schedule = self.catalog.schedule_for_remaining_day(state.day_remaining)
        if schedule is None:
            if priority is None:
                return HIFDecision(None, 0.0, ("缺少本战剩余日数或固定日程",), stop_reason="missing_schedule_day")
            selected = self._choose_by_priority(visible, priority)
            if selected is not None:
                return HIFDecision(selected.candidate_id, 0.6, ("使用安全默认的日程优先级",), ("schedule_day_unknown",))
            return HIFDecision(None, 0.0, ("默认日程候选未出现",), stop_reason="default_schedule_candidate_missing")

        default_priority = self._priority_for_schedule_action(schedule.action, preset)
        if schedule.fallback:
            default_priority += self._priority_for_schedule_action(schedule.fallback, preset)
        selected = self._choose_by_priority(visible, default_priority)
        if selected is None:
            return HIFDecision(
                None,
                0.0,
                ("固定日程候选未出现",),
                (f"expected={schedule.action}",),
                "fixed_schedule_candidate_missing",
            )
        return HIFDecision(selected.candidate_id, 0.8, (f"命中本战第 {schedule.day_index} 日固定日程",))

    def reward_search_order(self, reward_kind: str, preset: HIFPreset, limit: int = 12) -> tuple[HIFRankedName, ...]:
        """返回可供 OCR 逐项查找的奖励优先顺序。

        候选仍必须在屏幕上被 OCR 识别；本函数只给出排序，不能凭空选择不存在的卡。
        """

        if reward_kind == "skill":
            explicit = preset.skill_reward_names
            records = self.catalog.skill_cards
            profile_priority = _RINAMI_SKILL_PRIORITY
            tag_weights = {"reprise": 16.0, "good_condition": 12.0, "extra_play": 10.0, "draw": 8.0, "focus": 6.0, "score": 4.0}
        elif reward_kind == "drink":
            explicit = preset.drink_name_priority
            records = self.catalog.drinks
            profile_priority = _RINAMI_DRINK_PRIORITY
            tag_weights = {"draw": 12.0, "good_condition": 10.0, "focus": 8.0, "recovery": 5.0, "score": 3.0}
        else:
            return ()

        ranks: dict[str, HIFRankedName] = {}
        for index, name in enumerate(explicit):
            ranks[name] = HIFRankedName(name, 100.0 - index, ("预设精确优先级",))
        for index, name in enumerate(profile_priority):
            existing = ranks.get(name)
            score = 80.0 - index
            if existing is None or score > existing.score:
                ranks[name] = HIFRankedName(name, score, ("莉波好调路线核心资源",))
        for name, record in records.items():
            score = sum(weight for tag, weight in tag_weights.items() if tag in record.tags)
            if score <= 0:
                continue
            existing = ranks.get(name)
            if existing is None or score > existing.score:
                ranks[name] = HIFRankedName(name, score, ("按已结构化效果标签评分",))
        return tuple(sorted(ranks.values(), key=lambda item: (-item.score, item.name))[:limit])

    def custom_p_item_search_order(
        self,
        preset: HIFPreset,
        limit: int = 8,
        *,
        stage: int | None = None,
        parent: str | None = None,
    ) -> tuple[HIFRankedName, ...]:
        """返回当前已证实的莉波好调自定义 P 道具排序。

        安全默认预设不把攻略偏好当作确定事实，继续只接受游戏内推荐标识。
        """

        if preset.preset_id != "rinami_good_condition_safe":
            return ()
        return tuple(
            HIFRankedName(name, 100.0 - index, ("已记录的感性好调 P 道具路线",))
            for index, name in enumerate(self.catalog.custom_p_item_names("sense", limit, stage=stage, parent=parent))
        )

    @staticmethod
    def _choose_by_priority(candidates: Iterable[HIFCandidate], priority: Iterable[str]) -> HIFCandidate | None:
        candidate_by_category = {candidate.category: candidate for candidate in candidates}
        selected_key = choose_first_matching(candidate_by_category, priority)
        return candidate_by_category.get(selected_key) if selected_key else None

    @staticmethod
    def _choose_low_health_candidate(state: HIFRuntimeState, candidates: Iterable[HIFCandidate]) -> HIFCandidate | None:
        is_low_health = state.stamina is not None and state.stamina <= 10
        if state.stamina_ratio is not None:
            is_low_health = is_low_health or state.stamina_ratio <= 0.35
        if not is_low_health:
            return None
        return next((candidate for candidate in candidates if candidate.category == "go_out"), None)

    @staticmethod
    def _priority_for_schedule_action(action: str, preset: HIFPreset) -> tuple[str, ...]:
        if action == "公開レッスン" and preset.public_lesson_priority:
            return tuple(_PUBLIC_LESSON_TOKEN.get(item, item) for item in preset.public_lesson_priority)
        return _SCHEDULE_ACTION_PRIORITIES.get(action, ())
