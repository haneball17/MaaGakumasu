"""HIF 决策复盘总表:读 debug/decisions/session-*.jsonl 生成一局决策总表(终端+markdown)。

用法:
    python tools/hif_replay_report.py                 # 取最新 session
    python tools/hif_replay_report.py session-20260815.jsonl   # 指定文件(相对 debug/decisions/)
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECISIONS_DIR = REPO / "debug" / "decisions"

# 页面名的中文短标签(总表可读性)
SCREEN_LABELS = {
    "finals_action_select": "日程选择",
    "hif_class_options": "授業选项",
    "select_change_target": "変卡目标",
    "select_change_source_deck": "変卡源牌",
    "select_change_done": "変卡完成",
    "hif_drink_reward": "饮料三选一",
    "hif_skill_reward": "技能卡三选一",
    "hif_sp_card_select": "SP效果卡",
    "hif_drink_overflow": "饮料上限",
    "consult_shop": "相談",
    "hif_p_item_select": "P道具",
    "round1_initial": "Round1",
    "unknown_stop": "安全停止",
}


def _describe_candidates(rec: dict) -> str:
    """候选/选择摘要:三选一带分数,其他带文本。"""
    candidates = rec.get("candidates") or []
    if candidates and isinstance(candidates[0], dict) and "score" in candidates[0]:
        parts = []
        for c in candidates:
            card = c.get("card") or "?"
            parts.append(f"{card}={c['score']:g}")
        chosen = rec.get("chosen_card") or "?"
        return f"[{','.join(parts)}] → {chosen}"
    if candidates:
        chosen = rec.get("chosen") or rec.get("reason") or ""
        return f"{candidates} → {chosen}"
    return rec.get("chosen") or rec.get("reason") or rec.get("mode") or ""


def build_rows(records: list[dict]) -> list[list[str]]:
    rows = []
    for rec in records:
        screen = SCREEN_LABELS.get(rec.get("screen", "?"), rec.get("screen", "?"))
        flag = ""
        if rec.get("evidence_empty"):
            flag = "⚠空证据"
        if rec.get("action") == "reroll":
            flag = (flag + " 重抽").strip()
        detail = _describe_candidates(rec)
        overrides = "有" if rec.get("overrides") else ""
        rows.append([rec.get("ts", ""), screen, rec.get("action", ""), detail, overrides, flag])
    return rows


def render_table(rows: list[list[str]]) -> str:
    headers = ["时间", "页面", "动作", "候选→选择/原因", "调参", "标记"]
    widths = [max(len(str(r[i])) for r in rows + [headers]) for i in range(len(headers))]
    lines = [" | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("-|-".join("-" * w for w in widths))
    for row in rows:
        lines.append(" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))
    return "\n".join(lines)


def main() -> int:
    if not DECISIONS_DIR.exists():
        print("无 debug/decisions/ 目录")
        return 1
    if len(sys.argv) > 1:
        jsonl = DECISIONS_DIR / sys.argv[1]
    else:
        sessions = sorted(DECISIONS_DIR.glob("session-*.jsonl"))
        if not sessions:
            print("无 session-*.jsonl")
            return 1
        jsonl = sessions[-1]
    records = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]

    table = render_table(build_rows(records))
    print(f"# HIF 决策总表 {jsonl.name}（{len(records)} 条）\n")
    print(table)

    out_md = jsonl.with_suffix(".md")
    out_md.write_text(f"# HIF 决策总表 {jsonl.name}（{len(records)} 条）\n\n```\n{table}\n```\n", encoding="utf-8")
    print(f"\nmarkdown: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
