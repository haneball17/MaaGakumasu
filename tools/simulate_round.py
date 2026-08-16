"""HIF Round 模拟器 CLI(roundsim-design.md §4.3)。

用法:
    python tools/simulate_round.py --preset hif_r1_rinami --seed 42
    python tools/simulate_round.py --preset hif_r1_rinami --set scenario.initial.stamina=20
    python tools/simulate_round.py --preset hif_r2_rinami --out debug/roundsim/trace-r2.json

输出:trace JSON(stdout 或 --out 文件)。M1 为 skip-only;A/B 批量报告在 M4 接入。
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.hif.roundsim import PRESETS, run_exam, build_spec  # noqa: E402


def _parse_set(tokens: list[str]) -> dict:
    """--set key=value 列表 → 嵌套 override dict(点路径);值尝试 JSON 解析,失败退字符串。"""
    override: dict = {}
    for token in tokens or []:
        key, _, raw = token.partition("=")
        node = override
        parts = key.strip().split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        try:
            node[parts[-1]] = json.loads(raw)
        except json.JSONDecodeError:
            node[parts[-1]] = raw
    return override


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HIF Round 考试模拟器(M2:效果引擎+S1 得分)")
    parser.add_argument("--preset", default="hif_r1_rinami", choices=sorted(PRESETS), help="内置预设 ID")
    parser.add_argument("--seed", type=int, default=42, help="随机种子(CRN:同批种子同分布)")
    parser.add_argument("--strategy", default="skip", choices=["skip", "first_legal"], help="策略(M4 接贪心/GarakutaRinami)")
    parser.add_argument("--set", action="append", default=[], metavar="key=value", help="覆盖字段(点路径,可多次)")
    parser.add_argument("--out", type=Path, default=None, help="trace JSON 输出文件(缺省打印 stdout)")
    args = parser.parse_args(argv)

    strategy = None
    if args.strategy == "first_legal":
        from agent.hif.roundsim.runner import FirstLegalStrategy

        strategy = FirstLegalStrategy()
    spec = build_spec(args.preset, _parse_set(args.set))
    doc = run_exam(spec, seed=args.seed, strategy=strategy, preset_name=args.preset)
    payload = doc.model_dump_json(indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(f"trace 已写入 {args.out}")
    else:
        print(payload)
    # 摘要行(stderr 不污染管道)
    print(
        f"[summary] preset={args.preset} seed={args.seed} strategy={args.strategy} turns={len(doc.turns)} "
        f"score={doc.final.total_score} rank={doc.final.rank} reshuffles={doc.final.reshuffle_count}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
