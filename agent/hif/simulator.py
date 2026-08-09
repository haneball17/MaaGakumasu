"""HIF 路线模拟器公开 API（facade）。

历史实现已按职责拆分到 `agent.hif.algorithms` 子包，本文件仅做 re-export，
保持 `from agent.hif.simulator import ...` 的对外导入路径不变。
"""

from agent.hif.algorithms.case import build_sample_hif_case, build_reward_options_from_data
from agent.hif.algorithms.types import (
    RouteStep,
    RewardKind,
    RoutePhase,
    RewardOption,
    CandidateScore,
    DecisionResult,
    HardGateResult,
    ImmediateScore,
    ProduceProfile,
    ScenarioConfig,
    CandidateAction,
    HIFDecisionData,
    SimulationState,
    SelectionSnapshot,
    SoftGateAdjustment,
    HIFEvaluationConfig,
    HIFEvaluationReport,
    SelectionMemoryProfile,
    StarEvaluationBreakdown,
    FinalsEvaluationBreakdown,
    SelectionEvaluationBreakdown,
)
from agent.hif.algorithms.config import (
    load_decision_data,
    build_initial_state,
    load_produce_profile,
    load_scenario_config,
    build_default_produce_profile,
    build_default_scenario_config,
    build_default_hif_evaluation_config,
)
from agent.hif.algorithms.orchestrator import replay_hif_case, simulate_hif_route, simulate_hif_rewards, build_hif_evaluation_report

__all__ = [
    "CandidateAction",
    "CandidateScore",
    "DecisionResult",
    "FinalsEvaluationBreakdown",
    "HardGateResult",
    "HIFDecisionData",
    "HIFEvaluationConfig",
    "HIFEvaluationReport",
    "ImmediateScore",
    "ProduceProfile",
    "RewardKind",
    "RewardOption",
    "RoutePhase",
    "RouteStep",
    "ScenarioConfig",
    "SelectionEvaluationBreakdown",
    "SelectionMemoryProfile",
    "SelectionSnapshot",
    "SimulationState",
    "SoftGateAdjustment",
    "StarEvaluationBreakdown",
    "build_default_hif_evaluation_config",
    "build_default_produce_profile",
    "build_default_scenario_config",
    "build_hif_evaluation_report",
    "build_initial_state",
    "build_reward_options_from_data",
    "build_sample_hif_case",
    "load_decision_data",
    "load_produce_profile",
    "load_scenario_config",
    "replay_hif_case",
    "simulate_hif_rewards",
    "simulate_hif_route",
]
