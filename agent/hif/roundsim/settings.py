"""机制常量(锁死)与考试结构参数(可配)——roundsim-design.md §4.2。

常量全部来自官方 ExamSetting.yaml / ProduceExamBattleConfig 本地 dump
(.scrape/gakumasu-diff,mechanics.md S1-S8/H5/H13【A】),零拟合(ADR-0001):
改了就不是本游戏,由 tests/test_roundsim.py 常量断言看守。

结构参数(ExamSettings)默认 = 官方值,允许场景覆盖(§4.2「覆盖任意字段」);
与常量的分界 = 改结构参数只是换了考试规格,改常量是换了游戏。
"""

from __future__ import annotations

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 机制常量:锁死不开放(mechanics.md S2/S3/S4/S8,ExamSetting.yaml 官方值)
# ---------------------------------------------------------------------------

# 好調 ×1.5(examParameterBuffPermil 1500,S2【A】)
GOOD_CONDITION_PERMIL = 1500

# 絶好調:状態倍率 +0.1×好調層(相加,S3【A】;examParameterBuffMultiplePerTurnPermil 100)
EXCELLENT_ADD_PER_TURN_PERMIL = 100

# 集中(強気)分层倍率:1 级 ×2.0 / 2 级 ×2.5(S4/H10【A】;examConcentrationLessonValueMultiplePermil1/2)
CONCENTRATION_LESSON_MULT_L1 = 2.0
CONCENTRATION_LESSON_MULT_L2 = 2.5

# 集中(強気)時体力消耗 ×2.0(examConcentrationStaminaMultiplePermil1/2 均 2000)
CONCENTRATION_STAMINA_MULT = 2.0

# 温存:レッスン値 ×0.5/×0.25(examPreservationLessonValueMultiplePermil1/2;莉波池未用,引擎级常量)
PRESERVATION_LESSON_MULT = {1: 0.5, 2: 0.25}
# 全力:レッスン値 ×3.0 + 使用数 +1(examFullPowerLessonValueMultiplePermil 3000)
FULL_POWER_LESSON_MULT = 3.0

# 不調減衰 ×0.667(examGimmickParameterDebuffPermil 667;S7 精确式未查明,按 A7 假设无减衰时不触发)
GIMMICK_BAD_PERMIL = 667

# ---------------------------------------------------------------------------
# 考试结构默认值(ExamSetting.yaml / ProduceExamBattleConfig,H5【A】)
# ---------------------------------------------------------------------------

R1_TURNS = 9  # p_exam_battle_config-davi-01-produce_008-01 turn=9
R2_TURNS = 12  # p_exam_battle_config-davi-01-produce_008-02 turn=12

# 莉波 produce_008 審査基準(davi-01,流行序列 j3_random 的比率来源)
RINAMI_CRITERIA = {"Vo": 1089, "Da": 1960, "Vi": 1307}

# 応援棒补足目标枚数(D5【B】:技能卡不足 22 枚时补「基本」卡到 22)
OUENBOU_DECK_TARGET = 22

# 応援棒 parameter_buff 池(ProduceCardRandomPool p_random_pool-...-parameter_buff,ratio 1:2:1:1:1)
OUENBOU_BASIC_POOL: list[tuple[str, int]] = [
    ("ステージングの基本", 1),
    ("ステップの基本", 2),
    ("視線の基本", 1),
    ("思考の基本", 1),
    ("タイミングの基本", 1),
]


class ExamSettings(BaseModel):
    """考试结构参数(§4.2「结构参数可配」,默认 = 官方值)。

    覆盖任意字段用于实验(如 12 回合 R1);机制常量(好調 ×1.5 等)不在此列。
    """

    turns: int = R1_TURNS  # R1=9 / R2=12 或任意
    turn_start_distribute: int = 3  # M3 每回合开始分发 3 张
    hand_limit: int = 5  # M3 手札上限 5
    hold_limit: int = 2  # M3 保留上限 2
    stamina_recover_per_turn_end: int = 2  # S8 每回合结束回体力 2
