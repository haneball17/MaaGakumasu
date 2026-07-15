"""离线来源提取器。网络访问必须留在 :mod:`tools.data_catalog.fetch`。"""

from __future__ import annotations

import re
import hashlib
from typing import Any
from html.parser import HTMLParser

from .ids import stable_entity_id


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(_clean("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def extract_idol_cards_html(
    html: str,
    *,
    source_id: str = "source:seesaawiki-produce-idol-cards",
    observed_at: str,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """从 Wiki 表格提取 P 偶像卡候选与字段级断言。

    数量完全由页面决定。支持 ``Vo/Da/Vi`` 数值列和各自的 bonus 列，亦
    支持 ``100 (+15%)`` 的组合单元格。只有共享 ``ボーナス`` 时会保留为
    ``legacy_shared_bonus``，不会复制成三个独立事实。
    """

    parser = _TableParser()
    parser.feed(html)
    digest = content_hash or f"sha256:{hashlib.sha256(html.encode('utf-8')).hexdigest()}"
    records: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for table_index, table in enumerate(parser.tables):
        if len(table) < 2:
            continue
        headers = _contextual_headers(table[0])
        if not _has_card_name(headers):
            continue
        for row_index, cells in enumerate(table[1:], start=1):
            row = {headers[index]: cells[index] for index in range(min(len(headers), len(cells)))}
            name = _first(row, "card_name", "name")
            if not name:
                continue
            source_key = _first(row, "wiki_id", "id") or name
            entity_id = stable_entity_id("produce_idol_card", source_id, source_key)
            profile, profile_warnings = _stat_profile(row)
            warnings.extend(
                {"reason_code": reason, "source_locator": f"table:{table_index}/row:{row_index}", "card": name}
                for reason in profile_warnings
            )
            idol_name, title = _split_card_name(name)
            record = {
                "schema_version": "2.0",
                "entity_id": entity_id,
                "source_keys": {"source_page_key": source_key},
                "character_source_key": idol_name,
                "names": {"ja-JP": {"canonical": name}},
                "idol_name_jp": idol_name,
                "title_jp": title,
                "provisional_match_key": f"{idol_name}({title})" if title else idol_name,
                "rarity": _first(row, "rarity") or None,
                "debut_date": _first(row, "debut_date") or None,
                "stat_profiles": [profile],
                "strategy_annotations": [
                    {
                        "kind": "recommended_effect",
                        "text": _first(row, "recommended_effect") or "",
                        "fact_status": "strategy_only",
                    }
                ],
            }
            records.append(record)
            locator = f"table:{table_index}/row:{row_index}"
            for field, value in _assertable_fields(record):
                assertion_payload = f"{entity_id}\0{field}\0{value!r}\0{digest}"
                assertion_id = hashlib.sha256(assertion_payload.encode("utf-8")).hexdigest()
                assertions.append(
                    {
                        "schema_version": "2.0",
                        "assertion_id": f"assertion:{assertion_id}",
                        "entity_id": entity_id,
                        "field_path": field,
                        "value": value,
                        "raw_value": value,
                        "source_id": source_id,
                        "source_locator": locator,
                        "observed_at": observed_at,
                        "effective_from": None,
                        "source_confidence": "community_structured",
                        "parse_status": "complete",
                        "verification_status": "unverified",
                        "runtime_support": "display_only",
                        "parser_version": "seesaa-idols/2",
                        "content_hash": digest,
                    }
                )
    return {"records": records, "assertions": assertions, "warnings": warnings, "content_hash": digest}


def _stat_profile(row: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    profile: dict[str, Any] = {
        "profile_id": "source_default",
        "context": {"enhancement": "source_table_default"},
        "stamina": _number(_first(row, "stamina")),
    }
    for stat in ("vo", "da", "vi"):
        value, inline_bonus = _stat_and_bonus(_first(row, stat))
        explicit_bonus = _percent(_first(row, f"{stat}_bonus"))
        if explicit_bonus is not None and inline_bonus is not None and explicit_bonus != inline_bonus:
            warnings.append(f"conflicting_{stat}_bonus")
        profile[stat] = {"value": value, "bonus_percent": explicit_bonus if explicit_bonus is not None else inline_bonus}
    shared = _percent(_first(row, "shared_bonus"))
    if shared is not None:
        profile["legacy_shared_bonus"] = {
            "value": shared,
            "applies_to": ["vo", "da", "vi"],
            "evidence_status": "legacy_shared",
        }
    return profile, warnings


def _normalize_header(value: str) -> str:
    text = re.sub(r"\s+", "", value).lower()
    aliases = {
        "カード名": "card_name",
        "pアイドル": "card_name",
        "名前": "name",
        "id": "wiki_id",
        "wikiid": "wiki_id",
        "レアリティ": "rarity",
        "レア": "rarity",
        "vo": "vo",
        "da": "da",
        "vi": "vi",
        "体力": "stamina",
        "voボーナス": "vo_bonus",
        "voボーナス%": "vo_bonus",
        "vo加成": "vo_bonus",
        "daボーナス": "da_bonus",
        "daボーナス%": "da_bonus",
        "da加成": "da_bonus",
        "viボーナス": "vi_bonus",
        "viボーナス%": "vi_bonus",
        "vi加成": "vi_bonus",
        "ボーナス": "shared_bonus",
        "登場日": "debut_date",
        "登場": "debut_date",
        "おすすめ": "recommended_effect",
        "おすすめ効果": "recommended_effect",
        "プラン": "recommended_effect",
        "プランおすすめ効果": "recommended_effect",
    }
    return aliases.get(text, text)


def _contextual_headers(values: list[str]) -> list[str]:
    """把 Wiki 中重复的「ボーナス」按其前置 Vo/Da/Vi 列消歧。"""

    headers: list[str] = []
    previous_stat: str | None = None
    for value in values:
        header = _normalize_header(value)
        if header in {"vo", "da", "vi"}:
            previous_stat = header
        elif header == "shared_bonus" and previous_stat is not None:
            header = f"{previous_stat}_bonus"
            previous_stat = None
        elif header != "shared_bonus":
            previous_stat = None
        headers.append(header)
    return headers


def _has_card_name(headers: list[str]) -> bool:
    return ("card_name" in headers or "name" in headers) and {"vo", "da", "vi"}.issubset(headers)


def _first(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return value
    return ""


def _number(value: str) -> int | float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        return None
    number = float(match.group())
    return int(number) if number.is_integer() else number


def _percent(value: str) -> int | float | None:
    if not value:
        return None
    return _number(value)


def _stat_and_bonus(value: str) -> tuple[int | float | None, int | float | None]:
    stat_value = _number(value)
    bonus_match = re.search(r"(?:\(|（|\s)([-+]?\d+(?:\.\d+)?)\s*%", value)
    bonus = _number(bonus_match.group(1)) if bonus_match else None
    return stat_value, bonus


def _split_card_name(value: str) -> tuple[str, str | None]:
    bracket = re.match(r"^【(.*?)】\s*(.+)$", value, flags=re.DOTALL)
    if bracket:
        return _clean(bracket.group(2)), _clean(bracket.group(1))
    match = re.match(r"^(.*?)\s*[（(](.*?)[）)]$", value)
    return (match.group(1).strip(), match.group(2).strip()) if match else (value, None)


def _assertable_fields(record: dict[str, Any]) -> list[tuple[str, Any]]:
    profile = record["stat_profiles"][0]
    result: list[tuple[str, Any]] = [
        ("/names/ja-JP/canonical", record["names"]["ja-JP"]["canonical"]),
        ("/rarity", record["rarity"]),
        ("/debut_date", record["debut_date"]),
    ]
    for stat in ("vo", "da", "vi"):
        result.append((f"/stat_profiles/0/{stat}/value", profile[stat]["value"]))
        result.append((f"/stat_profiles/0/{stat}/bonus_percent", profile[stat]["bonus_percent"]))
    result.append(("/stat_profiles/0/stamina", profile["stamina"]))
    if "legacy_shared_bonus" in profile:
        result.append(("/stat_profiles/0/legacy_shared_bonus", profile["legacy_shared_bonus"]))
    result.append(("/strategy_annotations/0/text", record["strategy_annotations"][0]["text"]))
    return result


def _clean(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()
