"""Interval 商店流决策模块单测（issue #6 骨架 → #22 名称级策略，grill 定案 2026-08-24）。

覆盖：P 点解析、保守策略（no_purchase 恒空）、名称级匹配命中/未命中、
P3 共识优先级顺序、留额+预算帽语义、预算不足跳过、识别失败保守退出、
补山札条件项、preset 覆盖链（GUI/override 文件）。
実機联动（详情面板名称读取件→IntervalAuto 接线）归 #24。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.hif.decisions.interval import (
    WANTED_P3_CONSENSUS,
    IntervalProduct,
    IntervalShopState,
    PurchasePolicy,
    decide_purchase,
    match_wanted,
    normalize_shop_name,
    parse_p_points,
)
from agent.hif.presets import (
    SAFE_DEFAULT_PRESET,
    apply_file_overrides,
    build_purchase_policy,
    parse_hif_preset,
)


def test_parse_p_points_plain_and_comma() -> None:
    assert parse_p_points("380") == 380
    assert parse_p_points("1,000") == 1000


def test_parse_p_points_noise_returns_none() -> None:
    assert parse_p_points("P") is None
    assert parse_p_points("") is None
    assert parse_p_points("↓950") is None


def test_conservative_policy_never_buys() -> None:
    """goal 共识 5：no_purchase 对任意商店状态恒空。"""
    state = IntervalShopState(
        p_points=380,
        products=(IntervalProduct(name="センブリソーダ", price=30, row=1, col=1),),
    )
    assert decide_purchase(state, PurchasePolicy()) == ()
    assert decide_purchase(state, PurchasePolicy(mode="no_purchase", budget=999)) == ()


def test_buy_list_requires_name() -> None:
    """名称级语义：无名商品（识别失败/未读取）不可决策，恒跳过。"""
    state = IntervalShopState(
        p_points=380,
        products=(
            IntervalProduct(price=30, row=1, col=1),  # name=None
            IntervalProduct(name=None, is_card=True, price=40, row=0, col=0),  # 有类目无名
        ),
    )
    assert decide_purchase(state, PurchasePolicy(mode="buy_list")) == ()


def test_wanted_match_hit_and_miss() -> None:
    state = IntervalShopState(
        p_points=380,
        products=(
            IntervalProduct(name="ブーストエキス", price=50, row=0, col=0),
            IntervalProduct(name="初星黒酢", price=30, row=1, col=1),  # 未在 wanted 表
        ),
    )
    buys = decide_purchase(state, PurchasePolicy(mode="buy_list"))
    assert [p.name for p in buys] == ["ブーストエキス"]


def test_wanted_priority_order() -> None:
    """P3 共识顺序：センブリソーダ 先于 ブーストエキス（即使后者更便宜）。"""
    state = IntervalShopState(
        p_points=380,
        products=(
            IntervalProduct(name="ブーストエキス", price=40, row=0, col=0),
            IntervalProduct(name="センブリソーダ", price=80, row=1, col=1),
        ),
    )
    buys = decide_purchase(state, PurchasePolicy(mode="buy_list"))
    assert [p.name for p in buys] == ["センブリソーダ", "ブーストエキス"]


def test_normalize_and_substring_match() -> None:
    """OCR 变体（长音符丢失/空格）与子串匹配。"""
    assert normalize_shop_name("センブリ ソーダ") == normalize_shop_name("センブリソーダ")  # 空格+长音符双侧归一
    assert match_wanted("センブリソーダ", WANTED_P3_CONSENSUS) == 0
    assert match_wanted("ブストエキス", WANTED_P3_CONSENSUS) == 1  # 长音符丢失变体（タン内类）
    assert match_wanted("初星黒酢", WANTED_P3_CONSENSUS) is None
    assert match_wanted(None, WANTED_P3_CONSENSUS) is None


def test_budget_reserve_semantics() -> None:
    """留额 100P：余额 380 可花 280；预算内逐件扣减。"""
    state = IntervalShopState(
        p_points=380,
        products=(
            IntervalProduct(name="センブリソーダ", price=80, row=0, col=0),
            IntervalProduct(name="ブーストエキス", price=80, row=1, col=1),
        ),
    )
    buys = decide_purchase(state, PurchasePolicy(mode="buy_list"))
    assert len(buys) == 2  # 160 ≤ 280
    # 余额紧：留额后只够一件
    state2 = IntervalShopState(
        p_points=190,  # 可花 90，只够先买一件
        products=(
            IntervalProduct(name="センブリソーダ", price=80, row=0, col=0),
            IntervalProduct(name="ブーストエキス", price=80, row=1, col=1),
        ),
    )
    assert [p.name for p in decide_purchase(state2, PurchasePolicy(mode="buy_list"))] == ["センブリソーダ"]


def test_budget_cap() -> None:
    """budget 帽：min(余额-留额, budget)。"""
    state = IntervalShopState(
        p_points=500,
        products=(IntervalProduct(name="センブリソーダ", price=80, row=0, col=0),),
    )
    assert decide_purchase(state, PurchasePolicy(mode="buy_list", budget=50)) == ()
    assert len(decide_purchase(state, PurchasePolicy(mode="buy_list", budget=80))) == 1


def test_insufficient_skips_pricey_continues() -> None:
    """预算不足跳过贵件，后面便宜命中件仍可买。"""
    state = IntervalShopState(
        p_points=150,  # 可花 50
        products=(
            IntervalProduct(name="センブリソーダ", price=80, row=0, col=0),
            IntervalProduct(name="ブーストエキス", price=40, row=1, col=1),
        ),
    )
    assert [p.name for p in decide_purchase(state, PurchasePolicy(mode="buy_list"))] == ["ブーストエキス"]


def test_missing_ppoints_conservative_exit() -> None:
    """余额未读出=快照不完整，保守空返回。"""
    state = IntervalShopState(
        p_points=None,
        products=(IntervalProduct(name="センブリソーダ", price=30, row=0, col=0),),
    )
    assert decide_purchase(state, PurchasePolicy(mode="buy_list")) == ()


def test_restock_cards_first_when_deck_short() -> None:
    """补山札条件项：deck<22 时技能卡类目最优先，补到缺口张数为限。"""
    state = IntervalShopState(
        p_points=380,
        deck_size=20,  # 缺口 2
        products=(
            IntervalProduct(name="大胆不敵", is_card=True, price=60, row=0, col=0),
            IntervalProduct(name="始まりの合図", is_card=True, price=40, row=0, col=1),
            IntervalProduct(name="始まりの合図", is_card=True, price=40, row=0, col=2),
            IntervalProduct(name="センブリソーダ", is_card=False, price=80, row=1, col=0),
        ),
    )
    buys = decide_purchase(state, PurchasePolicy(mode="buy_list"))
    assert [p.name for p in buys] == ["始まりの合図", "始まりの合図", "センブリソーダ"]  # 便宜卡先补+卡不越 quota


def test_no_restock_when_deck_sufficient_or_unknown() -> None:
    """deck≥22 或未读出：不触发类目优先，只走 wanted。"""
    products = (
        IntervalProduct(name="大胆不敵", is_card=True, price=40, row=0, col=0),
        IntervalProduct(name="センブリソーダ", is_card=False, price=80, row=1, col=0),
    )
    ok = IntervalShopState(p_points=380, deck_size=22, products=products)
    unknown = IntervalShopState(p_points=380, deck_size=None, products=products)
    for state in (ok, unknown):
        assert [p.name for p in decide_purchase(state, PurchasePolicy(mode="buy_list"))] == ["センブリソーダ"]


def test_empty_products_returns_empty() -> None:
    state = IntervalShopState(p_points=380)
    assert decide_purchase(state, PurchasePolicy(mode="buy_list")) == ()


# ---------------------------------------------------------------------------
# preset 覆盖链（#22）：GUI 注入 / override 文件 / build_purchase_policy
# ---------------------------------------------------------------------------


def test_default_preset_is_conservative_with_p3_defaults() -> None:
    """默认档：no_purchase + P3 共识默认 + 留额 100P + 补山札 22。"""
    policy = build_purchase_policy(SAFE_DEFAULT_PRESET)
    assert policy.mode == "no_purchase"
    assert policy.wanted == WANTED_P3_CONSENSUS == ("センブリソーダ", "ブーストエキス")
    assert policy.reserve == 100
    assert policy.restock_target == 22


def test_parse_preset_interval_gui_params() -> None:
    raw = json.dumps({
        "interval_purchase_mode": "buy_list",
        "interval_wanted_str": "初星黒酢、センブリソーダ",
        "interval_budget": 150,
    })
    preset = parse_hif_preset(raw)
    assert preset.interval_purchase_mode == "buy_list"
    assert preset.interval_wanted == ("初星黒酢", "センブリソーダ")
    assert preset.interval_budget == 150
    # 非法 mode 回落默认
    assert parse_hif_preset(json.dumps({"interval_purchase_mode": "buy_all"})).interval_purchase_mode == "no_purchase"


def test_file_overrides_interval(tmp_path: Path) -> None:
    """override 文件层：mode/数值/名单可配置（写 assets/data/hif/decision_override.json 同构）。"""
    override = tmp_path / "decision_override.json"
    override.write_text(json.dumps({
        "interval_purchase_mode": "buy_list",
        "interval_budget": 120,
        "interval_wanted": ["初星黒酢"],
    }, ensure_ascii=False), encoding="utf-8")
    preset = apply_file_overrides(SAFE_DEFAULT_PRESET, override)
    assert preset.interval_purchase_mode == "buy_list"
    assert preset.interval_budget == 120
    assert preset.interval_wanted == ("初星黒酢",)
    assert build_purchase_policy(preset).budget == 120


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
