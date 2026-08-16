"""ScenarioSpec 契约导出(pydantic → JSON Schema → TS,§4.1/§8.4)。

用法:
    python tools/export_roundsim_schema.py   # 写 ui/src/generated/{scenariospec.schema.json,scenariospec.ts}

契约锁定:M4 起前端 TS 类型与 Python 真源由本工具同步;
tests/test_roundsim.py::test_ui_contract 断言仓库内生成文件与模型当前导出一致
(模型改动未重新导出 → 测试红,防前后端漂移)。
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.hif.roundsim.spec import ScenarioSpec  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "ui" / "src" / "generated"

_TS_TYPE = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
}


def _ts_interface(name: str, schema: dict) -> list[str]:
    """JSON Schema(本模型的扁平 subset:properties/required/$defs/anyOf(enum))→ TS interface 行。"""
    lines = [f"export interface {name} {{"]
    required = set(schema.get("required") or [])
    for key, prop in (schema.get("properties") or {}).items():
        ts_type = "unknown"
        if "$ref" in prop:
            ref_name = prop["$ref"].split("/")[-1]
            ts_type = ref_name
        elif "anyOf" in prop:
            parts = []
            for sub in prop["anyOf"]:
                if "enum" in sub:
                    parts.extend(json.dumps(v) for v in sub["enum"])
                elif "$ref" in sub:
                    parts.append(sub["$ref"].split("/")[-1])
                elif sub.get("type") in _TS_TYPE:
                    parts.append(_TS_TYPE[sub["type"]])
                elif sub.get("type") == "array":
                    parts.append("unknown[]")
                elif sub.get("type") == "object":
                    parts.append("Record<string, unknown>")
            ts_type = " | ".join(dict.fromkeys(parts)) or "unknown"
        elif prop.get("type") == "array":
            ts_type = "unknown[]"
        elif prop.get("type") == "object":
            ts_type = "Record<string, unknown>"
        elif prop.get("type") in _TS_TYPE:
            ts_type = _TS_TYPE[prop["type"]]
        marker = "" if key in required else "?"
        lines.append(f"    {key}{marker}: {ts_type};")
    lines.append("}")
    return lines


def export() -> tuple[str, str]:
    schema = ScenarioSpec.model_json_schema()
    defs = schema.get("$defs") or {}
    blocks: list[list[str]] = []
    for def_name, def_schema in defs.items():
        if def_schema.get("type") == "object" and "properties" in def_schema:
            blocks.append(_ts_interface(def_name, def_schema))
    blocks.append(_ts_interface("ScenarioSpec", schema))
    header = "// 由 tools/export_roundsim_schema.py 从 pydantic 模型生成——不要手改;改模型后重新导出。\n"
    return json.dumps(schema, ensure_ascii=False, indent=2), header + "\n\n".join("\n".join(b) for b in blocks) + "\n"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    schema_json, ts_text = export()
    (OUT_DIR / "scenariospec.schema.json").write_text(schema_json + "\n", encoding="utf-8")
    (OUT_DIR / "scenariospec.ts").write_text(ts_text, encoding="utf-8")
    print(f"导出: {OUT_DIR / 'scenariospec.ts'}(契约锁定见 tests/test_roundsim.py::test_ui_contract)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
