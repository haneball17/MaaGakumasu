"""trace JSON 格式(回合事件流 schema,roundsim-design.md §10 M1「一次定死」)。

一局 = TraceDocument;每回合 = TurnTrace(手牌快照 → 决策 → 效果链 → S1 得分明细 →
状态变化 → 牌库区演变)。schema_version 只增不改字段语义;前端三视图(M-UI)按此渲染。

向后兼容的空档:M2 填 effects/score_details,M3 填 triggers——M1 先定型字段,
skip-only 局 effects=[]、score 各分量为 0,前端可据此渲染骨架。
"""

from __future__ import annotations

from pydantic import Field, BaseModel

from agent.hif.roundsim.deck import ZoneCounts

TRACE_SCHEMA_VERSION = 1


class StateSnapshot(BaseModel):
    """回合内状态快照(决策前后各留一份在 TurnTrace)。"""

    stamina: int = 0
    energy: int = 0
    good_condition_turns: int = 0
    excellent_condition_turns: int = 0
    focus: int = 0
    cards_played: int = 0  # 本考试累计出牌数(自然体の魅力 +N/张 的基数)
    usable_left: int = 0  # 本回合剩余使用数


class ActionTrace(BaseModel):
    """本回合动作(裁判-选手接口 §3.3:PLAY_CARD / SKIP / USE_P_DRINK)。

    使用数追加可在一回合内多次出牌:action 记首次决策,plays 记全部出牌序列。
    """

    kind: str = "skip"  # play_card / skip / use_p_drink
    card: str | None = None  # PLAY_CARD 时的卡名(含档位)
    reason: str = ""  # 策略给出的决策理由(选手侧,裁判原样落盘)
    illegal: bool = False  # 预检失败(非法动作):裁判拒绝执行并记违约
    plays: list[str] = Field(default_factory=list)  # 本回合全部出牌 label 序列(含追加発動)


class EffectTrace(BaseModel):
    """单条效果执行记录(M2 效果引擎产出;tag = skill_card_effects 语义标签)。"""

    tag: str
    note: str = ""
    detail: str = ""  # 人类可读明细,如「好調 +4T」「使用数 +1」


class TriggerTrace(BaseModel):
    """trigger 触发记录(M3:P item「憧れ続けた輝き」等计数间隔+状态门槛类)。"""

    source: str  # 触发源(道具名)
    note: str = ""


class ScoreDetail(BaseModel):
    """S1 得分明细分解(§8.3 单局回放视图:「(23+4×2.0)×(1.5+0.6)=65.1」)。"""

    base_value: int = 0  # 卡基础值 + 附加(好印象/やる気/使用数加成)
    focus_value: int = 0  # 集中加算(池 × 档位倍率,一次性)
    state_mult: float = 1.0  # 状態倍率(好調 1.5;絶好調 +0.1×好調層 相加)
    param_mult: float = 0.0  # 属性有效参数/100(流行属性)
    score_up_mult: float = 1.0  # 得分上升量(1+n/100)
    bad_mult: float = 1.0  # 不調修正(A7:默认无减衰=1.0)
    points: int = 0  # 本张最终得分(逐级 ceil 后)
    formula: str = ""  # 展开式文本


class TurnTrace(BaseModel):
    """单回合事件流。"""

    turn: int
    flow: str  # 本回合流行属性 Vo/Da/Vi
    hand_before: list[str] = Field(default_factory=list)  # 发牌后手牌(label 列表)
    drew: list[str] = Field(default_factory=list)  # 本回合分发到的牌
    action: ActionTrace = Field(default_factory=ActionTrace)
    effects: list[EffectTrace] = Field(default_factory=list)
    triggers: list[TriggerTrace] = Field(default_factory=list)
    score: ScoreDetail = Field(default_factory=ScoreDetail)  # 主出牌得分(M1 为空)
    extra_scores: list[ScoreDetail] = Field(default_factory=list)  # 再演/追加発動等次次得分
    turn_score: int = 0  # 本回合总得分(主 + extra + 好印象结算,M2)
    state_after: StateSnapshot = Field(default_factory=StateSnapshot)
    zones: ZoneCounts = Field(default_factory=ZoneCounts)
    reshuffled: bool = False  # 本回合是否发生捨て札重洗


class OpponentRoll(BaseModel):
    """対手抽样落点(A1:uniform 独立)。"""

    name: str
    score: int


class FinalTrace(BaseModel):
    """终局:总分、対手、顺位。"""

    total_score: int = 0
    final_state: StateSnapshot = Field(default_factory=StateSnapshot)
    zones: ZoneCounts = Field(default_factory=ZoneCounts)
    reshuffle_count: int = 0
    opponents: list[OpponentRoll] = Field(default_factory=list)
    rank: int = 0  # 1 = 第 1 位(3 名含玩家)
    won: bool = False  # 優勝(R1 单段近似:rank==1)


class SpecDigest(BaseModel):
    """spec 摘要(不落全量卡组,前端回放只需规模与模式)。"""

    preset: str = ""
    turns: int = 0
    deck_size: int = 0
    popular_mode: str = ""
    ouenbou: bool = False
    idol_exclusive: str | None = None
    note: str = ""


class TraceDocument(BaseModel):
    """一局考试的完整事件流(前端/校准报告/归档消费)。"""

    schema_version: int = TRACE_SCHEMA_VERSION
    seed: int = 0
    strategy: str = "skip-only"  # 策略名(选手侧标识)
    spec_digest: SpecDigest = Field(default_factory=SpecDigest)
    turns: list[TurnTrace] = Field(default_factory=list)
    final: FinalTrace = Field(default_factory=FinalTrace)

    def turn_scores(self) -> list[int]:
        return [t.turn_score for t in self.turns]
