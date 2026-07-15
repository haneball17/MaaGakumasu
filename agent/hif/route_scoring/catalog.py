"""`rinami_garakuta_road` 当前画面已验证卡面效果。

效果来源为 ``assets/data/hif/skill_cards_master.json`` 的对应 tier。目录只收录
当前停点能严格解释的版本；未收录版本由评分器拒绝，不能按同名卡或相邻强化等级猜测。
"""

from __future__ import annotations

from types import MappingProxyType

from agent.hif.route_scoring.models import CardSpec, CardEffect, UpgradeLevel

_MASTER_SOURCE = "assets/data/hif/skill_cards_master.json"
_EFFECT_VERSION = "rinami-garakuta-observed-2026-07-15.1"

_SPECS = (
    CardSpec(
        card_id="祝福",
        title="祝福",
        upgrade=UpgradeLevel.BASE,
        stamina_cost=4,
        focus_cost=0,
        lesson_once=True,
        effect_version=_EFFECT_VERSION,
        effect=CardEffect(parameter_gain=26, good_condition_turns=1),
        source=f"{_MASTER_SOURCE}:669",
    ),
    CardSpec(
        card_id="祝福",
        title="祝福",
        upgrade=UpgradeLevel.PLUS,
        stamina_cost=4,
        focus_cost=0,
        lesson_once=True,
        effect_version=_EFFECT_VERSION,
        effect=CardEffect(parameter_gain=40, good_condition_turns=1),
        source=f"{_MASTER_SOURCE}:669",
    ),
    CardSpec(
        card_id="演出計画",
        title="演出計画",
        upgrade=UpgradeLevel.BASE,
        stamina_cost=4,
        focus_cost=0,
        lesson_once=True,
        effect_version=_EFFECT_VERSION,
        effect=CardEffect(excellent_condition_turns=3, fixed_guard_on_future_active=2),
        source=f"{_MASTER_SOURCE}:933",
    ),
    # 当前画面只证明「眠気」为灰卡，没有可执行效果证据。保留实体用于输出
    # 明确的 unsupported_card_effect；正常灰卡路径会更早以 gray_card 拒绝。
    CardSpec(
        card_id="眠気",
        title="眠気",
        upgrade=UpgradeLevel.BASE,
        stamina_cost=0,
        focus_cost=0,
        lesson_once=False,
        effect_version=_EFFECT_VERSION,
        effect=None,
        source="plans/hif-mvp/HANDOFF.md",
    ),
)

RINAMI_GARAKUTA_CARD_SPECS = MappingProxyType({spec.key: spec for spec in _SPECS})

