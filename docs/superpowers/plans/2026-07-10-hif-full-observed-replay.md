# HIF 全量实机回放与审计报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `rinami_garakuta_road_20260709` 从 7 个压缩关键帧扩充为 33 个有证据的实机步骤，并提供可定位状态差异、策略偏好与证据缺口的回放审计报告。

**Architecture:** 继续让 observed case JSON 保持唯一观测事实来源，`ObservedHIFCase` 只负责加载、校验、转换和报告；不把尚未证实的收益、候选池或 Interval 消费顺序伪造成模拟结果。`replay_hif_case` 仍按真实 `selected_action_id` 强制回放，但新增报告从原有候选评分中推导“非强制时 planner 的偏好”，并显式报告跨步骤状态不连续。

**Tech Stack:** Python 3.12 dataclasses / stdlib `json`，现有 `pytest`，`tools/simulate_hif.py` CLI，Prettier JSON 检查。

---

## 范围与非目标

- 本计划只完成“完整可审计的 observed replay”这一独立切片；不实现 `IntervalDecisionPlanner`、饮料/变卡评分器、回忆再生成评分器，也不接 OCR 或实机点击。
- 所有候选、数值、卡牌替换和截图路径必须来自 `docs/hif/finals-daily-log.md`。文档只确认“进入了但未完成”的事件，保留在 `observed_random_events`，不得塞入可强制回放的 `steps`。
- 已知观测断点必须保留：Day5 结算 `Da=2494` 与 Day4 初始 `Da=2603`、`P=200 -> 250` 没有完整证据链；Interval `P=580 -> 260` 也没有逐笔消费记录。审计报告应把它们标为差异，不得用虚构 delta 消除。
- 不改动 `README.md`，也不更改现有局内出牌模块 `agent/hif/decisions/`。

## 文件结构

- Modify: `agent/hif/simulator.py:9, 1446-1471`
  - 增加结算/回忆阶段类型；在 observed replay 结果中附加审计报告。
- Modify: `agent/hif/observed_case.py:100-196`
  - 提供纯数据的 state diff、跨步骤连续性检查和 replay report 构造器。
- Modify: `assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json`
  - 将数据扩充为 33 个已完成观测步骤，保留所有不完整观测为事件/开放问题。
- Modify: `tools/simulate_hif.py:40-124`
  - 新增 `report_hif_case` 子命令以及紧凑 text 输出。
- Modify: `tests/test_hif_decision.py:90-220`
  - 将 fixture 断言升级为全量流程、状态断点、审计报告和 CLI 行为测试。
- Modify: `docs/hif/hif-simulator-flow-design.md`
  - 在“阶段 1”下记录回放数据已具备 33 个证据步骤；继续注明真实候选池和策略替换尚未实现。

## 观测步骤清单

写入 JSON 的 `steps` 必须严格按下列顺序出现；每项的 `metadata.evidence` 使用 `finals-daily-log.md` 中对应截图文件名，未知收益使用 `metadata.unknown_fields` 而不是编造数值。

| # | `step_id` | 强制回放 action | 已确认事实 |
| --- | --- | --- | --- |
| 1 | `finals_day6_schedule_select` | `day6_select_vo_lesson` | `Vo / Da / Vi` 三个授業候选，初始 `35/35`、P `200` |
| 2 | `finals_day6_vo_option` | `day6_option_yoyuu_desu` | `余裕です！`，体力 `-5`，Vo `+180` |
| 3 | `finals_day6_select_change_reroll` | `day6_reroll_target_cards` | 目标卡候选从“あと3回”变为“あと2回” |
| 4 | `finals_day6_select_change_target` | `day6_target_hajimari_no_aizu` | 目标 A `始まりの合図` |
| 5 | `finals_day6_select_change_source` | `day6_source_daitan_futeki` | 源 B `大胆不敵` |
| 6 | `finals_day6_select_change_confirm` | `day6_confirm_change` | `大胆不敵 -> 始まりの合図` |
| 7 | `finals_day5_public_lesson_select` | `day5_da_public_lesson_sp` | Da/SP，`-8`，实际 `Da +185`、`Vi +28` |
| 8 | `finals_day4_gift_select` | `day4_select_gift` | `差し入れ`，P `+80` |
| 9 | `finals_day4_drink_select` | `day4_drink_senburi_soda` | `センブリソーダ` |
| 10 | `finals_day4_skill_reroll_first` | `day4_reroll_skill_cards_first` | 技能奖励第 1 次重抽 |
| 11 | `finals_day4_skill_reroll_second` | `day4_reroll_skill_cards_second` | 技能奖励第 2 次重抽 |
| 12 | `finals_day4_skill_select` | `day4_skill_hajimari_no_aizu` | 选择 `始まりの合図` |
| 13 | `finals_day4_drink_overflow_resolve` | `day4_keep_four_drinks` | 新饮料 2、容量暂记 4、最终保留 4 |
| 14 | `finals_day3_schedule_select` | `day3_select_vi_lesson` | `Vo / Da / Vi` 三个授業候选 |
| 15 | `finals_day3_vi_option` | `day3_option_nagai_michi` | `長い道のりでした`，体力 `-5`，Vi `+180` |
| 16 | `finals_day3_select_change_target` | `day3_target_hajimari_no_aizu` | 目标 A `始まりの合図` |
| 17 | `finals_day3_select_change_source` | `day3_source_hajimari_no_aizu` | 源 B 同名卡 |
| 18 | `finals_day3_select_change_confirm` | `day3_confirm_same_name_change` | `始まりの合図 -> 始まりの合図` |
| 19 | `finals_day2_public_lesson_select` | `day2_da_public_lesson_sp` | Da/SP，`-8`，P `+50`，实际 `Da +287`、`Vi +114` |
| 20 | `finals_day2_drink_overflow_resolve` | `day2_keep_observed_drinks` | 2 个新饮料，提示已为 `あと0個選択` |
| 21 | `finals_day1_consult_finish` | `day1_finish_without_purchase` | 商店不购买，保留 P `380` |
| 22 | `round1_initial_manual` | `round1_manual_play` | Vi、9 回合、初始手牌与手动打分 |
| 23 | `interval_deck_inspect` | `interval_inspect_twenty_cards` | 持有技能卡 `20` 张 |
| 24 | `interval_customize_card_select` | `interval_select_spprechchor_plus` | 选择 `シュプレヒコール+` |
| 25 | `interval_customize_menu_select` | `interval_choose_focus_cost_down` | `集中コスト値-`，标价 `40` |
| 26 | `interval_customize_execute` | `interval_execute_customize` | 已见总 P `580 -> 260`，逐笔流水未知 |
| 27 | `round2_manual` | `round2_manual_play` | 手动打分，最终 `4,756,391` |
| 28 | `score_settlement_continue` | `settlement_continue` | `優勝`、继续结算 |
| 29 | `live_skip` | `live_fast_forward` | 横屏 Live 快进 |
| 30 | `memory_photo_select` | `memory_photo_next` | 照片选择后“次へ” |
| 31 | `memory_photo_confirm` | `memory_photo_confirm` | “決定” |
| 32 | `memory_generate` | `memory_generate_card` | “生成” |
| 33 | `memory_preview` | `memory_accept` | `S4+`、`存在感+`、可再生成 1 次 |

`day4_p_item_select_change_partial` 和未执行的 `interval_recover_preview` 只记录在 `observed_random_events`：前者缺少目标/源卡和确认结果，后者只确认 `260 -> 250` 预览、没有确认执行。

### Task 1: 全量 observed case 与阶段类型

**Files:**

- Modify: `tests/test_hif_decision.py:90-148`
- Modify: `agent/hif/simulator.py:9`
- Modify: `assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json`

- [ ] **Step 1: 先写失败的全量 fixture 断言**

在 `tests/test_hif_decision.py` 添加并替换原先的 7-step 断言：

```python
def test_full_observed_hif_case_preserves_confirmed_steps_and_unknowns():
    case = load_observed_hif_case("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")

    assert case.initial_state["stamina"] == 35
    assert case.initial_state["p_points"] == 200
    assert len(case.steps) == 33
    assert [step.step_id for step in case.steps[:7]] == [
        "finals_day6_schedule_select",
        "finals_day6_vo_option",
        "finals_day6_select_change_reroll",
        "finals_day6_select_change_target",
        "finals_day6_select_change_source",
        "finals_day6_select_change_confirm",
        "finals_day5_public_lesson_select",
    ]
    assert case.steps[-1].phase == "memory_generation"
    assert case.steps[-1].metadata["screen_state"] == "memory_preview"

    events = {event.metadata["event_id"]: event for event in case.observed_random_events}
    assert events["day4_p_item_select_change_partial"].metadata["resolution_status"] == "partial"
    assert events["interval_recover_preview"].metadata["executed"] is False
```

- [ ] **Step 2: 验证测试当前失败**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_full_observed_hif_case_preserves_confirmed_steps_and_unknowns -q
```

Expected: FAIL，因为当前 fixture 的初始状态是 Day3/4 的压缩帧、仅有 7 步，且 `RoutePhase` 不含 `memory_generation`。

- [ ] **Step 3: 扩展阶段类型，不改变既有阶段的评分语义**

将 `agent/hif/simulator.py` 顶部的类型替换为：

```python
RoutePhase = Literal[
    "selection",
    "selection_exam",
    "selection_item",
    "finals_prepare",
    "round1",
    "interval",
    "round2",
    "score_settlement",
    "memory_generation",
]
```

`ImmediateScorer._score_target_gap` 不要增加针对新阶段的启发式分支；它们将继续走现有 finals 默认分支。为 Interval 牌库查看增加一个仅放行的类别，避免全量 replay 在第 23 步被 `HardGate` 阻断：

```python
        interval_categories = {
            "interval_budget",
            "deck_inspect",
            "shop_purchase",
            "select_change",
            "drink",
            "skill_upgrade",
            "skill_customize",
            "stamina_recover",
            "finish_interval",
        }
```

- [ ] **Step 4: 将 JSON 写成 33 个证据步骤**

替换 fixture 的 `initial_state`，保留抽象模拟字段，同时将真实参数仅放进 `snapshots["observed_attributes"]`：

```json
"initial_state": {
    "phase": "finals_prepare",
    "day_number": 6,
    "stamina": 35,
    "max_stamina": 35,
    "p_points": 200,
    "star_value": 0,
    "deck_size": 20,
    "trial_readiness": 0,
    "memory_quality": 0,
    "deck_quality": 0,
    "finals_readiness": 0,
    "interval_budget": 0,
    "support_event_progress": 0,
    "skill_tag_counts": {},
    "p_item_tag_counts": {},
    "snapshots": {
        "observed_attributes": {"Vo": 936, "Da": 2309, "Vi": 1853}
    }
}
```

按上方“观测步骤清单”写入全部 33 个对象。每个对象均含 `step_id`、`label`、`phase`、`day_number`、`selected_action_id`、至少一个带 `action_id` / `name` / `category` 的 candidate，以及 `metadata.screen_state` 与 `metadata.evidence`。需要保留完整状态的关键锚点如下：

```json
{
    "step_id": "finals_day5_public_lesson_select",
    "state_before": {"stamina": 30, "p_points": 200, "Vo": 1116, "Da": 2309, "Vi": 1853},
    "state_after": {"stamina": 22, "p_points": 200, "Vo": 1116, "Da": 2494, "Vi": 1881},
    "candidates": [{
        "action_id": "day5_da_public_lesson_sp",
        "name": "Da.公開レッスン",
        "category": "public_lesson",
        "tags": ["Da", "SP"],
        "stamina_delta": -8,
        "metadata": {
            "preview_delta": {"star": 30, "Da": 120, "Vi": 20},
            "attribute_bonus": {"Da": 0.549, "Vi": 0.43},
            "result_delta": {"Da": 185, "Vi": 28}
        }
    }]
}
```

对不连续观测，将下一锚点的 `state_before` 原样记录并显式标注来源，而不是篡改前一步：

```json
"metadata": {
    "screen_state": "finals_action_select",
    "evidence": ["MuMu-20260709-160445-070.png"],
    "observation_note": "与前一结算存在未观测资源变化；由审计报告输出 continuity gap"
}
```

Interval 执行步骤使用可通过现有 Gate 的 `skill_customize` 类别，并注明总额而非虚构消费明细：

```json
{
    "step_id": "interval_customize_execute",
    "phase": "interval",
    "selected_action_id": "interval_execute_customize",
    "state_before": {"stamina": 34, "p_points": 580, "deck_size": 20},
    "state_after": {"stamina": 34, "p_points": 260, "deck_size": 22},
    "metadata": {
        "screen_state": "skill_customize_success",
        "unknown_fields": ["interval_purchase_ledger"],
        "observation_note": "只确认总 P 点与牌库数量，逐笔购买/交换尚未获得证据"
    },
    "candidates": [{
        "action_id": "interval_execute_customize",
        "name": "シュプレヒコール+：集中コスト値-",
        "category": "skill_customize",
        "tags": ["interval", "customize", "key_card"],
        "metadata": {"card": "シュプレヒコール+", "customize_cost": 40}
    }]
}
```

在 `observed_random_events` 中增加这两个未完成事件：

```json
{
    "event_type": "select_change",
    "event_id": "day4_p_item_select_change_partial",
    "screen_state": "select_change_target",
    "trigger": "p_item_select_change",
    "resolution_status": "partial",
    "unknown_fields": ["target_candidates", "selected_target", "selected_source", "conversion_result"]
},
{
    "event_type": "stamina_recover",
    "event_id": "interval_recover_preview",
    "screen_state": "stamina_recover_confirm",
    "executed": false,
    "preview": {"stamina": "34 -> 35", "p_points": "260 -> 250"}
}
```

- [ ] **Step 5: 格式化 JSON 并验证全量 fixture**

Run:

```powershell
rtk proxy npx prettier --write "assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json"
rtk proxy python -m pytest tests/test_hif_decision.py::test_full_observed_hif_case_preserves_confirmed_steps_and_unknowns -q
```

Expected: Prettier 以 4 空格写回；pytest PASS。

- [ ] **Step 6: 提交这一个可运行的数据切片**

```powershell
rtk git add agent/hif/simulator.py assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json tests/test_hif_decision.py
rtk git commit -m "feat(hif): 补全实机回放步骤"
```

Expected: 一个提交只包含阶段类型、Gate 放行、fixture 与对应测试；不包含 `README.md`。

### Task 2: observed state diff 与回放审计报告

**Files:**

- Modify: `tests/test_hif_decision.py:151-220`
- Modify: `agent/hif/observed_case.py:100-196`
- Modify: `agent/hif/simulator.py:1446-1471`

- [ ] **Step 1: 写失败的报告测试**

在 `tests/test_hif_decision.py` 添加：

```python
def test_observed_replay_report_exposes_state_diffs_and_planner_preference():
    scenario = build_default_scenario_config()
    profile = build_default_produce_profile(load_decision_data())

    result = replay_hif_case(
        scenario,
        profile,
        "assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json",
    )

    report = result["observed_replay_report"]
    assert report["summary"] == {
        "step_count": 33,
        "random_event_count": 4,
        "recognition_hint_count": len(report["recognition_screen_states"]),
    }
    assert report["phase_order"][-2:] == ["score_settlement", "memory_generation"]
    assert report["steps"][0]["observed_action_id"] == "day6_select_vo_lesson"
    assert report["steps"][0]["planner_preference_action_id"] is not None
    assert any(gap["from_step_id"] == "finals_day5_public_lesson_select" for gap in report["continuity_gaps"])
    assert report["steps"][-1]["state_changes"] == [{
        "field": "memory_rank",
        "before": None,
        "after": "S4+",
        "before_known": False,
        "after_known": True,
    }]
```

`random_event_count` 在全量 fixture 中应是 4：Day4 饮料上限、Day4 未完成的 P item 变卡、Day3 同名变卡、Day2 饮料上限。

- [ ] **Step 2: 确认测试失败**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_observed_replay_report_exposes_state_diffs_and_planner_preference -q
```

Expected: FAIL，当前 `replay_hif_case` 没有 `observed_replay_report`。

- [ ] **Step 3: 在 adapter 中实现无副作用的审计构造器**

在 `agent/hif/observed_case.py` 的转换函数后添加以下完整实现。它只能读取 `case` 与已序列化的 replay 结果，不得修改 `SimulationState` 或评分结果：

```python
def _state_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field_name in sorted(set(before) | set(after)):
        before_known = field_name in before
        after_known = field_name in after
        before_value = before.get(field_name)
        after_value = after.get(field_name)
        if before_known and after_known and before_value == after_value:
            continue
        changes.append(
            {
                "field": field_name,
                "before": before_value,
                "after": after_value,
                "before_known": before_known,
                "after_known": after_known,
            }
        )
    return changes


def _planner_preference(decision: dict[str, Any]) -> str | None:
    allowed = [
        candidate
        for candidate in decision["candidate_scores"]
        if candidate["hard_gate"]["allowed"]
    ]
    if not allowed:
        return None
    return max(allowed, key=lambda candidate: candidate["total_score"])["action_id"]


def build_observed_replay_report(case: ObservedHIFCase, replay_result: dict[str, Any]) -> dict[str, Any]:
    replay_steps = {step["step_id"]: step for step in replay_result["steps"]}
    report_steps: list[dict[str, Any]] = []
    continuity_gaps: list[dict[str, Any]] = []
    previous_state_after: dict[str, Any] | None = None
    previous_step_id: str | None = None

    for observed_step in case.steps:
        replay_step = replay_steps[observed_step.step_id]
        decision = replay_step["decision"]
        planner_preference_action_id = _planner_preference(decision)
        if previous_state_after is not None and observed_step.state_before:
            changes = _state_changes(previous_state_after, observed_step.state_before)
            if changes:
                continuity_gaps.append(
                    {
                        "from_step_id": previous_step_id,
                        "to_step_id": observed_step.step_id,
                        "state_changes": changes,
                    }
                )

        report_steps.append(
            {
                "step_id": observed_step.step_id,
                "phase": observed_step.phase,
                "observed_action_id": observed_step.selected_action_id,
                "planner_preference_action_id": planner_preference_action_id,
                "planner_matches_observed": planner_preference_action_id == observed_step.selected_action_id,
                "state_changes": _state_changes(observed_step.state_before, observed_step.state_after),
            }
        )
        if observed_step.state_after:
            previous_state_after = observed_step.state_after
            previous_step_id = observed_step.step_id

    recognition_screen_states = [hint.screen_state for hint in case.recognition_hints]
    return {
        "case_id": case.case_id,
        "phase_order": [step.phase for step in case.steps],
        "recognition_screen_states": recognition_screen_states,
        "summary": {
            "step_count": len(case.steps),
            "random_event_count": len(case.observed_random_events),
            "recognition_hint_count": len(recognition_screen_states),
        },
        "steps": report_steps,
        "continuity_gaps": continuity_gaps,
    }
```

- [ ] **Step 4: 将审计报告附加到 replay API**

修改 `agent/hif/simulator.py` 的局部 import 与尾部：

```python
    from agent.hif.observed_case import (
        build_initial_state_from_observed_case,
        build_observed_replay_report,
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
    result["observed_replay_report"] = build_observed_replay_report(case, result)
    return result
```

- [ ] **Step 5: 运行报告测试和既有 replay 回归**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_observed_replay_report_exposes_state_diffs_and_planner_preference tests/test_hif_decision.py::test_replay_observed_hif_case_forces_observed_selection tests/test_hif_decision.py::test_replay_observed_hif_case_syncs_observed_state_after -q
```

Expected: PASS。特别确认 `planner_preference_action_id` 只是按评分推导的偏好，而 `DecisionResult.selected_action` 仍由 `observed_replay_forced_choice` 强制为实测选择。

- [ ] **Step 6: 提交审计 API 与测试**

```powershell
rtk git add agent/hif/observed_case.py agent/hif/simulator.py tests/test_hif_decision.py
rtk git commit -m "feat(hif): 增加实测回放审计报告"
```

Expected: 提交不包含 CLI、设计文档或 `README.md`。

### Task 3: CLI 报告、文档同步与完整验证

**Files:**

- Modify: `tools/simulate_hif.py:40-124`
- Modify: `tests/test_hif_decision.py`
- Modify: `docs/hif/hif-simulator-flow-design.md`

- [ ] **Step 1: 写 CLI JSON 输出测试**

在 `tests/test_hif_decision.py` 中新增 subprocess 测试：

```python
import subprocess
import sys


def test_report_hif_case_cli_returns_auditable_json():
    completed = subprocess.run(
        [
            sys.executable,
            "tools/simulate_hif.py",
            "report_hif_case",
            "--case-file",
            "assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json",
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    report = json.loads(completed.stdout)
    assert report["case_id"] == "rinami_garakuta_road_20260709"
    assert report["summary"]["step_count"] == 33
    assert report["continuity_gaps"]
```

- [ ] **Step 2: 验证 CLI 测试当前失败**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_report_hif_case_cli_returns_auditable_json -q
```

Expected: FAIL，因为 parser 尚未注册 `report_hif_case`。

- [ ] **Step 3: 增加 `report_hif_case` 子命令和 text 输出**

在 parser 中紧接 `replay_hif_case` 后注册命令：

```python
    report = subparsers.add_parser("report_hif_case", parents=[common])
    report.add_argument("--case-file", required=True)
```

添加纯输出函数：

```python
def _print_text_observed_report(report: dict) -> None:
    summary = report["summary"]
    print(f"Observed case: {report['case_id']}")
    print(
        f"steps={summary['step_count']} random_events={summary['random_event_count']} "
        f"recognition_hints={summary['recognition_hint_count']}"
    )
    print(f"continuity_gaps={len(report['continuity_gaps'])}")
    for gap in report["continuity_gaps"]:
        fields = ", ".join(change["field"] for change in gap["state_changes"])
        print(f"  {gap['from_step_id']} -> {gap['to_step_id']}: {fields}")
```

在 `main()` 的 `replay_hif_case` 分支前添加：

```python
    if args.command == "report_hif_case":
        replay_result = replay_hif_case(scenario, profile, args.case_file)
        report = replay_result["observed_replay_report"]
        if args.output == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_text_observed_report(report)
        return 0
```

- [ ] **Step 4: 更新设计文档的阶段状态**

在 `docs/hif/hif-simulator-flow-design.md` 的“阶段 1：schema 和 replay”后追加以下事实说明：

```markdown
阶段 1 的 observed case 已扩为 33 个有截图/实机记录支撑的步骤，并可输出每步状态 diff、跨步骤状态断点及 planner 偏好与实测选择的对照。该报告用于暴露证据缺口，不代表未观测状态已被推断补全。
```

- [ ] **Step 5: 运行全部相关验证**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py -q
rtk proxy python -m py_compile agent/hif/simulator.py agent/hif/observed_case.py tools/simulate_hif.py
rtk proxy npx prettier --check "assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json"
rtk proxy python tools/simulate_hif.py report_hif_case --case-file assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json --output json
rtk proxy python -m pytest -q
```

Expected: HIF 测试和全量测试通过；编译 exit code 为 0；Prettier 通过；CLI JSON 含 `summary.step_count = 33`、`continuity_gaps` 和每步的 `planner_preference_action_id`。

- [ ] **Step 6: 审查变更并提交交付切片**

Run:

```powershell
rtk git diff --check
rtk git diff -- agent/hif/simulator.py agent/hif/observed_case.py tools/simulate_hif.py tests/test_hif_decision.py assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json docs/hif/hif-simulator-flow-design.md
rtk git status --short
```

Expected: 不含 `README.md` 的改动，也不包含 `debug/` 日志。确认后提交：

```powershell
rtk git add agent/hif/simulator.py agent/hif/observed_case.py tools/simulate_hif.py tests/test_hif_decision.py assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json docs/hif/hif-simulator-flow-design.md
rtk git commit -m "feat(hif): 提供完整实测回放审计"
```

## 后续独立计划（本计划完成后再开始）

1. **Interval 决策器：** 从 observed case 的结构化商品中提取 `IntervalDecisionPlanner`，以牌库小于 22、P 点保留、key 卡指导、回复和刷新为约束；先离线评分，后接 OCR。
2. **随机事件评分器：** 分别实现饮料上限保留和两阶段 `セレクトチェンジ` 评分；它们共享卡牌 metadata，但不共享决策流程，避免形成巨型 scorer。
3. **回忆与概率样本：** 在至少两个 case 的基础上实现 memory 再生成评分和随机采样；在样本不足时只输出置信度与未知因素。
4. **OCR/实机：** 每个 screen state 先写截图离线识别测试，再校准 MuMu `720x1280` ROI，最后接 pipeline action。不得把本计划中的初版 ROI 当成最终点击坐标。

## 自检

- 覆盖交接的第一、二项建议：全量 observed steps 与 state diff/report；第三至第六项被明确拆为后续独立切片。
- 没有使用未展开的占位性实施步骤；所有未知实机数据均被放入 JSON 的 `unknown_fields` / `open_questions`，不是实现占位。
- API 名称一致：`build_observed_replay_report`、`observed_replay_report`、`report_hif_case` 在测试、实现、CLI 和验收命令中相同。
- 此计划不会回退 `README.md`，不会声称 HIF 已是完整成绩预测器或实机自动化。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-hif-full-observed-replay.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
