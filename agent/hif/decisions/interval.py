"""Interval 商店流读取与购买决策（issue #6，2026-08-23 取证轮输入）。

実機 UI 结构（forensic-report-20260823 §6，第二局手动接管实证）：
混合商品网格 2x4=8 件（技能卡+饮料道具，价格 P30-100 白椭圆标签）——
**无分类 tab**（issue 原「4 tab」假设不成立，底部 4 圆钮=饮料持有槽）。
购买链：点商品(选中描边)→交換する(~350,1075)→交換確認弹窗(P 点变化预览
380→350/×キャンセル (211,1156)/交換 (522,1157))→商品「交換済み」标记。

购买策略默认保守（no_purchase，goal 共识 5）：第一版可浏览不购买——
读取件落盘供决策审计（decision-audit 缺口 5），策略待第二轮 grill 定案后
在 ``PurchasePolicy`` 扩展，管线链路无需再动。
"""

from __future__ import annotations

from dataclasses import field, dataclass


@dataclass(frozen=True, slots=True)
class IntervalProduct:
    """网格商品行（第一版从价格标签 OCR 读取，名称需点开详情面板——留 grill 后）。"""

    price: int | None  # P 点价格（OCR 数字解析失败=None）
    row: int  # 网格行 0/1
    col: int  # 网格列 0-3


@dataclass(frozen=True, slots=True)
class IntervalShopState:
    """Interval 商店快照（IntervalAuto 到达时读取落盘）。"""

    p_points: int | None = None  # P 点余额（右上 [300,95,160,55] 数字）
    products: tuple[IntervalProduct, ...] = ()
    ocr_raw: tuple[str, ...] = ()  # 商品区全文 token（审计用）


@dataclass(frozen=True, slots=True)
class PurchasePolicy:
    """购买策略参数（grill 定案前只有保守档）。"""

    mode: str = "no_purchase"  # no_purchase | buy_list(grill 后扩展)
    budget: int = 0  # 可用 P 点上限（buy 档生效）
    wanted: tuple[str, ...] = field(default_factory=tuple)  # 商品名/类型优先表


def parse_p_points(text: str) -> int | None:
    """OCR 文本解析 P 点余额（纯数字，容忍千分位逗号与噪声字符）。"""
    cleaned = text.replace(",", "").strip()
    return int(cleaned) if cleaned.isdigit() else None


def decide_purchase(state: IntervalShopState, policy: PurchasePolicy) -> tuple[IntervalProduct, ...]:
    """返回本轮要购买的商品（按序执行点商品→交換する→確認→交換）。

    保守档恒空（可浏览不购买）；grill 定案后按 wanted/budget 扩展。
    """
    if policy.mode != "buy_list" or not state.products:
        return ()
    affordable = tuple(
        p for p in state.products if p.price is not None and 0 < p.price <= policy.budget
    )
    return affordable
