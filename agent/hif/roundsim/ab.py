"""A/B 考试平台(runsim-design.md §7)。

- CRN(共同随机数):对比策略跑同一批种子(同批洗牌/流行/対手分;対手抽样独立流,
  不受策略动作的 rng 消耗差异影响),得分差异只反映策略差异。
- 批量 rollout:默认 N=1000;报告得分分布(均值/P50/P90 + bootstrap 置信区间)、
  勝率/顺位分布。
- 優勝组合模式:同批种子跑 R1 + R2 两段 → 総合評価 = R1(第 1 位時 ×1.2,V1 假设)
  + R2,vs 双対手合计 → 勝率。
- 报告:stdout 表格 + markdown(对齐 hif_replay_report.py 风格);附假设清单、
  未建模 tag 计数、默认预设行恒在。

bootstrap:同批种子重采样(percentile 法,B=2000,95% CI);rng 注入式(seed 固定)。
"""

from __future__ import annotations

import random
from dataclasses import field, dataclass

from agent.hif.roundsim import engine
from agent.hif.roundsim.spec import PRESETS, ScenarioSpec
from agent.hif.roundsim.runner import run_exam
from agent.hif.roundsim.strategies import make_strategy

BOOTSTRAP_B = 2000
BOOTSTRAP_SEED = 20260816


@dataclass(slots=True)
class RolloutStat:
    """单策略批量 rollout 统计。"""

    strategy: str
    preset: str
    n: int = 0
    scores: list[int] = field(default_factory=list)
    ranks: list[int] = field(default_factory=list)
    r1_first: list[bool] = field(default_factory=list)  # R1 第 1 位(组合模式)

    def summary(self, bootstrap: bool = True) -> dict:
        """统计汇总;bootstrap 对 (score, rank) 成对重采样,勝率 CI 与得分 CI 同批。"""
        import statistics

        n = len(self.scores)
        scores = sorted(self.scores)
        mean = statistics.fmean(scores) if scores else 0.0
        p50 = scores[n // 2] if n else 0
        p90 = scores[min(n - 1, int(n * 0.9))] if n else 0
        win = sum(1 for r in self.ranks if r == 1)
        out = {
            "strategy": self.strategy,
            "preset": self.preset,
            "n": n,
            "mean": round(mean, 1),
            "p50": p50,
            "p90": p90,
            "win_rate": round(win / n, 4) if n else 0.0,
        }
        if bootstrap and n >= 30:
            rng = random.Random(BOOTSTRAP_SEED)
            means: list[float] = []
            p50s: list[int] = []
            wins: list[float] = []
            for _ in range(BOOTSTRAP_B):
                idx = [rng.randrange(n) for _ in range(n)]
                sample = sorted(self.scores[i] for i in idx)
                means.append(statistics.fmean(sample))
                p50s.append(sample[n // 2])
                wins.append(sum(1 for i in idx if self.ranks[i] == 1) / n)
            means.sort()
            p50s.sort()
            wins.sort()
            out["mean_ci95"] = (round(means[int(BOOTSTRAP_B * 0.025)], 1), round(means[int(BOOTSTRAP_B * 0.975)], 1))
            out["p50_ci95"] = (p50s[int(BOOTSTRAP_B * 0.025)], p50s[int(BOOTSTRAP_B * 0.975)])
            out["win_ci95"] = (round(wins[int(BOOTSTRAP_B * 0.025)], 4), round(wins[int(BOOTSTRAP_B * 0.975)], 4))
        return out


def run_ab(
    spec: ScenarioSpec,
    strategy_names: list[str],
    n: int = 1000,
    preset_name: str = "",
    spec_r2: ScenarioSpec | None = None,
    preset_r2: str = "",
    bootstrap: bool = True,
) -> list[RolloutStat]:
    """A/B 对比:每策略同批种子(seed 0..n-1)各跑 n 局;组合模式传 spec_r2。

    组合模式(優勝判定,§3.4):総合評価 = R1(第1位×1.2)+ R2 vs 双対手
    (対手 R1+R2 合计,対手 R1 第1位同样 ×1.2)。单段模式只报 R1/R2 自身分布。
    """
    stats = {name: RolloutStat(strategy=name, preset=preset_name) for name in strategy_names}
    for seed in range(n):
        for name in strategy_names:
            strategy = make_strategy(name)
            r1 = run_exam(spec, seed=seed, strategy=strategy, preset_name=preset_name)
            stat = stats[name]
            if spec_r2 is None:
                stat.scores.append(r1.final.total_score)
                stat.ranks.append(r1.final.rank)
                continue
            strategy2 = make_strategy(name)
            r2 = run_exam(spec_r2, seed=seed, strategy=strategy2, preset_name=preset_r2 or preset_name)
            stat.r1_first.append(r1.final.rank == 1)
            total, opp_totals = _combined_total(r1, r2)
            rank = 1 + sum(1 for t in opp_totals if t > total)
            stat.scores.append(total)
            stat.ranks.append(rank)
    for name, stat in stats.items():
        stat.n = len(stat.scores)
    return list(stats.values())


def _combined_total(r1, r2) -> tuple[int, list[int]]:
    """総合評価:R1 第 1 位者 ×1.2(V1),玩家总分 = adjR1 + R2;対手合计同理。"""
    r1_scores = [r1.final.total_score] + [o.score for o in r1.final.opponents]
    first = r1_scores.index(max(r1_scores))  # 并列时首位(保守口径,注明)
    adj_r1 = [round(s * 1.2) if i == first else s for i, s in enumerate(r1_scores)]
    total = adj_r1[0] + r2.final.total_score
    opp_totals = []
    for i, opp in enumerate(r1.final.opponents, start=1):
        r2_opp = next((o for o in r2.final.opponents if o.name == opp.name), None)
        opp_r2 = r2_opp.score if r2_opp else 0
        opp_totals.append(adj_r1[i] + opp_r2)
    return total, opp_totals


# 假设清单(§11 原文;随报告输出,报告读者须能看见当前翻转状态)
ASSUMPTIONS = [
    "A1 対手分 uniform(min,max) 每局独立抽样",
    "A2 R2 局内初始状态清零(好調/集中/体力→interval 実機值)",
    "A3 P 饮料为 produce 级资源跨 Round 持有",
    "A4 首回合流行权重自定(缺省按審査基準比率)",
    "A5 skip 回合得分 = 0",
    "A6 ×1.2 仅 R1 第 1 位(V1)",
    "A7 △/✕无减衰(U3)",
    "A8 lesson_once 用后 Lost 不回流(V2)",
    "A9 三围输有效参数口径(U2 成分分解不做)",
    "A10 莉波预设 20 张构筑为重构近似(実機逐卡清单未记录,核心五卡実機证据+池内补足)",
]


def format_report(stats: list[RolloutStat], spec: ScenarioSpec, preset_name: str, combined: bool) -> str:
    """markdown 报告(stdout 表格对齐 hif_replay_report.py 风格)。"""
    lines: list[str] = []
    title = "HIF Round 模拟器 A/B 报告"
    if combined:
        title += "(優勝组合模式:R1+R2)"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 预设:{preset_name}(默认预设行恒在,可对比基线)")
    lines.append(f"- 対手:{'; '.join(f'{o.name} {o.score_min}-{o.score_max}' for o in spec.opponent)}")
    lines.append(f"- 模式:{'R1+R2 组合(総合評価)' if combined else '单段'}")
    lines.append("")
    lines.append("| 策略 | N | 均值 | P50 | P90 | 勝率 | mean 95%CI | win 95%CI |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for stat in stats:
        s = stat.summary()
        ci = s.get("mean_ci95")
        wci = s.get("win_ci95")
        lines.append(
            f"| {s['strategy']} | {s['n']} | {s['mean']} | {s['p50']} | {s['p90']} | {s['win_rate']:.1%} "
            f"| {f'{ci[0]}~{ci[1]}' if ci else '-'} | {f'{wci[0]:.1%}~{wci[1]:.1%}' if wci else '-'} |"
        )
    lines.append("")
    lines.append("## 假设清单(可翻转,ADR-0001)")
    lines.append("")
    lines.extend(f"- {a}" for a in ASSUMPTIONS)
    unmodeled = engine.inventory_unmodeled_tags(spec.scenario.deck)
    lines.append("")
    lines.append(f"## 未建模 tag 计数(卡组预检外溢:{unmodeled or '无'})")
    return "\n".join(lines)
