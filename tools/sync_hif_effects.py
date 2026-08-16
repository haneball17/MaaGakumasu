"""Sync HIF 效果数值: gakumasu-diff 关联表 join → skill_card_effects.json + drink_effects.json。

用法(先 clone diff,见 sync_hif_master.py):
    python tools/sync_hif_effects.py

join 链路(设计文档 docs/hif/scoring-model-design.md 5.2 定案):
    ProduceCard(id, upgradeCount)
      → playEffects[].produceExamEffectId → ProduceExamEffect(数值: effectValue1/2/Count/Turn)
      → produceCardStatusEnchantId → ProduceCardStatusEnchant(持続効果容器)
          → produceCardGrowEffectIds → ProduceCardGrowEffect(数值: value)
    ProduceDrink → produceDrinkEffectIds → ProduceDrinkEffect
      → produceExamEffectId → ProduceExamEffect / produceEffectId → ProduceEffect

产物口径:
- 卡: planType ∈ {Plan1, Common}(莉波感性路线池,设计文档 5.5),按 id 聚合四档;
  固有卡标记(originIdolCardId/originSupportCardId/originCharacterId)与实证层标记
  (master diff_ids 命中 → master_verified)一并落盘(设计文档待定 #6/#7)。
- 饮料: 全量 29 条 + in_pool(planType ∈ {Common, Plan1},可用 17 种)。
- tag 为五族语义标签(family:semantics,设计文档 3.1),映射未覆盖的类型保留
  原始字段且 tag="unmapped",评分层消费时退关键词兜底,不猜语义。
"""

from __future__ import annotations

import sys
import json
import time
import argparse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_hif_master import TIER_KEYS, _load_yaml, _diff_commit  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIFF = REPO / ".scrape" / "gakumasu-diff"
MASTER_SRC = REPO / "assets" / "data" / "hif" / "skill_cards_master.json"
CARDS_OUT = REPO / "assets" / "data" / "hif" / "skill_card_effects.json"
DRINKS_OUT = REPO / "assets" / "data" / "hif" / "drink_effects.json"

POOL_PLANS = {"ProducePlanType_Plan1", "ProducePlanType_Common"}

# ProduceExamEffectType 短名 → (tag, op, unit, value_key)
# tag 格式 family:semantics;op ∈ add/mult/set;unit ∈ flat/pct/mult/turns
# 日文名对照见 ProduceDescriptionExamEffect.yaml(映射时逐条核过)
EXAM_EFFECT_TAGS: dict[str, tuple[str, str, str, str]] = {
    # --- 即得分族 ---
    "ExamLesson": ("score:parameter_add", "add", "flat", "value1"),
    "ExamLessonFix": ("score:parameter_add_fix", "add", "flat", "value1"),
    "ExamLessonValueMultiple": ("score:parameter_gain_mult", "mult", "pct", "value1"),
    "ExamLessonValueMultipleDown": ("score:parameter_gain_mult_down", "mult", "pct", "value1"),
    "ExamLessonValueMultipleDependReviewOrAggressive": ("score:parameter_gain_mult_cond", "mult", "pct", "value1"),
    "ExamLessonBuffLesson": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamMultipleLessonBuffLesson": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamMultipleEnthusiasticLesson": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonAddMultipleParameterBuff": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonAddMultipleLessonBuff": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependBlock": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependParameterBuff": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependExamReview": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependExamCardPlayAggressive": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependPlayCardCountSum": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependStamina": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependStaminaConsumptionSum": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependBlockConsumptionSum": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamLessonDependBlockAndSearchCount": ("score:parameter_add_cond", "add", "pct", "value2"),
    "ExamLessonPerSearchCount": ("score:parameter_add_cond", "add", "flat", "value1"),
    "ExamFullPowerLessonMultipleAdditive": ("score:full_power_amplify", "add", "flat", "value1"),
    "ExamLessonChangeSpecifyLessThan": ("score:parameter_change", "set", "flat", "value1"),
    "ExamLessonChangeSpecifyMoreThan": ("score:parameter_change", "set", "flat", "value1"),
    # --- 状态增益族 ---
    "ExamParameterBuff": ("buff:good_condition", "add", "turns", "value1"),
    "ExamParameterBuffMultiplePerTurn": ("buff:excellent_condition", "add", "turns", "value1"),
    "ExamParameterBuffMultiplePerTurnReduce": ("penalty:excellent_down", "add", "turns", "value1"),
    "ExamParameterBuffAdditive": ("buff:good_condition_amp", "add", "flat", "value1"),
    "ExamParameterBuffAdditiveFix": ("buff:good_condition_amp", "add", "flat", "value1"),
    "ExamParameterBuffDependLessonBuff": ("buff:good_condition_cond", "add", "turns", "value1"),
    "ExamParameterBuffReduce": ("penalty:good_condition_down", "add", "turns", "value1"),
    "ExamLessonBuff": ("buff:focus", "add", "turns", "value1"),
    "ExamLessonBuffMultiple": ("buff:focus_amplify", "mult", "pct", "value1"),
    "ExamLessonBuffAdditive": ("buff:focus_amp", "add", "flat", "value1"),
    "ExamLessonBuffAdditiveFix": ("buff:focus_amp", "add", "flat", "value1"),
    "ExamLessonBuffDependParameterBuff": ("buff:focus_cond", "add", "turns", "value1"),
    "ExamLessonBuffPerSearchCount": ("buff:focus_cond", "add", "turns", "value1"),
    "ExamLessonBuffReduce": ("penalty:focus_down", "add", "turns", "value1"),
    "ExamReview": ("buff:good_impression", "add", "flat", "value1"),
    "ExamReviewMultiple": ("buff:good_impression_amplify", "mult", "pct", "value1"),
    "ExamReviewValueMultiple": ("buff:good_impression_amplify", "mult", "pct", "value1"),
    "ExamReviewAdditive": ("buff:good_impression_amp", "add", "flat", "value1"),
    "ExamReviewReduce": ("penalty:good_impression_down", "add", "flat", "value1"),
    "ExamReviewPerSearchCount": ("buff:good_impression_cond", "add", "flat", "value1"),
    "ExamCardPlayAggressive": ("buff:motivation", "add", "flat", "value1"),
    "ExamAggressiveAdditive": ("buff:motivation_amp", "add", "flat", "value1"),
    "ExamAggressiveAdditiveFix": ("buff:motivation_amp", "add", "flat", "value1"),
    "ExamAggressiveValueMultiple": ("buff:motivation_amplify", "mult", "pct", "value1"),
    "ExamAggressiveReduce": ("penalty:motivation_down", "add", "flat", "value1"),
    "ExamConcentration": ("buff:confidence", "add", "flat", "value1"),
    "ExamFullPowerPoint": ("buff:full_power", "add", "flat", "value1"),
    "ExamFullPowerPointAdditive": ("buff:full_power_amp", "add", "flat", "value1"),
    "ExamFullPowerPointReduce": ("penalty:full_power_down", "add", "flat", "value1"),
    "ExamUplifting": ("buff:uplifting", "add", "flat", "value1"),
    "ExamCardUpgrade": ("buff:card_upgrade", "add", "flat", "value1"),
    "ExamGetCardUpgrade": ("buff:card_upgrade", "add", "flat", "value1"),
    "ExamEnthusiasticAdditive": ("buff:enthusiasm", "add", "flat", "value1"),
    "ExamEnthusiasticMultiple": ("buff:enthusiasm", "mult", "pct", "value1"),
    # --- 行动经济族 ---
    "ExamCardDraw": ("action:draw", "add", "flat", "value1"),
    "ExamHandGraveCountCardDraw": ("action:draw_replace", "add", "flat", "value1"),
    "ExamPlayableValueAdd": ("action:play_add", "add", "flat", "value1"),
    "ExamExtraTurn": ("action:extra_turn", "add", "flat", "value1"),
    "ExamCardCreateId": ("action:create", "add", "flat", "value1"),
    "ExamCardCreateSearch": ("action:create", "add", "flat", "value1"),
    "ExamCardMove": ("action:move", "add", "flat", "value1"),
    "ExamCardDuplicate": ("action:duplicate", "add", "flat", "value1"),
    "ExamStatusEnchantEncore": ("action:encore", "add", "flat", "value1"),
    "ExamHandHold": ("action:hand_hold", "add", "flat", "value1"),
    "ExamCardSearchEffectPlayCountBuff": ("action:extra_play", "add", "flat", "value1"),
    "ExamForcePlayCardSearch": ("action:force_search", "add", "flat", "value1"),
    "ExamForcePlayCardSearchWithCost": ("action:force_search", "add", "flat", "value1"),
    "ExamReviewCountAdd": ("action:extra_play", "add", "flat", "value1"),
    # --- 资源续航族 ---
    "ExamBlock": ("resource:energy", "add", "flat", "value1"),
    "ExamBlockFix": ("resource:energy_fix", "add", "flat", "value1"),
    "ExamBlockPerUseCardCount": ("resource:energy_cond", "add", "flat", "value1"),
    "ExamBlockAddMultipleAggressive": ("resource:energy_cond", "add", "flat", "value1"),
    "ExamBlockValueMultiple": ("resource:energy_amplify", "mult", "pct", "value1"),
    "ExamBlockDown": ("penalty:energy_down", "add", "flat", "value1"),
    "ExamBlockRestriction": ("penalty:energy_block", "add", "flat", "value1"),
    "ExamBlockAddDown": ("penalty:status_anxiety", "add", "flat", "value1"),
    "ExamBlockAddDownRestriction": ("defense:anxiety_block", "add", "flat", "value1"),
    "ExamStaminaRecoverFix": ("resource:stamina_recover", "add", "flat", "value1"),
    "ExamStaminaRecoverMultiple": ("resource:stamina_recover", "mult", "pct", "value1"),
    "ExamStaminaRecoverAdd": ("resource:stamina_recover_amp", "add", "flat", "value1"),
    "ExamStaminaRecoverRestriction": ("penalty:stamina_recover_block", "add", "flat", "value1"),
    "ExamStaminaConsumptionDown": ("resource:stamina_cost_down", "mult", "pct", "value1"),
    "ExamStaminaConsumptionDownFix": ("resource:stamina_cost_down_fix", "add", "flat", "value1"),
    "ExamStaminaConsumptionDownAdd": ("resource:stamina_cost_down_amp", "add", "flat", "value1"),
    "ExamStaminaReduceFix": ("resource:stamina_cost_fix", "add", "flat", "value1"),
    "ExamStaminaReduce": ("resource:stamina_cost_change", "mult", "pct", "value1"),
    "ExamStaminaReduceChange": ("resource:stamina_cost_change", "mult", "pct", "value1"),
    "ExamSearchPlayCardStaminaConsumptionChange": ("resource:stamina_cost_change", "mult", "pct", "value1"),
    "ExamItemFireLimitAdd": ("resource:item_use_add", "add", "flat", "value1"),
    # --- 代价妨害族 ---
    "ExamStaminaDamage": ("penalty:stamina_damage", "add", "flat", "value1"),
    "ExamStaminaConsumptionAdd": ("penalty:stamina_cost_add", "mult", "pct", "value1"),
    "ExamStaminaConsumptionAddFix": ("penalty:stamina_cost_add_fix", "add", "flat", "value1"),
    "ExamStaminaConsumptionAddDown": ("resource:stamina_cost_add_down", "add", "flat", "value1"),
    "ExamGimmickSleepy": ("penalty:status_sleepy", "add", "turns", "value1"),
    "ExamGimmickSlump": ("penalty:status_slump", "add", "turns", "value1"),
    "ExamGimmickPlayCardLimit": ("penalty:play_limit", "add", "turns", "value1"),
    "ExamGimmickLessonDebuff": ("penalty:status_tension", "add", "turns", "value1"),
    "ExamGimmickParameterDebuff": ("penalty:status_bad_condition", "add", "turns", "value1"),
    "ExamGimmickStartTurnCardDrawDown": ("penalty:draw_down", "add", "turns", "value1"),
    "ExamGimmickEnthusiastic": ("penalty:status_enthusiasm", "add", "turns", "value1"),
    "ExamPanic": ("penalty:status_whim", "add", "turns", "value1"),
    # --- 防御/指針/容器 ---
    "ExamAntiDebuff": ("defense:debuff_block", "add", "turns", "value1"),
    "ExamDebuffRecover": ("defense:debuff_recover", "add", "flat", "value1"),
    "ExamFullPower": ("stance:full_power", "add", "flat", "value1"),
    "ExamStanceReset": ("stance:reset", "add", "flat", "value1"),
    "StanceLock": ("stance:lock", "add", "turns", "value1"),
    "ExamPreservation": ("stance:preserve", "add", "flat", "value1"),
    "ExamOverPreservation": ("stance:over_preserve", "add", "flat", "value1"),
    "ExamStatusEnchant": ("container:enchant", "add", "flat", "value1"),
    "ExamEffectTimer": ("container:timer", "add", "flat", "value1"),
    "ExamAddGrowEffect": ("grow:add", "add", "flat", "value1"),
}

# ProduceCardGrowEffectType 短名 → (tag, op, unit)
GROW_EFFECT_TAGS: dict[str, tuple[str, str, str]] = {
    "LessonAdd": ("score:parameter_add", "add", "flat"),
    "LessonReduce": ("penalty:parameter_down", "add", "flat"),
    "LessonCountAdd": ("score:parameter_count_add", "add", "flat"),
    "LessonCountReduce": ("penalty:parameter_count_down", "add", "flat"),
    "BlockAdd": ("resource:energy", "add", "flat"),
    "BlockReduce": ("penalty:energy_down", "add", "flat"),
    "FullPowerPointAdd": ("buff:full_power", "add", "flat"),
    "FullPowerPointReduce": ("penalty:full_power_down", "add", "flat"),
    "ParameterBuffTurnAdd": ("buff:good_condition", "add", "flat"),
    "ParameterBuffTurnReduce": ("penalty:good_condition_down", "add", "flat"),
    "LessonBuffAdd": ("buff:focus", "add", "flat"),
    "LessonBuffReduce": ("penalty:focus_down", "add", "flat"),
    "ReviewAdd": ("buff:good_impression", "add", "flat"),
    "ReviewReduce": ("penalty:good_impression_down", "add", "flat"),
    "AggressiveAdd": ("buff:motivation", "add", "flat"),
    "AggressiveReduce": ("penalty:motivation_down", "add", "flat"),
    "CostReduce": ("resource:card_cost_down", "add", "flat"),
    "CostAdd": ("penalty:card_cost_add", "add", "flat"),
    "CostBuffReduce": ("resource:buffed_card_cost_down", "add", "flat"),
    "CostBuffAdd": ("penalty:buffed_card_cost_add", "add", "flat"),
    "CostPenetrateReduce": ("resource:stamina_pierce_cost_down", "add", "flat"),
    "CostPenetrateAdd": ("penalty:stamina_pierce_cost_add", "add", "flat"),
}

# ProduceEffectType(非考试期效果,饮料侧)短名 → (tag, op, unit)
PRODUCE_EFFECT_TAGS: dict[str, tuple[str, str, str]] = {
    "VocalAddition": ("score:parameter_add", "add", "flat"),
    "DanceAddition": ("score:parameter_add", "add", "flat"),
    "ExpressionAddition": ("score:parameter_add", "add", "flat"),
    "VocalAdditionExtra": ("score:parameter_add", "add", "flat"),
    "DanceAdditionExtra": ("score:parameter_add", "add", "flat"),
    "ExpressionAdditionExtra": ("score:parameter_add", "add", "flat"),
    "StaminaRecoverFix": ("resource:stamina_recover", "add", "flat"),
    "MotivationAddition": ("buff:motivation", "add", "flat"),
}


def _short(enum: str) -> str:
    """ProduceExamEffectType_ExamLesson → ExamLesson"""
    return enum.rsplit("_", 1)[-1] if enum else ""


def _enum_names(path: Path) -> dict[str, str]:
    """枚举表 type → 日文名(如 ExamLesson → パラメータ)。"""
    names: dict[str, str] = {}
    for row in _load_yaml(path):
        names[_short(row.get("type", ""))] = row.get("name", "")
    return names


def _index(rows: list[dict], key: str = "id") -> dict[str, dict]:
    return {row[key]: row for row in rows if row.get(key)}


def _exam_effect_entry(
    effect: dict,
    exam_names: dict[str, str],
    condition: str | None = None,
    note: str | None = None,
) -> dict:
    short = _short(effect.get("effectType", ""))
    tag, op, unit, value_key = EXAM_EFFECT_TAGS.get(short, ("unmapped", None, None, "value1"))
    return {
        "tag": tag,
        "name_jp": exam_names.get(short, ""),
        "op": op,
        "value": effect.get(value_key) if effect.get(value_key) else effect.get("effectValue1"),
        "value2": effect.get("effectValue2") or None,
        "turn": effect.get("effectTurn") or None,
        "count": effect.get("effectCount") or None,
        "unit": unit,
        "scope": "self",
        "condition": condition or (effect.get("produceCardSearchId") or None),
        "effect_id": effect.get("id"),
        "effect_type": effect.get("effectType"),
        "note": note,
    }


def _grow_effect_entry(grow: dict, grow_names: dict[str, str], condition: str | None) -> dict:
    short = _short(grow.get("effectType", ""))
    tag, op, unit = GROW_EFFECT_TAGS.get(short, ("unmapped", None, None))
    return {
        "tag": tag,
        "name_jp": grow_names.get(short, ""),
        "op": op,
        "value": grow.get("value"),
        "value2": None,
        "turn": None,
        "count": None,
        "unit": unit,
        "scope": "self",
        "condition": condition,
        "effect_id": grow.get("id"),
        "effect_type": grow.get("effectType"),
        "note": "grow_effect",
    }


def _expand_timer_child(
    effect: dict,
    entry: dict,
    exam_idx: dict[str, dict],
    exam_names: dict[str, str],
    condition: str | None,
) -> dict | None:
    """発動予約(timer)容器展开:child 效果 id 拼在 timer id 尾段
    (e_effect-exam_effect_timer-{delay}-{count}-{child_id}),delay = effectValue1。
    展开为 deferred 效果(评分侧按延迟折现);child 查不到返回 None(原条目保留)。"""
    # id 形如 e_effect-exam_effect_timer-0001-01-e_effect-exam_card_draw-0002:
    # 从第二个 "e_effect" 起为 child id
    tokens = effect.get("id", "").split("-")
    starts = [i for i, tok in enumerate(tokens) if tok == "e_effect"]
    child_id = "-".join(tokens[starts[1]:]) if len(starts) >= 2 else None
    if not child_id or child_id not in exam_idx:
        return None
    child = exam_idx[child_id]
    delay = effect.get("effectValue1") or 0
    expanded = _exam_effect_entry(child, exam_names, condition=condition)
    expanded["note"] = f"{expanded.get('note') or expanded['tag']}(予約:{delay}回合後)"
    expanded["deferred_turns"] = delay
    return expanded


def _card_tier_effects(
    variant: dict,
    exam_idx: dict[str, dict],
    grow_idx: dict[str, dict],
    enchant_idx: dict[str, dict],
    exam_names: dict[str, str],
    grow_names: dict[str, str],
    stats: dict,
) -> list[dict]:
    effects: list[dict] = []
    for play in variant.get("playEffects") or []:
        effect_id = play.get("produceExamEffectId")
        if not effect_id:
            continue
        effect = exam_idx.get(effect_id)
        if effect is None:
            effects.append({"tag": "unmapped", "effect_id": effect_id, "note": "exam effect not found"})
            continue
        condition = play.get("produceExamTriggerId") or None
        entry = _exam_effect_entry(effect, exam_names, condition=condition)
        # 強気(ExamConcentration)档位:effectValue1 = 1/2 级(倍率 ×2.0/×2.5,ExamSetting)
        if entry["tag"] == "buff:confidence" and effect.get("effectValue1") in (1, 2):
            entry["level"] = effect["effectValue1"]
        effects.append(entry)
        # 発動予約容器展开(聚光灯类循环卡的延迟效果,136 条解封)
        if entry["tag"] == "container:timer":
            expanded = _expand_timer_child(effect, entry, exam_idx, exam_names, condition)
            if expanded is not None:
                effects.append(expanded)
                stats["timer_expanded"] = stats.get("timer_expanded", 0) + 1
            else:
                stats["timer_unexpanded"] = stats.get("timer_unexpanded", 0) + 1
        # 成長効果(ExamAddGrowEffect 等指向的 grow 数值)展开一层
        for gid in effect.get("produceCardGrowEffectIds") or []:
            grow = grow_idx.get(gid)
            if grow is not None:
                effects.append(_grow_effect_entry(grow, grow_names, condition=condition))
    # 持続効果容器(条件触发,如「レッスン中1回」类卡的本质机制)
    enchant_id = variant.get("produceCardStatusEnchantId")
    if enchant_id and enchant_id in enchant_idx:
        enchant = enchant_idx[enchant_id]
        trigger = enchant.get("produceExamTriggerId") or None
        for gid in enchant.get("produceCardGrowEffectIds") or []:
            grow = grow_idx.get(gid)
            if grow is not None:
                effects.append(_grow_effect_entry(grow, grow_names, condition=trigger))
    return effects


def sync_cards(diff_root: Path, master: dict) -> tuple[dict, dict]:
    print("loading ProduceExamEffect.yaml ...")
    exam_idx = _index(_load_yaml(diff_root / "ProduceExamEffect.yaml"))
    print("loading ProduceCardStatusEnchant.yaml ...")
    enchant_idx = _index(_load_yaml(diff_root / "ProduceCardStatusEnchant.yaml"))
    print("loading ProduceCardGrowEffect.yaml ...")
    grow_idx = _index(_load_yaml(diff_root / "ProduceCardGrowEffect.yaml"))
    exam_names = _enum_names(diff_root / "ProduceDescriptionExamEffect.yaml")
    grow_names = _enum_names(diff_root / "ProduceDescriptionProduceCardGrowEffect.yaml")

    print("loading ProduceCard.yaml ...")
    pool: dict[str, list[dict]] = {}
    for card in _load_yaml(diff_root / "ProduceCard.yaml"):
        if card.get("planType") in POOL_PLANS:
            pool.setdefault(card["id"], []).append(card)

    # 实证层标记(待定 #7):master diff_ids 全档位 id 值集合
    master_ids: set[str] = set()
    for card in master.get("cards", []):
        for diff_id in (card.get("diff_ids") or {}).values():
            if diff_id:
                master_ids.add(diff_id)

    cards_out: list[dict] = []
    stats = {"tag": {}, "unmapped_types": {}, "origin_character": {}, "origin_idol": {}}
    for card_id, variants in sorted(pool.items()):
        variants.sort(key=lambda c: c.get("upgradeCount") or 0)
        base = variants[0]
        origin_character = base.get("originCharacterId") or ""
        origin_idol = base.get("originIdolCardId") or ""
        origin_support = base.get("originSupportCardId") or ""
        entry = {
            "card_id": card_id,
            "name_jp": base.get("name"),
            "rarity": base.get("rarity"),
            "plan": base.get("planType"),
            "category": base.get("category"),
            "origin_character_id": origin_character,
            "origin_idol_card_id": origin_idol,
            "origin_support_card_id": origin_support,
            # 待定 #6 定案(実機实证 2026-08-16):i_card-hrnm = 姫崎莉波固有卡,
            # s_card-* 支援卡固有卡在実機实证层大量出现,两者均保留;
            # 其他偶像固有(origin_idol 非 hrnm)与角色标记卡(nasr 等)实证层未出现,剔除
            "is_idol_exclusive": bool(
                (origin_idol and not origin_idol.startswith("i_card-hrnm-")) or bool(origin_character)
            ),
            "master_verified": card_id in master_ids,
            # 出牌去向(D1 裁决):Lost=lesson_once 用后除外不回流;Grave=捨て札重洗回流(循环卡)
            "move_position": (base.get("playMovePositionType") or "").replace("ProduceCardMovePositionType_", "") or None,
            "is_lesson_once": (base.get("playMovePositionType") or "").endswith("Lost"),
            "flags": {
                "is_initial": bool(base.get("isInitial")),
                "is_initial_deck": bool(base.get("isInitialDeckProduceCard")),
                "is_reward": bool(base.get("isReward")),
                "no_deck_duplication": bool(base.get("noDeckDuplication")),
            },
            "tiers": {},
        }
        for variant in variants:
            key = TIER_KEYS.get(variant.get("upgradeCount"))
            if key is None:
                continue
            effects = _card_tier_effects(variant, exam_idx, grow_idx, enchant_idx, exam_names, grow_names, stats)
            for eff in effects:
                tag = eff.get("tag") or "unmapped"
                stats["tag"][tag] = stats["tag"].get(tag, 0) + 1
                if tag == "unmapped":
                    t = eff.get("effect_type") or eff.get("effect_id") or "?"
                    stats["unmapped_types"][t] = stats["unmapped_types"].get(t, 0) + 1
            entry["tiers"][key] = {
                "stamina": variant.get("stamina"),
                "cost_type": variant.get("costType") or None,
                "cost_value": variant.get("costValue") or None,
                "effects": effects,
            }
        if entry["tiers"]:
            cards_out.append(entry)
            if entry["is_lesson_once"]:
                stats["lesson_once"] = stats.get("lesson_once", 0) + 1
            if origin_character:
                stats["origin_character"].setdefault(origin_character, []).append(base.get("name"))
            if origin_idol:
                stats["origin_idol"].setdefault(origin_idol, []).append(base.get("name"))

    payload = {
        "schema_version": 1,
        "entity": "hif_card_effects",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pool_note": "planType ∈ {Plan1, Common}(姫崎莉波感性路线池,设计文档 5.5);is_idol_exclusive=非莉波偶像固有/角色标记卡(待定 #6,实证剔除依据 hrnm=莉波、s_card 支援固有保留);master_verified=実機实证层(待定 #7)",
        "sources": [
            {
                "source": "vertesan/gakumasu-diff",
                "commit": _diff_commit(diff_root),
                "tables": [
                    "ProduceCard.yaml",
                    "ProduceExamEffect.yaml",
                    "ProduceCardStatusEnchant.yaml",
                    "ProduceCardGrowEffect.yaml",
                    "ProduceDescriptionExamEffect.yaml",
                    "ProduceDescriptionProduceCardGrowEffect.yaml",
                ],
            }
        ],
        "cards": cards_out,
    }
    return payload, stats


def sync_drinks(diff_root: Path) -> tuple[dict, dict]:
    print("loading drink tables ...")
    drinks = _load_yaml(diff_root / "ProduceDrink.yaml")
    drink_effect_idx = _index(_load_yaml(diff_root / "ProduceDrinkEffect.yaml"))
    exam_idx = _index(_load_yaml(diff_root / "ProduceExamEffect.yaml"))
    produce_idx = _index(_load_yaml(diff_root / "ProduceEffect.yaml"))
    exam_names = _enum_names(diff_root / "ProduceDescriptionExamEffect.yaml")
    produce_names = _enum_names(diff_root / "ProduceDescriptionProduceEffect.yaml")

    drinks_out = []
    stats = {"tag": {}, "unmapped_types": {}}
    for drink in drinks:
        effects = []
        for deid in drink.get("produceDrinkEffectIds") or []:
            de = drink_effect_idx.get(deid)
            if de is None:
                effects.append({"tag": "unmapped", "effect_id": deid, "note": "drink effect not found"})
                continue
            if de.get("produceExamEffectId"):
                effect = exam_idx.get(de["produceExamEffectId"])
                if effect is not None:
                    effects.append(_exam_effect_entry(effect, exam_names))
            if de.get("produceEffectId"):
                pe = produce_idx.get(de["produceEffectId"])
                if pe is not None:
                    short = _short(pe.get("produceEffectType", ""))
                    tag, op, unit = PRODUCE_EFFECT_TAGS.get(short, ("unmapped", None, None))
                    effects.append(
                        {
                            "tag": tag,
                            "name_jp": produce_names.get(short, ""),
                            "op": op,
                            "value": pe.get("effectValueMin"),
                            "value2": pe.get("effectValueMax"),
                            "turn": None,
                            "count": None,
                            "unit": unit,
                            "scope": "self",
                            "condition": None,
                            "effect_id": pe.get("id"),
                            "effect_type": pe.get("produceEffectType"),
                            "note": "produce_effect",
                        }
                    )
        for eff in effects:
            tag = eff.get("tag") or "unmapped"
            stats["tag"][tag] = stats["tag"].get(tag, 0) + 1
            if tag == "unmapped":
                t = eff.get("effect_type") or eff.get("effect_id") or "?"
                stats["unmapped_types"][t] = stats["unmapped_types"].get(t, 0) + 1
        drinks_out.append(
            {
                "drink_id": drink["id"],
                "name_jp": drink["name"],
                "rarity": drink.get("rarity"),
                "plan": drink.get("planType"),
                "in_pool": drink.get("planType") in POOL_PLANS,
                "origin_support_card_id": drink.get("originSupportCardId") or "",
                "effects": effects,
            }
        )

    payload = {
        "schema_version": 1,
        "entity": "hif_drink_effects",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pool_note": "in_pool = planType ∈ {Common, Plan1}(莉波路线可用 17 种,设计文档 5.4)",
        "sources": [
            {
                "source": "vertesan/gakumasu-diff",
                "commit": _diff_commit(diff_root),
                "tables": ["ProduceDrink.yaml", "ProduceDrinkEffect.yaml", "ProduceExamEffect.yaml", "ProduceEffect.yaml"],
            }
        ],
        "drinks": drinks_out,
    }
    return payload, stats


def run_reconciliation(cards_payload: dict, master: dict) -> list[str]:
    """M1 对账断言:master 121 卡全命中、88 实证、軽い足取り数值、plan 一致。"""
    problems: list[str] = []
    by_id = {c["card_id"]: c for c in cards_payload["cards"]}
    by_name: dict[str, dict] = {}
    for card in cards_payload["cards"]:
        by_name[card["name_jp"].rstrip("+")] = card

    # 1) master 感性池卡 name 全命中(全角&归一;master 的 Plan2/Plan3 卡共 32 张
    #    为死代码(设计文档 5.5),不在本池,跳过)
    norm = lambda s: s.replace("＆", "&").replace("&", "＆")
    diff_names = {norm(n) for n in by_name}
    missing = [
        c["name_jp"]
        for c in master.get("cards", [])
        if c.get("plan_type") in POOL_PLANS and norm(c["name_jp"]) not in diff_names
    ]
    if missing:
        problems.append(f"master 感性池卡未命中: {missing}")

    # 2) 实证层计数(设计文档 5.5:88 卡)
    verified = {c["name_jp"] for c in master.get("cards", []) if c.get("plan_type") in POOL_PLANS}
    hit = sum(1 for c in cards_payload["cards"] if c["master_verified"])
    if hit != len(verified):
        problems.append(f"master_verified 计数 {hit} != master 感性池卡数 {len(verified)}")

    # 3) 軽い足取り 数值对账(設計文檔 M1: パラメータ+6 好調2ターン)
    karui = by_name.get("軽い足取り")
    if not karui:
        problems.append("軽い足取り 不在产物中")
    else:
        tier0 = karui["tiers"].get("無印") or {}
        tags = {(e.get("tag"), e.get("value"), e.get("turn")) for e in tier0.get("effects", [])}
        if ("score:parameter_add", 6, None) not in tags:
            problems.append(f"軽い足取り 無印 缺 パラメータ+6: {tags}")
        if not any(t and t[0] == "buff:good_condition" and t[2] == 2 for t in tags):
            problems.append(f"軽い足取り 無印 缺 好調2ターン: {tags}")

    # 4) plan 一致性:master.plan_type vs diff plan(设计文档 5.3: 100% 一致)
    for c in master.get("cards", []):
        target = by_name.get(c["name_jp"].rstrip("+"))
        if target and c.get("plan_type") != target.get("plan"):
            problems.append(f"plan 不一致: {c['name_jp']} master={c.get('plan_type')} diff={target.get('plan')}")

    # 5) lesson_once 交叉验证(D1 裁决):master is_lesson_once vs diff move_position==Lost
    #    仅对实证层(master_verified)卡对账——wiki 标记与数据字段应一一对应
    mismatches = []
    for c in master.get("cards", []):
        target = by_name.get(c["name_jp"].rstrip("+"))
        if target and target.get("master_verified"):
            if bool(c.get("is_lesson_once")) != bool(target.get("is_lesson_once")):
                mismatches.append(f"{c['name_jp']}(wiki={c.get('is_lesson_once')} diff={target.get('move_position')})")
    if mismatches:
        problems.append(f"lesson_once 不一致 {len(mismatches)} 张: {mismatches[:5]}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff-path", type=Path, default=DEFAULT_DIFF)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (args.diff_path / "ProduceCard.yaml").exists():
        print(f"[FATAL] {args.diff_path} 下无 ProduceCard.yaml,先 clone vertesan/gakumasu-diff")
        return 1

    master = json.loads(MASTER_SRC.read_text(encoding="utf-8"))
    cards_payload, card_stats = sync_cards(args.diff_path, master)
    drinks_payload, drink_stats = sync_drinks(args.diff_path)

    tier_records = sum(len(c["tiers"]) for c in cards_payload["cards"])
    print(f"\ncards: {len(cards_payload['cards'])} 去重卡 / {tier_records} 档位记录")
    print(f"master_verified: {sum(1 for c in cards_payload['cards'] if c['master_verified'])}")
    print(f"is_idol_exclusive: {sum(1 for c in cards_payload['cards'] if c['is_idol_exclusive'])}")
    print(f"lesson_once(Lost 除外): {card_stats.get('lesson_once', 0)} / 循环卡(Grave): {sum(1 for c in cards_payload['cards'] if c.get('move_position') == 'Grave')}")
    print(f"timer 展开: {card_stats.get('timer_expanded', 0)} 成功 / {card_stats.get('timer_unexpanded', 0)} 未展开")
    print(f"in_pool drinks: {sum(1 for d in drinks_payload['drinks'] if d['in_pool'])} / {len(drinks_payload['drinks'])}")
    print("\n-- 固有卡对账(待定 #6,nasr 归属需人审)--")
    for char, names in sorted(card_stats["origin_character"].items()):
        print(f"  originCharacterId={char}: {len(names)} 卡 {names[:4]}")
    for idol, names in sorted(card_stats["origin_idol"].items()):
        print(f"  originIdolCardId={idol}: {len(names)} 卡 {names[:4]}")
    print("\n-- tag 分布 top15 --")
    for tag, n in sorted(card_stats["tag"].items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {n:4d}  {tag}")
    unmapped_total = sum(card_stats["unmapped_types"].values())
    print(f"\nunmapped effects: {unmapped_total} 条")
    for t, n in sorted(card_stats["unmapped_types"].items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {n:4d}  {t}")
    print(f"drink unmapped: {sum(drink_stats['unmapped_types'].values())} 条")
    for t, n in sorted(drink_stats["unmapped_types"].items(), key=lambda kv: -kv[1])[:5]:
        print(f"  {n:4d}  {t}")

    problems = run_reconciliation(cards_payload, master)
    if problems:
        print("\n[M1 对账失败]")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n[M1 对账通过] 121 卡全命中 / 88 实证 / 軽い足取り数值正确 / plan 100% 一致")

    if args.dry_run:
        print("(dry-run,未写盘)")
        return 0

    CARDS_OUT.write_text(json.dumps(cards_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DRINKS_OUT.write_text(json.dumps(drinks_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written: {CARDS_OUT}")
    print(f"written: {DRINKS_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
