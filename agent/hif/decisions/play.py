"""ガラクタロード姫崎莉波 の再演压缩流启发式策略（出牌大脑）。

从原 Maa-gakumas-bot 仓库 app/strategy/garakuta_rinami.py 移植：
- 决策逻辑原样保留（7 条启发式分支 + 参数感知告警）
- 仅改 import 路径，适配本仓库 agent/hif/decisions/ 包结构
- 去除对老仓库 StrategyPayload 的依赖，改用本仓库 ProfilePayload

核心循环：序盤尽早发动「お姉さんの感覚」→ 压缩山札凑齐「自然体の魅力」触发再演×4
→ 尽量多打好调卡（凑 P アイテム「憧れ続けた輝き」再抽牌，同时抬高自然体の魅力按
出牌数 +14/张加成）→ 好调接近收尾线时先打「国民的アイドル」叠好调铺垫
→ 最终ターン「自然体の魅力」1000% 倍率收尾。

所有阈值参数从 ProfilePayload 读取，不硬编码，便于配置热更新或为新角色复用骨架。
本模块零 maafw 依赖，纯逻辑可单测（17 个测试覆盖 7 条分支 + 边界）。
"""

from __future__ import annotations

from agent.hif.decisions.state import (
    ParamSet,
    ExamRound,
    ExamState,
    ActionKind,
    CardAction,
)
from agent.hif.decisions.config import ProfilePayload
from agent.hif.decisions.hand_meta import get_focus_cost as _get_focus
from agent.hif.decisions.hand_meta import get_effect_facts as _get_effect_facts
from agent.hif.decisions.hand_meta import get_stamina_cost as _get_stamina

# 固有卡名常量，避免散落字符串导致拼写偏差。
CARD_ONEESAN_NO_KANKAKU = "お姉さんの感覚"
CARD_SHIZEN_NO_MIRYOKU = "自然体の魅力"
CARD_KOKUMINTEKI_IDOL = "国民的アイドル"

# 固有卡消耗：从 assets/data/hif/skill_cards.json 查表（取代硬编码），保证与 wiki 数据一致。
# 查表未命中时回退经验默认值，保证策略在数据缺失时仍可降级运行。
CARD_ONEESAN_STAMINA_COST = _get_stamina(CARD_ONEESAN_NO_KANKAKU) or 6  # お姉さんの感覚 消耗体力
CARD_SHIZEN_FOCUS_COST = _get_focus(CARD_SHIZEN_NO_MIRYOKU) or 5  # 自然体の魅力 消耗集中

# 当前流 → ParamSet 属性名映射（姫崎莉波 バランス：流1/2/3 = Vi/Da/Vo）。
_FLOW_PARAM_ATTR: dict[str, str] = {"Vo": "vocal", "Da": "dance", "Vi": "visual"}


class GarakutaRinamiStrategy:
    """ガラクタロード姫崎莉波（センス/集中型）の启发式出牌策略。"""

    plan = "sense"
    recommend_effect = "集中"

    def __init__(self, payload: ProfilePayload) -> None:
        """绑定角色配置档，后续决策参数全部来自 payload。"""
        self.payload = payload

    def decide(self, state: ExamState) -> CardAction:
        """按优先级判定本ターン动作，并在山札低于目标时附加风险提示。"""
        action = self._decide_core(state)
        # 山札低于目标张数会触发 HIF 応援棒混入基本卡，统一在理由前加提示。
        if state.deck_size < self.payload.honisen.deck_target:
            action.reason = (
                f"[山札{state.deck_size}枚<目标{self.payload.honisen.deck_target}枚，"
                "警惕HIF応援棒混入基本卡] " + action.reason
            )
        return action

    def _decide_core(self, state: ExamState) -> CardAction:
        """七条启发式分支，按优先级从高到低返回首个命中的动作。"""
        cfg = self.payload
        reprise_max = cfg.reprise.max
        gate_start = cfg.reprise.good_cond_gate
        gate_finish = cfg.reprise.finisher_gate
        hand = state.hand

        # 收尾窗口：finisher_window=0 表示好调够即收尾（不限制，安全优先）；
        # 否则仅在 turn >= total_turns - window 内收尾，以最大化出牌加成。
        in_finisher_window = (
            cfg.reprise.finisher_window == 0
            or state.turn >= state.total_turns - cfg.reprise.finisher_window
        )

        # 1. 终结技：好调达标 + 手牌有自然体 + 未用 + 集中够付消耗 + 收尾窗口内。
        if (
            state.good_condition_turns >= gate_finish
            and hand.has_shizen_no_miryoku
            and not state.natural_finisher_used
            and state.focus >= CARD_SHIZEN_FOCUS_COST
            and in_finisher_window
        ):
            return CardAction(
                ActionKind.PLAY_CARD,
                CARD_SHIZEN_NO_MIRYOKU,
                "好调达标且集中足够，发动自然体の魅力 1000% 倍率终结技收尾",
            )

        # 2. 国民的铺垫：好调未到收尾线 + 手牌有国民的アイドル + 已达基础好调门槛
        #    → 先打国民的アイドル 叠好调，为终结技凑门槛。
        if (
            state.good_condition_turns < gate_finish
            and hand.has_kokuminteki_idol
            and state.good_condition_turns >= gate_start
        ):
            return CardAction(
                ActionKind.PLAY_CARD,
                CARD_KOKUMINTEKI_IDOL,
                f"好调{state.good_condition_turns}未达收尾线{gate_finish}，"
                "先发动国民的アイドル 叠好调铺垫终结技",
            )

        # 3. 序盤尽早打お姉さんの感覚以驱动再演（需体力付得起消耗）。
        if (
            state.reprise_count < reprise_max
            and state.good_condition_turns >= gate_start
            and hand.has_oneesan_no_kankaku
            and not state.oneesan_used
            and state.stamina >= CARD_ONEESAN_STAMINA_COST
        ):
            return CardAction(
                ActionKind.PLAY_CARD,
                CARD_ONEESAN_NO_KANKAKU,
                "序盤尽早发动お姉さんの感覚，驱动再演循环（可发动次数越多越有利）",
            )

        # 4. 再演未满但手牌无自然体 → 打出抽卡系/换牌系效果的卡压缩山札把它抽上来
        #    (M4 修复 3:実機无「ドロー/手札交換」独立按钮——它们是卡效果 tag,
        #     压缩手段 = 出手牌中带 action:draw / action:draw_replace 效果的卡,§3.3)。
        if state.reprise_count < reprise_max and not hand.has_shizen_no_miryoku:
            compression = _pick_compression_card(hand.card_names)
            if compression is not None:
                return CardAction(
                    ActionKind.PLAY_CARD,
                    compression,
                    f"打出抽卡系卡 {compression} 压缩山札，尽快把自然体の魅力抽到手牌以触发再演",
                )

        # 5. 低体力分支二选一（M4 修复 2）：喝优先 P ドリンク or Skip 回体 2。
        #    ラウンド1 注力（focus_r1）：失败率更高，体力告急时不惜药；无药可喝则 Skip 回体。
        if (
            cfg.focus_r1
            and state.round is ExamRound.HONSEN_R1
            and state.stamina <= cfg.honisen.stamina_critical
        ):
            drink = _pick_drink(state.available_p_drinks, cfg.p_drink_priority)
            if drink is not None:
                return CardAction(
                    ActionKind.USE_P_DRINK,
                    drink,
                    f"ラウンド1 注力策略，体力告急（{state.stamina}），不惜使用 {drink}",
                )
            return CardAction(
                ActionKind.SKIP,
                None,
                f"体力告急（{state.stamina}）且无 P ドリンク，Skip 回体 2 再战",
            )

        # 6. 默认：出好调卡（凑 P アイテム「憧れ続けた輝き」每4张再抽牌，抬高自然体の魅力
        #    +14/张加成；出牌亦可在手牌含自然体时触发再演），并按当前流参数与审查基准告警。
        #    M4 修复 1:target_card 从 None 具体化为 pick_playable_card() 选出的卡
        #    (好調付与值高 > 体力消耗低 > 不卡手);OCR 未读到卡名时退 None 留执行层。
        if hand.good_condition_card_count > 0 or hand.card_names:
            return CardAction(
                ActionKind.PLAY_CARD,
                pick_playable_card(state),
                self._default_play_reason(state),
            )

        # 7. 兜底（M4 修复 3）：无好调卡可出 → Skip 回体 2（実機无独立抽牌按钮，
        #    空转回合的最优真实动作就是 Skip）。
        return CardAction(ActionKind.SKIP, None, "无好调卡可用，Skip 回体 2 等下回合资源")

    def _default_play_reason(self, state: ExamState) -> str:
        """默认好调卡出牌理由，附当前流参数感知告警。

        HandSummary 只有好调卡计数而无具体卡，精确选卡（匹配流的卡）留执行层；
        此处做"告警 + 倾向"提示，逻辑可单测，待识别层提供更细手牌后升级。
        """
        parts = [
            "出好调卡：凑憧れ続けた輝き再抽牌并抬高自然体の魅力加成，"
            "手牌含自然体时出牌可触发再演"
        ]
        flow = state.current_flow
        param_value = _flow_param(state.params, flow)
        threshold = _flow_threshold(state.judge_thresholds, self.payload.flows, flow)
        if threshold is not None and param_value < threshold:
            parts.append(
                f"⚠ 当前流 {flow} 参数 {param_value} 低于△阈值 {threshold}，"
                "△✕ 会拖累他参得分，应优先匹配该流的好调卡"
            )
        else:
            parts.append(f"优先匹配当前流 {flow} 的好调卡")
        return "；".join(parts)


def _flow_param(params: ParamSet, flow: str) -> int:
    """取当前流对应的参数值，未知流返回 0。"""
    return getattr(params, _FLOW_PARAM_ATTR.get(flow, ""), 0)


# 关键卡(由分支 1-3 专门处理,默认选卡与压缩选卡均排除,避免推荐非法/浪费动作)。
_KEY_CARDS = {CARD_ONEESAN_NO_KANKAKU, CARD_SHIZEN_NO_MIRYOKU, CARD_KOKUMINTEKI_IDOL}


def pick_playable_card(state: ExamState) -> str | None:
    """M4 修复 1:默认「出好调卡」分支的具体选卡。

    从手牌卡名(OCR 读到的 hand.card_names)中按 好調付与值高 > 体力消耗低 >
    不卡手(即得分值高,lesson_value 为 0 的纯资源卡靠后)排序;排除关键三卡
    (分支 1-3 专管)、带使用可门槛的卡、以及当前资源付不起成本的卡
    (体力/集中/好調層)。未读到卡名或无可选卡返回 None,由执行层兜底选牌。
    """
    candidates: list[tuple[int, int, float, str]] = []
    for name in state.hand.card_names:
        if not name or name in _KEY_CARDS:
            continue
        facts = _effect_facts(name)
        if facts is None or facts["has_gate"]:
            continue
        if facts["stamina_cost"] > state.stamina or facts["focus_cost"] > state.focus:
            continue
        if facts["good_cost"] > state.good_condition_turns:
            continue
        candidates.append((-facts["good_turns"], facts["stamina_cost"], -facts["lesson_value"], name))
    if not candidates:
        return None
    return min(candidates)[3]


def _pick_compression_card(card_names: tuple[str, ...]) -> str | None:
    """M4 修复 3:压缩山札 = 出手牌中带抽卡/换牌效果(action:draw / draw_replace)的卡。

    选抽牌数多 > 体力消耗低;关键三卡与门槛卡排除(同 pick_playable_card)。
    """
    candidates: list[tuple[int, int, str]] = []
    for name in card_names:
        if not name or name in _KEY_CARDS:
            continue
        facts = _effect_facts(name)
        if facts is None or facts["has_gate"] or facts["draw_count"] <= 0:
            continue
        candidates.append((-facts["draw_count"], facts["stamina_cost"], name))
    if not candidates:
        return None
    return min(candidates)[2]


def _effect_facts(card_name: str) -> dict | None:
    """卡名 → 效果摘要(hand_meta.get_effect_facts,效果池未命中返回 None)。"""
    return _get_effect_facts(card_name)


def _flow_threshold(thresholds, flows: list[str], flow: str) -> int | None:
    """取当前流在 judge_thresholds 中的 △ 阈值；delta=0 视为未配置返回 None。"""
    try:
        idx = flows.index(flow)
    except ValueError:
        return None
    threshold = (thresholds.flow1, thresholds.flow2, thresholds.flow3)[idx]
    return threshold.delta if threshold.delta > 0 else None


def _pick_drink(available: list[str], priority: list[str]) -> str | None:
    """按优先级顺序返回持有的首个 P ドリンク，无则返回 None。"""
    for drink in priority:
        if drink in available:
            return drink
    return None
