"""HIF 评分模型校准(C1,设计文档第 4 节):模型排序 vs 社区 tier 榜相关性 + 分歧清单。

输入:.scrape/hif_tiers.py 抓的 .scrape/hif_tiers.json(Game8 SS/S/A/圏外)
     + assets/data/hif/skill_card_effects.json(流派过滤池)
方法:榜内卡逐张算模型分(中性局面),Spearman 秩相关(模型分 vs 档位 SS=4…圏外=1);
     分歧样本 = 模型分四分位档与榜档差 ≥2(C2 人工复核输入);
     关键参数比例小网格搜索,输出各组合相关性(调参方向参考,定值人工定)。

用法:python tools/calibrate_scoring.py
"""

from __future__ import annotations

import sys
import json
import unicodedata
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.hif.decisions.scoring import (  # noqa: E402
    ScoringParams,
    DecisionContext,
    score_card_by_name,
)

REPO = Path(__file__).resolve().parents[1]
TIERS_PATH = REPO / ".scrape" / "hif_tiers.json"
REPORT_PATH = REPO / ".scrape" / "calibration-report.json"

TIER_LEVEL = {"SS": 4, "S": 3, "A": 2, "B": 1.5, "C": 1, "圏外": 1}


def _norm(name: str) -> str:
    return unicodedata.normalize("NFKC", name.rstrip("+"))


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman 秩相关(并列取平均秩;无 scipy 依赖)。"""

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        rk = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    var_x = sum((a - mean_x) ** 2 for a in rx)
    var_y = sum((b - mean_y) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return 0.0
    return cov / (var_x * var_y) ** 0.5


def _model_tier(scores: list[float]) -> list[int]:
    """模型分 → 四分位档(4=最高),与榜档同尺度供档差比较。"""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    quart = [0] * len(scores)
    n = len(scores)
    for pos, idx in enumerate(order):
        quart[idx] = min(4, int(pos / n * 4) + 1)
    return quart


def load_samples() -> list[dict]:
    tiers = json.loads(TIERS_PATH.read_text(encoding="utf-8"))
    game8 = {_norm(k): v for k, v in tiers.get("game8_tiers", {}).items()}
    ctx = DecisionContext()
    samples = []
    for name, tier in sorted(game8.items()):
        model = score_card_by_name(name, ctx)
        if model is None:
            continue
        samples.append({
            "card": name,
            "game8_tier": tier,
            "tier_level": TIER_LEVEL.get(tier, 1),
            "model_score": round(model.total, 2),
            "breakdown": [(e.note, round(e.points, 2)) for e in model.breakdown if e.points],
        })
    return samples


def evaluate(samples: list[dict]) -> tuple[float, list[dict]]:
    rho = _spearman([s["model_score"] for s in samples], [s["tier_level"] for s in samples])
    quart = _model_tier([s["model_score"] for s in samples])
    disagreements = []
    for s, q in zip(samples, quart):
        s["model_quartile"] = q
        diff = q - s["tier_level"]
        if abs(diff) >= 2:
            s["tier_diff"] = diff
            disagreements.append(s)
    return rho, disagreements


def grid_search(samples: list[dict]) -> list[dict]:
    """关键参数比例小网格(相关性只看排序,global_scale 无关故不搜)。"""
    axes = {
        "k_buff": [3.0, 5.0, 7.0],
        "w_cycle": [4.0, 8.0, 12.0],
        "w_parameter": [0.5, 1.0, 1.5],
        "cond_factor": [0.6, 0.8, 1.0],
    }
    results = []
    ctx = DecisionContext()
    names = [s["card"] for s in samples]
    levels = [s["tier_level"] for s in samples]
    for k_buff, w_cycle, w_parameter, cond_factor in product(*axes.values()):
        params = ScoringParams(k_buff=k_buff, w_cycle=w_cycle, w_parameter=w_parameter, cond_factor=cond_factor)
        scores = []
        for name in names:
            m = score_card_by_name(name, ctx, params)
            scores.append(m.total if m else 0.0)
        results.append({
            "k_buff": k_buff, "w_cycle": w_cycle, "w_parameter": w_parameter, "cond_factor": cond_factor,
            "spearman": round(_spearman(scores, levels), 4),
        })
    results.sort(key=lambda r: -r["spearman"])
    return results


def main() -> int:
    if not TIERS_PATH.exists():
        print(f"[FATAL] {TIERS_PATH} 不存在,先跑 tools/scrape_hif_tiers.py")
        return 1
    samples = load_samples()
    if len(samples) < 10:
        print(f"[FATAL] 榜∩池样本仅 {len(samples)} 张,不足校准")
        return 1
    rho, disagreements = evaluate(samples)
    print(f"校准样本: {len(samples)} 张(Game8 榜 ∩ 流派过滤池,含圏外)")
    print(f"Spearman 相关性(默认参数): {rho:.4f}")
    print(f"分歧样本(档差≥2): {len(disagreements)} 张(C2 人工复核)")
    for s in disagreements[:12]:
        print(f"  [{s['game8_tier']}→模型Q{s['model_quartile']}] {s['card']} score={s['model_score']} {s['breakdown'][:3]}")

    grid = grid_search(samples)
    print("\n-- 参数网格 Top5(相关性方向参考,定值人工定)--")
    for row in grid[:5]:
        print(f"  rho={row['spearman']:+.4f}  k_buff={row['k_buff']} w_cycle={row['w_cycle']} "
              f"w_parameter={row['w_parameter']} cond_factor={row['cond_factor']}")

    REPORT_PATH.write_text(
        json.dumps({
            "sample_count": len(samples),
            "spearman_default": round(rho, 4),
            "grid_top": grid[:10],
            "grid_bottom": grid[-5:],
            "samples": samples,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nwritten: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
