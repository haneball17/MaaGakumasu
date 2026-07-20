from __future__ import annotations

import json
from pathlib import Path

from agent.hif.pipeline_validation import (
    find_unreachable_hif_nodes,
    load_hif_coverage_manifest,
    validate_hif_coverage_manifest,
)

PIPELINE_PATH = Path("assets/resource/base/pipeline/ProduceHIF.json")
MANIFEST_PATH = Path("assets/data/hif/pipeline_coverage.json")


def _pipeline():
    return json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))


def test_hif_coverage_manifest_exactly_matches_every_pipeline_node():
    pipeline = _pipeline()
    manifest = load_hif_coverage_manifest(MANIFEST_PATH)

    assert validate_hif_coverage_manifest(pipeline, manifest) == ()


def test_hif_unreachable_nodes_are_explicitly_declared_instead_of_silently_ignored():
    pipeline = _pipeline()
    manifest = load_hif_coverage_manifest(MANIFEST_PATH)
    unreachable = find_unreachable_hif_nodes(
        pipeline,
        entry_nodes=manifest["entry_nodes"],
        dynamic_targets=manifest["dynamic_targets"],
    )

    assert set(unreachable) == set(manifest["declared_unreachable"])


def test_hif_nodes_without_next_are_terminal_or_explicit_action_internal_stops():
    pipeline = _pipeline()
    manifest = load_hif_coverage_manifest(MANIFEST_PATH)
    stop_tasks = {name for name, node in pipeline.items() if node.get("action", {}).get("type") == "StopTask"}
    nextless = {name for name, node in pipeline.items() if not node.get("next")}

    assert nextless - stop_tasks == set(manifest["action_internal_stop_nodes"])


def test_unknown_pages_have_no_input_fallback_after_known_routes():
    pipeline = _pipeline()
    manifest = load_hif_coverage_manifest(MANIFEST_PATH)
    route = pipeline["ProduceEntryHIF"]["next"]

    for node_name in manifest["priority_before_safe_advance"]:
        assert route.index(node_name) < route.index("ProduceHIFUnknownStop"), node_name


def test_hif_router_stops_unknown_pages_without_safe_advance_input():
    route = _pipeline()["ProduceEntryHIF"]["next"]

    assert "ProduceHIFSafeAdvanceFlag" not in route
    assert route[-1] == "ProduceHIFUnknownStop"


def test_round1_routes_to_observation_then_stop_without_card_action():
    pipeline = _pipeline()

    assert pipeline["ProduceHIFRound1Flag"]["next"] == ["ProduceHIFRound1ObserveFlag"]
    assert pipeline["ProduceHIFRound1ObserveFlag"]["next"] == ["ProduceHIFRound1ReachedStop"]
