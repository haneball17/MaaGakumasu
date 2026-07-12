"""从已观察 HIF 案例加载页面按钮与 ROI 证据。"""

from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass

from agent.hif.runtime import HIF_FRAME_SIZE
from agent.hif.screen_profiles import load_hif_screen_profiles

ROI = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class HIFUiButton:
    screen_state: str
    button_id: str
    text: str
    roi: ROI


@dataclass(frozen=True, slots=True)
class HIFUiMap:
    buttons: dict[tuple[str, str], HIFUiButton]
    source_case_id: str

    def button_roi(self, screen_state: str, button_id: str) -> ROI | None:
        button = self.buttons.get((screen_state, button_id))
        return button.roi if button else None


def default_observed_case_path() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "data" / "hif" / "observed_cases" / "rinami_garakuta_road_20260709.json"


@lru_cache(maxsize=4)
def load_hif_ui_map(path: str | Path | None = None) -> HIFUiMap:
    """合并已观察案例与已审阅页面配置中的按钮证据。"""

    resolved = Path(path) if path is not None else default_observed_case_path()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("case_id"), str):
        raise ValueError(f"无效 HIF 已观察案例: {resolved}")
    buttons: dict[tuple[str, str], HIFUiButton] = {}
    profiles = load_hif_screen_profiles()
    for profile in profiles.profiles.values():
        for button in profile.buttons.values():
            key = (profile.screen_id, button.button_id)
            buttons[key] = HIFUiButton(
                screen_state=profile.screen_id,
                button_id=button.button_id,
                text=button.text,
                roi=button.roi,
            )
    for hint in payload.get("recognition_hints", []):
        if not isinstance(hint, dict):
            continue
        screen_state = hint.get("screen_state")
        if not isinstance(screen_state, str) or not screen_state:
            continue
        for raw_button in hint.get("buttons", []):
            button = _parse_button(screen_state, raw_button)
            if button is None:
                continue
            key = (button.screen_state, button.button_id)
            existing = buttons.get(key)
            if existing is not None and (existing.text != button.text or existing.roi != button.roi):
                raise ValueError(f"HIF 按钮证据冲突: {key}")
            buttons[key] = button
    return HIFUiMap(buttons=buttons, source_case_id=payload["case_id"])


def _parse_button(screen_state: str, raw: object) -> HIFUiButton | None:
    if not isinstance(raw, dict):
        return None
    button_id = raw.get("id")
    text = raw.get("text")
    if not isinstance(button_id, str) or not button_id or not isinstance(text, str):
        return None
    roi = _parse_roi(raw.get("roi"))
    return HIFUiButton(screen_state=screen_state, button_id=button_id, text=text, roi=roi) if roi else None


def _parse_roi(raw: object) -> ROI | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        x, y, width, height = (int(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > HIF_FRAME_SIZE[0] or y + height > HIF_FRAME_SIZE[1]:
        return None
    return x, y, width, height
