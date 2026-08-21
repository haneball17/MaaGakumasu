"""出牌状态适配层单测（ExamStateReader）。

覆盖纯逻辑组装函数 + mock OcrPort 的端到端组装验证。
所有测试离线可跑，不依赖 maafw Context 或模拟器。

关键场景：
- build_hand_summary: 3张关键卡判定 / 好调卡计数 / OCR误识修正
- build_exam_state: 数值缺失降级 / Pドリンク解析 / flow提取 / session 注入（C1）
- _parse_numeric: 整数解析 / flow识别（日文全称 B2）/ 解析失败
- ExamStateReader: 注入mock OcrPort 验证协调逻辑 / 体力归属（B6）
- ROUND1_PLAY_RECORD_FIELDS: 落盘 schema 对齐 roundsim ManualTurnRecord（F3）
"""

from __future__ import annotations

import sys
from pathlib import Path
from importlib import import_module

from agent.hif.decisions.state import (
    ROUND1_PLAY_RECORD_FIELDS,
    ExamRound,
    ExamState,
    ActionKind,
    CardAction,
    HandSummary,
)
from agent.hif.roundsim.adapter import ManualTurnRecord
from agent.hif.adapters.card_dict import (
    KEY_CARDS,
    normalize_card_name,
    build_card_name_dict,
    is_good_condition_card,
)
from agent.hif.adapters.exam_reader import (
    _NUMERIC_ROI,
    NumericROI,
    NumericRead,
    CardDetection,
    ExamStateReader,
    _parse_numeric,
    build_exam_state,
    build_hand_summary,
    filter_card_detections,
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


def test_is_good_condition_card_effects_pool_hit() -> None:
    """B4 效果池命中：skill_card_effects.json 带 ExamParameterBuff 族 buff:good_condition
    效果的卡判 True（档位变体剥 + 号查基础名）。"""
    assert is_good_condition_card("パンプアップ") is True
    assert is_good_condition_card("軽い足取り") is True
    assert is_good_condition_card("軽い足取り+") is True  # 档位变体
    assert is_good_condition_card("お姉さんの感覚") is True  # 池内带好調 buff 的关键卡


def test_is_good_condition_card_pool_miss_falls_back() -> None:
    """B4 fallback：池外卡（「〜の基礎」系基础卡不在 sync 池内）走硬编码名单判 True。"""
    assert is_good_condition_card("アピールの基礎") is True  # COMMON 名单 fallback
    assert is_good_condition_card("ダンスの基礎") is True


def test_is_good_condition_card_pool_negative() -> None:
    """B4 池内判负：在池中且无好调 buff、名单/字样也不沾的卡判 False（不因池外名单误判）。"""
    # 「アピールの基本」在池内（仅 score:parameter_add，无 buff:good_condition），
    # 与硬编码名单的「アピールの基礎」（旧 wiki 命名，池外）不同名 → 两者皆 miss
    assert is_good_condition_card("アピールの基本") is False
    assert is_good_condition_card("眠気") is False  # Trouble 卡，池内无好调效果


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


def test_hand_summary_key_card_with_plus_suffix() -> None:
    """実機 2026-08-21 漏检修复：带档位 + 后缀的关键卡名命中三标志。

    実機 OCR 读出的卡名带档位后缀（「自然体の魅力+」等），此前精确列表
    成员检查全部 miss → 决策分支 1/2/3 系统性失效。
    """
    detections = [
        CardDetection(label="cards", box=(0, 0, 150, 250), card_name="自然体の魅力+"),
        CardDetection(label="cards", box=(150, 0, 150, 250), card_name="お姉さんの感覚+"),
        CardDetection(label="cards", box=(300, 0, 150, 250), card_name="国民的アイドル+"),
    ]
    hand = build_hand_summary(detections)
    assert hand.has_shizen_no_miryoku is True
    assert hand.has_oneesan_no_kankaku is True
    assert hand.has_kokuminteki_idol is True


def test_hand_summary_key_card_plain_still_matches() -> None:
    """向后兼容：剥 + 后缀匹配不影响無印卡名命中（决策分支照常触发）。"""
    detections = [
        CardDetection(label="cards", box=(0, 0, 150, 250), card_name="国民的アイドル"),
    ]
    hand = build_hand_summary(detections)
    assert hand.has_kokuminteki_idol is True
    assert hand.has_shizen_no_miryoku is False


def test_hand_summary_plus_suffix_no_false_positive() -> None:
    """剥 + 后缀不误命中无关卡：带 + 的其他卡不触发三标志。"""
    detections = [
        CardDetection(label="cards", box=(0, 0, 150, 250), card_name="アピールの基礎+"),
        CardDetection(label="cards", box=(150, 0, 150, 250), card_name="国民的アイドル+"),
    ]
    hand = build_hand_summary(detections)
    assert hand.has_shizen_no_miryoku is False
    assert hand.has_oneesan_no_kankaku is False
    assert hand.has_kokuminteki_idol is True  # 仅同名基础卡命中


# ---------------------------------------------------------------------------
# filter_card_detections: YOLO 检测框去重过滤（実機 2026-08-21 取证修复）
# ---------------------------------------------------------------------------


def test_filter_card_detections_dedup_same_card() -> None:
    """同卡重复框去重：中心横向距离 <60px 视为同卡，保留高分框（低分 ~0.61 実機例）。"""
    high = CardDetection(label="cards", box=(100, 900, 150, 250), card_name="自然体の魅力", score=0.92)
    low = CardDetection(label="cards", box=(105, 905, 148, 245), card_name="", score=0.61)
    result = filter_card_detections([low, high])
    assert result == [high]  # 高分框胜出，返回保持输入顺序


def test_filter_card_detections_keeps_adjacent_cards() -> None:
    """相邻不同卡（中心横向距离 ≥60px，正常卡宽 130~185）不被误去重。"""
    cards = [
        CardDetection(label="cards", box=(0, 900, 140, 250), card_name="A", score=0.9),
        CardDetection(label="cards", box=(150, 900, 140, 250), card_name="B", score=0.85),
        CardDetection(label="cards", box=(300, 900, 140, 250), card_name="C", score=0.8),
    ]
    assert filter_card_detections(cards) == cards  # 中心间距 150px，全部保留


def test_filter_card_detections_drops_narrow_boxes() -> None:
    """过窄误检框（宽 <90px）丢弃，即便 score 更高（宽度检查优先于去重）。"""
    normal = CardDetection(label="cards", box=(100, 900, 150, 250), card_name="A", score=0.9)
    narrow = CardDetection(label="cards", box=(400, 900, 60, 250), card_name="", score=0.95)
    assert filter_card_detections([normal, narrow]) == [normal]


def test_filter_card_detections_empty() -> None:
    """空输入安全返回空列表。"""
    assert filter_card_detections([]) == []


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


def test_parse_numeric_turn_noise_hardened() -> None:
    """turn ROI 実機杂讯加固（Phase 2 取证 2026-08-21）：首个连续数字段提取。

    実機 turn ROI 内偶现「M」「•」纯文字杂讯（跳过）；带尾随标点「6）」
    正确取 6；空文本不抛异常。
    """
    assert _parse_numeric("turn", "9").value == 9
    assert _parse_numeric("turn", "8").value == 8
    assert _parse_numeric("turn", "6）").value == 6  # 带尾随全角括号
    assert _parse_numeric("turn", "M").value is None  # 纯文字杂讯
    assert _parse_numeric("turn", "").value is None  # 空文本


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
    """占位 ROI（全0）跳过 OCR，避免误读；実機校准项（turn/stamina/flow）会尝试读取。"""
    reader = ExamStateReader(_MockOcrPort([]))
    numerics = reader.read_numerics()
    # Phase 2 実機校准（2026-08-21）后 turn/stamina/flow 有真实 ROI，会尝试
    # 读取（mock 无文本 → 解析失败不抛异常）；其余（good_condition/reprise/
    # focus/deck_size/p_drinks）仍为占位全 0，应跳过。
    assert set(numerics.keys()) == {"turn", "stamina", "flow"}
    assert all(v.value is None and v.flow is None for v in numerics.values())


# ---------------------------------------------------------------------------
# _parse_numeric flow 日文映射（B2：実機画面只显示日文全称）
# ---------------------------------------------------------------------------


def test_parse_numeric_flow_japanese_text() -> None:
    """flow 日文全称映射：ビジュアル→Vi / ボーカル→Vo / ダンス→Da（実機带百分号数字）。"""
    assert _parse_numeric("flow", "ビジュアル 3807%").flow == "Vi"
    assert _parse_numeric("flow", "ボーカル 2480%").flow == "Vo"
    assert _parse_numeric("flow", "ダンス 1902%").flow == "Da"


def test_parse_numeric_flow_japanese_priority_and_miss() -> None:
    """日文全称优先；英文缩写保留兼容；两者皆无时 flow=None。"""
    assert _parse_numeric("flow", "ダンス流").flow == "Da"
    assert _parse_numeric("flow", "Vo").flow == "Vo"
    assert _parse_numeric("flow", "なし").flow is None


# ---------------------------------------------------------------------------
# read_exam_state 体力归属（B6：显式传参 > 画面 numerics > 回退 0）
# ---------------------------------------------------------------------------


def test_reader_stamina_explicit_param_wins(monkeypatch) -> None:
    """显式 stamina 传参优先，覆盖画面 numerics 读值。"""
    monkeypatch.setitem(_NUMERIC_ROI, "stamina", NumericROI("体力", (553, 204, 115, 55)))
    ocr = _MockOcrPort([], {"stamina": "50/100"})
    state = ExamStateReader(ocr).read_exam_state(ExamRound.HONSEN_R1, total_turns=9, stamina=80)
    assert state.stamina == 80


def test_reader_stamina_none_reads_numerics(monkeypatch) -> None:
    """stamina=None 时从画面 numerics 读取（ROI 校准后的目标行为）。"""
    monkeypatch.setitem(_NUMERIC_ROI, "stamina", NumericROI("体力", (553, 204, 115, 55)))
    ocr = _MockOcrPort([], {"stamina": "50/100"})
    state = ExamStateReader(ocr).read_exam_state(ExamRound.HONSEN_R1, total_turns=9)
    assert state.stamina == 50  # 「50/100」取首个数字段


def test_reader_stamina_none_falls_back_to_zero() -> None:
    """stamina=None 且画面读不到（mock OCR 返回空）时回退 0，不抛异常。"""
    state = ExamStateReader(_MockOcrPort([])).read_exam_state(ExamRound.HONSEN_R1, total_turns=9)
    assert state.stamina == 0


def test_reader_read_exam_state_injects_session() -> None:
    """C1 透传：read_exam_state 的 session 参数直达 build_exam_state（Phase 2 单调用链）。"""
    state = ExamStateReader(_MockOcrPort([])).read_exam_state(
        ExamRound.HONSEN_R1,
        total_turns=9,
        session={"cards_played": 4, "oneesan_used": True, "reprise_count": 2},
    )
    assert state.cards_played == 4
    assert state.oneesan_used is True
    assert state.reprise_count == 2  # numerics 无 reprise（占位 ROI 跳过）→ session 兜底
    # 不传 session 保持旧默认行为
    state_default = ExamStateReader(_MockOcrPort([])).read_exam_state(ExamRound.HONSEN_R1, total_turns=9)
    assert state_default.cards_played == 0
    assert state_default.oneesan_used is False


# ---------------------------------------------------------------------------
# build_exam_state session 注入（C1：round1 跨回合字段）
# ---------------------------------------------------------------------------


def test_exam_state_session_injects_cross_turn_fields() -> None:
    """session（round1 子树）注入跨回合字段；numerics 无 reprise 时 session 兜底。"""
    hand = HandSummary(
        has_shizen_no_miryoku=False,
        has_oneesan_no_kankaku=False,
        has_kokuminteki_idol=False,
        good_condition_card_count=0,
        swap_hand_available=False,
        draw_available=False,
    )
    session = {
        "cards_played": 5,
        "oneesan_used": True,
        "natural_finisher_used": True,
        "reprise_count": 3,
    }
    state = build_exam_state(hand, {}, ExamRound.HONSEN_R1, total_turns=9, stamina=40, session=session)
    assert state.cards_played == 5
    assert state.oneesan_used is True
    assert state.natural_finisher_used is True
    assert state.reprise_count == 3


def test_exam_state_session_none_keeps_defaults() -> None:
    """session=None 行为与旧版完全一致（跨回合字段默认 0/False）。"""
    hand = HandSummary(
        has_shizen_no_miryoku=False,
        has_oneesan_no_kankaku=False,
        has_kokuminteki_idol=False,
        good_condition_card_count=0,
        swap_hand_available=False,
        draw_available=False,
    )
    state = build_exam_state(hand, {}, ExamRound.HONSEN_R1, total_turns=9, stamina=40, session=None)
    assert state.cards_played == 0
    assert state.oneesan_used is False
    assert state.natural_finisher_used is False
    assert state.reprise_count == 0


def test_exam_state_reprise_numerics_wins_over_session() -> None:
    """reprise 画面优先（Q6 真值源）：numerics 有值（含 0）时 session 的 reprise_count 不生效。"""
    hand = HandSummary(
        has_shizen_no_miryoku=False,
        has_oneesan_no_kankaku=False,
        has_kokuminteki_idol=False,
        good_condition_card_count=0,
        swap_hand_available=False,
        draw_available=False,
    )
    state = build_exam_state(
        hand, {"reprise": NumericRead("reprise", "2", 2)}, ExamRound.HONSEN_R1,
        total_turns=9, stamina=40, session={"reprise_count": 4},
    )
    assert state.reprise_count == 2
    # 画面读到 0 也是真值，优先于 session
    state0 = build_exam_state(
        hand, {"reprise": NumericRead("reprise", "0", 0)}, ExamRound.HONSEN_R1,
        total_turns=9, stamina=40, session={"reprise_count": 4},
    )
    assert state0.reprise_count == 0
    # 画面解析失败（value=None）→ session 兜底
    state_missing = build_exam_state(
        hand, {"reprise": NumericRead("reprise", "不明", None)}, ExamRound.HONSEN_R1,
        total_turns=9, stamina=40, session={"reprise_count": 4},
    )
    assert state_missing.reprise_count == 4


# ---------------------------------------------------------------------------
# F3 出牌落盘 schema：对齐 roundsim ManualTurnRecord
# ---------------------------------------------------------------------------


def test_round1_play_record_fields_align_manual_turn_record() -> None:
    """出牌记录 schema：前六项与 ManualTurnRecord 逐一对齐，后五项为実機执行层扩展。"""
    manual_fields = tuple(ManualTurnRecord.model_fields.keys())
    assert ROUND1_PLAY_RECORD_FIELDS[: len(manual_fields)] == manual_fields
    assert ROUND1_PLAY_RECORD_FIELDS[len(manual_fields):] == ("action", "target_card", "reason", "dry_run", "evidence")


def _load_produce_hif_module():
    # 与 test_hif_session_state.py 相同的加载方式：agent/ 进 sys.path 以满足 produce_hif 内 `from utils import logger`
    agent_path = str(Path(__file__).resolve().parents[1] / "agent")
    sys.path.insert(0, agent_path)
    try:
        return import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)


def _build_state() -> ExamState:
    """构造带跨回合字段的 ExamState（F3 记录组装测试输入）。"""
    hand = HandSummary(
        has_shizen_no_miryoku=False,
        has_oneesan_no_kankaku=True,
        has_kokuminteki_idol=False,
        good_condition_card_count=1,
        swap_hand_available=False,
        draw_available=False,
    )
    return ExamState(
        round=ExamRound.HONSEN_R1,
        turn=3,
        total_turns=9,
        current_flow="Vi",
        good_condition_turns=6,
        focus=4,
        stamina=52,
        hand=hand,
        reprise_count=1,
        cards_played=7,
        deck_size=14,
        oneesan_used=True,
        natural_finisher_used=False,
        available_p_drinks=["初星黒酢"],
    )


def test_build_round1_play_record_schema_and_values() -> None:
    """F3 build_round1_play_record：字段序与 ROUND1_PLAY_RECORD_FIELDS 一致，值正确映射。"""
    produce_hif = _load_produce_hif_module()
    state = _build_state()
    action = CardAction(kind=ActionKind.PLAY_CARD, target_card="お姉さんの感覚", reason="分支3 循环启动")
    record = produce_hif._ProduceHIFActionBase.build_round1_play_record(
        state,
        action,
        played_cards=["お姉さんの感覚"],
        turn_score=52000,
        dry_run=True,
        evidence={"target_box": [100, 200, 120, 240], "ocr_text": "お姉さんの感覚"},
    )
    assert tuple(record.keys()) == ROUND1_PLAY_RECORD_FIELDS
    assert record["turn"] == 3
    assert record["flow"] == "Vi"
    assert record["played_cards"] == ["お姉さんの感覚"]
    assert record["good_condition_turns"] == 6
    assert record["stamina"] == 52
    assert record["turn_score"] == 52000
    assert record["action"] == "play_card"
    assert record["target_card"] == "お姉さんの感覚"
    assert record["reason"] == "分支3 循环启动"
    assert record["dry_run"] is True
    assert record["evidence"]["target_box"] == [100, 200, 120, 240]


def test_build_round1_play_record_defaults_explicit() -> None:
    """F3 缺省参数显式落 None/[]/{}（JSONL schema 稳定，「未记录」可辨）。"""
    produce_hif = _load_produce_hif_module()
    state = _build_state()
    action = CardAction(kind=ActionKind.SKIP, target_card=None, reason="无关键卡")
    record = produce_hif._ProduceHIFActionBase.build_round1_play_record(state, action)
    assert record["played_cards"] == []
    assert record["turn_score"] is None
    assert record["dry_run"] is False
    assert record["evidence"] == {}
    assert record["action"] == "skip"


def test_archive_round1_play_reorders_and_delegates(monkeypatch, tmp_path) -> None:
    """F3 _archive_round1_play：乱序/缺键入参重排为 schema 序后委托 _archive_decision。"""
    produce_hif = _load_produce_hif_module()
    base = produce_hif._ProduceHIFActionBase
    captured: dict = {}
    monkeypatch.setattr(base, "_archive_decision", staticmethod(lambda image, screen_state, record: captured.update({
        "image": image, "screen_state": screen_state, "record": record,
    })))
    # 乱序 + extra 键入参
    base._archive_round1_play("fake-image", {"reason": "x", "turn": 5, "extra_note": "retry"})
    assert captured["screen_state"] == base.ROUND1_PLAY_SCREEN == "round1_play"
    keys = tuple(captured["record"].keys())
    assert keys[: len(ROUND1_PLAY_RECORD_FIELDS)] == ROUND1_PLAY_RECORD_FIELDS
    assert captured["record"]["turn"] == 5
    assert captured["record"]["turn_score"] is None  # 缺键补 None
    assert captured["record"]["extra_note"] == "retry"  # extra 键保留在后
