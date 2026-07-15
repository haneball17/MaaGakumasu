"""当前路线已实证卡牌的动作后领域语义断言。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.hif.route_scoring.models import UpgradeLevel, RouteBattleState


@dataclass(frozen=True, slots=True)
class RoutePostconditionResult:
    verified: bool
    assertions: dict[str, bool]

    @property
    def failed_assertions(self) -> tuple[str, ...]:
        return tuple(name for name, passed in self.assertions.items() if not passed)


def verify_blessing_plus(
    before: RouteBattleState,
    after: RouteBattleState,
    *,
    displayed_score: int,
) -> RoutePostconditionResult:
    """验证 ``祝福+``：显示分数、体力4、好调1及同回合不变量。"""

    blessing_plus_remains = any(
        card.card_id == "祝福" and card.upgrade is UpgradeLevel.PLUS for card in after.hand
    )
    assertions = {
        "same_round": after.battle_round is before.battle_round,
        "same_turn": after.turn == before.turn,
        "score_delta_matches_card": after.current_score - before.current_score == displayed_score,
        "stamina_cost_four": after.stamina == before.stamina - 4,
        "good_condition_plus_one": after.good_condition_turns == before.good_condition_turns + 1,
        "focus_unchanged": after.focus == before.focus,
        "stage_multiplier_unchanged": after.stage_multiplier_percent == before.stage_multiplier_percent,
        "deck_size_unchanged": after.deck_size == before.deck_size,
        "blessing_plus_left_hand": not blessing_plus_remains,
    }
    return RoutePostconditionResult(all(assertions.values()), assertions)
