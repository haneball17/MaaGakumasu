"""scoring.py 结构化数值评分模型单测(M2 门槛:五族曲线 + 兜底链 + 量级对齐)。

曲线断言用合成 effects(纯逻辑离线);量级与回归断言用 A1 真数据产物
(assets/data/hif/skill_card_effects.json,缺失时 skip)。
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


def eff(tag: str, value=0, turn=0, condition=None, unit=None) -> dict:
    return {"tag": tag, "value": value, "turn": turn, "condition": condition, "unit": unit, "name_jp": tag}


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


def test_buff_log_saturation():
    """状态增益族:递增饱和 k×log₂(N+1),好調3T < 好調7T(盲区 1)。"""
    s3 = score_effects([eff("buff:good_condition", turn=3)], 0, CTX, P)
    s7 = score_effects([eff("buff:good_condition", turn=7)], 0, CTX, P)
    assert s3.breakdown[0].points == pytest.approx(P.k_buff * math.log2(4))
    assert s7.breakdown[0].points == pytest.approx(P.k_buff * math.log2(8))
    assert s3.total < s7.total
    assert s7.total == pytest.approx(15 * P.global_scale)


def test_excellent_condition_double():
    """絶好調 = 好調 × excellent_mult。"""
    s = score_effects([eff("buff:excellent_condition", turn=7)], 0, CTX, P)
    assert s.breakdown[0].points == pytest.approx(15 * P.excellent_mult)


def test_action_economy_cycle_value():
    """行动经济族:线性 × 循环系数;使用数追加 > 抽牌。"""
    draw = score_effects([eff("action:draw", 2)], 0, CTX, P)
    play = score_effects([eff("action:play_add", 2)], 0, CTX, P)
    assert draw.breakdown[0].points == pytest.approx(2 * P.w_cycle)
    assert play.breakdown[0].points > draw.breakdown[0].points


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
# 修饰系数层 + C 层 + synergy(3.2/3.3)
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
    assert high.total == pytest.approx(-high.cost_penalty * P.global_scale)


def test_cost_layer_focus_consumption():
    """C 层:集中系消耗(cost_type 卡,如立ち位置チェック 集中消費3)线性折罚,不随体力比率放大。"""
    full = score_effects([], 0, DecisionContext(stamina_ratio=1.0), P, focus_cost=3)
    low = score_effects([], 0, DecisionContext(stamina_ratio=0.2), P, focus_cost=3)
    assert full.cost_penalty == pytest.approx(3 * P.w_focus_cost)
    assert low.cost_penalty == pytest.approx(3 * P.w_focus_cost)


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
    assert unknown.total == pytest.approx(early.total)  # days=None 与充足日数同为 1.0
    assert early.breakdown[0].points == pytest.approx(15)  # 10 日 → 不打折


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
# 量级对齐 + 真数据回归(3.5,A1 产物)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _DATA.exists(), reason="A1 产物 skill_card_effects.json 不存在")
class TestRealPoolData:
    def test_karui_ashidori_regression(self):
        """軽い足取り(パラメータ+6 好調2ターン,体力4)数值回归。"""
        s = score_card_by_name("軽い足取り", CTX, P)
        assert s is not None
        v = 6 + P.k_buff * math.log2(3)
        cost = 4 * P.w_cost * (1 + P.cost_slope * (1 - 0.7))
        assert s.total == pytest.approx((v - cost) * P.global_scale, abs=0.2)
        tags = {item.tag for item in s.breakdown}
        assert "score:parameter_add" in tags
        assert "buff:good_condition" in tags

    def test_tier_variant_lookup(self):
        """档位变体名(軽い足取り+)可查且分不低于無印(档位加成)。"""
        base = score_card_by_name("軽い足取り", CTX, P)
        plus = score_card_by_name("軽い足取り+", CTX, P)
        assert plus is not None and base is not None
        assert plus.total >= base.total - P.global_scale  # + 档数据可能同值,容忍等值

    def test_scale_alignment_good_condition_7t(self):
        """好調7ターン单效果卡落在 ≈8 分档(量级对齐,3.5)。"""
        s = score_effects([eff("buff:good_condition", turn=7)], 0, CTX, P)
        assert 6.5 <= s.total <= 9.5

    def test_pool_covers_key_cards(self):
        """关键卡与莉波固有卡在池中可查(非 None)。"""
        for name in ("お姉さんの感覚", "自然体の魅力", "包容力", "コール＆レスポンス"):
            assert score_card_by_name(name, CTX, P) is not None, name
