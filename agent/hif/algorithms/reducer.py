from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.hif.algorithms.types import RouteStep, RoutePhase, CandidateAction, SimulationState, SelectionSnapshot, SelectionMemoryProfile


class PhaseResolver:
    @staticmethod
    def resolve(step: RouteStep) -> RoutePhase:
        return step.phase


class CandidateBuilder:
    def build(self, step: RouteStep, state: SimulationState) -> list[CandidateAction]:
        del state
        return deepcopy(step.candidates)


class StateReducer:
    def apply(self, state: SimulationState, step: RouteStep, candidate: CandidateAction) -> SimulationState:
        next_state = deepcopy(state)
        next_state.step_index += 1
        next_state.stamina = max(0, min(next_state.max_stamina, next_state.stamina + candidate.stamina_delta))
        next_state.p_points = max(0, next_state.p_points + candidate.p_point_delta)
        next_state.star_value = max(0, next_state.star_value + candidate.star_delta)
        next_state.trial_readiness = max(0, next_state.trial_readiness + candidate.trial_readiness_delta)
        next_state.memory_quality = max(0, next_state.memory_quality + candidate.memory_quality_delta)
        next_state.deck_quality = max(0, next_state.deck_quality + candidate.deck_quality_delta)
        next_state.finals_readiness = max(0, next_state.finals_readiness + candidate.finals_readiness_delta)
        next_state.interval_budget = max(0, next_state.interval_budget + candidate.interval_budget_delta)
        next_state.support_event_progress = max(0, next_state.support_event_progress + candidate.support_progress_delta)
        next_state.deck_size = max(0, next_state.deck_size + candidate.deck_size_delta)

        for tag, count in candidate.add_skill_tags.items():
            next_state.skill_tag_counts[tag] = next_state.skill_tag_counts.get(tag, 0) + count
        for tag, count in candidate.remove_skill_tags.items():
            next_state.skill_tag_counts[tag] = max(0, next_state.skill_tag_counts.get(tag, 0) - count)
        for tag, count in candidate.add_p_item_tags.items():
            next_state.p_item_tag_counts[tag] = next_state.p_item_tag_counts.get(tag, 0) + count

        if candidate.category == "p_item":
            next_state.change_count += 1
        if candidate.category == "skill_delete":
            next_state.delete_count += 1
        if candidate.category in {"consult", "finals_consult"}:
            next_state.refresh_count += 1

        self._apply_observed_state_after(next_state, step, candidate)

        next_state.decision_history.append(
            {
                "step_id": step.step_id,
                "label": step.label,
                "phase": step.phase,
                "selected_action": candidate.name,
                "tags": candidate.tags,
            }
        )
        return next_state

    @staticmethod
    def _apply_observed_state_after(state: SimulationState, step: RouteStep, candidate: CandidateAction) -> None:
        observed = candidate.metadata.get("observed_state_after")
        if not isinstance(observed, dict):
            return

        observed_int_fields = {
            "stamina",
            "max_stamina",
            "p_points",
            "star_value",
            "deck_size",
            "trial_readiness",
            "memory_quality",
            "deck_quality",
            "finals_readiness",
            "interval_budget",
            "support_event_progress",
        }
        for field_name in observed_int_fields:
            value = observed.get(field_name)
            if isinstance(value, int | float):
                setattr(state, field_name, max(0, int(value)))

        state.stamina = min(state.max_stamina, state.stamina)
        state.snapshots.setdefault("observed_state_after", {})[step.step_id] = deepcopy(observed)


class SnapshotBuilder:
    @staticmethod
    def build(state: SimulationState) -> SelectionSnapshot:
        return SelectionSnapshot(
            final_skill_tags=deepcopy(state.skill_tag_counts),
            final_p_item_tags=deepcopy(state.p_item_tag_counts),
            star_value=state.star_value,
            deck_size=state.deck_size,
            support_event_progress=state.support_event_progress,
            change_count=state.change_count,
            delete_count=state.delete_count,
            refresh_count=state.refresh_count,
            trial_readiness=state.trial_readiness,
            memory_quality=state.memory_quality,
            deck_quality=state.deck_quality,
            p_points=state.p_points,
            stamina=state.stamina,
        )


class MemoryProjector:
    @staticmethod
    def build(snapshot: SelectionSnapshot) -> SelectionMemoryProfile:
        key_skill_tags = {
            tag: count
            for tag, count in snapshot.final_skill_tags.items()
            if tag in {"buff_main", "loop_core", "draw_cycle", "score_main", "trouble"}
        }
        key_p_item_tags = {
            tag: count
            for tag, count in snapshot.final_p_item_tags.items()
            if tag in {"star_synergy", "card_gain", "ppoint_gain", "consult_discount"}
        }
        return SelectionMemoryProfile(
            star_value=snapshot.star_value,
            deck_size=snapshot.deck_size,
            key_skill_tags=key_skill_tags,
            key_p_item_tags=key_p_item_tags,
            pending_support_events=max(0, 10 - snapshot.support_event_progress),
            deck_quality=snapshot.deck_quality,
            memory_quality=snapshot.memory_quality,
        )
