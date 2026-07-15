import json

import pytest

from tools.data_catalog.io import read_json, read_jsonl, write_json, sha256_file, write_jsonl


def test_json_write_is_deterministic_and_uses_lf(tmp_path):
    path = tmp_path / "nested" / "data.json"
    write_json(path, {"z": 1, "名称": "月明かり", "a": [2, 1]})
    first = path.read_bytes()
    write_json(path, {"a": [2, 1], "名称": "月明かり", "z": 1})

    assert path.read_bytes() == first
    assert first.endswith(b"\n")
    assert b"\r\n" not in first
    assert read_json(path)["名称"] == "月明かり"
    assert len(sha256_file(path)) == 64


def test_jsonl_write_is_stable_sorted_and_round_trips(tmp_path):
    path = tmp_path / "data.jsonl"
    write_jsonl(path, [{"entity_id": "b", "value": 2}, {"value": 1, "entity_id": "a"}])
    first = path.read_bytes()
    write_jsonl(path, reversed(read_jsonl(path)))

    assert path.read_bytes() == first
    assert [row["entity_id"] for row in read_jsonl(path)] == ["a", "b"]
    assert all(" " not in line for line in path.read_text(encoding="utf-8").splitlines())


def test_invalid_jsonl_reports_line_number(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{}\n{"broken"\n', encoding="utf-8")

    with pytest.raises(ValueError, match=":2:"):
        read_jsonl(path)


def test_json_is_always_complete_after_replacement(tmp_path):
    path = tmp_path / "atomic.json"
    write_json(path, {"generation": 1})
    write_json(path, {"generation": 2, "payload": list(range(100))})

    assert json.loads(path.read_text(encoding="utf-8"))["generation"] == 2
    assert not list(tmp_path.glob(".atomic.json.*.tmp"))
