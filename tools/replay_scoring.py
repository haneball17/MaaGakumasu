"""HIF 决策日志离线回放:新旧双评分差异表(B5,设计文档第 6 节迁移路径第 3 步)。

对 session JSONL 中含 candidates 的三选一记录逐候选跑结构化数值评分
(scoring.score_card_by_name / score_drink_by_name),与实机当时的关键词分
(记录里的 score)对照,输出:
- 每候选 模型分/关键词分/评分来源(effects|keywords 兜底)
- 记录级 选中翻转(新 argmax ≠ 旧 chosen)清单,供人工审排名翻转是否
  发生在四盲区案例(数值/成本/上下文/手牌)而非噪声翻转
- 局面信号:day_remaining 取记录值(实机未存体力,回放退中性)

用法:
    python tools/replay_scoring.py [jsonl路径(默认最新 session-*.jsonl)]
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.hif.decisions.scoring import (  # noqa: E402
    ScoringParams,
    DecisionContext,
    score_card_by_name,
    score_drink_by_name,
)
from agent.hif.adapters.card_dict import normalize_card_name  # noqa: E402

DECISIONS_DIR = Path(__file__).resolve().parents[1] / "debug" / "decisions"


def replay(jsonl_path: Path, params: ScoringParams | None = None) -> dict:
    params = params or ScoringParams()
    records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    out_records = []
    totals = {"records": 0, "candidates": 0, "model_hits": 0, "keyword_fallbacks": 0, "flips": 0}

    for rec in records:
        candidates = rec.get("candidates")
        # 只回放三选一评分记录(candidates 为 dict 数组含 score 键;
        # hif_class_options 等的候选是字符串数组,非本模型范围)
        if not isinstance(candidates, list) or not candidates:
            continue
        if not all(isinstance(c, dict) and "score" in c for c in candidates):
            continue
        totals["records"] += 1
        is_drink = "drink" in (rec.get("screen") or "")
        context = DecisionContext(days_remaining=rec.get("day_remaining"), stamina_ratio=None)
        rows = []
        for cand in candidates:
            totals["candidates"] += 1
            card_raw = cand.get("card") or ""
            card = normalize_card_name(card_raw) if card_raw else ""
            keyword_score = cand.get("score") or 0.0
            scorer = score_drink_by_name if is_drink else score_card_by_name
            model = scorer(card, context, params) if card else None
            if model is not None:
                totals["model_hits"] += 1
                decision_score = model.total
                source = "effects"
                detail = [(e.note, round(e.points, 2)) for e in model.breakdown if e.points]
            else:
                totals["keyword_fallbacks"] += 1
                decision_score = keyword_score
                source = "keywords"
                detail = cand.get("breakdown") or []
            rows.append({
                "card": card or card_raw or "卡名未读",
                "normalized": card != card_raw,
                "keyword_score": keyword_score,
                "model_score": round(model.total, 2) if model is not None else None,
                "decision_score": round(decision_score, 2),
                "source": source,
                "detail": detail,
            })
        old_chosen = rec.get("chosen")
        new_best = max(rows, key=lambda r: r["decision_score"])
        new_chosen = rows.index(new_best) + 1
        flipped = old_chosen is not None and new_chosen != old_chosen
        if flipped:
            totals["flips"] += 1
        out_records.append({
            "screen": rec.get("screen"),
            "ts": rec.get("ts"),
            "day_remaining": rec.get("day_remaining"),
            "image": rec.get("image"),
            "action": rec.get("action"),
            "old_chosen": old_chosen,
            "new_chosen": new_chosen,
            "flipped": flipped,
            "candidates": rows,
        })

    return {"summary": totals, "records": out_records}


def main() -> int:
    if len(sys.argv) > 1:
        jsonl_path = Path(sys.argv[1])
    else:
        sessions = sorted(DECISIONS_DIR.glob("session-*.jsonl"))
        if not sessions:
            print("[FATAL] debug/decisions 下无 session-*.jsonl")
            return 1
        jsonl_path = sessions[-1]
    if not jsonl_path.exists():
        print(f"[FATAL] {jsonl_path} 不存在")
        return 1

    result = replay(jsonl_path)
    s = result["summary"]
    print(f"回放: {jsonl_path.name}")
    print(
        f"三选一记录 {s['records']} 条 / 候选 {s['candidates']} 个 | "
        f"模型命中 {s['model_hits']}({s['model_hits'] / s['candidates']:.0%}) "
        f"关键词兜底 {s['keyword_fallbacks']} | 选中翻转 {s['flips']}"
    )
    print("\n-- 翻转案例(人工审:是否为四盲区修正而非噪声)--")
    for rec in result["records"]:
        if not rec["flipped"]:
            continue
        print(f"\n[{rec['ts']}] {rec['screen']} day={rec['day_remaining']} 旧选{rec['old_chosen']} → 新选{rec['new_chosen']}")
        for i, row in enumerate(rec["candidates"], 1):
            mark = "*" if i == rec["new_chosen"] else " "
            model = f"model={row['model_score']}" if row["model_score"] is not None else "model=miss"
            print(f" {mark} 候选{i}: {row['card']} | {model} keyword={row['keyword_score']} [{row['source']}]")
            if row["source"] == "effects":
                print(f"     明细: {row['detail']}")

    out_path = DECISIONS_DIR / f"replay-{jsonl_path.stem.split('-')[-1]}-scoring.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwritten: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
