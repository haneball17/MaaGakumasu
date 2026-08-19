"""泛化 trigger 引擎(roundsim-design.md §5:「计数间隔 + 状态门槛」类,メモリー将来同接口)。

数据驱动(Item B):参数与発動效果链从 assets/data/hif/pitem_effects.json 读取
(tools/sync_hif_pitems.py 生成;dump 链 ProduceItem → ProduceItemEffect(ExamStatusEnchant)
→ ProduceExamStatusEnchant → ProduceExamTrigger + ProduceExamEffect)。

第一例 = 莉波专属 P item「憧れ続けた輝き」(mechanics H13【A】):
    好調 ≥8 ターン時、好調系カード(効果グループ「好調」)を 4 枚使用するごとに
    (最多 5 回):絶好調 1 ターン + スキルカード使用数追加 +1 + スキルカードを 1 枚引く + 体力 1 消費。
    (+版:好調≥6,且 dump 実証無体力消費——発動效果按各自数据链派发,不共用数值。)

引擎支持面(未建模形态硬失败,ADR-0001 零拟合):
- phase = [ExamPlayCountInterval](单一计数间隔)+ fieldStatus = [ParameterBuffUp](好調门槛);
- 対象卡 = 効果組(effectGroupIds)展开的 exam_effect_types 全列表(如「好調」組 5 型;
  旧版只匹配 ExamParameterBuff 一型属窄化,已按官方効果組对齐);
- 発動效果链 ∈ SUPPORTED_FIRE_EFFECTS(絶好調/使用数/抽牌/体力消費)。

触发时机语义(实现声明):每使用第 4 张対象卡時計数到点;到点時检状态门槛,满足且
次数未满 → 発動并重新计 4 张;门槛不满足 → 本次到点作废(下一次次 4 张再检)。
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from functools import lru_cache
from dataclasses import field, dataclass

from agent.hif.roundsim.deck import CardSpec, DeckZones
from agent.hif.roundsim.trace import TriggerTrace
from agent.hif.roundsim.runner import ExamRuntime

PITEM_DATA = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "pitem_effects.json"

SUPPORTED_PHASE = ("ExamPlayCountInterval",)
SUPPORTED_FIELD_STATUS = ("ParameterBuffUp",)
# 発動效果支持面(effect_type 短名);数值字段因型而异(絶好調→turn,使用数→count,抽牌/体力→value)
SUPPORTED_FIRE_EFFECTS = frozenset(
    {"ExamParameterBuffMultiplePerTurn", "ExamPlayableValueAdd", "ExamCardDraw", "ExamStaminaReduceFix"}
)
_FIRE_VALUE_FIELD = {
    "ExamParameterBuffMultiplePerTurn": "turn",
    "ExamPlayableValueAdd": "count",
    "ExamCardDraw": "value",
    "ExamStaminaReduceFix": "value",
}

_FIELD_STATUS_KEY = {"ParameterBuffUp": "good_condition"}


def _short(enum: str) -> str:
    return enum.rsplit("_", 1)[-1] if enum else ""


@lru_cache(maxsize=1)
def _load_items() -> dict[str, dict]:
    data = json.loads(PITEM_DATA.read_text(encoding="utf-8"))
    return {i["name"]: i for i in data["items"]}


@dataclass(slots=True)
class PlayCountIntervalTrigger:
    """「计数间隔 + 状态门槛」trigger 実例(裁判持有);参数与效果链全部来自 dump 数据。"""

    source: str  # 触发源名(P item 名)
    interval: int  # 计数间隔(4 张)
    status_key: str  # 门槛状态键(good_condition)
    status_threshold: int  # 门槛阈值(8)
    max_fires: int  # 発動上限(5)
    target_effect_types: frozenset[str] = field(default_factory=frozenset)  # 対象卡效果型全集(効果組展开)
    exam_effects: tuple[dict, ...] = ()  # 発動效果链(pitem_effects.json 原样)
    match_count: int = 0  # 已使用的対象卡计数
    fired: int = 0  # 已発動次数

    def is_target(self, spec: CardSpec) -> bool:
        """対象卡 = 效果列表含効果組内任一效果型的卡(如「好調」組 5 型)。"""
        return any((e.get("effect_type") or "").rsplit("_", 1)[-1] in self.target_effect_types for e in spec.effects)

    def _fire(self, runtime: ExamRuntime, zones: DeckZones, rng: random.Random, turn: int, hand_limit: int) -> str:
        """按数据链派发発動效果;返回 trace 摘要。构造时已预检,此处类型必在支持面。"""
        parts = []
        for eff in self.exam_effects:
            t = _short(eff.get("effect_type") or "")
            v = eff.get(_FIRE_VALUE_FIELD[t]) or 0
            if t == "ExamParameterBuffMultiplePerTurn":
                runtime.add_buff("excellent_condition", v, granted_turn=turn)
                parts.append(f"絶好調{v}T")
            elif t == "ExamPlayableValueAdd":
                runtime.usable += v  # P item 付与の追加(R3:skip 会消失 → 不入 card_adds_pending)
                parts.append(f"使用数+{v}")
            elif t == "ExamCardDraw":
                zones.draw(v, hand_limit, rng)
                parts.append(f"抽{v}")
            elif t == "ExamStaminaReduceFix":
                runtime.stamina -= v
                parts.append(f"体力-{v}")
        return "+".join(parts)

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
            return [
                TriggerTrace(
                    source=self.source,
                    note=f"第{self.match_count}张対象卡到点,{self.status_key}{runtime.buff_value(self.status_key)}<{self.status_threshold} 门槛未満,不発動",
                )
            ]
        detail = self._fire(runtime, zones, rng, turn, hand_limit)
        self.fired += 1
        return [
            TriggerTrace(
                source=self.source,
                note=f"{self.status_key}{runtime.buff_value(self.status_key)}T≥{self.status_threshold}:{detail}(第{self.fired}/{self.max_fires}回)",
            )
        ]


def _pitem_trigger_config(item: dict) -> dict | None:
    """数据条目 → trigger 参数;无 enchant 效果 → None(三围/流程类,不入模拟);
    支持面外 → ValueError 列出形态(零拟合:未建模就硬失败,不静默近似)。"""
    ench = next((e for e in item["effects"] if "enchant_id" in e), None)
    if ench is None:
        return None
    trig = ench["trigger"]
    name = item["name"]
    if tuple(trig["phase_types"]) != SUPPORTED_PHASE:
        raise ValueError(f"P item「{name}」trigger 形态未建模: phase={trig['phase_types']}(支持 {list(SUPPORTED_PHASE)})")
    if tuple(trig["field_status_types"]) != SUPPORTED_FIELD_STATUS:
        raise ValueError(
            f"P item「{name}」trigger 形态未建模: fieldStatus={trig['field_status_types']}(支持 {list(SUPPORTED_FIELD_STATUS)})"
        )
    unsupported = sorted({_short(e["effect_type"] or "") for e in ench["exam_effects"]} - SUPPORTED_FIRE_EFFECTS)
    if unsupported:
        raise ValueError(f"P item「{name}」発動效果未建模: {unsupported}(支持 {sorted(SUPPORTED_FIRE_EFFECTS)})")
    target_types = frozenset(et for g in trig["card_search_effect_groups"] for et in g["exam_effect_types"])
    return dict(
        interval=trig["phase_values"][0],
        status_key=_FIELD_STATUS_KEY[trig["field_status_types"][0]],
        status_threshold=trig["field_status_values"][0],
        max_fires=ench["effect_count"],
        target_effect_types=target_types,
        exam_effects=tuple(ench["exam_effects"]),
    )


def build_triggers(item_names: list[str]) -> list[PlayCountIntervalTrigger]:
    """P item 确定列表(R2-3)→ trigger 実例列表(依列表顺序判定)。

    未收录名 → ValueError(pitem_effects.json 范围 = 莉波偶像卡 26 + 支援卡 origin 127);
    无 enchant 效果件(三围加成/流程钥匙)跳过,不建 trigger。
    """
    known = _load_items()
    triggers: list[PlayCountIntervalTrigger] = []
    for name in item_names:
        item = known.get(name)
        if item is None:
            raise ValueError(f"P item「{name}」不在 pitem_effects.json(未收录;范围 153 件,拼错或范围外)")
        cfg = _pitem_trigger_config(item)
        if cfg is not None:
            triggers.append(PlayCountIntervalTrigger(source=name, **cfg))
    return triggers


def pitem_registry() -> list[dict]:
    """UI 消费:全部收录件 + trigger 支持标记(unsupported 带原因,前端标红禁选)。"""
    out = []
    for name, item in sorted(_load_items().items()):
        try:
            cfg = _pitem_trigger_config(item)
        except ValueError as exc:
            out.append({"name": name, "origin": "idol" if item["origin_idol_card_id"] else "support", "trigger": False, "supported": False, "reason": str(exc)})
            continue
        if cfg is None:
            out.append(
                {
                    "name": name,
                    "origin": "idol" if item["origin_idol_card_id"] else "support",
                    "trigger": False,
                    "supported": True,
                    "reason": "非考试期效果(三围等),不入 Round 模拟",
                }
            )
        else:
            out.append({"name": name, "origin": "idol" if item["origin_idol_card_id"] else "support", "trigger": True, "supported": True, "reason": ""})
    return out
