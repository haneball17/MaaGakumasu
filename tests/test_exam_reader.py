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

import pytest

from agent.hif.round_metrics import build_round_metrics
from agent.hif.decisions.state import ExamRound, HandSummary
from agent.hif.adapters.card_dict import (
    KEY_CARDS,
    normalize_card_name,
    build_card_name_dict,
    is_good_condition_card,
)
from agent.hif.adapters.exam_reader import (
    ReadStatus,
    NumericRead,
    CardDetection,
    ExamStateReader,
    ExamStateRejected,
    ExamStateObservation,
    _parse_numeric,
    build_exam_state,
    build_hand_summary,
    _hand_card_name_roi,
    infer_card_playability,
    _suppress_overlapping_card_detections,
)


def test_frame_saturation_playability_keeps_ambiguous_cards_unresolved() -> None:
    import numpy as np

    image = np.zeros((300, 360, 3), dtype=np.uint8)
    image[15:124, 15:105] = (180, 180, 180)
    image[15:124, 135:225] = (20, 80, 220)
    image[15:124, 255:300] = (180, 180, 180)
    image[15:124, 300:345] = (20, 80, 220)
    detections = [
        CardDetection("cards", (0, 0, 120, 200), "灰"),
        CardDetection("cards", (120, 0, 120, 200), "彩"),
        CardDetection("cards", (240, 0, 120, 200), "不确定"),
    ]

    infer_card_playability(image, detections)

    assert detections[0].playable is False
    assert detections[1].playable is True
    assert detections[2].playable is None
    assert all(detection.playability_source == "frame_saturation" for detection in detections)

# ---------------------------------------------------------------------------
# card_dict: 词典生成 + 好调卡判定
# ---------------------------------------------------------------------------


def test_card_dict_contains_key_cards() -> None:
    """OCR 词典必须包含 3 张关键卡（决策分支 1/2/3 的触发条件）。"""
    names = build_card_name_dict()
    for key in KEY_CARDS:
        assert key in names, f"词典缺失关键卡: {key}"


def test_card_dict_contains_observed_round_hand_names_without_strategy_metadata() -> None:
    names = build_card_name_dict()
    assert "仕切り直し" in names
    assert "眠気" in names
    assert "アイドル宣言" in names


def test_card_dict_dedup() -> None:
    """词典去重（skill_cards.json 卡名与关键卡重复时不重复出现）。"""
    names = build_card_name_dict()
    assert len(names) == len(set(names)), "词典存在重复卡名"


def test_is_good_condition_card() -> None:
    """好调卡判定：关键卡 + 常见卡 + 含「好調」字样。"""
    assert is_good_condition_card("自然体の魅力") is True
    assert is_good_condition_card("アピールの基礎") is True
    assert is_good_condition_card("好調ターン") is True
    assert is_good_condition_card("シュプレヒコール") is True
    assert is_good_condition_card("トラブル") is False
    assert is_good_condition_card("") is False


def test_normalize_card_name_strips_space() -> None:
    """OCR 文本去空格（日文 OCR 常插入多余空格）。"""
    assert normalize_card_name(" 自然 体 の 魅力 ") == "自然体の魅力"


def test_normalize_card_name_repairs_observed_five_card_overlap_variant() -> None:
    assert normalize_card_name("話題沸騰鳴") == "話題沸騰"


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


def test_hand_card_name_roi_uses_the_visible_bottom_caption_band() -> None:
    assert _hand_card_name_roi((49, 886, 165, 250)) == (29, 1056, 205, 80)


def test_hand_card_name_roi_does_not_expand_a_narrow_five_card_hand() -> None:
    assert _hand_card_name_roi((19, 884, 138, 250)) == (19, 1054, 138, 80)


def test_hand_detection_suppresses_a_narrow_duplicate_box_but_keeps_raw_evidence() -> None:
    detections = [
        CardDetection(label="cards", box=(49, 886, 165, 250), confidence=0.946322),
        CardDetection(label="cards", box=(265, 884, 157, 250), confidence=0.894209),
        CardDetection(label="cards", box=(383, 882, 69, 250), confidence=0.461208),
        CardDetection(label="cards", box=(482, 884, 163, 250), confidence=0.934772),
    ]

    _suppress_overlapping_card_detections(detections)

    assert [d.box for d in detections if not d.suppressed_reason] == [
        (49, 886, 165, 250),
        (265, 884, 157, 250),
        (482, 884, 163, 250),
    ]
    assert detections[2].suppressed_reason == "overlap_duplicate"


def test_hand_detection_preserves_an_existing_outside_hand_suppression() -> None:
    outside = CardDetection(label="cards", box=(92, 544, 126, 288), confidence=0.95, suppressed_reason="outside_hand_roi")
    hand = CardDetection(label="cards", box=(19, 884, 138, 250), confidence=0.9)

    _suppress_overlapping_card_detections([outside, hand])

    assert outside.suppressed_reason == "outside_hand_roi"
    assert hand.suppressed_reason == ""


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
    assert _parse_numeric("flow", "ビジュアル 3807%").flow == "Vi"


# ---------------------------------------------------------------------------
# build_exam_state: 状态组装（含降级）
# ---------------------------------------------------------------------------


def test_exam_state_rejects_missing_numerics_instead_of_inventing_zero() -> None:
    """缺失字段类型化拒绝，不能产生 deck_size=0 或默认 Vi。"""
    hand = HandSummary(
        has_shizen_no_miryoku=True,
        has_oneesan_no_kankaku=False,
        has_kokuminteki_idol=False,
        good_condition_card_count=2,
        swap_hand_available=False,
        draw_available=False,
    )
    with pytest.raises(ExamStateRejected) as caught:
        build_exam_state(hand, {}, ExamRound.HONSEN_R1, total_turns=9, stamina=80)

    assert {issue.field for issue in caught.value.issues} >= {"deck_size", "flow", "current_score", "stage_multiplier"}


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
    state = build_exam_state(
        hand,
        numerics,
        ExamRound.HONSEN_R1,
        total_turns=9,
        stamina=60,
        round_metrics=build_round_metrics(
            {"param_vo": "399277", "param_da": "304099", "param_vi": "111318", "current_score": "116611", "stage_multiplier": "3807%"}
        ),
        cards_played=3,
        oneesan_used=False,
        natural_finisher_used=False,
    )
    assert state.good_condition_turns == 12
    assert state.focus == 8
    assert state.reprise_count == 2
    assert state.turn == 5
    assert state.deck_size == 22
    assert state.current_flow == "Da"


def test_exam_state_rejects_missing_round_metrics() -> None:
    hand = HandSummary(False, False, False, 0, False, False)
    with pytest.raises(ExamStateRejected) as caught:
        build_exam_state(hand, {}, ExamRound.HONSEN_R1, total_turns=9, stamina=60)
    assert {issue.field for issue in caught.value.issues} >= {"current_score", "stage_multiplier"}


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
        "good_condition": NumericRead("good_condition", "12", 12),
        "focus": NumericRead("focus", "8", 8),
        "reprise": NumericRead("reprise", "2", 2),
        "turn": NumericRead("turn", "5", 5),
        "deck_size": NumericRead("deck_size", "22枚", 22),
        "flow": NumericRead("flow", "Da", None, flow="Da"),
        "p_drinks": NumericRead("p_drinks", "初星黒酢,パワフル漢方ドリンク", None),
    }
    state = build_exam_state(
        hand,
        numerics,
        ExamRound.HONSEN_R1,
        total_turns=9,
        stamina=10,
        round_metrics=build_round_metrics(
            {"param_vo": "399277", "param_da": "304099", "param_vi": "111318", "current_score": "116611", "stage_multiplier": "3807%"}
        ),
        cards_played=3,
        oneesan_used=False,
        natural_finisher_used=False,
    )
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
    ocr = _MockOcrPort(
        cards,
        {
            "good_condition": "47",
            "reprise": "2",
            "focus": "10",
            "turn": "6",
            "flow": "Vi",
            "deck_size": "22",
            "current_score": "116611",
            "stage_multiplier": "3807%",
        },
    )
    reader = ExamStateReader(ocr)
    with pytest.raises(ExamStateRejected) as caught:
        reader.read_exam_state(ExamRound.HONSEN_R1, total_turns=9, stamina=50)
    assert {issue.field for issue in caught.value.issues} >= {"param_vo", "param_da", "param_vi"}


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


def test_reader_only_attempts_fields_with_versioned_rois() -> None:
    """只读取已写入版本化 ROI 的字段，未校准字段继续跳过。"""
    reader = ExamStateReader(_MockOcrPort([]))
    numerics = reader.read_numerics()
    assert set(numerics) == {"good_condition", "reprise", "focus", "turn", "flow", "stamina"}
    assert all(read.value is None and read.flow is None for read in numerics.values())
    assert "p_drinks" not in numerics


def test_reader_prefers_a_verified_turn_template_over_ocr() -> None:
    class _TurnTemplatePort(_MockOcrPort):
        def run_ocr(self, name, expected, roi):
            if name.endswith("turn"):
                return "1"
            return super().run_ocr(name, expected, roi)

        def run_turn_digit_template(self):
            return "7", 0.99

    numerics = ExamStateReader(_TurnTemplatePort([])).read_numerics()

    assert numerics["turn"].value == 7
    assert numerics["turn"].status is ReadStatus.OK


def test_reader_falls_back_to_consistent_turn_ocr_without_template() -> None:
    class _TurnTemplatePort(_MockOcrPort):
        def __init__(self):
            super().__init__([])
            self.template_called = False

        def run_ocr(self, name, expected, roi):
            if name.endswith("turn"):
                return "8"
            return super().run_ocr(name, expected, roi)

        def run_turn_digit_template(self):
            self.template_called = True
            return None, 0.0

    port = _TurnTemplatePort()
    numerics = ExamStateReader(port).read_numerics()

    assert numerics["turn"].value == 8
    assert numerics["turn"].status is ReadStatus.OK
    assert port.template_called is True


def test_reader_rejects_an_unstable_numeric_read() -> None:
    class _UnstableNumericPort(_MockOcrPort):
        def __init__(self):
            super().__init__([])
            self.good_condition_reads = iter(("40ターン", "2", "3") * 3)

        def run_ocr(self, name, expected, roi):
            if name.endswith("good_condition"):
                return next(self.good_condition_reads)
            return super().run_ocr(name, expected, roi)

    numerics = ExamStateReader(_UnstableNumericPort()).read_numerics()

    assert numerics["good_condition"].value is None
    assert numerics["good_condition"].status is ReadStatus.CONFLICT
    assert numerics["good_condition"].samples == ("40ターン", "2", "3") * 3


def test_reader_accepts_two_matching_numeric_reads_when_the_third_is_empty() -> None:
    class _MostlyStableNumericPort(_MockOcrPort):
        def __init__(self):
            super().__init__([])
            self.focus_reads = iter(("M4", "", "M4") * 3)

        def run_ocr(self, name, expected, roi):
            if name.endswith("focus"):
                return next(self.focus_reads)
            return super().run_ocr(name, expected, roi)

    numerics = ExamStateReader(_MostlyStableNumericPort()).read_numerics()

    assert numerics["focus"].value == 4
    assert numerics["focus"].status is ReadStatus.OK


def test_exam_observation_exposes_missing_fields_for_execution_gate() -> None:
    """未校准 ROI 时只能影子决策，不能被自动点击层误认为完整状态。"""
    observation = ExamStateReader(_MockOcrPort([])).read_exam_observation(ExamRound.HONSEN_R1, total_turns=9, stamina=None)

    assert isinstance(observation, ExamStateObservation)
    assert observation.state is None
    assert {"hand", "stamina", "focus", "turn", "flow"}.issubset(observation.missing_fields)
    assert {"param_vo", "param_da", "param_vi", "current_score", "stage_multiplier"}.issubset(observation.missing_fields)
    assert observation.screen_confidence == 0.0


def test_exam_observation_keeps_conflict_distinct_from_missing() -> None:
    class _ConflictPort(_MockOcrPort):
        def __init__(self):
            super().__init__([])
            self.reads = iter(("21", "22", "23") * 3)

        def run_ocr(self, name, expected, roi):
            if name.endswith("good_condition"):
                return next(self.reads)
            return super().run_ocr(name, expected, roi)

    observation = ExamStateReader(_ConflictPort()).read_exam_observation(ExamRound.HONSEN_R1, 9, None)

    issue = next(issue for issue in observation.issues if issue.field == "good_condition")
    assert issue.code is ReadStatus.CONFLICT
    assert observation.state is None


def test_exam_observation_reports_grey_cards_separately() -> None:
    cards = [
        CardDetection(label="useless", box=(20, 884, 170, 250), card_name="眠気"),
        CardDetection(label="cards", box=(200, 884, 170, 250), card_name="祝福"),
    ]

    observation = ExamStateReader(_MockOcrPort(cards)).read_exam_observation(ExamRound.HONSEN_R1, 9, None)

    assert observation.grey_cards == ("眠気",)
    assert observation.unresolved_playability == ("祝福",)
    assert "hand_playability" in observation.missing_fields
