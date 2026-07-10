from __future__ import annotations

import json
from typing import Any, cast
from pathlib import Path
from dataclasses import field, dataclass

from agent.hif.simulator import RouteStep, RoutePhase, CandidateAction, SimulationState


@dataclass(slots=True)
class ObservedCaseStep:
    step_id: str
    label: str
    phase: RoutePhase
    day_number: int
    selected_action_id: str
    candidates: list[dict[str, Any]]
    state_before: dict[str, Any] = field(default_factory=dict)
    state_after: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ObservedRandomEvent:
    event_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RecognitionHint:
    screen_state: str
    title_ocr: str = ""
    primary_text_ocr: str = ""
    buttons: list[dict[str, Any]] = field(default_factory=list)
    regions: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ObservedHIFCase:
    schema_version: int
    case_id: str
    profile: dict[str, Any]
    initial_state: dict[str, Any]
    steps: list[ObservedCaseStep]
    observed_random_events: list[ObservedRandomEvent]
    recognition_hints: list[RecognitionHint]
    open_questions: list[str]


def load_observed_hif_case(path: str | Path) -> ObservedHIFCase:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    steps = [
        ObservedCaseStep(
            step_id=step["step_id"],
            label=step["label"],
            phase=cast(RoutePhase, step["phase"]),
            day_number=step["day_number"],
            selected_action_id=step["selected_action_id"],
            candidates=step["candidates"],
            state_before=step.get("state_before", {}),
            state_after=step.get("state_after", {}),
            metadata=step.get("metadata", {}),
        )
        for step in payload["steps"]
    ]
    observed_random_events = [
        ObservedRandomEvent(
            event_type=event["event_type"],
            metadata={key: value for key, value in event.items() if key != "event_type"},
        )
        for event in payload.get("observed_random_events", [])
    ]
    recognition_hints = [
        RecognitionHint(
            screen_state=hint["screen_state"],
            title_ocr=hint.get("title_ocr", ""),
            primary_text_ocr=hint.get("primary_text_ocr", ""),
            buttons=hint.get("buttons", []),
            regions=hint.get("regions", []),
            metadata={key: value for key, value in hint.items() if key not in {"screen_state", "title_ocr", "primary_text_ocr", "buttons", "regions"}},
        )
        for hint in payload.get("recognition_hints", [])
    ]
    case = ObservedHIFCase(
        schema_version=payload["schema_version"],
        case_id=payload["case_id"],
        profile=payload["profile"],
        initial_state=payload["initial_state"],
        steps=steps,
        observed_random_events=observed_random_events,
        recognition_hints=recognition_hints,
        open_questions=payload.get("open_questions", []),
    )
    validate_observed_hif_case(case)
    return case


def validate_observed_hif_case(case: ObservedHIFCase) -> None:
    if case.schema_version != 1:
        raise ValueError(f"Unsupported observed HIF case schema_version: {case.schema_version}")
    if not case.case_id:
        raise ValueError("Observed HIF case requires case_id")
    if not case.steps:
        raise ValueError(f"Observed HIF case {case.case_id} requires at least one step")

    for step in case.steps:
        if not step.candidates:
            raise ValueError(f"Observed step {step.step_id} requires at least one candidate")
        candidate_ids = {candidate.get("action_id") for candidate in step.candidates}
        if step.selected_action_id not in candidate_ids:
            raise ValueError(f"Observed step {step.step_id} selected_action_id {step.selected_action_id} is missing from candidates")

    for event in case.observed_random_events:
        if not event.event_type:
            raise ValueError(f"Observed HIF case {case.case_id} contains random event without event_type")

    for hint in case.recognition_hints:
        if not hint.screen_state:
            raise ValueError(f"Observed HIF case {case.case_id} contains recognition hint without screen_state")


def build_initial_state_from_observed_case(case: ObservedHIFCase) -> SimulationState:
    payload = case.initial_state
    return SimulationState(
        step_index=0,
        phase=cast(RoutePhase, payload.get("phase", "finals_prepare")),
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
