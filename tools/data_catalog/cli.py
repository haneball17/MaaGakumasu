"""统一游戏数据目录 v2 CLI。"""

from __future__ import annotations

import json
import argparse
from pathlib import Path

from .io import read_json, read_jsonl, write_json, write_jsonl
from .fetch import fetch_url
from .paths import CACHE_ROOT, CANONICAL_ROOT, DECISIONS_ROOT, MANIFESTS_ROOT, ASSERTIONS_ROOT
from .derive import derive_catalog
from .report import report_catalog
from .promote import promote_assertions
from .refresh import extract_cached_idol_refresh
from .validate import validate_catalog
from .bootstrap import bootstrap_catalog

_IDOL_URL = "https://seesaawiki.jp/gakumasu/d/%a5%d7%a5%ed%a5%c7%a5%e5%a1%bc%a5%b9%a5%a2%a5%a4%a5%c9%a5%eb%b0%ec%cd%f7"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一游戏数据目录 v2")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--source", required=True, choices=("seesaa-idols",))
    extract = sub.add_parser("extract")
    extract.add_argument("--source", required=True, choices=("seesaa-idols", "legacy-baseline"))
    sub.add_parser("diff")
    promote = sub.add_parser("promote")
    promote.add_argument("--decision", type=Path, required=True)
    derive = sub.add_parser("derive")
    derive.add_argument("--check", action="store_true")
    derive.add_argument("--write-runtime", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--profile", choices=("ingest", "hif-release"), default="ingest")
    sub.add_parser("report")
    all_command = sub.add_parser("all")
    all_command.add_argument("--offline", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        result = fetch_url(_IDOL_URL, CACHE_ROOT / "raw" / "seesaa-idols.html")
        manifest = {
            "schema_version": "2.0",
            "source_id": "source:seesaawiki-idol-cards",
            "url": _IDOL_URL,
            "observed_at": result["fetched_at"],
            "content_hash": result["content_hash"],
            "parser_version": "seesaa-idols/2",
            "status": "complete" if result["status"] in {"ok", "not_modified"} else "failed",
        }
        write_json(MANIFESTS_ROOT / "seesaa-idols-latest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "extract":
        if args.source == "legacy-baseline":
            result = bootstrap_catalog()
        else:
            result = extract_cached_idol_refresh()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "diff":
        result = extract_cached_idol_refresh()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "promote":
        decision = read_json(args.decision)
        canonical_path = CANONICAL_ROOT / decision["canonical_file"]
        assertions_path = ASSERTIONS_ROOT / decision["assertions_file"]
        records = read_jsonl(canonical_path)
        promoted, audit = promote_assertions(records, read_jsonl(assertions_path), decision)
        write_jsonl(canonical_path, promoted)
        write_json(DECISIONS_ROOT / f"{audit['promotion_id'].replace(':', '_')}.json", audit)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0
    if args.command == "derive":
        differences = derive_catalog(check=args.check, write_runtime=args.write_runtime)
        if differences:
            print(json.dumps(differences, ensure_ascii=False, indent=2))
            return 1
        print("derived compatibility check passed")
        return 0
    if args.command == "validate":
        issues = validate_catalog(args.profile)
        if issues:
            print(json.dumps(issues, ensure_ascii=False, indent=2))
            return 1
        print(f"validation passed: {args.profile}")
        return 0
    if args.command == "report":
        print(json.dumps(report_catalog(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "all":
        ingest = validate_catalog("ingest")
        release = validate_catalog("hif-release")
        differences = derive_catalog(check=True)
        summary = report_catalog()
        result = {"ingest_issues": ingest, "hif_release_issues": release, "compatibility_differences": differences, "reports": summary}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if ingest or release or differences else 0
    return 1
