"""统一游戏数据目录 v2 的核心工具。"""

from .io import read_json, read_jsonl, write_json, sha256_file, write_jsonl
from .ids import CATALOG_NAMESPACE, stable_entity_id
from .schema import SCHEMA_MAJOR_VERSION, SchemaStore, validate_instance

__all__ = [
    "CATALOG_NAMESPACE",
    "SCHEMA_MAJOR_VERSION",
    "SchemaStore",
    "read_json",
    "read_jsonl",
    "sha256_file",
    "stable_entity_id",
    "validate_instance",
    "write_json",
    "write_jsonl",
]
