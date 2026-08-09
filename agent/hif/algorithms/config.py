from __future__ import annotations

import json
from pathlib import Path

from agent.hif.algorithms.types import ProduceProfile, ScenarioConfig, HIFDecisionData, SimulationState, HIFEvaluationConfig


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_decision_data(path: str | Path | None = None) -> HIFDecisionData:
    decision_path = Path(path) if path else (_project_root() / "assets" / "data" / "produce_decision_data.json")
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    return HIFDecisionData(
        schema_version=payload["schema_version"],
        updated_at=payload["updated_at"],
        idol_cards=payload.get("idol_cards", []),
        skill_cards=payload.get("skill_cards", []),
        p_items=payload.get("p_items", []),
    )


def build_default_scenario_config() -> ScenarioConfig:
    return ScenarioConfig(
        scenario_name="HIF",
        selection_days=20,
        selection_trial_days=[7, 14, 20],
        finals_preparation_days=6,
        phases=["selection", "selection_exam", "selection_item", "finals_prepare", "round1", "interval", "round2"],
        beam_width=4,
        lookahead_depth=3,
        score_weights={
            "stamina": 0.4,
            "p_points": 0.35,
            "star_value": 0.7,
            "trial_readiness": 0.9,
            "memory_quality": 0.75,
            "deck_quality": 0.65,
            "finals_readiness": 0.85,
            "interval_budget": 0.8,
            "support_progress": 0.5,
            "deck_size": 0.2,
        },
        selection_targets={
            "trial_readiness": 78,
            "star_value": 40,
            "memory_quality": 48,
            "deck_quality": 44,
            "support_event_progress": 8,
            "deck_size": 22,
        },
        finals_targets={
            "finals_readiness": 52,
            "star_value": 48,
            "deck_quality": 52,
            "memory_quality": 55,
            "deck_size": 22,
        },
        interval_targets={
            "interval_budget": 80,
            "p_points": 110,
            "star_value": 52,
        },
    )


def build_default_hif_evaluation_config() -> HIFEvaluationConfig:
    base_attribute_total = 600
    flex_attribute_total = 500
    selection_attribute_total = 1100
    round1_weight = 1.2
    round2_weight = 1.0
    total_round_weight = round1_weight + round2_weight
    return HIFEvaluationConfig(
        scenario_name="HIF",
        base_attribute_total=base_attribute_total,
        flex_attribute_total=flex_attribute_total,
        selection_attribute_total=selection_attribute_total,
        base_ratio=round(base_attribute_total / selection_attribute_total, 4),
        flex_ratio=round(flex_attribute_total / selection_attribute_total, 4),
        round1_weight=round1_weight,
        round2_weight=round2_weight,
        round1_ratio=round(round1_weight / total_round_weight, 4),
        round2_ratio=round(round2_weight / total_round_weight, 4),
        selection_star_reward_cap=260,
        selection_star_reward_cap_with_bonus=390,
        public_lesson_star_total=160,
        hif_wappen_star_cap=200,
        low_attribute_penalty_note="低属性会影响整体试验分数加成，首版仅作为说明，不直接进入主评分器。",
        attribute_adaptation_note="属性贡献不是固定 33/33/33，而是受当场审查基准倍率影响。",
    )


def build_default_produce_profile(data: HIFDecisionData) -> ProduceProfile:
    record = next(
        (
            row
            for row in data.idol_cards
            if row.get("idol_name_jp") == "姫崎莉波" and "ガラクタロード" in row.get("card_name_jp", "")
        ),
        None,
    )
    if record is None:
        raise ValueError("未在 produce_decision_data.json 中找到 姫崎莉波(ガラクタロード)")

    return ProduceProfile(
        profile_name="rinami_garakuta_kansei_good_condition",
        idol_card_id=record["idol_card_id"],
        idol_name_jp=record["idol_name_jp"],
        idol_name_zh=record.get("idol_name_zh", record["idol_name_jp"]),
        card_name_jp=record["card_name_jp"],
        recommended_effect=record["recommended_effect"],
        plan="センス",
        build="好調",
        first=record["first"],
        second=record["second"],
        support_deck={"locked_core": [], "flex_slots": []},
        preferred_skill_tags={
            "buff_main": 3.0,
            "loop_core": 2.8,
            "draw_cycle": 2.6,
            "score_main": 2.2,
            "basic": 1.0,
            "trouble": -4.0,
        },
        preferred_p_item_tags={
            "star_synergy": 3.0,
            "card_gain": 2.4,
            "ppoint_gain": 2.1,
            "consult_discount": 1.7,
            "drink_gain": 1.2,
        },
        reward_priorities={
            "skill_acquire": 1.0,
            "skill_upgrade": 0.9,
            "skill_delete": 0.85,
            "p_item": 0.95,
        },
    )


def load_scenario_config(path: str | Path) -> ScenarioConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ScenarioConfig(**payload)


def load_produce_profile(path: str | Path) -> ProduceProfile:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ProduceProfile(**payload)


def build_initial_state() -> SimulationState:
    return SimulationState(
        step_index=0,
        phase="selection",
        day_number=1,
        stamina=34,
        max_stamina=34,
        p_points=0,
        star_value=0,
        deck_size=22,
        trial_readiness=0,
        memory_quality=0,
        deck_quality=0,
        finals_readiness=0,
        interval_budget=0,
        support_event_progress=0,
        skill_tag_counts={"basic": 3},
        p_item_tag_counts={},
    )
