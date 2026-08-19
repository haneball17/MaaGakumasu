"""Sync HIF P item 效果: gakumasu-diff 关联表 join → pitem_effects.json。

用法(先 clone diff,见 sync_hif_master.py):
    python tools/sync_hif_pitems.py

join 链路(roundsim Item B):
    ProduceItem(范围: originIdolCardId=莉波 hrnm 卡 或 originSupportCardId 非空)
      → produceItemEffectIds → ProduceItemEffect(ExamStatusEnchant 型: effectCount=発動上限, effectTurn=-1 常驻)
      → produceExamStatusEnchantId → ProduceExamStatusEnchant
          → produceExamTriggerId → ProduceExamTrigger(phase=计数间隔, fieldStatus=状态门槛, cardSearch=対象卡)
          → produceExamEffectIds → ProduceExamEffect(発動效果数值)
    ProduceCardSearch.effectGroupIds → EffectGroup(対象卡效果组,如「好調」5 型)

产物口径(R2-3 定案:P item = 确定列表,无随机层):
- 莉波偶像卡 26 件(13 道具 × 無印/+)+ 支援卡 origin 127 件,共 153 件;
- 支援卡不发 P item(SupportCard 无发放字段),origin 关系是道具 ← 卡的归属标记。

对账断言(憧憬数据 vs triggers.py 现硬编码,数据驱动切换的先行校验):
- 憧れ続けた輝き 無印/+: interval 4 / 好調门槛 8(+)6 / effectCount 5;
- 発動效果四条 = 絶好調1T + 使用数+1 + 抽1 + 体力1;
- 対象效果组「好調」examEffectTypes 含 ExamParameterBuff。
"""

from __future__ import annotations

import sys
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_hif_master import _load_yaml, _diff_commit  # noqa: E402
from sync_hif_effects import _index, _short, _enum_names, _exam_effect_entry  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIFF = REPO / ".scrape" / "gakumasu-diff"
OUT = REPO / "assets" / "data" / "hif" / "pitem_effects.json"


def _in_scope(item: dict) -> bool:
    """收集范围:莉波偶像卡 origin(hrnm)或支援卡 origin;其余偶像卡 HIF 模拟对象外。"""
    idol = item.get("originIdolCardId") or ""
    return idol.startswith("i_card-hrnm-") or bool(item.get("originSupportCardId"))


def sync(diff_root: Path) -> tuple[dict, dict]:
    print("loading ProduceItem / ProduceItemEffect ...")
    items = [r for r in _load_yaml(diff_root / "ProduceItem.yaml") if _in_scope(r)]
    pie_idx = _index(_load_yaml(diff_root / "ProduceItemEffect.yaml"))
    print("loading enchant / trigger / exam effect / effect group ...")
    ench_idx = _index(_load_yaml(diff_root / "ProduceExamStatusEnchant.yaml"))
    trig_idx = _index(_load_yaml(diff_root / "ProduceExamTrigger.yaml"))
    exam_idx = _index(_load_yaml(diff_root / "ProduceExamEffect.yaml"))
    search_idx = _index(_load_yaml(diff_root / "ProduceCardSearch.yaml"))
    group_idx = _index(_load_yaml(diff_root / "EffectGroup.yaml"))
    exam_names = _enum_names(diff_root / "ProduceDescriptionExamEffect.yaml")

    items_out = []
    stats = {"origin_idol": 0, "origin_support": 0, "non_enchant": 0, "missing_ref": []}
    for item in sorted(items, key=lambda r: r["id"]):
        effects = []
        for peid in item.get("produceItemEffectIds") or []:
            pie = pie_idx.get(peid)
            if pie is None:
                stats["missing_ref"].append(f"{item['name']}: PIE {peid} not found")
                continue
            if pie.get("effectType") != "ProduceItemEffectType_ExamStatusEnchant":
                # 非 ExamStatusEnchant 型(如直接 ProduceEffect 三围加成):roundsim 不消费,记录占位
                effects.append({"pitem_effect_id": peid, "effect_type": pie.get("effectType"), "note": "non_enchant"})
                stats["non_enchant"] += 1
                continue
            ench = ench_idx.get(pie.get("produceExamStatusEnchantId") or "")
            if ench is None:
                stats["missing_ref"].append(f"{item['name']}: enchant {pie.get('produceExamStatusEnchantId')} not found")
                continue
            trig = trig_idx.get(ench.get("produceExamTriggerId") or "")
            if trig is None:
                stats["missing_ref"].append(f"{item['name']}: trigger {ench.get('produceExamTriggerId')} not found")
                continue
            search = search_idx.get(trig.get("produceCardSearchId") or "")
            groups = []
            for gid in (search or {}).get("effectGroupIds") or []:
                g = group_idx.get(gid)
                if g is not None:
                    groups.append(
                        {
                            "id": gid,
                            "name": g.get("name"),
                            "exam_effect_types": [_short(t) for t in g.get("examEffectTypes") or []],
                        }
                    )
            exam_effects = []
            for eid in ench.get("produceExamEffectIds") or []:
                eff = exam_idx.get(eid)
                if eff is None:
                    stats["missing_ref"].append(f"{item['name']}: exam effect {eid} not found")
                    continue
                exam_effects.append(_exam_effect_entry(eff, exam_names))
            effects.append(
                {
                    "pitem_effect_id": peid,
                    "enchant_id": ench["id"],
                    "effect_count": pie.get("effectCount") or 0,  # 発動上限(-1 → 0 视为无限,官方未见)
                    "effect_turn": pie.get("effectTurn"),  # -1 = 常驻
                    "trigger": {
                        "trigger_id": trig["id"],
                        "phase_types": [_short(t) for t in trig.get("phaseTypes") or []],
                        "phase_values": trig.get("phaseValues") or [],
                        "field_status_types": [_short(t) for t in trig.get("fieldStatusTypes") or []],
                        "field_status_values": trig.get("fieldStatusValues") or [],
                        "card_search_id": trig.get("produceCardSearchId") or "",
                        "card_search_effect_groups": groups,
                    },
                    "exam_effects": exam_effects,
                }
            )
        items_out.append(
            {
                "item_id": item["id"],
                "name": item["name"],
                "rarity": item.get("rarity"),
                "is_upgraded": bool(item.get("isUpgraded")),
                "origin_idol_card_id": item.get("originIdolCardId") or "",
                "origin_support_card_id": item.get("originSupportCardId") or "",
                "effects": effects,
            }
        )
        if item.get("originIdolCardId"):
            stats["origin_idol"] += 1
        else:
            stats["origin_support"] += 1

    payload = {
        "schema_version": 1,
        "entity": "hif_pitem_effects",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pool_note": "范围 = 莉波偶像卡 origin(hrnm,26 件含+版)+ 支援卡 origin(127 件);R2-3 定案:P item 培育过程获得、考试前固定,spec 为确定列表无随机层;支援卡不发道具,originSupportCardId 是归属标记",
        "sources": [
            {
                "source": "vertesan/gakumasu-diff",
                "commit": _diff_commit(diff_root),
                "tables": [
                    "ProduceItem.yaml",
                    "ProduceItemEffect.yaml",
                    "ProduceExamStatusEnchant.yaml",
                    "ProduceExamTrigger.yaml",
                    "ProduceExamEffect.yaml",
                    "ProduceCardSearch.yaml",
                    "EffectGroup.yaml",
                    "ProduceDescriptionExamEffect.yaml",
                ],
            }
        ],
        "items": items_out,
    }
    return payload, stats


def run_reconciliation(payload: dict) -> list[str]:
    """对账断言:件数 + 憧憬数值 vs triggers.py 硬编码(数据驱动切换先行校验)。

    注:+版発動效果只有三条——dump 実証 + 版无 ExamStaminaReduceFix(発動不消耗体力1),
    現硬编码对無印/+ 一律扣体力 1 属既有近似,数据驱动后按各自 exam_effects 派发修正。
    """
    problems: list[str] = []
    by_name = {i["name"]: i for i in payload["items"]}
    idol = [i for i in payload["items"] if i["origin_idol_card_id"]]
    support = [i for i in payload["items"] if i["origin_support_card_id"]]
    if len(idol) != 26:
        problems.append(f"莉波偶像卡 P item {len(idol)} != 26(13 道具 × 無印/+)")
    if len(support) != 127:
        problems.append(f"支援卡 origin P item {len(support)} != 127")

    for name, threshold, expect_types in (
        ("憧れ続けた輝き", 8, ["ExamCardDraw", "ExamParameterBuffMultiplePerTurn", "ExamPlayableValueAdd", "ExamStaminaReduceFix"]),
        ("憧れ続けた輝き+", 6, ["ExamCardDraw", "ExamParameterBuffMultiplePerTurn", "ExamPlayableValueAdd"]),
    ):
        item = by_name.get(name)
        ench = next((e for e in (item or {}).get("effects", []) if "enchant_id" in e), None)
        if ench is None:
            problems.append(f"{name} 不在产物或无 enchant 效果")
            continue
        trig = ench["trigger"]
        if trig["phase_types"] != ["ExamPlayCountInterval"] or trig["phase_values"] != [4]:
            problems.append(f"{name} phase {trig['phase_types']}/{trig['phase_values']} != ExamPlayCountInterval/[4]")
        if trig["field_status_types"] != ["ParameterBuffUp"] or trig["field_status_values"] != [threshold]:
            problems.append(f"{name} 门槛 {trig['field_status_types']}/{trig['field_status_values']} != ParameterBuffUp/[{threshold}]")
        if ench["effect_count"] != 5 or ench["effect_turn"] != -1:
            problems.append(f"{name} effectCount/turn {ench['effect_count']}/{ench['effect_turn']} != 5/-1")
        groups = trig["card_search_effect_groups"]
        if not groups or "ExamParameterBuff" not in groups[0]["exam_effect_types"]:
            problems.append(f"{name} 対象効果組缺 ExamParameterBuff: {groups}")
        etypes = sorted(_short(e["effect_type"] or "") for e in ench["exam_effects"])
        if etypes != expect_types:
            problems.append(f"{name} 発動效果不符: {etypes} != {expect_types}")

    if any(i for i in payload["items"] if not i["effects"]):
        problems.append("存在零效果件(链路断裂)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff-path", type=Path, default=DEFAULT_DIFF)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (args.diff_path / "ProduceItem.yaml").exists():
        print(f"[FATAL] {args.diff_path} 下无 ProduceItem.yaml,先 clone vertesan/gakumasu-diff")
        return 1

    payload, stats = sync(args.diff_path)
    print(f"\nitems: {len(payload['items'])}(莉波偶像卡 {stats['origin_idol']} + 支援卡 origin {stats['origin_support']})")
    print(f"非 enchant 型效果条目: {stats['non_enchant']}")
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
    print("\n[对账通过] 153 件 / 憧憬 無印·+ 数值与 triggers.py 硬编码一致(interval4·门槛8/6·5回·四效果)")

    if args.dry_run:
        print("(dry-run,未写盘)")
        return 0
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
