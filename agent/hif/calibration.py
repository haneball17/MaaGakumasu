"""HIF 识别 ROI 的版本化校准文件读取器。"""

from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass

from agent.hif.runtime import HIF_FRAME_SIZE

ROI = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class HIFRoiCalibration:
    """仅接受与 HIF 模板一致的 ``720x1280`` ROI 校准。"""

    schema_version: int
    frame_size: tuple[int, int]
    exam_numeric: dict[str, ROI]
    round_metrics: dict[str, ROI]
    round_metrics_panel: dict[str, ROI]
    settlement_metrics: dict[str, ROI]
    updated_at: str
    source: str
    device_id: str = ""
    controller_kind: str = ""
    game_version: str = ""
    locale: str = ""
    evidence_sha256: str = ""

    def roi_for_exam_numeric(self, name: str) -> ROI | None:
        return self.exam_numeric.get(name)

    def roi_for_round_metric(self, name: str) -> ROI | None:
        return self.round_metrics.get(name)

    def roi_for_round_metric_panel(self, name: str) -> ROI | None:
        return self.round_metrics_panel.get(name)

    def roi_for_settlement_metric(self, name: str) -> ROI | None:
        return self.settlement_metrics.get(name)

    @property
    def is_exam_execution_ready(self) -> bool:
        """只有全部出牌必需数值均有同一份可追溯校准时才允许自动执行。"""

        required = {"good_condition", "reprise", "focus", "turn", "flow", "deck_size", "stamina"}
        return bool(self.device_id and self.evidence_sha256 and required.issubset(self.exam_numeric))

    def supports_exam_fields(self, required: set[str]) -> bool:
        """确认一组直接画面读数字段来自同一份可追溯校准。"""

        return bool(self.device_id and self.evidence_sha256 and required.issubset(self.exam_numeric))


def default_calibration_path() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "data" / "hif" / "roi_calibration.json"


@lru_cache(maxsize=4)
def load_hif_roi_calibration(path: str | Path | None = None) -> HIFRoiCalibration:
    """读取校准；未校准字段保持缺失，绝不以估算坐标替代。"""

    resolved = Path(path) if path is not None else default_calibration_path()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"无效 HIF ROI 校准文件: {resolved}")
    frame_size = _parse_frame_size(payload.get("frame_size"))
    if frame_size != HIF_FRAME_SIZE:
        raise ValueError(f"HIF ROI 校准必须基于 {HIF_FRAME_SIZE}，当前为 {frame_size}")
    regions = _parse_region_map(payload.get("exam_numeric", {}), "exam_numeric")
    round_metrics = _parse_region_map(payload.get("round_metrics", {}), "round_metrics")
    round_metrics_panel = _parse_region_map(payload.get("round_metrics_panel", {}), "round_metrics_panel")
    settlement_metrics = _parse_region_map(payload.get("settlement_metrics", {}), "settlement_metrics")
    return HIFRoiCalibration(
        schema_version=1,
        frame_size=frame_size,
        exam_numeric=regions,
        round_metrics=round_metrics,
        round_metrics_panel=round_metrics_panel,
        settlement_metrics=settlement_metrics,
        updated_at=str(payload.get("updated_at", "")),
        source=str(payload.get("source", "")),
        device_id=str(payload.get("device_id", "")),
        controller_kind=str(payload.get("controller_kind", "")),
        game_version=str(payload.get("game_version", "")),
        locale=str(payload.get("locale", "")),
        evidence_sha256=str(payload.get("evidence_sha256", "")),
    )


def _parse_region_map(raw_regions: object, name: str) -> dict[str, ROI]:
    if not isinstance(raw_regions, dict):
        raise ValueError(f"HIF ROI {name} 必须为对象")
    return {
        key: roi
        for key, raw in raw_regions.items()
        if isinstance(key, str) and (roi := _parse_roi(raw)) is not None
    }


def _parse_frame_size(raw: object) -> tuple[int, int]:
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError("HIF ROI frame_size 必须为 [width, height]")
    try:
        width, height = int(raw[0]), int(raw[1])
    except (TypeError, ValueError) as error:
        raise ValueError("HIF ROI frame_size 必须为整数") from error
    return width, height


def _parse_roi(raw: object) -> ROI | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError("HIF ROI 必须为 [x, y, width, height] 或 null")
    try:
        x, y, width, height = (int(value) for value in raw)
    except (TypeError, ValueError) as error:
        raise ValueError("HIF ROI 坐标必须为整数") from error
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > HIF_FRAME_SIZE[0] or y + height > HIF_FRAME_SIZE[1]:
        raise ValueError(f"HIF ROI 超出截图范围: {raw}")
    return x, y, width, height
