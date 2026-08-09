from __future__ import annotations

from typing import Any
from dataclasses import asdict, dataclass

from agent.hif.algorithms.gates import HardGate, SoftGate
from agent.hif.algorithms.types import (
    RouteStep,
    DecisionResult,
    HardGateResult,
    ImmediateScore,
    ProduceProfile,
    ScenarioConfig,
    CandidateAction,
    SimulationState,
    SoftGateAdjustment,
)
from agent.hif.algorithms.reducer import StateReducer, CandidateBuilder
from agent.hif.algorithms.scoring import ImmediateScorer


@dataclass(slots=True)
class _BeamEvaluation:
    action: CandidateAction
    hard_gate: HardGateResult
    soft_gate: SoftGateAdjustment
    immediate_score: ImmediateScore
    total_score: float
    top_reasons: list[str]
    confidence: float
    unknown_factors: list[str]


class BeamPlanner:
    def __init__(
        self,
        scenario: ScenarioConfig,
        profile: ProduceProfile,
        builder: CandidateBuilder,
        hard_gate: HardGate,
        soft_gate: SoftGate,
        scorer: ImmediateScorer,
        reducer: StateReducer,
    ):
        self.scenario = scenario
        self.profile = profile
        self.builder = builder
        self.hard_gate = hard_gate
        self.soft_gate = soft_gate
        self.scorer = scorer
        self.reducer = reducer

    def choose(self, steps: list[RouteStep], state: SimulationState) -> DecisionResult:
        step = steps[state.step_index]
        candidates = self.builder.build(step, state)
        evaluations = self._evaluate_candidates(steps, state, step, candidates)
        allowed = [item for item in evaluations if item.hard_gate.allowed]
        if not allowed:
            return DecisionResult(
                selected_action={"action_id": "", "name": "", "phase": step.phase},
                candidate_scores=[self._serialize_candidate_score(item) for item in evaluations],
                rule_hits=[item.hard_gate.blocked_reason for item in evaluations if item.hard_gate.blocked_reason],
                top_reasons=["没有可执行候选"],
                confidence=0.0,
                unknown_factors=["all_candidates_blocked"],
                fallback_reason="全部候选被 HardGate 阻断",
            )

        observed_action_id = step.metadata.get("observed_selected_action_id")
        observed_evaluation = next((item for item in allowed if item.action.action_id == observed_action_id), None)
        if observed_evaluation is not None:
            return DecisionResult(
                selected_action={
                    "action_id": observed_evaluation.action.action_id,
                    "name": observed_evaluation.action.name,
                    "category": observed_evaluation.action.category,
                    "phase": observed_evaluation.action.phase,
                },
                candidate_scores=[self._serialize_candidate_score(item) for item in evaluations],
                rule_hits=[
                    "observed_replay_forced_choice",
                    *[reason for item in evaluations for reason in ([item.hard_gate.blocked_reason] if item.hard_gate.blocked_reason else [])],
                ],
                top_reasons=["真实观测回放强制选择", *observed_evaluation.top_reasons],
                confidence=1.0,
                unknown_factors=observed_evaluation.unknown_factors,
            )

        allowed.sort(key=lambda item: item.total_score, reverse=True)
        best = allowed[0]
        second = allowed[1].total_score if len(allowed) > 1 else best.total_score - 5.0
        confidence = max(0.15, min(0.99, 0.55 + (best.total_score - second) / 25.0))

        return DecisionResult(
            selected_action={
                "action_id": best.action.action_id,
                "name": best.action.name,
                "category": best.action.category,
                "phase": best.action.phase,
            },
            candidate_scores=[self._serialize_candidate_score(item) for item in evaluations],
            rule_hits=[reason for item in evaluations for reason in ([item.hard_gate.blocked_reason] if item.hard_gate.blocked_reason else [])],
            top_reasons=best.top_reasons,
            confidence=round(confidence, 2),
            unknown_factors=best.unknown_factors,
        )

    def _evaluate_candidates(
        self,
        steps: list[RouteStep],
        state: SimulationState,
        step: RouteStep,
        candidates: list[CandidateAction],
    ) -> list[Any]:
        evaluations = []
        for candidate in candidates:
            hard = self.hard_gate.check(state, step, candidate)
            soft = self.soft_gate.apply(state, candidate)
            immediate = self.scorer.score(state, step, candidate, soft)
            future_score = 0.0
            if hard.allowed:
                next_state = self.reducer.apply(state, step, candidate)
                future_score = self._beam_score(
                    steps,
                    next_state,
                    self.scenario.lookahead_depth - 1,
                )

            total_score = immediate.total_score + future_score
            reasons = self._build_reasons(candidate, hard, soft, immediate)
            unknown = self._build_unknown_factors(candidate)
            evaluations.append(
                _BeamEvaluation(
                    action=candidate,
                    hard_gate=hard,
                    soft_gate=soft,
                    immediate_score=immediate,
                    total_score=round(total_score, 2),
                    top_reasons=reasons,
                    confidence=0.0,
                    unknown_factors=unknown,
                )
            )
        return evaluations

    def _beam_score(self, steps: list[RouteStep], state: SimulationState, depth: int) -> float:
        if depth <= 0 or state.step_index >= len(steps):
            return 0.0

        step = steps[state.step_index]
        candidates = self.builder.build(step, state)
        scored: list[float] = []
        for candidate in candidates:
            hard = self.hard_gate.check(state, step, candidate)
            if not hard.allowed:
                continue
            soft = self.soft_gate.apply(state, candidate)
            immediate = self.scorer.score(state, step, candidate, soft)
            next_state = self.reducer.apply(state, step, candidate)
            future = self._beam_score(steps, next_state, depth - 1)
            scored.append(immediate.total_score + future * 0.85)

        if not scored:
            return 0.0
        scored.sort(reverse=True)
        top = scored[: self.scenario.beam_width]
        return top[0]

    @staticmethod
    def _build_reasons(
        candidate: CandidateAction,
        hard_gate: HardGateResult,
        soft_gate: SoftGateAdjustment,
        immediate: ImmediateScore,
    ) -> list[str]:
        if not hard_gate.allowed:
            return [hard_gate.blocked_reason]

        reasons = []
        reasons.extend(soft_gate.bias_reasons[:2])
        if immediate.target_gap_score > 0:
            reasons.append("补阶段目标差距")
        if immediate.immediate_value > 0:
            reasons.append("即时收益为正")
        if candidate.category == "p_item":
            reasons.append("推进剧本道具协同")
        return reasons[:3] or ["默认安全推进"]

    @staticmethod
    def _build_unknown_factors(candidate: CandidateAction) -> list[str]:
        unknown = []
        if not candidate.tags:
            unknown.append("missing_tags")
        if candidate.category == "p_item" and not candidate.metadata.get("source_option_id"):
            unknown.append("missing_p_item_source")
        return unknown

    @staticmethod
    def _serialize_candidate_score(result: Any) -> dict[str, Any]:
        payload = asdict(result.immediate_score)
        return {
            "action_id": result.action.action_id,
            "action_name": result.action.name,
            "category": result.action.category,
            "total_score": result.total_score,
            "hard_gate": asdict(result.hard_gate),
            "soft_gate": asdict(result.soft_gate),
            "immediate_score": payload,
            "top_reasons": result.top_reasons,
            "unknown_factors": result.unknown_factors,
        }
