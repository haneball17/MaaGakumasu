"""observed case adapter + 手工録局 schema(M5:実機回放校验,§9 第 3 层)。

两层校验口径:
1. 全局口径:同卡组跑 N 局分布 vs 実機总分落点分位(tools/calibrate_roundsim.py)。
2. 逐回合口径(手工録局):実機每回合记 4-5 个数(出手牌/好調层/体力/回合得分),
   与模拟 trace 逐回合对比精确卡漂移(ManualGameRecord,録局文件后补不阻塞框架)。

実機数据缺口(observed case rinami_garakuta_road_20260709 実际持有):
- 有:R1 初始体力 28、Day5 后三围快照、R2 総合評価 4,756,391(優勝,順位画面)。
- 无:20 张逐卡清单(→ 预设重构构筑兜底,A10)、R1 单段最终分、R2 初始状态截图(A2)。
缺口的数值留 TODO 标注,不静默拟合(ADR-0001);待実機数据补校准。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, BaseModel, ConfigDict

from agent.hif.roundsim.spec import (
    PRESETS,
    PItems,
    CardInDeck,
    ExamSettings,
    ScenarioSpec,
    ParamsSnapshot,
    InitialExamState,
)
from agent.hif.roundsim.settings import R1_TURNS, R2_TURNS

_OBSERVED_CASES_DIR = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "observed_cases"


class ObservedCaseGap(Exception):
    """observed case 缺少构建 spec 必需字段(adapter 拒绝猜,列缺失项)。"""


def spec_from_observed_case(
    case_path: str | Path = "rinami_garakuta_road_20260709.json",
    round_tag: str = "r1",
) -> tuple[ScenarioSpec, dict]:
    """observed case JSON → ScenarioSpec(返回 spec + 数据缺口清单)。

    映射(只取実機记录,不补造):
    - 三围:initial_state.snapshots.observed_attributes + Day5 公開レッスン增量(最后记录值);
    - R1 初始体力:round1_initial 步骤 state_before.stamina;
    - R2 初始:実機未取证 → A2 假设(清零 + interval 実機体力 34),列入缺口;
    - 卡组:実機未落盘逐卡清单 → 内置莉波重构构筑兜底(A10);
    - 対手:produce_008 dump 区间(実機順位画面印证 R2 増分落在 -02 区间)。
    """
    path = case_path if isinstance(case_path, Path) else _OBSERVED_CASES_DIR / case_path
    case = json.loads(path.read_text(encoding="utf-8"))
    gaps: list[str] = []

    # 三围:快照 + 步骤 state_after 里的最后记录(実機记录链)
    snap = case.get("initial_state", {}).get("snapshots", {}).get("observed_attributes", {})
    params = ParamsSnapshot(vocal=snap.get("Vo", 0), dance=snap.get("Da", 0), visual=snap.get("Vi", 0))
    for step in case.get("steps", []):
        after = step.get("state_after") or {}
        if "Da" in after or "Vi" in after or "Vo" in after:
            params = ParamsSnapshot(
                vocal=after.get("Vo", params.vocal),
                dance=after.get("Da", params.dance),
                visual=after.get("Vi", params.visual),
            )

    # R1 初始体力(実機 round1_initial)
    r1_stamina = next(
        (s.get("state_before", {}).get("stamina") for s in case.get("steps", []) if s.get("step_id") == "round1_initial_manual"),
        None,
    )
    if r1_stamina is None:
        raise ObservedCaseGap("observed case 缺 round1_initial 步骤(初始体力)")

    gaps.append("卡组逐卡清单未记录(→ 内置重构构筑兜底,A10)")
    gaps.append("好調/集中初始値不在 case 内(→ 実機 session-20260815 观察值 6/6 注入)")

    preset = PRESETS["hif_r1_rinami" if round_tag == "r1" else "hif_r2_rinami"]
    initial = InitialExamState(
        stamina=r1_stamina if round_tag == "r1" else 34,
        good_condition_turns=6 if round_tag == "r1" else 0,
        focus=6 if round_tag == "r1" else 0,
        params=params,
    )
    if round_tag == "r2":
        gaps.append("R2 初始状态実機未取证(A2:buff 清零,体力 = interval 実機值 34)")
    spec = ScenarioSpec(
        scenario=preset.scenario.model_copy(update={"initial": initial}),
        exam_settings=ExamSettings(turns=R1_TURNS if round_tag == "r1" else R2_TURNS),
        opponent=preset.opponent,
        note=f"observed case adapter({path.name}, round={round_tag});缺口见 calibration 报告",
    )
    return spec, {"gaps": gaps}


def observed_final_scores(case_path: str | Path = "rinami_garakuta_road_20260709.json") -> dict[str, int | None]:
    """実機落点:R2 総合評価(round2_manual final_score)与 R1 单段分(未记录 → None)。"""
    path = case_path if isinstance(case_path, Path) else _OBSERVED_CASES_DIR / case_path
    case = json.loads(path.read_text(encoding="utf-8"))
    combined = next(
        (s.get("candidates", [{}])[0].get("metadata", {}).get("final_score") for s in case.get("steps", []) if s.get("step_id") == "round2_manual"),
        None,
    )
    return {"r1_final": None, "combined_final": combined}  # r1_final 待実機補録(TODO)


# ---------------------------------------------------------------------------
# 手工録局格式(逐回合口径,§9 実機配合项)
# ---------------------------------------------------------------------------


class ManualTurnRecord(BaseModel):
    """実機单回合手记 4-5 个数(可部分缺省,None = 未记录)。"""

    model_config = ConfigDict(extra="forbid")

    turn: int
    flow: str | None = None  # 流行属性
    played_cards: list[str] = Field(default_factory=list)  # 出手牌 label 序列(含追加発動)
    good_condition_turns: int | None = None  # 回合末好調層
    stamina: int | None = None  # 回合末体力
    turn_score: int | None = None  # 本回合得分


class ManualGameRecord(BaseModel):
    """手工録局一份(round 级);schema 一次定死,実機録局文件后补即用。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    case_id: str
    round_tag: str  # r1 / r2
    seed: int | None = None  # 若実機首手可复现(可选)
    turns: list[ManualTurnRecord] = Field(default_factory=list)
    final_score: int | None = None


def validate_trace_against_manual(trace, record: ManualGameRecord) -> dict:
    """模拟 trace vs 手工録局 逐回合对比 → 漂移报告(逐回合口径)。

    trace: TraceDocument(同 seed 局或代表局);返回 {turn: {field: (実機, 模拟)}} 差异表。
    """
    drifts: dict[int, dict] = {}
    by_turn = {t.turn: t for t in trace.turns}
    for rec in record.turns:
        sim = by_turn.get(rec.turn)
        if sim is None:
            drifts[rec.turn] = {"_missing": ("実機有记录", "模拟无此回合")}
            continue
        diff: dict = {}
        if rec.flow and rec.flow != sim.flow:
            diff["flow"] = (rec.flow, sim.flow)
        if rec.played_cards and rec.played_cards != sim.action.plays:
            diff["played_cards"] = (rec.played_cards, sim.action.plays)
        if rec.good_condition_turns is not None and rec.good_condition_turns != sim.state_after.good_condition_turns:
            diff["good"] = (rec.good_condition_turns, sim.state_after.good_condition_turns)
        if rec.stamina is not None and rec.stamina != sim.state_after.stamina:
            diff["stamina"] = (rec.stamina, sim.state_after.stamina)
        if rec.turn_score is not None and rec.turn_score != sim.turn_score:
            diff["turn_score"] = (rec.turn_score, sim.turn_score)
        if diff:
            drifts[rec.turn] = diff
    return drifts
