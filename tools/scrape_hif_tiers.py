"""抓取 HIF 校准用社区共识 tier 榜 → .scrape/hif_tiers.json(scoring-model 计划 A3)。

用法:
    python tools/scrape_hif_tiers.py            # 抓全部源
    python tools/scrape_hif_tiers.py --source game8

数据源:
- Game8 最強スキルカードランキング: 按计划(センス/ロジック/アノマリー/フリー)分表,
  行首 tier 横幅图 alt="SSバナー" 等(或文本"圏外"),卡名 = 卡片图 alt 去"画像"后缀。
  同卡多表出现时取标准表(非"初レジェンド")中的最高档位(SS>S>A>B>C>圏外)。
- seesaawiki 編成一覧(EUC-JP): 取"決戦級"相关表格,按本地 master121 白名单
  (assets/data/hif/skill_cards_master.json)统计卡名出现频次,作为共识投票代理指标。

容错: 单源失败不中断另一源,status/warning 记录原因;全部失败退出码 1。
页面结构变化解析不出卡时同样记 error,不输出空数据假装成功。
seesaawiki 对部分出口 IP 整站 403(2026-08 实测),此时换网络环境人工重跑即可。
"""

import sys
import json
import time
import argparse
import unicodedata
from pathlib import Path
from collections import Counter
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parents[1]
OUT_PATH = REPO / ".scrape" / "hif_tiers.json"
MASTER_PATH = REPO / "assets" / "data" / "hif" / "skill_cards_master.json"

GAME8_URL = "https://game8.jp/gakuen-idolmaster/609862"
SEESAAWIKI_URL = "https://seesaawiki.jp/gakumasu/d/" + quote("編成一覧".encode("euc-jp"))

DEFAULT_HEADERS = {
    "User-Agent": "MaaGakumasu/1.0 (+https://github.com/SuperWaterGod/MaaGakumasu)"
}

# 档位排序(越小越高);圏外垫底,未知档位排在圏外之前、C 之后
TIER_RANK = {"SS": 0, "S": 1, "A": 2, "B": 3, "C": 4, "D": 5, "圏外": 99}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def norm_name(text: str) -> str:
    """NFKC 归一 + 去空白(全半角) + 去尾部强化档位后缀,用于同名合并与白名单匹配。"""
    cleaned = unicodedata.normalize("NFKC", text or "").strip().replace(" ", "").replace("　", "")
    while cleaned.endswith("+"):
        cleaned = cleaned[:-1]
    return cleaned


def source_entry(source: str, url: str, status: str, warning: str = "") -> dict:
    return {"source": source, "url": url, "fetched_at": now_iso(), "status": status, "warning": warning}


def tier_sort_key(tier: str) -> int:
    return TIER_RANK.get(tier, 90)


# ---------------------------------------------------------------- Game8


def parse_game8(html: str) -> dict[str, str]:
    """解析 Game8 tier 表 → {卡名: 档位}。标准表(非初レジェンド)取最高档。"""
    soup = BeautifulSoup(html, "html.parser")
    best: dict[str, str] = {}
    tables_found = 0

    for h3 in soup.find_all("h3"):
        if "Tier表" not in h3.get_text(strip=True):
            continue
        table = None
        for sib in h3.find_next_siblings():
            if sib.name == "table":
                table = sib
                break
            if sib.name in ("h2", "h3"):
                break
        if table is None:
            continue
        tables_found += 1
        is_legend = "レジェンド" in h3.get_text(strip=True)

        for row in table.find_all("tr"):
            first = row.find(["td", "th"])
            if first is None:
                continue
            tier = unicodedata.normalize("NFKC", first.get_text(strip=True))
            if not tier:
                banner = first.find("img", alt=True)
                alt = unicodedata.normalize("NFKC", banner.get("alt", ""))
                if alt.endswith("バナー"):
                    tier = alt[:-3]
            if not tier or (tier != "圏外" and tier not in TIER_RANK):
                continue
            if is_legend:
                continue  # 初レジェンド是另一模式的榜,不并入 HIF 锚点
            for img in row.find_all("img", alt=True):
                alt = unicodedata.normalize("NFKC", img.get("alt", ""))
                if alt.endswith("画像") and len(alt) > 2:
                    name = norm_name(alt[:-2])
                    if not name:
                        continue
                    if name not in best or tier_sort_key(tier) < tier_sort_key(best[name]):
                        best[name] = tier

    if tables_found == 0:
        raise ValueError("Game8 页面未找到任何『Tier表』标题下的表格,页面结构可能已变化")
    if not best:
        raise ValueError("Game8 tier 表解析出 0 张卡(卡图 alt 结构可能已变化)")
    return dict(sorted(best.items(), key=lambda kv: (tier_sort_key(kv[1]), kv[0])))


def fetch_game8() -> tuple[dict[str, str], dict]:
    resp = requests.get(GAME8_URL, headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    tiers = parse_game8(resp.text)
    return tiers, source_entry("game8", GAME8_URL, "ok")


# ---------------------------------------------------------- seesaawiki


def load_whitelist() -> set[str]:
    if not MASTER_PATH.exists():
        return set()
    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    return {norm_name(c["name_jp"]) for c in master.get("cards", []) if c.get("name_jp")}


def _wiki_section(node) -> object | None:
    """向上找 seesaawiki 的 wiki-section 容器 div(包住该标题的全部内容)。"""
    for parent in node.parents:
        if parent.name == "div" and any("wiki-section" in c for c in parent.get("class") or []):
            return parent
    return None


def _tables_after_heading(soup: BeautifulSoup, keyword: str) -> list:
    """收集标题(含 keyword)相关表格:标题所在 wiki-section 内,或其后兄弟直到下一标题。"""
    tables: list = []
    seen: set[int] = set()

    def add(candidate) -> None:
        if candidate is not None and id(candidate) not in seen:
            seen.add(id(candidate))
            tables.append(candidate)

    for head in soup.find_all(["h2", "h3", "h4"]):
        if keyword not in head.get_text(strip=True):
            continue
        section = _wiki_section(head)
        if section is not None:
            for table in section.find_all("table"):
                add(table)
            continue
        # 不在 section 容器内:只收标题后的兄弟表格,直到下一个标题/section
        for sib in head.find_next_siblings():
            if sib.name in ("h2", "h3", "h4"):
                break
            if sib.name == "table":
                add(sib)
            elif sib.name == "div" and any("wiki-section" in c for c in sib.get("class") or []):
                break
    return tables


def parse_seesaawiki(html: str) -> dict[str, int]:
    """解析編成一覧『決戦級』表格 → {卡名: 出现次数}。白名单限定,防误计偶像名/数值。"""
    soup = BeautifulSoup(html, "html.parser")
    whitelist = load_whitelist()
    if not whitelist:
        raise ValueError(f"卡名白名单缺失或为空: {MASTER_PATH}(先运行 tools/sync_hif_master.py)")

    tables = _tables_after_heading(soup, "決戦級") or _tables_after_heading(soup, "決戦")
    if not tables:
        raise ValueError("編成一覧页面未找到『決戦級/決戦』标题下的表格,页面结构可能已变化")

    counts: Counter[str] = Counter()
    for table in tables:
        for cell in table.find_all(["td", "th"]):
            # 候选文本:整格文本 + 各链接文本(链接名常与格文本重复,需去重)
            candidates = {cell.get_text(strip=True)}
            candidates.update(a.get_text(strip=True) for a in cell.find_all("a"))
            # 一格可能混排多卡(A/B、A+B),按常见分隔符拆分后逐段匹配白名单
            matched: set[str] = set()
            for text in candidates:
                for fragment in text.replace("/", " ").replace("、", " ").replace("・", " ").split():
                    name = norm_name(fragment)
                    if name in whitelist:
                        matched.add(name)
            for name in matched:
                counts[name] += 1

    if not counts:
        raise ValueError(f"決戦級表格解析出 0 张白名单卡(共 {len(tables)} 表;页面结构或卡名写法可能已变化)")
    return dict(counts.most_common())


def fetch_seesaawiki() -> tuple[dict[str, int], dict]:
    resp = requests.get(SEESAAWIKI_URL, headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "EUC-JP"
    counts = parse_seesaawiki(resp.text)
    return counts, source_entry("seesaawiki", SEESAAWIKI_URL, "ok")


# ---------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["game8", "seesaawiki", "all"], default="all")
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    sources: list[dict] = []
    game8_tiers: dict[str, str] = {}
    seesaawiki_counts: dict[str, int] = {}

    if args.source in ("game8", "all"):
        try:
            game8_tiers, entry = fetch_game8()
            print(f"[game8] ok: {len(game8_tiers)} 张卡")
        except Exception as exc:
            entry = source_entry("game8", GAME8_URL, "error", str(exc))
            print(f"[game8] FAIL: {exc}", file=sys.stderr)
        sources.append(entry)

    if args.source in ("seesaawiki", "all"):
        try:
            seesaawiki_counts, entry = fetch_seesaawiki()
            print(f"[seesaawiki] ok: {len(seesaawiki_counts)} 张卡")
        except Exception as exc:
            entry = source_entry("seesaawiki", SEESAAWIKI_URL, "error", str(exc))
            print(f"[seesaawiki] FAIL: {exc}", file=sys.stderr)
        sources.append(entry)

    payload = {
        "schema_version": 1,
        "updated_at": now_iso(),
        "sources": sources,
        "game8_tiers": game8_tiers,
        "seesaawiki_counts": seesaawiki_counts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written: {args.output}")

    if game8_tiers:
        sample = list(game8_tiers.items())[:10]
        print("game8 sample:", ", ".join(f"{n}={t}" for n, t in sample))
    if seesaawiki_counts:
        sample = list(seesaawiki_counts.items())[:10]
        print("seesaawiki top:", ", ".join(f"{n}x{c}" for n, c in sample))

    if all(s["status"] == "error" for s in sources):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
