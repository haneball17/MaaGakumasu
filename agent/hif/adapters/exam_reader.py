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
from typing import TYPE_CHECKING, Protocol
from dataclasses import dataclass

from agent.hif.calibration import load_hif_roi_calibration
from agent.hif.round_metrics import RoundMetrics, build_round_metrics
from agent.hif.decisions.state import (
    ParamSet,
    ExamRound,
    ExamState,
    HandSummary,
)
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
    7: "produce/HIF/turn_digits/7.png",
    8: "produce/HIF/turn_digits/8.png",
    9: "produce/HIF/turn_digits/9.png",
}
_TURN_DIGIT_ROI = (13, 43, 120, 128)
_TURN_DIGIT_MIN_CONFIDENCE = 0.95


def _load_numeric_roi() -> dict[str, NumericROI]:
    """仅加载实机已校准字段；其余使用零 ROI 并由读取器跳过。"""

    calibration = load_hif_roi_calibration()
    return {
        key: NumericROI(label, calibration.roi_for_exam_numeric(key) or (0, 0, 0, 0))
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


@dataclass(slots=True)
class ExamStateObservation:
    """一次出牌画面的完整读取结果。

    ``ExamState`` 为兼容既有策略仍会对缺失值给出零值兜底，但自动点击必须
    检查 ``missing_fields``。这使影子模式可继续产出建议，而执行模式不会把
    未校准的 ROI 当作真实数值。
    """

    state: ExamState
    detections: list[CardDetection]
    numerics: dict[str, NumericRead]
    round_metrics: RoundMetrics
    missing_fields: tuple[str, ...]
    screen_confidence: float


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
) -> ExamState:
    """从 HandSummary + 数值字段组装 ExamState（纯逻辑，可单测）。

    numerics 缺失字段回退默认值（0/空），保证降级可用——
    即便部分数值字段 OCR 失败，决策大脑仍能基于手牌信息出牌。
    """
    def _int(key: str) -> int:
        v = numerics.get(key)
        return v.value if v and v.value is not None else 0

    def _flow() -> str:
        v = numerics.get("flow")
        return v.flow if v and v.flow else "Vi"  # 默认 Vi（姫崎莉波バランス 流1）

    # P ドリンク列表：OCR raw 按逗号分割（实机时由 read_numerics 解析）
    drinks_raw = numerics.get("p_drinks")
    p_drinks = [s.strip() for s in drinks_raw.raw.split(",")] if drinks_raw and drinks_raw.raw else []

    return ExamState(
        round=round_,
        turn=_int("turn"),
        total_turns=total_turns,
        current_flow=_flow(),
        good_condition_turns=_int("good_condition"),
        focus=_int("focus"),
        stamina=stamina,
        hand=hand,
        reprise_count=_int("reprise"),
        cards_played=0,  # 本レッスン已出牌数，当前不识别（决策不依赖此字段）
        deck_size=_int("deck_size"),
        oneesan_used=False,  # 是否本レッスン已用お姉さん，需跨回合状态（Step4 在 action 内维护）
        natural_finisher_used=False,  # 同上
        available_p_drinks=p_drinks,
        params=round_metrics.params if round_metrics and round_metrics.is_complete else ParamSet(),
        current_score=round_metrics.current_score if round_metrics and round_metrics.is_complete else None,
        stage_multiplier=round_metrics.stage_multiplier if round_metrics and round_metrics.is_complete else None,
    )


# ---------------------------------------------------------------------------
# maafw 适配（实机调用，依赖 Context，单测时用 mock 替换）
# ---------------------------------------------------------------------------


class _MaafwOcrAdapter:
    """OcrPort 的实机实现：包装 maafw Context，调用 pipeline OCR/YOLO。

    单测时不实例化本类，直接注入 mock OcrPort。
    """

    def __init__(self, context: "Context") -> None:
        self.context = context
        self._card_dict = build_card_name_dict()

    def run_ocr(self, name: str, expected: list[str], roi: tuple[int, int, int, int]) -> str | None:
        """对指定 ROI 跑 OCR，用 expected 约束候选集。

        复用 produce_hif.py 的 pipeline_override 机制调用 maafw OCR。
        """
        text, _ = self._run_ocr_with_confidence(name, expected, roi)
        return text

    def run_turn_digit_template(self) -> tuple[str | None, float]:
        """仅在回合 OCR 空读时，以已采证的数字模板作受限兜底。

        不把模板匹配的任意命中直接当成状态：只有一个候选达到阈值且严格
        高于其余候选时才返回。模板来自同一 MuMu 原始帧，后续新样式必须先
        补样本，不能降低阈值猜测。
        """

        candidates: list[tuple[int, float]] = []
        image = self.context.tasker.controller.post_screencap().wait().get()
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
                self.context.tasker.controller.post_screencap().wait().get(),
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
        image = self.context.tasker.controller.post_screencap().wait().get()
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
        for key, roi_spec in _NUMERIC_ROI.items():
            if all(v == 0 for v in roi_spec.roi):
                # 未校准 ROI 跳过，避免把页面其他数字误读成状态。
                continue
            expected = _NUMERIC_EXPECTED.get(key, [".*\\d+.*"])
            raw = self._read_numeric_raw(key, expected, roi_spec.roi)
            numerics[key] = _parse_numeric(key, raw)
        return numerics

    def read_round_metrics(self) -> RoundMetrics:
        """只读取已校准的 Round 参数/分数 ROI；缺项不会猜测或继承旧帧值。"""

        reads: dict[str, str] = {}
        for key, roi_spec in _ROUND_METRIC_ROI.items():
            if not any(roi_spec.roi):
                continue
            expected = [r"\\d+(?:[,.]\\d+)*(?:\\s*(?:%|％|倍))?"]
            raw = self._read_numeric_raw(key, expected, roi_spec.roi)
            reads[key] = raw
        return build_round_metrics(reads)

    def _read_numeric_raw(self, key: str, expected: list[str], roi: tuple[int, int, int, int]) -> str:
        """读取单个数值，模板优先修正回合 OCR，普通数值要求三次中至少两次一致。

        HIF 的动态舞台背景会让单次 OCR 偶发把 ``7`` 读为 ``1``、把 ``40``
        读为 ``2``。一次空读不会抹掉两次同值，但三种不同读数仍会保留为
        缺失字段并阻止执行，不能向策略层伪造一个看似有效的数值。
        """

        if key == "turn":
            template_reader = getattr(self.ocr, "run_turn_digit_template", None)
            if callable(template_reader):
                template_raw, _ = template_reader()
                if template_raw:
                    return template_raw
        if key == "flow":
            return self.ocr.run_ocr(f"HIFNumeric_{key}", expected, roi) or ""

        reads = [self.ocr.run_ocr(f"HIFNumeric_{key}", expected, roi) or "" for _ in range(3)]
        parsed = [_parse_numeric(key, raw).value for raw in reads]
        candidates = {value for value in parsed if value is not None}
        value = next((candidate for candidate in candidates if parsed.count(candidate) >= 2), None)
        if value is None:
            return ""
        return next(raw for raw in reads if _parse_numeric(key, raw).value == value)

    def read_exam_state(
        self,
        round_: ExamRound,
        total_turns: int,
        stamina: int,
    ) -> ExamState:
        """读完整出牌状态：手牌 + 数值 + 组装 ExamState。"""
        return self.read_exam_observation(round_, total_turns, stamina).state

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
        missing = []
        active_detections = [detection for detection in detections if not detection.suppressed_reason]
        if not active_detections:
            missing.append("hand")
        elif any(not detection.card_name for detection in active_detections):
            missing.append("hand_names")
        for key in _CARD_EXECUTION_NUMERICS:
            read = numerics.get(key)
            if key == "flow":
                if read is None or read.flow is None:
                    missing.append(key)
            elif read is None or read.value is None:
                missing.append(key)
        missing.extend(key for key in round_metrics.missing_fields if key not in missing)
        numeric_stamina = numerics.get("stamina")
        resolved_stamina = stamina if stamina is not None else numeric_stamina.value if numeric_stamina else None
        if resolved_stamina is None or resolved_stamina < 0:
            if "stamina" not in missing:
                missing.append("stamina")
            resolved_stamina = 0
        state = build_exam_state(hand, numerics, round_, total_turns, resolved_stamina, round_metrics)
        required_count = len(_CARD_EXECUTION_NUMERICS) + len(_ROUND_METRIC_LABELS) + 2  # 完整手牌、体力与局内指标
        confidence = round(max(0, required_count - len(missing)) / required_count, 2)
        return ExamStateObservation(
                state=state,
                detections=detections,
                numerics=numerics,
                round_metrics=round_metrics,
            missing_fields=tuple(missing),
            screen_confidence=confidence,
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
