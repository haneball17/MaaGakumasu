"""Interval 商店的纯决策层。"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from agent.hif.domain import HIFPhase, HIFDecision, HIFCandidate, HIFRuntimeState


@dataclass(frozen=True, slots=True)
class HIFIntervalPolicy:
    target_deck_size: int = 22
    low_stamina_ratio: float = 0.35


class HIFIntervalPlanner:
    """仅从已识别且价格可信的可见候选中做 Interval 决策。"""

    _CARD_CATEGORIES = frozenset({"skill", "skill_card", "card"})
    _CUSTOMIZE_CATEGORIES = frozenset({"skill_customize", "customize"})
    _RECOVERY_CATEGORIES = frozenset({"recovery", "recover"})
    _FINISH_CATEGORIES = frozenset({"finish_interval", "finish"})
    _CARD_TAG_SCORE = {
        "key_card": 50,
        "loop_core": 40,
        "good_condition": 30,
        "extra_play": 24,
        "draw": 18,
        "score": 10,
        "basic": -20,
    }

    def __init__(self, policy: HIFIntervalPolicy | None = None) -> None:
        self.policy = policy or HIFIntervalPolicy()

    def choose(self, state: HIFRuntimeState, candidates: Iterable[HIFCandidate]) -> HIFDecision:
        visible = tuple(candidates)
        if state.phase is not HIFPhase.INTERVAL:
            return HIFDecision(None, 0.0, ("当前不是 Interval",), stop_reason="unsupported_interval_phase")
        if state.p_points is None:
            return HIFDecision(None, 0.0, ("缺少可信 P 点",), stop_reason="interval_p_points_unknown")
        if state.deck_size is None:
            return HIFDecision(None, 0.0, ("缺少可信牌库数量",), stop_reason="interval_deck_size_unknown")

        affordable = tuple(candidate for candidate in visible if self._is_affordable(candidate, state.p_points))
        if state.deck_size < self.policy.target_deck_size:
            card = self._best_card(affordable)
            if card is not None:
                return HIFDecision(
                    card.candidate_id,
                    min(0.95, card.confidence),
                    (f"牌库 {state.deck_size} 张低于目标 {self.policy.target_deck_size} 张", "优先补充已验证且可负担的技能卡"),
                )
            return HIFDecision(None, 0.0, ("牌库未达目标且没有可负担技能卡",), stop_reason="interval_card_candidate_missing")

        customize = self._best_by_tags(affordable, self._CUSTOMIZE_CATEGORIES)
        if customize is not None:
            return HIFDecision(customize.candidate_id, min(0.9, customize.confidence), ("牌库已达目标，优先关键卡特别指导",))
        if self._is_low_stamina(state):
            recovery = self._best_by_tags(affordable, self._RECOVERY_CATEGORIES)
            if recovery is not None:
                return HIFDecision(recovery.candidate_id, min(0.85, recovery.confidence), ("体力偏低，选择已验证回复",))
        finish = next((candidate for candidate in visible if candidate.category in self._FINISH_CATEGORIES), None)
        if finish is not None:
            return HIFDecision(finish.candidate_id, min(0.8, finish.confidence), ("无更高优先级的已验证消费，结束 Interval",))
        return HIFDecision(None, 0.0, ("未识别到安全的 Interval 操作",), stop_reason="interval_no_safe_candidate")

    @staticmethod
    def _is_affordable(candidate: HIFCandidate, p_points: int) -> bool:
        if candidate.category in HIFIntervalPlanner._FINISH_CATEGORIES:
            return True
        return candidate.cost is not None and 0 <= candidate.cost <= p_points

    def _best_card(self, candidates: Iterable[HIFCandidate]) -> HIFCandidate | None:
        cards = [candidate for candidate in candidates if candidate.category in self._CARD_CATEGORIES]
        return max(cards, key=self._tag_score, default=None)

    def _best_by_tags(self, candidates: Iterable[HIFCandidate], categories: frozenset[str]) -> HIFCandidate | None:
        matched = [candidate for candidate in candidates if candidate.category in categories]
        return max(matched, key=self._tag_score, default=None)

    def _tag_score(self, candidate: HIFCandidate) -> float:
        return sum(self._CARD_TAG_SCORE.get(tag, 0) for tag in candidate.tags) + candidate.confidence

    def _is_low_stamina(self, state: HIFRuntimeState) -> bool:
        return state.stamina_ratio is not None and state.stamina_ratio <= self.policy.low_stamina_ratio
