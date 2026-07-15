from tools.data_catalog.reconcile import reconcile_records, assertion_conflicts


def test_reconcile_classifies_all_field_changes_deterministically() -> None:
    before = [{"entity_id": "card:1", "names": {"ja-JP": {"canonical": "旧名"}}, "value": 1, "parse_status": "complete"}]
    after = [{"entity_id": "card:1", "names": {"ja-JP": {"canonical": "新名"}}, "value": 2, "parse_status": "partial"}]

    changes = reconcile_records(before, after)
    assert [(item["field_path"], item["category"]) for item in changes] == [
        ("/names/ja-JP/canonical", "text"),
        ("/parse_status", "parse_regression"),
        ("/value", "numeric"),
    ]
    assert changes == reconcile_records(before, after)
    assert all(item["requires_promotion"] for item in changes)


def test_reconcile_reports_add_remove_and_conflicting_assertions() -> None:
    changes = reconcile_records([{"entity_id": "old:1"}], [{"entity_id": "new:1"}])
    assert {item["category"] for item in changes} == {"entity_added", "entity_removed"}

    conflicts = assertion_conflicts(
        [
            {"assertion_id": "a", "entity_id": "x", "field_path": "/value", "value": 1},
            {"assertion_id": "b", "entity_id": "x", "field_path": "/value", "value": 2},
        ]
    )
    assert conflicts[0]["assertion_ids"] == ["a", "b"]
    assert conflicts[0]["reason_code"] == "conflicting_assertions"
