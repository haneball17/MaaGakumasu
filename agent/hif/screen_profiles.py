"""HIF 页面配置的加载、校验与离线文本回放。

配置来自已审阅的本战截图，运行时仍须依赖当前帧 OCR 进行确认。这里不产生
点击坐标，也不将离线截图视作执行级校准证据。
"""

from __future__ import annotations

import re
import json
from typing import Literal
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass

from agent.hif.runtime import HIF_FRAME_SIZE

ROI = tuple[int, int, int, int]
RiskLevel = Literal["read_only", "safe_continue", "stateful_choice", "resource_choice", "battle"]
_RISK_LEVELS: frozenset[str] = frozenset({"read_only", "safe_continue", "stateful_choice", "resource_choice", "battle"})


@dataclass(frozen=True, slots=True)
class HIFScreenAnchor:
    anchor_id: str
    pattern: str
    roi: ROI

    def matches(self, texts: tuple[str, ...]) -> bool:
        expression = re.compile(self.pattern)
        return any(expression.search(text) for text in texts)


@dataclass(frozen=True, slots=True)
class HIFScreenButton:
    button_id: str
    text: str
    roi: ROI


@dataclass(frozen=True, slots=True)
class HIFScreenProfile:
    screen_id: str
    risk: RiskLevel
    anchors: tuple[HIFScreenAnchor, ...]
    regions: dict[str, ROI]
    buttons: dict[str, HIFScreenButton]

    def matches(self, texts: tuple[str | None, ...]) -> bool:
        normalized = tuple(text.strip() for text in texts if isinstance(text, str) and text.strip())
        return bool(normalized) and all(anchor.matches(normalized) for anchor in self.anchors)


@dataclass(frozen=True, slots=True)
class HIFScreenProfiles:
    profile_id: str
    review_sections: tuple[str, ...]
    profiles: dict[str, HIFScreenProfile]

    def get(self, screen_id: str) -> HIFScreenProfile | None:
        return self.profiles.get(screen_id)

    def button_roi(self, screen_id: str, button_id: str) -> ROI | None:
        profile = self.get(screen_id)
        button = profile.buttons.get(button_id) if profile else None
        return button.roi if button else None

    def classify(self, texts: tuple[str | None, ...]) -> tuple[HIFScreenProfile, ...]:
        return tuple(profile for profile in self.profiles.values() if profile.matches(texts))


def default_hif_screen_profile_path() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "data" / "hif" / "screen_profiles" / "rinami_garakuta_road_20260709.json"


@lru_cache(maxsize=4)
def load_hif_screen_profiles(path: str | Path | None = None) -> HIFScreenProfiles:
    resolved = Path(path) if path is not None else default_hif_screen_profile_path()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"无效 HIF 页面配置: {resolved}")
    if payload.get("frame_size") != list(HIF_FRAME_SIZE):
        raise ValueError(f"HIF 页面配置截图尺寸不匹配: {resolved}")
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError(f"HIF 页面配置缺少 profile_id: {resolved}")

    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError(f"HIF 页面配置缺少 profiles: {resolved}")
    profiles: dict[str, HIFScreenProfile] = {}
    for raw in raw_profiles:
        profile = _parse_profile(raw)
        if profile.screen_id in profiles:
            raise ValueError(f"HIF 页面配置存在重复 screen_id: {profile.screen_id}")
        profiles[profile.screen_id] = profile

    review_sections = payload.get("review_sections", [])
    if not isinstance(review_sections, list) or not all(isinstance(item, str) and item for item in review_sections):
        raise ValueError(f"HIF 页面配置 review_sections 无效: {resolved}")
    return HIFScreenProfiles(profile_id=profile_id, review_sections=tuple(review_sections), profiles=profiles)


def _parse_profile(raw: object) -> HIFScreenProfile:
    if not isinstance(raw, dict):
        raise ValueError("HIF 页面配置 profile 必须是对象")
    screen_id = raw.get("screen_id")
    risk = raw.get("risk")
    if not isinstance(screen_id, str) or not screen_id:
        raise ValueError("HIF 页面配置 profile 缺少 screen_id")
    if risk not in _RISK_LEVELS:
        raise ValueError(f"HIF 页面配置 risk 无效: {screen_id}:{risk}")
    anchors = tuple(_parse_anchor(item, screen_id) for item in _expect_list(raw.get("anchors"), screen_id, "anchors"))
    if not anchors:
        raise ValueError(f"HIF 页面配置缺少 anchors: {screen_id}")
    regions = {
        name: _parse_roi(value, f"{screen_id}.regions.{name}")
        for name, value in _expect_dict(raw.get("regions", {}), screen_id, "regions").items()
        if isinstance(name, str) and name
    }
    if len(regions) != len(_expect_dict(raw.get("regions", {}), screen_id, "regions")):
        raise ValueError(f"HIF 页面配置 region 名称无效: {screen_id}")
    buttons: dict[str, HIFScreenButton] = {}
    for item in _expect_list(raw.get("buttons", []), screen_id, "buttons"):
        button = _parse_button(item, screen_id)
        if button.button_id in buttons:
            raise ValueError(f"HIF 页面配置重复按钮: {screen_id}.{button.button_id}")
        buttons[button.button_id] = button
    return HIFScreenProfile(screen_id=screen_id, risk=risk, anchors=anchors, regions=regions, buttons=buttons)


def _parse_anchor(raw: object, screen_id: str) -> HIFScreenAnchor:
    if not isinstance(raw, dict):
        raise ValueError(f"HIF 页面锚点无效: {screen_id}")
    anchor_id = raw.get("id")
    pattern = raw.get("pattern")
    if not isinstance(anchor_id, str) or not anchor_id or not isinstance(pattern, str) or not pattern:
        raise ValueError(f"HIF 页面锚点缺少 id/pattern: {screen_id}")
    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError(f"HIF 页面锚点正则无效: {screen_id}.{anchor_id}") from error
    return HIFScreenAnchor(anchor_id=anchor_id, pattern=pattern, roi=_parse_roi(raw.get("roi"), f"{screen_id}.anchors.{anchor_id}"))


def _parse_button(raw: object, screen_id: str) -> HIFScreenButton:
    if not isinstance(raw, dict):
        raise ValueError(f"HIF 页面按钮无效: {screen_id}")
    button_id = raw.get("id")
    text = raw.get("text")
    if not isinstance(button_id, str) or not button_id or not isinstance(text, str) or not text:
        raise ValueError(f"HIF 页面按钮缺少 id/text: {screen_id}")
    return HIFScreenButton(button_id=button_id, text=text, roi=_parse_roi(raw.get("roi"), f"{screen_id}.buttons.{button_id}"))


def _parse_roi(raw: object, label: str) -> ROI:
    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError(f"HIF ROI 无效: {label}")
    try:
        x, y, width, height = (int(value) for value in raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"HIF ROI 非整数: {label}") from error
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > HIF_FRAME_SIZE[0] or y + height > HIF_FRAME_SIZE[1]:
        raise ValueError(f"HIF ROI 越界: {label}")
    return x, y, width, height


def _expect_list(raw: object, screen_id: str, field: str) -> list[object]:
    if not isinstance(raw, list):
        raise ValueError(f"HIF 页面配置 {field} 无效: {screen_id}")
    return raw


def _expect_dict(raw: object, screen_id: str, field: str) -> dict[object, object]:
    if not isinstance(raw, dict):
        raise ValueError(f"HIF 页面配置 {field} 无效: {screen_id}")
    return raw
