"""泛化 trigger 引擎(roundsim-design.md §5:「计数间隔 + 状态门槛」类,メモリー将来同接口)。

第一例 = 莉波专属 P item「憧れ続けた輝き」(mechanics H13【A】):
    好調 ≥8 ターン時、好調系カード(効果グループ exam_parameter_buff)を 4 枚使用するごとに
    (最多 5 回):絶好調 1 ターン + スキルカード使用数追加 +1 + スキルカードを 1 枚引く + 体力 1 消費。
数据链(本地 dump 実証,ProduceItemEffect → ProduceExamStatusEnchant → ProduceExamTrigger):
    enchant-p_item_effect_01-3-312-0-enc01(effectCount=5, effectTurn=-1 常驻)
    trigger = ExamPlayCountInterval(4) + fieldStatus ParameterBuffUp ≥8 + p_card_search(effect_group)
    effects = 絶好調1T(ExamParameterBuffMultiplePerTurn) + 使用数+1(ExamPlayableValueAdd)
              + 抽1(ExamCardDraw) + 体力消費1(ExamStaminaReduceFix)

触发时机语义(实现声明):每使用第 4 张好調系卡時計数到点;到点時检好調门槛,满足且
次数未满 → 発動并重新计 4 张;门槛不满足 → 本次到点作废(下一次次 4 张再检)。
好調系卡判定 = 卡效果列表含 ExamParameterBuff(好調付与)效果行。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from agent.hif.roundsim.deck import CardSpec, DeckZones
from agent.hif.roundsim.trace import TriggerTrace
from agent.hif.roundsim.runner import ExamRuntime


@dataclass(slots=True)
class PlayCountIntervalTrigger:
    """「计数间隔 + 状态门槛」trigger 実例(裁判持有)。"""

    source: str  # 触发源名(P item 名)
    interval: int  # 计数间隔(4 张)
    status_key: str  # 门槛状态键(good_condition)
    status_threshold: int  # 门槛阈值(8)
    max_fires: int  # 発動上限(5)
    match_count: int = 0  # 已使用的対象卡计数
    fired: int = 0  # 已発動次数

    def is_target(self, spec: CardSpec) -> bool:
        """対象卡 = 效果列表含好調付与(ExamParameterBuff)的卡(効果グループ exam_parameter_buff)。"""
        return any(
            (e.get("effect_type") or "").replace("ProduceExamEffectType_", "") == "ExamParameterBuff"
            for e in spec.effects
        )

    def on_card_played(
        self,
        spec: CardSpec,
        runtime: ExamRuntime,
        zones: DeckZones,
        rng: random.Random,
        turn: int,
        hand_limit: int,
    ) -> list[TriggerTrace]:
        """每张卡打出后调用;返回本次触发的 trace(通常 0 或 1 条)。"""
        if self.fired >= self.max_fires or not self.is_target(spec):
            return []
        self.match_count += 1
        if self.match_count % self.interval != 0:
            return []
        if runtime.buff_value(self.status_key) < self.status_threshold:
            return [TriggerTrace(source=self.source, note=f"第{self.match_count}张好調系卡到点,好調{runtime.buff_value(self.status_key)}<{self.status_threshold} 门槛未満,不発動")]
        # 発動:絶好調1T + 使用数+1 + 抽1 + 体力1消費(効果鏈 312-0-enc01)
        runtime.add_buff("excellent_condition", 1, granted_turn=turn)
        runtime.usable += 1  # P item 付与の追加(R3:skip 会消失 → 不入 card_adds_pending)
        zones.draw(1, hand_limit, rng)
        runtime.stamina -= 1
        self.fired += 1
        return [
            TriggerTrace(
                source=self.source,
                note=f"好調{runtime.buff_value(self.status_key)}T≥{self.status_threshold}:絶好調1T+使用数+1+抽1+体力-1(第{self.fired}/{self.max_fires}回)",
            )
        ]


# 内置 trigger 注册表:P item 名 → trigger 定义(新道具 = 加一行,不改引擎)。
TRIGGER_REGISTRY: dict[str, dict] = {
    "憧れ続けた輝き": dict(interval=4, status_key="good_condition", status_threshold=8, max_fires=5),
    "憧れ続けた輝き+": dict(interval=4, status_key="good_condition", status_threshold=6, max_fires=5),  # +版:好調≥6(312-1-enc01)
}


def build_trigger(item_name: str | None) -> PlayCountIntervalTrigger | None:
    """按 P item 名建 trigger 実例;未注册的道具名返回 None(无 trigger,不报错——流程钥匙类道具)。"""
    if not item_name or item_name not in TRIGGER_REGISTRY:
        return None
    cfg = TRIGGER_REGISTRY[item_name]
    return PlayCountIntervalTrigger(source=item_name, **cfg)
