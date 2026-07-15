"""已采证 Round1 手牌的保守精确选卡规则。"""

from __future__ import annotations

from collections.abc import Collection

from agent.hif.decisions.state import ExamRound, ExamState, ActionKind, CardAction

_OBSERVED_RECOVERY_HAND = frozenset({"天賦の才", "シュプレヒコール"})
_TENBU_NO_SAI = "天賦の才"
_WADAI_FUTTOU = "話題沸騰"
_POST_TOPIC_HAND = frozenset({"鳴り止まない拍手", "夏夜に咲く思い出", "仕切り直し", "始まりの合図"})
_SHIKIRINAOSHI = "仕切り直し"
_POST_SHIKIRINAOSHI_HAND = frozenset({"アイドル宣言", "演出計画", "存在感", "眠気", "祝福"})
_IDOL_DECLARATION = "アイドル宣言"


def choose_high_good_condition_topic_card(state: ExamState, playable_names: Collection[str]) -> CardAction | None:
    """在好调已达卡面门槛时，优先零消耗的 ``話題沸騰``。

    该卡的实机详情明确要求好调至少 8 回合；当前 Round1 状态满足时，它提供
    以好调效果双倍计算的即时参数收益，且不会消耗体力或集中。若卡不在已验证
    的可出牌集合或门槛不足，返回 ``None``，由上层继续安全停止。
    """

    names = {name.rstrip("+") for name in playable_names if name}
    if state.round is not ExamRound.HONSEN_R1 or state.good_condition_turns < 8 or _WADAI_FUTTOU not in names:
        return None
    return CardAction(
        ActionKind.PLAY_CARD,
        _WADAI_FUTTOU,
        "話題沸騰满足好调8回合门槛；零体力/集中消耗且以双倍好调效果提供即时参数收益，优先执行",
    )


def choose_observed_round1_recovery_card(state: ExamState, playable_names: Collection[str]) -> CardAction | None:
    """为当前已采证的两卡恢复现场给出唯一、可复算的保守目标。

    该规则不是通用同类卡排序器：只有 Round1、好调已越过终结门槛、集中较低
    且非灰候选恰为 ``天賦の才/シュプレヒコール`` 时才成立。天赋能补集中、将
    SSR 移至牌库顶并增加下回合使用次数；自然体不可出牌时，其长期收益优先于
    消耗集中的即时好调卡。其余候选集合均返回 ``None``。
    """

    names = frozenset(name.rstrip("+") for name in playable_names if name)
    if names != _OBSERVED_RECOVERY_HAND:
        return None
    if state.round is not ExamRound.HONSEN_R1 or state.good_condition_turns < 12:
        return None
    if state.focus > 4 or state.stamina < 5 or state.deck_size <= 0:
        return None
    return CardAction(
        ActionKind.PLAY_CARD,
        _TENBU_NO_SAI,
        "自然体当前为灰牌且好调已达终结门槛；天賦の才补集中、重排3张SSR并增加下回合使用次数，优先于消耗集中的シュプレヒコール",
    )


def choose_observed_round1_post_topic_card(state: ExamState, playable_names: Collection[str]) -> CardAction | None:
    """只为已实测的 ``話題沸騰+`` 后四卡状态选择低耗重抽卡。"""

    names = frozenset(name.rstrip("+") for name in playable_names if name)
    if names != _POST_TOPIC_HAND or state.round is not ExamRound.HONSEN_R1:
        return None
    if state.turn != 6 or state.good_condition_turns < 40 or state.focus != 5 or state.stamina < 2 or state.deck_size != 21:
        return None
    return CardAction(
        ActionKind.PLAY_CARD,
        _SHIKIRINAOSHI,
        "話題沸騰后四卡实测状态：仕切り直し仅耗体力2，重抽全手牌、减少后续体力消耗并增加使用次数，优先于耗体力5/7的候选",
    )


def choose_observed_round1_post_shikirinaoshi_card(state: ExamState, playable_names: Collection[str]) -> CardAction | None:
    """只为已实测的 ``仕切り直し+`` 重抽后五卡状态选择零耗续航卡。"""

    names = frozenset(name.rstrip("+") for name in playable_names if name)
    if names != _POST_SHIKIRINAOSHI_HAND or state.round is not ExamRound.HONSEN_R1:
        return None
    if state.turn != 6 or state.good_condition_turns < 47 or state.focus != 5 or state.stamina != 33 or state.deck_size != 21:
        return None
    return CardAction(
        ActionKind.PLAY_CARD,
        _IDOL_DECLARATION,
        "仕切り直し重抽后实测五卡状态：アイドル宣言+零消耗，增加使用次数、抽2张并减少后续体力消耗，优先于消耗体力或好调的候选",
    )
