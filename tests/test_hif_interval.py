"""Interval 商店流决策模块单测（issue #6，取证轮 2026-08-23 输入）。

覆盖：P 点解析、保守策略（no_purchase 恒空）、buy_list 档预算过滤骨架。
実機联动（P 点余额/商品区快照落盘）由 IntervalAuto 集成，验收轮观察。
"""

from __future__ import annotations

from agent.hif.decisions.interval import (
    PurchasePolicy,
    IntervalProduct,
    IntervalShopState,
    parse_p_points,
    decide_purchase,
)


def test_parse_p_points_plain_and_comma() -> None:
    assert parse_p_points("380") == 380
    assert parse_p_points("1,000") == 1000


def test_parse_p_points_noise_returns_none() -> None:
    assert parse_p_points("P") is None
    assert parse_p_points("") is None
    assert parse_p_points("↓950") is None


def test_conservative_policy_never_buys() -> None:
    """goal 共识 5：第一版可浏览不购买——默认策略对任意商店状态恒空。"""
    state = IntervalShopState(
        p_points=380,
        products=(IntervalProduct(price=30, row=1, col=1), IntervalProduct(price=50, row=0, col=0)),
    )
    assert decide_purchase(state, PurchasePolicy()) == ()
    # 显式 no_purchase 也空
    assert decide_purchase(state, PurchasePolicy(mode="no_purchase", budget=999)) == ()


def test_buy_list_filters_by_budget() -> None:
    """grill 后扩展档骨架：预算内可负担商品入选，超预算/无价排除。"""
    state = IntervalShopState(
        p_points=100,
        products=(
            IntervalProduct(price=30, row=1, col=1),
            IntervalProduct(price=75, row=1, col=3),
            IntervalProduct(price=None, row=0, col=2),  # 价格未读出
            IntervalProduct(price=150, row=0, col=3),   # 超预算
        ),
    )
    buys = decide_purchase(state, PurchasePolicy(mode="buy_list", budget=100))
    assert [p.price for p in buys] == [30, 75]


def test_buy_list_empty_products() -> None:
    state = IntervalShopState(p_points=50)
    assert decide_purchase(state, PurchasePolicy(mode="buy_list", budget=100)) == ()


# ---------------------------------------------------------------------------
# issue #7：USE_P_DRINK 槽位匹配纯逻辑（取证 A5 定案：同名瓶多槽）
# ---------------------------------------------------------------------------


def _round1play_cls():
    import sys
    from pathlib import Path
    from importlib import import_module

    sys.path.insert(0, str(Path("agent").resolve()))
    return import_module("custom.action.produce_hif").ProduceHIFRound1Play


def test_match_drink_slot_by_normalized_name() -> None:
    """规范名匹配首个命中槽（同名瓶多槽时取槽序靠前）。"""
    cls = _round1play_cls()
    slots = [
        {"slot": 1, "xy": [60, 1215], "name": "初星黒酢", "raw": "初星黒酢"},
        {"slot": 2, "xy": [150, 1215], "name": None, "raw": None},  # 空槽
        {"slot": 3, "xy": [240, 1215], "name": "ブーストエキス", "raw": "ブーストエキス"},
    ]
    hit = cls._match_drink_slot(slots, "ブーストエキス")
    assert hit and hit["slot"] == 3


def test_match_drink_slot_raw_fallback_and_miss() -> None:
    """匹配失败的槽回退 OCR 原文语义；无匹配/空目标返回 None。"""
    cls = _round1play_cls()
    slots = [{"slot": 4, "xy": [330, 1215], "name": None, "raw": "テステーション"}]
    assert cls._match_drink_slot(slots, "テステーション")["slot"] == 4
    assert cls._match_drink_slot(slots, "初星黒酢") is None
    assert cls._match_drink_slot(slots, "") is None
    assert cls._match_drink_slot(None, "初星黒酢") is None
    # 无坐标槽不可选（xy 缺失/零点）
    assert cls._match_drink_slot([{"slot": 1, "xy": [0, 0], "raw": "初星黒酢"}], "初星黒酢") is None
