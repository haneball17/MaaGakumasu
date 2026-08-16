"""效果执行引擎(roundsim-design.md §5)。

数据驱动:消费 skill_card_effects.json 结构化效果行,按 effect_type(非 tag——同名 tag
可能对应多种数据语义,如 score:parameter_add_cond 既可能是 体力依存 也可能是 使用数依存)
分发到执行器;新卡 = 数据行,不是代码(§2 原则 6)。

MVP 建模范围 = 莉波実機 20 张 + 基本卡池 5 种涉及的 effect_type / 使用可门槛 / 效果级条件,
全部列举在 SUPPORTED_* 常量并由 precheck 看守:范围外的卡进卡组 → DeckPrecheckError
硬失败(§2 原则 4:A/B 结论可信度 > 覆盖率),报错列出卡名与缺失项。

S1 得分函数(§3.1 #8,官方常量逐级 ceil):
    出牌得分 = ceil( ceil((基础值 + 集中×档位倍率 + 附加) × 状態倍率)
                     × 属性有效参数/100 × (1+得分上升量/100) × 不調修正 )
    状態倍率 = 1.5(好調) + 0.1×好調層(絶好調時,相加 S3)
実機算例回归: kjirou (23 + 4×2.0) × (1.5+0.6) = 65.10 → 逐级 ceil → 66。

使用数/再演/もう1回発動语义(M4/R3/R4)由 runner 持有状态,本引擎只执行单卡效果列表。
"""

from __future__ import annotations

import re
import math
from dataclasses import field, dataclass

from agent.hif.roundsim.deck import CardSpec
from agent.hif.roundsim.trace import EffectTrace, ScoreDetail
from agent.hif.roundsim.settings import (
    GOOD_CONDITION_PERMIL,
    CONCENTRATION_LESSON_MULT_L1,
    CONCENTRATION_LESSON_MULT_L2,
    EXCELLENT_ADD_PER_TURN_PERMIL,
)

# ---------------------------------------------------------------------------
# 支持清单(precheck 看守;扩展 = 显式加行 + 配套执行器 + 测试)
# ---------------------------------------------------------------------------

# effect_type 短名(去 ProduceExamEffectType_ 前缀)→ 执行器说明
SUPPORTED_EFFECT_TYPES: dict[str, str] = {
    "ExamLesson": "レッスン値加算(即得分)",
    "ExamLessonAddMultipleParameterBuff": "レッスン値加算+好調時×(value2/1000)(ステージングの基本:好調効果を2倍適用)",
    "ExamLessonDependStamina": "体力依存レッスン値(自然体の魅力:体力のN‰)",
    "ExamLessonDependPlayCardCountSum": "使用卡数依存レッスン値(+base+per_card×使用数)",
    "ExamParameterBuff": "好調付与(turn ターン)",
    "ExamParameterBuffMultiplePerTurn": "絶好調付与(turn ターン)",
    "ExamLessonBuff": "集中値池加算(value)",
    "ExamBlock": "元気加算(value)",
    "ExamStaminaRecoverMultiple": "最大体力の value‰ 回復",
    "ExamPlayableValueAdd": "使用数追加(count)",
    "ExamCardDraw": "抽牌 value 枚(deferred_turns>0 → N ターン後)",
    "ExamEffectTimer": "timer 容器行(no-op:延迟语义已平展到成对效果的 deferred_turns,スポットライト)",
    "ExamStatusEnchantEncore": "再演 enchant(条件卡在手時、任意卡使用後に自身再使用)",
    "ExamCardSearchEffectPlayCountBuff": "次に使用するカードの効果をもう1回発動",
}

# 效果级条件(condition 字段 = trigger/search id)→ 判定语义
SUPPORTED_CONDITIONS: dict[str, str] = {
    "": "无条件",
    "e_trigger-exam_card_play-lesson_buff_up-3": "集中値 ≥3 時発動(深呼吸の好調)",
    "e_trigger-none-card_search_count_up-2-p_card_search-trouble-not_lost": "除外以外にトラブルカード ≥2(パンプアップ追加値)",
    "p_card_search-n-r-sr-ssr-playing": "もう1回発動対象指定(N~SSR,実質全卡)",
}

# 卡级使用可门槛(play_trigger)解析:pattern → (状态键, 阈值)
_PLAY_TRIGGER_PATTERNS: dict[re.Pattern, str] = {
    re.compile(r"^e_trigger-none-parameter_buff_up-(\d+)$"): "good_condition",
    re.compile(r"^e_trigger-none-parameter_buff_multiple_per_turn_up-(\d+)$"): "excellent_condition",
}


def parse_play_gate(trigger: str) -> tuple[str, int] | None:
    """使用可门槛 → (状态键, 阈值);空串 → None;未知模式 → DeckPrecheckError。"""
    if not trigger:
        return None
    for pattern, key in _PLAY_TRIGGER_PATTERNS.items():
        m = pattern.match(trigger)
        if m:
            return key, int(m.group(1))
    from agent.hif.roundsim.deck import DeckPrecheckError

    raise DeckPrecheckError(f"未知使用可门槛 trigger: {trigger}")


def concentration_mult(level: int | None) -> float:
    """集中(強気)分层倍率(S4/H10:1 级 ×2.0 / 2 级 ×2.5)。"""
    return CONCENTRATION_LESSON_MULT_L2 if level == 2 else CONCENTRATION_LESSON_MULT_L1


# ---------------------------------------------------------------------------
# S1 得分函数(官方常量,零拟合; kjirou/lts129/kanon511 三实现交叉)
# ---------------------------------------------------------------------------


def state_multiplier(good_turns: int, excellent_active: bool, good_layers: int) -> float:
    """状態倍率(S2/S3):好調 → ×1.5(替换基线 1.0);絶好調時 +0.1×好調層(相加)。

    kjirou 整数实现:multiplier(十分位) = 好調?15:10 + (好調&&絶好調 ? 好調層 : 0)。
    絶好調加成依赖好調存量(无好調時絶好調不生效)。
    """
    if good_turns <= 0:
        return 1.0
    mult = GOOD_CONDITION_PERMIL / 1000
    if excellent_active:
        mult += EXCELLENT_ADD_PER_TURN_PERMIL / 1000 * good_layers
    return mult


def s1_lesson_score(
    base_value: float,
    focus_add: float = 0.0,
    good_turns: int = 0,
    excellent_active: bool = False,
    good_layers: int = 0,
    param: int = 100,
    score_up_permil: int = 0,
    bad: bool = False,
) -> ScoreDetail:
    """单次出牌得分(逐级 ceil,mechanics S1 总式)。

    base_value:卡面 レッスン値合计(基础+附加);focus_add:集中加算(池值×档位倍率,已由调用方算好)。
    param:本回合流行属性有效参数(S6 玩家侧 = 参数/100)。
    """
    mult = state_multiplier(good_turns, excellent_active, good_layers)
    stage1 = math.ceil((base_value + focus_add) * mult)
    score_up = 1 + score_up_permil / 1000
    param_mult = param / 100
    bad_mult = 0.667 if bad else 1.0
    points = math.ceil(stage1 * param_mult * score_up * bad_mult)
    return ScoreDetail(
        base_value=int(base_value),
        focus_value=int(focus_add),
        state_mult=round(mult, 4),
        param_mult=param_mult,
        score_up_mult=score_up,
        bad_mult=bad_mult,
        points=points,
        formula=f"({base_value}{'+' + str(focus_add) if focus_add else ''})×{mult:.4g}→{stage1} ×{param_mult:.4g} = {points}",
    )


# ---------------------------------------------------------------------------
# 效果执行
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EngineContext:
    """单次执行快照(runner 传入;engine 只读写这些状态,不触 zones 之外的任何东西)。

    trouble_not_lost:除外以外のトラブルカード数(パンプアップ条件);
    good_turns:当前好調層(ステージングの基本の2倍適用判定);
    scheduled_draws:延迟抽牌队列 [(due_turn, count)](runner 持有,engine 追加)。
    """

    turn: int
    stamina: int
    max_stamina: int
    cards_played: int
    focus: int
    trouble_not_lost: int
    good_turns: int = 0
    scheduled_draws: list[tuple[int, int]] = field(default_factory=list)


@dataclass(slots=True)
class EffectOutcome:
    """一次效果列表执行的结果(裁判汇总成 trace 与得分)。"""

    lesson_value: float = 0.0  # 本卡 レッスン値合计(S1 的 base_value)
    good_add: int = 0  # 好調付与ターン数合计
    excellent_add: int = 0  # 絶好調付与ターン数合计
    focus_add: int = 0  # 集中値池加算
    energy_add: int = 0  # 元気加算
    stamina_heal: int = 0  # 体力回復量(最大体力‰)
    play_add: int = 0  # 使用数追加
    immediate_draw: int = 0  # 即时抽牌张数
    encore: bool = False  # 再演 enchant 付与
    repeat_next: bool = False  # もう1回発動付与
    events: list[EffectTrace] = field(default_factory=list)


def _condition_met(condition: str | None, ctx: EngineContext, focus_now: int) -> bool:
    """效果级条件判定;支持清单外的条件已在 precheck 拦截,此处只判已知语义。"""
    cond = condition or ""
    if cond == "":
        return True
    if cond == "e_trigger-exam_card_play-lesson_buff_up-3":
        return focus_now >= 3
    if cond == "e_trigger-none-card_search_count_up-2-p_card_search-trouble-not_lost":
        return ctx.trouble_not_lost >= 2
    if cond == "p_card_search-n-r-sr-ssr-playing":
        return True
    return False


def execute_effects(spec: CardSpec, ctx: EngineContext) -> EffectOutcome:
    """按数据行执行一张卡的效果列表(顺序 = 数据行顺序,状态依存效果用执行时值)。

    focus 消耗由 runner 在调用前扣除;本函数只加不减。
    """
    out = EffectOutcome()
    focus_now = ctx.focus
    for eff in spec.effects:
        etype = (eff.get("effect_type") or "").replace("ProduceExamEffectType_", "")
        tag = eff.get("tag") or "unmapped"
        value = eff.get("value") or 0
        value2 = eff.get("value2") or 0
        turns = eff.get("turn") or 0
        count = eff.get("count") or 0
        note = eff.get("name_jp") or tag
        # 效果级条件统一门控(支持面外条件已在 precheck 拦截):不满足则整行跳过
        if not _condition_met(eff.get("condition"), ctx, focus_now):
            continue
        if etype == "ExamLesson":
            out.lesson_value += value
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"レッスン値+{value}"))
        elif etype == "ExamLessonAddMultipleParameterBuff":
            mult = 1 + value2 / 1000 if ctx.good_turns > 0 else 1
            gained = value * mult
            out.lesson_value += gained
            out.events.append(
                EffectTrace(tag=tag, note=note, detail=f"レッスン値+{value}" + (f"(好調×{mult:g})={gained:g}" if mult > 1 else ""))
            )
        elif etype == "ExamLessonDependStamina":
            gained = ctx.stamina * value / 1000
            out.lesson_value += gained
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"体力{ctx.stamina}の{value / 10}%=+{gained:g}"))
        elif etype == "ExamLessonDependPlayCardCountSum":
            gained = value + value2 * ctx.cards_played
            out.lesson_value += gained
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"+{value}+{value2}×{ctx.cards_played}使用={gained}"))
        elif etype == "ExamParameterBuff":
            out.good_add += turns
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"好調+{turns}T"))
        elif etype == "ExamParameterBuffMultiplePerTurn":
            out.excellent_add += turns
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"絶好調+{turns}T"))
        elif etype == "ExamLessonBuff":
            out.focus_add += value
            focus_now += value
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"集中+{value}"))
        elif etype == "ExamBlock":
            out.energy_add += value
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"元気+{value}"))
        elif etype == "ExamStaminaRecoverMultiple":
            heal = math.ceil(ctx.max_stamina * value / 1000)
            out.stamina_heal += heal
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"最大体力の{value / 10}%回復=+{heal}"))
        elif etype == "ExamPlayableValueAdd":
            n = count or value
            out.play_add += n
            out.events.append(EffectTrace(tag=tag, note=note, detail=f"使用数+{n}"))
        elif etype == "ExamCardDraw":
            deferred = eff.get("deferred_turns") or 0
            if deferred > 0:
                ctx.scheduled_draws.append((ctx.turn + deferred, value))
                out.events.append(EffectTrace(tag=tag, note=note, detail=f"{deferred}ターン後に{value}枚引く"))
            else:
                out.immediate_draw += value
                out.events.append(EffectTrace(tag=tag, note=note, detail=f"{value}枚引く"))
        elif etype == "ExamEffectTimer":
            out.events.append(EffectTrace(tag=tag, note=note, detail="timer 容器(延迟语义在成对效果行)"))
        elif etype == "ExamStatusEnchantEncore":
            out.encore = True
            out.events.append(EffectTrace(tag=tag, note="再演", detail=f"条件卡在手時自身再使用,{count}回まで"))
        elif etype == "ExamCardSearchEffectPlayCountBuff":
            out.repeat_next = True
            out.events.append(EffectTrace(tag=tag, note="もう1回発動", detail="次に使用するカードの効果をもう1回発動"))
        else:  # precheck 已拦,防御性兜底
            out.events.append(EffectTrace(tag=tag, note=note, detail="未建模(不应到达)"))
    return out


def precheck(entries: list) -> list[CardSpec]:
    """卡组预检:逐卡解析 + 效果/条件/门槛支持面检查,不支持即 DeckPrecheckError 列明细。

    返回解析后的 CardSpec 列表(与 entries 同序)。莉波池外 tag 不会到这里——
    resolve_card 先按卡名拦截;这里拦的是「池内但效果未建模」的卡。
    """
    from agent.hif.roundsim.deck import DeckPrecheckError, resolve_card

    specs: list[CardSpec] = []
    problems: list[str] = []
    for entry in entries:
        spec = resolve_card(entry)
        specs.append(spec)
        gate = spec.play_trigger
        try:
            parse_play_gate(gate)
        except DeckPrecheckError as e:
            problems.append(f"{spec.name}({spec.tier}): {e}")
        for eff in spec.effects:
            etype = (eff.get("effect_type") or "").replace("ProduceExamEffectType_", "")
            if etype not in SUPPORTED_EFFECT_TYPES:
                problems.append(f"{spec.name}({spec.tier}): 未建模效果类型 {etype}({eff.get('tag')})")
            cond = eff.get("condition") or ""
            if cond not in SUPPORTED_CONDITIONS:
                problems.append(f"{spec.name}({spec.tier}): 未建模条件 {cond}")
    if problems:
        raise DeckPrecheckError("卡组预检失败(未建模项):\n  " + "\n  ".join(problems))
    return specs


def inventory_unmodeled_tags(entries: list) -> dict[str, int]:
    """盘点:卡组内未建模 tag 计数(A/B 报告附注用;莉波池应为空)。"""
    from agent.hif.roundsim.deck import DeckPrecheckError, resolve_card

    counts: dict[str, int] = {}
    for entry in entries:
        try:
            spec = resolve_card(entry)
        except DeckPrecheckError:
            continue
        for eff in spec.effects:
            etype = (eff.get("effect_type") or "").replace("ProduceExamEffectType_", "")
            if etype not in SUPPORTED_EFFECT_TYPES:
                counts[eff.get("tag") or "unmapped"] = counts.get(eff.get("tag") or "unmapped", 0) + 1
    return counts
