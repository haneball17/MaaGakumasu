"""出牌状态适配层（ExamStateReader）：把画面像素翻译成 ExamState。

决策大脑（agent/hif/decisions/play.py）吃 ExamState 吐 CardAction，
但 ExamState 的 16 个字段在画面上散落各处，需要本适配层从画面读出。

设计要点（可测试性）：
- 纯逻辑组装函数（build_hand_summary / build_exam_state）与 maafw Context 调用分离
- 纯函数只吃 dataclass/原生类型，可离线单测（mock YOLO/OCR 返回值）
- maafw 调用（read_hand / read_numerics / read_exam_state）依赖 Context，需实机

识别管线（路线甲：YOLO 定位 + OCR 读名 + 查表）：
  1. ProduceRecognitionCards (YOLO cards.onnx) → 每张手牌的 box + label
  2. 对每个 box 跑 OCR 读卡名（expected 词典约束候选集）
  3. 查 hand_meta / card_dict → 组装 HandSummary
  4. OCR 读数值字段（好调/再演/集中/回合/流/山札，ROI 坐标 Step3 实机校准）
  5. 组装 ExamState → 喂给决策大脑

注：数值字段由 ``assets/data/hif/roi_calibration.json`` 管理；
    未校准字段保留零 ROI，读取器会显式跳过。
"""

from __future__ import annotations

import time
from enum import Enum
from typing import TYPE_CHECKING, Protocol
from dataclasses import dataclass

from agent.hif.calibration import load_hif_roi_calibration
from agent.hif.round_metrics import RoundMetrics, MetricIssueCode, build_round_metrics
from agent.hif.decisions.state import ExamRound, ExamState, HandSummary
from agent.hif.adapters.card_dict import (
    normalize_card_name,
    build_card_name_dict,
    is_good_condition_card,
)

if TYPE_CHECKING:
    from maa.context import Context

# ---------------------------------------------------------------------------
# 数值字段 ROI（由版本化实机校准文件加载）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumericROI:
    """单个数值字段在画面上的 ROI 区域 [x, y, w, h]（Step3 实机校准）。"""

    name: str
    roi: tuple[int, int, int, int]


_NUMERIC_LABELS = {
    "good_condition": "好调ターン数",
    "reprise": "再演次数",
    "focus": "集中值",
    "turn": "回合计数",
    "flow": "当前流 Vo/Da/Vi",
    "deck_size": "山札张数",
    "p_drinks": "持有Pドリンク",
    "stamina": "体力",
}

_NUMERIC_EXPECTED = {
    "flow": [".*(?:Vo|Da|Vi|ボーカル|ダンス|ビジュアル).*"],
    "p_drinks": [],
}

_ROUND_METRIC_LABELS = {
    "param_vo": "Vo参数",
    "param_da": "Da参数",
    "param_vi": "Vi参数",
    "current_score": "局内实时分数",
    "stage_multiplier": "当前审查倍率",
}

_TURN_DIGIT_TEMPLATES = {
    6: "produce/HIF/turn_digits/6.png",
    7: "produce/HIF/turn_digits/7.png",
    8: "produce/HIF/turn_digits/8.png",
    9: "produce/HIF/turn_digits/9.png",
}
_TURN_DIGIT_ROI = (13, 43, 120, 128)
_TURN_DIGIT_MIN_CONFIDENCE = 0.95


def _load_numeric_roi() -> dict[str, tuple[NumericROI, ...]]:
    """仅加载实机已校准字段；其余使用零 ROI 并由读取器跳过。"""

    calibration = load_hif_roi_calibration()
    return {
        key: tuple(NumericROI(label, roi) for roi in calibration.rois_for_exam_numeric(key))
        for key, label in _NUMERIC_LABELS.items()
    }


_NUMERIC_ROI = _load_numeric_roi()


def _load_round_metric_roi() -> dict[str, NumericROI]:
    calibration = load_hif_roi_calibration()
    return {
        key: NumericROI(label, calibration.roi_for_round_metric(key) or (0, 0, 0, 0))
        for key, label in _ROUND_METRIC_LABELS.items()
    }


_ROUND_METRIC_ROI = _load_round_metric_roi()


# ---------------------------------------------------------------------------
# maafw 返回值的本地抽象（让纯逻辑可单测，不依赖 maa 类型）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CardDetection:
    """单张手牌的 YOLO 检测结果（maafw NeuralNetworkDetect 输出的本地映射）。

    label 为 cards/suggestions/useless 之一；
    box 为 [x, y, w, h]；card_name 由后续 OCR 填充（初始为空）。
    """

    label: str
    box: tuple[int, int, int, int]
    card_name: str = ""
    raw_card_name: str = ""
    confidence: float = 0.0
    card_name_confidence: float = 0.0
    suppressed_reason: str = ""
    playable: bool | None = None
    playability_gray_ratio: float | None = None
    playability_source: str = ""


def infer_card_playability(image, detections: list[CardDetection]) -> None:
    """以当前原始帧的卡面饱和度保守区分灰卡、彩色卡与不确定卡。

    阈值来自 2026-07-15 同一停点六张零输入原始帧：灰色 ``眠気`` 的低饱和
    像素占比稳定为 0.657，三张彩色卡为 0.166～0.277。中间区间保持
    ``None``，不能因 YOLO 的 ``cards`` 标签自动取得执行权。
    """

    height, width = image.shape[:2]
    for detection in detections:
        if detection.suppressed_reason:
            continue
        if detection.label == "useless":
            detection.playable = False
            detection.playability_source = "yolo_useless"
            continue
        x, y, box_width, box_height = detection.box
        left = max(0, x + 15)
        right = min(width, x + box_width - 15)
        top = max(0, y + 15)
        bottom = min(height, y + int(box_height * 0.62))
        if left >= right or top >= bottom:
            continue
        crop = image[top:bottom, left:right, :3].astype("float32")
        maximum = crop.max(axis=2)
        minimum = crop.min(axis=2)
        low_saturation = (maximum == 0) | ((maximum - minimum) * 255 < maximum * 35)
        gray_ratio = float(low_saturation.mean())
        detection.playability_gray_ratio = gray_ratio
        detection.playability_source = "frame_saturation"
        if gray_ratio >= 0.55:
            detection.playable = False
        elif gray_ratio <= 0.35:
            detection.playable = True
        else:
            detection.playable = None


class ReadStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    CONFLICT = "conflict"


@dataclass(slots=True)
class NumericRead:
    """单个数值字段的 OCR 读取结果。

    value 为解析出的整数值（流字段为字符串 Vo/Da/Vi，存 raw）；
    raw 为 OCR 原始文本，便于调试。
    """

    name: str
    raw: str
    value: int | None
    flow: str | None = None  # 仅 flow 字段使用
    status: ReadStatus | None = None
    samples: tuple[str, ...] = ()
    confidence: float = 0.0
    confidences: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.status is None:
            self.status = ReadStatus.OK if self.value is not None or self.flow is not None else ReadStatus.MISSING


def _consensus_numeric_reads(key: str, reads: tuple[NumericRead, ...]) -> NumericRead:
    """多个独立 ROI 至少两个同值才接受；单 ROI 仍使用其内部三读结果。"""

    if len(reads) == 1:
        return reads[0]
    values = tuple(read.flow if key == "flow" else read.value for read in reads)
    candidates = {value for value in values if value is not None}
    winner = next((value for value in candidates if values.count(value) >= 2), None)
    samples = tuple(sample for read in reads for sample in (read.samples or (read.raw,)))
    if winner is None:
        status = (
            ReadStatus.CONFLICT
            if len(candidates) > 1 or any(read.status is ReadStatus.CONFLICT for read in reads)
            else ReadStatus.MISSING
        )
        return NumericRead(
            key,
            "",
            None,
            status=status,
            samples=samples,
            confidence=max((read.confidence for read in reads), default=0.0),
            confidences=tuple(read.confidence for read in reads),
        )
    accepted = next(read for read, value in zip(reads, values, strict=True) if value == winner)
    return NumericRead(
        key,
        accepted.raw,
        accepted.value,
        accepted.flow,
        ReadStatus.OK,
        samples,
        accepted.confidence,
        tuple(read.confidence for read in reads),
    )


@dataclass(slots=True)
class ExamStateObservation:
    """一次出牌画面的完整读取结果。

    ``ExamState`` 为兼容既有策略仍会对缺失值给出零值兜底，但自动点击必须
    检查 ``missing_fields``。这使影子模式可继续产出建议，而执行模式不会把
    未校准的 ROI 当作真实数值。
    """

    state: ExamState | None
    detections: list[CardDetection]
    numerics: dict[str, NumericRead]
    round_metrics: RoundMetrics
    missing_fields: tuple[str, ...]
    screen_confidence: float
    issues: tuple["ExamStateIssue", ...] = ()
    grey_cards: tuple[str, ...] = ()
    unresolved_playability: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExamStateIssue:
    field: str
    code: ReadStatus
    detail: str = ""


class ExamStateRejected(ValueError):
    """必需状态缺失或冲突，禁止构造带默认值的决策输入。"""

    def __init__(self, issues: tuple[ExamStateIssue, ...]) -> None:
        self.issues = issues
        super().__init__(", ".join(f"{issue.field}:{issue.code.value}" for issue in issues))


def _hand_card_name_roi(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """返回实机卡牌底部标题栏 ROI；保留足够上下留白供 OCR 检测。"""

    x, y, width, height = box
    top_offset = int(height * 0.68)
    if width < 160:
        # 五张手牌会压缩到约 140px 宽；沿用宽卡的横向扩展会吞入相邻标题，
        # 使 OCR 得到空名或拼接名。窄框只读自身可见标题带。
        return x, y + top_offset, width, max(1, height - top_offset)
    padded_x = max(0, x - 20)
    padded_width = min(720 - padded_x, width + 40)
    return padded_x, y + top_offset, padded_width, max(1, height - top_offset)


def _suppress_overlapping_card_detections(detections: list[CardDetection]) -> None:
    """标记被高置信卡框覆盖的窄重复框，同时保留原始检测证据。"""

    accepted: list[CardDetection] = []
    for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
        if detection.suppressed_reason:
            continue
        x, y, width, height = detection.box
        area = width * height
        if area <= 0:
            detection.suppressed_reason = "invalid_box"
            continue
        duplicate = False
        for existing in accepted:
            ex, ey, ew, eh = existing.box
            overlap_width = max(0, min(x + width, ex + ew) - max(x, ex))
            overlap_height = max(0, min(y + height, ey + eh) - max(y, ey))
            if overlap_width * overlap_height / area >= 0.45:
                duplicate = True
                break
        if duplicate:
            detection.suppressed_reason = "overlap_duplicate"
        else:
            accepted.append(detection)


_CARD_EXECUTION_NUMERICS = (
    "good_condition",
    "reprise",
    "focus",
    "turn",
    "flow",
    "deck_size",
)


class OcrPort(Protocol):
    """maafw Context 的 OCR 能力抽象（纯逻辑层依赖此协议，不依赖 maa.Context）。

    让单测可注入 mock 实现；实机时由 _MaafwOcrAdapter 包装真实 Context。
    """

    def run_ocr(self, name: str, expected: list[str], roi: tuple[int, int, int, int]) -> str | None:
        """对指定 ROI 跑 OCR，返回命中文本或 None。"""
        ...

    def run_yolo_cards(self) -> list[CardDetection]:
        """跑 ProduceRecognitionCards(YOLO)，返回每张手牌的检测框。"""
        ...


# ---------------------------------------------------------------------------
# 纯逻辑组装函数（可单测，零 maafw 依赖）
# ---------------------------------------------------------------------------


def build_hand_summary(detections: list[CardDetection]) -> HandSummary:
    """从 YOLO 检测 + OCR 卡名组装 HandSummary（纯逻辑，可单测）。

    判定逻辑：
    - has_shizen/has_oneesan/has_kokuminteki：检测中是否有对应卡名（OCR 已读出）
    - good_condition_card_count：label=suggestions 的数量 + 命中好调卡名的数量
    - draw_available/swap_hand_available：当前未识别（留 False，待实机补按钮识别）
    """
    active = [detection for detection in detections if not detection.suppressed_reason]
    card_names = [normalize_card_name(d.card_name) for d in active if d.card_name]
    has_shizen = "自然体の魅力" in card_names
    has_oneesan = "お姉さんの感覚" in card_names
    has_kokuminteki = "国民的アイドル" in card_names

    # 好调卡计数：YOLO suggestions 标签 + OCR 命中的好调卡名（去重避免双计）
    suggestion_count = sum(1 for d in active if d.label == "suggestions")
    ocr_good_count = sum(1 for n in set(card_names) if is_good_condition_card(n))
    good_count = max(suggestion_count, ocr_good_count)

    return HandSummary(
        has_shizen_no_miryoku=has_shizen,
        has_oneesan_no_kankaku=has_oneesan,
        has_kokuminteki_idol=has_kokuminteki,
        good_condition_card_count=good_count,
        # draw/swap 按钮识别留待实机（Step3/4），当前默认 False（决策会兜底处理）
        swap_hand_available=False,
        draw_available=False,
    )


def build_exam_state(
    hand: HandSummary,
    numerics: dict[str, NumericRead],
    round_: ExamRound,
    total_turns: int,
    stamina: int,
    round_metrics: RoundMetrics | None = None,
    *,
    cards_played: int | None = None,
    oneesan_used: bool | None = None,
    natural_finisher_used: bool | None = None,
) -> ExamState:
    """从 HandSummary + 数值字段组装 ExamState（纯逻辑，可单测）。

    决策输入只在所有直接依赖字段都有可信值时构造。缺失或冲突会类型化
    拒绝，绝不把 ``0``、默认流或部分 Round 指标伪装成当前状态。
    """
    issues: list[ExamStateIssue] = []
    for key in _CARD_EXECUTION_NUMERICS:
        read = numerics.get(key)
        if read is None:
            issues.append(ExamStateIssue(key, ReadStatus.MISSING))
        elif read.status is not ReadStatus.OK:
            issues.append(ExamStateIssue(key, read.status, repr(read.samples)))
        elif key == "flow" and read.flow is None:
            issues.append(ExamStateIssue(key, ReadStatus.MISSING))
        elif key != "flow" and read.value is None:
            issues.append(ExamStateIssue(key, ReadStatus.MISSING))
    if stamina < 0:
        issues.append(ExamStateIssue("stamina", ReadStatus.MISSING))
    for field, value in (
        ("cards_played", cards_played),
        ("oneesan_used", oneesan_used),
        ("natural_finisher_used", natural_finisher_used),
    ):
        if value is None:
            issues.append(ExamStateIssue(field, ReadStatus.MISSING, "需要同局已验证账本"))
    if round_metrics is None:
        issues.extend(
            (
                *(ExamStateIssue(field, ReadStatus.MISSING) for field in ("param_vo", "param_da", "param_vi")),
                ExamStateIssue("current_score", ReadStatus.MISSING),
                ExamStateIssue("stage_multiplier", ReadStatus.MISSING),
            )
        )
    else:
        if round_metrics.params is None:
            issues.extend(ExamStateIssue(field, ReadStatus.MISSING) for field in ("param_vo", "param_da", "param_vi"))
        if round_metrics.current_score is None:
            issues.append(ExamStateIssue("current_score", ReadStatus.MISSING))
        if round_metrics.stage_multiplier is None:
            issues.append(ExamStateIssue("stage_multiplier", ReadStatus.MISSING))
    if issues:
        raise ExamStateRejected(tuple(issues))

    def _int(key: str) -> int:
        value = numerics[key].value
        assert value is not None
        return value

    # P ドリンク列表：OCR raw 按逗号分割（实机时由 read_numerics 解析）
    drinks_raw = numerics.get("p_drinks")
    p_drinks = [s.strip() for s in drinks_raw.raw.split(",")] if drinks_raw and drinks_raw.raw else []

    return ExamState(
        round=round_,
        turn=_int("turn"),
        total_turns=total_turns,
        current_flow=numerics["flow"].flow or "",  # 已由上方完整性检查保证非空
        good_condition_turns=_int("good_condition"),
        focus=_int("focus"),
        stamina=stamina,
        hand=hand,
        reprise_count=_int("reprise"),
        cards_played=cards_played,
        deck_size=_int("deck_size"),
        oneesan_used=oneesan_used,
        natural_finisher_used=natural_finisher_used,
        available_p_drinks=p_drinks,
        params=round_metrics.params,
        current_score=round_metrics.current_score if round_metrics else None,
        stage_multiplier=round_metrics.stage_multiplier if round_metrics else None,
    )


# ---------------------------------------------------------------------------
# maafw 适配（实机调用，依赖 Context，单测时用 mock 替换）
# ---------------------------------------------------------------------------


class _MaafwOcrAdapter:
    """OcrPort 的实机实现：包装 maafw Context，调用 pipeline OCR/YOLO。

    单测时不实例化本类，直接注入 mock OcrPort。
    """

    def __init__(self, context: "Context", image: object | None = None) -> None:
        self.context = context
        self._image = image
        self._card_dict = build_card_name_dict()

    def _current_image(self):
        """同一个读取器实例只使用一张原始帧，避免动画把多字段拼成伪状态。"""

        if self._image is None:
            self._image = self.context.tasker.controller.post_screencap().wait().get()
        return self._image

    def run_ocr(self, name: str, expected: list[str], roi: tuple[int, int, int, int]) -> str | None:
        """对指定 ROI 跑 OCR，用 expected 约束候选集。

        复用 produce_hif.py 的 pipeline_override 机制调用 maafw OCR。
        """
        text, _ = self._run_ocr_with_confidence(name, expected, roi)
        return text

    def run_ocr_with_confidence(
        self,
        name: str,
        expected: list[str],
        roi: tuple[int, int, int, int],
    ) -> tuple[str | None, float]:
        return self._run_ocr_with_confidence(name, expected, roi)

    def run_turn_digit_template(self) -> tuple[str | None, float]:
        """仅在回合 OCR 空读时，以已采证的数字模板作受限兜底。

        不把模板匹配的任意命中直接当成状态：只有一个候选达到阈值且严格
        高于其余候选时才返回。模板来自同一 MuMu 原始帧，后续新样式必须先
        补样本，不能降低阈值猜测。
        """

        candidates: list[tuple[int, float]] = []
        image = self._current_image()
        for digit, template in _TURN_DIGIT_TEMPLATES.items():
            name = f"HIFTurnDigit{digit}"
            detail = self.context.run_recognition(
                name,
                image,
                pipeline_override={
                    name: {
                        "recognition": "TemplateMatch",
                        "template": template,
                        "roi": list(_TURN_DIGIT_ROI),
                        "threshold": _TURN_DIGIT_MIN_CONFIDENCE,
                    }
                },
            )
            if detail and detail.hit:
                score = getattr(detail.best_result, "score", 0.0)
                if isinstance(score, (int, float)):
                    candidates.append((digit, float(score)))

        qualified = [(digit, score) for digit, score in candidates if score >= _TURN_DIGIT_MIN_CONFIDENCE]
        if len(qualified) != 1:
            return None, 0.0
        digit, score = qualified[0]
        return str(digit), score

    def _run_ocr_with_confidence(
        self,
        name: str,
        expected: list[str],
        roi: tuple[int, int, int, int],
    ) -> tuple[str | None, float]:
        for attempt in range(3):
            detail = self.context.run_recognition(
                name,
                self._current_image(),
                pipeline_override={
                    name: {
                        "recognition": "OCR",
                        "expected": expected,
                        "roi": list(roi),
                    }
                },
            )
            if detail and detail.hit:
                score = getattr(detail.best_result, "score", 0.0)
                return detail.best_result.text, float(score) if isinstance(score, (int, float)) else 0.0
            if attempt < 2:
                time.sleep(0.15)
        return None, 0.0

    def run_yolo_cards(self) -> list[CardDetection]:
        """跑 ProduceRecognitionCards(YOLO)，把 maafw 返回映射为 CardDetection 列表。

        复用 MaaGakumasu 已有的 cards.onnx YOLO（NeuralNetworkDetect），
        对每个 box 追加 OCR 读名（run_ocr_for_card_box）。
        """
        image = self._current_image()
        detail = self.context.run_recognition("ProduceRecognitionCards", image)
        if not detail or not detail.hit:
            return []

        detections: list[CardDetection] = []
        # all_results 含每个检测框；filtered_results 为命中的（expected label）。
        for result in detail.all_results:
            box = tuple(result.box)  # type: ignore[arg-type]
            # label 从 detail 的分类信息读取（maafw NeuralNetworkDetect 提供）
            label = getattr(result, "label", "cards") or "cards"
            score = getattr(result, "score", 0.0)
            detection = CardDetection(
                label=label,
                box=box,
                confidence=float(score) if isinstance(score, (int, float)) else 0.0,
                playable=False if label == "useless" else None,
            )
            if box[1] < 800:
                # HIF Round 手牌固定出现在底部；保留 YOLO 原始框供 Journal 审计，
                # 但不能让角色/特效误框参与手牌名称、详情或出牌决策。
                detection.suppressed_reason = "outside_hand_roi"
            detections.append(detection)
        _suppress_overlapping_card_detections(detections)
        for detection in detections:
            if detection.suppressed_reason:
                continue
            card_name, raw_name, name_confidence = self._read_card_name_in_box(detection.box)
            detection.card_name = card_name
            detection.raw_card_name = raw_name
            detection.card_name_confidence = name_confidence
        return detections

    def _read_card_name_in_box(self, box: tuple[int, int, int, int]) -> tuple[str, str, float]:
        """在卡牌底部标题栏读取名称，同时保留强化后缀和 OCR 置信度。"""

        expected = [*self._card_dict, *(f"{name}+" for name in self._card_dict)]
        raw_name, confidence = self._run_ocr_with_confidence("HIFHandCardName", expected, _hand_card_name_roi(box))
        if not raw_name:
            return "", "", confidence
        normalized = normalize_card_name(raw_name[:-1] if raw_name.endswith("+") else raw_name)
        return normalized, raw_name, confidence


class ExamStateReader:
    """出牌状态读取器：协调 OcrPort 读取画面，组装 ExamState。

    单测时注入 mock OcrPort；实机时用 from_context() 工厂创建（含 _MaafwOcrAdapter）。
    本类本身不含 maafw 依赖（依赖 OcrPort 协议），便于离线测试。
    """

    def __init__(self, ocr: OcrPort) -> None:
        self.ocr = ocr

    @classmethod
    def from_context(cls, context: "Context") -> "ExamStateReader":
        """实机工厂：用 maafw Context 包装出 OcrPort。"""
        return cls(_MaafwOcrAdapter(context))

    def read_hand(self) -> HandSummary:
        """读手牌：YOLO 定位 + OCR 读名 → HandSummary。"""
        return build_hand_summary(self._read_detections())

    def _read_detections(self) -> list[CardDetection]:
        """读取手牌检测；复制列表避免调用方修改适配器返回值。"""

        return list(self.ocr.run_yolo_cards())

    def read_numerics(self) -> dict[str, NumericRead]:
        """读数值字段：对每个 ROI 跑 OCR，解析为 NumericRead。

        未校准字段会保持零 ROI 并跳过 OCR；调用者必须通过
        ``ExamStateObservation.missing_fields`` 阻止自动点击。
        """
        numerics: dict[str, NumericRead] = {}
        for key, roi_specs in _NUMERIC_ROI.items():
            if not roi_specs:
                # 未校准 ROI 跳过，避免把页面其他数字误读成状态。
                continue
            expected = _NUMERIC_EXPECTED.get(key, [".*\\d+.*"])
            reads = tuple(
                self._read_numeric(
                    key,
                    expected,
                    roi_spec.roi,
                    recognition_name=f"HIFNumericRoi{index}_{key}",
                )
                for index, roi_spec in enumerate(roi_specs)
            )
            numerics[key] = _consensus_numeric_reads(key, reads)
        return numerics

    def read_round_metrics(self) -> RoundMetrics:
        """只读取已校准的 Round 参数/分数 ROI；缺项不会猜测或继承旧帧值。"""

        reads: dict[str, str] = {}
        conflicts: set[str] = set()
        for key, roi_spec in _ROUND_METRIC_ROI.items():
            if not any(roi_spec.roi):
                continue
            expected = [r"\d+(?:[,.]\d+)*(?:\s*(?:%|％|倍))?"]
            read = self._read_numeric(key, expected, roi_spec.roi)
            reads[key] = read.raw if read.status is ReadStatus.OK else ""
            if read.status is ReadStatus.CONFLICT:
                conflicts.add(key)
        return build_round_metrics(reads, conflicting_fields=frozenset(conflicts))

    def _read_numeric(
        self,
        key: str,
        expected: list[str],
        roi: tuple[int, int, int, int],
        *,
        recognition_name: str | None = None,
    ) -> NumericRead:
        """三次读取至少两次一致；多值冲突与纯缺失保持不同类型。"""

        if key == "turn":
            template_reader = getattr(self.ocr, "run_turn_digit_template", None)
            if callable(template_reader):
                template_raw, _ = template_reader()
                if template_raw:
                    parsed = _parse_numeric(key, template_raw)
                    parsed.samples = (template_raw,)
                    return parsed

        name = recognition_name or f"HIFNumeric_{key}"
        confidence_reader = getattr(self.ocr, "run_ocr_with_confidence", None)
        if callable(confidence_reader):
            results = tuple(confidence_reader(name, expected, roi) for _ in range(3))
        else:
            results = tuple((self.ocr.run_ocr(name, expected, roi), 0.0) for _ in range(3))
        reads = tuple(text or "" for text, _ in results)
        confidences = tuple(float(confidence) for _, confidence in results)
        parsed = tuple(_parse_numeric(key, raw) for raw in reads)
        values = tuple(item.flow if key == "flow" else item.value for item in parsed)
        candidates = {value for value in values if value is not None}
        value = next((candidate for candidate in candidates if values.count(candidate) >= 2), None)
        if value is None:
            status = ReadStatus.CONFLICT if len(candidates) > 1 else ReadStatus.MISSING
            return NumericRead(
                key,
                "",
                None,
                status=status,
                samples=reads,
                confidence=max(confidences, default=0.0),
                confidences=confidences,
            )
        accepted = next(item for item, parsed_value in zip(parsed, values, strict=True) if parsed_value == value)
        accepted.status = ReadStatus.OK
        accepted.samples = reads
        matching_confidences = tuple(confidence for confidence, parsed_value in zip(confidences, values, strict=True) if parsed_value == value)
        accepted.confidence = max(matching_confidences, default=0.0)
        accepted.confidences = confidences
        return accepted

    def read_exam_state(
        self,
        round_: ExamRound,
        total_turns: int,
        stamina: int,
    ) -> ExamState:
        """读完整出牌状态：手牌 + 数值 + 组装 ExamState。"""
        observation = self.read_exam_observation(round_, total_turns, stamina)
        if observation.state is None:
            raise ExamStateRejected(observation.issues)
        return observation.state

    def read_exam_observation(
        self,
        round_: ExamRound,
        total_turns: int,
        stamina: int | None,
    ) -> ExamStateObservation:
        """读取出牌状态及其完整度，供影子/单步执行器做安全门控。"""

        detections = self._read_detections()
        hand = build_hand_summary(detections)
        numerics = self.read_numerics()
        round_metrics = self.read_round_metrics()
        missing: list[str] = []
        issues: list[ExamStateIssue] = []
        active_detections = [detection for detection in detections if not detection.suppressed_reason]
        if not active_detections:
            missing.append("hand")
            issues.append(ExamStateIssue("hand", ReadStatus.MISSING))
        elif any(not detection.card_name for detection in active_detections):
            missing.append("hand_names")
            issues.append(ExamStateIssue("hand_names", ReadStatus.MISSING))
        unresolved_playability = tuple(
            detection.card_name for detection in active_detections if detection.label != "useless" and detection.card_name
        )
        if unresolved_playability:
            # 当前实机证据中灰色「眠気」曾被 YOLO 标成普通 cards；因此 cards
            # 标签只能证明存在，不能证明可打。执行层完成卡片详情/视觉复核前拒绝。
            missing.append("hand_playability")
            issues.append(ExamStateIssue("hand_playability", ReadStatus.MISSING, repr(unresolved_playability)))
        for key in _CARD_EXECUTION_NUMERICS:
            read = numerics.get(key)
            if key == "flow":
                if read is None or read.flow is None:
                    missing.append(key)
                    issues.append(ExamStateIssue(key, read.status if read and read.status else ReadStatus.MISSING, repr(read.samples) if read else ""))
            elif read is None or read.value is None:
                missing.append(key)
                issues.append(ExamStateIssue(key, read.status if read and read.status else ReadStatus.MISSING, repr(read.samples) if read else ""))
        missing.extend(key for key in round_metrics.missing_fields if key not in missing)
        issues.extend(
            ExamStateIssue(
                issue.field,
                ReadStatus.CONFLICT if issue.code is MetricIssueCode.CONFLICT else ReadStatus.MISSING,
            )
            for issue in round_metrics.issues
        )
        numeric_stamina = numerics.get("stamina")
        resolved_stamina = stamina if stamina is not None else numeric_stamina.value if numeric_stamina else None
        if resolved_stamina is None or resolved_stamina < 0:
            if "stamina" not in missing:
                missing.append("stamina")
            resolved_stamina = -1
        try:
            state = build_exam_state(hand, numerics, round_, total_turns, resolved_stamina, round_metrics)
        except ExamStateRejected as error:
            state = None
            existing = {issue.field for issue in issues}
            issues.extend(issue for issue in error.issues if issue.field not in existing)
            missing.extend(issue.field for issue in error.issues if issue.field not in missing)
        required_count = len(_CARD_EXECUTION_NUMERICS) + len(_ROUND_METRIC_LABELS) + 2  # 完整手牌、体力与局内指标
        confidence = round(max(0, required_count - len(missing)) / required_count, 2)
        return ExamStateObservation(
            state=state,
            detections=detections,
            numerics=numerics,
            round_metrics=round_metrics,
            missing_fields=tuple(missing),
            screen_confidence=confidence,
            issues=tuple(issues),
            grey_cards=tuple(detection.card_name for detection in active_detections if detection.label == "useless" and detection.card_name),
            unresolved_playability=unresolved_playability,
        )


def _parse_numeric(key: str, raw: str) -> NumericRead:
    """解析 OCR 文本为 NumericRead（纯逻辑，可单测）。

    flow 字段提取 Vo/Da/Vi；其他字段提取整数；解析失败 value=None。
    """
    if key == "flow":
        aliases = {
            "Vo": ("Vo", "ボーカル"),
            "Da": ("Da", "ダンス"),
            "Vi": ("Vi", "ビジュアル"),
        }
        for flow, tokens in aliases.items():
            if any(token in raw for token in tokens):
                return NumericRead(name=key, raw=raw, value=None, flow=flow)
        return NumericRead(name=key, raw=raw, value=None, flow=None)

    # 提取首个整数（OCR 可能带「ターン」「枚」等单位）
    digits = ""
    for ch in raw:
        if ch.isdigit():
            digits += ch
        elif digits:
            break  # 读到首个连续数字段即止
    value = int(digits) if digits else None
    return NumericRead(name=key, raw=raw, value=value)
