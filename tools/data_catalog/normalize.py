"""名称匹配键归一化；不承担实体合并。"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from collections import defaultdict
from dataclasses import dataclass
from collections.abc import Mapping, Iterable

_ENHANCEMENT_SUFFIX = re.compile(r"(?P<suffix>無印|\+{1,3})$")
_DECORATION = re.compile(r"^[\s★☆◆◇■□●○・･]+|[\s★☆◆◇■□●○・･]+$")
_PUNCTUATION_TRANSLATION = str.maketrans({"（": "(", "）": ")", "［": "[", "］": "]", "：": ":"})


@dataclass(frozen=True, slots=True)
class NormalizedName:
    raw: str
    match_key: str
    base_match_key: str
    enhancement: str | None


def normalize_name(value: str) -> NormalizedName:
    if not isinstance(value, str):
        raise TypeError("名称必须为字符串")
    normalized = unicodedata.normalize("NFKC", value).translate(_PUNCTUATION_TRANSLATION)
    normalized = _DECORATION.sub("", normalized)
    normalized = "".join(normalized.split())
    match = _ENHANCEMENT_SUFFIX.search(normalized)
    enhancement = match.group("suffix") if match else None
    base = normalized[: match.start()] if match else normalized
    return NormalizedName(raw=value, match_key=normalized, base_match_key=base, enhancement=enhancement)


def normalize_match_key(value: str) -> str:
    return normalize_name(value).match_key


def normalization_collisions(
    records: Iterable[Mapping[str, Any]],
    *,
    value_field: str = "value",
    identity_field: str = "entity_id",
) -> list[dict[str, Any]]:
    """报告同一匹配键指向多个身份的情况，不执行合并。"""

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        value = record.get(value_field)
        identity = record.get(identity_field)
        if not isinstance(value, str) or not value or not isinstance(identity, str) or not identity:
            continue
        buckets[normalize_match_key(value)].append({"entity_id": identity, "raw": value})

    collisions = []
    for match_key, candidates in buckets.items():
        identities = {candidate["entity_id"] for candidate in candidates}
        if len(identities) > 1:
            collisions.append({"match_key": match_key, "candidates": sorted(candidates, key=lambda item: (item["entity_id"], item["raw"]))})
    return sorted(collisions, key=lambda item: item["match_key"])
