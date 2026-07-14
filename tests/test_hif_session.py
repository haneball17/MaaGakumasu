from agent.hif.session import HIFRunSession


def test_hif_session_keeps_only_confirmed_cross_page_facts():
    session = HIFRunSession()
    session.record_p_item("もじゃ（黄）", 1)
    session.record_p_item("花もじゃ（黄）", 2)
    session.record_card("round1", "お姉さんの感覚")

    assert session.latest_p_item(1) == "もじゃ（黄）"
    assert session.latest_p_item(2) == "花もじゃ（黄）"
    assert session.card_was_played("round1", "お姉さんの感覚")
    assert not session.card_was_played("round2", "お姉さんの感覚")


def test_hif_session_tracks_pending_reward_and_stops_safe_advance_frame_cycles():
    session = HIFRunSession()
    session.set_pending_reward("drink", "初星黒酢", "candidate_left")

    assert session.pending_reward is not None
    assert session.pending_reward.name == "初星黒酢"
    session.set_pending_select_change("スポットライト")
    assert session.pending_select_change is not None
    assert session.pending_select_change.target_name == "スポットライト"
    assert session.record_safe_advance("next-frame")
    assert not session.record_safe_advance("next-frame")

    session.clear_pending_reward()
    session.clear_pending_select_change()
    session.reset_safe_advance()
    assert session.pending_reward is None
    assert session.pending_select_change is None
    assert session.safe_advance_count == 0
