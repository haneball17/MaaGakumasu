"""HIF 页面文本信号的纯分类器。

Maa Pipeline 仍承担具体模板/OCR 节点；本模块用于日志、离线截图回放和
Custom Action 的后验检查。它宁可返回 ``UNKNOWN``，也不会用宽泛“本战”
字符串把本战准备页错分到战斗页。
"""

from __future__ import annotations

import re
from enum import StrEnum
from dataclasses import dataclass
from collections.abc import Iterable


class HIFScreenState(StrEnum):
    UNKNOWN = "unknown"
    SELECTION_MODE = "selection_mode"
    FINALS_MODE = "finals_mode"
    FINALS_PREPARE = "finals_prepare"
    ROUND1 = "round1"
    ROUND2 = "round2"
    INTERVAL = "interval"
    DRINK_OVERFLOW = "drink_overflow"
    SETTLEMENT = "settlement"
    LIVE = "live"
    MEMORY_PHOTO_SELECT = "memory_photo_select"
    MEMORY_PHOTO_CONFIRM = "memory_photo_confirm"
    MEMORY_GENERATE = "memory_generate"
    MEMORY_PREVIEW = "memory_preview"


@dataclass(frozen=True, slots=True)
class HIFScreenObservation:
    state: HIFScreenState
    confidence: float
    matched_states: tuple[HIFScreenState, ...] = ()

    @property
    def is_known(self) -> bool:
        return self.state is not HIFScreenState.UNKNOWN


_SCREEN_PATTERNS: tuple[tuple[HIFScreenState, re.Pattern[str]], ...] = (
    (HIFScreenState.SELECTION_MODE, re.compile(r"選抜試験モード")),
    (HIFScreenState.FINALS_MODE, re.compile(r"本戦モード")),
    (HIFScreenState.FINALS_PREPARE, re.compile(r"H\.?I\.?F\s*本戦まで\s*[1-6]日", re.IGNORECASE)),
    (HIFScreenState.ROUND1, re.compile(r"(?:ROUND|Round|1st)\s*1|1st\s*Round")),
    (HIFScreenState.ROUND2, re.compile(r"(?:ROUND|Round|2nd)\s*2|2nd\s*Round")),
    (HIFScreenState.INTERVAL, re.compile(r"インターバル")),
    (HIFScreenState.DRINK_OVERFLOW, re.compile(r"Pドリンク所持上限")),
    (HIFScreenState.SETTLEMENT, re.compile(r"優勝")),
    (HIFScreenState.LIVE, re.compile(r"歌詞OFF")),
    (HIFScreenState.MEMORY_PHOTO_SELECT, re.compile(r"メモリーにするフォトを選んでください")),
    (HIFScreenState.MEMORY_PHOTO_CONFIRM, re.compile(r"選択したフォトをメモリーとして保存しますか")),
    (HIFScreenState.MEMORY_GENERATE, re.compile(r"\bMEMORY\b|メモリーを生成")),
    (HIFScreenState.MEMORY_PREVIEW, re.compile(r"H\.?I\.?F専用")),
)


def classify_hif_screen(texts: Iterable[str | None]) -> HIFScreenObservation:
    """从已获得的 OCR 文本分类页面；多种强信号并存时安全地返回未知。"""

    normalized = "\n".join(text.strip() for text in texts if isinstance(text, str) and text.strip())
    matched = tuple(state for state, pattern in _SCREEN_PATTERNS if pattern.search(normalized))
    if len(matched) == 1:
        return HIFScreenObservation(matched[0], 1.0, matched)
    return HIFScreenObservation(HIFScreenState.UNKNOWN, 0.0, matched)
