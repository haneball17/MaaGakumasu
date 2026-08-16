"""OCR 卡名词典生成（约束 OCR 候选集，提升日文卡名识别准确率）。

YOLO(cards.onnx) 只输出 cards/suggestions/useless 三类 + box 位置，不读卡名。
适配层在每个 YOLO box 内跑 OCR 时，需用 expected 词典限定候选集，
避免 OCR 在全画面漫无目的识别导致误识。

词典来源：
1. assets/data/hif/skill_cards.json 的卡名（关键 3 张 + 其他）
2. assets/data/hif/skill_card_effects.json 流派过滤池（A1 产物，Plan1+Common
   剔非莉波固有 ≈122 卡，含档位变体全名；実機 変卡/技能卡候选与 Round1
   手牌均出自此池，master 121 卡的 Plan2/3 死代码已剔除；缺文件回退 master）
3. 常见状态卡硬编码（好調/集中等通用卡，提高好调卡计数准确度）

本模块零 maafw 依赖，纯数据生成，可离线单测。
"""

from __future__ import annotations

from agent.hif.decisions.hand_meta import _load_skill_cards, _load_effects_pool, _load_skill_master

# ガラクタロード策略必中的 3 张关键卡（决策分支 1/2/3 的触发条件）。
KEY_CARDS = [
    "お姉さんの感覚",  # 循环启动卡（分支3）
    "自然体の魅力",  # 终结技卡（分支1）
    "国民的アイドル",  # 好调铺垫卡（分支2）
]

# 常见好调/状态卡硬编码（提高 good_condition_card_count 计数准确度）。
# 决策分支6 默认出好调卡，需要较准确的好调卡计数。
COMMON_GOOD_CONDITION_CARDS = [
    "アピールの基礎",
    "ブレスの基礎",
    "ダンスの基礎",
    "ビジュアルの基礎",
    "歌唱の基礎",
    "好調",
]

# OCR 常见误识变体：日文片假名/汉字相近字符的容错映射。
# OCR 把「自然体の魅力」认成「自然体の鹿力」之类的，回退到正解。
# 注意：此映射仅用于 OCR 后的卡名修正，不改变决策逻辑。
# 积累方式：tools/hif_mine_ocr_variants.py 从决策日志挖掘候选，人工确认合入。
OCR_VARIANTS: dict[str, str] = {
    # 占位：实机调试时根据实际误识样本补充（Step 3 调优）。
}

# 编辑距离兜底阈值：距离不超过 max(1, len//4) 且唯一最近邻才修正（低置信标未读不乱猜）。
def _fuzzy_limit(text: str) -> int:
    """编辑距离兜底阈值(按名长分级):≤5 字限 1,≥6 字限 2(実機 2026-08-15
    「好調状能の提分」→「好調状態の提唱」距离 2);配合唯一最近邻约束防误纠。"""
    return 1 if len(text) <= 5 else 2


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein 距离（卡名短,O(n·m) 足够）。"""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_match(text: str, names: list[str]) -> str | None:
    """编辑距离兜底:唯一最近邻且距离达阈值才修正,否则 None(调用方标未读)。"""
    best_name: str | None = None
    best_dist = float("inf")
    ties = 0
    limit = _fuzzy_limit(text)
    for name in names:
        dist = _edit_distance(text, name)
        if dist < best_dist:
            best_name, best_dist, ties = name, dist, 0
        elif dist == best_dist:
            ties += 1
    if best_name is None or best_dist > limit or ties:
        return None
    return best_name


def build_card_name_dict() -> list[str]:
    """生成 OCR expected 词典（卡名候选集）。

    合并关键卡 + skill_cards.json 卡名 + master 121 卡 + 常见好调卡，去重保序。
    数据缺失时回退到硬编码常量，保证降级可用。
    """
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        # 词典统一 NFKC 归一(diff 侧「コール＆レスポンス」全角＆ → 半角&,
        # 与 normalize_card_name 的输入归一同空间,精确匹配不被全半角差异拦截)
        import unicodedata

        name = unicodedata.normalize("NFKC", name)
        if name and name not in seen:
            names.append(name)
            seen.add(name)

    # 1. 关键 3 张（必中，优先级最高）
    for card in KEY_CARDS:
        add(card)

    # 2. skill_cards.json 的卡名（含档位变体）
    table = _load_skill_cards()
    for card_name in table:
        add(card_name)
        base = table[card_name].get("base_name", "")
        if base:
            add(base)

    # 3. 流派过滤池（A1 产物 skill_card_effects.json：Plan1+Common 剔非莉波固有 ≈122 卡，
    #    按实际存在档位生成「軽い足取り+」等变体全名；master 121 卡的 Plan2/3 死代码已剔除，
    #    不再叠加。文件缺失时回退 master 121 卡，保证降级可用。）
    effects_pool = _load_effects_pool()
    if effects_pool:
        for base_name, card in effects_pool.items():
            for tier_key in card.get("tiers", {}):
                suffix = "" if tier_key == "無印" else tier_key
                add(f"{base_name}{suffix}")
    else:
        for card_name in _load_skill_master():
            add(card_name)

    # 4. 常见好调卡
    for card in COMMON_GOOD_CONDITION_CARDS:
        add(card)

    return names


def normalize_card_name(ocr_text: str) -> str:
    """OCR 卡名 → 标准卡名,分层置信匹配(grill 定案 2026-08-15)。

    层序(先高后低):
    1. NFKC 归一(全角＆/数字等 → 半角,実機实证「コール＆レスポンス」全角差异)
    2. 精确命中词典(含档位 + 号全名)
    3. + 号归一:剥档位尾缀后命中基础名 → 返回保留档位的规范名(「大声援+」→ 词典「大声援」确认)
    4. OCR_VARIANTS 变体词典
    5. 编辑距离兜底:唯一最近邻且距离 ≤ max(1, len//4) 才修正
    全部失败返回归一化原文(调用方据此标「卡名未读」,不乱猜)。
    """
    import unicodedata

    text = unicodedata.normalize("NFKC", ocr_text.strip().replace(" ", ""))
    if not text:
        return text
    names = build_card_name_dict()
    name_set = set(names)

    if text in name_set:
        return text

    # + 号档位归一:「大声援+」→ 基础名「大声援」在词典 → 规范返回带档位
    base = text.rstrip("+")
    suffix = text[len(base):]
    if suffix and base in name_set:
        return text

    variant_hit = OCR_VARIANTS.get(text)
    if variant_hit:
        return variant_hit

    fuzzy = _fuzzy_match(text, names)
    if fuzzy:
        return fuzzy
    return text


def is_good_condition_card(card_name: str) -> bool:
    """判断卡名是否属于好调类卡（用于 good_condition_card_count 计数）。

    简化判定：含「好調」字样或在 COMMON_GOOD_CONDITION_CARDS/KEY_CARDS 中。
    精确判定依赖 hand_meta 的 effect_summary，待数据完善后升级。
    """
    if not card_name:
        return False
    if card_name in KEY_CARDS:
        return True
    if card_name in COMMON_GOOD_CONDITION_CARDS:
        return True
    return "好調" in card_name or "好调" in card_name
