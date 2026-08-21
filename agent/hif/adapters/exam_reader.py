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

注：turn/stamina/flow 的 ROI 已実機校准（2026-08-21 MuMu 720×1280 取证局），
    其余数值字段仍为占位全 0（画面直读不可行/待模板定行，见 _NUMERIC_ROI 注释）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol
from dataclasses import dataclass

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
# 数值字段 ROI（占位，Step3 实机校准）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumericROI:
    """单个数值字段在画面上的 ROI 区域 [x, y, w, h]（Step3 实机校准）。"""

    name: str
    roi: tuple[int, int, int, int]


# 数值字段 ROI 坐标（竖屏 720×1280 画面，MuMu12 项目基准）。
# turn/stamina/flow 为実機实测（2026-08-21 取证局校准）；
# 其余为占位全 0，read_numerics 遇全 0 ROI 跳过不读（build_exam_state 降级默认值）。
_NUMERIC_ROI: dict[str, NumericROI] = {
    # Phase 2 実機结论：好調行位置随 buff 数动态重排，固定 ROI 画面直读不可行，
    # 待模板定行后由 Play action 内联读取；session 亦可兜底累计。
    "good_condition": NumericROI("好调ターン数", (0, 0, 0, 0)),
    # Phase 2 実機结论：再演右上 N 回无稳定数值区（同随 buff 重排），由 session 维护或 Play action 内联读取。
    "reprise": NumericROI("再演次数", (0, 0, 0, 0)),
    # Phase 2 実機结论：集中行同 good_condition 动态重排，待模板定行后由 Play action 内联读取。
    "focus": NumericROI("集中值", (0, 0, 0, 0)),
    # 残りターン数值区（実機实测）。ROI 内偶现「M」「•」杂讯，_parse_numeric
    # 取首个连续数字段可跳过纯文字；带尾随标点（「6）」）也能正确取 6。
    "turn": NumericROI("回合计数", (25, 50, 90, 70)),
    # 当前流显示区（実機实测）：盖日文名+百分数两行（「ビジュアル 3807%」），
    # _FLOW_TEXT_ALIASES 已支持日文全称映射。
    "flow": NumericROI("当前流 Vo/Da/Vi", (90, 45, 145, 80)),
    # Phase 2 実機结论：山札张数无稳定数值显示区，由 session 维护（round1 子树）。
    "deck_size": NumericROI("山札张数", (0, 0, 0, 0)),
    # Phase 2 実機结论：Pドリンク为图标+数量区非文本行，由 Play action 内联读取。
    "p_drinks": NumericROI("持有Pドリンク", (0, 0, 0, 0)),
    # 体力（実機实测，取代 Phase 0 候选占位）。注意：実機全屏 OCR 曾把 29 误读成 0
    # （数字分体），_parse_numeric 的「首个连续数字段」提取不改逻辑，误读风险
    # 依赖 ROI 收窄（120×60）缓解，异常值由决策侧 stamina 阈值兜底。
    "stamina": NumericROI("体力", (555, 200, 120, 60)),
}

# 流属性画面显示日文全称（実機例「ビジュアル 3807%」），英文缩写保留兼容（旧测试/回放）
_FLOW_TEXT_ALIASES: tuple[tuple[str, str], ...] = (
    ("ビジュアル", "Vi"),
    ("ボーカル", "Vo"),
    ("ダンス", "Da"),
)


# ---------------------------------------------------------------------------
# maafw 返回值的本地抽象（让纯逻辑可单测，不依赖 maa 类型）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CardDetection:
    """单张手牌的 YOLO 检测结果（maafw NeuralNetworkDetect 输出的本地映射）。

    label 为 cards/suggestions/useless 之一；
    box 为 [x, y, w, h]；card_name 由后续 OCR 填充（初始为空）；
    score 为 YOLO 置信度（filter_card_detections 同卡去重时保留高分框）。
    """

    label: str
    box: tuple[int, int, int, int]
    card_name: str = ""
    score: float = 1.0


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


# YOLO 检测框过滤阈值（実機 2026-08-21 MuMu 720×1280 取证）：
# - 正常手牌卡宽 130~185px，宽 <90px 为过窄误检框 → 丢弃；
# - 同一张卡的重复框相邻重叠（低分 ~0.61），box 中心横向距离 <60px 视为同卡 → 保留高分框。
_MIN_CARD_WIDTH = 90
_SAME_CARD_CENTER_DX = 60


def filter_card_detections(detections: list[CardDetection]) -> list[CardDetection]:
    """YOLO 检测框去重过滤（纯逻辑，可单测；実機 2026-08-21 取证修复）。

    実機 cards.onnx 偶发两类噪声（不处理会导致同卡双计/误检卡混入决策）：
    1. 同一张卡的重复框：相邻重叠、低分（~0.61）——按 box 中心横向距离
       <60px 视为同卡，保留 score 高的框（score 并列保持输入顺序）；
    2. 过窄误检框：宽 <90px（正常卡 130~185px）——直接丢弃。
    返回保持输入顺序，便于下游按画面位置处理。
    """
    # 按 score 降序贪心占位（sorted 稳定，并列时先输入者胜出）
    indexed = sorted(enumerate(detections), key=lambda p: p[1].score, reverse=True)
    kept: list[int] = []
    for idx, det in indexed:
        if det.box[2] < _MIN_CARD_WIDTH:
            continue
        cx = det.box[0] + det.box[2] / 2
        if any(abs(cx - (detections[k].box[0] + detections[k].box[2] / 2)) < _SAME_CARD_CENTER_DX for k in kept):
            continue  # 与已保留框同卡（中心横向距离过近）→ 低分重复框丢弃
        kept.append(idx)
    return [detections[i] for i in sorted(kept)]


def _matches_key_card(card_name: str, key_card: str) -> bool:
    """关键卡命中判定：剥档位「+」后缀后比较基础名（実機 2026-08-21 漏检修复）。

    実機 OCR 读出的卡名带档位后缀（「自然体の魅力+」「国民的アイドル+」），
    此前用精确列表成员检查会全部 miss → 决策分支 1/2/3（终结技/铺垫/循环
    启动）系统性失效（実機终结技回合 dry-run 给错卡实测）。剥 + 号后与
    KEY 卡名比较，無印卡名仍命中（向后兼容）。
    """
    return card_name.rstrip("+") == key_card


def build_hand_summary(detections: list[CardDetection]) -> HandSummary:
    """从 YOLO 检测 + OCR 卡名组装 HandSummary（纯逻辑，可单测）。

    判定逻辑：
    - has_shizen/has_oneesan/has_kokuminteki：卡名剥档位 + 后缀匹配关键卡
      （_matches_key_card，実機 2026-08-21「自然体の魅力+」漏检修复）
    - good_condition_card_count：label=suggestions 的数量 + 命中好调卡名的数量
    - draw_available/swap_hand_available：当前未识别（留 False，待实机补按钮识别）
    """
    card_names = [normalize_card_name(d.card_name) for d in detections if d.card_name]
    label_set = {d.label for d in detections}

    has_shizen = any(_matches_key_card(n, "自然体の魅力") for n in card_names)
    has_oneesan = any(_matches_key_card(n, "お姉さんの感覚") for n in card_names)
    has_kokuminteki = any(_matches_key_card(n, "国民的アイドル") for n in card_names)

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
        card_names=tuple(card_names),
    )


def build_exam_state(
    hand: HandSummary,
    numerics: dict[str, NumericRead],
    round_: ExamRound,
    total_turns: int,
    stamina: int,
    session: dict | None = None,
) -> ExamState:
    """从 HandSummary + 数值字段组装 ExamState（纯逻辑，可单测）。

    numerics 缺失字段回退默认值（0/空），保证降级可用——
    即便部分数值字段 OCR 失败，决策大脑仍能基于手牌信息出牌。

    session 为 session-state 的 round1 子树（跨回合局内字段，画面外状态）：
    cards_played / oneesan_used / natural_finisher_used 直接注入；
    reprise_count 画面优先（Q6 真值源）——numerics 有值（含 0）信画面，
    缺失时 session 兜底。session=None 时行为与旧版完全一致。
    """
    session = session or {}

    def _int(key: str) -> int:
        v = numerics.get(key)
        return v.value if v and v.value is not None else 0

    def _flow() -> str:
        v = numerics.get("flow")
        return v.flow if v and v.flow else "Vi"  # 默认 Vi（姫崎莉波バランス 流1）

    # 再演次数：numerics 有值（含 0）时画面优先，缺失时 session 兜底
    reprise_read = numerics.get("reprise")
    if reprise_read and reprise_read.value is not None:
        reprise_count = reprise_read.value
    else:
        reprise_count = int(session.get("reprise_count") or 0)

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
        reprise_count=reprise_count,
        cards_played=int(session.get("cards_played") or 0),  # 跨回合累计，画面不显示（session-state round1 维护）
        deck_size=_int("deck_size"),
        oneesan_used=bool(session.get("oneesan_used", False)),  # 跨回合状态，画面不可读（session 注入）
        natural_finisher_used=bool(session.get("natural_finisher_used", False)),  # 同上
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
        expected 为字面词典;词典经 maafw IPC 偶发 UTF-8→GBK 乱码(実機
        2026-08-20 Round1 读手牌),大词典(>32 项)改为全量 OCR + Python 侧
        子串匹配,小列表仍走 expected 约束(需转义元字符)。
        """
        big_dict = len(expected) > 32
        if big_dict:
            override_expected = [".*"]
        else:
            override_expected = [re.escape(item) for item in expected]
        detail = self.context.run_recognition(
            name,
            self.context.tasker.controller.post_screencap().wait().get(),
            pipeline_override={
                name: {
                    "recognition": "OCR",
                    "expected": override_expected,
                    "roi": list(roi),
                }
            },
        )
        if not detail:
            return None
        if not big_dict:
            return detail.best_result.text if detail.hit else None
        for item in detail.all_results:
            text = item.text.strip()
            for dict_name in expected:
                if dict_name in text:
                    return dict_name
        return None

    def run_yolo_cards(self) -> list[CardDetection]:
        """跑 ProduceRecognitionCards(YOLO)，把 maafw 返回映射为 CardDetection 列表。

        复用 MaaGakumasu 已有的 cards.onnx YOLO（NeuralNetworkDetect），
        对每个 box 追加 OCR 读名（run_ocr_for_card_box）；
        返回前经 filter_card_detections 去重复框 + 丢弃过窄误检框
        （実機 2026-08-21 取证修复）。
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
            score = float(getattr(result, "score", 1.0) or 1.0)
            # 对每个 box 跑 OCR 读卡名（卡牌上半部为卡名区，box 上移压缩高度）
            card_name = self._read_card_name_in_box(box)
            detections.append(CardDetection(label=label, box=box, card_name=card_name, score=score))
        return filter_card_detections(detections)

    def _read_card_name_in_box(self, box: tuple[int, int, int, int]) -> str:
        """在 YOLO box 内跑 OCR 读卡名（box 底部为卡名区域）。"""
        x, y, w, h = box
        # 実機 2026-08-20 Round1:卡名文字在 box 底部约 84%~100% 高度带
        # (实测「静かな意志」y1102 落在 box y886+250h 的 86% 处),此前取上 40% 恒空
        name_roi = (x, y + int(h * 0.84), w, max(1, int(h * 0.16)))
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
        detections = self.ocr.run_yolo_cards()
        return build_hand_summary(detections)

    def read_numerics(self) -> dict[str, NumericRead]:
        """读数值字段：对每个 ROI 跑 OCR，解析为 NumericRead。

        占位 ROI（全 0：good_condition/reprise/focus/deck_size/p_drinks，
        Phase 2 実機结论画面直读不可行者）跳过不读；turn/stamina/flow 为
        実機校准坐标（2026-08-21），会实际调 OCR。build_exam_state 对
        缺失/解析失败字段回退默认值，保证降级运行。
        """
        numerics: dict[str, NumericRead] = {}
        for key, roi_spec in _NUMERIC_ROI.items():
            if all(v == 0 for v in roi_spec.roi):
                # 占位 ROI 跳过（Step3 校准前不调 OCR，避免误读）
                continue
            raw = self.ocr.run_ocr(f"HIFNumeric_{key}", [], roi_spec.roi) or ""
            numerics[key] = _parse_numeric(key, raw)
        return numerics

    def read_exam_state(
        self,
        round_: ExamRound,
        total_turns: int,
        stamina: int | None = None,
        session: dict | None = None,
    ) -> ExamState:
        """读完整出牌状态：手牌 + 数值 + 组装 ExamState。

        stamina 显式传参优先；None 时从 numerics["stamina"]（画面 ROI）读取，
        解析失败回退 0，不抛异常（占位 ROI 校准前的安全降级）。
        session 为 session-state 的 round1 子树，透传 build_exam_state 注入跨回合
        字段（cards_played/oneesan_used/natural_finisher_used/reprise_count 兜底），
        None 时保持旧默认行为（Phase 2 出牌节点单调用链免二次组装）。
        """
        hand = self.read_hand()
        numerics = self.read_numerics()
        if stamina is None:
            v = numerics.get("stamina")
            stamina = v.value if v and v.value is not None else 0
        return build_exam_state(hand, numerics, round_, total_turns, stamina, session=session)


def _parse_numeric(key: str, raw: str) -> NumericRead:
    """解析 OCR 文本为 NumericRead（纯逻辑，可单测）。

    flow 字段提取 Vo/Da/Vi；其他字段提取整数；解析失败 value=None。
    """
    if key == "flow":
        # 日文全称优先（実機画面只显示日文，如「ビジュアル 3807%」），英文缩写兜底
        for jp_text, flow in _FLOW_TEXT_ALIASES:
            if jp_text in raw:
                return NumericRead(name=key, raw=raw, value=None, flow=flow)
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
