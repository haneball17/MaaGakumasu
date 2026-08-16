# HIF Round 模拟器设计

**日期：** 2026-08-16（同日定案：四轮 grill + 两轮全面复盘 + 前端技术调研）
**状态：** 设计定案，未开工。机制表述以 [`mechanics.md`](mechanics.md) 置信度分级为准；实施进度见（开工后另建的）`roundsim-implementation-plan.md`。
**适用场景：** HIF 本戦 Round1/Round2 考试的出牌级模拟、策略 A/B 对比、実機回放校验、可视化模拟驱动。
**前置阅读：** [`mechanics.md`](mechanics.md)（机制知识库，M/S/D/H/J 条目）、[`scoring-model-design.md`](scoring-model-design.md)（选卡侧评分模型，与本模拟器分工见 §2）、[`finals-daily-log.md`](finals-daily-log.md) Round1 节、[ADR-0001](../adr/0001-simulator-zero-fitting.md)、[ADR-0002](../adr/0002-local-web-ui-stack-for-simulator.md)。

---

## 1. 定位与目标

五步路线（机制知识库 ✅ → **模拟器** → 参数枚举 → 用户可配置 → 自动定参）的第 2 步。模拟器承担三个角色：

1. **A/B 考试平台**（主用途）：批量跑局、共同随机数、输出策略得分分布与勝率——第 3 步「参数枚举」与第 5 步「自动定参」的考官。
2. **実機回放校验器**（兼带）：用実機观察数据复算得分对比，作为模拟器自身正确性的金标准。
3. **可视化模拟驱动器**：前端配置 → 触发模拟 → 看结果，三视图呈现全流程。

**C2 调参（评分模型人工网格定参）由此推迟**，由模拟器参数枚举取代；评分分歧样本人工审阅不阻塞、可并行。

**非目标**（MVP 不做，边界见 §3-§5）：

- メモリー（記憶）效果执行——仅留 `initial_enchants` 注入接口。
- 特別指導（カスタマイズ，[customize-integration-notes.md](customize-integration-notes.md)）——Round2 流程立项时接入。
- △/✕评价减衰（U3 精确式未查明）——按无减衰实现并标注。
- 対手出牌模拟——対手为静态分数（§3.4）。
- 実機管线接线——出牌策略接入 `ProduceHIFRound1Observe` 是模拟器验收后的另一个立项。

## 2. 设计哲学（六原则）

| # | 原则 | 含义 |
| --- | --- | --- |
| 1 | **零拟合** | 得分函数、対手分数、抽牌规则、指針倍率全部查官方数据（gakumasu-diff），不做任何参数拟合。模拟器是项目内「地面真相」层：它说「这局得多少分」，评分模型（scoring v2，含 k_buff 等校准参数的近似层）说「这张卡值得拿」。两者分歧时以模拟器校评分模型，不可反向。详见 [ADR-0001](../adr/0001-simulator-zero-fitting.md)。 |
| 2 | **実機对齐** | 只模拟実機真实存在的东西：动作集只认実機按钮（§3.3），初始状态用実機观察值（体力 28/好調 6/集中 6），卡组用実機构筑。実機未证实的规则进显式假设清单（§11），每条可翻转。 |
| 3 | **裁判/选手分离** | 模拟器只做诚实的规则执行与计分（裁判），不含决策智能；全部智能住在策略层（选手）。收益：A/B 公平 + 策略可迁移（同一策略函数接模拟器或実機管线）。 |
| 4 | **显式失败优于静默近似** | 卡组含未建模效果的卡 → 预检硬失败报错；不用评分模型折算、不静默跳过。A/B 结论可信度 > 覆盖率。 |
| 5 | **随机性用 CRN 压制** | 抽牌/流行序列/対手分建模为注入式 RNG；A/B 用共同随机数（同批种子），单策略评估用 N 局分布 + bootstrap CI。 |
| 6 | **数据驱动效果执行** | 效果引擎消费 `skill_card_effects.json` 结构化字段按 tag 派发，不逐卡硬编码；新卡 = 数据行，不是代码。 |

## 3. 内核规格（`agent/hif/roundsim/`）

### 3.1 八件套

| # | 组件 | 规格 | 依据 |
| --- | --- | --- | --- |
| 1 | 卡组容器 | R1：実機构筑原样（莉波 20 张，允许 <22，无応援棒）；R2：応援棒（R1 后強制配布，固定 on）在考试开始时补「基本」卡至 22（parameter_buff 池 5 种按 ProduceCardRandomPool ratio 抽，随机位置插入）；deck ≥22 则不触发 | 実機 observed case + D5【B】+ ProduceCardRandomPool【A】 |
| 2 | 抽牌洗牌 | 每回合开始发 3（`turnStartDistribute`）、手牌上限 5、hold 上限 2；回合结束手牌全弃（Hold 卡除外）进捨て札；山札不足抽牌需要时捨て札全部洗回、当回合续抽不推迟 | M3/D2【A/B】 |
| 3 | 手牌投影 | 具体手牌列表 → `HandSummary`（`exam_reader.build_hand_summary` 逻辑平移）——模拟器与実機 OCR 走同一种状态视图 | 现成代码 |
| 4 | Grave-Lost 分流 | 逐卡 `playMovePositionType`：`is_lesson_once`（池内 102 张）→ Lost 除外不回流；其余（19 张循环卡）→ Grave 重洗回流。七种去向枚举含 Hand/DeckFirst/DeckLast/DeckRandom/Hold | D1【A】 |
| 5 | 回合循环 | R1 = 9 ターン / R2 = 12 ターン（可配置，§4.2）；流行序列双模式：`fixed`（显式注入，A/B 控制变量）与 `j3_random`（末 3 回合固定 3→2→1 位、末回合必 1 位、首回合自定权重、中段按審査基準比率随机）；buff 次回合开始 -1、付与回合保护 | J3【B，首回合权重为假设】+ R1【B】 |
| 6 | 效果执行 | tag 派发引擎（§5）；MVP 建模范围 = 莉波実機 20 张 + 基本卡池 5 种涉及的全部 tag | §5 |
| 7 | 使用数 | 基准每回合 1 张；`play_add` 追加（打出即回补，净行动成本 ≈0）；SKIP 不消耗、追加 buff 可延续到下回合，一旦出卡残余追加即解除；「使用準備」不消耗使用数直接发动 | M4【B】 |
| 8 | 得分函数 | S1 总式（官方常量、逐级 ceil）：`出牌得分 = ceil(ceil((基础值 + 集中×档位倍率 + 附加) × 状態倍率) × 属性有效参数/100 × (1+得分上升量/100) × 不調修正)`；状態倍率 = 1.5 + 0.1×好調層（相加）；玩家侧属性倍率 = 该属性有效参数/100；集中 1/2 档 ×2.0/×2.5、体力 ×2.0 | S1-S6【A】+ ExamSetting 常量 |

**牌库动力学要点**（R1 的核心看点）：20 张 × 9 回合 × 每回合抽 3 ≈ 27 次抽取需求 > 牌组张数 → Grave 重洗在 R1 必然发生；lesson_once 卡持续除外使有效山札变薄（D4 压缩），循环卡被抽中概率上升。

### 3.2 状态与得分的口径

- 三围输入为**有效参数**口径（含親愛度/HIFボーナス换算后的実機画面值），親愛度分解不做（U2 假设）。
- P 饮料效果值从 `drink_effects.json` 读（センブリソーダ等）。
- skip 回合得分 = 0（假设，§11）。

### 3.3 合法动作集（裁判-选手接口）

```
CardAction ∈ { PLAY_CARD(含具体卡名), SKIP, USE_P_DRINK }
```

策略每回合收 `ExamState` 投影、返回 `CardAction`；非法动作预检报错。**依据**：実機 Round1 界面唯一独立按钮是 SKIP（finals-daily-log ROI 表）+ 底部饮料栏；没有「手札交換」「ドロー」独立按钮——旧仓库抽象的 `DRAW`/`SWAP_HAND` 是失真（它们是卡效果 tag：draw 85 条 / 手札入れ替え词条），已从动作集剔除（§6.3 修复项 3）。

### 3.4 対手与優勝判定

対手 = 静态分数（`isStaticNpcScore: true`），每局从 scoreMin/Max 区间 **uniform 独立抽样**（莉波玩家挂 amao 组）：

| Round | 対手 1（十王星南） | 対手 2（莉波镜像） |
| --- | --- | --- |
| R1 | 403161–409161 | 301182–316182 |
| R2 | 598779–618779 | 437672–487672 |

（baseScore 406150 ≈ jsna 区间中点，自洽印证。）

**優勝组合模式**：runner 支持同批种子跑 R1 + R2 两段 → 総合評価判定：R1 得第 1 位时 ×1.2（V1 假设）+ R2 得分 vs 两名対手合计 → 勝率/顺位分布。R1/R2 独立模拟时勝率只能近似。

### 3.5 初始状态默认值

R1 默认 = 実機观察值：体力 28、好調 6 ターン、集中 6（場外メモリー/P item 注入的等效产物，走 `initial` 字段注入）。R2 初始状态実機未取证（假设清单 §11）。

## 4. ScenarioSpec（输入模型）

### 4.1 单一真源

pydantic model 定义于 Python 侧，导出 JSON Schema 供前端对齐 + 契约测试锁定（防前后端漂移）。`spec = preset ⊕ overrides`：用户改的字段覆盖默认，未改字段继承预设。

### 4.2 三层结构

| 层 | 字段 | 可配置性 |
| --- | --- | --- |
| `scenario` | `deck`（卡名+档位列表）、`initial`（体力/元気/三围有效参数/饮料数/初期 buff，R1 默认実機值）、`p_items`（応援棒 R2 固定 on）、`popular_mode`（`fixed` 序列或 `j3_random`）、可选 `first_hand` 固定首手注入（复现実機首手/逐局校验用） | 全部可配 |
| `exam_settings` | **结构参数可配**（默认 = 官方值）：`turns`（R1=9/R2=12 或任意）、`turn_start_distribute`（3）、`hand_limit`（5）、`hold_limit`（2）、`stamina_recover_per_turn_end`（2） | 覆盖任意字段 |
| `opponent` | 默认挂 produce_008 双対手区间（§3.4）；可自定义分数区间 | 覆盖 |

**机制常量锁死不开放**：好調 ×1.5、絶好調 +0.1/層、集中 ×2.0/×2.5、温存/全力倍率、元気代偿、S1 式结构与逐级 ceil——A 级实证，常量断言测试看守（§9.1）。改了就不是本游戏。

### 4.3 内置预设（一等公民，测试锁定完整性）

| 预设 ID | 内容 |
| --- | --- |
| `hif_r1_rinami` | R1 9T、莉波実機 20 张卡组、初期体力 28/好調 6/集中 6、专属 P item「憧れ続けた輝き」、`j3_random`、produce_008-01 双対手、N=1000 |
| `hif_r2_rinami` | R2 12T、応援棒 on（补足至 22）、其余同上、対手挂 -02 |

CLI：`python tools/simulate_round.py --preset hif_r1_rinami [--set key=value ...]` 零配置直跑；前端下拉同源。用户自定义预设命名保存到 `debug/roundsim/presets/`（与内置同格式），可导出 JSON 给 CLI——三个入口（CLI/前端/文件）完全同源。A/B 网格 = 预设 ⊕ 参数扫描，报告里默认预设一行恒在（可对比基线）。

## 5. 效果执行引擎

- **数据源**：`assets/data/hif/skill_card_effects.json`（170 卡，effects[] 带 op/value/turn/count/unit/scope/condition/deferred_turns/level；move_position；tiers 消耗）。
- **tag 派发**：按 `effect_type`（31 种）分发到执行器；莉波 20 张 + 基本池 5 种涉及的全部 tag 在 MVP 实现。`decisions/scoring.py` 的 `_effect_points` 已解释 20+ tag 语义，可迁移为执行内核参考。
- **指針/集中**：S8/H9/H10 全表常量（集中 1/2 档 ×2.0/×2.5 与体力 ×2.0、温存 ×0.5/×0.25、全力 ×3.0 + 使用数+1、元気阈值解除链）；指針由卡效果显式付与，**无手动切换**（数据 + 実機双重确认，実機界面无指針按钮）。
- **trigger 引擎**（泛化触发器，メモリー将来同接口）：第一例 = 专属 P item「憧れ続けた輝き」——好調 ≥8 ターン门槛 + 每使用 4 张好調系卡计数间隔，触发：絶好調 1 ターン + 使用数追加 +1 + 抽 1 张 + 体力消費 1（最多 5 次）。与 lesson_once 同族的「计数间隔 + 状态门槛」类。
- **未建模处理**：卡组预检阶段发现未实现效果的卡 → **硬失败**，报错列出卡名与缺失 tag；报告附未建模 tag 计数。
- **数据缺口已知项**：`condition` 为原始 effect_id 引用串，需解释层；timer/enchant（207 条）展开语义复杂——莉波池实际用量在 M2 盘点，出界即预检失败。

## 6. 策略接口与先行修复

### 6.1 接入（零改动部分）

`GarakutaRinamiStrategy.decide(ExamState) -> CardAction`（纯逻辑、无 maafw 依赖）直接作为被测策略；`ExamState`/`HandSummary`/`CardAction` 复用 `decisions/state.py`。

### 6.2 即时分贪心基线

对照策略：每回合枚举手牌可出卡，用模拟器自己的 S1 得分函数算**本回合即时得分**，选最高（平手选体力消耗低）；不看好調覆盖/压缩/再演协同。复用计分层，兼当效果引擎烟雾测试。（官方 AutoEvaluation 表因好调流权重缺位不作基线，S10。）

### 6.3 play.py 先行修复（模拟器开工的前置，§M4）

1. **`pick_playable_card()`**：`target_card=None` 的「出好调卡」分支具体化——可出卡按 好調付与值高 > 体力消耗低 > 不卡手 排序；再演/收尾分支已有具体卡名不动。模拟器与実機接线共用此函数。
2. **SKIP 动作**：`ActionKind` 增加 SKIP；低体力分支二选一（喝 P 饮料 or SKIP 回体 2）。
3. **④分支重写**：原「DRAW/SWAP_HAND 压缩山札」改为「打出抽卡系/换牌系效果的卡」（卡效果语义，§3.3）；⑦兜底抽牌同理修正为 SKIP。

## 7. A/B 方法论

- **共同随机数（CRN）**：对比策略跑同一批种子（同样洗牌/流行/対手分），得分差异只反映策略差异。
- **批量 rollout**：默认 N=1000；报告得分分布（均值/P50/P90 + bootstrap 置信区间）、勝率/顺位分布（対手抽样同步 CRN）。
- **参数网格**：`ProfilePayload` 变体工厂（reprise.max / good_cond_gate / finisher_gate 等），网格 = 预设 ⊕ 扫描。
- **报告**：CLI stdout 表格 + markdown 文件（对齐 `hif_replay_report.py` 风格）；附未建模 tag 计数与假设清单（§11）。默认预设一行恒在。

## 8. 前端与工具（M-UI）

### 8.1 技术栈（详见 [ADR-0002](../adr/0002-local-web-ui-stack-for-simulator.md)）

Vue 3 + Vite + ECharts + FastAPI/uvicorn（**新 Python 依赖**）；vite-plugin-singlefile；node ≥22 LTS（构建链，此前仓库 Node 侧仅 prettier 工具链）。

### 8.2 架构：开发/发布双模式

```
ui/                        # Vite 项目（顶级目录，工具链性质）
  src/                     # Vue 组件：回放 / 分布 / A/B 视图
tools/round_sim_app.py     # FastAPI 入口：python tools/round_sim_app.py → localhost:8xxx
tools/render_round_ui.py   # trace 注入自包含模板 → round-trace.html（离线查看降级模式）
```

- **开发**：`npm run dev`（HMR），Vite dev server 代理 API。
- **驱动**：前端表单 → `POST /api/simulate` → 内核跑局 → 返回 trace/统计 → 渲染。同步快（N≤200 即时返回）；大 N/网格走异步任务（提交 → 轮询进度 → 可取消）。
- **离线**：构建产物为含 `__TRACE_DATA__` 占位符的自包含模板 HTML，Python 注入 trace → 单文件双击可开（规避 file:// 的 fetch CORS），可归档 `debug/`。

### 8.3 三视图三模式

| 视图 | 内容 |
| --- | --- |
| 单局回放 | 回合 scrubber + ▶ 播放/暂停 + 任意回合跳转；每回合：手牌快照 → 策略决策（含理由）→ 效果链 → S1 得分明细分解（如 `(23+4×2.0)×(1.5+0.6)=65.1`）→ 状态变化（好調/集中/体力/使用数）→ 牌库区演变（山札/Grave/Lost 计数，压缩过程可视化） |
| 批量分布 | 得分直方图/箱线图（ECharts）+ 代表局跳转（P50/最佳/最差局点进单局回放） |
| A/B 对比 | 多策略 CRN 分布对比 + 勝率表 + 假设清单页（未建模 tag、可翻转假设） |

### 8.4 配置 UI（三档渐进披露）

1. **快速预设**：下拉选内置/自定义预设，零配置直跑。
2. **标准表单**：卡组编辑（MVP = 预设下拉 + 按卡名搜索增删 + JSON 粘贴；完整卡池浏览器后置）、初始状态、策略选择 + 参数滑块、seed/N/流行模式。
3. **高级折叠**：exam_settings 结构参数覆盖、対手分数区间自定义。

配置保存/加载/导出 JSON，与 CLI ScenarioSpec 完全同源（§4.1）。schema 由 pydantic 导出，TS 类型对齐 + 契约测试锁定。

## 9. 验证（三层金字塔）

| 层 | 内容 | 时机 |
| --- | --- | --- |
| 1 常量断言 | 机制常量与结构不变式：M3（3/5/2）、D1 分流、S1 逐级 ceil、S3 相加结构、S4 集中档、R1 递减时机、exam_settings 锁死清单 | M1 起 |
| 2 算例回归 | 実機算例：kjirou `(23+4×2.0)×(1.5+0.6)=65.10` 等；katabami83 的 100 样本实测数据集列为候选（contest 口径，兼容性待验） | M2 |
| 3 実機回放 | 全局口径：同卡组跑 N 局分布、実機总分落点校准整体偏差；逐回合口径：手工録局格式（実機每回合记 4-5 个数：出手牌/好調层/体力/回合得分）精确卡漂移 | M5 |

**実機配合项**（一次跑图打包）：R1 最终得分 ≥1 局（数字或順位画面截图）；R2 初始状态截图（体力/好調/集中/饮料数，补 §11 盲区）；Round 中卡组计数变化（验 V2，可选）。

## 10. 里程碑

| # | 内容 | 交付/验收 |
| --- | --- | --- |
| M1 | spec + exam_settings + deck + 回合循环（skip-only 可跑完）+ **trace 格式定型** + 常量断言 | `roundsim/` 包 + `test_roundsim.py` |
| M2 | 效果引擎（莉波 20 张 + 基本池）+ S1 得分 + 算例回归 | 算例单测绿 |
| M3 | 专属 P item trigger + 応援棒补卡（仅 R2 路径） | 莉波流完整局可跑 |
| M4 | play.py 三修复 + 贪心基线 + A/B runner + CLI 报告 | **A/B 结论可用**（C2 被取代点） |
| M5 | observed case adapter + 実機回放校验 | 校准报告（需実機配合项） |
| M-UIa | FastAPI 骨架 + 回放/分布查看（只读 trace） | localhost 查看 |
| M-UIb | 配置表单 + 模拟驱动 + A/B 视图 | 前端一键模拟 |

每步跑 `tests/test_roundsim.py`；`algorithms/`（日程模拟器）冻结不动；M-UIa 在 M4 后、M-UIb 在 M5 后可并行。

## 11. 假设清单（可翻转，随报告输出）

| # | 假设 | 翻转条件 |
| --- | --- | --- |
| A1 | 対手分 uniform(min,max) 每局独立抽样 | 実機順位画面対手分数分布采样 |
| A2 | R2 局内初始状态清零（好調/集中/体力） | R2 初始状态実機截图（実機配合项 2） |
| A3 | P 饮料为 produce 级资源跨 Round 持有（R2 持有 = R1 剩余 + Interval 购买） | 同上 |
| A4 | 首回合流行权重自定（官方 HIF 概率表 dump 不存在） | 実機多局首回合属性采样 |
| A5 | skip 回合得分 = 0 | 手工録局 |
| A6 | ×1.2 仅 R1 第 1 位（V1） | R1 非 1 位时的順位画面 |
| A7 | △/✕无减衰（U3） | 実機减衰样本 |
| A8 | lesson_once 用后 Lost 不回流（V2，数据裁决 1% 残留） | Round 中卡组计数実機 |
| A9 | 三围输有效参数口径（U2 成分分解不做） | 3807% 成分分解查明 |

## 12. 来源

- **官方数据**：`.scrape/gakumasu-diff/`（ExamSetting / ProduceExamBattleScoreConfig / ProduceExamBattleConfig / ProduceStepAuditionDifficulty / ProduceExamBattleNpcGroup / ExamInitialDeck / ProduceInitialDeck / ProduceCardRandomPool / ProduceItem(Effect) / ProduceExamStatusEnchant / ProduceCard(Tag/Search) / IdolCard / ProduceExamGimmickEffectGroup【produce_008 gimmick 为 startTurn=99 死占位，可忽略】）。
- **実機**：`debug/decisions/session-20260815.jsonl` round1_initial、`assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json`（20 张构筑 + 三围快照）、`finals-daily-log.md` Round1 节（:1351-1440）。
- **参考实现**：`debug/research/repos/` 三得分公式模拟器（kanon511 / kjirou / lts129，蓝本 lts129——Python 四区分流 + 词条派发；三仓库均无 ScoreConfig 阶梯表，卡池过时，本仓库数据链更新）。
- **机制依据**：`mechanics.md` M1-M4 / D1-D5 / S1-S10 / H1-H13 / J1-J4 各条（置信度分级见彼处）。
- **前端调研（2026-08）**：[svar.dev 框架对比](https://svar.dev/blog/react-vs-vue-vs-svelte-for-modern-web-apps/)、[Strapi 2026 框架基准](https://strapi.io/blog/best-javascript-frameworks)、[FusionCharts 图表库指南](https://www.fusioncharts.com/blog/best-javascript-charting-libraries-data-visualization-2/)、[vite-plugin-singlefile](https://github.com/richardtallent/vite-plugin-singlefile)。
