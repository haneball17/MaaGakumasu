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
