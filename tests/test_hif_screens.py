from agent.hif.screens import HIFScreenState, classify_hif_screen


def test_screen_classifier_distinguishes_finals_mode_from_remaining_days_banner():
    assert classify_hif_screen(["H.I.F本戦まで 6日"]).state is HIFScreenState.FINALS_PREPARE
    assert classify_hif_screen(["H.I.F 本戦モード"]).state is HIFScreenState.FINALS_MODE


def test_screen_classifier_handles_known_endgame_pages_and_rejects_ambiguity():
    assert classify_hif_screen(["インターバル", "Pポイントで利用するものを選んでください"]).state is HIFScreenState.INTERVAL
    assert classify_hif_screen(["メモリーにするフォトを選んでください"]).state is HIFScreenState.MEMORY_PHOTO_SELECT
    ambiguous = classify_hif_screen(["インターバル", "優勝"])

    assert ambiguous.state is HIFScreenState.UNKNOWN
    assert set(ambiguous.matched_states) == {HIFScreenState.INTERVAL, HIFScreenState.SETTLEMENT}
