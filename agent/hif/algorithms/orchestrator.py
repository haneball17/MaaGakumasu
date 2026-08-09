from __future__ import annotations

from copy import deepcopy
from typing import Any
from pathlib import Path
from dataclasses import asdict

from agent.hif.algorithms.case import build_reward_options_from_data
from agent.hif.algorithms.gates import HardGate, SoftGate
from agent.hif.algorithms.types import (
    RouteStep,
    RewardKind,
    ProduceProfile,
    ScenarioConfig,
    CandidateAction,
    HIFDecisionData,
    SimulationState,
    HIFEvaluationConfig,
    StarEvaluationBreakdown,
    FinalsEvaluationBreakdown,
    SelectionEvaluationBreakdown,
)
from agent.hif.algorithms.config import build_initial_state
from agent.hif.algorithms.planner import BeamPlanner
from agent.hif.algorithms.reducer import StateReducer, PhaseResolver, MemoryProjector, SnapshotBuilder, CandidateBuilder
from agent.hif.algorithms.scoring import RewardScorer, ImmediateScorer


def simulate_hif_route(
    scenario: ScenarioConfig,
    profile: ProduceProfile,
    route_steps: list[RouteStep],
    initial_state: SimulationState | None = None,
) -> dict[str, Any]:
    builder = CandidateBuilder()
    hard_gate = HardGate()
    soft_gate = SoftGate(scenario, profile)
    scorer = ImmediateScorer(scenario)
    reducer = StateReducer()
    planner = BeamPlanner(scenario, profile, builder, hard_gate, soft_gate, scorer, reducer)

    state = deepcopy(initial_state or build_initial_state())
    step_results: list[dict[str, Any]] = []

    while state.step_index < len(route_steps):
        step = route_steps[state.step_index]
        state.phase = PhaseResolver.resolve(step)
        state.day_number = step.day_number
        decision = planner.choose(route_steps, state)
        selected_action = decision.selected_action
        if not selected_action["action_id"]:
            step_results.append(
                {
                    "step_id": step.step_id,
                    "label": step.label,
                    "phase": step.phase,
                    "decision": asdict(decision),
                    "state_after": asdict(state),
                }
            )
            break

        action = next(candidate for candidate in step.candidates if candidate.action_id == selected_action["action_id"])
        state = reducer.apply(state, step, action)

        step_results.append(
            {
                "step_id": step.step_id,
                "label": step.label,
                "phase": step.phase,
                "decision": asdict(decision),
                "state_after": asdict(state),
            }
        )

        if step.phase == "selection_exam" and step.day_number == scenario.selection_days:
            snapshot = SnapshotBuilder.build(state)
            memory = MemoryProjector.build(snapshot)
            state.snapshots["selection_snapshot"] = asdict(snapshot)
            state.snapshots["selection_memory_profile"] = asdict(memory)

    snapshot_dict = state.snapshots.get("selection_snapshot")
    memory_dict = state.snapshots.get("selection_memory_profile")
    if not snapshot_dict:
        snapshot = SnapshotBuilder.build(state)
        memory = MemoryProjector.build(snapshot)
        snapshot_dict = asdict(snapshot)
        memory_dict = asdict(memory)

    return {
        "scenario": asdict(scenario),
        "profile": asdict(profile),
        "steps": step_results,
        "selection_snapshot": snapshot_dict,
        "selection_memory_profile": memory_dict,
        "final_state": asdict(state),
    }


def simulate_hif_rewards(
    profile: ProduceProfile,
    data: HIFDecisionData,
    reward_kind: RewardKind,
    limit: int = 5,
) -> dict[str, Any]:
    options = build_reward_options_from_data(data, reward_kind)[:limit]
    scorer = RewardScorer(profile)
    return scorer.score(reward_kind, options)


def build_hif_evaluation_report(
    evaluation_config: HIFEvaluationConfig,
    simulation_result: dict[str, Any],
    scenario: ScenarioConfig,
) -> dict[str, Any]:
    selection_snapshot = simulation_result["selection_snapshot"]
    selection_memory = simulation_result["selection_memory_profile"]
    final_state = simulation_result["final_state"]

    selection_evaluation = SelectionEvaluationBreakdown(
        base_attribute_total=evaluation_config.base_attribute_total,
        flex_attribute_total=evaluation_config.flex_attribute_total,
        selection_attribute_total=evaluation_config.selection_attribute_total,
        base_ratio=evaluation_config.base_ratio,
        flex_ratio=evaluation_config.flex_ratio,
        star_completion=_completion_ratio(selection_snapshot["star_value"], evaluation_config.selection_star_reward_cap),
        trial_readiness_completion=_completion_ratio(
            selection_snapshot["trial_readiness"], scenario.selection_targets["trial_readiness"]
        ),
        memory_quality_completion=_completion_ratio(
            selection_snapshot["memory_quality"], scenario.selection_targets["memory_quality"]
        ),
        deck_quality_completion=_completion_ratio(
            selection_snapshot["deck_quality"], scenario.selection_targets["deck_quality"]
        ),
        support_progress_completion=_completion_ratio(
            selection_snapshot["support_event_progress"], scenario.selection_targets["support_event_progress"]
        ),
    )

    finals_evaluation = FinalsEvaluationBreakdown(
        round1_weight=evaluation_config.round1_weight,
        round2_weight=evaluation_config.round2_weight,
        round1_ratio=evaluation_config.round1_ratio,
        round2_ratio=evaluation_config.round2_ratio,
        interval_budget_target=scenario.interval_targets["interval_budget"],
        interval_budget_completion=_completion_ratio(
            final_state["interval_budget"], scenario.interval_targets["interval_budget"]
        ),
        finals_readiness_completion=_completion_ratio(
            final_state["finals_readiness"], scenario.finals_targets["finals_readiness"]
        ),
        star_completion=_completion_ratio(final_state["star_value"], scenario.finals_targets["star_value"]),
        deck_quality_completion=_completion_ratio(
            final_state["deck_quality"], scenario.finals_targets["deck_quality"]
        ),
        memory_quality_completion=_completion_ratio(
            final_state["memory_quality"], scenario.finals_targets["memory_quality"]
        ),
    )

    major_sources_total = (
        evaluation_config.selection_star_reward_cap
        + evaluation_config.public_lesson_star_total
        + evaluation_config.hif_wappen_star_cap
    )
    star_evaluation = StarEvaluationBreakdown(
        current_star_value=final_state["star_value"],
        selection_star_reward_cap=evaluation_config.selection_star_reward_cap,
        selection_star_reward_cap_with_bonus=evaluation_config.selection_star_reward_cap_with_bonus,
        public_lesson_star_total=evaluation_config.public_lesson_star_total,
        hif_wappen_star_cap=evaluation_config.hif_wappen_star_cap,
        relative_to_selection_cap=_completion_ratio(
            final_state["star_value"], evaluation_config.selection_star_reward_cap
        ),
        relative_to_bonus_cap=_completion_ratio(
            final_state["star_value"], evaluation_config.selection_star_reward_cap_with_bonus
        ),
        relative_to_major_sources=_completion_ratio(final_state["star_value"], major_sources_total),
        level=_star_level(final_state["star_value"], evaluation_config),
    )

    overall_assessment = {
        "strengths": _build_strengths(selection_evaluation, finals_evaluation, star_evaluation),
        "weaknesses": _build_weaknesses(selection_evaluation, finals_evaluation, star_evaluation),
        "notes": [
            "当前报表中的完成度是代理指标，不是官方最终总评公式。",
            evaluation_config.low_attribute_penalty_note,
            evaluation_config.attribute_adaptation_note,
            f"SelectionMemoryProfile 当前主保留字段：star={selection_memory['star_value']} deck={selection_memory['deck_size']}",
        ],
    }

    return {
        "evaluation_config": asdict(evaluation_config),
        "selection_evaluation": asdict(selection_evaluation),
        "finals_evaluation": asdict(finals_evaluation),
        "star_evaluation": asdict(star_evaluation),
        "overall_assessment": overall_assessment,
    }


def replay_hif_case(
    scenario: ScenarioConfig,
    profile: ProduceProfile,
    case_file: str | Path,
    initial_state: SimulationState | None = None,
) -> dict[str, Any]:
    from agent.hif.observed_case import (  # noqa: I001 延迟导入避免与 observed_case 的循环依赖
        build_initial_state_from_observed_case,
        build_route_steps_from_observed_case,
        load_observed_hif_case,
    )

    case = load_observed_hif_case(case_file)
    route_steps = build_route_steps_from_observed_case(case)
    replay_initial_state = initial_state or build_initial_state_from_observed_case(case)
    result = simulate_hif_route(scenario, profile, route_steps, initial_state=replay_initial_state)
    result["observed_case"] = {
        "case_id": case.case_id,
        "profile": case.profile,
        "step_count": len(case.steps),
        "random_event_types": [event.event_type for event in case.observed_random_events],
        "recognition_screen_states": [hint.screen_state for hint in case.recognition_hints],
        "open_questions": case.open_questions,
    }
    return result


def _completion_ratio(current: int | float, target: int | float) -> float:
    if target <= 0:
        return 0.0
    return round(current / target, 4)


def _star_level(current_star: int, config: HIFEvaluationConfig) -> str:
    if current_star < config.selection_star_reward_cap * 0.4:
        return "偏低"
    if current_star < config.selection_star_reward_cap * 0.8:
        return "达标"
    return "偏高"


def _build_strengths(
    selection: SelectionEvaluationBreakdown,
    finals: FinalsEvaluationBreakdown,
    star: StarEvaluationBreakdown,
) -> list[str]:
    strengths = []
    if selection.trial_readiness_completion >= 1.0:
        strengths.append("选拔试验准备度达标")
    if selection.deck_quality_completion >= 1.0:
        strengths.append("选拔阶段牌组质量达标")
    if finals.finals_readiness_completion >= 1.0:
        strengths.append("本战准备度达标")
    if star.level == "偏高":
        strengths.append("当前星性处于偏高区间")
    if finals.interval_budget_completion >= 1.0:
        strengths.append("Interval 预算达标")
    return strengths or ["当前样本已形成基础可通关框架"]


def _build_weaknesses(
    selection: SelectionEvaluationBreakdown,
    finals: FinalsEvaluationBreakdown,
    star: StarEvaluationBreakdown,
) -> list[str]:
    weaknesses = []
    if selection.memory_quality_completion < 1.0:
        weaknesses.append("选拔阶段记忆质量仍未达目标")
    if finals.memory_quality_completion < 1.0:
        weaknesses.append("本战记忆质量仍偏低")
    if star.level == "偏低":
        weaknesses.append("当前星性偏低，后续应提高星性获取效率")
    if finals.star_completion < 1.0:
        weaknesses.append("本战阶段星性未达到目标线")
    return weaknesses or ["当前报表未发现明显硬短板，但仍需实机验证"]
