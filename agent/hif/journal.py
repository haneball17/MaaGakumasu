"""HIF 实机动作的可审计 Journal。

HIF 是长流程且含资源消耗的自动化。本模块把每个决策、点击和验证结果写入
``debug/hif-journal``，供实机复盘使用。写日志或保存截图失败不得改变游戏
动作的安全语义，因此所有持久化错误都会被吞掉并留给调用者记录警告。
"""

from __future__ import annotations

import os
import json
import hashlib
from enum import Enum
from typing import Any
from pathlib import Path
from datetime import datetime
from dataclasses import asdict, dataclass, is_dataclass
from collections.abc import Mapping, Callable

from agent.hif.runtime import get_image_size
from agent.hif.image_io import save_hif_image


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2] / "debug" / "hif-journal"


@dataclass(frozen=True, slots=True)
class HIFFrameEvidence:
    """截图的最小可复核证据。

    ``image_path`` 仅在截图对象可安全转为 PNG 时存在；MaaFramework 的某些
    绑定对象不暴露像素数据，此时仍保留尺寸、类型和指纹可用性，绝不伪造图像。
    """

    frame_id: str
    width: int | None
    height: int | None
    fingerprint: str | None
    image_path: str | None
    image_type: str


@dataclass(frozen=True, slots=True)
class HIFJournalEntry:
    """一条决策或执行记录。"""

    timestamp: str
    session_id: str
    screen_state: str
    event: str
    outcome: str
    details: dict[str, Any]
    before: HIFFrameEvidence | None = None
    after: HIFFrameEvidence | None = None


@dataclass(frozen=True, slots=True)
class HIFJournalAudit:
    """对一次 HIF Journal 的离线可复核性审计结果。"""

    entry_count: int
    verified_execution_count: int
    failures: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failures


class HIFJournal:
    """追加式 JSONL Journal；可注入目录以便单测。"""

    def __init__(
        self,
        root: Path | None = None,
        session_id: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root or _default_root()
        self._now = now or datetime.now
        created_at = self._now()
        self.session_id = session_id or f"{created_at:%Y%m%dT%H%M%S}-{os.getpid()}"
        self._sequence = 0

    @property
    def path(self) -> Path:
        return self.root / f"{self.session_id}.jsonl"

    def capture(self, image: Any, label: str) -> HIFFrameEvidence:
        """记录一帧的尺寸、指纹，并在支持时保存 PNG。"""

        self._sequence += 1
        frame_id = f"{self.session_id}-{self._sequence:04d}-{_safe_label(label)}"
        size = get_image_size(image)
        image_path = self._save_image(image, frame_id)
        fingerprint = _fingerprint(image)
        if fingerprint is None and image_path is not None:
            fingerprint = _file_fingerprint(self.root / image_path)
        return HIFFrameEvidence(
            frame_id=frame_id,
            width=size[0] if size else None,
            height=size[1] if size else None,
            fingerprint=fingerprint,
            image_path=image_path,
            image_type=type(image).__name__,
        )

    def record(
        self,
        screen_state: str,
        event: str,
        outcome: str,
        *,
        details: Mapping[str, Any] | None = None,
        before: HIFFrameEvidence | None = None,
        after: HIFFrameEvidence | None = None,
    ) -> HIFJournalEntry:
        """写入一条 JSONL 记录，并始终返回可供日志输出的领域对象。"""

        entry = HIFJournalEntry(
            timestamp=self._now().isoformat(timespec="milliseconds"),
            session_id=self.session_id,
            screen_state=screen_state,
            event=event,
            outcome=outcome,
            details=_json_safe(dict(details or {})),
            before=before,
            after=after,
        )
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(json.dumps(_json_safe(asdict(entry)), ensure_ascii=False, sort_keys=True))
                file.write("\n")
        except OSError:
            # Journal 是调试证据，不应因为磁盘不可写而允许调用者绕过安全停止。
            pass
        return entry

    def _save_image(self, image: Any, frame_id: str) -> str | None:
        path = self.root / f"{frame_id}.png"
        try:
            save = getattr(image, "save", None)
            if callable(save):
                self.root.mkdir(parents=True, exist_ok=True)
                save(path)
                return path.name

            shape = getattr(image, "shape", None)
            if isinstance(shape, tuple) and len(shape) >= 2:
                save_hif_image(image, path)
                return path.name
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            return None
        return None


def frame_changed(before: HIFFrameEvidence | None, after: HIFFrameEvidence | None) -> bool:
    """仅在两帧都有不同可比较指纹时确认点击后的页面变化。"""

    return bool(before and after and before.fingerprint and after.fingerprint and before.fingerprint != after.fingerprint)


def load_hif_journal(path: str | Path) -> tuple[HIFJournalEntry, ...]:
    """读取已落盘的 JSONL Journal；畸形记录不能被悄悄忽略。"""

    resolved = Path(path)
    entries: list[HIFJournalEntry] = []
    for line_number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            entries.append(_entry_from_payload(payload))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"无效 HIF Journal 记录: {resolved}:{line_number}") from error
    return tuple(entries)


def audit_hif_journal(entries: tuple[HIFJournalEntry, ...] | list[HIFJournalEntry]) -> HIFJournalAudit:
    """核验已声明成功的执行动作是否具备可比较的前后帧证据。"""

    failures: list[str] = []
    verified_execution_count = 0
    for index, entry in enumerate(entries, start=1):
        if entry.outcome != "verified":
            continue
        verified_execution_count += 1
        if not frame_changed(entry.before, entry.after):
            failures.append(f"entry#{index}:{entry.screen_state}/{entry.event}:verified_without_changed_frame")
    return HIFJournalAudit(len(entries), verified_execution_count, tuple(failures))


_RUNTIME_JOURNAL: HIFJournal | None = None


def get_runtime_hif_journal() -> HIFJournal:
    """返回当前 Python 进程共享的 HIF Journal。"""

    global _RUNTIME_JOURNAL
    if _RUNTIME_JOURNAL is None:
        _RUNTIME_JOURNAL = HIFJournal()
    return _RUNTIME_JOURNAL


def _fingerprint(image: Any) -> str | None:
    if image is None:
        return None
    if isinstance(image, (bytes, bytearray, memoryview)):
        payload = bytes(image)
    else:
        tobytes = getattr(image, "tobytes", None)
        if not callable(tobytes):
            return None
        try:
            payload = bytes(tobytes())
        except (AttributeError, TypeError, ValueError):
            return None
    if not payload:
        return None
    return hashlib.sha256(payload).hexdigest()[:16]


def _file_fingerprint(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def _safe_label(label: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in label)[:64] or "frame"


def _entry_from_payload(payload: object) -> HIFJournalEntry:
    if not isinstance(payload, dict):
        raise ValueError("Journal entry must be an object")
    details = payload.get("details", {})
    if not isinstance(details, dict):
        raise ValueError("Journal details must be an object")
    return HIFJournalEntry(
        timestamp=str(payload["timestamp"]),
        session_id=str(payload["session_id"]),
        screen_state=str(payload["screen_state"]),
        event=str(payload["event"]),
        outcome=str(payload["outcome"]),
        details=details,
        before=_frame_from_payload(payload.get("before")),
        after=_frame_from_payload(payload.get("after")),
    )


def _frame_from_payload(payload: object) -> HIFFrameEvidence | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Journal frame must be an object or null")
    width = payload.get("width")
    height = payload.get("height")
    return HIFFrameEvidence(
        frame_id=str(payload["frame_id"]),
        width=int(width) if width is not None else None,
        height=int(height) if height is not None else None,
        fingerprint=str(payload["fingerprint"]) if payload.get("fingerprint") is not None else None,
        image_path=str(payload["image_path"]) if payload.get("image_path") is not None else None,
        image_type=str(payload["image_type"]),
    )


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
