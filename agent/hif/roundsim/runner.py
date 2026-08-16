"""回合循环与考试状态推进(roundsim-design.md §3.1 #5/#7)。

裁判(本模块)只执行规则与计分:
- 流行序列双模式:fixed(显式注入)/ j3_random(J3:末 3 回合固定 3→2→1 位、末回合必 1 位、
  首回合自定权重(A4)、中段按審査基準比率随机)。
- buff 递减(R1/kjirou 快照模型):次回合开始 -1、付与回合保护——回合 t 开始时,
  granted_turn ≤ t-2 的 buff 各 -1(付与当回合与下一回合不减);归零移除。
  考试初始 buff granted_turn=0(第 1 回合即生效,N ターン恰好覆盖 N 个回合)。
- 使用数:基准每回合 1 张(M4:play_add 追加/SKIP 不消耗);M1 skip-only 不消耗。
- RNG 全注入式:洗牌/流行/対手分共用同一个 random.Random(seed)(A/B 用 CRN 同批种子)。

M1 范围:skip-only 跑完(skip 回合得分 0,A5 假设);出牌执行/效果引擎在 M2 接线。
"""

from __future__ import annotations

import random
from dataclasses import field, dataclass

from agent.hif.roundsim.deck import DeckZones
from agent.hif.roundsim.spec import PopularMode, FixedPopular, ScenarioSpec, J3RandomPopular
from agent.hif.roundsim.trace import (
    TurnTrace,
    FinalTrace,
    SpecDigest,
    ActionTrace,
    OpponentRoll,
    StateSnapshot,
    TraceDocument,
)

_DECAY_KINDS = {"good_condition", "excellent_condition"}  # R1 衰减名单(好印象/消費増減 M2 扩)


@dataclass(slots=True)
class BuffState:
    """带付与回合标记的状态 buff(R1 递减时机建模)。"""

    kind: str  # good_condition / excellent_condition / ...
    remaining: int  # 剩余ターン
    granted_turn: int  # 付与回合(0 = 考试初始)


@dataclass(slots=True)
class ExamRuntime:
    """考试局内状态(裁判持有,策略只能看投影)。"""

    stamina: int
    max_stamina: int
    energy: int = 0
    focus: int = 0
    cards_played: int = 0  # 累计出牌数(自然体の魅力 加成基数)
    buffs: list[BuffState] = field(default_factory=list)
    p_drinks: dict[str, int] = field(default_factory=dict)

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


def generate_popular_sequence(mode: PopularMode, turns: int, rng: random.Random) -> list[str]:
    """流行属性序列(§3.1 #5)。

    fixed:显式注入(A/B 控制变量),长度须等于 turns;
    j3_random:末 3 回合固定按基準从低到高(3→2→1 位,末回合必 1 位)、
    首回合按 first_weights(缺省 = 基準比率,A4 假设)、中段按基準比率随机。
    """
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

    def run(self, strategy=None) -> TraceDocument:
        """跑完整场考试。M1:仅支持 strategy=None(全 SKIP);M2 接出牌执行。"""
        if strategy is not None:
            raise NotImplementedError("策略接入在 M2 效果引擎后接线;M1 为 skip-only 骨架")
        scenario = self.spec.scenario
        settings = self.spec.exam_settings
        zones = DeckZones.build(scenario.deck, self.rng)
        padded = zones.pad_ouenbou(self.rng) if scenario.p_items.ouenbou else 0
        initial = scenario.initial
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
            strategy=self.strategy_name,
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
            runtime.decay_buffs(turn_no)
            drew = zones.draw(settings.turn_start_distribute, settings.hand_limit, self.rng)
            hand_before = [card.label for card in zones.hand]
            # M1 skip-only:A5 假设 skip 回合得分 0、不消耗使用数
            action = ActionTrace(kind="skip", reason="M1 skip-only 骨架")
            # 回合结束:手牌全弃进捨て札 → 回体力(S8)→ 使用数重置(基准 1)
            zones.discard_hand()
            runtime.stamina = min(runtime.max_stamina, runtime.stamina + settings.stamina_recover_per_turn_end)
            doc.turns.append(
                TurnTrace(
                    turn=turn_no,
                    flow=flow,
                    hand_before=hand_before,
                    drew=list(drew),
                    action=action,
                    state_after=runtime.snapshot(usable_left=1),
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
    strategy=None,
    strategy_name: str = "skip-only",
    preset_name: str = "",
) -> TraceDocument:
    """便捷入口:单局模拟。"""
    return RoundSimRunner(spec, seed, strategy_name=strategy_name, preset_name=preset_name).run(strategy)
