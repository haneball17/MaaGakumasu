from agent.hif.ui_map import load_hif_ui_map


def test_ui_map_loads_observed_interval_and_settlement_button_rois():
    ui_map = load_hif_ui_map()

    assert ui_map.button_roi("interval_shop", "finish") == (565, 1045, 155, 84)
    assert ui_map.button_roi("score_settlement", "next") == (230, 1094, 258, 82)
    assert ui_map.button_roi("missing", "button") is None
