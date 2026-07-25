from agent.hif.decisions.change_pair import choose_change_pair


def test_change_pair_decision_uses_stable_slot_order_for_ties():
    decision = choose_change_pair(
        ("candidate_left", "candidate_center", "candidate_right"),
        ("visible_slot_r1c2", "visible_slot_r2c1"),
    )

    assert decision is not None
    assert decision.candidate_slot == "candidate_left"
    assert decision.source_slot == "visible_slot_r1c2"
    assert decision.tie_break_fallback is True


def test_change_pair_decision_rejects_an_empty_side():
    assert choose_change_pair((), ("visible_slot_r1c1",)) is None
    assert choose_change_pair(("candidate_left",), ()) is None
