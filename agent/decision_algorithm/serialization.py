"""规范 JSON、SHA-256 与无第三方依赖的最小 JSON Schema 校验。"""

from __future__ import annotations

import re
import json
import math
from enum import Enum
from typing import Any
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from dataclasses import fields, is_dataclass

DECIMAL_PLACES = 6
SCHEMA_DIRECTORY = Path(__file__).with_name("schemas")


class SchemaValidationError(ValueError):
    pass


def canonical_decimal(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("只允许有限 Decimal")
    value = value.normalize()
    exponent = value.as_tuple().exponent
    if exponent < -DECIMAL_PLACES:
        raise ValueError(f"Decimal 最多允许 {DECIMAL_PLACES} 位小数")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def canonical_json_data(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        data = {field.name: canonical_json_data(getattr(value, field.name)) for field in fields(value)}
        action_type = getattr(value, "action_type", None)
        if action_type is not None and "action_type" not in data:
            data["action_type"] = canonical_json_data(action_type)
        return data
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON 对象键必须为字符串")
        return {key: canonical_json_data(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical_json_data(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("禁止 NaN/Infinity")
        raise TypeError("领域 JSON 禁止二进制浮点；请使用 Decimal")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"不支持规范序列化的类型: {type(value).__name__}")


def canonical_json_text(value: Any) -> str:
    return json.dumps(canonical_json_data(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json_text(value).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def load_schema(schema_name: str) -> dict[str, Any]:
    path = (SCHEMA_DIRECTORY / schema_name).resolve()
    if path.parent != SCHEMA_DIRECTORY.resolve() or not path.is_file():
        raise ValueError(f"未知 Schema: {schema_name}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schema(instance: Any, schema_name: str) -> None:
    """校验本项目首版 Schema 使用到的 JSON Schema 2020-12 子集。"""

    data = canonical_json_data(instance)
    _validate(data, load_schema(schema_name), "$", schema_name)


def _resolve_ref(ref: str, current_schema_name: str) -> tuple[dict[str, Any], str]:
    if ref.startswith("#/"):
        schema = load_schema(current_schema_name)
        target: Any = schema
        for token in ref[2:].split("/"):
            target = target[token.replace("~1", "/").replace("~0", "~")]
        return target, current_schema_name
    if "#" in ref:
        filename, fragment = ref.split("#", 1)
        schema = load_schema(filename)
        target: Any = schema
        for token in fragment.removeprefix("/").split("/") if fragment else ():
            target = target[token.replace("~1", "/").replace("~0", "~")]
        return target, filename
    return load_schema(ref), ref


def _fail(path: str, message: str) -> None:
    raise SchemaValidationError(f"{path}: {message}")


def _validate(instance: Any, schema: dict[str, Any], path: str, current_schema_name: str) -> None:
    if "$ref" in schema:
        target, target_name = _resolve_ref(schema["$ref"], current_schema_name)
        _validate(instance, target, path, target_name)
        return
    if "const" in schema and instance != schema["const"]:
        _fail(path, f"必须等于 {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        _fail(path, "不在允许枚举中")
    if "anyOf" in schema or "oneOf" in schema:
        variants = schema.get("anyOf", schema.get("oneOf"))
        matches = 0
        for variant in variants:
            try:
                _validate(instance, variant, path, current_schema_name)
                matches += 1
            except SchemaValidationError:
                pass
        if matches == 0 or ("oneOf" in schema and matches != 1):
            _fail(path, "不匹配联合类型")
        return
    expected = schema.get("type")
    if expected is not None:
        allowed = [expected] if isinstance(expected, str) else expected
        actual = _json_type(instance)
        if actual not in allowed:
            _fail(path, f"类型应为 {allowed}，实际为 {actual}")
    if isinstance(instance, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in instance]
        if missing:
            _fail(path, f"缺少字段 {missing}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                _validate(value, properties[key], f"{path}.{key}", current_schema_name)
            elif schema.get("additionalProperties") is False:
                _fail(path, f"不允许字段 {key}")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            _fail(path, "数组元素不足")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in instance}) != len(instance):
            _fail(path, "数组元素必须唯一")
        if "items" in schema:
            for index, item in enumerate(instance):
                _validate(item, schema["items"], f"{path}[{index}]", current_schema_name)
    if isinstance(instance, str):
        if "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
            _fail(path, "字符串格式不匹配")
        if len(instance) < schema.get("minLength", 0):
            _fail(path, "字符串过短")
        if "format" in schema and schema["format"] == "decimal":
            try:
                canonical_decimal(Decimal(instance))
            except (InvalidOperation, ValueError) as error:
                _fail(path, f"十进制字符串无效: {error}")
    if isinstance(instance, int) and not isinstance(instance, bool) and instance < schema.get("minimum", instance):
        _fail(path, f"数值小于 {schema['minimum']}")


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"
