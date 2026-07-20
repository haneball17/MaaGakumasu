from __future__ import annotations

from copy import deepcopy

import pytest

from agent.hif.change_snapshot import SNAPSHOT_VERSION, snapshot_path, load_change_snapshot, write_change_snapshot


def _snapshot(session_id: str = "session-1") -> dict:
    return {
        "version": SNAPSHOT_VERSION,
        "session_id": session_id,
        "stage": "deck_snapshot",
        "candidates": [],
        "source_instances": [],
        "missing_slots": [],
        "deck_complete": False,
        "reroll_count": 3,
        "decision": None,
        "evidence_frames": [],
        "updated_at": "2026-07-20T23:50:00",
    }


def test_change_snapshot_write_replaces_atomically_and_load_requires_the_explicit_session(tmp_path):
    first = _snapshot()
    target = write_change_snapshot(tmp_path, first)
    second = deepcopy(first)
    second["reroll_count"] = 2
    write_change_snapshot(tmp_path, second)

    assert target == snapshot_path(tmp_path, "session-1")
    assert not target.with_suffix(".tmp").exists()
    assert load_change_snapshot(tmp_path, "session-1")["reroll_count"] == 2


@pytest.mark.parametrize("mutator", [lambda snapshot: snapshot.pop("stage"), lambda snapshot: snapshot.update(session_id="../other")])
def test_change_snapshot_rejects_incomplete_or_unsafe_payloads(tmp_path, mutator):
    snapshot = _snapshot()
    mutator(snapshot)

    with pytest.raises(ValueError):
        write_change_snapshot(tmp_path, snapshot)


def test_change_snapshot_rejects_corruption_and_session_mismatch(tmp_path):
    target = snapshot_path(tmp_path, "session-1")
    tmp_path.mkdir(exist_ok=True)
    target.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="不可读"):
        load_change_snapshot(tmp_path, "session-1")

    write_change_snapshot(tmp_path, _snapshot())
    with pytest.raises(ValueError, match="不可读|不匹配"):
        load_change_snapshot(tmp_path, "session-2")
