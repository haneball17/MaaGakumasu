"""回合循环与考试状态推进(roundsim-design.md §3.1 #5/#7,§3.3)。

裁判(本模块)只执行规则与计分;策略(选手)经 Strategy 协议接入,收到 ExamView 投影、
返回 CardAction(decisions/state.py 复用)。非法动作(卡不在手/门槛不满足/资源不足/
使用数耗尽)→ IllegalActionError 硬报错(§3.3 预检报错,不猜策略意图)。

- 流行序列双模式:fixed / j3_random(J3 规则,首回合权重 A4 假设)。
- buff 递减(R1/kjirou 快照模型):回合 t 开始,granted_turn ≤ t-2 的 buff 各 -1
  (付与回合保护:当回合与下一回合不减);归零移除。考试初始 buff granted_turn=0。
- 使用数(M4/R3):基准每回合 1;play_add 打出即回补(净行动成本≈0);SKIP 不消耗、
  卡付与追加可延续到下回合;一旦出卡,残余(未消费的)卡追加清零。
- 再演(R4):enchant 付与後,任意卡使用時に条件卡(自然体の魅力)在手且本ターン未発動
  → 自身效果再执行(不消耗コスト/使用数),{count}回まで・ターン内1回;再演后源卡进 Grave 可回流。
- もう1回発動:次に使用するカードの効果再执行一遍(第二个得分条目)。
- RNG 全注入式:洗牌/流行/対手分共用 random.Random(seed)(A/B 用 CRN 同批种子)。
"""

from __future__ import annotations

import random
from typing import Protocol
from dataclasses import field, dataclass

from agent.hif.roundsim import engine
from agent.hif.roundsim.deck import DeckZones, CardInstance
from agent.hif.roundsim.spec import PopularMode, FixedPopular, ScenarioSpec, J3RandomPopular
from agent.hif.roundsim.trace import (
    TurnTrace,
    FinalTrace,
    SpecDigest,
    ActionTrace,
    EffectTrace,
    ScoreDetail,
    OpponentRoll,
    TriggerTrace,
    StateSnapshot,
    TraceDocument,
)
from agent.hif.decisions.state import ActionKind, CardAction

_DECAY_KINDS = {"good_condition", "excellent_condition"}  # R1 衰减名单(好印象/消費増減不在莉波池)


class IllegalActionError(Exception):
    """策略返回非法动作:裁判拒绝执行并报错(§3.3)。"""


@dataclass(slots=True)
class BuffState:
    """带付与回合标记的状态 buff(R1 递减时机建模)。"""

    kind: str  # good_condition / excellent_condition / ...
    remaining: int  # 剩余ターン
    granted_turn: int  # 付与回合(0 = 考试初始)


@dataclass(slots=True)
class EncoreState:
    """再演 enchant(R4:「憧れ…」无关,お姉さんの感覚付与)。"""

    source_name: str  # 源卡名(お姉さんの感覚)
    condition_name: str  # 条件卡名(自然体の魅力)
    remaining: int  # 剩余発動回数(4)
    used_this_turn: bool = False


@dataclass(slots=True)
class ExamRuntime:
    """考试局内状态(裁判持有,策略只能看 ExamView 投影)。"""

    stamina: int
    max_stamina: int
    energy: int = 0
    focus: int = 0
    cards_played: int = 0  # 累计出牌数(自然体の魅力 +N/张 的基数)
    buffs: list[BuffState] = field(default_factory=list)
    p_drinks: dict[str, int] = field(default_factory=dict)
    usable: int = 1  # 本回合剩余使用数
    card_adds_pending: int = 0  # 卡付与の追加(SKIP 可延续;出卡后残余清零)
    repeat_next: int = 0  # もう1回発動待発数
    encore: EncoreState | None = None
    scheduled_draws: list[tuple[int, int]] = field(default_factory=list)  # (due_turn, count)

    def buff_value(self, kind: str) -> int:
        """同类 buff 叠加量(好調層 = Σremaining;无则 0)。"""
        return sum(b.remaining for b in self.buffs if b.kind == kind and b.remaining > 0)

    def add_buff(self, kind: str, turns: int, granted_turn: int) -> None:
        if turns <= 0:
            return
        self.buffs.append(BuffState(kind=kind, remaining=turns, granted_turn=granted_turn))

    def decay_buffs(self, turn: int) -> list[str]:
        """回合开始递减(R1:granted_turn ≤ turn-2 的各 -1,归零移除),返回递减明细。"""
        events: list[str] = []
        for buff in self.buffs:
            if buff.kind in _DECAY_KINDS and buff.remaining > 0 and buff.granted_turn <= turn - 2:
                buff.remaining -= 1
                events.append(f"{buff.kind}→{buff.remaining}")
        self.buffs = [b for b in self.buffs if b.remaining > 0]
        return events

    def consume_good_layers(self, amount: int) -> None:
        """消耗好調層(国民的アイドル的 ExamParameterBuff 成本):从最早的 buff 实例扣。"""
        for buff in sorted(self.buffs, key=lambda b: b.granted_turn):
            if buff.kind != "good_condition" or amount <= 0:
                continue
            take = min(buff.remaining, amount)
            buff.remaining -= take
            amount -= take
        self.buffs = [b for b in self.buffs if b.remaining > 0]

    def snapshot(self, usable_left: int = 0) -> StateSnapshot:
        return StateSnapshot(
            stamina=self.stamina,
            energy=self.energy,
            good_condition_turns=self.buff_value("good_condition"),
            excellent_condition_turns=self.buff_value("excellent_condition"),
            focus=self.focus,
            cards_played=self.cards_played,
            usable_left=usable_left,
        )


# ---------------------------------------------------------------------------
# 策略接口(裁判-选手协议,§3.3/§6.1)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PlayableCard:
    """ExamView 里的手牌条目(含裁判算好的合法性,策略无需重复判)。"""

    label: str
    name: str
    tier: str
    stamina_cost: int  # 体力+固定合计
    focus_cost: int  # 集中コスト(0 = 无)
    good_cost: int  # 好調層コスト(0 = 无)
    playable: bool
    blockers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExamView:
    """策略投影(裁判只读视图;M4 适配 decisions.ExamState 时复用同源字段)。"""

    round_tag: str  # "honsen_r1" / "honsen_r2"
    turn: int
    total_turns: int
    flow: str  # Vo/Da/Vi
    params: dict[str, int]  # 有效参数
    stamina: int
    max_stamina: int
    energy: int
    focus: int
    good_condition_turns: int
    excellent_condition_turns: int
    usable_left: int
    cards_played: int
    hand: list[PlayableCard]
    deck_size: int
    p_drinks: dict[str, int]
    reprise_remaining: int  # 再演剩余回数(0 = 无/耗尽)
    repeat_next: int


class Strategy(Protocol):
    """选手协议:name 用于报告/trace;decide 每次出牌机会调用一次。"""

    name: str

    def decide(self, view: ExamView) -> CardAction: ...


class FirstLegalStrategy:
    """占位选手(M2/M3 引擎验证用):出手牌中第一张可出卡,否则 SKIP。

    无决策智能——顺序 = 手牌顺序(发牌序);A/B 对照在 M4 由贪心/GarakutaRinami 取代。
    """

    name = "first_legal"

    def decide(self, view: ExamView) -> CardAction:
        for card in view.hand:
            if card.playable:
                return CardAction(ActionKind.PLAY_CARD, card.label, f"first_legal:出第一张可出卡 {card.label}")
        return CardAction(ActionKind.SKIP, None, "first_legal:无可出卡,Skip")


# ---------------------------------------------------------------------------
# 流行序列
# ---------------------------------------------------------------------------


def generate_popular_sequence(mode: PopularMode, turns: int, rng: random.Random) -> list[str]:
    """流行属性序列(§3.1 #5):fixed 显式注入;j3_random 末 3 回合固定 3→2→1 位。"""
    if isinstance(mode, FixedPopular):
        if len(mode.turns) != turns:
            raise ValueError(f"fixed 流行序列长度 {len(mode.turns)} ≠ turns {turns}")
        return list(mode.turns)
    criteria = {k: v for k, v in mode.criteria.items() if k in ("Vo", "Da", "Vi")}
    if len(criteria) != 3:
        raise ValueError(f"j3_random criteria 须含 Vo/Da/Vi 三属性: {criteria}")
    ranked = sorted(criteria, key=criteria.get, reverse=True)  # [1位, 2位, 3位]
    tail = [ranked[2], ranked[1], ranked[0]][max(0, 3 - turns):]  # 末 3 回合低→高(turns<3 截断)
    head_len = turns - len(tail)
    first_weights = mode.first_weights or criteria
    attrs = list(criteria.keys())
    seq: list[str] = []
    for i in range(head_len):
        weights = first_weights if i == 0 else criteria
        seq.append(rng.choices(attrs, weights=[weights.get(a, 0) for a in attrs], k=1)[0])
    return seq + tail


# ---------------------------------------------------------------------------
# 裁判
# ---------------------------------------------------------------------------


class RoundSimRunner:
    """单场考试裁判。run() 产出 TraceDocument;同 spec + 同 seed 完全可复现。"""

    def __init__(
        self,
        spec: ScenarioSpec,
        seed: int,
        strategy_name: str = "skip-only",
        preset_name: str = "",
    ) -> None:
        self.spec = spec
        self.seed = seed
        self.strategy_name = strategy_name
        self.preset_name = preset_name
        self.rng = random.Random(seed)
        settings = spec.exam_settings
        self.popular = generate_popular_sequence(spec.scenario.popular_mode, settings.turns, self.rng)
        # M2 预检:未建模卡硬失败(§5)
        engine.precheck(spec.scenario.deck)
        # M3:P item trigger(憧れ続けた輝き 等;未注册道具名 → None)
        from agent.hif.roundsim.triggers import build_trigger

        self.trigger = build_trigger(spec.scenario.p_items.idol_exclusive)

    # -- 视图与合法性 --------------------------------------------------------

    def _playable(self, card: CardInstance, runtime: ExamRuntime) -> PlayableCard:
        spec = card.spec
        blockers: list[str] = []
        gate = engine.parse_play_gate(spec.play_trigger)
        if gate is not None:
            key, threshold = gate
            if runtime.buff_value(key) < threshold:
                blockers.append(f"使用可门槛 {key}≥{threshold} 不满足")
        focus_cost = good_cost = 0
        if spec.cost_type == "ExamCostType_ExamLessonBuff":
            focus_cost = spec.cost_value or 0
            if runtime.focus < focus_cost:
                blockers.append(f"集中{runtime.focus}<{focus_cost}")
        elif spec.cost_type == "ExamCostType_ExamParameterBuff":
            good_cost = spec.cost_value or 0
            if runtime.buff_value("good_condition") < good_cost:
                blockers.append(f"好調{runtime.buff_value('good_condition')}<{good_cost}")
        if runtime.usable <= 0:
            blockers.append("使用数耗尽")
        total_cost = spec.total_stamina_cost
        if runtime.energy + runtime.stamina < total_cost:
            blockers.append(f"体力+元気{runtime.energy + runtime.stamina}<{total_cost}")
        return PlayableCard(
            label=card.label,
            name=spec.name,
            tier=spec.tier,
            stamina_cost=total_cost,
            focus_cost=focus_cost,
            good_cost=good_cost,
            playable=not blockers,
            blockers=blockers,
        )

    def _view(self, round_tag: str, turn: int, flow: str, runtime: ExamRuntime, zones: DeckZones, params: dict) -> ExamView:
        return ExamView(
            round_tag=round_tag,
            turn=turn,
            total_turns=len(self.popular),
            flow=flow,
            params=params,
            stamina=runtime.stamina,
            max_stamina=runtime.max_stamina,
            energy=runtime.energy,
            focus=runtime.focus,
            good_condition_turns=runtime.buff_value("good_condition"),
            excellent_condition_turns=runtime.buff_value("excellent_condition"),
            usable_left=runtime.usable,
            cards_played=runtime.cards_played,
            hand=[self._playable(card, runtime) for card in zones.hand],
            deck_size=len(zones.deck),
            p_drinks=dict(runtime.p_drinks),
            reprise_remaining=runtime.encore.remaining if runtime.encore else 0,
            repeat_next=runtime.repeat_next,
        )

    # -- 出牌执行 ------------------------------------------------------------

    def _execute_play(self, card: CardInstance, runtime: ExamRuntime, zones: DeckZones, turn: int, flow: str, params: dict) -> tuple[list[ScoreDetail], list[EffectTrace], list[TriggerTrace]]:
        """执行一次出牌(成本 → 效果 → 移动 → 再演/もう1回),返回 (得分条目, 效果事件, 触发事件)。"""
        spec = card.spec
        # 1. 成本
        if runtime.usable <= 0:
            raise IllegalActionError(f"T{turn} 使用数耗尽,不能出 {card.label}")
        cost = spec.total_stamina_cost
        energy_pay = min(runtime.energy, cost)
        runtime.energy -= energy_pay
        runtime.stamina -= cost - energy_pay
        if spec.cost_type == "ExamCostType_ExamLessonBuff":
            runtime.focus -= spec.cost_value or 0
        elif spec.cost_type == "ExamCostType_ExamParameterBuff":
            runtime.consume_good_layers(spec.cost_value or 0)
        runtime.usable -= 1
        runtime.card_adds_pending = 0  # 一旦出卡,残余追加解除(消费的那次含在内)
        runtime.cards_played += 1

        # 2. 效果(可能 もう1回発動 重复执行)
        executions = 1 + (1 if runtime.repeat_next > 0 else 0)
        runtime.repeat_next = 0
        score_entries: list[ScoreDetail] = []
        effect_events: list[EffectTrace] = []
        trigger_events: list[TriggerTrace] = []
        param = params[flow]
        for i in range(executions):
            ctx = engine.EngineContext(
                turn=turn,
                stamina=runtime.stamina,
                max_stamina=runtime.max_stamina,
                cards_played=runtime.cards_played,
                focus=runtime.focus,
                good_turns=runtime.buff_value("good_condition"),
                trouble_not_lost=sum(
                    1 for z in (zones.deck, zones.hand, zones.grave, zones.hold) for c in z if "Trouble" in c.spec.category
                ),
                scheduled_draws=runtime.scheduled_draws,
            )
            outcome = engine.execute_effects(spec, ctx)
            self._apply_outcome(runtime, outcome, turn)
            effect_events.extend(outcome.events if i == 0 else [EffectTrace(tag=e.tag, note=e.note, detail=f"再発動:{e.detail}") for e in outcome.events])
            if outcome.lesson_value:
                detail = engine.s1_lesson_score(
                    base_value=outcome.lesson_value,
                    good_turns=runtime.buff_value("good_condition"),
                    excellent_active=runtime.buff_value("excellent_condition") > 0,
                    good_layers=runtime.buff_value("good_condition"),
                    param=param,
                )
                score_entries.append(detail)
            if i == 1:
                trigger_events.append(TriggerTrace(source="国民的アイドル", note="もう1回発動:効果再実行"))

        # 3. 移动(D1 分流)
        zones.move_played(card, self.rng)

        # 4. P item trigger(M3:憧れ続けた輝き 计数间隔+状态门槛)
        if self.trigger is not None:
            trigger_events.extend(
                self.trigger.on_card_played(
                    spec, runtime, zones, self.rng, turn, self.spec.exam_settings.hand_limit
                )
            )

        # 5. 再演判定(R4:任意卡使用後、条件卡在手、本ターン未発動、回数未满)
        self._check_encore(runtime, zones, turn, trigger_events, params, flow)
        return score_entries, effect_events, trigger_events

    def _apply_outcome(self, runtime: ExamRuntime, outcome: engine.EffectOutcome, turn: int) -> None:
        runtime.stamina = min(runtime.max_stamina, runtime.stamina + outcome.stamina_heal)
        runtime.energy += outcome.energy_add
        runtime.focus += outcome.focus_add
        runtime.add_buff("good_condition", outcome.good_add, granted_turn=turn)
        runtime.add_buff("excellent_condition", outcome.excellent_add, granted_turn=turn)
        if outcome.play_add:
            runtime.usable += outcome.play_add
            runtime.card_adds_pending += outcome.play_add
        if outcome.encore and runtime.encore is None:
            # R4:enchant 常驻(count=回数上限);源卡实例留在 Lost/Grave 由再演处理
            runtime.encore = EncoreState(source_name="お姉さんの感覚", condition_name="自然体の魅力", remaining=4)
        if outcome.repeat_next:
            runtime.repeat_next += 1
        if outcome.immediate_draw:
            zones_draw = getattr(self, "_zones", None)
            if zones_draw is not None:
                zones_draw.draw(outcome.immediate_draw, self.spec.exam_settings.hand_limit, self.rng)

    def _execute_drink(self, drink: str, runtime: ExamRuntime, turn: int, flow: str, params: dict) -> tuple[list[ScoreDetail], list[EffectTrace]]:
        """P 饮料执行:效果与卡同构走同一引擎;无成本/不占使用数(A3:produce 级资源)。"""
        from agent.hif.roundsim.drink import resolve_drink

        dspec = resolve_drink(drink)
        ctx = engine.EngineContext(
            turn=turn,
            stamina=runtime.stamina,
            max_stamina=runtime.max_stamina,
            cards_played=runtime.cards_played,
            focus=runtime.focus,
            good_turns=runtime.buff_value("good_condition"),
            trouble_not_lost=0,
            scheduled_draws=runtime.scheduled_draws,
        )
        outcome = engine.execute_effects(dspec, ctx)
        self._apply_outcome(runtime, outcome, turn)
        scores: list[ScoreDetail] = []
        if outcome.lesson_value:
            scores.append(
                engine.s1_lesson_score(
                    base_value=outcome.lesson_value,
                    good_turns=runtime.buff_value("good_condition"),
                    excellent_active=runtime.buff_value("excellent_condition") > 0,
                    good_layers=runtime.buff_value("good_condition"),
                    param=params[flow],
                )
            )
        return scores, list(outcome.events)

    def _check_encore(self, runtime: ExamRuntime, zones: DeckZones, turn: int, trigger_events: list, params: dict, flow: str) -> None:
        """再演:源卡效果再执行(免费),回数-1;源卡从 Lost 归 Grave(可回流,R4)。"""
        enc = runtime.encore
        if enc is None or enc.remaining <= 0 or enc.used_this_turn:
            return
        if not any(c.spec.name == enc.condition_name for c in zones.hand):
            return
        # 源卡实例:Lost 中找回(再演后进捨て札)
        source_instance = next((c for c in zones.lost if c.spec.name == enc.source_name), None)
        if source_instance is not None:
            zones.lost.remove(source_instance)
            zones.grave.append(source_instance)
        ctx = engine.EngineContext(
            turn=turn,
            stamina=runtime.stamina,
            max_stamina=runtime.max_stamina,
            cards_played=runtime.cards_played,
            focus=runtime.focus,
            good_turns=runtime.buff_value("good_condition"),
            trouble_not_lost=0,
            scheduled_draws=runtime.scheduled_draws,
        )
        if source_instance is not None:
            outcome = engine.execute_effects(source_instance.spec, ctx)
        else:  # 防御:源卡不在 Lost(理论上不发生)时按名字解析
            from agent.hif.roundsim.deck import resolve_card
            from agent.hif.roundsim.spec import CardInDeck

            outcome = engine.execute_effects(resolve_card(CardInDeck(name=enc.source_name)), ctx)
        self._apply_outcome(runtime, outcome, turn)
        enc.remaining -= 1
        enc.used_this_turn = True
        trigger_events.append(
            TriggerTrace(source="お姉さんの感覚(再演)", note=f"自然体の魅力在手→自身再使用,残り{enc.remaining}回")
        )

    # -- 主循环 ----------------------------------------------------------

    def run(self, strategy: Strategy | None = None) -> TraceDocument:
        """跑完整场考试。strategy=None → 全 SKIP(M1 兼容);策略经 Strategy 协议接入。"""
        scenario = self.spec.scenario
        settings = self.spec.exam_settings
        zones = DeckZones.build(scenario.deck, self.rng)
        self._zones = zones  # immediate_draw 用
        padded = zones.pad_ouenbou(self.rng) if scenario.p_items.ouenbou else 0
        initial = scenario.initial
        round_tag = "honsen_r2" if settings.turns == 12 else "honsen_r1"
        params = {"Vo": initial.params.vocal, "Da": initial.params.dance, "Vi": initial.params.visual}
        runtime = ExamRuntime(
            stamina=initial.stamina,
            max_stamina=initial.max_stamina,
            energy=initial.energy,
            focus=initial.focus,
            p_drinks=dict(initial.p_drinks),
        )
        runtime.add_buff("good_condition", initial.good_condition_turns, granted_turn=0)
        runtime.add_buff("excellent_condition", initial.excellent_condition_turns, granted_turn=0)

        doc = TraceDocument(
            seed=self.seed,
            strategy=strategy.name if strategy else "skip-only",
            spec_digest=SpecDigest(
                preset=self.preset_name,
                turns=settings.turns,
                deck_size=len(scenario.deck) + padded,
                popular_mode=scenario.popular_mode.mode,
                ouenbou=scenario.p_items.ouenbou,
                idol_exclusive=scenario.p_items.idol_exclusive,
                note=self.spec.note,
            ),
        )

        for turn_no, flow in enumerate(self.popular, start=1):
            # 回合开始:buff 递减 → 使用数重置(基准1+延续追加)→ 发牌 → 延迟抽牌到期
            runtime.decay_buffs(turn_no)
            runtime.usable = 1 + runtime.card_adds_pending
            runtime.card_adds_pending = 0
            if runtime.encore:
                runtime.encore.used_this_turn = False
            drew = zones.draw(settings.turn_start_distribute, settings.hand_limit, self.rng)
            for due, count in [d for d in runtime.scheduled_draws if d[0] == turn_no]:
                drew += zones.draw(count, settings.hand_limit, self.rng)
                runtime.scheduled_draws.remove((due, count))
            hand_before = [card.label for card in zones.hand]

            scores: list[ScoreDetail] = []
            effect_events: list[EffectTrace] = []
            trigger_events: list[TriggerTrace] = []
            action = ActionTrace(kind="skip", reason="skip-only")
            plays: list[str] = []

            # 出牌循环:使用数允许多次出牌(基准 1 + 追加);策略逐次决策
            while True:
                if strategy is None:
                    break  # M1 兼容:skip-only
                view = self._view(round_tag, turn_no, flow, runtime, zones, params)
                decision = strategy.decide(view)
                if decision.kind is ActionKind.SKIP:
                    action = ActionTrace(kind="skip", card=None, reason=decision.reason)
                    break
                if decision.kind is ActionKind.USE_P_DRINK:
                    drink = decision.target_card or ""
                    if runtime.p_drinks.get(drink, 0) <= 0:
                        raise IllegalActionError(f"T{turn_no} 饮料 {drink} 不在持有清单")
                    runtime.p_drinks[drink] -= 1
                    action = ActionTrace(kind="use_p_drink", card=drink, reason=decision.reason)
                    effect_events.append(EffectTrace(tag="p_drink", note=drink, detail="P ドリンク使用"))
                    drink_scores, drink_events = self._execute_drink(drink, runtime, turn_no, flow, params)
                    scores.extend(drink_scores)
                    effect_events.extend(drink_events)
                    break  # 饮料不占使用数;喝完仍可出牌,但策略应分步返回——本实现每回合至多一次(近似,trace 留痕)
                if decision.kind is not ActionKind.PLAY_CARD:
                    raise IllegalActionError(f"T{turn_no} 非法动作类型 {decision.kind}(実機无此按钮,§3.3)")
                target = decision.target_card or ""
                card = next((c for c in zones.hand if c.label == target or c.spec.name == target), None)
                if card is None:
                    raise IllegalActionError(f"T{turn_no} 出牌 {target} 不在手牌: {[c.label for c in zones.hand]}")
                playable = self._playable(card, runtime)
                if not playable.playable:
                    raise IllegalActionError(f"T{turn_no} 出牌 {card.label} 不合法: {playable.blockers}")
                if action.kind == "skip":
                    action = ActionTrace(kind="play_card", card=card.label, reason=decision.reason)
                plays.append(card.label)
                play_scores, play_events, play_triggers = self._execute_play(card, runtime, zones, turn_no, flow, params)
                scores.extend(play_scores)
                effect_events.extend(play_events)
                trigger_events.extend(play_triggers)
                if runtime.usable <= 0:
                    break

            action.plays = plays

            # 回合结束:手牌全弃进捨て札 → 回体力(S8)
            turn_score = sum(s.points for s in scores)
            zones.discard_hand()
            runtime.stamina = min(runtime.max_stamina, runtime.stamina + settings.stamina_recover_per_turn_end)
            doc.turns.append(
                TurnTrace(
                    turn=turn_no,
                    flow=flow,
                    hand_before=hand_before,
                    drew=list(drew),
                    action=action,
                    effects=effect_events,
                    triggers=trigger_events,
                    score=scores[0] if scores else ScoreDetail(),
                    extra_scores=scores[1:],
                    turn_score=turn_score,
                    state_after=runtime.snapshot(usable_left=runtime.usable),
                    zones=zones.counts(),
                    reshuffled=zones.reshuffle_count > 0,
                )
            )

        total_score = sum(t.turn_score for t in doc.turns)
        opponents = [
            OpponentRoll(name=o.name, score=self.rng.randint(o.score_min, o.score_max))
            for o in self.spec.opponent
        ]
        rank = 1 + sum(1 for o in opponents if o.score > total_score)
        doc.final = FinalTrace(
            total_score=total_score,
            final_state=runtime.snapshot(),
            zones=zones.counts(),
            reshuffle_count=zones.reshuffle_count,
            opponents=opponents,
            rank=rank,
            won=rank == 1,
        )
        return doc


def run_exam(
    spec: ScenarioSpec,
    seed: int,
    strategy: Strategy | None = None,
    preset_name: str = "",
) -> TraceDocument:
    """便捷入口:单局模拟。strategy=None → skip-only(M1 兼容)。"""
    name = strategy.name if strategy else "skip-only"
    return RoundSimRunner(spec, seed, strategy_name=name, preset_name=preset_name).run(strategy)
