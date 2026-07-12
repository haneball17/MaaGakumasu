from agent.hif.observation import observe_hif_page
from agent.hif.screen_profiles import load_hif_screen_profiles


def test_screen_profiles_cover_all_reviewed_roi_sections_and_stay_inside_hif_frame():
    profiles = load_hif_screen_profiles()

    assert len(profiles.review_sections) == 34
    assert profiles.button_roi("drink_reward", "receive") == (230, 1052, 260, 84)
    assert profiles.button_roi("score_settlement", "next") == (230, 1094, 258, 82)
    assert profiles.button_roi("missing", "button") is None
    for profile in profiles.profiles.values():
        for anchor in profile.anchors:
            assert anchor.roi[0] + anchor.roi[2] <= 720
            assert anchor.roi[1] + anchor.roi[3] <= 1280
        for region in profile.regions.values():
            assert region[0] + region[2] <= 720
            assert region[1] + region[3] <= 1280


def test_page_observation_requires_a_unique_anchor_match():
    assert observe_hif_page(["Pドリンク所持上限", "保持しておくドリンクを選んでください"]).screen_id == "drink_overflow"
    assert observe_hif_page(["メモリーにするフォトを選んでください"]).screen_id == "memory_photo_select"

    ambiguous = observe_hif_page(["インターバル", "Pポイントと交換するものを選んでください"])
    assert ambiguous.screen_id is None
    assert set(ambiguous.matched_screen_ids) == {"interval_shop", "consult_shop"}
