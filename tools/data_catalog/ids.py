"""统一目录的稳定实体 ID。"""

from __future__ import annotations

from uuid import UUID, uuid5

# 项目固定命名空间；发布后不得更换。
CATALOG_NAMESPACE = UUID("453f8356-a7b1-5cdd-a5de-4d589c0017fd")


def stable_entity_uuid(entity_type: str, source: str, source_key: str) -> UUID:
    parts = (entity_type.strip(), source.strip(), source_key.strip())
    if any(not part for part in parts):
        raise ValueError("entity_type、source 和 source_key 均不能为空")
    return uuid5(CATALOG_NAMESPACE, "\x1f".join(parts))


def stable_entity_id(entity_type: str, source: str, source_key: str) -> str:
    """以稳定来源键生成带实体类型前缀的 UUIDv5。"""

    normalized_type = entity_type.strip()
    return f"{normalized_type}:{stable_entity_uuid(normalized_type, source, source_key)}"
