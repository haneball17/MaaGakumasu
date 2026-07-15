"""确定性的 JSON/JSONL 读写。"""

from __future__ import annotations

import os
import json
import hashlib
import tempfile
from typing import Any
from pathlib import Path
from collections.abc import Iterable


def canonical_json_text(value: Any, *, trailing_newline: bool = True) -> str:
    """返回稳定键序、UTF-8 友好的规范 JSON 文本。"""

    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return f"{text}\n" if trailing_newline else text


def canonical_json_bytes(value: Any, *, trailing_newline: bool = True) -> bytes:
    return canonical_json_text(value, trailing_newline=trailing_newline).encode("utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any) -> None:
    _atomic_write(Path(path), canonical_json_bytes(value))


def read_jsonl(path: str | Path) -> list[Any]:
    records: list[Any] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: 非法 JSONL") from exc
    return records


def write_jsonl(path: str | Path, records: Iterable[Any], *, sort: bool = True) -> None:
    """写入一行一条的规范 JSON；默认按完整规范行排序。"""

    lines = [json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) for record in records]
    if sort:
        lines.sort()
    payload = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
    _atomic_write(Path(path), payload)


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
