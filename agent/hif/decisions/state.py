"""出牌决策数据结构（PlayDecision 域）。

从原 Maa-gakumas-bot 仓库 app/strategy/base.py 抽取并瘦身：
- 仅保留 PlayDecision 出牌域所需结构（ExamState/HandSummary/CardAction 等）
- 去除对老仓库数据库层（app.models.*）与 pydantic 的依赖，改纯 dataclass
- 去除其余决策域（Acquisition/Schedule/Meta）占位结构，保持出牌域聚焦

设计原则：本模块零 maafw 依赖，只含纯数据结构，可离线单测。
字段由适配层（ExamStateReader，从画面 OCR/YOLO 读出）填充后喂给 PlayDecision.decide()。
"""

from __future__ import annotations

from enum import Enum
from dataclasses import field, dataclass


class ExamRound(str, Enum):
    """試験/ラウンド类型。本规格首版仅落地本戦两个ラウンド；選抜試験预留。"""

    HONSEN_R1 = "honisen_r1"  # 本戦ラウンド1（9 ターン）
    HONSEN_R2 = "honsen_r2"  # 本戦ラウンド2（12 ターン）
    # 预留：選抜試験，后续规格接入自动导航。
    SELECTION_1 = "selection_1"
    SELECTION_2 = "selection_2"
    SELECTION_3 = "selection_3"


class ActionKind(str, Enum):
    """出牌决策的动作类型。"""

    PLAY_CARD = "play_card"
    SWAP_HAND = "swap_hand"
    DRAW = "draw"
    USE_P_DRINK = "use_p_drink"


@dataclass(slots=True)
class HandSummary:
    """手牌摘要，由识别层从画面识别后填充（PlayDecision 输入）。

    ガラクタロード策略只关心 3 张关键卡的有无，以及好调卡计数与抽换手段可用性，
    不关心其他卡的具体名字。适配层通过 OCR 读卡名后查表填充本结构。
    """

    has_shizen_no_miryoku: bool  # 是否持有「自然体の魅力」（终结技卡）
    has_oneesan_no_kankaku: bool  # 是否持有「お姉さんの感覚」（循环启动卡）
    has_kokuminteki_idol: bool  # 是否持有「国民的アイドル」（好调铺垫卡）
    good_condition_card_count: int  # 好调卡张数（凑 P アイテム再抽牌 + 抬高自然体加成）
    swap_hand_available: bool  # 手札交換是否可用
    draw_available: bool  # ドロー追加是否可用


@dataclass(slots=True)
class ParamSet:
    """Vo/Da/Vi 三维参数值（横切参数，由识别层填充，用于参数感知告警）。"""

    vocal: int = 0
    dance: int = 0
    visual: int = 0


@dataclass(slots=True)
class JudgeThreshold:
    """单一流的审查基准 △〇 閾値。△ 以下拖累他参得分。"""

    delta: int = 0  # △ 閾値
    circle: int = 0  # 〇 閾値


@dataclass(slots=True)
class JudgeThresholds:
    """三个流的审查基准。姫崎莉波 バランス：流1/2/3 = Vi/Da/Vo。"""

    flow1: JudgeThreshold = field(default_factory=JudgeThreshold)
    flow2: JudgeThreshold = field(default_factory=JudgeThreshold)
    flow3: JudgeThreshold = field(default_factory=JudgeThreshold)


@dataclass(slots=True)
class ExamState:
    """单回合决策输入（PlayDecision）。字段由适配层从画面填充。

    所有字段均可单测构造，决策层据此判定本ターン动作。
    """

    round: ExamRound
    turn: int
    total_turns: int
    current_flow: str  # 当前流 Vo/Da/Vi
    good_condition_turns: int  # 当前好调ターン数
    focus: int  # 当前集中值
    stamina: int  # 当前体力
    hand: HandSummary
    reprise_count: int  # 已发动再演次数（ガラクタロード上限 4）
    cards_played: int  # 本レッスン已出牌数
    deck_size: int  # 山札剩余张数（防 HIF 応援棒混入）
    oneesan_used: bool  # お姉さんの感覚本レッスン已用
    natural_finisher_used: bool  # 自然体の魅力本レッスン已用
    available_p_drinks: list[str]
    # 横切参数：识别层填充后用于参数感知告警，默认空值不破坏旧构造。
    params: ParamSet = field(default_factory=ParamSet)
    judge_thresholds: JudgeThresholds = field(default_factory=JudgeThresholds)
    # 局内得分与倍率必须来自本局同帧的校准 ROI；缺失时保持 None，不用零值伪造。
    current_score: int | None = None
    stage_multiplier: float | None = None


@dataclass(slots=True)
class CardAction:
    """PlayDecision 输出：本ターン出牌动作。

    kind=PLAY_CARD 时 target_card 为卡名（终结技/铺垫卡）或 None（默认出好调卡，精确选卡留执行层）。
    reason 为人类可读决策理由，便于日志与调试。
    """

    kind: ActionKind
    target_card: str | None = None
    reason: str = ""
