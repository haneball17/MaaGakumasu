# Round 模拟器实施计划(随里程碑更新)

**设计真源:** [`roundsim-design.md`](roundsim-design.md)(冲突以其为准) · **ADR:** [0001 零拟合](../adr/0001-simulator-zero-fitting.md) / [0002 本地 WebUI 栈](../adr/0002-local-web-ui-stack-for-simulator.md)
**状态速览更新到本表顶部;每里程碑 = 一次 `feat(hif): roundsim M*` 提交。**

## 里程碑速览

| # | 主题 | 状态 | 提交 | 验收证据 |
| --- | --- | --- | --- | --- |
| M1 | 内核骨架(spec/settings/deck/runner/trace + CLI) | ✅ 完成 | `feat(hif): roundsim M1 内核骨架` | pytest 151 全绿(存量 128 + 新增 23);`simulate_round.py --preset hif_r1_rinami --seed 42` 出 9 回合合法 trace;R2 预设応援棒补足 22 张;ruff 过 |
| M2 | 效果引擎 + S1 得分 + 算例回归 | ⬜ | | |
| M3 | 专属 P item trigger + 応援棒 | ⬜ | | (応援棒补卡已在 M1 随 deck.py 落地) |
| M4 | play.py 三修复 + 贪心基线 + A/B runner | ⬜ | | |
| M5 | observed case adapter + 実機回放校验 | ⬜ | | |
| M-UIa | FastAPI 骨架 + 回放查看 | ⬜ | | |
| M-UIb | 配置表单 + 模拟驱动 + A/B 视图 | ⬜ | | |

## M1 记录(2026-08-16)

- **包**:`agent/hif/roundsim/`(settings/spec/deck/trace/runner 五件)+ `tests/test_roundsim.py`(23 例)+ `tools/simulate_round.py`(CLI:`--preset/--seed/--set/--out`)。
- **常量断言看守**(§4.2 锁死清单):M3 抽牌 3/上限 5/hold 2、S2 好調 ×1.5、S3 相加 1.5+0.1B(连乘式排除)、S4 集中 2.0/2.5、S1 kjirou 算例 (23+4×2.0)×(1.5+0.6)=65.10→ceil 66、R1/R2 回合数 9/12。
- **预设**:「莉波実機 20 张构筑」在 observed case 中只有 `deck_size=20` 与三围快照,无逐卡清单——**构筑为重构近似**(核心五卡実機证据 + 莉波好調流池内补足 15 张),已在 `spec.py` 模块 docstring 与 spec.note 声明,待実機逐卡取证校正。R2 预设 = 同构筑 + シュプレヒコール→+(interval 実機 customize)+ 応援棒补足 22 + 対手 -02 区间。
- **buff 递减**(R1/kjirou 快照模型):`granted_turn ≤ t-2` 的 buff 回合开始各 -1;考试初始 buff granted_turn=0(好調 6T 恰覆盖第 1-6 回合,测试锁定)。付与回合内新 buff 下回合不减(保护),下下回合起减——与 mechanics R1【B】一致。
- **応援棒补足**(D5)已在 M1 的 deck.py 实现(R2 预设验证 22 张);M3 剩余工作 = 专属 P item trigger 引擎。
- **流行序列**:j3_random 按 davi-01 基準(Da1960>Vi1307>Vo1089)末 3 回合固定 Vo→Vi→Da、首回合权重 A4 假设(缺省按基準比率)、中段按比率;fixed 模式注入 + 长度校验。
- **union 覆盖语义**:`build_spec` 深合并遇判别 union(j3_random→fixed)整体替换,不残留旧变体字段。

## 假设清单(§11,随报告输出)

A1 対手 uniform / A2 R2 初始清零 / A3 饮料跨 Round / A4 首回合流行权重自定 / A5 skip 得分 0 / A6 ×1.2 仅 R1 第 1 位 / A7 △✕无减衰 / A8 lesson_once Lost / A9 有效参数口径——全部按设计 §11 原文,未新增未删;莉波预设构筑的重构近似为**新增声明项**(数据缺口,非规则假设)。
