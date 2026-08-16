"""HIF 三选一结构化数值评分模型(设计文档 docs/hif/scoring-model-design.md 3.0-3.5 定案)。

总公式:
    score(card, context) = V(effect, magnitude) × synergy − C(cost, stamina_ratio)

- V 层五族曲线(3.1):即得分线性 / 状态增益 log 饱和 / 行动经济×循环系数 /
  资源续航线性(体力回復上下文敏感)/ 代价妨害线性罚;复合卡按族拆解求和。
- 修饰系数层:condition 非空的效果按 cond_factor 折扣(P1 命中率先验由
  tier 榜校准承载,不做显式条件建模)。
- C 层(3.2):stamina 按当前体力比率折罚,体力越低同额消耗罚越重。
- synergy(3.3):P1 恒 1.0 占位(缺手牌数据宁可不算不可误判)。
- 终盘衰减(3.4):剩余日数少时,N ターン长线 buff 按剩余出牌期望打折。
- 量级对齐(3.5):global_scale 使好調7ターン单效果 ≈8 分(旧表 絶好調=8 档),
  accept_threshold=4 的重抽语义不变。

数据源:A1 产物 assets/data/hif/skill_card_effects.json(流派过滤池,tag/value/turn);
卡名 miss 时本模块返回 None,调用方(rewards 链)退关键词评分兜底(设计文档第 6 节)。
"""

from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path
from functools import lru_cache
from dataclasses import field, dataclass

from agent.hif.decisions.hand_meta import _load_effects_pool, _split_tier_suffix

_DRINK_EFFECTS_PATH = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "drink_effects.json"

# 未提供局面信号时的中性默认:体力比率 0.7(中等)、终盘不衰减。
NEUTRAL_STAMINA_RATIO = 0.7

# ％转换/倍率类的基准存量估计(C 阶段校准对象)。
PARAM_GAIN_BASE = 50.0

# 剩余日数 → 剩余出牌期望的折算(每日演出次数基准,C 阶段校准对象)。
APPEALS_PER_DAY = 2.0

# 档位系数:同名卡高档位数值更强,但池内 tiers 已分档存值,这里只调同卡跨档选择偏好。
_TIER_BONUS = {"無印": 0.0, "+": 0.5, "++": 1.0, "+++": 1.5}


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """三选一时刻的局面信号(3.4);None 表示该信号不可用,相关项退中性。"""

    stamina_ratio: float | None = None  # 当前体力/上限,1.0=满
    days_remaining: int | None = None  # 剩余日数(HUD 倒计时)


@dataclass(frozen=True, slots=True)
class ScoringParams:
    """评分参数;C 阶段校准调参对象,global_scale/endgame_weight 经 GUI 暴露(B4)。"""

    global_scale: float = 0.53  # 量级对齐:好調7T(log 饱和 15)→ ≈8 分
    endgame_weight: float = 1.0  # 终盘权重(B4 GUI;0=关闭终盘衰减)
    w_parameter: float = 1.0  # 每点参数直加
    k_buff: float = 5.0  # buff 族 log₂(N+1) 饱和基数(3T=10 / 7T=15 未缩放)
    excellent_mult: float = 2.0  # 絶好調相对好調
    focus_mult: float = 0.9  # 集中/やる気/好印象相对好調
    w_cycle: float = 8.0  # 行动经济:每张抽牌/使用数的循环价值
    play_add_mult: float = 1.2  # 使用数追加相对抽牌
    extra_turn_value: float = 3.0  # ターン追加/再演(倍数于 w_cycle)
    w_energy: float = 0.5  # 每点元気
    w_stamina_recover: float = 2.0  # 每点体力回復(×上下文系数)
    w_stamina_cost_down: float = 2.0  # 每点消費軽減(百分比/100)
    w_penalty_stamina: float = 1.5  # 每点体力伤害/消費増罚
    cond_factor: float = 0.8  # 条件発動/依赖型效果折扣(先验,校准承载)
    w_cost: float = 0.4  # C 层:每点 stamina 消耗的基准罚
    cost_slope: float = 1.0  # C 层:体力比率每降 1.0 的罚增幅
    w_focus_cost: float = 0.3  # C 层:每点集中/好調系消耗(cost_type)的罚,不随体力比率放大


@dataclass(slots=True)
class ScoredEffect:
    """单条效果的评分明细(决策日志三件套消费)。"""

    tag: str
    points: float  # 族内分(未缩放)
    note: str = ""


def _endgame_factor(turn: int, context: DecisionContext, params: ScoringParams) -> float:
    """终盘衰减(3.4):buff 需要后续回合铺垫,剩余出牌期望不足时打折。

    factor = min(1, remaining_appeals / turn) ** endgame_weight;日数未知或 turn=0 时恒 1。
    """
    if turn <= 0 or context.days_remaining is None or params.endgame_weight <= 0:
        return 1.0
    remaining_appeals = max(context.days_remaining, 0) * APPEALS_PER_DAY
    ratio = remaining_appeals / turn
    return min(1.0, ratio) ** params.endgame_weight


def _effect_points(effect: dict, context: DecisionContext, params: ScoringParams) -> tuple[float, str]:
    """单条效果 → 族内原始分与说明;未建模 tag 返回 (0, 说明) 不炸。"""
    tag = effect.get("tag") or "unmapped"
    value = effect.get("value") or 0
    turn = effect.get("turn") or 0
    note = effect.get("name_jp") or tag

    def cond(points: float) -> tuple[float, str]:
        # 修饰系数层:条件発動/依赖型(3.1)与 playEffects 触发条件统一折扣
        if effect.get("condition"):
            return points * params.cond_factor, f"{note}(条件)"
        return points, note

    if tag == "score:parameter_add":
        return cond(value * params.w_parameter)
    if tag == "score:parameter_add_fix":
        return cond(value * params.w_parameter)
    if tag == "score:parameter_add_cond":
        return value * params.w_parameter * params.cond_factor, f"{note}(依赖)"
    if tag == "score:parameter_gain_mult":
        return cond(value / 100.0 * PARAM_GAIN_BASE * params.w_parameter)
    if tag == "score:parameter_gain_mult_cond":
        return value / 100.0 * PARAM_GAIN_BASE * params.w_parameter * params.cond_factor, f"{note}(依赖)"

    if tag == "buff:good_condition":
        return cond(params.k_buff * math.log2(turn + 1) * _endgame_factor(turn, context, params))
    if tag == "buff:excellent_condition":
        return cond(
            params.k_buff * math.log2(turn + 1) * params.excellent_mult * _endgame_factor(turn, context, params)
        )
    if tag in ("buff:focus", "buff:motivation", "buff:good_impression", "buff:full_power"):
        return cond(params.k_buff * math.log2(turn + 1) * params.focus_mult * _endgame_factor(turn, context, params))

    if tag == "action:draw":
        return cond(value * params.w_cycle)
    if tag == "action:draw_replace":
        return cond(value * params.w_cycle * 0.5)
    if tag == "action:play_add":
        return cond(value * params.w_cycle * params.play_add_mult)
    if tag in ("action:extra_turn", "action:encore"):
        return cond(params.w_cycle * params.extra_turn_value)

    if tag == "resource:energy":
        return cond(value * params.w_energy)
    if tag == "resource:stamina_recover":
        # 上下文敏感(3.1):体力比率越低价值越高,满体力 ≈0;比率未知退中性 0.5
        ratio = context.stamina_ratio if context.stamina_ratio is not None else 0.5
        return cond(value * params.w_stamina_recover * (1.0 - ratio))
    if tag in ("resource:stamina_cost_down", "resource:stamina_cost_down_fix"):
        return cond(value / 100.0 * params.w_stamina_cost_down if effect.get("unit") == "pct" else value * 0.3)

    if tag == "penalty:stamina_damage":
        return -value * params.w_penalty_stamina, note
    if tag in ("penalty:stamina_cost_add", "penalty:stamina_cost_add_fix"):
        magnitude = value / 100.0 * 4.0 if effect.get("unit") == "pct" else value
        return -magnitude * params.w_penalty_stamina, note

    # 未建模(container/stance/defense/unmapped 等):不计分,保真记录
    return 0.0, f"{note}(未建模)"


def _cost_penalty(
    stamina: int | None,
    context: DecisionContext,
    params: ScoringParams,
    focus_cost: int | None = None,
) -> float:
    """C 层(3.2):体力消耗按当前比率折罚(stamina 缺失/0 → 0);
    集中/好調系消耗(cost_type,cost_value)线性折罚,不随体力比率放大。"""
    ratio = context.stamina_ratio if context.stamina_ratio is not None else NEUTRAL_STAMINA_RATIO
    ratio = min(max(ratio, 0.0), 1.0)
    penalty = (stamina or 0) * params.w_cost * (1.0 + params.cost_slope * (1.0 - ratio))
    penalty += (focus_cost or 0) * params.w_focus_cost
    return penalty


@dataclass(slots=True)
class CardScore:
    """卡评分结果:总分(缩放后)+ 族内明细 + 元信息。"""

    total: float
    breakdown: list[ScoredEffect] = field(default_factory=list)
    cost_penalty: float = 0.0
    synergy: float = 1.0
    source: str = "effects_pool"

    @property
    def scaled_total(self) -> float:
        return self.total


def score_effects(
    effects: list[dict],
    stamina: int | None,
    context: DecisionContext,
    params: ScoringParams | None = None,
    focus_cost: int | None = None,
) -> CardScore:
    """效果列表(skill_card_effects.json tiers[tier].effects)→ 卡评分。

    focus_cost:集中/好調系消耗点数(tier.cost_type 非 Unknown 时的 cost_value)。
    """
    params = params or ScoringParams()
    breakdown: list[ScoredEffect] = []
    v_total = 0.0
    for effect in effects or []:
        points, note = _effect_points(effect, context, params)
        v_total += points
        breakdown.append(ScoredEffect(tag=effect.get("tag") or "unmapped", points=points, note=note))
    cost = _cost_penalty(stamina, context, params, focus_cost)
    synergy = 1.0  # P2 手牌跟踪激活前恒 1.0(3.3)
    total = (v_total * synergy - cost) * params.global_scale
    return CardScore(total=total, breakdown=breakdown, cost_penalty=cost, synergy=synergy)


def score_card_by_name(
    card_name: str,
    context: DecisionContext | None = None,
    params: ScoringParams | None = None,
    effects_pool: dict[str, dict] | None = None,
) -> CardScore | None:
    """按卡名(含档位符号,NFKC 归一后)查流派过滤池评分。

    未命中返回 None——调用方退关键词评分兜底(设计文档第 6 节,断崖为零)。
    """
    pool = effects_pool if effects_pool is not None else _load_effects_pool()
    if not pool:
        return None
    base, suffix = _split_tier_suffix(card_name)
    card = pool.get(unicodedata.normalize("NFKC", base))
    if card is None:
        return None
    tier_key = {"": "無印", "+": "+", "++": "++", "+++": "+++"}.get(suffix, "無印")
    tier = card.get("tiers", {}).get(tier_key) or card.get("tiers", {}).get("無印")
    if not tier:
        return None
    focus_cost = tier.get("cost_value") if tier.get("cost_type") not in (None, "", "ExamCostType_Unknown") else None
    result = score_effects(tier.get("effects", []), tier.get("stamina"), context or DecisionContext(), params, focus_cost)
    result.total += _TIER_BONUS.get(tier_key, 0.0) * (params.global_scale if params else ScoringParams().global_scale)
    return result


@lru_cache(maxsize=1)
def _load_drink_effects() -> dict[str, dict]:
    """饮料效果池(A1 产物 drink_effects.json,in_pool=莉波路线可用 17 种),键 NFKC 归一。"""
    if not _DRINK_EFFECTS_PATH.exists():
        return {}
    raw = json.loads(_DRINK_EFFECTS_PATH.read_text(encoding="utf-8"))
    return {
        unicodedata.normalize("NFKC", drink["name_jp"]): drink
        for drink in raw.get("drinks", [])
        if drink.get("in_pool")
    }


def score_drink_by_name(
    drink_name: str,
    context: DecisionContext | None = None,
    params: ScoringParams | None = None,
    drink_pool: dict[str, dict] | None = None,
) -> CardScore | None:
    """按饮料名查效果池评分(饮料无体力成本,C 层恒 0);未命中返回 None 退关键词兜底。"""
    pool = drink_pool if drink_pool is not None else _load_drink_effects()
    if not pool:
        return None
    drink = pool.get(unicodedata.normalize("NFKC", drink_name))
    if drink is None:
        return None
    return score_effects(drink.get("effects", []), None, context or DecisionContext(), params)
