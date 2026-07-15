"""当前 HIF 路线的确定性、可解释单步评分器。"""

from __future__ import annotations

from collections.abc import Mapping

from agent.hif.route_scoring.models import (
    CardSpec,
    HandCard,
    BattleRound,
    UpgradeLevel,
    RejectionCode,
    RouteDecision,
    ScoreComponent,
    RouteBattleState,
    CandidateEvaluation,
    RouteDecisionStatus,
)
from agent.hif.route_scoring.catalog import RINAMI_GARAKUTA_CARD_SPECS

_ROUTE_ID = "rinami_garakuta_road"
_REQUIRED_FIELDS = (
    "battle_round",
    "turn",
    "total_turns",
    "current_score",
    "stage_multiplier_percent",
    "stamina",
    "focus",
    "good_condition_turns",
    "reprise_count",
    "deck_size",
    "trusted",
    "fresh",
)


class RinamiGarakutaRouteScorer:
    """对最新可信状态中的全部手牌做 Hard Gate 后选择唯一最高分。"""

    def __init__(self, card_specs: Mapping[tuple[str, UpgradeLevel], CardSpec] | None = None) -> None:
        self._card_specs = RINAMI_GARAKUTA_CARD_SPECS if card_specs is None else card_specs

    def decide(self, state: RouteBattleState) -> RouteDecision:
        rejection = self._validate_state(state)
        if rejection is not None:
            code, detail = rejection
            return self._reject(code, detail)

        duplicate = self._find_duplicate_identity(state.hand)
        if duplicate is not None:
            code, detail = duplicate
            return self._reject(code, detail)

        candidates = tuple(self._evaluate_candidate(state, card) for card in state.hand)
        unknown = next(
            (candidate for candidate in candidates if candidate.rejection_code is RejectionCode.UNKNOWN_CARD),
            None,
        )
        if unknown is not None:
            # 未知的可打牌可能优于所有已建模牌；忽略它再排名会产生虚假的唯一目标。
            return self._reject(
                RejectionCode.UNKNOWN_CARD,
                f"可打手牌未建模：{unknown.title}:{unknown.upgrade.value}",
                candidates,
            )
        legal = tuple(candidate for candidate in candidates if candidate.is_legal)
        if not legal:
            return self._reject(RejectionCode.NO_LEGAL_CANDIDATE, "全部手牌均被 Hard Gate 排除", candidates)

        highest = max(candidate.total_score for candidate in legal if candidate.total_score is not None)
        winners = tuple(candidate for candidate in legal if candidate.total_score == highest)
        if len(winners) != 1:
            tied = ",".join(f"{item.title}:{item.upgrade.value}" for item in winners)
            return self._reject(RejectionCode.SCORE_TIE, f"最高分 {highest} 并列：{tied}", candidates)

        winner = winners[0]
        return RouteDecision(
            status=RouteDecisionStatus.SELECTED,
            selected_target_id=winner.target_id,
            selected_card_id=winner.card_id,
            selected_title=winner.title,
            selected_upgrade=winner.upgrade,
            candidates=candidates,
        )

    @staticmethod
    def _validate_state(state: RouteBattleState) -> tuple[RejectionCode, str] | None:
        if state.route_id != _ROUTE_ID:
            return RejectionCode.UNSUPPORTED_ROUTE, f"route_id={state.route_id}"
        missing = tuple(field for field in _REQUIRED_FIELDS if getattr(state, field) is None)
        if missing:
            return RejectionCode.MISSING_STATE_FIELD, ",".join(missing)
        if state.trusted is not True:
            return RejectionCode.UNTRUSTED_STATE, "状态未通过同帧观测与已验证账本门禁"
        if state.fresh is not True:
            return RejectionCode.STALE_STATE, "状态不是本次决策前的最新观测"
        if not state.hand:
            return RejectionCode.EMPTY_HAND, "未观察到手牌"
        if state.battle_round not in (BattleRound.ROUND1, BattleRound.ROUND2):
            return RejectionCode.INVALID_STATE, "不支持的 Battle Round"
        assert state.turn is not None
        assert state.total_turns is not None
        assert state.current_score is not None
        assert state.stage_multiplier_percent is not None
        assert state.stamina is not None
        assert state.focus is not None
        assert state.good_condition_turns is not None
        assert state.reprise_count is not None
        assert state.deck_size is not None
        if not 1 <= state.turn <= state.total_turns:
            return RejectionCode.INVALID_STATE, "turn 不在 [1,total_turns]"
        if min(
            state.current_score,
            state.stage_multiplier_percent,
            state.stamina,
            state.focus,
            state.good_condition_turns,
            state.reprise_count,
            state.deck_size,
        ) < 0:
            return RejectionCode.INVALID_STATE, "牌局数值不能为负"
        if state.stage_multiplier_percent == 0:
            return RejectionCode.INVALID_STATE, "stage_multiplier_percent 必须大于 0"
        return None

    @staticmethod
    def _find_duplicate_identity(hand: tuple[HandCard, ...]) -> tuple[RejectionCode, str] | None:
        target_ids = [card.target_id for card in hand]
        if len(target_ids) != len(set(target_ids)):
            return RejectionCode.DUPLICATE_TARGET_ID, "observation target_id 不唯一"
        titles = [(card.title, card.upgrade) for card in hand]
        if len(titles) != len(set(titles)):
            return RejectionCode.NON_UNIQUE_TITLE, "同一标题与强化等级出现多个目标"
        return None

    def _evaluate_candidate(self, state: RouteBattleState, card: HandCard) -> CandidateEvaluation:
        if not card.playable:
            return self._candidate_rejection(card, RejectionCode.GRAY_CARD, "画面判定为灰卡/不可出牌")
        spec = self._card_specs.get(card.spec_key)
        if spec is None or spec.title != card.title:
            return self._candidate_rejection(card, RejectionCode.UNKNOWN_CARD, "卡牌或强化等级未进入当前路线白名单")
        if spec.effect is None:
            return self._candidate_rejection(card, RejectionCode.UNSUPPORTED_CARD_EFFECT, "没有可执行的结构化效果")
        if spec.lesson_once and spec.key in state.used_card_specs:
            return self._candidate_rejection(card, RejectionCode.ALREADY_USED, "本局限用一次且账本已记录使用")
        assert state.stamina is not None
        assert state.focus is not None
        if state.stamina < spec.stamina_cost:
            return self._candidate_rejection(card, RejectionCode.INSUFFICIENT_STAMINA, f"需要体力 {spec.stamina_cost}")
        if state.focus < spec.focus_cost:
            return self._candidate_rejection(card, RejectionCode.INSUFFICIENT_FOCUS, f"需要集中 {spec.focus_cost}")
        components = self._score_components(state, spec)
        return CandidateEvaluation(
            target_id=card.target_id,
            card_id=card.card_id,
            title=card.title,
            upgrade=card.upgrade,
            total_score=sum(component.value for component in components),
            components=components,
        )

    @staticmethod
    def _score_components(state: RouteBattleState, spec: CardSpec) -> tuple[ScoreComponent, ...]:
        assert spec.effect is not None
        assert state.turn is not None
        assert state.total_turns is not None
        assert state.stage_multiplier_percent is not None
        horizon = min(3, state.total_turns - state.turn + 1)
        effect = spec.effect
        return (
            ScoreComponent(
                "immediate_parameter",
                effect.parameter_gain,
                state.stage_multiplier_percent,
                effect.parameter_gain * state.stage_multiplier_percent,
                "卡面参数增量 × 当前同帧审查倍率（共同整数尺度）",
            ),
            ScoreComponent(
                "good_condition_setup",
                effect.good_condition_turns,
                1_500,
                effect.good_condition_turns * 1_500,
                "好调延长的当前路线短视价值",
            ),
            ScoreComponent(
                "excellent_condition_setup",
                effect.excellent_condition_turns * horizon,
                700,
                effect.excellent_condition_turns * horizon * 700,
                f"绝好调效果在最多 {horizon} 回合短视窗口内的设置价值",
            ),
            ScoreComponent(
                "future_fixed_guard",
                effect.fixed_guard_on_future_active * horizon,
                300,
                effect.fixed_guard_on_future_active * horizon * 300,
                f"后续主动卡固定元气在最多 {horizon} 回合内的保守价值",
            ),
            ScoreComponent(
                "stamina_cost",
                spec.stamina_cost,
                -1_000,
                spec.stamina_cost * -1_000,
                "体力消耗的显式安全惩罚",
            ),
            ScoreComponent(
                "focus_cost",
                spec.focus_cost,
                -1_200,
                spec.focus_cost * -1_200,
                "集中消耗的显式路线惩罚",
            ),
        )

    @staticmethod
    def _candidate_rejection(card: HandCard, code: RejectionCode, detail: str) -> CandidateEvaluation:
        return CandidateEvaluation(card.target_id, card.card_id, card.title, card.upgrade, None, (), code, detail)

    @staticmethod
    def _reject(
        code: RejectionCode,
        detail: str,
        candidates: tuple[CandidateEvaluation, ...] = (),
    ) -> RouteDecision:
        return RouteDecision(RouteDecisionStatus.REJECTED, None, None, None, None, candidates, code, detail)
