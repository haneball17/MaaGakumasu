from agent.hif.session import HIFRunSession, HIFSelectChangeSlot


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


def test_hif_session_keeps_change_snapshots_only_until_the_pending_change_is_cleared():
    session = HIFRunSession()
    target = HIFSelectChangeSlot("candidate_center", (297, 837, 127, 128), "始まりの合図", 0.99, "target-frame")
    source = HIFSelectChangeSlot("visible_slot_r2c1", (80, 786, 120, 120), "スリリング+", 0.98, "source-frame", page_index=1)

    session.set_select_change_target_snapshot((target,))
    session.set_select_change_source_snapshot((source,))
    session.set_pending_select_change(target.name, target.slot_id, target.slot_roi)

    assert session.pending_select_change is not None
    assert session.pending_select_change.target_slot == "candidate_center"
    assert session.select_change_target_snapshot == (target,)
    assert session.select_change_source_snapshot == (source,)
    session.clear_pending_select_change()
    assert session.select_change_target_snapshot == ()
    assert session.select_change_source_snapshot == ()


def test_hif_session_keeps_verified_hand_detail_titles_only_for_the_current_run():
    session = HIFRunSession()
    box = (19, 884, 138, 250)

    session.record_hand_detail_name(box, "話題沸騰")
    session.record_hand_detail_name((142, 884, 141, 248), "")

    assert session.hand_detail_name(box) == "話題沸騰"
    assert session.hand_detail_name((20, 884, 138, 250)) == "話題沸騰"
    assert session.hand_detail_name((142, 884, 141, 248)) is None
