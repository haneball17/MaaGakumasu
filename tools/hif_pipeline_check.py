"""离线检查 HIF Pipeline 的节点引用与 Custom Action 注册。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.hif.pipeline_validation import load_pipeline_nodes, load_registered_custom_actions, validate_hif_pipeline


def main() -> int:
    pipeline_root = ROOT / "assets" / "resource" / "base" / "pipeline"
    hif_path = pipeline_root / "ProduceHIF.json"
    all_nodes = load_pipeline_nodes(pipeline_root)
    hif_nodes = json.loads(hif_path.read_text(encoding="utf-8"))
    issues = validate_hif_pipeline(
        hif_nodes,
        known_nodes=all_nodes,
        registered_custom_actions=load_registered_custom_actions(ROOT / "agent" / "custom" / "action"),
    )
    print(json.dumps({"ok": not issues, "issue_count": len(issues), "issues": issues}, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
