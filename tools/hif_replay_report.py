"""HIF 决策复盘总表:读 debug/decisions/session-*.jsonl 生成一局决策总表(终端+markdown)。

用法:
    python tools/hif_replay_report.py                 # 取最新 session
    python tools/hif_replay_report.py session-20260815.jsonl   # 指定文件(相对 debug/decisions/)
"""

from __future__ import annotations

import sys
import json
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECISIONS_DIR = REPO / "debug" / "decisions"


def _load_viewer():
    """按文件加载 viewer.py(无 maafw 依赖;避免 agent 包 __init__ 的 custom.reco import 链)。"""
    spec = importlib.util.spec_from_file_location("hif_viewer", REPO / "agent" / "hif" / "decisions" / "viewer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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


def _is_noise_passthrough(text) -> bool:
    """默认不过滤(独立调用/测试兼容);main 注入 viewer._is_noise_text。"""
    return False


def _describe_candidates(rec: dict, noise) -> str:
    """候选/选择摘要:三选一带分数(?=卡名未读),其他带文本(OCR 碎片噪音隐藏)。"""
    candidates = rec.get("candidates") or []
    if candidates and isinstance(candidates[0], dict) and "score" in candidates[0]:
        parts = []
        for c in candidates:
            card = c.get("card") or "卡名未读"
            if card == "?":
                card = "卡名未读"
            parts.append(f"{card}={c['score']:g}")
        chosen = rec.get("chosen_card") or "卡名未读"
        return f"[{','.join(parts)}] → {chosen}"
    if candidates:
        clean = [c for c in candidates if not noise(c)]
        head = " / ".join(clean[:3])
        rest = f" 等 {len(clean)} 项" if len(clean) > 3 else ""
        chosen = rec.get("chosen") or rec.get("reason") or ""
        return f"{head if clean else '(OCR碎片)'}{rest} → {chosen}"
    return rec.get("chosen") or rec.get("reason") or rec.get("mode") or ""


def build_rows(records: list[dict], noise=_is_noise_passthrough) -> list[list[str]]:
    """同 screen 连续记录合并为组行(×N+选择序列),其余逐条。"""
    rows = []
    i = 0
    while i < len(records):
        rec = records[i]
        screen = rec.get("screen", "?")
        j = i
        while j + 1 < len(records) and records[j + 1].get("screen", "?") == screen:
            j += 1
        group = records[i : j + 1]
        label = SCREEN_LABELS.get(screen, screen)
        if len(group) == 1:
            flag = "⚠空证据" if rec.get("evidence_empty") else ""
            if rec.get("action") == "reroll":
                flag = (flag + " 重抽").strip()
            rows.append([rec.get("ts", ""), rec.get("_day", "?"), label, rec.get("action", ""), _describe_candidates(rec, noise), "有" if rec.get("overrides") else "", flag])
        else:
            seq = [str(r.get("chosen_card") or r.get("chosen") or r.get("policy") or r.get("mode") or "") for r in group]
            seq = [s for s in seq if s]
            uniq = sorted(set(seq))
            detail = "(" + "→".join(uniq[:3]) + (f" …共{len(group)}条" if len(seq) > 3 else "") + ")"
            flags = "⚠空证据" if any(r.get("evidence_empty") for r in group) else ""
            rows.append([f"{group[0].get('ts', '')}~{group[-1].get('ts', '')}", group[0].get("_day", "?"), f"{label}×{len(group)}", "组", detail, "", flags])
        i = j + 1
    return rows


def render_table(rows: list[list[str]]) -> str:
    headers = ["时间", "Day", "页面", "动作", "候选→选择/原因", "调参", "标记"]
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
    viewer = _load_viewer()
    viewer._attach_day_labels(records)

    table = render_table(build_rows(records, noise=viewer._is_noise_text))
    print(f"# HIF 决策总表 {jsonl.name}（{len(records)} 条）\n")
    print(table)

    out_md = jsonl.with_suffix(".md")
    out_md.write_text(f"# HIF 决策总表 {jsonl.name}（{len(records)} 条）\n\n```\n{table}\n```\n", encoding="utf-8")
    print(f"\nmarkdown: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
