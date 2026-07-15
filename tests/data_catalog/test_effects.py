import pytest

from tools.data_catalog.effects import parse_effect_text, verified_hif_effect, apply_executable_ast


def test_unparsed_effect_is_preserved_as_unknown():
    parsed = parse_effect_text("パラメータ+10 未対応の特殊文法")
    assert parsed.parse_status == "partial"
    assert parsed.ast[-1]["op"] == "unknown"
    assert parsed.unmatched


def test_verified_blessing_has_complete_executable_ast():
    parsed = verified_hif_effect("祝福", "+", "パラメータ+ 40 好調 1ターン")
    assert parsed is not None
    assert parsed.parse_status == "complete"
    result = apply_executable_ast({"parameter": 0, "statuses": {}}, parsed.ast)
    assert result["parameter"] == 40
    assert result["statuses"]["status:good_condition"] == 1


def test_verified_effect_rejects_source_drift():
    assert verified_hif_effect("祝福", "+", "パラメータ+41 好調 1ターン") is None


def test_executor_rejects_condition_and_invalid_boundary():
    node = {
        "op": "add_parameter",
        "value": 1,
        "condition": {"status": "status:good_condition", "minimum": 2},
    }
    with pytest.raises(ValueError, match="effect_condition_rejected"):
        apply_executable_ast({"statuses": {"status:good_condition": 1}}, [node])
    with pytest.raises(ValueError, match="invalid_effect_value"):
        apply_executable_ast({}, [{"op": "add_parameter", "value": -1, "condition": None}])


def test_executor_rejects_unknown_operations():
    with pytest.raises(ValueError, match="unsupported_effect_op"):
        apply_executable_ast({}, [{"op": "unknown", "value": 0, "condition": None}])


def test_executable_card_movement_and_use_count_have_normal_and_boundary_behavior():
    ast = [
        {
            "op": "move_card",
            "value": 1,
            "condition": None,
            "source_zone": "deck_or_discard",
            "destination_zone": "deck_top",
            "card_filter": {"rarity": "SSR"},
        },
        {"op": "add_card_uses", "value": 1, "condition": None},
        {"op": "draw_card", "value": 2, "condition": None},
    ]
    result = apply_executable_ast({"deck": [{"rarity": "R"}], "discard": [{"rarity": "SSR"}], "hand": []}, ast)
    assert result["card_uses"] == 1
    assert result["hand"] == [{"rarity": "SSR"}, {"rarity": "R"}]
    with pytest.raises(ValueError, match="insufficient_move_candidates"):
        apply_executable_ast({"deck": [], "discard": []}, [ast[0]])


def test_redraw_discards_old_hand_and_draws_only_available_cards():
    result = apply_executable_ast(
        {"hand": ["old-1", "old-2"], "deck": ["new"], "discard": []},
        [{"op": "redraw_hand", "value": 0, "condition": None}],
    )
    assert result["hand"] == ["new"]
    assert result["discard"] == ["old-1", "old-2"]
