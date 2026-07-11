"""只读审计 HIF Journal 的执行证据完整性。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.hif.journal import audit_hif_journal, load_hif_journal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读审计 HIF Journal 的前后帧验证证据")
    parser.add_argument("journal", type=Path, help="debug/hif-journal 下的 JSONL 文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = audit_hif_journal(load_hif_journal(args.journal))
    print(
        json.dumps(
            {
                "entry_count": audit.entry_count,
                "verified_execution_count": audit.verified_execution_count,
                "ok": audit.ok,
                "failures": audit.failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if audit.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
