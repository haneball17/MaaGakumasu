"""OCR 卡名词典生成（约束 OCR 候选集，提升日文卡名识别准确率）。

YOLO(cards.onnx) 只输出 cards/suggestions/useless 三类 + box 位置，不读卡名。
适配层在每个 YOLO box 内跑 OCR 时，需用 expected 词典限定候选集，
避免 OCR 在全画面漫无目的识别导致误识。

词典来源：
1. assets/data/hif/skill_cards.json 的卡名（关键 3 张 + 其他）
2. 常见状态卡硬编码（好調/集中等通用卡，提高好调卡计数准确度）

本模块零 maafw 依赖，纯数据生成，可离线单测。
"""

from __future__ import annotations

from agent.hif.catalog import load_hif_catalog
from agent.hif.decisions.hand_meta import _load_skill_cards

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

# 已在实机源卡牌库中观察到、但主卡表尚未收录的基础卡。
# 仅用于约束 OCR 识别，不能作为自动出牌或奖励决策依据。
OBSERVED_SOURCE_DECK_CARD_NAMES = [
    "タイミングの基本",
    "仕切り直し",
    "眠気",
    "アイドル宣言",
    "シュプレヒコール",
]

# OCR 常见误识变体：日文片假名/汉字相近字符的容错映射。
# OCR 把「自然体の魅力」认成「自然体の鹿力」之类的，回退到正解。
# 注意：此映射仅用于 OCR 后的卡名修正，不改变决策逻辑。
OCR_VARIANTS: dict[str, str] = {
    # Round1 五卡压缩布局中，右邻卡标题首字会被拼入末尾。
    "話題沸騰鳴": "話題沸騰",
}


def build_card_name_dict() -> list[str]:
    """生成 OCR expected 词典（卡名候选集）。

    合并 skill_cards.json 卡名 + 关键卡 + 常见好调卡，去重保序。
    数据缺失时回退到硬编码常量，保证降级可用。
    """
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
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

    # 3. 常见好调卡
    for card in COMMON_GOOD_CONDITION_CARDS:
        add(card)

    # 4. 实机源卡牌库的已观察基础卡
    for card in OBSERVED_SOURCE_DECK_CARD_NAMES:
        add(card)

    return names


def normalize_card_name(ocr_text: str) -> str:
    """修正 OCR 误识变体，返回标准卡名。

    OCR 识别结果若命中 OCR_VARIANTS，回退到正解；
    否则原样返回（调用方据此查 hand_meta 判断）。
    """
    text = ocr_text.strip().replace(" ", "")
    return OCR_VARIANTS.get(text, text)


def is_good_condition_card(card_name: str) -> bool:
    """判断卡名是否属于好调类卡（用于 good_condition_card_count 计数）。

    简化判定：含「好調」字样或在 COMMON_GOOD_CONDITION_CARDS/KEY_CARDS 中。
    精确判定依赖 hand_meta 的 effect_summary，待数据完善后升级。
    """
    if not card_name:
        return False
    card = load_hif_catalog().skill_cards.get(card_name)
    if card is not None:
        return "good_condition" in card.tags
    if card_name in KEY_CARDS:
        return True
    if card_name in COMMON_GOOD_CONDITION_CARDS:
        return True
    return "好調" in card_name or "好调" in card_name
