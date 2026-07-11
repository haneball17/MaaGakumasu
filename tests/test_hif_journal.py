import json
from datetime import datetime

from agent.hif.journal import HIFJournal, audit_hif_journal, frame_changed, load_hif_journal
from agent.hif.execution import HIFExecutionMode, parse_execution_mode, approve_card_execution


def test_hif_journal_records_jsonl_with_frame_evidence(tmp_path):
    journal = HIFJournal(root=tmp_path, session_id="case", now=lambda: datetime(2026, 7, 11, 12, 0, 0))
    before = journal.capture(b"before", "before")
    after = journal.capture(b"after", "after")
    entry = journal.record(
        "round1",
        "play_card",
        "verified",
        details={"card": "自然体の魅力", "tags": {"good_condition"}},
        before=before,
        after=after,
    )

    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    assert entry.screen_state == "round1"
    assert payload["details"]["card"] == "自然体の魅力"
    assert payload["before"]["fingerprint"] == before.fingerprint
    assert frame_changed(before, after)
    entries = load_hif_journal(journal.path)
    audit = audit_hif_journal(entries)
    assert audit.ok
    assert audit.verified_execution_count == 1


def test_journal_audit_rejects_verified_action_without_changed_frames(tmp_path):
    journal = HIFJournal(root=tmp_path, session_id="case", now=lambda: datetime(2026, 7, 11, 12, 0, 0))
    same = journal.capture(b"same", "same")
    journal.record("round1", "play_card", "verified", before=same, after=same)

    audit = audit_hif_journal(load_hif_journal(journal.path))

    assert not audit.ok
    assert audit.failures == ("entry#1:round1/play_card:verified_without_changed_frame",)


def test_card_execution_never_clicks_for_observation_or_incomplete_state():
    assert parse_execution_mode("bad-value") is HIFExecutionMode.OBSERVE
    assert not approve_card_execution(
        HIFExecutionMode.OBSERVE,
        screen_confidence=1.0,
        missing_fields=(),
        target_count=1,
        postcondition_supported=True,
    ).should_execute
    denied = approve_card_execution(
        HIFExecutionMode.SINGLE_STEP,
        screen_confidence=1.0,
        missing_fields=("focus",),
        target_count=1,
        postcondition_supported=True,
    )
    assert denied.reason == "missing_required_state"
