"""HIF Round 考试模拟器内核(roundsim-design.md §3 八件套)。

裁判/选手分离:本包只做诚实的规则执行与计分(裁判),决策智能全部住在策略层
(选手,GarakutaRinamiStrategy 等在 decisions/,经 ExamState/CardAction 协议接入)。
RNG 全注入式(random.Random(seed) 显式传参,禁全局随机源);未建模卡组预检硬失败。

分层:
- settings.py 机制常量(锁死)+ ExamSettings 结构参数(可配)
- spec.py     ScenarioSpec 三层输入模型 + 内置预设 + preset⊕override 合成
- deck.py     卡组解析/四区(山札/手牌/捨札/除外)/抽牌重洗/応援棒补足
- runner.py   回合循环(状态推进 + trace 产出)
- trace.py    trace JSON 格式(回合事件流 schema,一次定死)
"""

from agent.hif.roundsim.spec import PRESETS, ScenarioSpec, build_spec
from agent.hif.roundsim.runner import RoundSimRunner, run_exam
from agent.hif.roundsim.settings import ExamSettings

__all__ = [
    "ExamSettings",
    "PRESETS",
    "ScenarioSpec",
    "RoundSimRunner",
    "build_spec",
    "run_exam",
]
