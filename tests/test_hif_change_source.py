"""変卡源卡选择纯逻辑单测（grill 共识 2026-08-21，実機校准值驱动）。

覆盖 ProduceChooseHIFSelectChangeSourceAuto 的名单优先/fallback/去重，与
presets.validate_select_change_source_names 的启动校验三态。
"""

from __future__ import annotations

import sys
from pathlib import Path
from importlib import import_module


def _load_modules():
    # 与 test_hif_session_state.py 相同的加载方式：agent/ 进 sys.path 以满足 produce_hif 内 `from utils import logger`
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        produce_hif = import_module("agent.custom.action.produce_hif")
        presets = import_module("agent.hif.presets")
        return produce_hif, presets
    finally:
        sys.path.remove(agent_path)


_produce_hif, _presets = _load_modules()
Src = _produce_hif.ProduceChooseHIFSelectChangeSourceAuto
validate_select_change_source_names = _presets.validate_select_change_source_names


def _entry(name: str, screen: int = 0, cell: str = "s0r1c1") -> dict:
    return {"screen": screen, "cell": cell, "xy": [139, 695], "name": name}


# ------------------------------------------------------------------
# _pick_source_by_list（Q3 裁决：名单优先 → 非トラブル第一格 fallback）
# ------------------------------------------------------------------


def test_pick_source_named_first_priority_wins():
    deck = [_entry("夏夜に咲く思い出"), _entry("大胆不敵", screen=1), _entry("始まりの合図", screen=1)]
    chosen = Src._pick_source_by_list(("大胆不敵", "始まりの合図"), deck)
    assert chosen is not None and chosen["name"] == "大胆不敵"


def test_pick_source_named_second_when_first_missing():
    deck = [_entry("夏夜に咲く思い出"), _entry("始まりの合図", screen=1)]
    chosen = Src._pick_source_by_list(("大胆不敵", "始まりの合図"), deck)
    assert chosen is not None and chosen["name"] == "始まりの合図"


def test_pick_source_fallback_first_cell_on_miss():
    deck = [_entry("夏夜に咲く思い出"), _entry("祝福")]
    chosen = Src._pick_source_by_list(("不在库里的卡",), deck)
    assert chosen is not None and chosen["name"] == "夏夜に咲く思い出" and chosen["screen"] == 0


def test_pick_source_fallback_on_empty_names():
    deck = [_entry("祝福"), _entry("存在感")]
    chosen = Src._pick_source_by_list((), deck)
    assert chosen is not None and chosen["name"] == "祝福"


def test_pick_source_empty_deck_returns_none():
    assert Src._pick_source_by_list(("大胆不敵",), []) is None


def test_pick_source_strips_plus_suffix_in_names():
    """名单配置带 + 档后缀（実機 OCR 口径）也要能匹配剥后缀后的 deck 名。"""
    deck = [_entry("大胆不敵")]
    chosen = Src._pick_source_by_list(("大胆不敵+",), deck)
    assert chosen is not None and chosen["name"] == "大胆不敵"


# ------------------------------------------------------------------
# #51 fallback 最低价值卡（実機轮 8:盲选第一格吃掉 SSR 夏夜に咲く思い出）
# ------------------------------------------------------------------


def test_fallback_lowest_score_skips_ssr():
    """名单 miss + 注入评分：SSR 保护不选，非 SSR 中效果最弱（无使用数追加）被选。"""
    hand_meta = import_module("agent.hif.decisions.hand_meta")
    assert hand_meta.get_card_meta("夏夜に咲く思い出").rarity == "Ssr"  # master 数据驱动前提

    deck = [_entry("夏夜に咲く思い出"), _entry("シュプレヒコール"), _entry("始まりの合図")]
    score = lambda text: 10 if "使用数追加" in text else 1  # noqa: E731
    chosen = Src._pick_source_by_list((), deck, fallback_score=score)
    assert chosen is not None and chosen["name"] == "始まりの合図"  # SSR 跳过+最弱效果


def test_fallback_lowest_score_all_ssr_returns_first():
    """全 SSR 极端局面：退回第一格（変卡必须选一张源，不能停）。"""
    deck = [_entry("夏夜に咲く思い出")]
    chosen = Src._pick_source_by_list((), deck, fallback_score=lambda _t: 1)
    assert chosen is not None and chosen["name"] == "夏夜に咲く思い出"


def test_fallback_lowest_score_unknown_card_not_crash():
    """master 查不到的卡（OCR 变体）：meta=None 按空文本评分，不崩。"""
    deck = [_entry("OCR誤読変体卡名"), _entry("始まりの合図")]
    chosen = Src._pick_source_by_list((), deck, fallback_score=lambda text: 0 if text == "" else 9)
    # 未知卡空文本得 0 分最低 → 被选（查不到效果=不可控,选它比选已知卡保守度见 preset 名单）
    assert chosen is not None and chosen["name"] == "OCR誤読変体卡名"


# ------------------------------------------------------------------
# _dedupe_deck（滚动重叠屏去重，Q2 全库收集配套）
# ------------------------------------------------------------------


def test_dedupe_keeps_first_occurrence():
    entries = [
        _entry("タイミングの基本"),
        _entry("演出計画"),
        _entry("タイミングの基本", screen=1),  # 滚动重叠重复
        _entry("存在感", screen=1),
    ]
    out = Src._dedupe_deck(entries)
    assert [e["name"] for e in out] == ["タイミングの基本", "演出計画", "存在感"]


def test_dedupe_skips_unread_names():
    entries = [_entry(""), _entry("祝福"), _entry("")]
    out = Src._dedupe_deck(entries)
    assert [e["name"] for e in out] == ["祝福"]


# ------------------------------------------------------------------
# 网格常量（実機 2026-08-21 校准：3 行×4 列，防手滑改坏）
# ------------------------------------------------------------------


def test_grid_constants_shape():
    assert len(Src.GRID_COLS) == 4
    assert len(Src.GRID_ROWS) == 3
    assert Src.NAME_ZONE == (60, 255, 560, 315)  # y315 以下效果行混入（実測噪声源）


# ------------------------------------------------------------------
# validate_select_change_source_names（Q9 启动校验，告警不阻断）
# ------------------------------------------------------------------


def test_validate_reports_unknown_name():
    w = validate_select_change_source_names(("存在しない卡",), {"大胆不敵", "始まりの合図"})
    assert any("not_in_dict" in x for x in w)


def test_validate_reports_trouble_card():
    w = validate_select_change_source_names(("眠気",), {"眠気"})
    assert any("trouble_card" in x for x in w)


def test_validate_clean_names_no_warning():
    w = validate_select_change_source_names(("大胆不敵", "始まりの合図"), {"大胆不敵", "始まりの合図"})
    assert w == []


def test_validate_none_dict_skips_dict_check():
    """词典不可用时降级：只做トラブル判定，不误报 not_in_dict。"""
    w = validate_select_change_source_names(("任意卡",), None)
    assert all("not_in_dict" not in x for x in w)


# ------------------------------------------------------------------
# 完整状态识别纯逻辑（grill 三层设计，2026-08-21 计划批准）
# ------------------------------------------------------------------

_play_cls = None


def _load_play():
    global _play_cls
    if _play_cls is None:
        agent_path = str(Path("agent").resolve())
        sys.path.insert(0, agent_path)
        try:
            mod = import_module("agent.custom.action.produce_hif")
            _play_cls = mod.ProduceHIFRound1Play
        finally:
            sys.path.remove(agent_path)
    return _play_cls


def test_available_drinks_from_slots_filters_empty_keeps_order():
    Play = _load_play()
    slots = [{"slot": 1, "name": "初星黒酢"}, {"slot": 2, "name": None},
             {"slot": 3, "name": "ビタミンドリンク"}, {"slot": 4, "name": None}]
    assert Play._available_drinks_from_slots(slots) == ["初星黒酢", "ビタミンドリンク"]


def test_available_drinks_empty_slots():
    assert _load_play()._available_drinks_from_slots([]) == []


def test_cluster_buff_words_same_row_tolerance():
    Play = _load_play()
    words = [
        {"text": "19ターン", "box": [55, 261, 86, 25]},
        {"text": "1回", "box": [57, 268, 42, 27]},   # y 差 7 → 同行
        {"text": "1回", "box": [57, 384, 42, 27]},   # y 差 >15 → 新行
    ]
    rows = Play._cluster_buff_words_to_rows(words)
    assert len(rows) == 2
    assert rows[0]["words"] == ["19ターン", "1回"]
    assert rows[1]["words"] == ["1回"]


def test_cluster_buff_words_real_layout():
    """実機 2026-08-21 実测行位（273/398/458/520/615 五行）聚行验证。"""
    Play = _load_play()
    words = [
        {"text": "30ターン", "box": [55, 261, 86, 25]},
        {"text": "1回", "box": [57, 390, 42, 27]},
        {"text": "回", "box": [67, 452, 30, 27]},
        {"text": "回", "box": [74, 514, 20, 19]},
        {"text": "4回", "box": [58, 605, 40, 26]},
    ]
    rows = Play._cluster_buff_words_to_rows(words)
    assert len(rows) == 5


# ------------------------------------------------------------------
# 统一面板法纯逻辑（grill 三轮共识，2026-08-21）
# ------------------------------------------------------------------


def test_merge_panel_items_counts_duplicates():
    Play = _load_play()
    items: dict = {}
    Play._merge_panel_items(items, ["スキルカード使用数追加", "集中 13"])
    Play._merge_panel_items(items, ["スキルカード使用数追加"])  # 第二屏重叠再现
    assert items == {"スキルカド使用数追加": 2, "集中 13": 1}  # 键归一化去长音符


def test_merge_panel_items_long_note_variants_merge():
    """OCR 长音符变体（ターン内/タン内）归并为同一键（probe4 round2 実証）。"""
    Play = _load_play()
    items: dict = {}
    Play._merge_panel_items(items, ["3回ターン内0回"])
    Play._merge_panel_items(items, ["3回タン内0回"])
    assert items == {"3回タン内0回": 2}


def test_extract_reprise_from_items():
    Play = _load_play()
    items = {"お姉さんの感覚+(再演)": 1, "3回ターン内0回": 1, "好調 29ターン": 1}
    assert Play._extract_reprise_from_items(items) == 3


def test_extract_reprise_missing_returns_none():
    assert _load_play()._extract_reprise_from_items({"好調 29ターン": 1}) is None


def test_extract_focus_from_items():
    Play = _load_play()
    assert Play._extract_focus_from_items({"集中 13": 1, "好調 29ターン": 1}) == 13
    assert Play._extract_focus_from_items({"好調 29ターン": 1}) is None


# ------------------------------------------------------------------
# 好調面板双保险+P 饮料槽防毒缓存（実機 2026-08-23 四轮复盘：good_condition_turns
# 此前从未被写入 session→模板 miss 时 ExamState 落假 0；P 饮料锚窄带全 null 毒缓存）
# ------------------------------------------------------------------


def test_extract_good_from_items():
    Play = _load_play()
    assert Play._extract_good_from_items({"好調 29ターン": 1, "集中 13": 1}) == 29
    assert Play._extract_good_from_items({"好調 8ターン": 1}) == 8


def test_extract_good_missing_returns_none():
    Play = _load_play()
    assert Play._extract_good_from_items({"集中 13": 1}) is None
    assert Play._extract_good_from_items({}) is None


def test_extract_good_excludes_excellent_condition():
    # 絶好調行不应被好調提取误吞（键含「好調」但语义不同）
    Play = _load_play()
    assert Play._extract_good_from_items({"絶好調 6ターン": 1}) is None
    assert Play._extract_good_from_items({"絶好調 6ターン": 1, "好調 12ターン": 1}) == 12


def test_pdrink_anchor_roi_covers_floating_title():
    # 锚带覆盖标题浮动范围（実測 y722/838；旧 80px 窄带在 y838 时恒 miss→全 null 毒缓存）
    Play = _load_play()
    x, y, w, h = Play.PDRINK_POPUP_ANCHOR_ROI
    assert y <= 722 and y + h >= 838 + 30, "锚带须覆盖标题 y722-838 浮动范围"
    assert Play.PDRINK_PROBE_MAX_ATTEMPTS >= 1, "全空探测须有整局放弃上限"


# ------------------------------------------------------------------
# #53 帧差判底（借鉴 gakumas-assistant check_frame_change：滚不动=到底）
# ------------------------------------------------------------------


def _gray_frame(value: int):
    import numpy as np
    return np.full((200, 200, 3), value, dtype=np.uint8)


def test_frames_similar_identical_frames():
    frame = _gray_frame(120)
    assert Src._frames_similar(frame, frame) is True


def test_frames_similar_near_identical_frames():
    assert Src._frames_similar(_gray_frame(120), _gray_frame(121)) is True


def test_frames_similar_scrolled_frames():
    """滚动位移哪怕一行，均值差应远超阈值判 False。"""
    import numpy as np
    frame_a = np.zeros((200, 200, 3), dtype=np.uint8)
    frame_a[100:, :] = 200  # 上半黑下半白
    frame_b = np.roll(frame_a, 40, axis=0)  # 位移 40px
    assert Src._frames_similar(frame_a, frame_b) is False


def test_frames_similar_none_inputs():
    assert Src._frames_similar(None, _gray_frame(0)) is False
    assert Src._frames_similar(_gray_frame(0), None) is False
