"""roundsim 选手策略集(M4:贪心基线 + GarakutaRinami 适配器)。

裁判-选手协议(§6.1):策略收 ExamView 投影、返 decisions.CardAction;
模拟器与実機管线共用同一策略函数(策略可迁移原则 §2 #3)。

- GreedyStrategy(§6.2):即时分贪心——枚举手牌可出卡,用模拟器自己的 S1 得分函数
  算本回合即时得分,选最高(平手选体力消耗低);不看好調覆盖/压缩/再演协同。
  全部候选即时分为 0 时 Skip(省体力,平手规则精神)。
- RinamiStrategyAdapter:包装 decisions.GarakutaRinamiStrategy(启发式 7 分支),
  ExamView → decisions.ExamState 投影(与実機 OCR 适配层同构),复用决策大脑本体。
"""

from __future__ import annotations

from agent.hif.roundsim import engine
from agent.hif.decisions.play import GarakutaRinamiStrategy
from agent.hif.decisions.state import (
    ParamSet,
    ExamRound,
    ExamState,
    ActionKind,
    CardAction,
    HandSummary,
)
from agent.hif.roundsim.runner import ExamView, FirstLegalStrategy
from agent.hif.decisions.config import ProfilePayload


class GreedyStrategy:
    """即时分贪心基线(§6.2):每张可出卡的即时 S1 分 → argmax,平手选体力消耗低。"""

    name = "greedy"

    def _immediate_score(self, view: ExamView, idx: int) -> tuple[int, int, str]:
        """(即时分, 体力消耗, 卡名):用 S1 函数复算该卡本回合打出能得多少分。"""
        card = view.hand[idx]
        # 从 view 重建该卡 spec:hand 只带名字/档位,走效果池解析(裁判同源数据)
        from agent.hif.roundsim.deck import resolve_card
        from agent.hif.roundsim.spec import CardInDeck

        spec = resolve_card(CardInDeck(name=card.name, tier=card.tier))
        ctx = engine.EngineContext(
            turn=view.turn,
            stamina=view.stamina,
            max_stamina=view.max_stamina,
            cards_played=view.cards_played,
            focus=view.focus,
            good_turns=view.good_condition_turns,
            trouble_not_lost=0,
        )
        outcome = engine.execute_effects(spec, ctx)
        if outcome.lesson_value <= 0:
            return 0, card.stamina_cost, card.label
        detail = engine.s1_lesson_score(
            base_value=outcome.lesson_value,
            good_turns=view.good_condition_turns,
            excellent_active=view.excellent_condition_turns > 0,
            good_layers=view.good_condition_turns,
            param=view.params[view.flow],
        )
        return detail.points, card.stamina_cost, card.label

    def decide(self, view: ExamView) -> CardAction:
        candidates = [(self._immediate_score(view, i), i) for i in range(len(view.hand)) if view.hand[i].playable]
        if not candidates:
            return CardAction(ActionKind.SKIP, None, "greedy:无可出卡,Skip")
        best_score = max(score for (score, _cost, _label), _i in candidates)
        if best_score <= 0:
            return CardAction(ActionKind.SKIP, None, "greedy:全部候选即时分为 0,Skip 省体力")
        (score, cost, label), _ = min(candidates, key=lambda c: (-c[0][0], c[0][1]))
        return CardAction(ActionKind.PLAY_CARD, label, f"greedy:即时分最高 {label}(+{score},耗体{cost})")


class RinamiStrategyAdapter:
    """包装 GarakutaRinamiStrategy:ExamView → decisions.ExamState 投影后决策。

    与実機接线(ProduceHIFRound1Observe)共用同一个决策大脑与状态视图结构;
    oneesan/natural_finisher 的「本考试已用」由本适配器在返回出牌动作时记账
    (ExamState 无此字段的运行时来源,実機側由识别层维护)。
    """

    name = "garakuta_rinami"

    def __init__(self, payload: ProfilePayload | None = None) -> None:
        self.payload = payload or ProfilePayload.default()
        self._strategy = GarakutaRinamiStrategy(self.payload)
        self._oneesan_used = False
        self._shizen_used = False

    def project(self, view: ExamView) -> ExamState:
        names = [card.name for card in view.hand]
        hand = HandSummary(
            has_shizen_no_miryoku="自然体の魅力" in names,
            has_oneesan_no_kankaku="お姉さんの感覚" in names,
            has_kokuminteki_idol="国民的アイドル" in names,
            good_condition_card_count=sum(
                1
                for card in view.hand
                if any(
                    (e.get("effect_type") or "").endswith("ExamParameterBuff")
                    for e in _card_effects(card)
                )
            ),
            swap_hand_available=False,  # M4 修复 3 后废弃字段,恒 False
            draw_available=False,
            card_names=tuple(card.label for card in view.hand),
        )
        drinks: list[str] = []
        for name, count in view.p_drinks.items():
            drinks.extend([name] * count)
        return ExamState(
            round=ExamRound.HONSEN_R2 if view.round_tag == "honsen_r2" else ExamRound.HONSEN_R1,
            turn=view.turn,
            total_turns=view.total_turns,
            current_flow=view.flow,
            good_condition_turns=view.good_condition_turns,
            focus=view.focus,
            stamina=view.stamina,
            hand=hand,
            reprise_count=4 - view.reprise_remaining,  # 再演已用次数(上限 4)
            cards_played=view.cards_played,
            deck_size=view.deck_size,
            oneesan_used=self._oneesan_used,
            natural_finisher_used=self._shizen_used,
            available_p_drinks=drinks,
            params=ParamSet(
                vocal=view.params.get("Vo", 0),
                dance=view.params.get("Da", 0),
                visual=view.params.get("Vi", 0),
            ),
        )

    def decide(self, view: ExamView) -> CardAction:
        from agent.hif.decisions.play import pick_playable_card

        state = self.project(view)
        action = self._strategy.decide(state)
        if action.kind is ActionKind.PLAY_CARD:
            if action.target_card == "お姉さんの感覚":
                self._oneesan_used = True
            elif action.target_card == "自然体の魅力":
                self._shizen_used = True
            # 裁判-选手适配:策略的 None/资源不足选卡在交给裁判前兜底
            # (None → pick_playable_card;仍无 or 目标不可出 → Skip,不让裁判报非法)。
            if not action.target_card:
                action.target_card = pick_playable_card(state)
            if action.target_card is None:
                return CardAction(ActionKind.SKIP, None, "适配器兜底:无合法默认卡,Skip")
            target = action.target_card
            playable = next((c for c in view.hand if c.label == target or c.name == target.rstrip("+")), None)
            if playable is None or not playable.playable:
                return CardAction(ActionKind.SKIP, None, f"适配器兜底:{target} 当前不可出({playable.blockers if playable else '不在手牌'}),Skip")
        return action


def _card_effects(card) -> list[dict]:
    """PlayableCard → 效果行(效果池解析;裁判同源数据)。"""
    from agent.hif.roundsim.deck import resolve_card
    from agent.hif.roundsim.spec import CardInDeck

    return list(resolve_card(CardInDeck(name=card.name, tier=card.tier)).effects)


STRATEGIES = {
    "first_legal": FirstLegalStrategy,
    "greedy": GreedyStrategy,
    "garakuta_rinami": RinamiStrategyAdapter,
}


def make_strategy(name: str):
    """按名建策略実例(A/B runner 与 CLI 共用注册表)。"""
    if name not in STRATEGIES:
        raise KeyError(f"未注册策略 {name};可用: {sorted(STRATEGIES)}")
    return STRATEGIES[name]()
