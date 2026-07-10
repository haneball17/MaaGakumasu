# HIF Observed Case Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first implementation slice of `docs/hif/hif-simulator-flow-design.md`: load one structured HIF observed case, convert it to simulator route steps, and run it once through the existing CLI.

**Architecture:** Add a focused `agent/hif/observed_case.py` adapter that owns observed-case dataclasses, validation, and conversion to existing `RouteStep` / `CandidateAction` / `SimulationState`. Keep `agent/hif/simulator.py` mostly stable by making `replay_hif_case` delegate to the adapter. Add one JSON fixture under `assets/data/hif/observed_cases/` based on the documented Rinami Garakuta Road run.

**Tech Stack:** Python 3.12 dataclasses, stdlib `json` / `pathlib`, existing pytest suite, existing CLI `tools/simulate_hif.py`.

---

## File Structure

- Create: `agent/hif/observed_case.py`
  - Owns observed-case schema dataclasses and conversion functions.
- Modify: `agent/hif/simulator.py`
  - Delegates `replay_hif_case` to `observed_case.py`.
- Modify: `tools/simulate_hif.py`
  - Makes `replay_hif_case --case-file ...` print JSON/text from observed replay.
- Create: `assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json`
  - First structured case extracted from `docs/hif/finals-daily-log.md`.
- Modify: `tests/test_hif_decision.py`
  - Adds loader, conversion, and replay tests.

## Task 1: Observed Case Adapter

**Files:**
- Create: `agent/hif/observed_case.py`
- Test: `tests/test_hif_decision.py`

- [ ] **Step 1: Write failing import and load test**

Add this test to `tests/test_hif_decision.py`:

```python
from pathlib import Path

from agent.hif.observed_case import (
    build_initial_state_from_observed_case,
    build_route_steps_from_observed_case,
    load_observed_hif_case,
)


def test_load_observed_hif_case_fixture():
    case_path = Path("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")
    case = load_observed_hif_case(case_path)

    assert case.case_id == "rinami_garakuta_road_20260709"
    assert case.profile["idol_name_jp"] == "姫崎 莉波"
    assert len(case.steps) >= 9
    assert case.steps[0].step_id == "finals_day6_class_select_change"
    assert case.steps[-1].phase == "memory_generation"


def test_observed_hif_case_builds_route_steps_and_initial_state():
    case = load_observed_hif_case("assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json")

    initial_state = build_initial_state_from_observed_case(case)
    route_steps = build_route_steps_from_observed_case(case)

    assert initial_state.stamina == 22
    assert initial_state.max_stamina == 35
    assert initial_state.p_points == 330
    assert route_steps[0].step_id == "finals_day6_class_select_change"
    assert route_steps[0].candidates[0].action_id == "day1_select_good_condition"
    assert route_steps[-1].phase == "round2"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
rtk pytest tests/test_hif_decision.py::test_load_observed_hif_case_fixture tests/test_hif_decision.py::test_observed_hif_case_builds_route_steps_and_initial_state -q
```

Expected: FAIL because `agent.hif.observed_case` does not exist.

- [ ] **Step 3: Implement `agent/hif/observed_case.py`**

Create the file with this structure:

```python
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from agent.hif.simulator import CandidateAction, RouteStep, SimulationState


@dataclass(slots=True)
class ObservedCaseStep:
    step_id: str
    label: str
    phase: str
    day_number: int
    selected_action_id: str
    candidates: list[dict[str, Any]]
    state_before: dict[str, Any] = field(default_factory=dict)
    state_after: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ObservedHIFCase:
    schema_version: int
    case_id: str
    profile: dict[str, Any]
    initial_state: dict[str, Any]
    steps: list[ObservedCaseStep]
    observed_random_events: list[dict[str, Any]]
    recognition_hints: list[dict[str, Any]]
    open_questions: list[str]


def load_observed_hif_case(path: str | Path) -> ObservedHIFCase:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    steps = [
        ObservedCaseStep(
            step_id=step["step_id"],
            label=step["label"],
            phase=step["phase"],
            day_number=step["day_number"],
            selected_action_id=step["selected_action_id"],
            candidates=step["candidates"],
            state_before=step.get("state_before", {}),
            state_after=step.get("state_after", {}),
            metadata=step.get("metadata", {}),
        )
        for step in payload["steps"]
    ]
    return ObservedHIFCase(
        schema_version=payload["schema_version"],
        case_id=payload["case_id"],
        profile=payload["profile"],
        initial_state=payload["initial_state"],
        steps=steps,
        observed_random_events=payload.get("observed_random_events", []),
        recognition_hints=payload.get("recognition_hints", []),
        open_questions=payload.get("open_questions", []),
    )


def build_initial_state_from_observed_case(case: ObservedHIFCase) -> SimulationState:
    payload = case.initial_state
    return SimulationState(
        step_index=0,
        phase=payload.get("phase", "finals_prepare"),
        day_number=payload.get("day_number", 6),
        stamina=payload["stamina"],
        max_stamina=payload["max_stamina"],
        p_points=payload["p_points"],
        star_value=payload.get("star_value", 0),
        deck_size=payload.get("deck_size", 20),
        trial_readiness=payload.get("trial_readiness", 0),
        memory_quality=payload.get("memory_quality", 0),
        deck_quality=payload.get("deck_quality", 0),
        finals_readiness=payload.get("finals_readiness", 0),
        interval_budget=payload.get("interval_budget", 0),
        support_event_progress=payload.get("support_event_progress", 0),
        skill_tag_counts=payload.get("skill_tag_counts", {}),
        p_item_tag_counts=payload.get("p_item_tag_counts", {}),
        snapshots=payload.get("snapshots", {}),
    )


def build_route_steps_from_observed_case(case: ObservedHIFCase) -> list[RouteStep]:
    route_steps: list[RouteStep] = []
    for step in case.steps:
        candidates = [
            CandidateAction(
                action_id=candidate["action_id"],
                name=candidate["name"],
                category=candidate["category"],
                phase=step.phase,
                tags=candidate.get("tags", []),
                stamina_delta=candidate.get("stamina_delta", 0),
                p_point_delta=candidate.get("p_point_delta", 0),
                star_delta=candidate.get("star_delta", 0),
                trial_readiness_delta=candidate.get("trial_readiness_delta", 0),
                memory_quality_delta=candidate.get("memory_quality_delta", 0),
                deck_quality_delta=candidate.get("deck_quality_delta", 0),
                finals_readiness_delta=candidate.get("finals_readiness_delta", 0),
                interval_budget_delta=candidate.get("interval_budget_delta", 0),
                support_progress_delta=candidate.get("support_progress_delta", 0),
                deck_size_delta=candidate.get("deck_size_delta", 0),
                add_skill_tags=candidate.get("add_skill_tags", {}),
                add_p_item_tags=candidate.get("add_p_item_tags", {}),
                remove_skill_tags=candidate.get("remove_skill_tags", {}),
                forced=candidate.get("forced", False),
                risk=candidate.get("risk", 0.0),
                metadata={
                    **candidate.get("metadata", {}),
                    "observed_selected": candidate["action_id"] == step.selected_action_id,
                    "observed_state_before": step.state_before,
                    "observed_state_after": step.state_after,
                },
            )
            for candidate in step.candidates
        ]
        route_steps.append(
            RouteStep(
                step_id=step.step_id,
                label=step.label,
                phase=step.phase,
                day_number=step.day_number,
                candidates=candidates,
                metadata={
                    **step.metadata,
                    "observed_selected_action_id": step.selected_action_id,
                    "observed_state_before": step.state_before,
                    "observed_state_after": step.state_after,
                },
            )
        )
    return route_steps
```

- [ ] **Step 4: Run import test again**

Run:

```powershell
rtk pytest tests/test_hif_decision.py::test_load_observed_hif_case_fixture tests/test_hif_decision.py::test_observed_hif_case_builds_route_steps_and_initial_state -q
```

Expected: FAIL because the JSON fixture does not exist.

## Task 2: Observed Case Fixture

**Files:**
- Create: `assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json`
- Test: `tests/test_hif_decision.py`

- [ ] **Step 1: Add JSON fixture**

Create `assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json`:

```json
{
    "schema_version": 1,
    "case_id": "rinami_garakuta_road_20260709",
    "profile": {
        "idol_name_jp": "姫崎 莉波",
        "song": "ガラクタロード",
        "route_plan": "好調",
        "source_doc": "docs/hif/finals-daily-log.md"
    },
    "initial_state": {
        "phase": "finals_prepare",
        "day_number": 6,
        "stamina": 22,
        "max_stamina": 35,
        "p_points": 330,
        "star_value": 0,
        "deck_size": 20,
        "trial_readiness": 0,
        "memory_quality": 0,
        "deck_quality": 12,
        "finals_readiness": 10,
        "interval_budget": 0,
        "support_event_progress": 0,
        "skill_tag_counts": {
            "good_condition": 1,
            "draw": 1
        },
        "p_item_tag_counts": {},
        "snapshots": {
            "observed_attributes": {
                "Vo": 1116,
                "Da": 2633,
                "Vi": 1881
            }
        }
    },
    "steps": [
        {
            "step_id": "finals_day6_class_select_change",
            "label": "本戦前6日 Vi授業 セレクトチェンジ",
            "phase": "finals_prepare",
            "day_number": 6,
            "selected_action_id": "day1_select_good_condition",
            "state_before": {"stamina": 22, "p_points": 330},
            "state_after": {"stamina": 17, "p_points": 330, "Vi": 2061},
            "candidates": [
                {
                    "action_id": "day1_select_good_condition",
                    "name": "長い道のりでした",
                    "category": "class",
                    "tags": ["Vi", "good_condition", "select_change"],
                    "stamina_delta": -5,
                    "finals_readiness_delta": 8,
                    "deck_quality_delta": 5,
                    "metadata": {"preview_delta": {"Vi": 180}, "target_card": "始まりの合図"}
                }
            ]
        },
        {
            "step_id": "finals_day5_public_lesson_da_sp",
            "label": "本戦前2日 Da公開レッスン SP",
            "phase": "finals_prepare",
            "day_number": 2,
            "selected_action_id": "day5_da_public_lesson_sp",
            "state_before": {"stamina": 17, "p_points": 330, "Da": 2633, "Vi": 2061},
            "state_after": {"stamina": 9, "p_points": 380, "Da": 2920, "Vi": 2175},
            "candidates": [
                {
                    "action_id": "day5_da_public_lesson_sp",
                    "name": "Da.公開レッスン",
                    "category": "public_lesson",
                    "tags": ["Da", "SP", "cap_safe"],
                    "stamina_delta": -8,
                    "p_point_delta": 50,
                    "finals_readiness_delta": 10,
                    "metadata": {"result_delta": {"Da": 287, "Vi": 114}}
                }
            ]
        },
        {
            "step_id": "finals_day1_consult_skip",
            "label": "本戦前1日 相談 終了",
            "phase": "finals_prepare",
            "day_number": 1,
            "selected_action_id": "day6_consult_finish_without_purchase",
            "state_before": {"stamina": 9, "p_points": 380},
            "state_after": {"stamina": 9, "p_points": 380},
            "candidates": [
                {
                    "action_id": "day6_consult_finish_without_purchase",
                    "name": "終了",
                    "category": "finals_consult",
                    "tags": ["consult", "skip_purchase", "reserve_p_points"],
                    "metadata": {"reserve_p_points_for_interval": true}
                }
            ]
        },
        {
            "step_id": "round1_initial_manual",
            "label": "Round1 初始 手动打分",
            "phase": "round1",
            "day_number": 0,
            "selected_action_id": "round1_manual_play",
            "state_before": {"stamina": 28, "score": 0},
            "state_after": {"stamina": 34, "p_points": 580},
            "candidates": [
                {
                    "action_id": "round1_manual_play",
                    "name": "Round1 手动打分",
                    "category": "manual_battle",
                    "tags": ["round1", "manual"],
                    "p_point_delta": 200,
                    "metadata": {"turn_remaining": 9, "exam_attribute": "Vi"}
                }
            ]
        },
        {
            "step_id": "interval_customize_spprechchor",
            "label": "Interval シュプレヒコール+ カスタマイズ",
            "phase": "interval",
            "day_number": 0,
            "selected_action_id": "interval_customize_focus_cost_down",
            "state_before": {"stamina": 34, "p_points": 580, "deck_size": 20},
            "state_after": {"stamina": 34, "p_points": 260, "deck_size": 22},
            "candidates": [
                {
                    "action_id": "interval_customize_focus_cost_down",
                    "name": "集中コスト値-",
                    "category": "skill_customize",
                    "tags": ["interval", "customize", "key_card"],
                    "p_point_delta": -320,
                    "deck_size_delta": 2,
                    "deck_quality_delta": 12,
                    "metadata": {"card": "シュプレヒコール+", "customize_cost": 40}
                }
            ]
        },
        {
            "step_id": "round2_manual",
            "label": "Round2 手动打分",
            "phase": "round2",
            "day_number": 0,
            "selected_action_id": "round2_manual_play",
            "state_before": {"stamina": 34, "p_points": 260},
            "state_after": {"score": 4756391},
            "candidates": [
                {
                    "action_id": "round2_manual_play",
                    "name": "Round2 手动打分",
                    "category": "manual_battle",
                    "tags": ["round2", "manual"],
                    "finals_readiness_delta": 20,
                    "metadata": {"final_score": 4756391}
                }
            ]
        },
        {
            "step_id": "memory_preview",
            "label": "回忆卡生成 预览",
            "phase": "round2",
            "day_number": 0,
            "selected_action_id": "memory_accept",
            "state_before": {"score": 4756391},
            "state_after": {"memory_rank": "S4+"},
            "candidates": [
                {
                    "action_id": "memory_accept",
                    "name": "次へ",
                    "category": "memory_generation",
                    "tags": ["memory", "accept"],
                    "memory_quality_delta": 20,
                    "metadata": {
                        "memory_rank": "S4+",
                        "memory_skill": "存在感+",
                        "memory_abilities": ["ダンスパラメータボーナス+2.8%", "初期ビジュアル上昇+15", "初期Pポイント+30"]
                    }
                }
            ]
        }
    ],
    "observed_random_events": [
        {"event_type": "drink_overflow_resolution", "drink_capacity": 4},
        {"event_type": "select_change", "target_card": "始まりの合図"}
    ],
    "recognition_hints": [
        {"screen_state": "interval_shop", "title_ocr": "インターバル"},
        {"screen_state": "memory_preview", "title_ocr": "S4+"}
    ],
    "open_questions": [
        "Round2 初始状态还缺截图",
        "P 点 580 到 260 的完整消费流水仍需补证据"
    ]
}
```

- [ ] **Step 2: Run observed case tests**

Run:

```powershell
rtk pytest tests/test_hif_decision.py::test_load_observed_hif_case_fixture tests/test_hif_decision.py::test_observed_hif_case_builds_route_steps_and_initial_state -q
```

Expected: PASS.

## Task 3: Replay Integration

**Files:**
- Modify: `agent/hif/simulator.py`
- Modify: `tools/simulate_hif.py`
- Test: `tests/test_hif_decision.py`

- [ ] **Step 1: Add replay test**

Add this test:

```python
from agent.hif.simulator import load_default_scenario, load_default_profile, replay_hif_case


def test_replay_observed_hif_case_runs_to_memory_preview():
    scenario = load_default_scenario()
    profile = load_default_profile()

    result = replay_hif_case(
        scenario,
        profile,
        "assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json",
    )

    assert result["observed_case"]["case_id"] == "rinami_garakuta_road_20260709"
    assert result["steps"][-1]["step_id"] == "memory_preview"
    assert result["final_state"]["memory_quality"] >= 20
```

- [ ] **Step 2: Run replay test to verify it fails**

Run:

```powershell
rtk pytest tests/test_hif_decision.py::test_replay_observed_hif_case_runs_to_memory_preview -q
```

Expected: FAIL because `replay_hif_case` does not return `observed_case`.

- [ ] **Step 3: Modify `replay_hif_case`**

Change `agent/hif/simulator.py` so `replay_hif_case` imports and delegates:

```python
def replay_hif_case(
    scenario: ScenarioConfig,
    profile: ProduceProfile,
    case_file: str | Path,
    initial_state: SimulationState | None = None,
) -> dict[str, Any]:
    from agent.hif.observed_case import (
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
        "open_questions": case.open_questions,
    }
    return result
```

- [ ] **Step 4: Run replay test**

Run:

```powershell
rtk pytest tests/test_hif_decision.py::test_replay_observed_hif_case_runs_to_memory_preview -q
```

Expected: PASS.

- [ ] **Step 5: Verify CLI runs once**

Run:

```powershell
rtk proxy python tools/simulate_hif.py replay_hif_case --case-file assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json --output json
```

Expected: JSON output includes `"observed_case"` and `"case_id": "rinami_garakuta_road_20260709"`.

## Task 4: Regression and Documentation Check

**Files:**
- Modify: `docs/hif/hif-simulator-flow-design.md` only if implementation names changed.
- Test: existing tests.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
rtk pytest tests/test_hif_decision.py -q
```

Expected: all HIF tests pass.

- [ ] **Step 2: Compile Python agent**

Run:

```powershell
rtk proxy python -m py_compile agent/hif/simulator.py agent/hif/observed_case.py tools/simulate_hif.py
```

Expected: exit code 0.

- [ ] **Step 3: Check git diff**

Run:

```powershell
rtk git diff -- agent/hif/simulator.py agent/hif/observed_case.py tools/simulate_hif.py tests/test_hif_decision.py docs/hif/hif-simulator-flow-design.md
```

Expected: only observed case replay implementation changes appear.

## Execution Notes

- Do not change `README.md`; it is an unrelated existing modification.
- Keep observed case conversion metadata-rich but behavior-compatible with existing `CandidateAction`.
- The first replay is allowed to use abstract deltas. The goal of this slice is not perfect final score prediction; it is proving the full observed flow can be loaded and run once.
- Future tasks can replace abstract deltas with full attribute/deck/drink state once replay infrastructure is stable.
