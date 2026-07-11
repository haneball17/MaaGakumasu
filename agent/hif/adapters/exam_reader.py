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

from typing import TYPE_CHECKING, Protocol
from dataclasses import dataclass

from agent.hif.calibration import load_hif_roi_calibration
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
}


def _load_numeric_roi() -> dict[str, NumericROI]:
    """仅加载实机已校准字段；其余使用零 ROI 并由读取器跳过。"""

    calibration = load_hif_roi_calibration()
    return {
        key: NumericROI(label, calibration.roi_for_exam_numeric(key) or (0, 0, 0, 0))
        for key, label in _NUMERIC_LABELS.items()
    }


_NUMERIC_ROI = _load_numeric_roi()


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
    missing_fields: tuple[str, ...]
    screen_confidence: float


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
    card_names = [normalize_card_name(d.card_name) for d in detections if d.card_name]
    has_shizen = "自然体の魅力" in card_names
    has_oneesan = "お姉さんの感覚" in card_names
    has_kokuminteki = "国民的アイドル" in card_names

    # 好调卡计数：YOLO suggestions 标签 + OCR 命中的好调卡名（去重避免双计）
    suggestion_count = sum(1 for d in detections if d.label == "suggestions")
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
        params=ParamSet(),  # 三维参数，当前不识别（仅影响参数感知告警，非关键）
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
            return detail.best_result.text
        return None

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
            # 对每个 box 跑 OCR 读卡名（卡牌上半部为卡名区，box 上移压缩高度）
            card_name = self._read_card_name_in_box(box)
            detections.append(CardDetection(label=label, box=box, card_name=card_name))
        return detections

    def _read_card_name_in_box(self, box: tuple[int, int, int, int]) -> str:
        """在 YOLO box 内跑 OCR 读卡名（box 上半部为卡名区域）。"""
        x, y, w, h = box
        # 卡名通常在卡牌上半部：ROI 取 box 上 40% 高度区域。
        name_roi = (x, y, w, max(1, int(h * 0.4)))
        text = self.run_ocr("HIFHandCardName", self._card_dict, name_roi)
        return normalize_card_name(text) if text else ""


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
            raw = self.ocr.run_ocr(f"HIFNumeric_{key}", [], roi_spec.roi) or ""
            numerics[key] = _parse_numeric(key, raw)
        return numerics

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
        missing = []
        if not detections:
            missing.append("hand")
        for key in _CARD_EXECUTION_NUMERICS:
            read = numerics.get(key)
            if key == "flow":
                if read is None or read.flow is None:
                    missing.append(key)
            elif read is None or read.value is None:
                missing.append(key)
        if stamina is None or stamina < 0:
            missing.append("stamina")
        state = build_exam_state(hand, numerics, round_, total_turns, stamina if stamina is not None else 0)
        required_count = len(_CARD_EXECUTION_NUMERICS) + 2  # 手牌和体力
        confidence = round(max(0, required_count - len(missing)) / required_count, 2)
        return ExamStateObservation(
            state=state,
            detections=detections,
            numerics=numerics,
            missing_fields=tuple(missing),
            screen_confidence=confidence,
        )


def _parse_numeric(key: str, raw: str) -> NumericRead:
    """解析 OCR 文本为 NumericRead（纯逻辑，可单测）。

    flow 字段提取 Vo/Da/Vi；其他字段提取整数；解析失败 value=None。
    """
    if key == "flow":
        for flow in ("Vo", "Da", "Vi"):
            if flow in raw:
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
