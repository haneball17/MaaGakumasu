from dataclasses import replace

from agent.hif.route_scoring import HandCard, BattleRound, UpgradeLevel, RouteBattleState
from agent.hif.route_scoring.postconditions import verify_blessing_plus


def _state() -> RouteBattleState:
    return RouteBattleState(
        route_id="rinami_garakuta_road",
        battle_round=BattleRound.ROUND1,
        turn=6,
        total_turns=9,
        current_score=116_611,
        stage_multiplier_percent=3_807,
        stamina=33,
        focus=10,
        good_condition_turns=47,
        reprise_count=2,
        deck_size=21,
        trusted=True,
        fresh=True,
        hand=(HandCard("hand-4", "祝福", "祝福", UpgradeLevel.PLUS, True),),
    )


def test_blessing_plus_requires_all_domain_effects() -> None:
    before = _state()
    after = replace(
        before,
        current_score=120_342,
        stamina=29,
        good_condition_turns=48,
        hand=(),
    )

    result = verify_blessing_plus(before, after, displayed_score=3_731)

    assert result.verified
    assert result.failed_assertions == ()


def test_blessing_plus_rejects_frame_change_without_exact_score_or_effect() -> None:
    before = _state()
    after = replace(before, current_score=120_341, stamina=29, hand=())

    result = verify_blessing_plus(before, after, displayed_score=3_731)

    assert not result.verified
    assert result.failed_assertions == ("score_delta_matches_card", "good_condition_plus_one")
