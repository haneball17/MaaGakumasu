"""scoring.py v2 结构化数值评分模型单测(M2 门槛:五族曲线 + 兜底链 + 量级对齐 + v2 语义)。

曲线断言用合成 effects(纯逻辑离线);量级与回归断言用 A1 v2 真数据产物
(assets/data/hif/skill_card_effects.json,缺失时 skip)。

v2 新增覆盖(相对 v1):絶好調动态倍率、集中池加算、好印象延时因子、
使用数追加 count 字段、timer 预约折现、Lost 压缩项、Grave 重复乘数。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from agent.hif.decisions.scoring import (
    ScoringParams,
    DecisionContext,
    score_effects,
    score_card_by_name,
)

_DATA = Path(__file__).resolve().parents[1] / "assets" / "data" / "hif" / "skill_card_effects.json"


def eff(tag: str, value=0, turn=0, condition=None, unit=None, count=None, level=None, deferred_turns=None) -> dict:
    return {
        "tag": tag, "value": value, "turn": turn, "condition": condition, "unit": unit,
        "count": count, "level": level, "deferred_turns": deferred_turns, "name_jp": tag,
    }


P = ScoringParams()
CTX = DecisionContext()  # 无局面信号:中性


# ---------------------------------------------------------------------------
# V 层五族曲线(3.1)
# ---------------------------------------------------------------------------

def test_immediate_parameter_linear():
    """即得分族:パラメータ直加线性,N 进分值(盲区 1)。"""
    s6 = score_effects([eff("score:parameter_add", 6)], 0, CTX, P)
    s12 = score_effects([eff("score:parameter_add", 12)], 0, CTX, P)
    assert s6.total == pytest.approx(6 * P.global_scale)
    assert s12.total == pytest.approx(2 * s6.total)


def test_buff_good_condition_log_saturation():
    """好調族(×1.5 乘区的 log 近似):3T < 7T,7T ≈ 15 未缩放。"""
    s3 = score_effects([eff("buff:good_condition", turn=3)], 0, CTX, P)
    s7 = score_effects([eff("buff:good_condition", turn=7)], 0, CTX, P)
    assert s3.breakdown[0].points == pytest.approx(P.k_buff * math.log2(4))
    assert s7.breakdown[0].points == pytest.approx(P.k_buff * math.log2(8))
    assert s3.total < s7.total


def test_excellent_dynamic_multiplier():
    """絶好調 v2:动态倍率 (1.5+0.1B)/1.5,依赖好調存量(上下文敏感)。"""
    low_b = score_effects(
        [eff("buff:excellent_condition", turn=5)], 0, DecisionContext(good_condition_turns=2), P
    )
    high_b = score_effects(
        [eff("buff:excellent_condition", turn=5)], 0, DecisionContext(good_condition_turns=10), P
    )
    base = score_effects([eff("buff:good_condition", turn=5)], 0, DecisionContext(good_condition_turns=0), P)
    assert low_b.breakdown[0].points == pytest.approx(base.breakdown[0].points * (1.5 + 0.2) / 1.5)
    assert high_b.breakdown[0].points > low_b.breakdown[0].points


def test_focus_pool_additive():
    """集中 v2:一次性加算池 value×2.0(2 级 ×2.5),不再看 turn(修正 v1 log)。"""
    s = score_effects([eff("buff:focus", 4)], 0, CTX, P)
    s2 = score_effects([eff("buff:focus", 4, level=2)], 0, CTX, P)
    assert s.breakdown[0].points == pytest.approx(4 * P.w_focus_pool)
    assert s2.breakdown[0].points == pytest.approx(4 * P.w_focus_pool * 2.5 / 2.0)


def test_good_impression_delayed_score():
    """好印象 v2:延时即得分——剩余出牌越多价值越高(方向与 buff 终盘衰减相反)。"""
    late = score_effects([eff("buff:good_impression", 8)], 0, DecisionContext(days_remaining=1), P)
    early = score_effects([eff("buff:good_impression", 8)], 0, DecisionContext(days_remaining=6), P)
    assert late.breakdown[0].points < early.breakdown[0].points
    assert early.breakdown[0].points == pytest.approx(8 * P.w_review_pool * (1 + min(1.0, 12 / 10)))


def test_action_economy_play_add_count_field():
    """使用数追加 v2:数量在 count 字段(v1 误读 value 导致 0 分)。"""
    s = score_effects([eff("action:play_add", value=0, count=1)], 0, CTX, P)
    assert s.breakdown[0].points == pytest.approx(1 * P.w_cycle * P.play_add_mult)
    assert s.total > 0


def test_deferred_timer_discount():
    """timer 预约折现:延迟越大价值越低(deferred_discount^delay)。"""
    now = score_effects([eff("action:draw", 2)], 0, CTX, P)
    d1 = score_effects([eff("action:draw", 2, deferred_turns=1)], 0, CTX, P)
    d2 = score_effects([eff("action:draw", 2, deferred_turns=2)], 0, CTX, P)
    assert d1.breakdown[0].points == pytest.approx(now.breakdown[0].points * P.deferred_discount)
    assert d2.breakdown[0].points < d1.breakdown[0].points


def test_stamina_recover_context_sensitive():
    """资源续航族:体力回復上下文敏感——满体力 ≈0,低体力高(盲区 3)。"""
    full = score_effects([eff("resource:stamina_recover", 5)], 0, DecisionContext(stamina_ratio=1.0), P)
    low = score_effects([eff("resource:stamina_recover", 5)], 0, DecisionContext(stamina_ratio=0.2), P)
    assert full.breakdown[0].points == pytest.approx(0.0)
    assert low.breakdown[0].points == pytest.approx(5 * P.w_stamina_recover * 0.8)


def test_penalty_linear():
    """代价妨害族:体力伤害线性罚。"""
    s = score_effects([eff("penalty:stamina_damage", 4)], 0, CTX, P)
    assert s.breakdown[0].points == pytest.approx(-4 * P.w_penalty_stamina)
    assert s.total < 0


# ---------------------------------------------------------------------------
# 修饰系数层 + C 层 + 牌库项
# ---------------------------------------------------------------------------

def test_condition_discount():
    """条件発動折扣:condition 非空 × cond_factor。"""
    plain = score_effects([eff("buff:good_condition", turn=3)], 0, CTX, P)
    cond = score_effects([eff("buff:good_condition", turn=3, condition="e_trigger-x")], 0, CTX, P)
    assert cond.breakdown[0].points == pytest.approx(plain.breakdown[0].points * P.cond_factor)


def test_cost_layer_stamina_ratio():
    """C 层:同额体力消耗,体力比率越低罚越重(盲区 2)。"""
    high = score_effects([], 4, DecisionContext(stamina_ratio=1.0), P)
    low = score_effects([], 4, DecisionContext(stamina_ratio=0.3), P)
    assert high.cost_penalty == pytest.approx(4 * P.w_cost)
    assert low.cost_penalty > high.cost_penalty


def test_cost_layer_focus_consumption():
    """C 层:集中系消耗线性折罚,不随体力比率放大。"""
    full = score_effects([], 0, DecisionContext(stamina_ratio=1.0), P, focus_cost=3)
    low = score_effects([], 0, DecisionContext(stamina_ratio=0.2), P, focus_cost=3)
    assert full.cost_penalty == pytest.approx(3 * P.w_focus_cost)
    assert low.cost_penalty == pytest.approx(3 * P.w_focus_cost)


def test_deck_terms_lost_vs_grave():
    """牌库项(D1/D4):Lost 压缩补偿加分;Grave 循环卡效果 ×重复乘数。"""
    effects = [eff("score:parameter_add", 10)]
    lost = score_effects(effects, 0, CTX, P, repeat_mult=1.0, compression_bonus=P.w_compression)
    grave = score_effects(effects, 0, CTX, P, repeat_mult=P.grave_repeat_mult, compression_bonus=0.0)
    plain = score_effects(effects, 0, CTX, P)
    assert lost.total == pytest.approx((10 + P.w_compression) * P.global_scale)
    assert grave.total == pytest.approx(10 * P.grave_repeat_mult * P.global_scale)
    assert grave.total > plain.total
    assert "圧縮" in lost.deck_note and "Grave" in grave.deck_note


def test_synergy_placeholder():
    """synergy 恒 1.0 占位(P2 手牌跟踪前)。"""
    s = score_effects([eff("score:parameter_add", 10)], 0, CTX, P)
    assert s.synergy == 1.0


# ---------------------------------------------------------------------------
# 终盘衰减(3.4)
# ---------------------------------------------------------------------------

def test_endgame_decay():
    """剩余日数少时长线 buff 打折;日数未知不衰减。"""
    early = score_effects([eff("buff:good_condition", turn=7)], 0, DecisionContext(days_remaining=10), P)
    late = score_effects([eff("buff:good_condition", turn=7)], 0, DecisionContext(days_remaining=1), P)
    unknown = score_effects([eff("buff:good_condition", turn=7)], 0, CTX, P)
    assert late.total < early.total
    assert unknown.total == pytest.approx(early.total)
    assert early.breakdown[0].points == pytest.approx(P.k_buff * math.log2(8))  # 10 日 → 不打折


# ---------------------------------------------------------------------------
# 兜底链(设计文档第 6 节)
# ---------------------------------------------------------------------------

def test_unmapped_tags_score_zero():
    """未建模 tag(container/stance/unmapped)计 0 分,不炸不猜。"""
    s = score_effects([eff("container:timer", 3), eff("unmapped", 99), eff("stance:full_power", 1)], 0, CTX, P)
    assert all(item.points == 0 for item in s.breakdown)
    assert s.total == pytest.approx(0.0)


def test_pool_miss_returns_none():
    """效果池未命中的卡名返回 None(调用方退关键词兜底)。"""
    assert score_card_by_name("存在しないカード") is None


# ---------------------------------------------------------------------------
# 量级对齐 + 真数据回归(3.5,A1 v2 产物)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _DATA.exists(), reason="A1 产物 skill_card_effects.json 不存在")
class TestRealPoolData:
    def test_karui_ashidori_regression(self):
        """軽い足取り(パラメータ+6 好調2ターン,体力4,Grave 循环卡重复乘数生效)数值回归。"""
        s = score_card_by_name("軽い足取り", CTX, P)
        assert s is not None
        v = (6 + P.k_buff * math.log2(3)) * P.grave_repeat_mult  # Grave:重洗回流,期望重复使用
        cost = 4 * P.w_cost * (1 + P.cost_slope * (1 - 0.7))
        assert s.total == pytest.approx((v - cost) * P.global_scale, abs=0.25)
        tags = {item.tag for item in s.breakdown}
        assert "score:parameter_add" in tags
        assert "buff:good_condition" in tags
        assert "Grave" in s.deck_note

    def test_tier_variant_lookup(self):
        """档位变体名(軽い足取り+)可查且带档位加成。"""
        base = score_card_by_name("軽い足取り", CTX, P)
        plus = score_card_by_name("軽い足取り+", CTX, P)
        assert plus is not None and base is not None
        assert plus.total >= base.total - P.global_scale

    def test_scale_alignment_good_condition_7t(self):
        """好調7ターン单效果卡落在 ≈8 分档(量级对齐,3.5)。"""
        s = score_effects([eff("buff:good_condition", turn=7)], 0, CTX, P)
        assert 6.5 <= s.total <= 9.5

    def test_spotlight_timer_expanded(self):
        """聚光灯(Grave 循环卡):timer 展开的预约抽牌计分 + Grave 重复乘数生效。"""
        s = score_card_by_name("スポットライト", CTX, P)
        assert s is not None
        notes = [item.note for item in s.breakdown]
        assert any("予約" in n for n in notes), notes
        assert "Grave" in s.deck_note
        draw_items = [item for item in s.breakdown if item.tag == "action:draw" and item.points > 0]
        assert draw_items, "预约抽牌应有正分"

    def test_pool_covers_key_cards(self):
        """关键卡与莉波固有卡在池中可查(非 None)。"""
        for name in ("お姉さんの感覚", "自然体の魅力", "包容力", "コール＆レスポンス"):
            assert score_card_by_name(name, CTX, P) is not None, name
