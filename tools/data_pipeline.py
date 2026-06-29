import argparse
import hashlib
import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "assets" / "data"
CACHE_DIR = PROJECT_ROOT / ".cache" / "gakumas-data"

IDOLS_MASTER = DATA_DIR / "idols_master.json"
SUPPORT_MASTER = DATA_DIR / "support_cards_master.json"
SKILL_MASTER = DATA_DIR / "skill_cards_master.json"
P_ITEMS_MASTER = DATA_DIR / "p_items_master.json"
ENTITIES_META = DATA_DIR / "entities_meta.json"

IDOLS_COMPACT = DATA_DIR / "idols_cards.json"
SUPPORT_COMPACT = DATA_DIR / "support_cards.json"
SKILL_COMPACT = DATA_DIR / "skill_cards_compact.json"
DECISION_COMPACT = DATA_DIR / "produce_decision_data.json"
IDOLS_COMPACT_PREVIEW = CACHE_DIR / "idols_cards.generated.json"
SUPPORT_COMPACT_PREVIEW = CACHE_DIR / "support_cards.generated.json"

SUPPORT_TRANSLATION_URL = (
    "https://raw.githubusercontent.com/chinosk6/GakumasTranslationData/main/"
    "local-files/masterTrans/SupportCard.json"
)
IDOL_CARDS_URL = "https://seesaawiki.jp/gakumasu/d/%a5%d7%a5%ed%a5%c7%a5%e5%a1%bc%a5%b9%a5%a2%a5%a4%a5%c9%a5%eb%b0%ec%cd%f7"

DEFAULT_HEADERS = {
    "User-Agent": "MaaGakumasu/1.0 (+https://github.com/SuperWaterGod/MaaGakumasu)"
}

IDOL_TRANSLATIONS = {
    "雨夜燕": "雨夜燕",
    "藤田ことね": "藤田琴音",
    "葛城リーリヤ": "葛城莉莉娅",
    "花海咲季": "花海咲季",
    "花海佑芽": "花海佑芽",
    "紫雲清夏": "紫云清夏",
    "篠澤広": "筱泽广",
    "秦谷美鈴": "秦谷美铃",
    "有村麻央": "有村麻央",
    "月村手毬": "月村手毬",
    "十王星南": "十王星南",
    "倉本千奈": "仓本千奈",
    "姫崎莉波": "姬崎莉波",
}

EFFECT_TRANSLATIONS = {
    "ｷロジックやる気": "理性·干劲",
    "ｶロジック好印象": "理性·好印象",
    "ｻロジック好印象": "理性·好印象",
    "ｱセンス好調": "感性·好调",
    "ｼセンス好調": "感性·好调",
    "ｲセンス集中": "感性·集中",
    "ｻアノマリー強気": "非凡·强气",
    "ｼアノマリー強気": "非凡·强气",
    "ｼアノマリー全力": "非凡·全力",
    "ｽアノマリー温存": "非凡·温存",
}

IDOL_PREFERENCES = {
    "雨夜燕": {"first": "Da", "second": "Vo"},
    "藤田琴音": {"first": "Da", "second": "Vi"},
    "葛城莉莉娅": {"first": "Vi", "second": "Da"},
    "花海咲季": {"first": "Vi", "second": "Da"},
    "花海佑芽": {"first": "Da", "second": "Vo"},
    "紫云清夏": {"first": "Da", "second": "Vi"},
    "筱泽广": {"first": "Vo", "second": "Da"},
    "秦谷美铃": {"first": "Vo", "second": "Vi"},
    "有村麻央": {"first": "Vo", "second": "Vi"},
    "月村手毬": {"first": "Vo", "second": "Da"},
    "十王星南": {"first": "Vi", "second": "Vo"},
    "仓本千奈": {"first": "Da", "second": "Vi"},
    "姬崎莉波": {"first": "Vi", "second": "Da"},
}


@dataclass
class SourceSnapshot:
    source: str
    url: str
    fetched_at: str
    fingerprint: str
    item_count: int
    status: str = "ok"
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "url": self.url,
            "fetched_at": self.fetched_at,
            "fingerprint": self.fingerprint,
            "item_count": self.item_count,
            "status": self.status,
            "warning": self.warning,
        }


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_key(*parts: str) -> str:
    payload = "::".join((part or "").strip() for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def cache_text(name: str, text: str) -> Path:
    path = CACHE_DIR / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def cache_json(name: str, data: Any) -> Path:
    path = CACHE_DIR / name
    save_json(path, data)
    return path


def translate_idol(name: str) -> str:
    return IDOL_TRANSLATIONS.get(name, name)


def normalize_effect(text: str) -> str:
    cleaned = (text or "").strip().replace(" ", "").replace("　", "")
    for key, value in EFFECT_TRANSLATIONS.items():
        if cleaned == key.replace(" ", "").replace("　", ""):
            return value
    return text or ""


def extract_idol_song(card_name: str) -> tuple[str, str]:
    import re

    match = re.match(r"【(.+?)】(.+)", card_name)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    return card_name.strip(), ""


def fetch_support_translation() -> tuple[list[dict[str, Any]], SourceSnapshot]:
    with urllib.request.urlopen(SUPPORT_TRANSLATION_URL) as response:
        raw = response.read().decode("utf-8")
    cache_path = cache_text("support_translation.json", raw)
    payload = json.loads(raw)
    cards = payload.get("data", [])
    snapshot = SourceSnapshot(
        source="github:chinosk6/GakumasTranslationData",
        url=SUPPORT_TRANSLATION_URL,
        fetched_at=now_iso(),
        fingerprint=file_sha256(cache_path),
        item_count=len(cards),
    )
    return cards, snapshot


def fetch_idol_cards() -> tuple[list[dict[str, Any]], SourceSnapshot]:
    response = requests.get(IDOL_CARDS_URL, headers=DEFAULT_HEADERS, timeout=30)
    response.encoding = "EUC-JP"
    response.raise_for_status()
    cache_path = cache_text("idol_cards_source.html", response.text)
    soup = BeautifulSoup(response.text, "html.parser")

    all_cards: list[dict[str, Any]] = []
    rarity_map = {"SSR": "content_1_1", "SR": "content_1_2", "R": "content_1_3"}

    for rarity, anchor in rarity_map.items():
        section = soup.find("h4", id=anchor)
        if not section:
            continue
        parent = section.find_parent("div", class_="wiki-section-2")
        if not parent:
            continue
        table = parent.find("table", {"class": ["sort", "filter"]})
        if not table:
            continue

        headers: list[str] = []
        thead = table.find("thead")
        if thead and thead.find("tr"):
            headers = [th.get_text(strip=True) for th in thead.find("tr").find_all("th")]

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            record: dict[str, Any] = {"rarity": rarity}
            raw_name = ""
            for idx, cell in enumerate(cells):
                text = cell.get_text(strip=True)
                header = headers[idx] if idx < len(headers) else ""

                if header == "カード名":
                    raw_name = text
                    idol_name, song_name = extract_idol_song(text)
                    record.update(
                        {
                            "card_name_jp": f"{idol_name}({song_name})" if song_name else idol_name,
                            "idol_name_jp": idol_name,
                            "song_name_jp": song_name,
                            "idol_name_zh": translate_idol(idol_name),
                            "song_name_zh": "",
                        }
                    )
                elif header in {"Vo", "Da", "Vi", "体力"}:
                    try:
                        record[header] = int(text) if text else 0
                    except ValueError:
                        record[header] = text
                elif header == "ボーナス":
                    cleaned = text.replace("%", "").strip()
                    record["bonus"] = float(cleaned) if cleaned else 0.0
                elif header == "登場日" or "登場" in header:
                    record["debut_date"] = text
                elif "プラン" in header or "おすすめ" in header:
                    record["recommended_effect_jp"] = text
                    record["recommended_effect"] = normalize_effect(text)

            if raw_name:
                record["idol_card_id"] = stable_key(
                    "idol",
                    record.get("card_name_jp", ""),
                    rarity,
                    record.get("debut_date", ""),
                )
                all_cards.append(record)

    snapshot = SourceSnapshot(
        source="seesaawiki:gakumasu-idol-cards",
        url=IDOL_CARDS_URL,
        fetched_at=now_iso(),
        fingerprint=file_sha256(cache_path),
        item_count=len(all_cards),
    )
    return all_cards, snapshot


def normalize_idols_master(raw_cards: list[dict[str, Any]], snapshot: SourceSnapshot) -> dict[str, Any]:
    records = []
    for item in raw_cards:
        records.append(
            {
                "idol_card_id": item["idol_card_id"],
                "source_keys": {
                    "source_slug": item["idol_card_id"],
                    "card_name_jp": item.get("card_name_jp", ""),
                },
                "names": {
                    "card_jp": item.get("card_name_jp", ""),
                    "card_zh": item.get("card_name_jp", ""),
                    "idol_jp": item.get("idol_name_jp", ""),
                    "idol_zh": item.get("idol_name_zh", item.get("idol_name_jp", "")),
                    "song_jp": item.get("song_name_jp", ""),
                    "song_zh": item.get("song_name_zh", ""),
                },
                "rarity": item.get("rarity", ""),
                "stats": {
                    "Vo": item.get("Vo", 0),
                    "Da": item.get("Da", 0),
                    "Vi": item.get("Vi", 0),
                    "stamina": item.get("体力", 0),
                    "bonus": item.get("bonus", 0.0),
                },
                "recommended_effect": {
                    "jp": item.get("recommended_effect_jp", ""),
                    "zh": item.get("recommended_effect", ""),
                },
                "debut_date": item.get("debut_date", ""),
                "derived_tags": [],
                "unique_skill": None,
                "p_item": None,
                "sources": [snapshot.to_dict()],
            }
        )

    return {
        "schema_version": 1,
        "entity": "idol_cards",
        "updated_at": now_iso(),
        "sources": [snapshot.to_dict()],
        "records": records,
    }


def normalize_support_master(raw_cards: list[dict[str, Any]], snapshot: SourceSnapshot) -> dict[str, Any]:
    records = []
    for item in raw_cards:
        support_card_id = item.get("id", "") or stable_key("support", item.get("name", ""))
        records.append(
            {
                "support_card_id": support_card_id,
                "source_keys": {"translation_id": item.get("id", "")},
                "names": {"jp": item.get("name", ""), "zh": item.get("name", "")},
                "rarity": "",
                "effect_text": "",
                "event_name": "",
                "derived_tags": [],
                "sources": [snapshot.to_dict()],
            }
        )

    return {
        "schema_version": 1,
        "entity": "support_cards",
        "updated_at": now_iso(),
        "sources": [snapshot.to_dict()],
        "records": records,
    }


def build_skill_master() -> dict[str, Any]:
    source = {
        "source": "manual_seed:hif-skill-cards",
        "url": "https://gamerch.com/gakumasu/855252",
        "fetched_at": now_iso(),
        "fingerprint": "manual-seed-v1",
        "item_count": 8,
        "status": "seed",
        "warning": "??? HIF ?????????????????",
    }
    records = [
        {
            "skill_card_id": stable_key("skill_seed", "stretch_talk"),
            "source_keys": {"seed_key": "appeal_basic"},
            "names": {"jp": "???????", "zh": "????"},
            "type": "basic",
            "effect_text": "??????????????",
            "derived_tags": ["basic", "score_main"],
            "priority": {"upgrade": 1, "delete": 1},
            "sources": [source],
        },
        {
            "skill_card_id": stable_key("skill_seed", "spirited"),
            "source_keys": {"seed_key": "expression_basic"},
            "names": {"jp": "?????", "zh": "????"},
            "type": "basic",
            "effect_text": "????????????",
            "derived_tags": ["basic", "buff_main"],
            "priority": {"upgrade": 0, "delete": 1},
            "sources": [source],
        },
        {
            "skill_card_id": stable_key("skill_seed", "pose_basic"),
            "source_keys": {"seed_key": "pose_basic"},
            "names": {"jp": "??????", "zh": "????"},
            "type": "basic",
            "effect_text": "????????????????????",
            "derived_tags": ["basic", "buff_main"],
            "priority": {"upgrade": 0, "delete": 1},
            "sources": [source],
        },
        {
            "skill_card_id": stable_key("skill_seed", "spirited"),
            "source_keys": {"seed_key": "spirited"},
            "names": {"jp": "?????", "zh": "?????"},
            "type": "support",
            "effect_text": "???????????????",
            "derived_tags": ["buff_main"],
            "priority": {"upgrade": 1, "delete": 0},
            "sources": [source],
        },
        {
            "skill_card_id": stable_key("skill_seed", "first_step"),
            "source_keys": {"seed_key": "first_step"},
            "names": {"jp": "?????????", "zh": "???"},
            "type": "support",
            "effect_text": "??????????????",
            "derived_tags": ["buff_main"],
            "priority": {"upgrade": 1, "delete": 0},
            "sources": [source],
        },
        {
            "skill_card_id": stable_key("skill_seed", "stretch_talk"),
            "source_keys": {"seed_key": "stretch_talk"},
            "names": {"jp": "???????", "zh": "????"},
            "type": "engine",
            "effect_text": "???????????????????",
            "derived_tags": ["loop_core", "draw_cycle", "buff_main"],
            "priority": {"upgrade": 3, "delete": 0},
            "sources": [source],
        },
        {
            "skill_card_id": stable_key("skill_seed", "big_riceball"),
            "source_keys": {"seed_key": "big_riceball"},
            "names": {"jp": "????????", "zh": "???"},
            "type": "score",
            "effect_text": "???????????????",
            "derived_tags": ["score_main"],
            "priority": {"upgrade": 2, "delete": 0},
            "sources": [source],
        },
        {
            "skill_card_id": stable_key("skill_seed", "trouble"),
            "source_keys": {"seed_key": "trouble"},
            "names": {"jp": "????", "zh": "??"},
            "type": "trouble",
            "effect_text": "HIF ????????????",
            "derived_tags": ["trouble"],
            "priority": {"upgrade": 0, "delete": 5},
            "sources": [source],
        },
    ]
    return {
        "schema_version": 1,
        "entity": "skill_cards",
        "updated_at": now_iso(),
        "sources": [source],
        "records": records,
        "notes": "??? HIF ?????????? Gamerch / Seesaa ??????",
    }


def build_p_items_master() -> dict[str, Any]:
    source = {
        "source": "manual_seed:hif-p-items",
        "url": "https://wikiwiki.jp/gakumas/HIF/%E5%9F%BA%E6%9C%AC%E6%83%85%E5%A0%B1",
        "fetched_at": now_iso(),
        "fingerprint": "manual-seed-v1",
        "item_count": 6,
        "status": "seed",
        "warning": "??? HIF ?????????????? Wiki ?????",
    }
    records = [
        {
            "p_item_id": stable_key("pitem_seed", "hif_wappen"),
            "source_keys": {"seed_key": "hif_wappen"},
            "names": {"jp": "H.I.F????", "zh": "H.I.F??"},
            "scenario": "HIF",
            "effect_text": "?????????????????? HIF ??????",
            "derived_tags": ["star_synergy", "card_gain"],
            "sources": [source],
        },
        {
            "p_item_id": stable_key("pitem_seed", "outing_bag"),
            "source_keys": {"seed_key": "gripper"},
            "names": {"jp": "???????", "zh": "?????"},
            "scenario": "common",
            "effect_text": "?? P???????? P?????????",
            "derived_tags": ["ppoint_gain"],
            "sources": [source],
        },
        {
            "p_item_id": stable_key("pitem_seed", "outing_bag"),
            "source_keys": {"seed_key": "stepper"},
            "names": {"jp": "???????", "zh": "?????"},
            "scenario": "common",
            "effect_text": "?? P???????????????????",
            "derived_tags": ["ppoint_gain"],
            "sources": [source],
        },
        {
            "p_item_id": stable_key("pitem_seed", "dumbbell"),
            "source_keys": {"seed_key": "dumbbell"},
            "names": {"jp": "??????", "zh": "????"},
            "scenario": "common",
            "effect_text": "??????????????",
            "derived_tags": ["consult_discount"],
            "sources": [source],
        },
        {
            "p_item_id": stable_key("pitem_seed", "nia_tote"),
            "source_keys": {"seed_key": "nia_tote"},
            "names": {"jp": "N.I.A??????", "zh": "N.I.A???"},
            "scenario": "common",
            "effect_text": "P???????????????",
            "derived_tags": ["drink_gain"],
            "sources": [source],
        },
        {
            "p_item_id": stable_key("pitem_seed", "outing_bag"),
            "source_keys": {"seed_key": "outing_bag"},
            "names": {"jp": "???????", "zh": "???"},
            "scenario": "common",
            "effect_text": "??????????????????????",
            "derived_tags": ["card_gain"],
            "sources": [source],
        },
    ]
    return {
        "schema_version": 1,
        "entity": "p_items",
        "updated_at": now_iso(),
        "sources": [source],
        "records": records,
        "notes": "??? HIF ?????????????? Wiki ?????",
    }


def derive_idols_cards(master: dict[str, Any]) -> dict[str, Any]:
    grouped = {"保存时间": datetime.now().strftime("%Y/%m/%d"), "SSR": [], "SR": [], "R": []}
    for record in master.get("records", []):
        rarity = record.get("rarity", "")
        if rarity not in {"SSR", "SR", "R"}:
            continue
        names = record.get("names", {})
        stats = record.get("stats", {})
        effect = record.get("recommended_effect", {})
        grouped[rarity].append(
            {
                "卡片名称": names.get("card_jp", ""),
                "偶像名称": names.get("idol_jp", ""),
                "歌曲名称": names.get("song_jp", ""),
                "偶像中文": names.get("idol_zh", names.get("idol_jp", "")),
                "歌曲中文": names.get("song_zh", ""),
                "推荐效果": effect.get("zh", ""),
                "Vo": stats.get("Vo", 0),
                "Da": stats.get("Da", 0),
                "Vi": stats.get("Vi", 0),
                "体力": stats.get("stamina", 0),
                "奖励加成": stats.get("bonus", 0.0),
                "登场日期": record.get("debut_date", ""),
            }
        )
    for rarity in ("SSR", "SR", "R"):
        grouped[rarity] = sorted(
            grouped[rarity],
            key=lambda item: (item.get("偶像名称", ""), item.get("登场日期", "")),
            reverse=True,
        )
    return grouped


def merge_legacy_song_names(new_data: dict[str, Any], legacy_data: dict[str, Any]) -> dict[str, Any]:
    legacy_map: dict[tuple[str, str], str] = {}
    for rarity in ("SSR", "SR", "R"):
        for item in legacy_data.get(rarity, []):
            key = (item.get("偶像名称", ""), item.get("歌曲名称", ""))
            song_zh = item.get("歌曲中文", "")
            if song_zh:
                legacy_map[key] = song_zh

    for rarity in ("SSR", "SR", "R"):
        for item in new_data.get(rarity, []):
            key = (item.get("偶像名称", ""), item.get("歌曲名称", ""))
            if not item.get("歌曲中文") and key in legacy_map:
                item["歌曲中文"] = legacy_map[key]
    return new_data


def derive_support_cards(master: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": record.get("support_card_id", ""),
            "name": record.get("names", {}).get("zh", record.get("names", {}).get("jp", "")),
        }
        for record in master.get("records", [])
    ]


def derive_skill_cards_compact(skill_master: dict[str, Any]) -> list[dict[str, Any]]:
    compact = []
    for record in skill_master.get("records", []):
        tags = record.get("derived_tags", []) or (["trouble"] if record.get("type") == "trouble" else ["basic"])
        priority = record.get("priority", {})
        compact.append(
            {
                "skill_card_id": record.get("skill_card_id", ""),
                "name_jp": record.get("names", {}).get("jp", ""),
                "name_zh": record.get("names", {}).get("zh", ""),
                "tags": tags,
                "type": record.get("type", ""),
                "upgrade_priority": priority.get("upgrade", 0),
                "delete_priority": priority.get("delete", 0),
            }
        )
    return compact


def derive_decision_data(
    idols_master: dict[str, Any],
    skill_master: dict[str, Any],
    p_items_master: dict[str, Any],
) -> dict[str, Any]:
    idol_cards = []
    for record in idols_master.get("records", []):
        names = record.get("names", {})
        idol_zh = names.get("idol_zh", "")
        pref = IDOL_PREFERENCES.get(idol_zh, {})
        idol_cards.append(
            {
                "idol_card_id": record.get("idol_card_id", ""),
                "idol_name_jp": names.get("idol_jp", ""),
                "idol_name_zh": idol_zh,
                "card_name_jp": names.get("card_jp", ""),
                "recommended_effect": record.get("recommended_effect", {}).get("zh", ""),
                "first": pref.get("first", ""),
                "second": pref.get("second", ""),
                "derived_tags": record.get("derived_tags", []),
            }
        )

    skill_cards = derive_skill_cards_compact(skill_master)
    p_items = []
    for record in p_items_master.get("records", []):
        p_items.append(
            {
                "p_item_id": record.get("p_item_id", ""),
                "name_jp": record.get("names", {}).get("jp", ""),
                "name_zh": record.get("names", {}).get("zh", ""),
                "scenario": record.get("scenario", ""),
                "tags": record.get("derived_tags", []) or [],
            }
        )

    return {
        "schema_version": 1,
        "updated_at": now_iso(),
        "idol_cards": idol_cards,
        "skill_cards": skill_cards,
        "p_items": p_items,
    }


def write_entities_meta(snapshots: list[SourceSnapshot], mode: str) -> None:
    save_json(
        ENTITIES_META,
        {
            "schema_version": 1,
            "updated_at": now_iso(),
            "mode": mode,
            "sources": [snapshot.to_dict() for snapshot in snapshots],
        },
    )


def validate_master(master: dict[str, Any], id_key: str, name: str) -> list[str]:
    errors = []
    records = master.get("records", [])
    if not isinstance(records, list):
        return [f"{name}: records 不是列表"]
    ids = [record.get(id_key, "") for record in records]
    if any(not item for item in ids):
        errors.append(f"{name}: 存在空主键")
    if len(set(ids)) != len(ids):
        errors.append(f"{name}: 主键重复")
    return errors


def validate_all() -> list[str]:
    errors = []
    errors.extend(validate_master(load_json(IDOLS_MASTER, {}), "idol_card_id", "idols_master"))
    errors.extend(validate_master(load_json(SUPPORT_MASTER, {}), "support_card_id", "support_cards_master"))
    skill_master = load_json(SKILL_MASTER, {})
    if skill_master:
        errors.extend(validate_master(skill_master, "skill_card_id", "skill_cards_master"))
    p_items_master = load_json(P_ITEMS_MASTER, {})
    if p_items_master:
        errors.extend(validate_master(p_items_master, "p_item_id", "p_items_master"))
    return errors


def run_fetch() -> list[SourceSnapshot]:
    ensure_dirs()
    snapshots: list[SourceSnapshot] = []

    support_cards, support_snapshot = fetch_support_translation()
    cache_json("support_translation_parsed.json", support_cards)
    snapshots.append(support_snapshot)

    try:
        idol_cards, idol_snapshot = fetch_idol_cards()
        cache_json("idol_cards_parsed.json", idol_cards)
        snapshots.append(idol_snapshot)
    except Exception as exc:
        snapshots.append(
            SourceSnapshot(
                source="seesaawiki:gakumasu-idol-cards",
                url=IDOL_CARDS_URL,
                fetched_at=now_iso(),
                fingerprint="",
                item_count=0,
                status="error",
                warning=str(exc),
            )
        )

    return snapshots


def run_normalize() -> list[SourceSnapshot]:
    ensure_dirs()

    support_cards, support_snapshot = fetch_support_translation()
    support_master = normalize_support_master(support_cards, support_snapshot)
    save_json(SUPPORT_MASTER, support_master)

    idol_cards, idol_snapshot = fetch_idol_cards()
    idols_master = normalize_idols_master(idol_cards, idol_snapshot)
    save_json(IDOLS_MASTER, idols_master)

    if not SKILL_MASTER.exists():
        save_json(SKILL_MASTER, build_skill_master())
    if not P_ITEMS_MASTER.exists():
        save_json(P_ITEMS_MASTER, build_p_items_master())

    snapshots = [support_snapshot, idol_snapshot]
    write_entities_meta(snapshots, "normalize")
    return snapshots


def run_derive(write_legacy_compact: bool = False) -> None:
    ensure_dirs()
    idols_master = load_json(IDOLS_MASTER, {})
    support_master = load_json(SUPPORT_MASTER, {})
    skill_master = load_json(SKILL_MASTER, build_skill_master())
    p_items_master = load_json(P_ITEMS_MASTER, build_p_items_master())
    legacy_idols_compact = load_json(IDOLS_COMPACT, {})

    idols_compact = derive_idols_cards(idols_master)
    if legacy_idols_compact:
        idols_compact = merge_legacy_song_names(idols_compact, legacy_idols_compact)

    support_compact = derive_support_cards(support_master)

    if write_legacy_compact:
        save_json(IDOLS_COMPACT, idols_compact)
        save_json(SUPPORT_COMPACT, support_compact)
    else:
        save_json(IDOLS_COMPACT_PREVIEW, idols_compact)
        save_json(SUPPORT_COMPACT_PREVIEW, support_compact)

    save_json(SKILL_COMPACT, derive_skill_cards_compact(skill_master))
    save_json(DECISION_COMPACT, derive_decision_data(idols_master, skill_master, p_items_master))


def run_report() -> dict[str, Any]:
    return {
        "updated_at": now_iso(),
        "idols_master_records": len(load_json(IDOLS_MASTER, {}).get("records", [])),
        "support_master_records": len(load_json(SUPPORT_MASTER, {}).get("records", [])),
        "skill_master_records": len(load_json(SKILL_MASTER, {}).get("records", [])),
        "p_items_master_records": len(load_json(P_ITEMS_MASTER, {}).get("records", [])),
        "legacy_compact_overwrite_default": False,
        "idols_compact_preview": str(IDOLS_COMPACT_PREVIEW),
        "support_compact_preview": str(SUPPORT_COMPACT_PREVIEW),
        "validation_errors": validate_all(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="学マス资料抓取与本地数据体系工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("fetch")
    subparsers.add_parser("normalize")
    derive_parser = subparsers.add_parser("derive")
    derive_parser.add_argument("--write-legacy-compact", action="store_true")
    subparsers.add_parser("validate")
    subparsers.add_parser("report")
    all_parser = subparsers.add_parser("all")
    all_parser.add_argument("--write-legacy-compact", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "fetch":
        snapshots = run_fetch()
        print(json.dumps([snapshot.to_dict() for snapshot in snapshots], ensure_ascii=False, indent=2))
        return 0

    if args.command == "normalize":
        snapshots = run_normalize()
        print(json.dumps([snapshot.to_dict() for snapshot in snapshots], ensure_ascii=False, indent=2))
        return 0

    if args.command == "derive":
        run_derive(write_legacy_compact=args.write_legacy_compact)
        return 0

    if args.command == "validate":
        errors = validate_all()
        if errors:
            for error in errors:
                print(error)
            return 1
        print("validation passed")
        return 0

    if args.command == "report":
        print(json.dumps(run_report(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "all":
        run_normalize()
        run_derive(write_legacy_compact=args.write_legacy_compact)
        report = run_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["validation_errors"] else 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
