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
    """出牌决策的动作类型。実機 Round 界面唯一独立按钮是 SKIP + 底部饮料栏
    (roundsim-design §3.3);旧仓库抽象的 DRAW/SWAP_HAND 是失真(卡效果 tag,非按钮),
    保留枚举值以兼容存量决策日志,新策略禁止返回。"""

    PLAY_CARD = "play_card"
    SKIP = "skip"
    SWAP_HAND = "swap_hand"  # 已废弃:実機无「手札交換」独立按钮(roundsim-design §6.3 修复 3)
    DRAW = "draw"  # 已废弃:実機无「ドロー」独立按钮(是卡效果 tag action:draw)
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
    # 実機 2026-08-15 接线：OCR 读到的卡名（决策日志/实证用，空=未读到）
    card_names: tuple[str, ...] = ()


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


@dataclass(slots=True)
class CardAction:
    """PlayDecision 输出：本ターン出牌动作。

    kind=PLAY_CARD 时 target_card 为卡名（终结技/铺垫卡）或 None（默认出好调卡，精确选卡留执行层）。
    reason 为人类可读决策理由，便于日志与调试。
    """

    kind: ActionKind
    target_card: str | None = None
    reason: str = ""
