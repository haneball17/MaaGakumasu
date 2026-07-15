from agent.hif.adapters.active_effects import parse_active_effects


def test_parses_current_round1_effect_list_into_execution_ready_snapshot() -> None:
    snapshot = parse_active_effects(
        (
            "発動予約",
            "1回 1ターン",
            "パラメータ上昇量増加",
            "スコア上昇量を30％増加（好印象による上昇も含む）",
            "30% 1ターン",
            "消費体力減少",
            "消費体力を50％軽減 5ターン",
            "絶好調",
            "2ターン",
        )
    )

    assert snapshot.score_increase_percent == 30
    assert snapshot.score_increase_turns == 1
    assert snapshot.stamina_cost_reduction_percent == 50
    assert snapshot.stamina_cost_reduction_turns == 5
    assert snapshot.excellent_turns == 2
    assert snapshot.reservation_count == 1
    assert snapshot.reservation_turns == 1
    assert snapshot.execution_ready


def test_rejects_ambiguous_or_incomplete_effect_values() -> None:
    snapshot = parse_active_effects(
        (
            "パラメータ上昇量増加",
            "スコア上昇量を30%増加",
            "スコア上昇量を40%増加",
            "消費体力減少",
            "消費体カを50%軽減",
        )
    )

    assert snapshot.score_increase_percent is None
    assert snapshot.stamina_cost_reduction_percent == 50
    assert not snapshot.execution_ready
