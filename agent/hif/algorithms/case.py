from __future__ import annotations

from copy import deepcopy

from agent.hif.algorithms.types import RouteStep, RewardKind, RewardOption, ProduceProfile, CandidateAction, HIFDecisionData


def build_reward_options_from_data(data: HIFDecisionData, reward_kind: RewardKind) -> list[RewardOption]:
    if reward_kind == "p_item":
        return [
            RewardOption(
                option_id=item["p_item_id"],
                name=item["name_jp"],
                kind="p_item",
                tags=item.get("tags", []),
                metadata={"scenario": item.get("scenario", "")},
            )
            for item in data.p_items
        ]

    options = []
    for card in data.skill_cards:
        options.append(
            RewardOption(
                option_id=card["skill_card_id"],
                name=card["name_jp"],
                kind=reward_kind,
                tags=card.get("tags", []),
                metadata={
                    "type": card.get("type", ""),
                    "upgrade_priority": card.get("upgrade_priority", 0),
                    "delete_priority": card.get("delete_priority", 0),
                },
            )
        )
    return options


def build_sample_hif_case(data: HIFDecisionData, profile: ProduceProfile) -> list[RouteStep]:
    primary = profile.first.lower()
    secondary = profile.second.lower()
    p_items = build_reward_options_from_data(data, "p_item")
    p_item_actions = [
        CandidateAction(
            action_id=f"pitem:{option.option_id}",
            name=option.name,
            category="p_item",
            phase="selection_item",
            tags=option.tags,
            star_delta=3 if "star_synergy" in option.tags else 0,
            p_point_delta=12 if "ppoint_gain" in option.tags else 0,
            memory_quality_delta=2 if "card_gain" in option.tags else 0,
            deck_quality_delta=2 if "card_gain" in option.tags else 0,
            add_p_item_tags={tag: 1 for tag in option.tags},
            risk=0.1,
            metadata={"source_option_id": option.option_id},
        )
        for option in p_items[:3]
    ]

    def lesson_action(day: int, stat: str, weight: int) -> CandidateAction:
        is_primary = stat == primary
        return CandidateAction(
            action_id=f"{stat}_lesson_day_{day}",
            name=f"{stat.upper()} lesson",
            category="lesson",
            phase="selection",
            tags=[f"{stat}_lesson", "good_condition" if is_primary else "steady_growth"],
            stamina_delta=-(6 if is_primary else 5),
            trial_readiness_delta=8 if is_primary else 6,
            finals_readiness_delta=6 if is_primary else 5,
            deck_quality_delta=4 if is_primary else 3,
            star_delta=2 if is_primary else 1,
            support_progress_delta=1 if weight % 2 == 0 else 0,
            risk=0.6 if is_primary else 0.45,
        )

    def consult_action(day: int) -> CandidateAction:
        return CandidateAction(
            action_id=f"consult_day_{day}",
            name="相談",
            category="consult",
            phase="selection",
            tags=["consult", "ppoint_gain"],
            stamina_delta=-2,
            p_point_delta=32,
            deck_quality_delta=4,
            support_progress_delta=1,
            risk=0.25,
        )

    def outing_action(day: int) -> CandidateAction:
        return CandidateAction(
            action_id=f"outing_day_{day}",
            name="おでかけ",
            category="outing",
            phase="selection",
            tags=["recovery", "memory_support"],
            stamina_delta=18,
            memory_quality_delta=6,
            support_progress_delta=1,
            risk=0.1,
        )

    def event_action(day: int) -> CandidateAction:
        return CandidateAction(
            action_id=f"event_day_{day}",
            name="特別指導",
            category="event",
            phase="selection",
            tags=["star_gain", "memory_support"],
            stamina_delta=-3,
            star_delta=9,
            memory_quality_delta=7,
            finals_readiness_delta=2,
            risk=0.35,
        )

    steps: list[RouteStep] = []
    for day in range(1, 21):
        if day in {7, 14, 20}:
            steps.append(
                RouteStep(
                    step_id=f"selection_exam_{day}",
                    label=f"選抜試験 Day {day}",
                    phase="selection_exam",
                    day_number=day,
                    candidates=[
                        CandidateAction(
                            action_id=f"exam_day_{day}",
                            name="選抜試験",
                            category="exam",
                            phase="selection_exam",
                            tags=["exam"],
                            trial_readiness_delta=4,
                            finals_readiness_delta=2,
                            forced=True,
                            risk=0.05,
                        )
                    ],
                )
            )
            continue

        if day in {6, 13, 19}:
            steps.append(
                RouteStep(
                    step_id=f"selection_item_{day}",
                    label=f"カスタムPアイテム Day {day}",
                    phase="selection_item",
                    day_number=day,
                    candidates=deepcopy(p_item_actions),
                )
            )
            continue

        steps.append(
            RouteStep(
                step_id=f"selection_{day}",
                label=f"選抜日程 Day {day}",
                phase="selection",
                day_number=day,
                candidates=[
                    lesson_action(day, primary, day),
                    lesson_action(day, secondary, day),
                    consult_action(day),
                    outing_action(day),
                    event_action(day),
                ],
            )
        )

    for offset in range(1, 7):
        day = 20 + offset
        steps.append(
            RouteStep(
                step_id=f"finals_prepare_{offset}",
                label=f"本戦準備 Day {offset}",
                phase="finals_prepare",
                day_number=day,
                candidates=[
                    CandidateAction(
                        action_id=f"finals_primary_{offset}",
                        name=f"{profile.first} 仕上げ",
                        category="finals_lesson",
                        phase="finals_prepare",
                        tags=["good_condition", "score_main"],
                        stamina_delta=-5,
                        finals_readiness_delta=8,
                        deck_quality_delta=4,
                        star_delta=3,
                        risk=0.4,
                    ),
                    CandidateAction(
                        action_id=f"finals_consult_{offset}",
                        name="本戦相談",
                        category="finals_consult",
                        phase="finals_prepare",
                        tags=["consult", "ppoint_gain"],
                        stamina_delta=-2,
                        p_point_delta=24,
                        deck_quality_delta=3,
                        support_progress_delta=1,
                        finals_readiness_delta=3,
                        risk=0.2,
                    ),
                    CandidateAction(
                        action_id=f"finals_event_{offset}",
                        name="本戦イベント",
                        category="finals_event",
                        phase="finals_prepare",
                        tags=["memory_support", "star_gain"],
                        stamina_delta=-3,
                        memory_quality_delta=4,
                        star_delta=6,
                        finals_readiness_delta=4,
                        risk=0.25,
                    ),
                    CandidateAction(
                        action_id=f"finals_recover_{offset}",
                        name="本戦休息",
                        category="outing",
                        phase="finals_prepare",
                        tags=["recovery", "memory_support"],
                        stamina_delta=14,
                        memory_quality_delta=2,
                        finals_readiness_delta=1,
                        risk=0.05,
                    ),
                ],
            )
        )

    steps.extend(
        [
            RouteStep(
                step_id="round1",
                label="Round1",
                phase="round1",
                day_number=27,
                candidates=[
                    CandidateAction(
                        action_id="round1_exam",
                        name="Round1",
                        category="round_exam",
                        phase="round1",
                        tags=["exam", "round1"],
                        finals_readiness_delta=3,
                        forced=True,
                        risk=0.05,
                    )
                ],
            ),
            RouteStep(
                step_id="interval",
                label="Interval",
                phase="interval",
                day_number=28,
                candidates=[
                    CandidateAction(
                        action_id="interval_safe",
                        name="Interval: safe budget",
                        category="interval_budget",
                        phase="interval",
                        tags=["interval", "ppoint_gain"],
                        p_point_delta=18,
                        interval_budget_delta=26,
                        finals_readiness_delta=2,
                        risk=0.1,
                    ),
                    CandidateAction(
                        action_id="interval_balanced",
                        name="Interval: balanced",
                        category="interval_budget",
                        phase="interval",
                        tags=["interval", "star_gain"],
                        p_point_delta=8,
                        interval_budget_delta=18,
                        star_delta=6,
                        finals_readiness_delta=4,
                        risk=0.15,
                    ),
                    CandidateAction(
                        action_id="interval_aggressive",
                        name="Interval: aggressive",
                        category="interval_budget",
                        phase="interval",
                        tags=["interval", "score_main"],
                        p_point_delta=-10,
                        interval_budget_delta=10,
                        finals_readiness_delta=8,
                        deck_quality_delta=3,
                        risk=0.45,
                    ),
                ],
            ),
            RouteStep(
                step_id="round2",
                label="Round2",
                phase="round2",
                day_number=29,
                candidates=[
                    CandidateAction(
                        action_id="round2_exam",
                        name="Round2",
                        category="round_exam",
                        phase="round2",
                        tags=["exam", "round2"],
                        finals_readiness_delta=4,
                        forced=True,
                        risk=0.05,
                    )
                ],
            ),
        ]
    )
    return steps
