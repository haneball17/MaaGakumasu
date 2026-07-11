import json
from pathlib import Path

from agent.hif.pipeline_validation import _remove_jsonc_trivia, load_pipeline_nodes, load_registered_custom_actions, validate_hif_pipeline


def test_hif_pipeline_references_existing_nodes_and_registered_actions():
    pipeline_root = Path("assets/resource/base/pipeline")
    all_nodes = load_pipeline_nodes(pipeline_root)
    hif_nodes = json.loads((pipeline_root / "ProduceHIF.json").read_text(encoding="utf-8"))

    issues = validate_hif_pipeline(
        hif_nodes,
        known_nodes=all_nodes,
        registered_custom_actions=load_registered_custom_actions("agent/custom/action"),
    )

    assert issues == ()


def test_hif_pipeline_validation_reports_missing_action_and_target():
    issues = validate_hif_pipeline(
        {
            "Node": {
                "action": {"type": "Custom", "param": {"custom_action": "MissingAction"}},
                "next": ["[JumpBack]MissingNode"],
            }
        },
        known_nodes={"Node"},
        registered_custom_actions=(),
    )

    assert issues == (
        "Node:unregistered_custom_action:MissingAction",
        "Node:missing_next_target:[JumpBack]MissingNode",
    )


def test_pipeline_jsonc_reader_preserves_comment_markers_inside_strings():
    payload = json.loads(_remove_jsonc_trivia('{"url":"https://example.invalid/a//b", /* note */ "items":[1,],}'))

    assert payload == {"url": "https://example.invalid/a//b", "items": [1]}
