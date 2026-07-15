import pytest

from tools.data_catalog.promote import promote_assertions

ASSERTIONS = [
    {"assertion_id": "assertion:new-name", "entity_id": "card:1", "field_path": "/names/ja-JP/canonical", "value": "新名"},
    {"assertion_id": "assertion:rejected", "entity_id": "card:1", "field_path": "/names/ja-JP/canonical", "value": "別名"},
]


def test_promote_requires_explicit_auditable_decision() -> None:
    records, audit = promote_assertions(
        [{"entity_id": "card:1", "names": {"ja-JP": {"canonical": "旧名"}}}],
        ASSERTIONS,
        {
            "decision_id": "decision:1",
            "selected_assertion_ids": ["assertion:new-name"],
            "rejected_assertion_ids": ["assertion:rejected"],
            "reason": "两项来源交叉验证后采用新表记",
            "decided_at": "2026-07-15T00:00:00+08:00",
            "reviewer": "human",
        },
    )

    assert records[0]["names"]["ja-JP"]["canonical"] == "新名"
    assert audit["selected_assertion_ids"] == ["assertion:new-name"]
    assert audit["rejected_assertion_ids"] == ["assertion:rejected"]
    assert audit["promotion_id"].startswith("promotion:")


@pytest.mark.parametrize(
    "decision",
    [
        {"selected_assertion_ids": [], "reason": "x", "decided_at": "now"},
        {"selected_assertion_ids": ["missing"], "reason": "x", "decided_at": "now"},
        {"selected_assertion_ids": ["assertion:new-name"], "reason": "", "decided_at": "now"},
    ],
)
def test_promote_rejects_implicit_or_invalid_decisions(decision: dict) -> None:
    with pytest.raises(ValueError):
        promote_assertions([{"entity_id": "card:1"}], ASSERTIONS, decision)
