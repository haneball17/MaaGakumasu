"""HIF 本战准备、奖励和日程的纯决策服务。"""

from __future__ import annotations

from typing import Any, Mapping, Iterable
from dataclasses import dataclass

from agent.hif.domain import HIFPhase, HIFDecision, HIFCandidate, HIFRuntimeState, HIFPublicLessonPreview
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

_SKILL_TAG_WEIGHTS = {
    "reprise": 16.0,
    "good_condition_grant": 12.0,
    "good_condition": 6.0,
    "extra_play": 10.0,
    "draw": 8.0,
    "focus": 6.0,
    "score": 4.0,
    "recovery": 2.0,
    "good_condition_requirement": -4.0,
}

_SKILL_TAG_REASONS = {
    "reprise": "包含再演效果",
    "good_condition_grant": "直接提供好调回合",
    "good_condition": "与好调路线相关",
    "extra_play": "增加技能卡使用次数",
    "draw": "提供抽牌或入手牌效果",
    "focus": "提供集中效果",
    "score": "提供参数增长",
    "recovery": "提供元气或体力恢复",
}

_SKILL_DETAIL_MARKERS = {
    "good_condition": (("好調",),),
    "good_condition_grant": (("好調",),),
    "good_condition_requirement": (("好調状態の場合",), ("使用可",)),
    "extra_play": (("使用数追加",),),
    "draw": (("スキルカードを引く", "手札に移動"),),
    "focus": (("集中",),),
    "recovery": (("元気", "体力回復"),),
    "reprise": (("再演",),),
    "score": (("パラメータ",),),
}

_MIN_OBSERVED_SKILL_DETAIL_CONFIDENCE = 0.95


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

    @staticmethod
    def choose_public_lesson(
        previews: Iterable[HIFPublicLessonPreview],
        strategy_id: str,
    ) -> HIFDecision:
        """首版仅接受完整快照后的固定 Da 测试决策。"""

        observed = tuple(previews)
        if strategy_id != "fixed_da_test":
            return HIFDecision(None, 0.0, ("公开课策略未实现",), stop_reason="unsupported_public_lesson_strategy")
        if len(observed) != 3 or {preview.candidate_id for preview in observed} != {"Vo", "Da", "Vi"}:
            return HIFDecision(None, 0.0, ("公开课候选不完整",), stop_reason="public_lesson_candidates_incomplete")
        if not all(preview.verified for preview in observed):
            return HIFDecision(None, 0.0, ("公开课收益未验证",), stop_reason="public_lesson_preview_unverified")
        return HIFDecision("Da", 1.0, ("测试配置：固定选择Da公开课",))

    def reward_search_order(self, reward_kind: str, preset: HIFPreset, limit: int = 12) -> tuple[HIFRankedName, ...]:
        """返回可供 OCR 逐项查找的奖励优先顺序。

        候选仍必须在屏幕上被 OCR 识别；本函数只给出排序，不能凭空选择不存在的卡。
        """

        if reward_kind == "skill":
            explicit = preset.skill_reward_names
            records = self.catalog.skill_cards
            profile_priority = _RINAMI_SKILL_PRIORITY
            tag_weights = _SKILL_TAG_WEIGHTS
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
                if reward_kind == "skill":
                    reasons = tuple(_SKILL_TAG_REASONS[tag] for tag in _SKILL_TAG_REASONS if tag in record.tags)
                    if "good_condition_requirement" in record.tags:
                        reasons += ("好调前置状态未校验，降低候选优先级",)
                    ranks[name] = HIFRankedName(name, score, reasons or ("按已结构化效果标签评分",))
                else:
                    ranks[name] = HIFRankedName(name, score, ("按已结构化效果标签评分",))
        return tuple(sorted(ranks.values(), key=lambda item: (-item.score, item.name))[:limit])

    def choose_observed_skill_reward(
        self,
        candidates: Iterable[Mapping[str, Any]],
        preset: HIFPreset,
    ) -> HIFDecision:
        """仅接受名称、详情和 OCR 置信度均可核验的技能卡候选。"""

        observed = tuple(candidates)
        if not observed:
            return HIFDecision(None, 0.0, ("未读取到技能卡奖励候选",), stop_reason="no_observed_reward_candidates")
        names: list[str] = []
        for candidate in observed:
            if not isinstance(candidate, Mapping):
                return HIFDecision(None, 0.0, ("技能卡候选结构无效",), stop_reason="invalid_observed_skill_reward_candidate")
            name = candidate.get("name")
            if not isinstance(name, str) or not name:
                return HIFDecision(None, 0.0, ("技能卡候选名称无效",), stop_reason="invalid_observed_skill_reward_candidate")
            card = self.catalog.skill_cards.get(name)
            if card is None:
                return HIFDecision(
                    None,
                    0.0,
                    ("技能卡候选未收录",),
                    (f"unknown={name}",),
                    "unknown_observed_reward_candidate",
                )
            name_confidence = candidate.get("name_confidence")
            detail_confidence = candidate.get("detail_confidence")
            if not all(
                isinstance(confidence, (int, float)) and confidence >= _MIN_OBSERVED_SKILL_DETAIL_CONFIDENCE
                for confidence in (name_confidence, detail_confidence)
            ):
                return HIFDecision(
                    None,
                    0.0,
                    ("技能卡候选 OCR 置信度不足",),
                    (f"name={name}", f"name_confidence={name_confidence}", f"detail_confidence={detail_confidence}"),
                    "unverified_skill_reward_candidate_detail",
                )
            detail_text = candidate.get("effect_text")
            if not isinstance(detail_text, str) or not detail_text.strip():
                return HIFDecision(
                    None,
                    0.0,
                    ("技能卡候选详情为空",),
                    (f"name={name}",),
                    "unverified_skill_reward_candidate_detail",
                )
            missing = self._missing_skill_detail_markers(card.tags, detail_text)
            if missing:
                return HIFDecision(
                    None,
                    0.0,
                    ("技能卡候选详情与已收录效果不符",),
                    (f"name={name}", f"missing={','.join(missing)}"),
                    "observed_skill_reward_detail_mismatch",
                )
            names.append(name)
        return self.choose_observed_reward("skill", names, preset)

    def choose_observed_reward(
        self,
        reward_kind: str,
        candidate_names: Iterable[str],
        preset: HIFPreset,
    ) -> HIFDecision:
        """只在所有已观察候选均可解析且最高分唯一时给出领取目标。"""

        visible = tuple(name for name in candidate_names if isinstance(name, str) and name)
        if not visible:
            return HIFDecision(None, 0.0, ("未读取到奖励候选",), stop_reason="no_observed_reward_candidates")
        if len(set(visible)) != len(visible):
            return HIFDecision(None, 0.0, ("奖励候选名称重复",), stop_reason="duplicate_observed_reward_candidates")

        if reward_kind == "drink":
            records = self.catalog.drinks
        elif reward_kind == "skill":
            records = self.catalog.skill_cards
        else:
            return HIFDecision(None, 0.0, ("奖励类别不受支持",), stop_reason="unsupported_reward_kind")

        unknown = tuple(sorted(name for name in visible if name not in records))
        if unknown:
            return HIFDecision(
                None,
                0.0,
                ("奖励候选未收录",),
                tuple(f"unknown={name}" for name in unknown),
                "unknown_observed_reward_candidate",
            )

        ranked = self.reward_search_order(reward_kind, preset, limit=len(records))
        rank_by_name = {item.name: item for item in ranked}
        unranked = tuple(name for name in visible if name not in rank_by_name)
        if unranked:
            return HIFDecision(
                None,
                0.0,
                ("奖励候选缺少可解释评分",),
                tuple(f"unranked={name}" for name in unranked),
                "unranked_observed_reward_candidate",
            )

        observed = tuple(rank_by_name[name] for name in visible)
        highest_score = max(item.score for item in observed)
        best = tuple(item for item in observed if item.score == highest_score)
        if len(best) != 1:
            return HIFDecision(
                None,
                0.0,
                ("奖励最高分并列",),
                tuple(f"candidate={item.name}" for item in best),
                "ambiguous_observed_reward_candidates",
            )
        winner = best[0]
        return HIFDecision(winner.name, min(0.99, 0.5 + min(winner.score, 100.0) / 200.0), winner.reasons)

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
    def _missing_skill_detail_markers(tags: Iterable[str], detail_text: str) -> tuple[str, ...]:
        normalized = "".join(detail_text.split())
        missing: list[str] = []
        for tag in tags:
            marker_groups = _SKILL_DETAIL_MARKERS.get(tag)
            if marker_groups and any(not any(marker in normalized for marker in markers) for markers in marker_groups):
                missing.append(tag)
        return tuple(sorted(missing))

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
