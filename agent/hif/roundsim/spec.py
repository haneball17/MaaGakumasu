"""ScenarioSpec:模拟器输入模型单一真源(roundsim-design.md §4)。

pydantic 定义于 Python 侧,导出 JSON Schema 供前端对齐 + 契约测试锁定(§4.1);
spec = preset ⊕ overrides:用户改的字段覆盖默认,未改字段继承预设(深合并,列表整体替换)。

三层结构(§4.2):
- scenario   卡组/初始状态/P item/流行模式/固定首手 —— 全部可配
- exam_settings 结构参数(默认官方值,见 settings.py)
- opponent   対手分数区间(默认 produce_008 双対手,§3.4)

莉波预设的构筑/三围为**重构近似**:実機 observed case(rinami_garakuta_road_20260709)
只记录了 deck_size=20 与三围快照,未落盘逐卡清单——核心五卡(お姉さんの感覚/自然体の魅力/
国民的アイドル/シュプレヒコール/始まりの合図)有実機与策略层证据,其余 15 张按
莉波好調流(P2 定番:好調付与 + 抽牌 + 集中资源)从流派池补足。待実機逐卡取证后校正,
此处不假装是逐卡实录(零拟合:数据缺失就声明缺失)。
"""

from __future__ import annotations

import copy
import unicodedata
from typing import Literal, Annotated

from pydantic import Field, BaseModel, ConfigDict

from agent.hif.roundsim.settings import R1_TURNS, R2_TURNS, RINAMI_CRITERIA, ExamSettings

# 所有 spec 模型禁止未知字段:override 拼写错误必须报错,不静默吞(§2 原则 4)。
_STRICT = ConfigDict(extra="forbid")

Flow = Literal["Vo", "Da", "Vi"]
TierKey = Literal["無印", "+", "++", "+++"]
PopularModeKind = Literal["fixed", "j3_random"]


class CardInDeck(BaseModel):
    """卡组条目:卡名 + 档位(§4.2 scenario.deck)。"""

    model_config = _STRICT

    name: str
    tier: TierKey = "無印"


class ParamsSnapshot(BaseModel):
    """三围有效参数口径(U2/A9:含親愛度/HIFボーナス换算后的実機画面值,成分分解不做)。"""

    model_config = _STRICT

    vocal: int = 0
    dance: int = 0
    visual: int = 0


class InitialExamState(BaseModel):
    """考试初始状态(§3.5:R1 默认 = 実機观察值;R2 実機未取证走 A2 假设)。"""

    model_config = _STRICT

    stamina: int = 28  # R1 実機:体力 28(round1_initial)
    max_stamina: int = 35  # observed case initial_state.max_stamina
    energy: int = 0  # 元気(体力优先支付缓冲,R2)
    params: ParamsSnapshot = Field(default_factory=ParamsSnapshot)
    p_drinks: dict[str, int] = Field(default_factory=dict)  # P 饮料名 → 数量(A3 跨 Round 持有)
    good_condition_turns: int = 0  # 初期好調ターン(R1 実機 = 6)
    excellent_condition_turns: int = 0  # 初期絶好調ターン
    focus: int = 0  # 初期集中値池(R1 実機 = 6)


class PItems(BaseModel):
    """P アイテム开关(§4.2:応援棒 R2 固定 on;偶像专属道具随偶像卡挂载,H13)。"""

    model_config = _STRICT

    ouenbou: bool = False  # HIF 応援棒(R1 后強制配布,D5:技能卡 <22 补基本卡)
    idol_exclusive: str | None = None  # 偶像专属道具名,如「憧れ続けた輝き」;None=不携带


class FixedPopular(BaseModel):
    """流行序列固定注入(A/B 控制变量用,§3.1 #5)。turns 长度须等于 exam_settings.turns。"""

    model_config = _STRICT

    mode: Literal["fixed"] = "fixed"
    turns: list[Flow]


class J3RandomPopular(BaseModel):
    """J3 官方规则:末 3 回合固定 3→2→1 位、末回合必 1 位、首回合自定权重、中段按比率随机。

    criteria:属性 → 審査基準值(produce_008 davi-01 = Da1960/Vi1307/Vo1089)。
    first_weights:首回合属性权重(A4 假设:官方 HIF 概率表不存在,缺省按 criteria 比率)。
    """

    model_config = _STRICT

    mode: Literal["j3_random"] = "j3_random"
    criteria: dict[str, int] = Field(default_factory=lambda: dict(RINAMI_CRITERIA))
    first_weights: dict[str, float] | None = None


PopularMode = Annotated[FixedPopular | J3RandomPopular, Field(discriminator="mode")]


class OpponentSpec(BaseModel):
    """対手:静态分数,每局 uniform(score_min, score_max) 独立抽样(A1 假设,§3.4)。"""

    model_config = _STRICT

    name: str
    score_min: int
    score_max: int


class Scenario(BaseModel):
    """scenario 层(§4.2)。first_hand:固定首手注入(复现実機首手/逐局校验用)。"""

    model_config = _STRICT

    deck: list[CardInDeck]
    initial: InitialExamState = Field(default_factory=InitialExamState)
    p_items: PItems = Field(default_factory=PItems)
    popular_mode: PopularMode
    first_hand: list[str] | None = None


class ScenarioSpec(BaseModel):
    """模拟器输入顶层模型 = scenario + exam_settings + opponent 三层。"""

    model_config = _STRICT

    scenario: Scenario
    exam_settings: ExamSettings = Field(default_factory=ExamSettings)
    opponent: list[OpponentSpec] = Field(default_factory=list)
    note: str = ""  # 数据来源/重构说明,随 trace 与报告输出


# ---------------------------------------------------------------------------
# 莉波実機 20 张构筑(重构近似,见模块 docstring)
# ---------------------------------------------------------------------------

RINAMI_DECK_20: list[CardInDeck] = [
    # 核心引擎(実機/策略层证据:play.py 固有卡 + observed case)
    CardInDeck(name="お姉さんの感覚"),  # 再演驱动(R4:好調≥4 使用可,好調4T+回体+再演×4)
    CardInDeck(name="自然体の魅力"),  # 终结技(好調≥12 使用可,体力の800%分パラメータ)
    CardInDeck(name="国民的アイドル"),  # 好調铺垫(もう1回発動 + 使用数追加;好調1層コスト)
    CardInDeck(name="始まりの合図"),  # 好調5T(observed case day6 変卡目标)
    # 集中/好調资源循环(莉波池补足,P2 定番流)
    CardInDeck(name="シュプレヒコール"),  # 集中3コスト:参数+6 好調2T 使用数+1(R2 预设升+档)
    CardInDeck(name="スポットライト"),
    CardInDeck(name="スポットライト"),  # 元気+7 好調5T 次ターン2枚引(Grave 循环卡)
    CardInDeck(name="深呼吸"),
    CardInDeck(name="深呼吸"),  # 集中+好調(Grave 循环卡)
    CardInDeck(name="ペース配分"),  # 絶好調時使用可:参数+3 集中+3 好調3T
    CardInDeck(name="軽い足取り"),  # 参数+6 好調2T
    CardInDeck(name="パンプアップ"),
    CardInDeck(name="アドリブ"),
    CardInDeck(name="祝福"),
    CardInDeck(name="大声援"),  # 好調+元気
    CardInDeck(name="振る舞いの基本"),  # 元気+1 好調2T(基本卡,Grave)
    CardInDeck(name="視線の基本"),
    CardInDeck(name="視線の基本"),  # 元気+5 好調2T
    CardInDeck(name="ステップの基本"),  # 参数+6 好調2T
    CardInDeck(name="タイミングの基本"),  # 元気+5 絶好調1T
]


def _rinami_initial(good: int, focus: int, stamina: int) -> InitialExamState:
    """莉波三围快照(observed case:Day5 公開レッスン后 Vo1116/Da2920/Vi2175)。"""
    return InitialExamState(
        stamina=stamina,
        good_condition_turns=good,
        focus=focus,
        params=ParamsSnapshot(vocal=1116, dance=2920, visual=2175),
    )


def _rinami_deck_r2() -> list[CardInDeck]:
    """R2 构筑 = R1 同名 20 张(D3:考试结束卡组复原),シュプレヒコール 升 + 档。

    依据 observed case interval_customize:実機对 シュプレヒコール+ 执行「集中コスト値-」
    (無印 3 → + 档 2)。Interval 购入的 2 张(20→22)実機未记录,不虚构——
    由 応援棒 补足至 22(D5 路径)。
    """
    deck = [card.model_copy() for card in RINAMI_DECK_20]
    for card in deck:
        if unicodedata.normalize("NFKC", card.name) == "シュプレヒコール":
            card.tier = "+"
            break
    return deck


_PRESET_NOTE = (
    "莉波ガラクタロード重构预设:核心五卡有実機证据(observed case/play.py),"
    "其余 15 张按莉波好調流从流派池补足;三围 Vo1116/Da2920/Vi2175 为実機快照。"
    "R1 初始 体力28/好調6T/集中6 = 実機观察;対手区间 = produce_008 dump(H6)。"
)

_PRESET_NOTE_R2 = _PRESET_NOTE + " R2 初始状态実機未取证(A2:buff 清零,体力 = interval 実機值 34)。"


PRESETS: dict[str, ScenarioSpec] = {
    "hif_r1_rinami": ScenarioSpec(
        scenario=Scenario(
            deck=list(RINAMI_DECK_20),
            initial=_rinami_initial(good=6, focus=6, stamina=28),
            p_items=PItems(ouenbou=False, idol_exclusive="憧れ続けた輝き"),
            popular_mode=J3RandomPopular(),
        ),
        exam_settings=ExamSettings(turns=R1_TURNS),
        opponent=[
            OpponentSpec(name="十王星南", score_min=403161, score_max=409161),
            OpponentSpec(name="有村麻央", score_min=301182, score_max=316182),
        ],
        note=_PRESET_NOTE,
    ),
    "hif_r2_rinami": ScenarioSpec(
        scenario=Scenario(
            deck=_rinami_deck_r2(),
            initial=_rinami_initial(good=0, focus=0, stamina=34),
            p_items=PItems(ouenbou=True, idol_exclusive="憧れ続けた輝き"),
            popular_mode=J3RandomPopular(),
        ),
        exam_settings=ExamSettings(turns=R2_TURNS),
        opponent=[
            OpponentSpec(name="十王星南", score_min=598779, score_max=618779),
            OpponentSpec(name="有村麻央", score_min=437672, score_max=487672),
        ],
        note=_PRESET_NOTE_R2,
    ),
}


# ---------------------------------------------------------------------------
# preset ⊕ override 合成(§4.1)
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, override: dict) -> dict:
    """深合并:dict 递归合并,标量/列表整体替换。override 键优先。

    判别 union 节点(带 mode 键)跨变体覆盖时整体替换——把 J3RandomPopular 换成
    FixedPopular 时不得把 criteria/first_weights 残留进新变体(extra=forbid 会拦)。
    """
    if "mode" in override and "mode" in base and override["mode"] != base["mode"]:
        return copy.deepcopy(override)
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def build_spec(preset: str | ScenarioSpec, overrides: dict | None = None) -> ScenarioSpec:
    """preset ⊕ overrides → ScenarioSpec。

    preset 可为内置预设 ID 或已有 spec;overrides 为同构 dict(嵌套字段路径)。
    校验失败(字段名错/值类型错)由 pydantic 报错——不静默吞。
    """
    base = PRESETS[preset] if isinstance(preset, str) else preset
    if not overrides:
        return base.model_copy(deep=True)
    return ScenarioSpec.model_validate(_deep_merge(base.model_dump(), overrides))
