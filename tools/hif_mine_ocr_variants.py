"""HIF OCR 变体挖掘:离线分析决策日志的卡名/饮料名未命中样本,产出候选变体表。

用法:
    python tools/hif_mine_ocr_variants.py [session-20260815.jsonl]

产出三类(人工确认后合入):
1. 变体建议——未命中文本与词典最近邻距离 ≤4,可作 OCR_VARIANTS 候选
2. 池外卡——距离远,判定为 121 白名单外的真实卡(HIF 池扩充候选,sync 白名单加名)
3. 噪音——过短/纯符号,忽略

不依赖截图重读(实机 OCR 重扫留实机阶段);数据源为决策记录里已存的 OCR 文本。
"""

from __future__ import annotations

import sys
import json
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECISIONS_DIR = REPO / "debug" / "decisions"


def _load_card_dict():
    """按文件加载 card_dict(避免 agent 包 __init__ 依赖链)。"""
    spec = importlib.util.spec_from_file_location(
        "hif_card_dict", REPO / "agent" / "hif" / "adapters" / "card_dict.py"
    )
    module = importlib.util.module_from_spec(spec)
    # card_dict 依赖 agent.hif.decisions.hand_meta → 注入仓库根 sys.path
    sys.path.insert(0, str(REPO))
    try:
        spec.loader.exec_module(module)
    finally:
        pass
    return module


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _is_noise(text: str) -> bool:
    if not text or len(text.strip()) <= 1:
        return True
    return not any(
        "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" or ch.isalpha() or ch.isdigit()
        for ch in text
    )


def main() -> int:
    session = sys.argv[1] if len(sys.argv) > 1 else None
    if session:
        jsonl = DECISIONS_DIR / session
    else:
        files = sorted(DECISIONS_DIR.glob("session-*.jsonl"))
        if not files:
            print("无 session-*.jsonl")
            return 1
        jsonl = files[-1]

    card_dict = _load_card_dict()
    names = set(card_dict.build_card_name_dict())
    drinks = json.loads((REPO / "assets" / "data" / "hif" / "drinks.json").read_text(encoding="utf-8"))
    drink_names = {d["name_jp"] for d in drinks.get("drinks", [])}

    records = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").strip().splitlines() if l.strip()]
    variants: dict[str, list[str]] = {}
    outside: dict[str, list[str]] = {}
    checked = 0

    for rec in records:
        if rec.get("ghost"):
            continue
        for cand in rec.get("candidates") or []:
            if not (isinstance(cand, dict) and "score" in cand):
                continue
            text = cand.get("card") or ""
            if not text or text == "?" or text in names or text in drink_names:
                continue
            checked += 1
            where = f"{rec.get('ts')} {rec.get('screen')}"
            norm = card_dict.normalize_card_name(text)
            if norm in names or norm in drink_names or norm.rstrip("+") in names:
                variants.setdefault(text, []).append(f"{where}→{norm}")
                continue
            if _is_noise(text):
                continue
            nearest = min((( _edit_distance(text, n), n) for n in names), default=(99, ""))
            if nearest[0] <= 4:
                variants.setdefault(text, []).append(f"{where}→建议:{nearest[1]}(距离{nearest[0]},待人工确认)")
            else:
                outside.setdefault(text, []).append(where)

    print(f"# OCR 变体挖掘 {jsonl.name}(卡名非空且未直接命中: {checked} 个候选)\n")
    print("## 变体建议(人工确认后合入 card_dict.OCR_VARIANTS)")
    for text, hits in sorted(variants.items()):
        print(f"- {text!r}: {hits[0]}{' …' if len(hits) > 1 else ''}")
    print("\n## 池外卡(121 白名单外,HIF 池扩充候选 → sync 白名单加名)")
    for text, hits in sorted(outside.items()):
        print(f"- {text!r}: 出现 {len(hits)} 次({hits[0]} 等)")
    if not variants and not outside:
        print("(全部命中,无候选)")

    out = DECISIONS_DIR / jsonl.name.replace(".jsonl", "-variants.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
