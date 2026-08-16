"""HIF 三选一结构化数值评分模型 v2(机制语义版,依据 docs/hif/mechanics.md §9 修正清单)。

总公式:
    score(card, context) = (V(效果族) × synergy − C(成本) ± 牌库项) × global_scale

v2 相对 v1 的语义修正(全部 A 级机制依据,见 mechanics.md):
- 好調 = ×1.5 乘区(S2 官方):log 饱和曲线保留作近似,k_buff 留校准
- 絶好調 = 1.5+0.1×好調層(S3 官方):固定 2.0 → 动态倍率(context 好調未知时用期望)
- 集中(ExamLessonBuff)= 一次性加算池 ×2.0/2.5 分层(S4/H10):从 log(turn) 改为
  value × 池系数(池数值本身在效果 value)
- 好印象 = 回合终了按层数延时得分(S5):价值随剩余出牌期望上升(early 因子)
- 使用数追加 = 净零成本出牌(M4/P1):数量在 count 字段(v1 误读 value 导致 0 分),
  估值为「额外行动机会」;行动机会成本模型留 P2/模拟器(opportunity_cost 默认 0)
- lesson_once(Lost,D1)= 用后除外:压缩补偿项 w_compression(牌库动力学 D4)
- Grave 循环卡 = 重洗回流可重复使用:效果 ×grave_repeat_mult
- 元気 = 体力优先支付缓冲(R2):w_energy 1.0
- 発動预约(timer 展开,A1 产物 v2):按 deferred_discount^延迟 折现
- C 层:体力比率折罚 + 集中/好調系 cost_type 罚不变;回合结束回体 2(S8)计入
  体力经济学注释(精确建模留模拟器);体力不足硬约束需绝对值,P2 接

数据源:assets/data/hif/skill_card_effects.json v2(含 move_position/is_lesson_once/
deferred_turns/level 字段);卡名 miss 返回 None 退关键词兜底(设计文档第 6 节)。
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

# 剩余日数 → 剩余出牌期望的折算(S1:每回合基准 1 张 + 追加;保守取 2,C 校准)。
APPEALS_PER_DAY = 2.0

# 好印象延时收益的满额出牌期望(剩余 ~10 次出牌时 early 因子打满)。
REVIEW_EARLY_FULL_APPEALS = 10.0

# 档位系数:同名卡高档位数值更强,池内 tiers 已分档存值,这里只调同卡跨档选择偏好。
_TIER_BONUS = {"無印": 0.0, "+": 0.5, "++": 1.0, "+++": 1.5}


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """三选一时刻的局面信号(mechanics.md §1/§3);None 表示该信号不可用,相关项退中性。"""

    stamina_ratio: float | None = None  # 当前体力/上限,1.0=满
    days_remaining: int | None = None  # 剩余日数(HUD 倒计时)
    good_condition_turns: int | None = None  # 当前好調剩余回合(HUD,Round 中可读;准备期 None)


@dataclass(frozen=True, slots=True)
class ScoringParams:
    """评分参数;C 阶段校准调参对象,global_scale/endgame_weight 经 GUI 暴露(B4)。"""

    global_scale: float = 0.53  # 量级对齐:好調7T(log 饱和 15)→ ≈8 分
    endgame_weight: float = 1.0  # 终盘权重(B4 GUI;0=关闭终盘衰减)
    # --- V 层:即得分 ---
    w_parameter: float = 1.0  # 每点参数直加
    # --- V 层:状态增益 ---
    k_buff: float = 5.0  # 好調 log₂(N+1) 饱和基数(×1.5 乘区的近似;3T=10/7T=15 未缩放)
    expected_good_turns: float = 5.0  # 絶好調动态倍率的期望好調層(context 未知时用;C 校准)
    w_focus_pool: float = 2.0  # 集中池每点价值(一次性加算 ×2.0 分层,S4/H10)
    w_review_pool: float = 2.0  # 好印象每层价值(延时即得分,S5;×(1+early) 因子)
    w_full_power_pool: float = 1.0  # 全力値每点
    # --- V 层:行动经济 ---
    w_cycle: float = 8.0  # 每张抽牌/使用数的循环价值(网格方向 ↑,C 校准)
    play_add_mult: float = 1.2  # 使用数追加相对抽牌(净零成本出牌,M4)
    extra_turn_value: float = 3.0  # ターン追加/再演(倍数于 w_cycle)
    deferred_discount: float = 0.7  # 発動预约每延迟 1 回合的折现率(timer 展开)
    # --- V 层:资源续航 ---
    w_energy: float = 1.0  # 每点元気(=体力优先缓冲,R2;v1 0.5 → v2 1.0)
    w_stamina_recover: float = 2.0  # 每点体力回復(×上下文系数)
    w_stamina_cost_down: float = 2.0  # 每点消費軽減(百分比/100)
    # --- V 层:代价妨害 ---
    w_penalty_stamina: float = 1.5  # 每点体力伤害/消費増罚
    # --- 修饰系数层 ---
    cond_factor: float = 0.8  # 条件発動/依赖型效果折扣(先验,校准承载)
    # --- C 层 ---
    w_cost: float = 0.4  # 每点 stamina 消耗的基准罚
    cost_slope: float = 1.0  # 体力比率每降 1.0 的罚增幅
    w_focus_cost: float = 0.3  # 每点集中/好調系消耗(cost_type)的罚,不随体力比率放大
    # --- 牌库项(D1/D4) ---
    w_compression: float = 1.5  # lesson_once(Lost 用后除外)的压缩补偿,未缩放
    grave_repeat_mult: float = 1.5  # Grave 循环卡(重洗回流)的效果重复使用乘数
    # --- 行动机会(P2 预留) ---
    opportunity_cost: float = 0.0  # 打出一张卡的行动机会成本占 w_cycle 比例;0=不启用


@dataclass(slots=True)
class ScoredEffect:
    """单条效果的评分明细(决策日志三件套消费)。"""

    tag: str
    points: float  # 族内分(未缩放)
    note: str = ""


def _remaining_appeals(context: DecisionContext) -> float | None:
    """剩余出牌期望(次);日数未知返回 None。"""
    if context.days_remaining is None:
        return None
    return max(context.days_remaining, 0) * APPEALS_PER_DAY


def _endgame_factor(turn: int, context: DecisionContext, params: ScoringParams) -> float:
    """终盘衰减(3.4):buff 需要后续回合铺垫,剩余出牌期望不足时打折。

    factor = min(1, remaining_appeals / turn) ** endgame_weight;日数未知或 turn=0 时恒 1。
    """
    if turn <= 0 or context.days_remaining is None or params.endgame_weight <= 0:
        return 1.0
    remaining_appeals = _remaining_appeals(context) or 0.0
    ratio = remaining_appeals / turn
    return min(1.0, ratio) ** params.endgame_weight


def _early_factor(context: DecisionContext, params: ScoringParams) -> float:
    """延时收益因子(好印象用,方向与 endgame 相反):剩余出牌期望越多,层数结算次数越多。"""
    remaining = _remaining_appeals(context)
    if remaining is None:
        return 0.5  # 中性:一半满额
    return min(1.0, remaining / REVIEW_EARLY_FULL_APPEALS)


def _excellent_mult(context: DecisionContext, params: ScoringParams) -> float:
    """絶好調动态倍率(S3):状态倍率 1.5+0.1×B 相对好調 1.5 的放大;B=context 好調或期望。"""
    b = context.good_condition_turns if context.good_condition_turns is not None else params.expected_good_turns
    return (1.5 + 0.1 * b) / 1.5


def _effect_points(effect: dict, context: DecisionContext, params: ScoringParams) -> tuple[float, str]:
    """单条效果 → 族内原始分与说明;未建模 tag 返回 (0, 说明) 不炸。"""
    tag = effect.get("tag") or "unmapped"
    # 使用数追加的数量在 count(v1 误读 value 导致 0 分,実データ 2026-08-16 実証)
    value = effect.get("value") or 0
    count = effect.get("count") or 0
    turn = effect.get("turn") or 0
    note = effect.get("name_jp") or tag

    def with_modifiers(points: float) -> float:
        # 修饰系数层:条件発動/依赖型(3.1)+ 発動预约延迟折现(timer 展开,A1 v2)
        if effect.get("condition"):
            points *= params.cond_factor
        delay = effect.get("deferred_turns") or 0
        if delay > 0:
            points *= params.deferred_discount ** delay
        return points

    if tag == "score:parameter_add":
        return with_modifiers(value * params.w_parameter), note
    if tag == "score:parameter_add_fix":
        return with_modifiers(value * params.w_parameter), note
    if tag == "score:parameter_add_cond":
        return with_modifiers(value * params.w_parameter * params.cond_factor), f"{note}(依赖)"
    if tag == "score:parameter_gain_mult":
        return with_modifiers(value / 100.0 * PARAM_GAIN_BASE * params.w_parameter), note
    if tag == "score:parameter_gain_mult_cond":
        return with_modifiers(value / 100.0 * PARAM_GAIN_BASE * params.w_parameter * params.cond_factor), f"{note}(依赖)"

    if tag == "buff:good_condition":
        # ×1.5 乘区近似(log 饱和):turn = 覆盖回合数
        return with_modifiers(params.k_buff * math.log2(turn + 1) * _endgame_factor(turn, context, params)), note
    if tag == "buff:excellent_condition":
        mult = _excellent_mult(context, params)
        return with_modifiers(
            params.k_buff * math.log2(turn + 1) * mult * _endgame_factor(turn, context, params)
        ), f"{note}(×{mult:.2f})"
    if tag == "buff:focus":
        # 集中 = 一次性加算池(S4/H10):value = 池数值,×分层倍率近似(強気1/2 由 effect.level 决定)
        level_mult = 2.5 if effect.get("level") == 2 else 2.0
        return with_modifiers(value * params.w_focus_pool * level_mult / 2.0), note
    if tag == "buff:good_impression":
        # 好印象 = 延时即得分(S5):层数 ×(1+early),越早堆收益越大
        return with_modifiers(value * params.w_review_pool * (1.0 + _early_factor(context, params))), note
    if tag == "buff:motivation":
        return with_modifiers(value * params.w_focus_pool * 0.8), note
    if tag == "buff:full_power":
        return with_modifiers(value * params.w_full_power_pool), note

    if tag == "action:draw":
        return with_modifiers(value * params.w_cycle), note
    if tag == "action:draw_replace":
        return with_modifiers(value * params.w_cycle * 0.5), note
    if tag == "action:play_add":
        n = count or value  # 数量在 count(実データ)
        return with_modifiers(n * params.w_cycle * params.play_add_mult), note
    if tag in ("action:extra_turn", "action:encore"):
        return with_modifiers(params.w_cycle * params.extra_turn_value), note

    if tag == "resource:energy":
        return with_modifiers(value * params.w_energy), note
    if tag == "resource:stamina_recover":
        # 上下文敏感(3.1):体力比率越低价值越高,满体力 ≈0;比率未知退中性 0.5
        ratio = context.stamina_ratio if context.stamina_ratio is not None else 0.5
        return with_modifiers(value * params.w_stamina_recover * (1.0 - ratio)), note
    if tag in ("resource:stamina_cost_down", "resource:stamina_cost_down_fix"):
        points = value / 100.0 * params.w_stamina_cost_down if effect.get("unit") == "pct" else value * 0.3
        return with_modifiers(points), note

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
    集中/好調系消耗(cost_type,cost_value)线性折罚,不随体力比率放大。
    注:每回合结束回体力 2(S8)未显式建模——它改变的是体力经济基准而非单卡差异,
    留给模拟器;体力不足不可用需体力绝对值,P2 接。"""
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
    deck_note: str = ""  # 牌库项说明(Lost 压缩/Grave 重复)
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
    repeat_mult: float = 1.0,
    compression_bonus: float = 0.0,
) -> CardScore:
    """效果列表(skill_card_effects.json v2 tiers[tier].effects)→ 卡评分。

    focus_cost:集中/好調系消耗点数(tier.cost_type 非 Unknown 时的 cost_value)。
    repeat_mult:Grave 循环卡的效果重复使用乘数(D1;Lost 卡传 1.0)。
    compression_bonus:lesson_once(Lost)压缩补偿(未缩放;Grave 卡传 0)。
    """
    params = params or ScoringParams()
    breakdown: list[ScoredEffect] = []
    v_total = 0.0
    for effect in effects or []:
        points, note = _effect_points(effect, context, params)
        v_total += points
        breakdown.append(ScoredEffect(tag=effect.get("tag") or "unmapped", points=points, note=note))
    v_total = v_total * repeat_mult + compression_bonus
    cost = _cost_penalty(stamina, context, params, focus_cost)
    synergy = 1.0  # P2 手牌跟踪激活前恒 1.0(3.3)
    total = (v_total * synergy - cost) * params.global_scale
    deck_note = []
    if repeat_mult != 1.0:
        deck_note.append(f"Grave×{repeat_mult}")
    if compression_bonus:
        deck_note.append(f"圧縮+{compression_bonus}")
    return CardScore(total=total, breakdown=breakdown, cost_penalty=cost, synergy=synergy, deck_note=" ".join(deck_note))


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
    # 牌库项(D1/D4):Lost=用后除外(压缩补偿);Grave=重洗回流(重复使用乘数)
    move = card.get("move_position")
    repeat_mult = params.grave_repeat_mult if (params and move == "Grave") else (
        ScoringParams().grave_repeat_mult if move == "Grave" else 1.0
    )
    compression = (params.w_compression if params else ScoringParams().w_compression) if card.get("is_lesson_once") else 0.0
    result = score_effects(
        tier.get("effects", []),
        tier.get("stamina"),
        context or DecisionContext(),
        params,
        focus_cost,
        repeat_mult=repeat_mult,
        compression_bonus=compression,
    )
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
