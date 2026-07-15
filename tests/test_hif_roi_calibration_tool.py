import sys

import pytest

from tools import hif_roi_calibration


def test_round_metric_field_is_accepted_only_with_its_matching_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["hif_roi_calibration.py", "--kind", "round_metrics", "--field", "param_vo", "--roi", "1,2,3,4"])

    args = hif_roi_calibration.parse_args()

    assert args.kind == "round_metrics"
    assert args.field == "param_vo"


def test_calibration_field_groups_are_disjoint() -> None:
    assert "param_vo" not in hif_roi_calibration.EXAM_NUMERIC_FIELDS
    assert "leader_score_pair" in hif_roi_calibration.SETTLEMENT_METRIC_FIELDS
