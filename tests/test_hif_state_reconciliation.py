from datetime import UTC, datetime, timedelta

from agent.hif.adapters.state_reconciliation import (
    LedgerField,
    StateLedger,
    ObservedField,
    StateIssueCode,
    StateObservation,
    reconcile_state,
    rebuild_after_restart,
)

NOW = datetime(2026, 7, 15, 14, 0, tzinfo=UTC)


def observation(fields: dict[str, int], *, run_id: str = "run-1", age_seconds: int = 0, conflicts=None):
    captured_at = NOW - timedelta(seconds=age_seconds)
    return StateObservation(
        run_id,
        captured_at,
        {key: ObservedField(value, captured_at) for key, value in fields.items()},
        conflicts or {},
    )


def ledger(fields: dict[str, int], *, run_id: str = "run-1", verified: bool = True, age_seconds: int = 0):
    return StateLedger(
        run_id,
        {
            key: LedgerField(value, NOW - timedelta(seconds=age_seconds), f"action-{key}", verified)
            for key, value in fields.items()
        },
    )


def reconcile(obs, book=None):
    return reconcile_state(
        obs,
        book,
        required_fields=frozenset({"turn", "deck_size", "oneesan_used"}),
        ledger_fields=frozenset({"oneesan_used"}),
        now=NOW,
        max_observation_age=timedelta(seconds=5),
        max_ledger_age=timedelta(minutes=5),
    )


def test_reconcile_uses_current_screen_and_only_declared_ledger_fields() -> None:
    result = reconcile(observation({"turn": 6, "deck_size": 22}), ledger({"oneesan_used": 1}))

    assert result.is_trusted
    assert result.values == {"deck_size": 22, "oneesan_used": 1, "turn": 6}
    assert result.sources["deck_size"] == "screen"
    assert result.sources["oneesan_used"] == "ledger:action-oneesan_used"


def test_reconcile_rejects_missing_visible_field_instead_of_using_ledger() -> None:
    result = reconcile(observation({"turn": 6}), ledger({"deck_size": 22, "oneesan_used": 1}))

    issue = next(issue for issue in result.issues if issue.field == "deck_size")
    assert issue.code is StateIssueCode.MISSING
    assert "deck_size" not in result.values


def test_reconcile_rejects_conflict_stale_and_wrong_run() -> None:
    stale = reconcile(observation({"turn": 6, "deck_size": 22}, age_seconds=10), ledger({"oneesan_used": 1}))
    conflict = reconcile(
        observation({"turn": 6, "deck_size": 22}, conflicts={"deck_size": (21, 22)}),
        ledger({"oneesan_used": 1}),
    )
    wrong_run = reconcile(observation({"turn": 6, "deck_size": 22}), ledger({"oneesan_used": 1}, run_id="old-run"))

    assert any(issue.code is StateIssueCode.STALE for issue in stale.issues)
    assert any(issue.field == "deck_size" and issue.code is StateIssueCode.CONFLICT for issue in conflict.issues)
    assert any(issue.code is StateIssueCode.RUN_MISMATCH for issue in wrong_run.issues)


def test_reconcile_rejects_unverified_or_expired_ledger() -> None:
    unverified = reconcile(observation({"turn": 6, "deck_size": 22}), ledger({"oneesan_used": 1}, verified=False))
    expired = reconcile(observation({"turn": 6, "deck_size": 22}), ledger({"oneesan_used": 1}, age_seconds=301))

    assert any(issue.code is StateIssueCode.UNVERIFIED_LEDGER for issue in unverified.issues)
    assert any(issue.field == "oneesan_used" and issue.code is StateIssueCode.STALE for issue in expired.issues)


def test_restart_requires_rescan_and_rejects_visible_ledger_overlap() -> None:
    result = rebuild_after_restart(
        observation({"turn": 6, "deck_size": 22}),
        ledger({"oneesan_used": 1}),
        visible_fields=frozenset({"turn", "deck_size"}),
        ledger_fields=frozenset({"deck_size", "oneesan_used"}),
        now=NOW,
        max_observation_age=timedelta(seconds=5),
        max_ledger_age=timedelta(minutes=5),
    )

    assert not result.is_trusted
    assert any(issue.field == "deck_size" and issue.code is StateIssueCode.LEDGER_NOT_ALLOWED for issue in result.issues)
