import json

import pytest

from agent.hif.calibration import load_hif_roi_calibration


def test_default_calibration_only_enables_fields_with_current_mumu_evidence():
    calibration = load_hif_roi_calibration()

    assert calibration.frame_size == (720, 1280)
    assert set(calibration.exam_numeric) == {"good_condition", "reprise", "focus", "turn", "flow", "deck_size", "stamina"}
    assert calibration.device_id == "mumu12-instance1-127.0.0.1:16416"
    assert calibration.evidence_sha256
    assert calibration.exam_numeric["deck_size"] == (647, 174, 42, 39)
    assert calibration.round_metrics == {"current_score": (367, 119, 123, 45), "stage_multiplier": (65, 75, 150, 48)}
    assert calibration.round_metrics_panel == {"current_score": (42, 145, 135, 38)}
    assert calibration.settlement_metrics == {"leader_score_pair": (220, 290, 330, 75)}
    assert calibration.is_exam_execution_ready
    assert calibration.supports_exam_fields({"good_condition", "focus", "turn", "flow", "stamina"})


def test_calibration_requires_complete_traceable_dataset_for_exam_execution(tmp_path):
    path = tmp_path / "ready.json"
    fields = {
        key: [0, 0, 1, 1]
        for key in ("good_condition", "reprise", "focus", "turn", "flow", "deck_size", "p_drinks", "stamina")
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frame_size": [720, 1280],
                "exam_numeric": fields,
                "round_metrics": {"param_vo": [1, 1, 1, 1]},
                "settlement_metrics": {"score": [1, 1, 1, 1]},
                "device_id": "mumu-12-1",
                "evidence_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    assert load_hif_roi_calibration(path).is_exam_execution_ready


def test_calibration_rejects_out_of_bounds_roi(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frame_size": [720, 1280],
                "exam_numeric": {"focus": [700, 1200, 50, 100]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="超出"):
        load_hif_roi_calibration(path)
