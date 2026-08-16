# Round 模拟器实施计划(随里程碑更新)

**设计真源:** [`roundsim-design.md`](roundsim-design.md)(冲突以其为准) · **ADR:** [0001 零拟合](../adr/0001-simulator-zero-fitting.md) / [0002 本地 WebUI 栈](../adr/0002-local-web-ui-stack-for-simulator.md)
**状态速览更新到本表顶部;每里程碑 = 一次 `feat(hif): roundsim M*` 提交。**

## 里程碑速览

| # | 主题 | 状态 | 提交 | 验收证据 |
| --- | --- | --- | --- | --- |
| M1 | 内核骨架(spec/settings/deck/runner/trace + CLI) | ✅ 完成 | `feat(hif): roundsim M1 内核骨架` | pytest 151 全绿(存量 128 + 新增 23);`simulate_round.py --preset hif_r1_rinami --seed 42` 出 9 回合合法 trace;R2 预设応援棒补足 22 张;ruff 过 |
| M2 | 效果引擎 + S1 得分 + 算例回归 | ✅ 完成 | `feat(hif): roundsim M2 效果引擎+S1` | kjirou 算例 (23+4×2.0)×(1.5+0.6)=65.1→66 与 (10+4)×2.1=29.4→30 单测绿;莉波池+基本池未建模 tag=0;first_legal 完整局 R1/R2 可跑(守恒/D1 分流/再演/延迟抽牌在 trace 可见);pytest 167 全绿;ruff 过 |
| M3 | 专属 P item trigger + 応援棒 | ⬜ | | (応援棒补卡已随 M1 deck.py 落地并测试) |
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

## M2 记录(2026-08-16)

- **引擎**(`agent/hif/roundsim/engine.py`):按 effect_type(非 tag——同名 tag 多语义)派发,支持面 = SUPPORTED_EFFECT_TYPES(13 类)+ SUPPORTED_CONDITIONS(3 条)+ 使用可门槛 pattern 2 族,全部由 `precheck()` 看守,范围外硬失败列出卡名。FirstLegalStrategy 占位选手(M4 由贪心/GarakutaRinami 取代)。
- **S1 函数**:`ceil(ceil((基础+集中×档)×状態倍率)×参数/100×…)`,状態倍率好調替换式 1.5(非 1.0+1.5 叠加)+ 絶好調 0.1×層相加。kjirou 双算例回归绿。
- **数据链增补**:`tools/sync_hif_effects.py` 新增 `force_stamina`(固定体力消耗,お姉さん=6/スポットライト=3,旧 stamina 字段漏)与 `play_trigger`(使用可门槛:好調≥4/≥12、絶好調≥1)两字段并重新生成 skill_card_effects.json(121 卡对账通过)。
- **timer/enchant/condition 盘点(莉波 20 张+基本池 5 种实际用量)**:timer=スポットライト延迟抽牌 2 条(平展为 deferred_turns,容器行 no-op);enchant=再演(お姉さん)+もう1回発動(国民的)各 1,以 runtime 状态建模;condition=深呼吸(集中≥3)/パンプアップ(トラブル≥2)/国民的 targeting 3 条,全部在支持面——**未超界,无需扩**。
- **応援棒池补建模**:ステージングの基本 = ExamLessonAddMultipleParameterBuff(好調時 2 倍適用,value2=1000‰),已入引擎(否则 R2 补足卡带未建模效果)。
- **裁判强制项**:使用可门槛/集中成本(ExamLessonBuff)/好調層成本(ExamParameterBuff)/体力+元気支付(元気优先,R2)/使用数(play_add 即回补、出卡后残余追加清零、SKIP 延续)/再演(ターン内 1 回・4 回まで・源卡 Lost→Grave 可回流)/もう1回発動(次卡效果双执行,第二个得分条目)。非法动作 IllegalActionError。
- **修 bug**:deck.move_played 未从手牌移除(卡无限复用→使用数雪崩死循环);好調倍率叠加错误(1.0+1.5→2.5,应为替换 1.5)。
- **ActionKind.SKIP** 已加入 decisions/state.py(M4 修复项前置,枚举向后兼容)。

## 假设清单(§11,随报告输出)

A1 対手 uniform / A2 R2 初始清零 / A3 饮料跨 Round / A4 首回合流行权重自定 / A5 skip 得分 0 / A6 ×1.2 仅 R1 第 1 位 / A7 △✕无减衰 / A8 lesson_once Lost / A9 有效参数口径——全部按设计 §11 原文,未新增未删;莉波预设构筑的重构近似为**新增声明项**(数据缺口,非规则假设)。
