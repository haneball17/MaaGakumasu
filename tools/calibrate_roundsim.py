"""実機回放校准报告(M5,roundsim-design.md §9 第 3 层·全局口径)。

用法:
    python tools/calibrate_roundsim.py [--n 200] [--strategy garakuta_rinami] [--manual 録局.json]

产出(stdout markdown):
- 実機落点分位:同卡组 N 局分布 vs observed case 総合評価(4,756,391);
- 偏差归因:落点在分布外的系统性偏低/偏高 → §11 假设条目候选(A9 三围口径/A10 构筑近似/
  好印象等未建模乘区),不静默拟合(ADR-0001);
- 数据缺口清单(adapter 返回,含 TODO 実機補録项);
- 手工録局(可选 --manual):逐回合口径漂移表。
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.hif.roundsim.ab import ASSUMPTIONS  # noqa: E402
from agent.hif.roundsim.spec import PRESETS  # noqa: E402
from agent.hif.roundsim.runner import run_exam  # noqa: E402
from agent.hif.roundsim.adapter import (  # noqa: E402
    ManualGameRecord,
    observed_final_scores,
    spec_from_observed_case,
    validate_trace_against_manual,
)
from agent.hif.roundsim.strategies import make_strategy  # noqa: E402

# 落点越界时的候选归因(§11 条目;人工审阅入口,不是自动拟合)
_OUT_OF_RANGE_ATTRIBUTIONS = {
    "low": [
        "A9 三围输有效参数口径:预设为准备期中段快照(Vo1116/Da2920/Vi2175),実機 R1 入场值更高(3807% 局 Vi=3807)→ 系统性放大参数倍率",
        "A10 构筑重构近似:15 张池内补足卡与実機 20 张不同 → 关键卡(好印象/得分上升系)缺位压低分布",
        "未建模乘区:好印象(S5)/得分上升量/S6 分段表与親愛度(H7)不在 MVP 支持面",
    ],
    "high": ["A1 対手 uniform 区间或与実機実分布不符", "构筑近似含超実機强度卡"],
}


def percentile_of(value: float, sorted_scores: list[int]) -> float:
    """実機值在模拟分布中的分位(0-100)。"""
    n = len(sorted_scores)
    below = sum(1 for s in sorted_scores if s <= value)
    return round(100.0 * below / n, 2) if n else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="roundsim 実機回放校准(全局口径)")
    parser.add_argument("--n", type=int, default=200, help="模拟局数")
    parser.add_argument("--strategy", default="garakuta_rinami", help="被校准策略")
    parser.add_argument("--manual", type=Path, default=None, help="手工録局 JSON(逐回合口径,可选)")
    args = parser.parse_args(argv)

    spec_r1, info_r1 = spec_from_observed_case(round_tag="r1")
    spec_r2, info_r2 = spec_from_observed_case(round_tag="r2")
    finals = observed_final_scores()
    strategy_name = args.strategy

    lines: list[str] = ["# roundsim 実機回放校准报告(全局口径)", ""]
    lines.append(f"- 策略:{strategy_name}  N={args.n}(CRN 同批种子)")
    lines.append(f"- 対象:observed case rinami_garakuta_road_20260709")
    lines.append("")

    # R1 单段分布(R1 実機分未録 → 分布表仍产出,落点留 TODO)
    r1_scores = sorted(
        run_exam(spec_r1, seed=s, strategy=make_strategy(strategy_name), preset_name="observed_r1").final.total_score
        for s in range(args.n)
    )
    lines.append("## R1 单段分布")
    lines.append("")
    lines.append(f"- P10/P50/P90 = {r1_scores[args.n // 10]}/{r1_scores[args.n // 2]}/{r1_scores[int(args.n * 0.9)]}")
    if finals["r1_final"] is None:
        lines.append("- 実機 R1 最终得分:**TODO 待実機補録**(実機配合项 1:R1 順位画面截图/数字)")
    else:
        lines.append(f"- 実機 R1 落点分位:{percentile_of(finals['r1_final'], r1_scores)}%")

    # R2 单段 + 総合(総合評価実機值在 case 内)
    r2_scores = sorted(
        run_exam(spec_r2, seed=s, strategy=make_strategy(strategy_name), preset_name="observed_r2").final.total_score
        for s in range(args.n)
    )
    combined_scores = sorted(a + b for a, b in zip(r1_scores, r2_scores))
    lines.append("")
    lines.append("## R2 单段 / 総合評価分布")
    lines.append("")
    lines.append(f"- R2 P10/P50/P90 = {r2_scores[args.n // 10]}/{r2_scores[args.n // 2]}/{r2_scores[int(args.n * 0.9)]}")
    lines.append(f"- 総合(R1+R2,同 seed 配对)P10/P50/P90 = {combined_scores[args.n // 10]}/{combined_scores[args.n // 2]}/{combined_scores[int(args.n * 0.9)]}")
    combined_final = finals["combined_final"]
    if combined_final is not None:
        pct = percentile_of(combined_final, combined_scores)
        lines.append(f"- **実機総合評価落点分位:{pct}%**(実機 {combined_final:,} vs 模拟 P100 {combined_scores[-1]:,})")
        if pct >= 99.5:
            lines.append("")
            lines.append("### 偏差归因(実機显著高于模拟,候选假设条目)")
            lines.append("")
            lines.extend(f"- {a}" for a in _OUT_OF_RANGE_ATTRIBUTIONS["low"])
        elif pct <= 0.5:
            lines.append("")
            lines.extend(f"- {a}" for a in _OUT_OF_RANGE_ATTRIBUTIONS["high"])

    lines.append("")
    lines.append("## 数据缺口(adapter 声明,TODO 待実機補録)")
    lines.append("")
    lines.extend(f"- [R1] {g}" for g in info_r1["gaps"])
    lines.extend(f"- [R2] {g}" for g in info_r2["gaps"])
    lines.append("- 実機配合项:① R1 最終得分 ≥1 局;② R2 初始状态截图(体力/好調/集中/饮料数);③ Round 中卡组计数(验 A8,可选)")
    lines.append("")
    lines.append("## 假设清单(§11)")
    lines.append("")
    lines.extend(f"- {a}" for a in ASSUMPTIONS)

    if args.manual and args.manual.exists():
        record = ManualGameRecord.model_validate(json.loads(args.manual.read_text(encoding="utf-8")))
        spec = spec_r1 if record.round_tag == "r1" else spec_r2
        trace = run_exam(spec, seed=record.seed or 0, strategy=make_strategy(strategy_name))
        drifts = validate_trace_against_manual(trace, record)
        lines.append("")
        lines.append("## 手工録局逐回合漂移(逐回合口径)")
        lines.append("")
        if not drifts:
            lines.append("- 全部记录回合一致")
        else:
            lines.append("```json")
            lines.append(json.dumps(drifts, ensure_ascii=False, indent=1))
            lines.append("```")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
