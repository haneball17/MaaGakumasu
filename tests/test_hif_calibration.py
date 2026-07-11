import json

import pytest

from agent.hif.calibration import load_hif_roi_calibration


def test_default_calibration_keeps_unverified_exam_rois_disabled():
    calibration = load_hif_roi_calibration()

    assert calibration.frame_size == (720, 1280)
    assert calibration.exam_numeric == {}
    assert not calibration.is_exam_execution_ready


def test_calibration_requires_complete_traceable_dataset_for_exam_execution(tmp_path):
    path = tmp_path / "ready.json"
    fields = {key: [0, 0, 1, 1] for key in ("good_condition", "reprise", "focus", "turn", "flow", "deck_size", "p_drinks")}
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frame_size": [720, 1280],
                "exam_numeric": fields,
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
