from __future__ import annotations

from typing import Any, Iterable

from agent.hif.algorithms.types import (
    RouteStep,
    RewardKind,
    RoutePhase,
    RewardOption,
    ImmediateScore,
    ProduceProfile,
    ScenarioConfig,
    CandidateAction,
    SimulationState,
    SoftGateAdjustment,
)


class ImmediateScorer:
    def __init__(self, scenario: ScenarioConfig):
        self.scenario = scenario

    def score(
        self,
        state: SimulationState,
        step: RouteStep,
        candidate: CandidateAction,
        soft_gate: SoftGateAdjustment,
    ) -> ImmediateScore:
        weights = self.scenario.score_weights
        immediate_value = (
            candidate.stamina_delta * weights["stamina"]
            + candidate.p_point_delta * weights["p_points"]
            + candidate.star_delta * weights["star_value"]
            + candidate.trial_readiness_delta * weights["trial_readiness"]
            + candidate.memory_quality_delta * weights["memory_quality"]
            + candidate.deck_quality_delta * weights["deck_quality"]
            + candidate.finals_readiness_delta * weights["finals_readiness"]
            + candidate.interval_budget_delta * weights["interval_budget"]
            + candidate.support_progress_delta * weights["support_progress"]
            + candidate.deck_size_delta * weights["deck_size"]
        )

        target_gap_score = self._score_target_gap(state, step.phase, candidate)
        synergy_score = soft_gate.bias_score + self._score_existing_synergy(state, candidate)
        risk_penalty = candidate.risk * 5.0

        projected_stamina = max(0, min(state.max_stamina, state.stamina + candidate.stamina_delta))
        if projected_stamina < 8 and candidate.category not in {"outing", "exam", "round_exam"}:
            risk_penalty += 8.0

        total = immediate_value + target_gap_score + synergy_score - risk_penalty
        return ImmediateScore(
            immediate_value=round(immediate_value, 2),
            target_gap_score=round(target_gap_score, 2),
            synergy_score=round(synergy_score, 2),
            risk_penalty=round(risk_penalty, 2),
            total_score=round(total, 2),
        )

    def _score_target_gap(self, state: SimulationState, phase: RoutePhase, candidate: CandidateAction) -> float:
        if phase in {"selection", "selection_exam", "selection_item"}:
            targets = self.scenario.selection_targets
            deltas = {
                "trial_readiness": candidate.trial_readiness_delta,
                "star_value": candidate.star_delta,
                "memory_quality": candidate.memory_quality_delta,
                "deck_quality": candidate.deck_quality_delta,
                "support_event_progress": candidate.support_progress_delta,
            }
        elif phase == "interval":
            targets = self.scenario.interval_targets
            deltas = {
                "interval_budget": candidate.interval_budget_delta,
                "p_points": candidate.p_point_delta,
                "star_value": candidate.star_delta,
            }
        else:
            targets = self.scenario.finals_targets
            deltas = {
                "finals_readiness": candidate.finals_readiness_delta,
                "star_value": candidate.star_delta,
                "memory_quality": candidate.memory_quality_delta,
                "deck_quality": candidate.deck_quality_delta,
            }

        score = 0.0
        for metric, delta in deltas.items():
            current = getattr(state, metric, 0)
            target = targets.get(metric, current)
            before_gap = max(0, target - current)
            after_gap = max(0, target - (current + delta))
            score += (before_gap - after_gap) * 0.9
        return score

    @staticmethod
    def _score_existing_synergy(state: SimulationState, candidate: CandidateAction) -> float:
        score = 0.0
        for tag in candidate.tags:
            if tag in state.skill_tag_counts:
                score += min(2.0, state.skill_tag_counts[tag] * 0.5)
            if tag in state.p_item_tag_counts:
                score += min(1.8, state.p_item_tag_counts[tag] * 0.4)
        return score


class RewardScorer:
    def __init__(self, profile: ProduceProfile):
        self.profile = profile

    def score(self, reward_kind: RewardKind, options: Iterable[RewardOption]) -> dict[str, Any]:
        ranked = []
        for option in options:
            tag_score = sum(self._tag_weight(tag, reward_kind) for tag in option.tags)
            if reward_kind in {"skill_acquire", "skill_upgrade", "skill_delete"}:
                tag_score += option.metadata.get("upgrade_priority", 0) * (1.2 if reward_kind != "skill_delete" else -0.4)
                tag_score += option.metadata.get("delete_priority", 0) * (1.6 if reward_kind == "skill_delete" else -0.5)
            if reward_kind == "p_item":
                tag_score += sum(self.profile.preferred_p_item_tags.get(tag, 0.0) for tag in option.tags)

            reasons = []
            if any(tag in self.profile.preferred_skill_tags for tag in option.tags):
                reasons.append("命中技能偏好标签")
            if any(tag in self.profile.preferred_p_item_tags for tag in option.tags):
                reasons.append("命中 P 道具偏好标签")
            if "trouble" in option.tags and reward_kind == "skill_delete":
                reasons.append("麻烦牌删除优先")
            elif "trouble" in option.tags:
                reasons.append("麻烦牌不宜拿取")

            confidence = 0.55 if option.tags else 0.35
            ranked.append(
                {
                    "option_id": option.option_id,
                    "name": option.name,
                    "kind": reward_kind,
                    "tags": option.tags,
                    "score": round(tag_score * self.profile.reward_priorities.get(reward_kind, 1.0), 2),
                    "top_reasons": reasons[:3] or ["保守默认评分"],
                    "confidence": round(confidence, 2),
                    "unknown_factors": [] if option.tags else ["missing_tags"],
                }
            )

        ranked.sort(key=lambda item: item["score"], reverse=True)
        return {
            "reward_kind": reward_kind,
            "selected_option": ranked[0] if ranked else None,
            "ranked_options": ranked,
        }

    def _tag_weight(self, tag: str, reward_kind: RewardKind) -> float:
        if reward_kind == "p_item":
            return self.profile.preferred_p_item_tags.get(tag, 0.0)
        return self.profile.preferred_skill_tags.get(tag, 0.0)
