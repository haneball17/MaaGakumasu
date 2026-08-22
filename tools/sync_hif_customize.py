"""Sync HIF 特別指導(カスタマイズ)菜单: gakumasu-diff join → card_customize.json。

用法(先 clone diff,见 sync_hif_master.py):
    python tools/sync_hif_customize.py

join 链路(roundsim Item C):
    ProduceCard(池内 Plan1/Common,逐 tier: upgradeCount) → produceCardCustomizeIds(菜单)
      → ProduceCardCustomize(340 条: producePoint/customizeCount/produceCardGrowEffectIds)
      → ProduceCardGrowEffect(数值: effectType/value)
    maxCustomizeCount(dump 実証: 無印 = 0 不可指導,+ 档以上 = 1)

产物口径:
- 按卡 + 档位组织,仅落 maxCustomizeCount>0 或菜单非空的档(池内);
- grow effect 落 effect_type 短名 + value + cost_type(引擎消费的最小面)。

对账断言(回归用例 = 実機 observed case interval_customize):
- シュプレヒコール(card_id=p_card-01-act-2_001,注意不是 1_105)無印菜单空且 maxCustomizeCount=0;
- + 档菜单两条,含 p_card_custom-040-g_effect-cost_lesson_buff_reduce-1(40P);
- 该选项 grow effect = CostLessonBuffReduce value 1(集中 cost −1);
- ProduceCardCustomize 340 条全量引用零缺失。
"""

from __future__ import annotations

import sys
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_hif_master import TIER_KEYS, _load_yaml, _diff_commit  # noqa: E402
from sync_hif_effects import _short  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIFF = REPO / ".scrape" / "gakumasu-diff"
OUT = REPO / "assets" / "data" / "hif" / "card_customize.json"

POOL_PLANS = {"ProducePlanType_Plan1", "ProducePlanType_Common"}


def sync(diff_root: Path) -> tuple[dict, dict]:
    print("loading ProduceCardCustomize / ProduceCardGrowEffect ...")
    cc_idx = {r["id"]: r for r in _load_yaml(diff_root / "ProduceCardCustomize.yaml")}
    grow_idx = {r["id"]: r for r in _load_yaml(diff_root / "ProduceCardGrowEffect.yaml")}
    print("loading ProduceCard.yaml ...")
    cards_out = []
    stats = {"tiers": 0, "menu_entries": 0, "missing_ref": []}
    for card in _load_yaml(diff_root / "ProduceCard.yaml"):
        if card.get("planType") not in POOL_PLANS:
            continue
        menu = card.get("produceCardCustomizeIds") or []
        if not menu and not (card.get("maxCustomizeCount") or 0):
            continue
        tier_key = TIER_KEYS.get(card.get("upgradeCount"))
        if tier_key is None:
            continue
        customizes = []
        for cid in menu:
            cc = cc_idx.get(cid)
            if cc is None:
                stats["missing_ref"].append(f"{card['name']}: customize {cid} not found")
                continue
            grows = []
            for gid in cc.get("produceCardGrowEffectIds") or []:
                g = grow_idx.get(gid)
                if g is None:
                    stats["missing_ref"].append(f"{card['name']}: grow effect {gid} not found")
                    continue
                grows.append(
                    {
                        "id": gid,
                        "effect_type": _short(g.get("effectType", "")),
                        "value": g.get("value"),
                        "cost_type": (g.get("costType") or "").replace("ExamCostType_", "") or None,
                    }
                )
            customizes.append(
                {
                    "id": cid,
                    "produce_point": cc.get("producePoint") or 0,
                    "customize_count": cc.get("customizeCount") or 0,
                    "grow_effects": grows,
                }
            )
        cards_out.append(
            {
                "card_id": card["id"],
                "name_jp": card["name"],
                "tier": tier_key,
                "max_customize_count": card.get("maxCustomizeCount") or 0,
                "customizes": customizes,
            }
        )
        stats["tiers"] += 1
        stats["menu_entries"] += len(customizes)

    payload = {
        "schema_version": 1,
        "entity": "hif_card_customize",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pool_note": "特別指導(カスタマイズ)菜单,池内 Plan1/Common 逐档;dump 実証無印 maxCustomizeCount=0(不可指導);Interval 指導上限 2 张(p_setting-8 customizeProduceCardCount)",
        "sources": [
            {
                "source": "vertesan/gakumasu-diff",
                "commit": _diff_commit(diff_root),
                "tables": ["ProduceCard.yaml", "ProduceCardCustomize.yaml", "ProduceCardGrowEffect.yaml"],
            }
        ],
        "cards": cards_out,
    }
    return payload, stats


def run_reconciliation(payload: dict) -> list[str]:
    """对账断言:シュプレヒコール 実機回归用例(observed case interval_customize)。"""
    problems: list[str] = []
    by_tier = {(c["card_id"], c["tier"]): c for c in payload["cards"]}
    base = by_tier.get(("p_card-01-act-2_001", "無印"))
    plus = by_tier.get(("p_card-01-act-2_001", "+"))
    if base is not None and (base["customizes"] or base["max_customize_count"]):
        problems.append(f"シュプレヒコール 無印 可指導? menu={base['customizes']} max={base['max_customize_count']}")
    if plus is None:
        problems.append("シュプレヒコール+ 不在产物")
        return problems
    ids = {c["id"] for c in plus["customizes"]}
    if len(plus["customizes"]) != 2:
        problems.append(f"シュプレヒコール+ 菜单 {len(plus['customizes'])} 条 != 2: {ids}")
    target = next((c for c in plus["customizes"] if c["id"] == "p_card_custom-040-g_effect-cost_lesson_buff_reduce-1"), None)
    if target is None:
        problems.append("シュプレヒコール+ 菜单缺 p_card_custom-040-g_effect-cost_lesson_buff_reduce-1")
    else:
        if target["produce_point"] != 40:
            problems.append(f"40P 选项 producePoint={target['produce_point']}")
        g = target["grow_effects"][0] if target["grow_effects"] else {}
        if g.get("effect_type") != "CostLessonBuffReduce" or g.get("value") != 1:
            problems.append(f"40P 选项 grow effect {g} != CostLessonBuffReduce/1")
    if stats_missing(payload):
        problems.append(f"产物内存在空 grow_effects 选项")
    return problems


def stats_missing(payload: dict) -> int:
    return sum(1 for c in payload["cards"] for cu in c["customizes"] if not cu["grow_effects"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff-path", type=Path, default=DEFAULT_DIFF)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (args.diff_path / "ProduceCard.yaml").exists():
        print(f"[FATAL] {args.diff_path} 下无 ProduceCard.yaml,先 clone vertesan/gakumasu-diff")
        return 1

    payload, stats = sync(args.diff_path)
    print(f"\ncards×tier: {stats['tiers']}(菜单条目 {stats['menu_entries']})")
    if stats["missing_ref"]:
        print(f"[链路断裂引用] {len(stats['missing_ref'])} 条:")
        for m in stats["missing_ref"][:10]:
            print(f"  - {m}")

    problems = run_reconciliation(payload)
    if problems:
        print("\n[对账失败]")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n[对账通过] シュプレヒコール 無印不可指導/+ 菜单两条/40P=CostLessonBuffReduce value1")

    if args.dry_run:
        print("(dry-run,未写盘)")
        return 0
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
