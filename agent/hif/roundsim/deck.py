"""卡组容器与牌库动力学(roundsim-design.md §3.1 #1/#2/#4)。

- 卡解析:skill_card_effects.json 流派池(莉波感性路线池,键 NFKC 归一)按 名+档位 解析;
  池内查不到 → DeckPrecheckError(硬失败,§2 原则 4:显式失败优于静默近似)。
- 四区:山札 deck / 手牌 hand / 捨て札 grave / 除外 lost(+ hold)。
- 出牌去向:逐卡 playMovePositionType 分流(D1:lesson_once → Lost 不回流;其余 → Grave 重洗回流;
  七种去向含 Hand/DeckFirst/DeckLast/DeckRandom/Hold)。
- 抽牌:每回合开始发 turnStartDistribute、手牌上限 handLimit;山札不足时捨て札全部洗回
  山札、当回合续抽不推迟(D2)。
- 応援棒补足(D5):考试开始时技能卡 <22 → 按 ProduceCardRandomPool ratio 随机位置补「基本」卡。
"""

from __future__ import annotations

import random
import unicodedata
from pathlib import Path
from functools import lru_cache
from dataclasses import field, dataclass

from pydantic import BaseModel

from agent.hif.roundsim.spec import CardInDeck
from agent.hif.roundsim.settings import OUENBOU_BASIC_POOL, OUENBOU_DECK_TARGET

_EFFECTS_POOL_PATH = Path(__file__).resolve().parents[3] / "assets" / "data" / "hif" / "skill_card_effects.json"


class DeckPrecheckError(Exception):
    """卡组预检失败:含流派池外卡名或缺失效果建模(M2 扩展用)。"""


@dataclass(frozen=True, slots=True)
class CardSpec:
    """解析后的卡面数据(skill_card_effects.json 单档 tier 视图)。"""

    name: str
    tier: str
    card_id: str
    stamina: int
    force_stamina: int  # 固定体力消耗(お姉さんの感覚=6 等;消費軽減不可)
    cost_type: str | None
    cost_value: int | None
    effects: tuple[dict, ...]
    move_position: str
    is_lesson_once: bool
    play_trigger: str = ""  # 使用可门槛(e_trigger-none-parameter_buff_up-4 等;空=无门槛)
    category: str = ""
    rarity: str = ""
    plan: str = ""

    @property
    def total_stamina_cost(self) -> int:
        """出牌体力成本 = 基础 + 固定部分。"""
        return (self.stamina or 0) + (self.force_stamina or 0)


@dataclass(slots=True)
class CardInstance:
    """具体一张卡(卡组内同名多张各自独立,uid 区分)。"""

    uid: int
    spec: CardSpec

    @property
    def label(self) -> str:
        """trace 用显示名:档位非無印时附档位符号。"""
        suffix = "" if self.spec.tier == "無印" else self.spec.tier
        return f"{self.spec.name}{suffix}"


@lru_cache(maxsize=1)
def _load_pool() -> dict[str, dict]:
    """流派效果池({NFKC 归一基础名: 原始 dict});剔除偶像固有(与评分层同口径)。"""
    if not _EFFECTS_POOL_PATH.exists():
        raise DeckPrecheckError(f"skill_card_effects.json 不存在: {_EFFECTS_POOL_PATH}")
    import json

    raw = json.loads(_EFFECTS_POOL_PATH.read_text(encoding="utf-8"))
    return {
        unicodedata.normalize("NFKC", card["name_jp"]): card
        for card in raw.get("cards", [])
        if not card.get("is_idol_exclusive")
    }


def resolve_card(entry: CardInDeck) -> CardSpec:
    """CardInDeck(名+档位)→ CardSpec;池外卡名硬失败。"""
    pool = _load_pool()
    base = unicodedata.normalize("NFKC", entry.name)
    card = pool.get(base)
    if card is None:
        raise DeckPrecheckError(f"卡组预检失败:卡「{entry.name}」不在流派效果池(skill_card_effects.json)")
    tier = card.get("tiers", {}).get(entry.tier) or card.get("tiers", {}).get("無印")
    if tier is None:
        raise DeckPrecheckError(f"卡组预检失败:「{entry.name}」无档位 {entry.tier}")
    return CardSpec(
        name=card["name_jp"],
        tier=entry.tier,
        card_id=card.get("card_id", ""),
        stamina=tier.get("stamina") or 0,
        force_stamina=tier.get("force_stamina") or 0,
        cost_type=tier.get("cost_type"),
        cost_value=tier.get("cost_value"),
        effects=tuple(tier.get("effects") or []),
        move_position=card.get("move_position") or "Grave",
        is_lesson_once=bool(card.get("is_lesson_once")),
        play_trigger=card.get("play_trigger") or "",
        category=card.get("category", ""),
        rarity=card.get("rarity", ""),
        plan=card.get("plan", ""),
    )


class ZoneCounts(BaseModel):
    """trace 用牌库区计数(牌库动力学可视化)。"""

    deck: int = 0
    hand: int = 0
    grave: int = 0
    lost: int = 0
    hold: int = 0


@dataclass(slots=True)
class DeckZones:
    """四区牌库容器。所有随机操作(rng.shuffle / 随机位置插入)显式传 rng(§2 原则 5)。"""

    deck: list[CardInstance] = field(default_factory=list)
    hand: list[CardInstance] = field(default_factory=list)
    grave: list[CardInstance] = field(default_factory=list)
    lost: list[CardInstance] = field(default_factory=list)
    hold: list[CardInstance] = field(default_factory=list)
    reshuffle_count: int = 0

    # -- 构造 ---------------------------------------------------------------

    @classmethod
    def build(cls, entries: list[CardInDeck], rng: random.Random) -> DeckZones:
        """解析卡组并洗匀山札(考试开始)。"""
        instances = [CardInstance(uid=i, spec=resolve_card(entry)) for i, entry in enumerate(entries)]
        zones = cls(deck=instances)
        rng.shuffle(zones.deck)
        return zones

    def pad_ouenbou(self, rng: random.Random, target: int = OUENBOU_DECK_TARGET) -> int:
        """応援棒补足(D5):技能卡总数 < target 时按 ratio 随机位置补「基本」卡,返回补入张数。

        池:ProduceCardRandomPool parameter_buff(ステージング/ステップ/視線/思考/タイミングの基本,
        ratio 1:2:1:1:1)。补入卡不消失(随既有卡走 Grave/Lost 循环)。
        """
        total = len(self.deck) + len(self.hand) + len(self.grave) + len(self.lost) + len(self.hold)
        names = [name for name, _w in OUENBOU_BASIC_POOL]
        weights = [w for _n, w in OUENBOU_BASIC_POOL]
        padded = 0
        while total + padded < target:
            picked = rng.choices(names, weights=weights, k=1)[0]
            instance = CardInstance(uid=100000 + padded, spec=resolve_card(CardInDeck(name=picked)))
            position = rng.randrange(len(self.deck) + 1)
            self.deck.insert(position, instance)
            padded += 1
        return padded

    # -- 抽牌与弃牌 ----------------------------------------------------------

    def draw(self, count: int, hand_limit: int, rng: random.Random) -> list[str]:
        """抽牌:手牌补到上限;山札空时捨て札全部洗回(D2:当回合续抽不推迟)。

        返回本张实际抽到的卡 label(供 trace)。
        """
        drawn: list[str] = []
        for _ in range(count):
            if len(self.hand) >= hand_limit:
                break
            if not self.deck:
                if not self.grave:
                    break  # 山札与捨て札俱空(过度压缩):无牌可抽
                self.deck = self.grave
                self.grave = []
                rng.shuffle(self.deck)
                self.reshuffle_count += 1
            self.hand.append(self.deck.pop())
            drawn.append(self.hand[-1].label)
        return drawn

    def discard_hand(self) -> list[str]:
        """回合结束:手牌全弃进捨て札(Hold 保留的卡除外,M3/D2)。"""
        discarded = [card.label for card in self.hand]
        self.grave.extend(self.hand)
        self.hand = []
        return discarded

    def move_played(self, card: CardInstance, rng: random.Random) -> str:
        """出牌后按卡面 playMovePositionType 分流(D1),返回去向名。先移出手牌再入区。"""
        if card in self.hand:
            self.hand.remove(card)
        dest = card.spec.move_position
        if dest == "Lost":
            self.lost.append(card)
        elif dest == "Hold":
            self.hold.append(card)
        elif dest == "Hand":
            self.hand.append(card)
        elif dest == "DeckFirst":
            self.deck.insert(0, card)
        elif dest == "DeckLast":
            self.deck.append(card)
        elif dest == "DeckRandom":
            self.deck.insert(rng.randrange(len(self.deck) + 1), card)
        else:  # Grave 及未知值兜底(池内 19 张循环卡全为 Grave)
            self.grave.append(card)
            dest = "Grave"
        return dest

    def counts(self) -> ZoneCounts:
        return ZoneCounts(
            deck=len(self.deck),
            hand=len(self.hand),
            grave=len(self.grave),
            lost=len(self.lost),
            hold=len(self.hold),
        )
