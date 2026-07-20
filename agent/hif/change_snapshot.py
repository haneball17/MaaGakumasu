"""Day1 变卡测试的可审计快照读写。"""

from __future__ import annotations

import json
from typing import Any
from pathlib import Path

SNAPSHOT_VERSION = 1
_REQUIRED_FIELDS = frozenset(
    {
        "version",
        "session_id",
        "stage",
        "candidates",
        "source_instances",
        "missing_slots",
        "deck_complete",
        "reroll_count",
        "decision",
        "evidence_frames",
        "updated_at",
    }
)


def snapshot_path(snapshot_dir: Path, session_id: str) -> Path:
    """返回一个 session 的固定快照位置，不接受路径片段。"""

    if not session_id or Path(session_id).name != session_id:
        raise ValueError("session_id 非法")
    return snapshot_dir / f"{session_id}.json"


def write_change_snapshot(snapshot_dir: Path, payload: dict[str, Any]) -> Path:
    """先写临时文件再原子替换，避免半写入快照成为恢复依据。"""

    missing = _REQUIRED_FIELDS.difference(payload)
    if missing:
        raise ValueError(f"快照缺少字段: {','.join(sorted(missing))}")
    if payload["version"] != SNAPSHOT_VERSION or not isinstance(payload["session_id"], str):
        raise ValueError("快照版本或 session_id 非法")

    target = snapshot_path(snapshot_dir, payload["session_id"])
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def load_change_snapshot(snapshot_dir: Path, resume_session_id: str) -> dict[str, Any]:
    """只读取显式指定的 session；调用方仍须重新验证页面与目标预览。"""

    target = snapshot_path(snapshot_dir, resume_session_id)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"快照不可读: {error}") from error
    if not isinstance(payload, dict) or _REQUIRED_FIELDS.difference(payload):
        raise ValueError("快照字段不完整")
    if payload.get("version") != SNAPSHOT_VERSION or payload.get("session_id") != resume_session_id:
        raise ValueError("快照 session 或版本不匹配")
    return payload
