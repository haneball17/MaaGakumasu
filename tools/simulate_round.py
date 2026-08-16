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
    parser = argparse.ArgumentParser(description="HIF Round 考试模拟器(M4:策略+效果引擎+A/B)")
    parser.add_argument("--preset", default="hif_r1_rinami", choices=sorted(PRESETS), help="内置预设 ID")
    parser.add_argument("--seed", type=int, default=42, help="随机种子(CRN:同批种子同分布)")
    parser.add_argument("--strategy", default="skip", choices=["skip", "first_legal", "greedy", "garakuta_rinami"], help="单局策略")
    parser.add_argument("--set", action="append", default=[], metavar="key=value", help="覆盖字段(点路径,可多次)")
    parser.add_argument("--out", type=Path, default=None, help="trace JSON 输出文件(缺省打印 stdout)")
    parser.add_argument(
        "--ab",
        default=None,
        metavar="A,B",
        help="A/B 模式:逗号分隔策略名(如 garakuta_rinami,greedy);默认预设行恒含 first_legal 基线",
    )
    parser.add_argument("--n", type=int, default=1000, help="A/B 批量局数(默认 1000)")
    parser.add_argument("--combined", action="store_true", help="A/B 優勝组合模式(R1+R2 総合評価,preset 为 R1、自动配 R2 预设)")
    args = parser.parse_args(argv)

    if args.ab:
        from agent.hif.roundsim.ab import run_ab, format_report

        names = [s.strip() for s in args.ab.split(",") if s.strip()]
        if "first_legal" not in names:
            names.append("first_legal")  # 默认基线行恒在
        spec_r1 = build_spec(args.preset, _parse_set(args.set))
        spec_r2 = None
        preset_r2 = ""
        if args.combined:
            preset_r2 = "hif_r2_rinami" if args.preset == "hif_r1_rinami" else "hif_r1_rinami"
            spec_r2 = build_spec(preset_r2)
        stats = run_ab(spec_r1, names, n=args.n, preset_name=args.preset, spec_r2=spec_r2, preset_r2=preset_r2)
        print(format_report(stats, spec_r1, args.preset, combined=spec_r2 is not None))
        return 0

    strategy = None
    if args.strategy != "skip":
        from agent.hif.roundsim.strategies import make_strategy

        strategy = make_strategy(args.strategy)
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
