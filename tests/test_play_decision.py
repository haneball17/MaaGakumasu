"""ガラクタロード姫崎莉波出牌策略单测。

从原 Maa-gakumas-bot 仓库 tests/unit/test_garakuta_rinami_strategy.py 移植：
- 测试逻辑原样保留（17 个测试覆盖 7 条启发式分支 + 边界）
- 仅改 import 路径 + 配置构造方式（pydantic → 纯 dataclass）
- 确保决策大脑迁移后行为可测、可回归

所有测试为纯逻辑，不依赖 MaaFrame 或模拟器，离线可跑。
"""

from __future__ import annotations

from agent.hif.decisions.play import (
    CARD_KOKUMINTEKI_IDOL,
    CARD_SHIZEN_NO_MIRYOKU,
    CARD_ONEESAN_NO_KANKAKU,
    GarakutaRinamiStrategy,
)
from agent.hif.decisions.state import (
    ParamSet,
    ExamRound,
    ExamState,
    ActionKind,
    HandSummary,
    JudgeThreshold,
    JudgeThresholds,
)
from agent.hif.decisions.config import HonisenConfig, RepriseConfig, ProfilePayload

# ---------------------------------------------------------------------------
# 构造工厂
# ---------------------------------------------------------------------------


def make_payload(**overrides: object) -> ProfilePayload:
    """构造ガラクタロード默认 payload（好调门槛 4/12、再演上限 4、deck 目标 22）。"""
    payload = ProfilePayload.default()
    # 按 overrides 增量覆盖（支持嵌套 reprise/honisen 字典替换）。
    if "reprise" in overrides:
        payload.reprise = RepriseConfig(**overrides["reprise"])  # type: ignore[arg-type]
    if "honisen" in overrides:
        payload.honisen = HonisenConfig(**overrides["honisen"])  # type: ignore[arg-type]
    for key in ("plan", "recommend_effect", "flows", "p_drink_priority", "focus_r1"):
        if key in overrides:
            setattr(payload, key, overrides[key])  # type: ignore[arg-type]
    return payload


def make_hand(**overrides: object) -> HandSummary:
    """构造手牌摘要，默认不含关键卡但有好调卡与抽换手段。"""
    base: dict[str, object] = {
        "has_shizen_no_miryoku": False,
        "has_oneesan_no_kankaku": False,
        "has_kokuminteki_idol": False,
        "good_condition_card_count": 2,
        "swap_hand_available": True,
        "draw_available": True,
    }
    base.update(overrides)
    return HandSummary(**base)  # type: ignore[arg-type]


def make_state(**overrides: object) -> ExamState:
    """构造本戦ラウンド1 中盘的默认状态（params/judge_thresholds 默认空）。"""
    base: dict[str, object] = {
        "round": ExamRound.HONSEN_R1,
        "turn": 1,
        "total_turns": 9,
        "current_flow": "Vi",
        "good_condition_turns": 6,
        "focus": 10,
        "stamina": 80,
        "hand": make_hand(),
        "reprise_count": 0,
        "cards_played": 0,
        "deck_size": 22,
        "oneesan_used": False,
        "natural_finisher_used": False,
        "available_p_drinks": [],
    }
    base.update(overrides)
    return ExamState(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 分支 1：终结技（含 E1 可行性检查 + 收尾窗口）
# ---------------------------------------------------------------------------


def test_finisher_fires_when_good_condition_met() -> None:
    """好调≥12 + 手牌有自然体 + 未用过 + 集中≥5 → 发动自然体の魅力收尾。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=12,
        hand=make_hand(has_shizen_no_miryoku=True),
    )
    action = strategy.decide(state)
    assert action.kind is ActionKind.PLAY_CARD
    assert action.target_card == CARD_SHIZEN_NO_MIRYOKU
    assert "1000%" in action.reason


def test_finisher_skipped_when_already_used() -> None:
    """自然体の魅力本レッスン已用则不再建议终结技。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=12,
        hand=make_hand(has_shizen_no_miryoku=True),
        natural_finisher_used=True,
    )
    action = strategy.decide(state)
    assert action.target_card != CARD_SHIZEN_NO_MIRYOKU


def test_finisher_skipped_when_focus_insufficient() -> None:
    """集中<5（自然体消耗 5 集中）时不应建议终结技，避免非法出牌。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=12,
        focus=3,
        hand=make_hand(has_shizen_no_miryoku=True),
    )
    action = strategy.decide(state)
    assert action.target_card != CARD_SHIZEN_NO_MIRYOKU


def test_finisher_blocked_outside_window() -> None:
    """配置 finisher_window=2 时，未进入收尾窗口不终结技。"""
    strategy = GarakutaRinamiStrategy(
        make_payload(reprise={"max": 4, "good_cond_gate": 4, "finisher_gate": 12, "finisher_window": 2})
    )
    state = make_state(
        turn=6,
        total_turns=9,
        good_condition_turns=12,
        hand=make_hand(has_shizen_no_miryoku=True),
    )
    action = strategy.decide(state)
    assert action.target_card != CARD_SHIZEN_NO_MIRYOKU


def test_finisher_fires_inside_window() -> None:
    """配置 finisher_window=2 时，进入窗口（turn >= total-2）可终结技。"""
    strategy = GarakutaRinamiStrategy(
        make_payload(reprise={"max": 4, "good_cond_gate": 4, "finisher_gate": 12, "finisher_window": 2})
    )
    state = make_state(
        turn=7,
        total_turns=9,
        good_condition_turns=12,
        hand=make_hand(has_shizen_no_miryoku=True),
    )
    action = strategy.decide(state)
    assert action.target_card == CARD_SHIZEN_NO_MIRYOKU


# ---------------------------------------------------------------------------
# 分支 2：国民的铺垫（E1 新增）
# ---------------------------------------------------------------------------


def test_kokuminteki_setup_when_below_finisher_gate() -> None:
    """好调未到收尾线 + 手牌有国民的アイドル + 已达基础门槛 → 打国民的铺垫。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=8,
        hand=make_hand(has_kokuminteki_idol=True),
    )
    action = strategy.decide(state)
    assert action.target_card == CARD_KOKUMINTEKI_IDOL


def test_kokuminteki_skipped_below_base_gate() -> None:
    """好调未达基础门槛时不打国民的铺垫（避免无意义消耗）。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=3,
        hand=make_hand(has_kokuminteki_idol=True),
    )
    action = strategy.decide(state)
    assert action.target_card != CARD_KOKUMINTEKI_IDOL


# ---------------------------------------------------------------------------
# 分支 3：序盤お姉さんの感覚（含 E1 体力可行性）
# ---------------------------------------------------------------------------


def test_oneesan_played_early_to_drive_reprise() -> None:
    """好调≥4 + 手牌有お姉さん + 再演未满 + 未用过 + 体力≥6 → 尽早发动。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=5,
        hand=make_hand(has_oneesan_no_kankaku=True),
    )
    action = strategy.decide(state)
    assert action.kind is ActionKind.PLAY_CARD
    assert action.target_card == CARD_ONEESAN_NO_KANKAKU


def test_oneesan_blocked_when_good_condition_below_gate() -> None:
    """好调<4 时不可发动お姉さん，应退到默认分支。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=3,
        hand=make_hand(has_oneesan_no_kankaku=True),
    )
    action = strategy.decide(state)
    assert action.target_card != CARD_ONEESAN_NO_KANKAKU


def test_oneesan_blocked_when_reprise_maxed() -> None:
    """再演已满 4 次则不再驱动お姉さん。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=6,
        hand=make_hand(has_oneesan_no_kankaku=True),
        reprise_count=4,
    )
    action = strategy.decide(state)
    assert action.target_card != CARD_ONEESAN_NO_KANKAKU


def test_oneesan_skipped_when_stamina_insufficient() -> None:
    """体力<6（お姉さん消耗 6 体力）时不应建议打お姉さん，避免非法出牌。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        good_condition_turns=5,
        stamina=3,
        hand=make_hand(has_oneesan_no_kankaku=True),
    )
    action = strategy.decide(state)
    assert action.target_card != CARD_ONEESAN_NO_KANKAKU


# ---------------------------------------------------------------------------
# 分支 4：压缩山札（M4 修复 3：打出抽卡系/换牌系效果的卡，実機无独立按钮）
# ---------------------------------------------------------------------------


def test_play_draw_card_when_shizen_missing() -> None:
    """再演未满 + 手牌无自然体 + 手牌有抽卡系卡(スポットライト)→ 打出它压缩。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(hand=make_hand(has_shizen_no_miryoku=False, card_names=("スポットライト", "アドリブ")))
    action = strategy.decide(state)
    assert action.kind is ActionKind.PLAY_CARD
    assert action.target_card == "スポットライト"


def test_compression_skipped_when_no_draw_card() -> None:
    """手牌无抽卡系效果卡时不虚构压缩动作，落到后续分支（好调默认/兜底 Skip）。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(hand=make_hand(has_shizen_no_miryoku=False, card_names=("アドリブ",)))
    action = strategy.decide(state)
    assert action.kind is not ActionKind.DRAW
    assert action.kind is not ActionKind.SWAP_HAND


# ---------------------------------------------------------------------------
# 分支 5：ラウンド1 不惜药
# ---------------------------------------------------------------------------


def test_p_drink_when_stamina_low_in_round1() -> None:
    """ラウンド1 + 体力告急 + 持有优先 P ドリンク → 不惜药。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        stamina=15,
        available_p_drinks=["初星黒酢"],
        hand=make_hand(good_condition_card_count=0, draw_available=False, swap_hand_available=False),
    )
    action = strategy.decide(state)
    assert action.kind is ActionKind.USE_P_DRINK
    assert action.target_card == "初星黒酢"


def test_p_drink_skipped_in_round2() -> None:
    """ラウンド2 不触发注力惜药策略（focus_r1 仅限ラウンド1）。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        round=ExamRound.HONSEN_R2,
        total_turns=12,
        stamina=15,
        available_p_drinks=["初星黒酢"],
        hand=make_hand(good_condition_card_count=0, draw_available=False, swap_hand_available=False),
    )
    action = strategy.decide(state)
    assert action.kind is not ActionKind.USE_P_DRINK


def test_p_drink_respects_priority_order() -> None:
    """仅持有次优先 P ドリンク时按优先级顺序选择实际持有的那个。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        stamina=10,
        available_p_drinks=["パワフル漢方ドリンク"],
        hand=make_hand(good_condition_card_count=0, draw_available=False, swap_hand_available=False),
    )
    action = strategy.decide(state)
    assert action.target_card == "パワフル漢方ドリンク"


# ---------------------------------------------------------------------------
# 分支 6/7：默认（含 E1 参数感知）与兜底
# ---------------------------------------------------------------------------


def test_default_play_good_condition_card() -> None:
    """无特殊触发时默认出好调卡（凑再抽牌 + 抬高自然体加成）。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(reprise_count=4, hand=make_hand(good_condition_card_count=3))
    action = strategy.decide(state)
    assert action.kind is ActionKind.PLAY_CARD
    assert action.target_card is None
    assert "好调" in action.reason


def test_default_reason_warns_when_param_below_delta() -> None:
    """当前流参数低于 △ 阈值时，默认出牌理由附参数告警。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        reprise_count=4,
        current_flow="Vi",
        params=ParamSet(visual=100),
        judge_thresholds=JudgeThresholds(flow1=JudgeThreshold(delta=200)),
        hand=make_hand(good_condition_card_count=2),
    )
    action = strategy.decide(state)
    assert action.kind is ActionKind.PLAY_CARD
    assert "△" in action.reason
    assert "拖累" in action.reason


def test_default_reason_no_false_alarm_when_delta_unset() -> None:
    """△ 阈值未配置（=0）时不误报告警，仅给出流倾向提示。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        reprise_count=4,
        current_flow="Vi",
        params=ParamSet(visual=0),
        hand=make_hand(good_condition_card_count=2),
    )
    action = strategy.decide(state)
    assert "△" not in action.reason
    assert "Vi" in action.reason


def test_fallback_skip_when_no_good_card() -> None:
    """无好调卡且无特殊触发时兜底 Skip 回体 2（M4 修复 3：実機无独立抽牌按钮）。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        reprise_count=4,
        hand=make_hand(good_condition_card_count=0, draw_available=True),
    )
    action = strategy.decide(state)
    assert action.kind is ActionKind.SKIP


# ---------------------------------------------------------------------------
# 风险提示
# ---------------------------------------------------------------------------


def test_deck_below_target_adds_warning_prefix() -> None:
    """山札低于目标张数时决策理由附带 HIF 応援棒警告。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(deck_size=18, reprise_count=4, hand=make_hand(good_condition_card_count=2))
    action = strategy.decide(state)
    assert "HIF応援棒" in action.reason


def test_strategy_satisfies_protocol() -> None:
    """插件满足角色策略协议（plan/recommend_effect/decide 齐备）。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    assert strategy.plan == "sense"
    assert strategy.recommend_effect == "集中"
    assert isinstance(strategy.decide(make_state()).kind, ActionKind)


# ---------------------------------------------------------------------------
# M4 修复：pick_playable_card 具体选卡 + 低体力 Skip 回退
# ---------------------------------------------------------------------------


def test_pick_playable_card_prefers_good_grant_then_low_cost() -> None:
    """默认选卡排序:好調付与值高 > 体力消耗低 > 不卡手(即得分高)。"""
    from agent.hif.decisions.play import pick_playable_card

    # 深呼吸(好調3T,集中+2,体力0)vs 軽い足取り(好調2T,体力4)vs ステージングの基本(无好調,即得分)
    state = make_state(hand=make_hand(card_names=("ステージングの基本", "軽い足取り", "深呼吸")))
    assert pick_playable_card(state) == "深呼吸"
    state2 = make_state(hand=make_hand(card_names=("軽い足取り", "アドリブ")))  # 好調2T vs 好調3T(アドリブ)
    assert pick_playable_card(state2) == "アドリブ"


def test_pick_playable_card_excludes_key_and_gated_cards() -> None:
    """关键三卡与门槛卡(自然体/お姉さん/国民的/ペース配分)不进默认选卡。"""
    from agent.hif.decisions.play import pick_playable_card

    state = make_state(hand=make_hand(card_names=("自然体の魅力", "ペース配分", "軽い足取り")))
    assert pick_playable_card(state) == "軽い足取り"


def test_pick_playable_card_returns_none_without_names() -> None:
    """OCR 未读到卡名(card_names 空)→ None,由执行层兜底(向后兼容)。"""
    from agent.hif.decisions.play import pick_playable_card

    state = make_state(hand=make_hand(card_names=()))
    assert pick_playable_card(state) is None


def test_low_stamina_without_drink_skips() -> None:
    """M4 修复 2:体力告急 + 无 P ドリンク → Skip 回体 2(二选一的另一支)。"""
    strategy = GarakutaRinamiStrategy(make_payload())
    state = make_state(
        stamina=15,
        available_p_drinks=[],
        hand=make_hand(good_condition_card_count=0, draw_available=False, swap_hand_available=False),
    )
    action = strategy.decide(state)
    assert action.kind is ActionKind.SKIP
    assert "回体" in action.reason


# ---------------------------------------------------------------------------
# issue #3：出牌画像经 preset 覆盖链解析（GUI > override 文件 > preset 默认）
# ---------------------------------------------------------------------------


def _make_preset(**overrides: object):
    """从安全默认 preset 点名覆盖构造（dataclasses.replace 语义）。"""
    import dataclasses

    from agent.hif.presets import SAFE_DEFAULT_PRESET

    return dataclasses.replace(SAFE_DEFAULT_PRESET, **overrides)  # type: ignore[arg-type]


def test_profile_from_preset_drink_priority_override() -> None:
    """GUI 微调优先名单(drink_priority)最高优先 → 喝药选瓶序变化影响决策。"""
    import sys
    from pathlib import Path
    from importlib import import_module

    sys.path.insert(0, str(Path("agent").resolve()))
    action_cls = import_module("custom.action.produce_hif").ProduceHIFRound1Play

    preset = _make_preset(drink_priority=("テステーション",))
    profile = action_cls._profile_from_preset(preset)
    assert profile.p_drink_priority == ["テステーション"]

    # 决策联动：低体力 R1 手持用户点名瓶 → USE_P_DRINK 指向该瓶
    # (默认画像的优先序不含此瓶,若未走覆盖链则选不中)
    strategy = GarakutaRinamiStrategy(profile)
    state = make_state(
        stamina=10,
        available_p_drinks=["テステーション"],
        hand=make_hand(good_condition_card_count=0, draw_available=False, swap_hand_available=False),
    )
    action = strategy.decide(state)
    assert action.kind is ActionKind.USE_P_DRINK
    assert action.target_card == "テステーション"


def test_profile_from_preset_falls_back_to_preset_default() -> None:
    """GUI 未点名(drink_priority 空)→ 回落 preset 默认 drink_name_priority。"""
    import sys
    from pathlib import Path
    from importlib import import_module

    sys.path.insert(0, str(Path("agent").resolve()))
    action_cls = import_module("custom.action.produce_hif").ProduceHIFRound1Play

    preset = _make_preset(drink_name_priority=("センブリソーダ", "テステーション"))
    profile = action_cls._profile_from_preset(preset)
    assert profile.p_drink_priority == ["センブリソーダ", "テステーション"]


def test_profile_from_preset_keeps_default_when_both_empty() -> None:
    """两级都空 → 保持角色默认优先序(初星黒酢优先)。"""
    import sys
    from pathlib import Path
    from importlib import import_module

    from agent.hif.decisions.config import ProfilePayload as _PP

    sys.path.insert(0, str(Path("agent").resolve()))
    action_cls = import_module("custom.action.produce_hif").ProduceHIFRound1Play

    preset = _make_preset(drink_priority=(), drink_name_priority=())
    profile = action_cls._profile_from_preset(preset)
    assert profile.p_drink_priority == _PP.default().p_drink_priority

    # 默认序决策回归:手持默认次优先瓶仍按默认序选中
    strategy = GarakutaRinamiStrategy(profile)
    state = make_state(
        stamina=10,
        available_p_drinks=["パワフル漢方ドリンク"],
        hand=make_hand(good_condition_card_count=0, draw_available=False, swap_hand_available=False),
    )
    action = strategy.decide(state)
    assert action.kind is ActionKind.USE_P_DRINK
    assert action.target_card == "パワフル漢方ドリンク"
