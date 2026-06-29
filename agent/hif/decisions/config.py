"""出牌决策配置（角色参数，L4 配置层）。

从原 Maa-gakumas-bot 仓库 app/schemas/strategy.py 抽取并瘦身：
- 去除 pydantic BaseModel（新仓库无 pydantic 依赖），改纯 dataclass
- 去除数据库持久化字段（CharacterRef.id/plugin 等插件注册字段）
- 仅保留ガラクタロード再演压缩流实际读取的参数字段

配置可通过 ProfilePayload.default() 取默认值，或从 JSON 加载自定义角色参数。
"""

from __future__ import annotations

from dataclasses import field, dataclass


@dataclass(slots=True)
class HonisenConfig:
    """本戦相关参数。"""

    deck_target: int = 22  # 技能卡目标张数（防 HIF 応援棒混入基本卡）
    star_threshold_r1: int = 8  # ラウンド1 目标スター性
    star_threshold_r2: int = 9  # ラウンド2 開始スター性（優勝门槛）
    stamina_critical: int = 20  # 体力告急阈值，低于则考虑使用 P ドリンク


@dataclass(slots=True)
class RepriseConfig:
    """再演机制相关参数（ガラクタロード固有，但以通用字段命名供他角色复用）。"""

    max: int = 4  # 再演发动上限
    good_cond_gate: int = 4  # お姉さんの感覚 使用所需的好调ターン门槛
    finisher_gate: int = 12  # 自然体の魅力 使用所需的好调ターン门槛
    finisher_window: int = 0  # 收尾窗口ターン数；0=好调够即收尾（不限制）


@dataclass(slots=True)
class ProfilePayload:
    """ガラクタロード姫崎莉波角色配置（决策大脑读取的参数集）。

    所有决策阈值集中在此，便于通过配置热更新或为新角色复用启发式骨架。
    角色级属性 plan/recommend_effect/flows 决定参数感知告警的方向。
    """

    plan: str = "sense"  # センス/ロジック/アノマリー
    recommend_effect: str = "集中"  # 好调/集中/好印象/やる気/全力/強気
    flows: list[str] = field(default_factory=lambda: ["Vi", "Da", "Vo"])  # 流1/2/3
    honisen: HonisenConfig = field(default_factory=HonisenConfig)
    reprise: RepriseConfig = field(default_factory=RepriseConfig)
    p_drink_priority: list[str] = field(default_factory=list)
    focus_r1: bool = True  # ラウンド1 注力策略（冲 92.5 万评价点）

    @classmethod
    def default(cls) -> ProfilePayload:
        """ガラクタロード姫崎莉波（センス/集中/バランス）默认配置。"""
        return cls(
            plan="sense",
            recommend_effect="集中",
            flows=["Vi", "Da", "Vo"],
            honisen=HonisenConfig(),
            reprise=RepriseConfig(),
            p_drink_priority=["初星黒酢", "パワフル漢方ドリンク"],
            focus_r1=True,
        )
