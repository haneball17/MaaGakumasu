import sys
import json
import subprocess

from tools.data_catalog.io import read_json, read_jsonl, sha256_file
from tools.data_catalog.paths import PROJECT_ROOT, REPORTS_ROOT, CANONICAL_ROOT
from tools.data_catalog.derive import derive_catalog
from tools.data_catalog.validate import validate_catalog


def test_migrated_baseline_counts_and_legacy_hashes_are_frozen():
    baseline = read_json(REPORTS_ROOT / "legacy_baseline.json")
    assert len(read_json(CANONICAL_ROOT / "characters.json")) == 13
    assert len(read_jsonl(CANONICAL_ROOT / "produce_idol_cards.jsonl")) == 136
    wiki_skills = [
        item
        for item in read_jsonl(CANONICAL_ROOT / "skill_cards.jsonl")
        if any(key.get("source_id") == "source:seesaawiki-skill-cards-2026-07-01" for key in item["source_keys"])
    ]
    assert len(wiki_skills) == 122
    assert len(read_jsonl(CANONICAL_ROOT / "drinks.jsonl")) == 28
    for item in baseline["files"]:
        path = PROJECT_ROOT / item["path"]
        assert sha256_file(path) == item["sha256"]


def test_legacy_shared_bonus_is_not_promoted_as_three_independent_facts():
    for card in read_jsonl(CANONICAL_ROOT / "produce_idol_cards.jsonl"):
        profile = card["stat_profiles"][0]
        assert profile["vo"]["bonus_percent"] is None
        assert profile["da"]["bonus_percent"] is None
        assert profile["vi"]["bonus_percent"] is None
        assert profile["legacy_shared_bonus"]["evidence_status"] == "legacy_shared"


def test_ingest_release_and_derived_compatibility_pass():
    assert validate_catalog("ingest") == []
    assert validate_catalog("hif-release") == []
    assert derive_catalog(check=True) == []


def test_offline_clis_do_not_import_network_or_fetch_dependencies():
    script_template = """
import builtins, runpy, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'bs4' or name == 'requests' or name.startswith('urllib.request'):
        raise AssertionError('offline command imported network dependency: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
sys.argv = {argv!r}
runpy.run_path({path!r}, run_name='__main__')
"""
    cases = (
        ("tools/data_catalog.py", ["tools/data_catalog.py", "validate", "--profile", "ingest"]),
        ("tools/data_pipeline.py", ["tools/data_pipeline.py", "validate"]),
    )
    for path, argv in cases:
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", script_template.format(path=path, argv=argv)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "validation passed" in completed.stdout


def test_all_offline_cli_is_a_network_free_release_gate():
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "tools/data_catalog.py", "all", "--offline"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ingest_issues"] == []
    assert payload["hif_release_issues"] == []
    assert payload["compatibility_differences"] == []
