"""Sync HIF master 数据库: vertesan/gakumasu-diff YAML → skill_cards_master.json + drinks.json。

用法:
    git clone --depth 1 https://github.com/vertesan/gakumasu-diff.git .scrape/gakumasu-diff
    python tools/sync_hif_master.py

合并策略(grill 定案 2026-08-15):
- 卡表: 以现有 121 卡 name 白名单为 HIF 池过滤,diff 同名 upgradeCount 0-3 合并为
  tiers{無印/+/++/+++}; wiki 特有字段(is_lesson_once/note_raw)从旧库继承;
  effect_raw 由 produceDescriptions 碎片按序拼接(深度数值解析待关联表 join,另立项)
- 饮料: 旧 seesaawiki 结构化 effects 保留,diff 补 id/rarity/planType 等权威字段
  并合入新增饮料(效果深解析待 ProduceDrinkEffect 关联链)
- 旧库有 diff 无的卡(命名差异)原样保留并标 wiki_only
"""

from __future__ import annotations

import sys
import json
import time
import argparse
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIFF = REPO / ".scrape" / "gakumasu-diff"
MASTER_OUT = REPO / "assets" / "data" / "hif" / "skill_cards_master.json"
DRINKS_OUT = REPO / "assets" / "data" / "hif" / "drinks.json"

# upgradeCount → master tiers 键(与 hand_meta._TIER_KEYS 一致)
TIER_KEYS = {0: "無印", 1: "+", 2: "++", 3: "+++"}


def _load_yaml(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def _diff_commit(diff_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(diff_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _effect_text(card: dict) -> str:
    """produceDescriptions 碎片按序拼接为效果参考文本(深度数值解析待关联表 join)。剥 HTML 标签。"""
    import re

    parts = []
    for desc in card.get("produceDescriptions") or []:
        text = (desc.get("text") or "").strip()
        if text:
            parts.append(text)
    return re.sub(r"<[^>]+>", "", " ".join(parts))


def sync_cards(diff_root: Path, old_master: dict) -> dict:
    cards = _load_yaml(diff_root / "ProduceCard.yaml")
    by_name: dict[str, list[dict]] = {}
    for card in cards:
        by_name.setdefault(card["name"], []).append(card)

    old_cards = {c["name_jp"]: c for c in old_master.get("cards", [])}
    out_cards: list[dict] = []
    wiki_only: list[str] = []

    for name, old in old_cards.items():
        variants = by_name.get(name)
        if not variants:
            wiki_only.append(name)
            out_cards.append(old)
            continue
        tiers: dict[str, dict] = {}
        diff_ids: dict[str, str] = {}
        sample = None
        for variant in sorted(variants, key=lambda c: c["upgradeCount"]):
            key = TIER_KEYS.get(variant["upgradeCount"])
            if key is None:
                continue
            old_tier = (old.get("tiers") or {}).get(key, {})
            tiers[key] = {
                # stamina 取 diff 权威数值;focus/effect_raw 继承 wiki(更完整,diff 深解析待关联表 join)
                "stamina_cost": variant.get("stamina"),
                "focus_cost": old_tier.get("focus_cost"),
                "effect_raw": old_tier.get("effect_raw") or _effect_text(variant),
                "effect_raw_diff": _effect_text(variant),
            }
            diff_ids[key] = variant["id"]
            if sample is None:
                sample = variant
        merged = {
            "wiki_id": old.get("wiki_id"),
            "name_jp": name,
            "is_lesson_once": old.get("is_lesson_once", False),
            "note_raw": old.get("note_raw", ""),
            "rarity": sample.get("rarity"),
            "category": sample.get("category"),
            "plan_type": sample.get("planType"),
            "diff_ids": diff_ids,
            "tiers": tiers,
        }
        out_cards.append(merged)

    payload = {
        "schema_version": 3,
        "entity": "skill_cards_master",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hif_pool_note": "以旧 master 121 卡白名单过滤 diff 全量(実機实证 HIF 池);后续按実機观察扩充",
        "sources": [
            {
                "source": "vertesan/gakumasu-diff",
                "commit": _diff_commit(diff_root),
                "tables": ["ProduceCard.yaml"],
            },
            *old_master.get("sources", []),
        ],
        "cards": out_cards,
    }
    return payload | {"_wiki_only": wiki_only}


def sync_drinks(diff_root: Path, old_drinks: dict) -> dict:
    diff_drinks = _load_yaml(diff_root / "ProduceDrink.yaml")
    old_by_name = {d["name_jp"]: d for d in old_drinks.get("drinks", [])}
    out: list[dict] = []
    added: list[str] = []
    for drink in diff_drinks:
        name = drink["name"]
        old = old_by_name.get(name)
        entry = {
            "drink_id": drink["id"],
            "name_jp": name,
            "rarity": drink.get("rarity"),
            "plan": drink.get("planType"),
            "unlock_plv": drink.get("unlockProducerLevel"),
            "origin_support_card_id": drink.get("originSupportCardId"),
        }
        if old:
            entry |= {
                "name_zh": old.get("name_zh"),
                "wiki_id": old.get("wiki_id"),
                "cost": old.get("cost"),
                "effects": old.get("effects", []),
                "raw_text": old.get("raw_text"),
            }
        else:
            added.append(name)
            entry |= {"name_zh": None, "wiki_id": None, "cost": None, "effects": [], "raw_text": None,
                      "unmatched": "diff 新增,效果待关联表解析"}
        entry["sources"] = [{"source": "vertesan/gakumasu-diff", "commit": _diff_commit(diff_root)}] + (
            old.get("sources", []) if old else []
        )
        out.append(entry)

    return {
        "schema_version": 2,
        "entity": "p_drinks",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sources": [
            {"source": "vertesan/gakumasu-diff", "commit": _diff_commit(diff_root), "tables": ["ProduceDrink.yaml"]},
            *old_drinks.get("sources", []),
        ],
        "drinks": out,
        "_added": added,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff-path", type=Path, default=DEFAULT_DIFF)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (args.diff_path / "ProduceCard.yaml").exists():
        print(f"[FATAL] {args.diff_path} 下无 ProduceCard.yaml,先 clone vertesan/gakumasu-diff")
        return 1

    old_master = json.loads(MASTER_OUT.read_text(encoding="utf-8"))
    old_drinks = json.loads(DRINKS_OUT.read_text(encoding="utf-8"))

    master = sync_cards(args.diff_path, old_master)
    wiki_only = master.pop("_wiki_only")
    drinks = sync_drinks(args.diff_path, old_drinks)
    added = drinks.pop("_added")

    # 回归断言:旧库卡全在,tiers 档位结构完整(hand_meta 消费兼容)
    old_names = {c["name_jp"] for c in old_master.get("cards", [])}
    new_names = {c["name_jp"] for c in master["cards"]}
    assert old_names <= new_names, f"旧卡丢失: {old_names - new_names}"
    assert all("tiers" in c and c["tiers"] for c in master["cards"]), "存在无 tiers 的卡"
    assert len(drinks["drinks"]) >= len(old_drinks.get("drinks", [])), "饮料数量回退"

    print(f"cards: {len(master['cards'])} 张(wiki_only {len(wiki_only)}: {wiki_only})")
    print(f"drinks: {len(drinks['drinks'])} 项(新增 {added})")
    if args.dry_run:
        print("(dry-run,未写盘)")
        return 0

    MASTER_OUT.write_text(json.dumps(master, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DRINKS_OUT.write_text(json.dumps(drinks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written: {MASTER_OUT}")
    print(f"written: {DRINKS_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
