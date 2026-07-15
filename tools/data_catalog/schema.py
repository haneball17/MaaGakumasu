"""JSON Schema Draft 2020-12 加载与校验。"""

from __future__ import annotations

import re
import json
from typing import Any
from pathlib import Path

SCHEMA_MAJOR_VERSION = 2
DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "assets" / "data" / "catalog" / "schemas"


class UnsupportedSchemaVersion(ValueError):
    pass


def schema_major(value: Any) -> int:
    if isinstance(value, bool):
        raise UnsupportedSchemaVersion("schema_version 不是合法版本")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and (match := re.fullmatch(r"(\d+)(?:\.\d+)?", value)):
        return int(match.group(1))
    if isinstance(value, dict) and isinstance(value.get("major"), int):
        return value["major"]
    raise UnsupportedSchemaVersion("schema_version 不是合法版本")


def require_supported_schema_version(instance: Any) -> None:
    if not isinstance(instance, dict) or "schema_version" not in instance:
        return
    major = schema_major(instance["schema_version"])
    if major != SCHEMA_MAJOR_VERSION:
        raise UnsupportedSchemaVersion(f"不支持的 Schema 主版本 {major}，仅支持 {SCHEMA_MAJOR_VERSION}")


class SchemaStore:
    def __init__(self, schema_dir: str | Path = DEFAULT_SCHEMA_DIR) -> None:
        self.schema_dir = Path(schema_dir)

    def load(self, name: str) -> dict[str, Any]:
        filename = name if name.endswith(".schema.json") else f"{name}.schema.json"
        path = self.schema_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"缺少 Schema: {path}")
        schema = json.loads(path.read_text(encoding="utf-8"))
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(schema)
        return schema

    def validate(self, name: str, instance: Any) -> None:
        require_supported_schema_version(instance)
        from jsonschema import RefResolver, Draft202012Validator

        schema = self.load(name)
        schemas = {loaded["$id"]: loaded for path in self.schema_dir.glob("*.schema.json") if (loaded := json.loads(path.read_text(encoding="utf-8"))).get("$id")}
        validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema, store=schemas))
        validator.validate(instance)


def validate_instance(name: str, instance: Any, *, schema_dir: str | Path = DEFAULT_SCHEMA_DIR) -> None:
    SchemaStore(schema_dir).validate(name, instance)
