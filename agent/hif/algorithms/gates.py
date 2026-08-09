from __future__ import annotations

from agent.hif.algorithms.types import (
    RouteStep,
    HardGateResult,
    ProduceProfile,
    ScenarioConfig,
    CandidateAction,
    SimulationState,
    SoftGateAdjustment,
)


class HardGate:
    def check(self, state: SimulationState, step: RouteStep, candidate: CandidateAction) -> HardGateResult:
        forced = [action for action in step.candidates if action.forced]
        if forced and not candidate.forced:
            return HardGateResult(False, "当前步骤存在强制行动")

        interval_categories = {
            "interval_budget",
            "shop_purchase",
            "select_change",
            "drink",
            "skill_upgrade",
            "skill_customize",
            "stamina_recover",
            "finish_interval",
        }
        if step.phase == "interval" and candidate.category not in interval_categories:
            return HardGateResult(False, "Interval 仅允许预算决策")

        if state.stamina <= 10 and candidate.stamina_delta < 0 and candidate.category not in {"outing", "exam", "round_exam"}:
            return HardGateResult(False, "低体力禁止高风险推进")

        if candidate.category == "p_item" and step.phase != "selection_item":
            return HardGateResult(False, "当前阶段不允许 P 道具选择")

        return HardGateResult(True)


class SoftGate:
    def __init__(self, scenario: ScenarioConfig, profile: ProduceProfile):
        self.scenario = scenario
        self.profile = profile

    def apply(self, state: SimulationState, candidate: CandidateAction) -> SoftGateAdjustment:
        bias = 0.0
        reasons: list[str] = []

        if self.profile.build == "好調" and ("good_condition" in candidate.tags or "buff_main" in candidate.tags):
            bias += 5.0
            reasons.append("好调路线偏好")

        if f"{self.profile.first.lower()}_lesson" in candidate.tags:
            bias += 3.8
            reasons.append("主属性推进")
        elif f"{self.profile.second.lower()}_lesson" in candidate.tags:
            bias += 2.0
            reasons.append("副属性补足")

        if state.p_points < self.scenario.interval_targets["p_points"] and "ppoint_gain" in candidate.tags:
            bias += 2.6
            reasons.append("补 P 点缺口")

        if state.star_value < self.scenario.selection_targets["star_value"] and "star_gain" in candidate.tags:
            bias += 3.2
            reasons.append("补星性缺口")

        if state.deck_size > self.scenario.selection_targets["deck_size"] and candidate.category in {"consult", "finals_consult"}:
            bias += 1.5
            reasons.append("牌组偏厚时优先调整资源")

        return SoftGateAdjustment(bias_score=bias, bias_reasons=reasons)
