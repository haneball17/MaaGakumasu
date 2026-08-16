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
