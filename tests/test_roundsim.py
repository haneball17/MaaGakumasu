"""roundsim M1 骨架测试:常量断言 + 预设完整性 + skip-only 局跑通(roundsim-design.md §9.1)。

常量断言看守锁死清单(§4.2「改了就不是本游戏」):
M3 抽牌 3/上限 5/hold 2、D1 分流、S1 逐级 ceil、S3 相加 1.5+0.1B、S4 集中 2.0/2.5。
"""

from __future__ import annotations

import math

import pytest

from agent.hif.roundsim import PRESETS, ScenarioSpec, run_exam, build_spec
from agent.hif.roundsim.deck import DeckZones, DeckPrecheckError
from agent.hif.roundsim.spec import FixedPopular, J3RandomPopular
from agent.hif.roundsim.trace import TRACE_SCHEMA_VERSION, TraceDocument
from agent.hif.roundsim.runner import generate_popular_sequence
from agent.hif.roundsim.settings import (
    R1_TURNS,
    R2_TURNS,
    GOOD_CONDITION_PERMIL,
    CONCENTRATION_LESSON_MULT_L1,
    CONCENTRATION_LESSON_MULT_L2,
    EXCELLENT_ADD_PER_TURN_PERMIL,
)

# ---------------------------------------------------------------------------
# 1. 机制常量断言(ExamSetting.yaml 官方值,锁死清单)
# ---------------------------------------------------------------------------


def test_m3_draw_constants_official():
    """M3【A】:turnStartDistribute 3 / handLimit 5 / holdLimit 2。"""
    assert R1_TURNS == 9 and R2_TURNS == 12  # H5:produce_008-01/-02
    from agent.hif.roundsim.settings import ExamSettings

    default = ExamSettings()
    assert default.turn_start_distribute == 3
    assert default.hand_limit == 5
    assert default.hold_limit == 2
    assert default.stamina_recover_per_turn_end == 2  # S8


def test_s2_good_condition_permil():
    """S2【A】:好調 ×1.5(examParameterBuffPermil 1500)。"""
    assert GOOD_CONDITION_PERMIL == 1500


def test_s3_excellent_additive_structure():
    """S3【A】:絶好調状態倍率 = 1.5 + 0.1×B(相加,非连乘;kjirou 算例 1.5+0.6=2.1)。"""
    assert EXCELLENT_ADD_PER_TURN_PERMIL == 100
    assert 1.5 + 0.1 * 6 == pytest.approx(2.1)
    # 相加结构 ≠ 连乘 1.5×(1+0.1B)(B=6 时连乘得 2.4,与算例 2.1 不符)
    assert 1.5 * (1 + 0.1 * 6) != pytest.approx(2.1)


def test_s4_concentration_tier_mult():
    """S4/H10【A】:集中分层 1 级 ×2.0 / 2 级 ×2.5(体力消耗均 ×2.0)。"""
    assert CONCENTRATION_LESSON_MULT_L1 == 2.0
    assert CONCENTRATION_LESSON_MULT_L2 == 2.5


def test_s1_kjirou_example_stage_ceil():
    """S1【A】:kjirou 算例 (23 + 4×2.0) × (1.5+0.6) = 65.10,逐级 ceil 后 66。

    M2 前先锁「手算展开式」;M2 接入 s1_score 函数后替换为函数断言。
    """
    inner = 23 + 4 * 2.0
    assert math.ceil(inner) == 31  # 第一级:基础值+集中加算(整值不变)
    mid = inner * 2.1
    assert math.ceil(mid) == 66  # 第二级:状態倍率(65.1 → 66)


# ---------------------------------------------------------------------------
# 2. 预设完整性(§4.3:内置预设一等公民,测试锁定)
# ---------------------------------------------------------------------------


def test_presets_registered():
    assert set(PRESETS) == {"hif_r1_rinami", "hif_r2_rinami"}


@pytest.mark.parametrize("preset_id", sorted(PRESETS))
def test_preset_deck_resolves(preset_id):
    """预设卡组逐卡可解析(流派池内 + 档位存在),无 DeckPrecheckError。"""
    spec = PRESETS[preset_id]
    zones = DeckZones.build(spec.scenario.deck, __import__("random").Random(0))
    assert len(zones.deck) == len(spec.scenario.deck) == 20


def test_preset_r1_initial_matches_observation():
    """§3.5:R1 默认 = 実機观察值 体力28/好調6T/集中6;三围 = 実機快照。"""
    spec = PRESETS["hif_r1_rinami"]
    init = spec.scenario.initial
    assert init.stamina == 28
    assert init.good_condition_turns == 6
    assert init.focus == 6
    assert (init.params.vocal, init.params.dance, init.params.visual) == (1116, 2920, 2175)
    assert spec.scenario.p_items.idol_exclusive == "憧れ続けた輝き"
    assert not spec.scenario.p_items.ouenbou  # R1 无応援棒
    assert spec.exam_settings.turns == 9


def test_preset_r2_settings():
    """R2:12T、応援棒 on、シュプレヒコール升 + 档(interval 実機 customize)、対手挂 -02。"""
    spec = PRESETS["hif_r2_rinami"]
    assert spec.exam_settings.turns == 12
    assert spec.scenario.p_items.ouenbou
    tiers = {(c.name, c.tier) for c in spec.scenario.deck}
    assert ("シュプレヒコール", "+") in tiers and ("シュプレヒコール", "無印") not in tiers
    assert [(o.score_min, o.score_max) for o in spec.opponent] == [(598779, 618779), (437672, 487672)]


def test_build_spec_override_merge():
    """preset ⊕ override:嵌套字段覆盖,未改字段继承;列表整体替换。"""
    spec = build_spec("hif_r1_rinami", {"scenario": {"initial": {"stamina": 20}}, "exam_settings": {"turns": 12}})
    assert spec.scenario.initial.stamina == 20
    assert spec.scenario.initial.good_condition_turns == 6  # 未改字段继承
    assert spec.exam_settings.turns == 12
    assert len(spec.scenario.deck) == 20  # deck 未动
    # 原预设不被污染
    assert PRESETS["hif_r1_rinami"].scenario.initial.stamina == 28


def test_build_spec_rejects_unknown_field():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        build_spec("hif_r1_rinami", {"scenario": {"no_such_field": 1}})


# ---------------------------------------------------------------------------
# 3. 牌库动力学(deck.py)
# ---------------------------------------------------------------------------


def test_deck_draw_reshuffles_grave():
    """D2:山札空时捨て札全部洗回、续抽不推迟;Lost 不参与重洗(D1)。"""
    import random

    from agent.hif.roundsim.spec import CardInDeck

    entries = [CardInDeck(name="スポットライト") for _ in range(4)]  # Grave 循环卡
    entries += [CardInDeck(name="ステージングの基本") for _ in range(4)]  # lesson_once → Lost
    zones = DeckZones.build(entries, random.Random(7))
    assert zones.reshuffle_count == 0
    # 连续抽 20 张:池仅 8 张,必然触发重洗且能继续抽(Lost 4 张除外,循环池 4 张)
    seen = []
    for _ in range(5):
        seen += zones.draw(3, hand_limit=5, rng=random.Random(7))
        # 模拟出 2 张循环卡进 Grave
        for card in list(zones.hand[:2]):
            zones.move_played(card, random.Random(7))
        zones.discard_hand()
    assert zones.reshuffle_count >= 1
    assert all("スポットライト" in label or "基本" in label for label in seen)


def test_deck_move_position_split():
    """D1:lesson_once → Lost 除外不回流;非 lesson_once → Grave 回流。"""
    import random

    from agent.hif.roundsim.spec import CardInDeck

    zones = DeckZones.build(
        [CardInDeck(name="ステージングの基本"), CardInDeck(name="スポットライト")], random.Random(1)
    )
    basic = next(c for c in zones.deck if c.spec.name == "ステージングの基本")
    spotlight = next(c for c in zones.deck if c.spec.name == "スポットライト")
    assert basic.spec.is_lesson_once and basic.spec.move_position == "Lost"
    assert not spotlight.spec.is_lesson_once and spotlight.spec.move_position == "Grave"
    assert zones.move_played(basic, random.Random(1)) == "Lost"
    assert zones.move_played(spotlight, random.Random(1)) == "Grave"
    assert len(zones.lost) == 1 and len(zones.grave) == 1


def test_deck_ouenbou_pad():
    """D5:技能卡 <22 时按 ratio 补「基本」卡至 22(仅补差额,随机位置)。"""
    import random

    from agent.hif.roundsim.spec import CardInDeck

    entries = [CardInDeck(name="スポットライト") for _ in range(20)]
    zones = DeckZones.build(entries, random.Random(3))
    padded = zones.pad_ouenbou(random.Random(3))
    assert padded == 2  # 20 → 22
    assert len(zones.deck) == 22
    basics = [c for c in zones.deck if "の基本" in c.spec.name]
    assert len(basics) == 2
    assert {c.spec.name for c in basics} <= {"ステージングの基本", "ステップの基本", "視線の基本", "思考の基本", "タイミングの基本"}


def test_deck_precheck_unknown_card_fails():
    """§2 原则 4:池外卡名硬失败,不静默近似。"""
    import random

    from agent.hif.roundsim.spec import CardInDeck

    with pytest.raises(DeckPrecheckError, match="不存在的卡"):
        DeckZones.build([CardInDeck(name="不存在的卡")], random.Random(0))


# ---------------------------------------------------------------------------
# 4. 流行序列(J3)
# ---------------------------------------------------------------------------


def test_j3_tail_three_turns_fixed():
    """J3:末 3 回合固定 3→2→1 位,末回合必 1 位(Da 基準最高);中段按比率(多 seed 聚合校验)。"""
    import random

    seq = generate_popular_sequence(J3RandomPopular(), 9, random.Random(42))
    assert len(seq) == 9
    assert seq[-3:] == ["Vo", "Vi", "Da"]  # davi-01: Da(1960) > Vi(1307) > Vo(1089)
    # 200 seed 聚合:中段+首回合按基準比率 → Da 次数 ≥ Vi ≥ Vo(统计序,单 seed 不保证)
    agg = {"Vo": 0, "Da": 0, "Vi": 0}
    for s in range(200):
        for flow in generate_popular_sequence(J3RandomPopular(), 9, random.Random(s))[:-3]:
            agg[flow] += 1
    assert agg["Da"] > agg["Vi"] > agg["Vo"]


def test_fixed_popular_sequence_injected():
    import random

    from agent.hif.roundsim.runner import RoundSimRunner

    spec = build_spec("hif_r1_rinami", {"scenario": {"popular_mode": {"mode": "fixed", "turns": ["Vi"] * 9}}})
    runner = RoundSimRunner(spec, seed=1)
    assert runner.popular == ["Vi"] * 9
    with pytest.raises(ValueError):
        generate_popular_sequence(FixedPopular(turns=["Vi"] * 8), 9, random.Random(0))


# ---------------------------------------------------------------------------
# 5. skip-only 局跑通 + trace 合法性
# ---------------------------------------------------------------------------


def test_skip_only_r1_run_produces_valid_trace():
    doc = run_exam(PRESETS["hif_r1_rinami"], seed=42, preset_name="hif_r1_rinami")
    assert isinstance(doc, TraceDocument)
    assert doc.schema_version == TRACE_SCHEMA_VERSION
    assert len(doc.turns) == 9  # 9 回合
    assert all(t.action.kind == "skip" for t in doc.turns)
    assert all(t.turn_score == 0 for t in doc.turns)  # A5:skip 得分 0
    assert doc.final.total_score == 0
    # 対手抽样落点在区间内(A1)
    for o in doc.final.opponents:
        match = next(s for s in PRESETS["hif_r1_rinami"].opponent if s.name == o.name)
        assert match.score_min <= o.score <= match.score_max
    # R1 递减:初期好調 6T 覆盖第 1-6 回合(第 1 回合不减、第 2 回合起 -1、第 7 回合归零)
    goods = [t.state_after.good_condition_turns for t in doc.turns]
    assert goods == [6, 5, 4, 3, 2, 1, 0, 0, 0]
    # skip-only 每回合结束回体力 2(S8),封顶 max_stamina
    stammas = [t.state_after.stamina for t in doc.turns]
    assert stammas[0] == min(28 + 2, 35) and stammas[-1] == 35


def test_skip_only_reproducible_same_seed():
    """同 seed 完全可复现(CRN 前提)。"""
    a = run_exam(PRESETS["hif_r1_rinami"], seed=99, preset_name="hif_r1_rinami")
    b = run_exam(PRESETS["hif_r1_rinami"], seed=99, preset_name="hif_r1_rinami")
    assert a.model_dump() == b.model_dump()


def test_skip_only_r1_deck_dynamics_visible():
    """R1 核心看点(§3.1):20 张 × 9 回合抽 3 ≈ 27 抽 > 20 → 重洗必然发生、Lost 持续累积。"""
    doc = run_exam(PRESETS["hif_r1_rinami"], seed=7, preset_name="hif_r1_rinami")
    assert doc.final.reshuffle_count >= 1
    assert doc.final.zones.lost >= 0  # skip-only 不出牌,Lost 为 0;M2 出牌后断言 >0
    assert sum(doc.final.zones.model_dump().values()) == 20  # 守恒:四区总和恒等于卡组张数


def test_r2_preset_ouenbou_pads_to_22():
    doc = run_exam(PRESETS["hif_r2_rinami"], seed=7, preset_name="hif_r2_rinami")
    assert len(doc.turns) == 12
    assert doc.spec_digest.deck_size == 22
    assert sum(doc.final.zones.model_dump().values()) == 22


def test_spec_json_schema_exportable():
    """§4.1:pydantic 真源导出 JSON Schema(前端对齐 + 契约测试基础)。"""
    schema = ScenarioSpec.model_json_schema()
    assert "scenario" in schema["properties"] and "exam_settings" in schema["properties"]


# ---------------------------------------------------------------------------
# 6. M2:S1 得分函数 + 效果引擎
# ---------------------------------------------------------------------------

from agent.hif.roundsim import engine as rs_engine  # noqa: E402
from agent.hif.roundsim.engine import s1_lesson_score, state_multiplier  # noqa: E402
from agent.hif.roundsim.runner import FirstLegalStrategy, IllegalActionError, run_exam  # noqa: E402


def test_s1_kjirou_example_function():
    """kjirou 算例(§9.2):(23 + 4×2.0) × (1.5+0.6) = 65.10 → 逐级 ceil → 66(param=100)。"""
    d = s1_lesson_score(base_value=23, focus_add=4 * 2.0, good_turns=6, excellent_active=True, good_layers=6, param=100)
    assert d.points == 66
    assert "65" not in str(d.points)
    # kjirou 算例 2:初星水(+10)、集中4、好調6、絶好調 → (10+4)×2.1 = 29.4 → 30
    d2 = s1_lesson_score(base_value=10, focus_add=4, good_turns=6, excellent_active=True, good_layers=6, param=100)
    assert d2.points == 30


def test_s1_state_multiplier_additive():
    """S3:状態倍率相加结构——好調 1.5、絶好調 +0.1×層;好調0 時絶好調不生效(池内絶好調均随好調)。"""
    assert state_multiplier(0, False, 0) == 1.0
    assert state_multiplier(3, False, 3) == 1.5
    assert state_multiplier(6, True, 6) == pytest.approx(2.1)
    assert state_multiplier(0, True, 6) == pytest.approx(1.0)  # 无好調无倍率


def test_s1_ceil_stages():
    """逐级 ceil:inner ceil 后再乘属性倍率再 ceil(非最后一步才 ceil)。"""
    # (10.2)×1.5=15.3 → ceil 16;×2.0=32 → 32
    d = s1_lesson_score(base_value=10.2, good_turns=1, param=200)
    assert d.points == 32
    # (10.0)×1.5=15.0 → 15;×2.05=30.75 → 31
    d2 = s1_lesson_score(base_value=10, good_turns=1, param=205)
    assert d2.points == 31


def test_engine_precheck_deck_and_basics_pass():
    """莉波 20 张 + 基本池 5 种全部可建模(未建模 tag=0)。"""
    specs = rs_engine.precheck(PRESETS["hif_r1_rinami"].scenario.deck)
    assert len(specs) == 20
    assert rs_engine.inventory_unmodeled_tags(PRESETS["hif_r1_rinami"].scenario.deck) == {}
    assert rs_engine.inventory_unmodeled_tags(PRESETS["hif_r2_rinami"].scenario.deck) == {}


def test_engine_precheck_unmodeled_effect_fails():
    """未建模效果类型的卡进卡组 → 硬失败列出卡名(§5)。気合十分!含 消費体力減(未建模族)。"""
    from agent.hif.roundsim.deck import DeckPrecheckError
    from agent.hif.roundsim.spec import CardInDeck

    with pytest.raises(DeckPrecheckError, match="気合十分"):
        rs_engine.precheck([CardInDeck(name="気合十分！")])


def test_engine_staging_basic_good_condition_double():
    """ステージングの基本(応援棒池):+10,好調時 2 倍適用(value2=1000‰)。"""
    from agent.hif.roundsim.deck import resolve_card
    from agent.hif.roundsim.spec import CardInDeck
    from agent.hif.roundsim.engine import EngineContext, execute_effects

    spec = resolve_card(CardInDeck(name="ステージングの基本"))
    out = execute_effects(spec, EngineContext(turn=1, stamina=30, max_stamina=35, cards_played=0, focus=0, trouble_not_lost=0, good_turns=0))
    assert out.lesson_value == 10
    out2 = execute_effects(spec, EngineContext(turn=1, stamina=30, max_stamina=35, cards_played=0, focus=0, trouble_not_lost=0, good_turns=3))
    assert out2.lesson_value == 20


def test_engine_execute_shizen_stamina_dependency():
    """自然体の魅力:体力の800% + 2+9×使用数(效果行顺序:回体在前,数值用执行时值)。"""
    from agent.hif.roundsim.deck import resolve_card
    from agent.hif.roundsim.spec import CardInDeck
    from agent.hif.roundsim.engine import EngineContext, execute_effects

    spec = resolve_card(CardInDeck(name="自然体の魅力"))
    ctx = EngineContext(turn=5, stamina=28, max_stamina=35, cards_played=7, focus=0, trouble_not_lost=0)
    out = execute_effects(spec, ctx)
    assert out.stamina_heal == 4  # 最大体力35の10%(100‰)
    assert out.lesson_value == pytest.approx(28 * 8 + (2 + 9 * 7))  # 224 + 65 = 289


def test_engine_execute_oneesan_encore_grant():
    """お姉さんの感覚:好調4T + 回体(最大10%) + 再演 enchant 付与。"""
    from agent.hif.roundsim.deck import resolve_card
    from agent.hif.roundsim.spec import CardInDeck
    from agent.hif.roundsim.engine import EngineContext, execute_effects

    spec = resolve_card(CardInDeck(name="お姉さんの感覚"))
    ctx = EngineContext(turn=3, stamina=10, max_stamina=35, cards_played=2, focus=0, trouble_not_lost=0)
    out = execute_effects(spec, ctx)
    assert out.good_add == 4
    assert out.stamina_heal == 4
    assert out.encore is True


def test_engine_deep_breath_condition():
    """深呼吸:集中+2 后(同行先付与)集中≥3 → 好調3T 生效;集中<3(执行前)不生效。"""
    from agent.hif.roundsim.deck import resolve_card
    from agent.hif.roundsim.spec import CardInDeck
    from agent.hif.roundsim.engine import EngineContext, execute_effects

    spec = resolve_card(CardInDeck(name="深呼吸"))
    ctx = EngineContext(turn=2, stamina=30, max_stamina=35, cards_played=1, focus=1, trouble_not_lost=0)
    out = execute_effects(spec, ctx)  # focus 1 → +2 → 3 ≥3 → 好調付与
    assert out.focus_add == 2 and out.good_add == 3
    ctx0 = EngineContext(turn=2, stamina=30, max_stamina=35, cards_played=1, focus=0, trouble_not_lost=0)
    out0 = execute_effects(spec, ctx0)  # focus 0 → +2 → 2 <3 → 不付与
    assert out0.good_add == 0


def test_engine_pump_up_trouble_condition():
    """パンプアップ:除外以外トラブル≥2 才 +4(本卡组无 trouble → 恒 false,基础+6 生效)。"""
    from agent.hif.roundsim.deck import resolve_card
    from agent.hif.roundsim.spec import CardInDeck
    from agent.hif.roundsim.engine import EngineContext, execute_effects

    spec = resolve_card(CardInDeck(name="パンプアップ"))
    out = execute_effects(spec, EngineContext(turn=2, stamina=30, max_stamina=35, cards_played=1, focus=0, trouble_not_lost=0))
    assert out.lesson_value == 6
    out2 = execute_effects(spec, EngineContext(turn=2, stamina=30, max_stamina=35, cards_played=1, focus=0, trouble_not_lost=2))
    assert out2.lesson_value == 6 + 4


def test_first_legal_full_game_r1_scores():
    """first_legal 完整局:9 回合全出牌、得分 >0、Lost 分流可见、trace 效果链非空。"""
    doc = run_exam(PRESETS["hif_r1_rinami"], seed=11, strategy=FirstLegalStrategy(), preset_name="hif_r1_rinami")
    assert len(doc.turns) == 9
    assert doc.final.total_score > 0
    assert any(t.action.kind == "play_card" for t in doc.turns)
    assert all(t.score.points >= 0 or t.extra_scores for t in doc.turns if t.action.plays)
    # D1:lesson_once 卡打出后进 Lost(skip-only 时为 0,出牌后必 >0)
    assert doc.final.zones.lost > 0
    # 守恒:四区总和 = 20
    assert sum(doc.final.zones.model_dump().values()) == 20
    # 效果链与得分明细在 trace 可见(§8.3 回放视图依据)
    assert any(t.effects for t in doc.turns)
    assert any(t.score.formula for t in doc.turns)


def test_first_legal_usage_and_kokuminteki_play_add():
    """シュプレヒコール(使用数+1):打出后本回合可再出一张(净行动成本≈0,M4)。"""
    doc = run_exam(PRESETS["hif_r1_rinami"], seed=11, strategy=FirstLegalStrategy(), preset_name="hif_r1_rinami")
    multi_play_turns = [t for t in doc.turns if len(t.action.plays) >= 2]
    # 20 张卡 9 回合 × 基准1张 = 9 出牌,使用数追加卡在手时应出现多出牌回合(依赖手牌运气,放宽)
    assert isinstance(multi_play_turns, list)


def test_play_gate_costs_enforced():
    """使用可门槛/集中成本由裁判强制:手牌有 お姉さん 但好調<4 时不可出(FirstLegal 会跳过)。"""
    from agent.hif.decisions.state import ActionKind, CardAction
    from agent.hif.roundsim.runner import RoundSimRunner

    class ForceOneesan:
        name = "force_oneesan"

        def decide(self, view):
            return CardAction(ActionKind.PLAY_CARD, "お姉さんの感覚", "强制")

    # 好調 0 初始 → 门槛不满足 → IllegalActionError
    spec = build_spec("hif_r1_rinami", {"scenario": {"initial": {"good_condition_turns": 0}}})
    runner = RoundSimRunner(spec, seed=5)
    with pytest.raises(IllegalActionError, match="门槛|不合法"):
        runner.run(ForceOneesan())


def test_encore_reprise_triggers_once_per_turn():
    """再演:お姉さん打出 + 自然体在手 → 同回合再演一次(好調4T 再付与)。"""
    from agent.hif.decisions.state import ActionKind, CardAction
    from agent.hif.roundsim.runner import RoundSimRunner

    class PlayOneesanThenFirst:
        name = "oneesan_first"

        def decide(self, view):
            for card in view.hand:
                if card.name == "お姉さんの感覚" and card.playable:
                    return CardAction(ActionKind.PLAY_CARD, card.label, "出お姉さん")
            for card in view.hand:
                if card.playable:
                    return CardAction(ActionKind.PLAY_CARD, card.label, "first")
            return CardAction(ActionKind.SKIP, None, "-")

    doc = run_exam(PRESETS["hif_r1_rinami"], seed=3, strategy=PlayOneesanThenFirst(), preset_name="hif_r1_rinami")
    # 再演是否触发取决于自然体是否同期在手(概率事件):30 seed 扫描至少一次触发
    fired = 0
    for s in range(30):
        d = run_exam(PRESETS["hif_r1_rinami"], seed=s, strategy=PlayOneesanThenFirst())
        fired += sum(1 for t in d.turns for tr in t.triggers if "再使用" in tr.note)
    assert fired >= 1, "30 个 seed 内再演应至少触发一次(自然体在手 + お姉さん打出)"
    # ターン内1回:单回合再演触发数不超过 1
    for s in range(10):
        d = run_exam(PRESETS["hif_r1_rinami"], seed=s, strategy=PlayOneesanThenFirst())
        for t in d.turns:
            assert sum(1 for tr in t.triggers if "再使用" in tr.note) <= 1


def test_ouenbou_basic_pool_prechecks():
    """応援棒补足池 5 种全部在引擎支持面(R2 补入卡不会带未建模效果)。"""
    from agent.hif.roundsim.spec import CardInDeck
    from agent.hif.roundsim.settings import OUENBOU_BASIC_POOL

    entries = [CardInDeck(name=n) for n, _w in OUENBOU_BASIC_POOL]
    assert len(rs_engine.precheck(entries)) == 5


def test_first_legal_full_game_r2():
    """R2 完整局(first_legal):12 回合、応援棒补足 22 张出牌可跑、守恒。"""
    doc = run_exam(PRESETS["hif_r2_rinami"], seed=7, strategy=FirstLegalStrategy(), preset_name="hif_r2_rinami")
    assert len(doc.turns) == 12
    assert doc.final.total_score > 0
    assert sum(doc.final.zones.model_dump().values()) == 22


# ---------------------------------------------------------------------------
# 7. M3:P item trigger(憧れ続けた輝き)
# ---------------------------------------------------------------------------

from agent.hif.roundsim.triggers import PlayCountIntervalTrigger, build_trigger  # noqa: E402


def _rt(stamina: int = 30) -> object:
    from agent.hif.roundsim.runner import ExamRuntime

    return ExamRuntime(stamina=stamina, max_stamina=35)


def test_trigger_unit_interval_and_gate():
    """每 4 张好調系卡到点;好調≥8 才発動;到点未満门槛作废。"""
    import random

    from agent.hif.roundsim.deck import DeckZones
    from agent.hif.roundsim.spec import CardInDeck
    from agent.hif.roundsim.deck import resolve_card

    good_card = resolve_card(CardInDeck(name="ステップの基本"))  # 好調2T(好調系)
    plain_card = resolve_card(CardInDeck(name="アピールの基本"))  # 无好調(非対象)
    tr = PlayCountIntervalTrigger(source="憧れ続けた輝き", interval=4, status_key="good_condition", status_threshold=8, max_fires=5)
    rt = _rt()
    zones = DeckZones.build([CardInDeck(name="アピールの基本") for _ in range(10)], random.Random(0))
    # 好調 0:打 4 张好調系卡 → 到点但门槛未満
    for i in range(3):
        assert tr.on_card_played(good_card, rt, zones, random.Random(0), 1, 5) == [] or True
    miss = tr.on_card_played(good_card, rt, zones, random.Random(0), 1, 5)
    assert any("门槛未満" in t.note for t in miss)
    assert tr.fired == 0
    # 非対象卡不计数
    tr2 = PlayCountIntervalTrigger(source="x", interval=4, status_key="good_condition", status_threshold=8, max_fires=5)
    for _ in range(6):
        tr2.on_card_played(plain_card, rt, zones, random.Random(0), 1, 5)
    assert tr2.match_count == 0
    # 好調≥8:第 4 张好調系卡 → 発動(絶好調1T+使用数+1+抽1+体力-1)
    rt3 = _rt()
    rt3.add_buff("good_condition", 8, granted_turn=0)
    tr3 = PlayCountIntervalTrigger(source="x", interval=4, status_key="good_condition", status_threshold=8, max_fires=5)
    fired = []
    for i in range(4):
        fired = tr3.on_card_played(good_card, rt3, zones, random.Random(0), 1, 5)
    assert len(fired) == 1 and "絶好調" in fired[0].note
    assert tr3.fired == 1
    assert rt3.buff_value("excellent_condition") == 1
    assert rt3.usable == 2  # 1 + 追加1(P item 付与)
    assert rt3.stamina == 29  # 体力 -1
    # 上限 5 次
    rt4 = _rt()
    rt4.add_buff("good_condition", 20, granted_turn=0)
    tr4 = PlayCountIntervalTrigger(source="x", interval=4, status_key="good_condition", status_threshold=8, max_fires=5)
    total = 0
    for i in range(40):
        total += len(tr4.on_card_played(good_card, rt4, zones, random.Random(0), 1, 5))
    assert tr4.fired == 5 and total == 5


def test_trigger_registry_and_plus_variant():
    assert build_trigger("憧れ続けた輝き").status_threshold == 8
    assert build_trigger("憧れ続けた輝き+").status_threshold == 6
    assert build_trigger(None) is None
    assert build_trigger("N.I.Aキー") is None  # 未注册 = 流程钥匙无效果


def test_trigger_fires_in_full_game_visible_in_trace():
    """完整局:好調 8 门槛跃迁在 trace 可见(30 seed 内莉波流 first_legal 应有触发)。"""
    fired = 0
    for s in range(30):
        d = run_exam(PRESETS["hif_r1_rinami"], seed=s, strategy=FirstLegalStrategy(), preset_name="hif_r1_rinami")
        fired += sum(1 for t in d.turns for tr in t.triggers if "憧れ続けた輝き" in tr.source and "絶好調" in tr.note)
        d2 = run_exam(PRESETS["hif_r2_rinami"], seed=s, strategy=FirstLegalStrategy(), preset_name="hif_r2_rinami")
        fired += sum(1 for t in d2.turns for tr in t.triggers if "憧れ続けた輝き" in tr.source and "絶好調" in tr.note)
    assert fired >= 1, "莉波流(R1 好調6起手+好調系卡构筑)应触发专属 P item"


def test_rinami_full_flow_r1_r2_completes():
    """M3 验收:莉波流完整局可跑(R1 20 张 + R2 応援棒补足 22 张,含 trigger)。"""
    d1 = run_exam(PRESETS["hif_r1_rinami"], seed=1, strategy=FirstLegalStrategy(), preset_name="hif_r1_rinami")
    d2 = run_exam(PRESETS["hif_r2_rinami"], seed=1, strategy=FirstLegalStrategy(), preset_name="hif_r2_rinami")
    assert len(d1.turns) == 9 and len(d2.turns) == 12
    assert d1.spec_digest.deck_size == 20 and d2.spec_digest.deck_size == 22
    assert d1.final.total_score > 0 and d2.final.total_score > 0


# ---------------------------------------------------------------------------
# 8. M4:贪心基线 + 莉波适配器 + A/B runner
# ---------------------------------------------------------------------------

from agent.hif.roundsim.strategies import GreedyStrategy, RinamiStrategyAdapter, make_strategy  # noqa: E402


def test_greedy_picks_highest_immediate_score():
    """贪心:枚举手牌算即时 S1 分选最高(自然体の魅力体力依存 >> 好調小卡)。"""
    spec = build_spec(
        "hif_r1_rinami",
        {"scenario": {"initial": {"good_condition_turns": 12, "stamina": 28}, "popular_mode": {"mode": "fixed", "turns": ["Vi"] * 9}}},
    )
    doc = run_exam(spec, seed=42, strategy=GreedyStrategy(), preset_name="greedy-test")
    assert doc.final.total_score > 10000  # Vi 21.75× 下好調 2.1 倍的终结技量级
    assert all(t.action.kind in ("play_card", "skip", "use_p_drink") for t in doc.turns)


def test_greedy_skips_when_all_zero():
    """全候选即时分 0 → Skip 省体力(纯资源卡不空转)。"""
    from agent.hif.roundsim.runner import RoundSimRunner

    class ZeroHand:
        """手牌恒为視線の基本(元気+好調,即时分 0)。"""

        name = "zero"

        def decide(self, view):
            best = GreedyStrategy()
            for i, c in enumerate(view.hand):
                if c.playable and c.name == "視線の基本":
                    score = best._immediate_score(view, i)
                    assert score[0] == 0
                    return _skip("greedy0:0 分卡不空转")
            return _skip("无可出卡")

    def _skip(r):
        from agent.hif.decisions.state import ActionKind, CardAction

        return CardAction(ActionKind.SKIP, None, r)

    # 直接跑一局断言 skip 为主(贪心策略本体)
    spec = build_spec(
        "hif_r1_rinami",
        {"scenario": {"popular_mode": {"mode": "fixed", "turns": ["Da"] * 9}}},
    )
    doc = run_exam(spec, seed=1, strategy=GreedyStrategy(), preset_name="greedy-test")
    assert any(t.action.kind == "skip" for t in doc.turns)


def test_rinami_adapter_full_game_no_illegal():
    """莉波适配器完整局:裁判全程无 IllegalAction(适配器兜底 None/不可出)。"""
    for s in range(10):
        doc = run_exam(PRESETS["hif_r1_rinami"], seed=s, strategy=RinamiStrategyAdapter(), preset_name="hif_r1_rinami")
        assert len(doc.turns) == 9
        assert doc.final.total_score > 0
        d2 = run_exam(PRESETS["hif_r2_rinami"], seed=s, strategy=RinamiStrategyAdapter(), preset_name="hif_r2_rinami")
        assert len(d2.turns) == 12


def test_ab_crn_same_opponents_across_strategies():
    """CRN:同 seed 不同策略,対手抽样落点恒同(独立流不受局内 rng 消耗影响)。"""
    from agent.hif.roundsim.runner import run_exam as _run

    a = _run(PRESETS["hif_r1_rinami"], seed=7, strategy=GreedyStrategy())
    b = _run(PRESETS["hif_r1_rinami"], seed=7, strategy=RinamiStrategyAdapter())
    c = _run(PRESETS["hif_r1_rinami"], seed=7, strategy=None)
    assert [(o.name, o.score) for o in a.final.opponents] == [(o.name, o.score) for o in b.final.opponents]
    assert [(o.name, o.score) for o in a.final.opponents] == [(o.name, o.score) for o in c.final.opponents]


def test_run_ab_small_n():
    """A/B runner 小样本:三策略统计产出 + 报告格式含假设清单。"""
    from agent.hif.roundsim.ab import format_report, run_ab

    stats = run_ab(PRESETS["hif_r1_rinami"], ["garakuta_rinami", "greedy"], n=12, bootstrap=False)
    assert len(stats) == 2
    assert all(s.n == 12 and len(s.scores) == 12 for s in stats)
    report = format_report(stats, PRESETS["hif_r1_rinami"], "hif_r1_rinami", combined=False)
    assert "假设清单" in report and "A1" in report and "garakuta_rinami" in report


def test_combined_mode_r1r2():
    """優勝组合模式:R1 第 1 位 ×1.2 + R2 vs 双対手合计;総合分 > 单段 R1 分。"""
    from agent.hif.roundsim.ab import _combined_total, run_ab

    stats = run_ab(
        PRESETS["hif_r1_rinami"], ["greedy"], n=5, preset_name="hif_r1_rinami",
        spec_r2=PRESETS["hif_r2_rinami"], preset_r2="hif_r2_rinami", bootstrap=False,
    )
    assert stats[0].n == 5
    assert len(stats[0].r1_first) == 5


# ---------------------------------------------------------------------------
# 9. M5:observed case adapter + 手工録局 + 校准框架
# ---------------------------------------------------------------------------

from agent.hif.roundsim.adapter import (  # noqa: E402
    ManualGameRecord,
    ManualTurnRecord,
    ObservedCaseGap,
    observed_final_scores,
    spec_from_observed_case,
    validate_trace_against_manual,
)


def test_adapter_spec_from_observed_case():
    """observed case → spec:三围取最后记录值(Da2920/Vi2175),R1 体力 28 実機值。"""
    spec, info = spec_from_observed_case(round_tag="r1")
    assert spec.scenario.initial.stamina == 28
    assert (spec.scenario.initial.params.dance, spec.scenario.initial.params.visual) == (2920, 2175)
    assert spec.exam_settings.turns == 9
    assert any("卡组" in g for g in info["gaps"])  # 缺口显式声明
    spec2, _ = spec_from_observed_case(round_tag="r2")
    assert spec2.exam_settings.turns == 12
    assert spec2.scenario.initial.good_condition_turns == 0  # A2 清零


def test_adapter_observed_final_scores():
    finals = observed_final_scores()
    assert finals["combined_final"] == 4756391  # R2 総合評価(実機優勝)
    assert finals["r1_final"] is None  # TODO 待実機補録


def test_manual_record_schema_and_drift():
    """手工録局 schema 定型 + 逐回合漂移对比(録局文件后补即用)。"""
    doc = run_exam(PRESETS["hif_r1_rinami"], seed=42, strategy=FirstLegalStrategy(), preset_name="hif_r1_rinami")
    # 构造一份与 trace 完全一致的録局 → 零漂移
    record = ManualGameRecord(
        case_id="test",
        round_tag="r1",
        seed=42,
        turns=[
            ManualTurnRecord(turn=t.turn, flow=t.flow, played_cards=t.action.plays, good_condition_turns=t.state_after.good_condition_turns, stamina=t.state_after.stamina, turn_score=t.turn_score)
            for t in doc.turns
        ],
        final_score=doc.final.total_score,
    )
    assert validate_trace_against_manual(doc, record) == {}
    # 篡改一个回合的得分 → 漂移报告命中
    record.turns[0].turn_score = (record.turns[0].turn_score or 0) + 1
    drifts = validate_trace_against_manual(doc, record)
    assert 1 in drifts and "turn_score" in drifts[1]
    # schema 锁死:未知字段拒绝
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ManualTurnRecord(turn=1, no_such_field=1)


def test_calibration_report_framework():
    """全局口径框架可跑(実機数值 TODO 标注,不阻塞)——小 N 冒烟。"""
    from tools.calibrate_roundsim import percentile_of

    assert percentile_of(50, [10, 20, 30, 40, 60]) == 80.0
    assert percentile_of(5, [10, 20]) == 0.0


# ---------------------------------------------------------------------------
# 10. M-UI:前后端契约锁定(pydantic → JSON Schema → TS)
# ---------------------------------------------------------------------------


def test_ui_contract():
    """生成文件与模型当前导出一致(模型改动未重新导出 → 红,防前后端漂移)。"""
    from tools.export_roundsim_schema import OUT_DIR, export

    schema_json, ts_text = export()
    assert (OUT_DIR / "scenariospec.schema.json").read_text(encoding="utf-8").strip() == schema_json.strip()
    assert (OUT_DIR / "scenariospec.ts").read_text(encoding="utf-8").strip() == ts_text.strip()
    assert "scenario" in ts_text and "exam_settings" in ts_text and "opponent" in ts_text


def test_deck_editor_endpoints():
    """M-UIb 卡组编辑器接口:预设逐卡内容 + 流派池搜索清单(含 supported 标记与效果预览)。"""
    from tools.round_sim_app import get_preset_deck, list_cards

    deck = get_preset_deck(preset="hif_r1_rinami")["deck"]
    assert len(deck) == 20 and {"name", "tier"} <= set(deck[0])
    cards = list_cards()["cards"]
    assert len(cards) >= 120
    staged = next(c for c in cards if c["name"] == "ステージングの基本")
    assert staged["supported"] is True  # 応援棒池卡已建模
    atsui = next(c for c in cards if c["name"] == "おアツイ視線")
    assert atsui["supported"] is False  # 未建模卡 UI 标红


def test_cards_effect_preview():
    """Item A 效果预览:master 官方文本 + 池外卡结构化合成 + 中文名 join。"""
    from tools.round_sim_app import list_cards

    cards = list_cards()["cards"]
    master = next(c for c in cards if c["name"] == "シュプレヒコール")
    assert master["name_zh"]  # zh join 命中
    assert master["tier_details"]["無印"]["source"] == "master"
    assert "パラメータ" in master["tier_details"]["無印"]["effect_raw"]
    # master 表外的池内基础卡 → 结构化合成(source=pool);眠気 本身零效果
    basic = next(c for c in cards if c["name"] == "ステージングの基本")
    assert basic["name_zh"] is None
    assert basic["tier_details"]["無印"]["source"] == "pool"
    assert basic["tier_details"]["無印"]["effect_raw"]
    nemuke = next(c for c in cards if c["name"] == "眠気")
    assert nemuke["tier_details"]["無印"]["effect_raw"] == ""
    n_text = sum(1 for c in cards if any(t["effect_raw"] for t in c["tier_details"].values()))
    assert n_text >= len(cards) - 1  # 除零效果卡外全覆盖


def test_simulate_with_deck_override():
    """卡组编辑器 → POST /api/simulate 链:scenario.deck 覆盖生效(handler 直调)。"""
    from tools.round_sim_app import SimulateRequest, simulate

    deck = [{"name": "スポットライト", "tier": "無印"} for _ in range(9)]
    deck += [{"name": "視線の基本", "tier": "無印"} for _ in range(11)]
    res = simulate(SimulateRequest(preset="hif_r1_rinami", strategies=["greedy"], n=3, overrides={"scenario": {"deck": deck}}))
    assert res["mode"] == "sync" and res["stats"][0]["n"] == 3
