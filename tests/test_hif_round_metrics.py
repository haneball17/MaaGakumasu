from agent.hif.round_metrics import (
    MetricIssueCode,
    parse_integer,
    build_round_metrics,
    parse_settlement_score,
    parse_stage_multiplier,
    build_settlement_metrics,
)


def test_round_metrics_require_every_calibrated_value_before_becoming_complete() -> None:
    metrics = build_round_metrics(
        {
            "param_vo": "399,277",
            "param_da": "304,099",
            "param_vi": "111,318",
            "current_score": "814,694",
            "stage_multiplier": "3807%",
        }
    )

    assert metrics.params.vocal == 399277
    assert metrics.params.dance == 304099
    assert metrics.params.visual == 111318
    assert metrics.current_score == 814694
    assert metrics.stage_multiplier == 38.07
    assert metrics.is_complete


def test_round_metrics_do_not_turn_partial_or_ambiguous_ocr_into_a_score() -> None:
    metrics = build_round_metrics({"param_vo": "399277", "param_da": "304099", "param_vi": "111318"})

    assert metrics.current_score is None
    assert metrics.stage_multiplier is None
    assert metrics.missing_fields == ("current_score", "stage_multiplier")
    assert not metrics.is_complete


def test_round_metrics_preserve_conflict_as_a_typed_issue() -> None:
    metrics = build_round_metrics(
        {"stage_multiplier": "3807%"},
        conflicting_fields=frozenset({"current_score"}),
    )

    issue = next(issue for issue in metrics.issues if issue.field == "current_score")
    assert issue.code is MetricIssueCode.CONFLICT


def test_settlement_metrics_derives_the_multiplier_from_the_observed_score_pair() -> None:
    metrics = build_settlement_metrics("4,756,391+2,692,097")

    assert metrics.base_score == 4756391
    assert metrics.bonus_score == 2692097
    assert metrics.final_score == 7448488
    assert metrics.effective_multiplier == 7448488 / 4756391
    assert metrics.is_complete


def test_metric_parsers_refuse_text_that_contains_unrelated_numbers() -> None:
    assert parse_integer("Vo 399277") is None
    assert parse_stage_multiplier("倍率 120%") is None
    assert parse_settlement_score("4,756,391 +2,692,097 / 1") == (None, None)
