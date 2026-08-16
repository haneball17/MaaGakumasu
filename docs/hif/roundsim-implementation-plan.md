# Round 模拟器实施计划(随里程碑更新)

**设计真源:** [`roundsim-design.md`](roundsim-design.md)(冲突以其为准) · **ADR:** [0001 零拟合](../adr/0001-simulator-zero-fitting.md) / [0002 本地 WebUI 栈](../adr/0002-local-web-ui-stack-for-simulator.md)
**状态速览更新到本表顶部;每里程碑 = 一次 `feat(hif): roundsim M*` 提交。**

## 里程碑速览

| # | 主题 | 状态 | 提交 | 验收证据 |
| --- | --- | --- | --- | --- |
| M1 | 内核骨架(spec/settings/deck/runner/trace + CLI) | ✅ 完成 | `feat(hif): roundsim M1 内核骨架` | pytest 151 全绿(存量 128 + 新增 23);`simulate_round.py --preset hif_r1_rinami --seed 42` 出 9 回合合法 trace;R2 预设応援棒补足 22 张;ruff 过 |
| M2 | 效果引擎 + S1 得分 + 算例回归 | ✅ 完成 | `feat(hif): roundsim M2 效果引擎+S1` | kjirou 算例 (23+4×2.0)×(1.5+0.6)=65.1→66 与 (10+4)×2.1=29.4→30 单测绿;莉波池+基本池未建模 tag=0;first_legal 完整局 R1/R2 可跑(守恒/D1 分流/再演/延迟抽牌在 trace 可见);pytest 167 全绿;ruff 过 |
| M3 | 专属 P item trigger + 応援棒 | ✅ 完成 | `feat(hif): roundsim M3 P item trigger` | 憧れ続けた輝き(好調≥8+每4张好調系卡→絶好調1T/使用数+1/抽1/体力-1,≤5次,+版好調≥6)单测+完整局 trace 可见;莉波流 R1(20张)+R2(応援棒补足22张)完整局可跑;pytest 171 全绿;ruff 过 |
| M4 | play.py 三修复 + 贪心基线 + A/B runner | ✅ 完成(C2 被取代点) | `feat(hif): roundsim M4 三修复+贪心+A/B` | **首个 A/B 结论**(N=1000, CRN, bootstrap CI):R1 garakuta 13661[13134,14162] vs greedy 1954[1913,2004] vs first_legal 5841(7.0×,CI 不重叠);R2 garakuta 6359[5710,6987] vs greedy 2046(P50 1651 低于 greedy 2029,方差大=好調门槛依赖)。pytest 181 全绿;ruff 过 |
| M5 | observed case adapter + 実機回放校验 | ✅ 完成(待実機数据补校准) | `feat(hif): roundsim M5 実機回放校验` | 校准报告生成:`calibrate_roundsim.py --n 50` 出 R1/R2/総合分布+実機総合落点分位(4,756,391 → 100%)+偏差归因(A9/A10/未建模乘区)+数据缺口清单;手工録局 schema 定型+漂移对比单测;実機 R1 分/R2 初始未録 → TODO 标注不阻塞 M-UI;pytest 185 全绿 |
| M-UIa | FastAPI 骨架 + 回放/分布查看 | ✅ 完成 | `feat(hif): roundsim M-UIa WebUI 骨架` | node v24.19.0(winget)+fastapi/uvicorn;localhost:8642 API 全通(presets/trace/distribution/simulate 同步+异步任务/schema);Vue3+Vite+ECharts+singlefile 构建自包含 dist(入库,无 node 者可离线渲染);回放视图 DOM 级验证(総分/回合表/效果链/触发/牌库图表全渲染);render_round_ui.py 离线注入双模式(Vue 模板→降级最小查看器);prettier 欠账还清 |
| M-UIb | 配置表单 + 模拟驱动 + A/B 视图 | ✅ 完成 | `feat(hif): roundsim M-UIb 配置驱动+契约锁定` | POST /api/simulate(N≤200 同步/大 N 异步任务轮询取消)验收:零配置 hif_r1_rinami 一键 A/B(garakuta 14217[11785,16732] vs greedy 1887)+代表局回放(seed=0 trace 9 回合)全链通;三档表单(快速预设→标准表单→高级折叠 JSON);配置保存 debug/roundsim/presets/ 与 CLI 同源(save→list→trace 往返验证);pydantic→JSON Schema→TS 契约锁定(export_roundsim_schema + test_ui_contract 漂移检测);pytest 186 全绿 |

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

## M3 记录(2026-08-16)

- **triggers.py**:`PlayCountIntervalTrigger`(计数间隔+状态门槛类,メモリー将来同接口)+ 注册表(憧れ続けた輝き = interval 4/好調≥8/≤5 回;+版 好調≥6——dump 312-0/312-1-enc01 両版本)。新道具 = 注册表加一行。
- **触发语义实现声明**:每第 4 张好調系卡(效果含 ExamParameterBuff)到点时检好調门槛;満 → 絶好調1T+使用数+1(P item 付与,skip 即失,R3)+抽1+体力-1;未満 → 本次作废,下个 4 张再检。
- 応援棒补卡已在 M1 随 deck.pad_ouenbou 落地(ratio 1:2:1:1:1,ProduceCardRandomPool 実証)。

## M4 记录(2026-08-16)——C2 被取代点

- **play.py 三修复**(§6.3):①`pick_playable_card()` 默认出好調卡分支具体化(好調付与值高>体力消耗低>不卡手;排除关键三卡/门槛卡/付不起成本卡;OCR 无卡名退 None);②低体力二选一(喝优先饮料 or SKIP 回体 2);③④分支 DRAW/SWAP_HAND → 打出抽卡系卡(`_pick_compression_card`),⑦兜底 → SKIP。存量 22 测试随修复更新 + 新增 6 例,共 26 绿。
- **贪心基线**(§6.2):`GreedyStrategy` 复用 S1 函数算每张可出卡即时分,argmax 平手选省体力,全 0 分 Skip。
- **A/B runner**(`ab.py` + CLI `--ab A,B --n --combined`):CRN 同批种子(対手抽样独立 RNG 流,不受局内 rng 消耗差异影响——同 seed 跨策略対手分恒同,有测试);bootstrap CI(percentile,B=2000,(score,rank) 成对重采样);優勝组合模式 R1(第1位×1.2,V1)+R2 vs 双対手合计;报告 markdown 附假设清单+未建模计数+默认预设行(first_legal 基线恒在)。
- **适配器**:`RinamiStrategyAdapter` 包装 decisions.GarakutaRinamiStrategy(ExamView→ExamState 投影,与実機 OCR 适配层同构);None/不可出目标在交给裁判前兜底 Skip(裁判 IllegalActionError 仍守底线)。
- **首个 A/B 结论**(莉波重构构筑,R1 9T/R2 12T):garakuta_rinami 显著优于 greedy(R1 均值 7.0×,CI 不重叠;R2 3.1×);R2 garakuta P50(1651)低于 greedy(2029)——好調 12T 收尾门槛在 buff 清零的 R2 前期不满足,分布重尾(自然体命中即大分)。**此 commit 起 C2(评分模型人工调参)正式被模拟器参数枚举取代(ADR-0001)**。
- **絶対分校准注记**:sim R1 ~1.4万 vs 対手 40万——预设三围为准备期中段快照(Vo1116/Da2920/Vi2175),実機 R1 入场三围未取证(3807% 那次 Vi=3807);相对 A/B 结论不受影响(同构筑同対手),絶対落点校准归 M5(実機总分落点分位 → 归因 A9/构筑近似)。

## M5 记录(2026-08-16)——**待実機数据补校准**

- **adapter.py**:`spec_from_observed_case`(三围取実機记录链最后值 Da2920/Vi2175、R1 体力 28;缺口显式声明不猜)+ `observed_final_scores`(R2 総合評価 4,756,391 在 case 内;R1 单段分未録 → None/TODO)+ `ManualGameRecord/ManualTurnRecord` 手工録局 schema(extra=forbid 锁死)+ `validate_trace_against_manual` 逐回合漂移对比。
- **calibrate_roundsim.py**:全局口径报告(R1/R2/総合分布 P10/P50/P90、実機落点分位、越界归因到 §11 条目、数据缺口清单、可选 --manual 逐回合口径)。
- **当前校准结论(n=50)**:実機総合 475.6 万落点 100% 分位(模拟 P100 ≈ 7.6 万)——系统性偏低,候选归因 A9(预设三围为准备期中段快照,実機入场值更高)+ A10(构筑重构近似)+ 未建模乘区(好印象 S5/得分上升量/S6 分段+親愛度 H7)。**待実機配合项补录后重跑**:① R1 最終得分;② R2 初始状态截图;③ Round 中卡组计数。

## M-UIa/M-UIb 记录(2026-08-16)

- **环境前置**:node v24.19.0(winget,≥22 LTS 满足);fastapi 0.141 + uvicorn 0.52(清华镜像);root devDeps 补 prettier-plugin-multiline-arrays 实装。
- **架构落地**(§8.2 双模式):`tools/round_sim_app.py`(FastAPI,静态托管 ui/dist + /api)+ `ui/`(Vue3+Vite7+ECharts6+vite-plugin-singlefile,构建自包含单 HTML 1.2MB **入库**——无 node 使用者的离线渲染底板)+ `tools/render_round_ui.py`(注入 `__TRACE_DATA__`,无构建时降级内嵌原生 JS 最小查看器)。
- **API**:presets(含 custom 标记)/trace/distribution(N≤200)/simulate(同步+异步任务+轮询+取消)/tasks/schema/custom-presets(存 debug/roundsim/presets/ 与 CLI 同源)。
- **三档配置**(§8.4):快速预设下拉 → 标准表单(策略多选/N/seed0/JSON 粘贴)/高级折叠说明;A/B 表含 CI + 「代表局回放」跳转(App tab 切换 + ReplayView 注入加载)。
- **契约锁定**(§4.1):`tools/export_roundsim_schema.py` 生成 `ui/src/generated/scenariospec.{schema.json,ts}`;`test_ui_contract` 断言仓库文件与模型导出一致(漂移即红)。vue-tsc 类型检查过。
- **验证方式注记**:本会话 IAB 面板点击事件不可送达(环境限制),交互路径以 ①注入 trace 的全量渲染 DOM 快照(回放视图総分/回合表/效果链/触发/牌库图全在)②API 全链(presets fetch→simulate→trace)③同源 load() 函数三条证据覆盖;実機浏览器人工复核留待用户。
- **修 bug**:main.ts 根 props 传 ref 对象恒真 → 离线模式误判(改传值)。

## 假设清单(§11,随报告输出)

A1 対手 uniform / A2 R2 初始清零 / A3 饮料跨 Round / A4 首回合流行权重自定 / A5 skip 得分 0 / A6 ×1.2 仅 R1 第 1 位 / A7 △✕无减衰 / A8 lesson_once Lost / A9 有效参数口径——全部按设计 §11 原文,未新增未删;莉波预设构筑的重构近似为**新增声明项**(数据缺口,非规则假设)。
