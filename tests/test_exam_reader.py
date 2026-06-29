"""出牌状态适配层单测（ExamStateReader）。

覆盖纯逻辑组装函数 + mock OcrPort 的端到端组装验证。
所有测试离线可跑，不依赖 maafw Context 或模拟器。

关键场景：
- build_hand_summary: 3张关键卡判定 / 好调卡计数 / OCR误识修正
- build_exam_state: 数值缺失降级 / Pドリンク解析 / flow提取
- _parse_numeric: 整数解析 / flow识别 / 解析失败
- ExamStateReader: 注入mock OcrPort 验证协调逻辑
"""

from __future__ import annotations

from agent.hif.decisions.state import ExamRound, HandSummary
from agent.hif.adapters.card_dict import (
    KEY_CARDS,
    normalize_card_name,
    build_card_name_dict,
    is_good_condition_card,
)
from agent.hif.adapters.exam_reader import (
    NumericRead,
    CardDetection,
    ExamStateReader,
    _parse_numeric,
    build_exam_state,
    build_hand_summary,
)

# ---------------------------------------------------------------------------
# card_dict: 词典生成 + 好调卡判定
# ---------------------------------------------------------------------------


def test_card_dict_contains_key_cards() -> None:
    """OCR 词典必须包含 3 张关键卡（决策分支 1/2/3 的触发条件）。"""
    names = build_card_name_dict()
    for key in KEY_CARDS:
        assert key in names, f"词典缺失关键卡: {key}"


def test_card_dict_dedup() -> None:
    """词典去重（skill_cards.json 卡名与关键卡重复时不重复出现）。"""
    names = build_card_name_dict()
    assert len(names) == len(set(names)), "词典存在重复卡名"


def test_is_good_condition_card() -> None:
    """好调卡判定：关键卡 + 常见卡 + 含「好調」字样。"""
    assert is_good_condition_card("自然体の魅力") is True
    assert is_good_condition_card("アピールの基礎") is True
    assert is_good_condition_card("好調ターン") is True
    assert is_good_condition_card("トラブル") is False
    assert is_good_condition_card("") is False


def test_normalize_card_name_strips_space() -> None:
    """OCR 文本去空格（日文 OCR 常插入多余空格）。"""
    assert normalize_card_name(" 自然 体 の 魅力 ") == "自然体の魅力"


# ---------------------------------------------------------------------------
# build_hand_summary: 手牌组装（核心纯逻辑）
# ---------------------------------------------------------------------------


def test_hand_summary_detects_key_cards() -> None:
    """YOLO+OCR 读出 3 张关键卡名时，HandSummary 对应位置为 True。"""
    detections = [
        CardDetection(label="cards", box=(0, 0, 100, 200), card_name="自然体の魅力"),
        CardDetection(label="cards", box=(100, 0, 100, 200), card_name="お姉さんの感覚"),
        CardDetection(label="cards", box=(200, 0, 100, 200), card_name="国民的アイドル"),
    ]
    hand = build_hand_summary(detections)
    assert hand.has_shizen_no_miryoku is True
    assert hand.has_oneesan_no_kankaku is True
    assert hand.has_kokuminteki_idol is True


def test_hand_summary_missing_key_card() -> None:
    """手牌无关键卡时，HandSummary 对应位置为 False。"""
    detections = [
        CardDetection(label="cards", box=(0, 0, 100, 200), card_name="アピールの基礎"),
    ]
    hand = build_hand_summary(detections)
    assert hand.has_shizen_no_miryoku is False
    assert hand.has_oneesan_no_kankaku is False
    assert hand.has_kokuminteki_idol is False


def test_hand_summary_good_condition_count_from_suggestions() -> None:
    """YOLO suggestions 标签计入好调卡数。"""
    detections = [
        CardDetection(label="suggestions", box=(0, 0, 100, 200), card_name=""),
        CardDetection(label="suggestions", box=(100, 0, 100, 200), card_name=""),
        CardDetection(label="cards", box=(200, 0, 100, 200), card_name=""),
    ]
    hand = build_hand_summary(detections)
    assert hand.good_condition_card_count == 2


def test_hand_summary_good_condition_count_from_ocr() -> None:
    """OCR 命中好调卡名也计入（与 suggestions 取最大值，避免双计）。"""
    detections = [
        CardDetection(label="cards", box=(0, 0, 100, 200), card_name="アピールの基礎"),
        CardDetection(label="cards", box=(100, 0, 100, 200), card_name="ダンスの基礎"),
    ]
    hand = build_hand_summary(detections)
    assert hand.good_condition_card_count == 2


def test_hand_summary_empty_detections() -> None:
    """无任何手牌检测时返回全 False/0（决策兜底处理）。"""
    hand = build_hand_summary([])
    assert hand.has_shizen_no_miryoku is False
    assert hand.good_condition_card_count == 0


def test_hand_summary_ocr_variant_normalized() -> None:
    """OCR 误识变体经 normalize_card_name 修正后能命中关键卡。"""
    # 带空格的 OCR 文本应被规整后命中
    detections = [
        CardDetection(label="cards", box=(0, 0, 100, 200), card_name=" 自然体の魅力 "),
    ]
    hand = build_hand_summary(detections)
    assert hand.has_shizen_no_miryoku is True


# ---------------------------------------------------------------------------
# _parse_numeric: 数值解析
# ---------------------------------------------------------------------------


def test_parse_numeric_int() -> None:
    """整数解析：提取首个连续数字段。"""
    assert _parse_numeric("good_condition", "12ターン").value == 12
    assert _parse_numeric("focus", "5").value == 5
    assert _parse_numeric("reprise", "残3").value == 3


def test_parse_numeric_no_digit() -> None:
    """无数字时 value=None（build_exam_state 会降级为 0）。"""
    result = _parse_numeric("focus", "不明")
    assert result.value is None


def test_parse_numeric_flow() -> None:
    """flow 字段提取 Vo/Da/Vi。"""
    assert _parse_numeric("flow", "Vi").flow == "Vi"
    assert _parse_numeric("flow", "Da流").flow == "Da"
    assert _parse_numeric("flow", "なし").flow is None


# ---------------------------------------------------------------------------
# build_exam_state: 状态组装（含降级）
# ---------------------------------------------------------------------------


def test_exam_state_degrades_on_missing_numerics() -> None:
    """数值字段缺失时降级为默认值（0/空），决策仍可基于手牌运行。"""
    hand = HandSummary(
        has_shizen_no_miryoku=True,
        has_oneesan_no_kankaku=False,
        has_kokuminteki_idol=False,
        good_condition_card_count=2,
        swap_hand_available=False,
        draw_available=False,
    )
    state = build_exam_state(hand, {}, ExamRound.HONSEN_R1, total_turns=9, stamina=80)
    assert state.good_condition_turns == 0  # 缺失降级
    assert state.focus == 0
    assert state.reprise_count == 0
    assert state.deck_size == 0
    assert state.current_flow == "Vi"  # 默认流
    assert state.hand.has_shizen_no_miryoku is True  # 手牌信息保留
    assert state.stamina == 80


def test_exam_state_parses_numerics() -> None:
    """数值字段正常解析时填入 ExamState。"""
    hand = HandSummary(
        has_shizen_no_miryoku=False,
        has_oneesan_no_kankaku=False,
        has_kokuminteki_idol=False,
        good_condition_card_count=3,
        swap_hand_available=True,
        draw_available=True,
    )
    numerics = {
        "good_condition": NumericRead("good_condition", "12", 12),
        "focus": NumericRead("focus", "8", 8),
        "reprise": NumericRead("reprise", "2", 2),
        "turn": NumericRead("turn", "5", 5),
        "deck_size": NumericRead("deck_size", "22枚", 22),
        "flow": NumericRead("flow", "Da", None, flow="Da"),
    }
    state = build_exam_state(hand, numerics, ExamRound.HONSEN_R1, total_turns=9, stamina=60)
    assert state.good_condition_turns == 12
    assert state.focus == 8
    assert state.reprise_count == 2
    assert state.turn == 5
    assert state.deck_size == 22
    assert state.current_flow == "Da"


def test_exam_state_p_drink_parsing() -> None:
    """P ドリンク列表按逗号分割。"""
    hand = HandSummary(
        has_shizen_no_miryoku=False,
        has_oneesan_no_kankaku=False,
        has_kokuminteki_idol=False,
        good_condition_card_count=0,
        swap_hand_available=False,
        draw_available=False,
    )
    numerics = {
        "p_drinks": NumericRead("p_drinks", "初星黒酢,パワフル漢方ドリンク", None),
    }
    state = build_exam_state(hand, numerics, ExamRound.HONSEN_R1, total_turns=9, stamina=10)
    assert "初星黒酢" in state.available_p_drinks
    assert "パワフル漢方ドリンク" in state.available_p_drinks


# ---------------------------------------------------------------------------
# ExamStateReader: mock OcrPort 端到端验证
# ---------------------------------------------------------------------------


class _MockOcrPort:
    """测试用 mock OcrPort，返回预设的 YOLO/OCR 结果。"""

    def __init__(self, cards: list[CardDetection], numerics: dict[str, str] | None = None) -> None:
        self._cards = cards
        self._numerics = numerics or {}

    def run_ocr(self, name: str, expected: list[str], roi: tuple[int, int, int, int]) -> str | None:
        # 数值字段按 name 后缀匹配（HIFNumeric_good_condition → good_condition）
        for key, val in self._numerics.items():
            if key in name:
                return val
        return None

    def run_yolo_cards(self) -> list[CardDetection]:
        return self._cards


def test_reader_assembles_state_from_mock_ocr() -> None:
    """注入 mock OcrPort，验证 ExamStateReader 端到端组装。"""
    cards = [
        CardDetection(label="cards", box=(0, 0, 100, 200), card_name="自然体の魅力"),
        CardDetection(label="suggestions", box=(100, 0, 100, 200), card_name="アピールの基礎"),
    ]
    ocr = _MockOcrPort(cards)
    reader = ExamStateReader(ocr)
    state = reader.read_exam_state(ExamRound.HONSEN_R1, total_turns=9, stamina=50)
    assert state.hand.has_shizen_no_miryoku is True
    assert state.stamina == 50
    assert state.round is ExamRound.HONSEN_R1
    assert state.total_turns == 9


def test_reader_read_hand_uses_yolo_then_ocr() -> None:
    """read_hand 调用 YOLO 拿 box，再用 OCR 卡名组装 HandSummary。"""
    cards = [
        CardDetection(label="cards", box=(0, 0, 100, 200), card_name="お姉さんの感覚"),
        CardDetection(label="useless", box=(100, 0, 100, 200), card_name=""),
    ]
    reader = ExamStateReader(_MockOcrPort(cards))
    hand = reader.read_hand()
    assert hand.has_oneesan_no_kankaku is True
    # お姉さんの感覚 本身是好调类卡（效果：好調6ターン），计入好调卡数；
    # useless 卡无卡名，不计入，故总数为 1（来自 OCR 命中的お姉さん）。
    assert hand.good_condition_card_count == 1


def test_reader_skips_zero_roi_numerics() -> None:
    """占位 ROI（全0）跳过 OCR，避免误读（Step3 校准前的安全行为）。"""
    reader = ExamStateReader(_MockOcrPort([]))
    numerics = reader.read_numerics()
    # 所有 ROI 当前为占位（全0），应全部跳过
    assert numerics == {}
