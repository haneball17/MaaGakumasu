"""Interval 商店流读取与购买决策（issue #6 骨架 → #22 名称级策略，grill 定案 2026-08-24）。

実機 UI 结构（forensic-report-20260823 §6，第二局手动接管实证）：
混合商品网格 2x4=8 件（技能卡+饮料道具，价格 P30-100 白椭圆标签）——
**无分类 tab**（issue 原「4 tab」假设不成立，底部 4 圆钮=饮料持有槽）。
购买链：点商品(选中描边)→交換する(~350,1075)→交換確認弹窗(P 点变化预览
380→350/×キャンセル (211,1156)/交換 (522,1157))→商品「交換済み」标记。

购买策略（grill 定案 2026-08-24，名称级）：
- 商品匹配走**名称级**（点开详情面板读名，非价格档启发）；读取件（详情面板
  名称 OCR）是独立識別件，実機接线归 #24——策略层只消费 ``IntervalProduct.name``。
- 默认 wanted = P3 社区共识优先级：补山札到 22 枚 → センブリソーダ → ブーストエキス。
- budget 语义为**留额后可用上限**：可花 = min(budget 帽, P 点余额 - reserve)，
  reserve 默认 100P（特別指導 Round2 竞争用途，mechanics.md P3/H12）。
- 识别失败（商品名 None / P 点余额 None）保守退出：不购买、不猜测点击。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# P3 共识默认优先表（名称级；补山札条件项见 PurchasePolicy.restock_target）
WANTED_P3_CONSENSUS: tuple[str, ...] = ("センブリソーダ", "ブーストエキス")


@dataclass(frozen=True, slots=True)
class IntervalProduct:
    """网格商品行（名称来自详情面板读取件；类目由读取件按名称 join 数据源填）。"""

    name: str | None = None  # 商品名（详情面板 OCR；None=未识别/未读取）
    is_card: bool | None = None  # True=技能卡（补山札类目）；None=类目未知
    price: int | None = None  # P 点价格（OCR 数字解析失败=None）
    row: int = 0  # 网格行 0/1
    col: int = 0  # 网格列 0-3


@dataclass(frozen=True, slots=True)
class IntervalShopState:
    """Interval 商店快照（IntervalAuto 到达时读取落盘）。"""

    p_points: int | None = None  # P 点余额（右上 [300,95,160,55] 数字）
    products: tuple[IntervalProduct, ...] = ()
    deck_size: int | None = None  # 山札枚数（対局牌堆读取件 session 传递；名称级补山札条件输入）
    ocr_raw: tuple[str, ...] = ()  # 商品区全文 token（审计用）


@dataclass(frozen=True, slots=True)
class PurchasePolicy:
    """购买策略参数（grill 定案 2026-08-24：名称级 + P3 共识默认 + 留额语义）。

    - ``mode``：no_purchase（保守浏览）| buy_list（名称级购买）。
    - ``budget``：可花上限帽（P 点）；0 = 不额外设帽（仅受余额-留额约束）。
    - ``reserve``：特別指導留额（默认 100P），可花 = 余额 - reserve 再 min budget。
    - ``restock_target``：山札补到 N 枚；deck_size < target 时技能卡类目最优先。
    - ``wanted``：名称优先表（默认 P3 共识），名称级子串匹配（归一化后）。
    """

    mode: str = "no_purchase"
    budget: int = 0
    reserve: int = 100
    restock_target: int = 22
    wanted: tuple[str, ...] = WANTED_P3_CONSENSUS


def parse_p_points(text: str) -> int | None:
    """OCR 文本解析 P 点余额（纯数字，容忍千分位逗号与噪声字符）。"""
    cleaned = text.replace(",", "").strip()
    return int(cleaned) if cleaned.isdigit() else None


def normalize_shop_name(name: str) -> str:
    """商品名归一化（OCR 变体纪律）：去空白与长音符 ー（ターン内/タン内类丢音变体）。"""
    return re.sub(r"[\sー]+", "", name)


def match_wanted(name: str | None, wanted: tuple[str, ...]) -> int | None:
    """商品名对 wanted 优先表做归一化子串匹配，返回优先序号（0 最高）；未命中 None。"""
    if not name:
        return None
    normalized = normalize_shop_name(name)
    for idx, word in enumerate(wanted):
        if word and normalize_shop_name(word) in normalized:
            return idx
    return None


def decide_purchase(state: IntervalShopState, policy: PurchasePolicy) -> tuple[IntervalProduct, ...]:
    """名称级购买决策（纯函数）：返回按执行序要购买的商品。

    优先级（P3 共识）：①deck_size < restock_target 时的技能卡（补到 target 张为限）
    ②wanted 名称命中（按表序）③其余不买。逐件扣减可花额度，买不起跳过继续。

    保守退出（恒空返回，不猜测点击）：mode != buy_list；余额/商品未读出；
    商品名 None（识别失败）逐件跳过——名称级语义下无名商品不可决策。
    """
    if policy.mode != "buy_list" or not state.products:
        return ()
    if state.p_points is None:
        return ()  # 余额读不到=快照不完整，保守退出
    avail = max(0, state.p_points - policy.reserve)
    if policy.budget > 0:
        avail = min(avail, policy.budget)
    if avail <= 0:
        return ()

    def restock_quota() -> int:
        """补山札缺口张数（deck 未读出/已达标 → 0，不触发类目优先）。"""
        if state.deck_size is None or state.deck_size >= policy.restock_target:
            return 0
        return policy.restock_target - state.deck_size

    quota = restock_quota()
    plan: list[IntervalProduct] = []
    spent = 0

    def try_buy(product: IntervalProduct) -> None:
        nonlocal spent
        if product.price is None or product.price <= 0:
            return
        if product.price > avail - spent:
            return  # 余额不足跳过（后面可能有更便宜的命中件）
        plan.append(product)
        spent += product.price

    restock_pool = sorted(
        (p for p in state.products if quota > 0 and p.is_card and p.name),
        key=lambda p: (p.price is None, p.price or 0),  # 便宜卡优先，同预算多补一张
    )
    for product in restock_pool:
        if len([p for p in plan if p.is_card]) >= quota:
            break
        try_buy(product)

    wanted_pool = sorted(
        (p for p in state.products if p.name and match_wanted(p.name, policy.wanted) is not None),
        key=lambda p: (match_wanted(p.name, policy.wanted), p.price is None, p.price or 0),
    )
    for product in wanted_pool:
        if product not in plan:
            try_buy(product)
    return tuple(plan)
