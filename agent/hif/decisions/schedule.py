"""HIF 日程推进的页面级选择逻辑（公開レッスン选卡、授業选项分类）。

調研结论（seesaawiki H.I.F 页，2026-08-15）：
- 公開レッスンの SP 是该日到来时随机决定，玩家不可选，唯一决策是选属性。
- 授業选项是固定可枚举表（選択して獲得 / セレクトチェンジ / トラブル追加），
  叙事对话事件文案无公开数据，靠排除法兜底。
"""

from __future__ import annotations

from typing import Iterable

CLASS_OPTION_TROUBLE = "トラブル"
CLASS_OPTION_ACQUIRE = ("選択して獲得", "選んで獲得")
CLASS_OPTION_CHANGE = ("セレクトチェンジ", "チェンジ")


def classify_class_option(text: str) -> str:
    """授業选项文本分类：acquire / change / trouble / unknown。

    选项行通常只有叙事文案（「余裕です！」类，无固定表），
    标记类文本（トラブル追加 / チェンジ / 獲得）出现在选项行小字或预览页。
    """

    if CLASS_OPTION_TROUBLE in text:
        return "trouble"
    if any(marker in text for marker in CLASS_OPTION_ACQUIRE):
        return "acquire"
    if any(marker in text for marker in CLASS_OPTION_CHANGE):
        return "change"
    return "unknown"


def choose_public_lesson(cards: Iterable[dict], attr_priority: tuple[str, ...]) -> dict | None:
    """按属性优先序选公開レッスン候选卡；SP 与否当日随机不可选，不参与决策。"""

    by_attr = {card["name"]: card for card in cards}
    for attr in attr_priority:
        if attr in by_attr:
            return by_attr[attr]
    return None
