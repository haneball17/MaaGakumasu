from dataclasses import replace

from agent.hif.route_scoring import (
    CardSpec,
    HandCard,
    CardEffect,
    BattleRound,
    UpgradeLevel,
    RejectionCode,
    RouteBattleState,
    RouteDecisionStatus,
    RinamiGarakutaRouteScorer,
)


def _card(
    target_id: str,
    card_id: str,
    upgrade: UpgradeLevel = UpgradeLevel.BASE,
    *,
    playable: bool = True,
    title: str | None = None,
) -> HandCard:
    return HandCard(target_id, card_id, title or card_id, upgrade, playable)


def _observed_stop_state() -> RouteBattleState:
    """2026-07-15 零输入复核现场；不包含坐标或截图指纹。"""

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
        deck_size=22,
        trusted=True,
        fresh=True,
        hand=(
            _card("hand-1", "演出計画"),
            _card("hand-2", "眠気", playable=False),
            _card("hand-3", "祝福"),
            _card("hand-4", "祝福", UpgradeLevel.PLUS),
        ),
    )


def test_observed_round1_case_selects_unique_blessing_plus_with_explainable_breakdown() -> None:
    decision = RinamiGarakutaRouteScorer().decide(_observed_stop_state())

    assert decision.status is RouteDecisionStatus.SELECTED
    assert decision.selected_target_id == "hand-4"
    assert decision.selected_title == "祝福"
    assert decision.selected_upgrade is UpgradeLevel.PLUS
    gray = next(candidate for candidate in decision.candidates if candidate.target_id == "hand-2")
    assert gray.rejection_code is RejectionCode.GRAY_CARD
    winner = next(candidate for candidate in decision.candidates if candidate.target_id == "hand-4")
    assert winner.total_score == sum(component.value for component in winner.components)
    assert {component.name for component in winner.components} == {
        "immediate_parameter",
        "good_condition_setup",
        "excellent_condition_setup",
        "future_fixed_guard",
        "stamina_cost",
        "focus_cost",
    }


def test_missing_deck_size_rejects_instead_of_reusing_historical_zero() -> None:
    decision = RinamiGarakutaRouteScorer().decide(replace(_observed_stop_state(), deck_size=None))

    assert decision.status is RouteDecisionStatus.REJECTED
    assert decision.rejection_code is RejectionCode.MISSING_STATE_FIELD
    assert decision.rejection_detail == "deck_size"


def test_stale_or_untrusted_state_is_rejected() -> None:
    scorer = RinamiGarakutaRouteScorer()

    stale = scorer.decide(replace(_observed_stop_state(), fresh=False))
    untrusted = scorer.decide(replace(_observed_stop_state(), trusted=False))

    assert stale.rejection_code is RejectionCode.STALE_STATE
    assert untrusted.rejection_code is RejectionCode.UNTRUSTED_STATE


def test_unknown_playable_card_rejects_candidate_and_cannot_be_guessed() -> None:
    state = replace(_observed_stop_state(), hand=(_card("unknown", "未観測カード"),))

    decision = RinamiGarakutaRouteScorer().decide(state)

    assert decision.rejection_code is RejectionCode.UNKNOWN_CARD
    assert decision.candidates[0].rejection_code is RejectionCode.UNKNOWN_CARD


def test_unknown_playable_card_stops_even_when_a_known_card_is_legal() -> None:
    state = replace(
        _observed_stop_state(),
        hand=(_card("known", "祝福"), _card("unknown", "未観測カード")),
    )

    decision = RinamiGarakutaRouteScorer().decide(state)

    assert decision.rejection_code is RejectionCode.UNKNOWN_CARD
    assert decision.selected_target_id is None


def test_gray_card_is_never_ranked_even_if_its_title_is_known() -> None:
    state = replace(_observed_stop_state(), hand=(_card("sleepy", "眠気", playable=False),))

    decision = RinamiGarakutaRouteScorer().decide(state)

    assert decision.rejection_code is RejectionCode.NO_LEGAL_CANDIDATE
    assert decision.candidates[0].rejection_code is RejectionCode.GRAY_CARD
    assert decision.candidates[0].total_score is None


def test_duplicate_title_and_upgrade_rejects_before_ranking() -> None:
    state = replace(
        _observed_stop_state(),
        hand=(_card("left", "祝福"), _card("right", "祝福")),
    )

    decision = RinamiGarakutaRouteScorer().decide(state)

    assert decision.rejection_code is RejectionCode.NON_UNIQUE_TITLE
    assert decision.candidates == ()


def test_exact_score_tie_is_rejected_instead_of_using_input_order() -> None:
    blessing = CardSpec(
        "祝福",
        "祝福",
        UpgradeLevel.BASE,
        4,
        0,
        True,
        "test",
        CardEffect(parameter_gain=26, good_condition_turns=1),
        "test",
    )
    alias = replace(blessing, card_id="同点カード", title="同点カード")
    state = replace(
        _observed_stop_state(),
        hand=(_card("left", "祝福"), _card("right", "同点カード")),
    )

    decision = RinamiGarakutaRouteScorer({blessing.key: blessing, alias.key: alias}).decide(state)

    assert decision.rejection_code is RejectionCode.SCORE_TIE
    assert all(candidate.is_legal for candidate in decision.candidates)


def test_insufficient_resource_and_already_used_cards_are_hard_gated() -> None:
    state = replace(
        _observed_stop_state(),
        stamina=3,
        hand=(_card("base", "祝福"), _card("plus", "祝福", UpgradeLevel.PLUS)),
        used_card_specs=frozenset({("祝福", UpgradeLevel.PLUS)}),
    )

    decision = RinamiGarakutaRouteScorer().decide(state)

    assert decision.rejection_code is RejectionCode.NO_LEGAL_CANDIDATE
    by_target = {candidate.target_id: candidate for candidate in decision.candidates}
    assert by_target["base"].rejection_code is RejectionCode.INSUFFICIENT_STAMINA
    assert by_target["plus"].rejection_code is RejectionCode.ALREADY_USED


def test_same_state_is_deterministic() -> None:
    scorer = RinamiGarakutaRouteScorer()
    state = _observed_stop_state()

    assert scorer.decide(state) == scorer.decide(state)
