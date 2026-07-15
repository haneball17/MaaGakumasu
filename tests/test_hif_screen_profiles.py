from agent.hif.observation import observe_hif_page
from agent.hif.screen_profiles import load_hif_screen_profiles


def test_screen_profiles_cover_all_reviewed_roi_sections_and_stay_inside_hif_frame():
    profiles = load_hif_screen_profiles()

    assert len(profiles.review_sections) == 35
    assert profiles.button_roi("hif_start_confirm", "start") == (210, 1030, 300, 105)
    assert profiles.button_roi("drink_reward", "receive") == (230, 1052, 260, 84)
    assert profiles.get("drink_reward").anchors[0].roi == (120, 590, 520, 80)
    assert profiles.get("skill_reward").anchors[0].roi == (112, 585, 510, 66)
    assert profiles.get("skill_reward").anchors[0].pattern == "受[けは]取るスキルカードを選んでください"
    assert profiles.get("skill_reward").matches(("受け取るスキルカードを選んでください。",))
    assert profiles.get("skill_reward").matches(("受は取るスキルカードを選んでください。",))
    assert profiles.get("skill_reward").regions["candidate_left"] == (158, 821, 127, 128)
    assert profiles.get("skill_reward").regions["candidate_center"] == (297, 821, 127, 128)
    assert profiles.get("skill_reward").regions["candidate_right"] == (436, 821, 127, 128)
    assert profiles.get("skill_reward").regions["detail_name"] == (118, 500, 500, 60)
    assert profiles.get("skill_reward").regions["reveal_name"] == (72, 840, 576, 76)
    assert profiles.get("drink_reward").regions["candidate_left"] == (158, 822, 127, 127)
    assert profiles.get("drink_reward").regions["candidate_center"] == (297, 822, 127, 127)
    assert profiles.get("drink_reward").regions["candidate_right"] == (436, 822, 127, 127)
    assert profiles.get("drink_reward").regions["reveal_name"] == (72, 840, 576, 76)
    assert profiles.get("finals_prepare").regions["lesson_accent_left"] == (205, 1008, 55, 55)
    assert profiles.get("finals_prepare").regions["lesson_accent_center"] == (369, 1008, 55, 55)
    assert profiles.get("finals_prepare").regions["lesson_accent_right"] == (534, 1008, 55, 55)
    assert profiles.get("class_options").regions["preview"] == (52, 434, 616, 205)
    assert profiles.get("class_options").regions["option_top"] == (52, 650, 616, 90)
    assert profiles.get("select_change_target").regions["candidate_left"] == (158, 837, 127, 128)
    assert profiles.get("select_change_target").regions["detail_name"] == (180, 500, 360, 60)
    source_deck = profiles.get("select_change_source_deck")
    assert source_deck is not None
    assert [(anchor.anchor_id, anchor.roi) for anchor in source_deck.anchors] == [
        ("prompt_start", (100, 570, 150, 55)),
        ("prompt_end", (490, 570, 140, 55)),
    ]
    assert source_deck.regions["visible_slot_r1c1"] == (80, 638, 120, 120)
    assert source_deck.regions["visible_slot_r3c4"] == (521, 933, 120, 120)
    assert profiles.button_roi("score_settlement", "next") == (230, 1094, 258, 82)
    assert profiles.get("round1").regions["deck_button"] == (519, 1174, 80, 82)
    round_details = profiles.get("round_details")
    assert round_details is not None
    assert [(anchor.anchor_id, anchor.roi) for anchor in round_details.anchors] == [
        ("score", (20, 110, 220, 80)),
        ("hand_info", (540, 420, 170, 90)),
    ]
    assert round_details.regions["close"] == (314, 1118, 92, 92)
    hand_history = profiles.get("hand_history_view")
    assert hand_history is not None
    assert [(anchor.anchor_id, anchor.roi) for anchor in hand_history.anchors] == [
        ("title", (15, 565, 500, 80)),
        ("used_cards", (35, 860, 430, 70)),
    ]
    ranking_transition = profiles.get("finals_ranking_transition")
    assert ranking_transition is not None
    assert [(anchor.anchor_id, anchor.roi) for anchor in ranking_transition.anchors] == [
        ("title", (0, 120, 720, 120)),
        ("prompt", (200, 1120, 320, 120)),
    ]
    assert profiles.button_roi("missing", "button") is None
    for profile in profiles.profiles.values():
        for anchor in profile.anchors:
            assert anchor.roi[0] + anchor.roi[2] <= 720
            assert anchor.roi[1] + anchor.roi[3] <= 1280
        for region in profile.regions.values():
            assert region[0] + region[2] <= 720
            assert region[1] + region[3] <= 1280


def test_verified_safe_advance_point_does_not_overlap_known_resource_choice_controls():
    point = (341, 204)
    profiles = load_hif_screen_profiles()

    for screen_id in ("drink_reward", "skill_reward", "select_change_target", "select_change_source_deck", "drink_overflow"):
        profile = profiles.get(screen_id)
        assert profile is not None
        for button in profile.buttons.values():
            x, y, width, height = button.roi
            assert not (x <= point[0] < x + width and y <= point[1] < y + height)


def test_page_observation_requires_a_unique_anchor_match():
    finals_prepare = observe_hif_page(["H.I.F本戦まで", "6日"])
    assert finals_prepare.screen_id == "finals_prepare"
    assert finals_prepare.is_unique
    assert observe_hif_page(["授業", "トラブル追加"]).screen_id == "class_options"
    assert observe_hif_page(["授業", "チェンジで獲得するスキルカードを選んでください"]).screen_id == "select_change_target"
    assert observe_hif_page(["チェンジする", "てください"]).screen_id == "select_change_source_deck"
    assert observe_hif_page(["Pドリンク所持上限", "保持しておくドリンクを選んでください"]).screen_id == "drink_overflow"
    assert observe_hif_page(["メモリーにするフォトを選んでください"]).screen_id == "memory_photo_select"
    assert observe_hif_page(["現在順位", "タップして次へ"]).screen_id == "finals_ranking_transition"

    ambiguous = observe_hif_page(["インターバル", "Pポイントと交換するものを選んでください"])
    assert ambiguous.screen_id is None
    assert set(ambiguous.matched_screen_ids) == {"interval_shop", "consult_shop"}
