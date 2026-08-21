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
