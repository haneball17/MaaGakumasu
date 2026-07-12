"""HIF 本战准备页面的状态读取器。

本模块只负责把 OCR 文本转换为 ``HIFRuntimeState``，不做点击或策略判断。
ROI 来自 ``docs/hif/finals-daily-log.md`` 的 MuMu ``720x1280`` 实机记录；
无法读取的字段保留为 None，交由执行层安全停止。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol
from dataclasses import field, dataclass

from agent.hif.domain import HIFPhase, HIFRuntimeState
from agent.hif.observation import HIFPageObservation, observe_hif_page
from agent.hif.screen_profiles import load_hif_screen_profiles

if TYPE_CHECKING:
    from maa.context import Context


_FINALS_REGION_NAMES = {
    "remaining_day": "day",
    "health": "health",
    "p_points": "p_points",
    "attributes": "attributes",
}


class HIFStateOcrPort(Protocol):
    def read_ocr(self, name: str, roi: tuple[int, int, int, int]) -> str | None:
        """读取指定 HIF ROI 的 OCR 文本。"""


@dataclass(frozen=True, slots=True)
class HIFStateReading:
    state: HIFRuntimeState
    raw: dict[str, str] = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    page_observation: HIFPageObservation | None = None


def parse_health(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if not match:
        return None
    current, maximum = (int(value) for value in match.groups())
    if maximum <= 0 or current < 0 or current > maximum:
        return None
    return current, maximum


def parse_remaining_day(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"([1-6])\s*日", text)
    return int(match.group(1)) if match else None


def parse_p_points(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.search(r"\d+", text.replace(",", ""))
    return int(digits.group()) if digits else None


def parse_attributes(text: str | None) -> dict[str, int]:
    """从含标签的 OCR 文本提取 Vo/Da/Vi；无法可靠关联标签时不猜测。"""

    if not text:
        return {}
    attributes: dict[str, int] = {}
    for key, aliases in {
        "Vo": ("Vo", "ボーカル"),
        "Da": ("Da", "ダンス"),
        "Vi": ("Vi", "ビジュアル"),
    }.items():
        match = re.search(rf"(?:{'|'.join(aliases)})[^0-9]{{0,20}}(\d{{1,4}})", text, re.IGNORECASE)
        if match:
            attributes[key] = int(match.group(1))
    return attributes


class HIFStateReader:
    """读取 HIF 本战准备页的最小状态。"""

    def __init__(self, ocr: HIFStateOcrPort) -> None:
        self.ocr = ocr

    @classmethod
    def from_context(cls, context: "Context", image) -> "HIFStateReader":
        return cls(_MaafwHIFStateOcrAdapter(context, image))

    def read_finals_prepare_state(self) -> HIFStateReading:
        return self._read_state(HIFPhase.FINALS_PREPARE)

    def read_interval_state(self) -> HIFStateReading:
        """读取 Round1 与 Round2 之间 Interval 页的共享资源状态。"""

        return self._read_state(HIFPhase.INTERVAL)

    def _read_state(self, phase: HIFPhase) -> HIFStateReading:
        profiles = load_hif_screen_profiles()
        profile = profiles.get("finals_prepare")
        if profile is None:
            raise RuntimeError("HIF 页面配置缺少 finals_prepare")
        roi_by_key = {
            key: next(anchor.roi for anchor in profile.anchors if anchor.anchor_id == region_name)
            if key == "remaining_day"
            else profile.regions[region_name]
            for key, region_name in _FINALS_REGION_NAMES.items()
        }
        raw = {key: self.ocr.read_ocr(f"HIFState_{key}", roi) or "" for key, roi in roi_by_key.items()}
        screen_profile = profiles.get("finals_prepare" if phase is HIFPhase.FINALS_PREPARE else "interval_shop")
        if screen_profile is None:
            raise RuntimeError(f"HIF 页面配置缺少阶段页面: {phase.value}")
        anchor_texts = [
            self.ocr.read_ocr(f"HIFPageAnchor_{phase.value}_{anchor.anchor_id}", anchor.roi) or ""
            for anchor in screen_profile.anchors
        ]
        health = parse_health(raw["health"])
        day_remaining = parse_remaining_day(raw["remaining_day"])
        p_points = parse_p_points(raw["p_points"])
        required_fields = ["health", "p_points"]
        if phase is HIFPhase.FINALS_PREPARE:
            required_fields.insert(1, "remaining_day")
        values_are_missing = {
            "health": health is None,
            "remaining_day": day_remaining is None,
            "p_points": p_points is None,
        }
        missing = [field_name for field_name in required_fields if values_are_missing[field_name]]
        state = HIFRuntimeState(
            phase=phase,
            day_remaining=day_remaining,
            stamina=health[0] if health else None,
            max_stamina=health[1] if health else None,
            p_points=p_points,
            attributes=parse_attributes(raw["attributes"]),
            screen_confidence=round((len(required_fields) - len(missing)) / len(required_fields), 2),
        )
        return HIFStateReading(
            state=state,
            raw=raw,
            missing_fields=tuple(missing),
            page_observation=observe_hif_page([*raw.values(), *anchor_texts], profiles),
        )


class _MaafwHIFStateOcrAdapter:
    """将 MaaFramework Context 适配为纯逻辑读取端口。"""

    def __init__(self, context: "Context", image) -> None:
        self.context = context
        self.image = image

    def read_ocr(self, name: str, roi: tuple[int, int, int, int]) -> str | None:
        detail = self.context.run_recognition(
            name,
            self.image,
            pipeline_override={
                name: {
                    "recognition": "OCR",
                    "expected": [],
                    "roi": list(roi),
                }
            },
        )
        if detail and detail.hit:
            return detail.best_result.text
        return None
