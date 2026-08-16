# HIF 三选一评分模型设计

**日期：** 2026-08-15（同日第二轮 grill 修订：曲线族结构、数值解析路线、卡池边界、先验声明四项定案）
**状态：** 设计定案；离线链 A/B 已实施（2026-08-16，见 [`scoring-model-implementation-plan.md`](scoring-model-implementation-plan.md) 实施结果速览），待定 #6/#7 已实证关闭
**适用场景：** HIF 本战三选一（セレクトチェンジ変卡目标 / 技能卡奖励 / P ドリンク奖励 / SP 效果卡列表）
**前置阅读：** [`decision-override.md`](decision-override.md)（现有关键词评分与三层覆盖）、[`round1-blockers.md`](round1-blockers.md)、[`finals-daily-log.md`](finals-daily-log.md) 2026-08-15 各节

本文档沉淀「关键词启发式评分 → 结构化数值评分模型」的升级设计。第 3-4 节公式与分层为 grill 定案（两轮累计），不可改；第 5 节数据 schema 为 2026-08-15 阶段 0 实测记录；第 7 节为开放问题。

## 1. 现状模型分析（关键词启发式）

### 1.1 现有流程

三选一页逐张点选候选 → OCR 详情面板效果文本（纯白底深色字，如「レッスン中1回 好調7ターン 集中+3」）→ 按 `assets/data/hif/decision_keywords.json` 三倾向（`good_condition` / `focus` / `balanced`）关键词表线性加分（実機例：好調Nターン +6、集中 +2 → 合计 8 分）。实现于 `agent/hif/decisions/rewards.py`。

决策链（升级后保持不变）：

```text
名单优先（card_priority / drink_priority 命中卡名/饮料名直选，跳过评分）
  > 评分最高者确认（并列取先出现）
  > 最高分 < accept_threshold（4）且剩重抽次数（変卡 3 / 奖励 2）→ 重抽
```

参数覆盖链：GUI「HIF 决策微调」（MFA input 17 框体系）> `decision_override.json` 文件 > 倾向基准（见 `decision-override.md`）。

### 1.2 四盲区（実機 2026-08-15 实证）

| # | 盲区 | 実機例 | 根因 |
| --- | --- | --- | --- |
| 1 | 数值盲 | 好調3ターン 与 好調7ターン 同为 +6 | 关键词表按词给固定分，N 不进分值 |
| 2 | 无成本观 | -4 体力卡与 -2 体力卡同待遇 | 效果文本 OCR 里根本没有成本信息；master 表 `tiers.stamina_cost` 现成未用 |
| 3 | 无上下文 | 体力 35/35 满时「体力回復+5」照样满分 | 评分函数不接收局面状态 |
| 4 | 无手牌观 | 手牌已有多张好调卡时再来一张边际递减，模型不知 | 三选一页 UI 手牌不可见，且无累积跟踪 |

### 1.3 卡名链路实测（新模型可行性依据，実機 2026-08-15）

- 正常进程下，技能卡/変卡页候选卡名 **100% OCR 读出**（`agent/hif/adapters/card_dict.py` 用 master 121 卡词典约束候选集）。
- 读出卡名对 master 词典命中 **6/9**；miss 全为可归因噪声：「大声援+」类 **+ 号档位未归一**、「好調状能の提分」类 **OCR 误读**。
- 结论：卡名→权威数据的链路已打通且足够稳，效果数值可以不依赖效果文本 OCR，从数据侧直读。

## 2. 优化目标定义

- **HIF 胜利条件** = 審査基準最大化（Round1/Round2 演出得分）。
- **卡牌真值** = 进手牌后对最终审查基准的**边际贡献**——不是效果文本里写了几条，而是这张卡实际改变结局多少。
- **出牌策略先验**（2026-08-15 第二轮 grill 定案）：卡牌真值通过出牌实现，V 层内嵌一个出牌侧假设。P1 该先验**隐式由 tier 榜校准承载**（Game8/seesaawiki 排序本身就是跨 profile 的「平均怎么打」共识），`play.py`（莉波单角色硬编码启发式）**不接入**选卡模型——显式接入会把选卡评分绑死在一个角色上。P2 手牌跟踪落地后再以实际出牌记录精化。
- **社区 tier 榜**（Game8 等）= 玩家共识沉淀的边际贡献排序 → 可作**外部校准锚**（见第 4 节）。

## 3. 新模型设计（grill 定案）

### 3.0 总公式

```text
score(card, context) = V(effect, magnitude) × synergy(hand?) − C(cost, stamina_ratio)
```

三层职责：V 回答「效果值多少」，C 回答「代价多大」，synergy 回答「与现有手牌搭不搭」。乘法放 synergy（倍率语义、缺数据时可安全置 1），减法放 C（罚金语义、可为 0）。

### 3.1 V 层：效果价值曲线（五族 + 修饰系数层，2026-08-15 第二轮 grill 定案）

**按价值语义分族，一族一条曲线**：族内曲线形式统一、参数各异，复合卡（平均挂 2–3 条效果）按族拆解后求和。分族依据为 master 121 卡实测效果分布（族间不互斥，括号内为命中卡数）：

| 价值族 | 覆盖效果类型 | 曲线形式 |
| --- | --- | --- |
| 即得分 | パラメータ直加（55）；％转换（11，好印象/やる気のN%分）；倍率適用（11） | 直加与％转换线性（N% × 基准存量）；倍率適用做乘子作用于被修饰效果的值 |
| 状态增益 | 好調（37）/ 集中（37）/ 絶好調（6）/ 好印象（12）/ やる気（13），多带 Nターン 时限（51） | 递增饱和 `k×log₂(N+1)`（好調示例：3ターン≈10、7ターン≈15）× 终盘衰减（见 3.4）——解决盲区 1 |
| 行动经济 | 使用数追加（31）/ ドロー（21）/ 再演（1，特例并入） | 线性 × 手牌循环价值系数（每多打一轮，手牌整体价值复利一次）；系数承载出牌策略先验（第 2 节），待校准 |
| 资源续航 | 元気（32）/ 体力回復（11）/ 消費体力軽減（约13） | 线性；体力回復上下文敏感——当前体力比率越低价值越高，满体力时≈0——解决盲区 3 体力侧 |
| 代价妨害 | 眠気生成（5）/ 消費体力増加（2）/ トラブル参照（2） | 线性罚。本池无纯妨害卡，负面全部以自伤代价附着在高收益卡上 |

**修饰系数层**（非独立族）：条件発動（46）/ 使用可门槛（20）不产生独立价值，做折扣/放大系数作用于上述各族。P1 命中率先验同样由 tier 榜校准承载（第 2 节先验定案），不做显式条件建模。

> 注：首版草案口头清单（絶好調 / 再演 / ターン追加 / トラブル 等）与实测偏差大——ターン追加本池 **0 张**、再演 1 张、トラブル 2 张，反而漏了使用数追加（31）/ 元気（32）/ ドロー（21）三个大类，已由本表取代。

### 3.2 C 层：成本折算

- `stamina_cost` 按**当前体力比率**折罚：体力越低，同额体力消耗罚越重（低体力时一张 -4 卡可能直接压掉日程行动机会）——解决盲区 2。
- 集中消耗（`focus_cost`）、重複不可等结构性代价同层折算。

### 3.3 synergy 层：手牌协同（接口占位）

- 首版为**纯接口占位（soft signal）**：缺手牌数据时系数恒 = 1.0，**宁可不算、不可误判**。
- 激活后先做两条：同名重复递减（`noDeckDuplication` 之外的同质卡过剩）、好调卡计数饱和（手牌已有 N 张好调系时再来一张打折）。
- 数据来源是**累积手牌跟踪（P2 读牌库基础设施）**：三选一页 UI 看不到手牌，只能靠历史决策 + 出牌记录拼。激活时点见第 7 节。

### 3.4 局面信号（context 的获取方式）

| 信号 | 来源 | 现状 |
| --- | --- | --- |
| 体力 / 体力比率 | 三选一页顶部 HUD，现有 `_get_health`（`agent/custom/action/produce_hif.py`）即可读 | ✅ 现成 |
| 剩余日数 | 同一 HUD 区域倒计时面板 | ✅ 可读，接线待做 |
| 手牌快照 | UI 不可见，需累积跟踪 | ⏳ P2 |

剩余日数作为**终盘权重调节器**：调节**长线 buff（N ターン类增益）与即时得分类效果的权重**（终盘即时生效收益相对上调、需后续回合铺垫的长线效果相对下调，作用于 3.1 状态增益族的终盘衰减项）——解决盲区 3 的一半（体力侧由 C 层与资源续航族的上下文敏感曲线解决）。（第二轮 grill 修正：原表述「ターン追加类」本池实测 0 张，系事实错误。）

### 3.5 分值量级对齐

新模型输出**对齐现有体系量级**：经全局缩放系数校准后，好調7ターン（单效果）落在现有 ≈8 分档（现表 絶好調Nターン=8 / 好調Nターン=6），`accept_threshold=4` 的「值不值得占一次选择」语义不变，重抽行为与决策日志消费方式均不破坏。

## 4. 校准方案（双源交叉）

- **源 1：Game8 tier 榜** —— <https://game8.jp/gakuen-idolmaster/609862>。量大、标准化（S/A/B/C 分级）。
- **源 2：seesaawiki 決戦級編成一覧** —— <https://seesaawiki.jp/gakumasu/d/編成一覧>。更贴近 HIF 场景（決戦級編成即玩家对边际贡献的实战投票）。
- **冲突仲裁**：两源对同一卡分级不一致时，**以 HIF 场景共识为准**（seesaawiki 編成表优先，Game8 作正则化基准）。仲裁规则细化见第 7 节。
- **校准样本分层**（第二轮 grill 定案）：**实证层 88 卡**（master 実機白名单 ∩ 感性+通用流派，恰好每卡 4 档）为调参优先样本；流派层其余卡（约 82 张未実機实证）P1 不进校准集，只享受模型外推。
- **先验承载**：tier 榜排序同时承载出牌策略先验与条件発動命中率先验（第 2 节、3.1 修饰系数层），即「平均怎么打」被烘焙进调参目标，无需显式出牌建模。
- **方法**：把 S/A/B/C 级卡喂入模型调参（曲线参数 + 缩放系数），使**模型输出排序与社区共识排序的相关性最大化**；調参后对分歧样本（模型与榜差 ≥2 档）人工复核，作为下一轮曲线修正输入。

## 5. 数据依赖与 schema 实测（2026-08-15 阶段 0）

### 5.1 数据源

**vertesan/gakumasu-diff**（master.mdb 全量 dump），已 clone 至本仓 `.scrape/gakumasu-diff/`（不入库）。

### 5.2 ProduceCard.yaml 实测

约 103.6 万行、**1686 条**含档位变体记录；`upgradeCount` 分布 0/1/2/3 = **441/415/415/415**（即 無印/+/++/+++ 四档，1686 = 441 基础卡 × 档位展开）。

关键字段：

| 字段 | 例 | 用途 |
| --- | --- | --- |
| `id` | `p_card-01-act-1_002`（p_card-{星级}-{men/act}-{稀有度}_{编号}） | 主键，可接翻译数据按 id join |
| `name` | 軽い足取り | 卡名日文直出，对齐 OCR 链路 |
| `rarity` / `planType` / `category` | `ProduceCardRarity_R` / `ProduceCardCategory_Trouble` | 池筛选与负面类别识别 |
| `stamina` | 4 | C 层成本输入（现成） |
| `upgradeCount` | 0-3 | 档位，对应 master `tiers` 键 |
| `noDeckDuplication` / `isInitial` / `playMovePositionType` | — | synergy 与循环价值建模备用 |

**`produceDescriptions` 碎片化存储**——效果文本按显示片段拆条（「軽い足取り」的 パラメータ+6 好調2ターン 拆成 `text=パラメータ` / `+` / `6` / `好調` 四条，`effectValue1` / `turn` / `effectCount` 分散在各条目），结构化解析需 join `playEffects` / `produceCardStatusEffectId` 等关联表。**数值解析路线（第二轮 grill 定案）：直接做关联表 join，产出全量结构化效果数值**——不做「描述拼接文本 + 正则抽取」的中间路线；master `effect_raw` 纯文本降级为展示与对照基线。理由：五族曲线（3.1）需要权威数值输入，正则抽取存在解析失败兜底分支，而 join 一次到位且后续扩池免重做。join 实现为下一阶段任务（本文档只定路线）。

### 5.3 与现有 master 表的对账

- 现有 `assets/data/hif/skill_cards_master.json`（seesaawiki 121 卡）名称在 diff 中命中 **120/121**。
- 唯一 miss「コール&レスポンス」（wiki_id `com_S_SSR_A_0001`）：复核确认为**半角/全角 `&` 差异**（diff 侧写作「コール＆レスポンス」全角＆），归一化即可消除，非数据缺失。补录后确认其 **planType = Plan1（感性）**，4 档俱全（diff id `p_card-01-act-3_030`）。
- **planType 交叉验证（第二轮 grill 实测）**：master 121 卡的 `plan_type` 与 diff `planType` 经 `diff_ids` 直连比对 **100% 一致（0 mismatch）**，两表同维度，流派过滤可直接以 diff 为准。

### 5.4 ProduceDrink.yaml 实测

**29 条**（旧 `drinks.json` 28 条，新增「初星スペシャル青汁X」）。字段：`id` / `name` / `rarity` / `planType` / `produceDrinkEffectIds` / `effectGroupIds` / `originSupportCardId`。效果数值同样在关联表（`produceDrinkEffectIds` 所指），解析路线同 5.2 定案（关联表 join）。

**流派过滤口径（第二轮 grill）**：planType 分布 Common 11 / Plan1 6 / Plan2 6 / Plan3 6 → 莉波感性路线可用 **17 种**（11 通用 + 6 感性），其余 12 种为遇不到的死数据，词典与评分同口径剔除。

### 5.5 HIF 池界定（流派过滤池，第二轮 grill 定案）

`ExamInitialDeck` 等表未检出 `fes` 关键字，HIF 专属子池无法直接圈出——但**偶像流派给出了结构化上界**：HIF 培育固定偶像姫崎莉波走感性（sense）路线，実機只会出现**感性専用 + 通用**卡。`ProduceDescriptionProducePlan.yaml` 明示枚举语义：`Plan1`=【センス専用】、`Plan2`=【ロジック専用】、`Plan3`=【アノマリー専用】、`Common`=共通。

**池边界 = `planType ∈ {Plan1, Common}`**：

| 口径 | 卡数 | 档位记录 |
| --- | --- | --- |
| diff 全 DB（流派过滤后） | 170 去重卡 | 653 |
| 実機实证层（master 121 ∩ 流派过滤） | **88 卡**（68 Plan1 + 20 Common，每卡恰好 4 档） | 352 |
| 死代码（master 121 中 Plan2 19 + Plan3 13，遇不到） | 32 卡 | 剔除 |

- **OCR 词典与数值评分圈定流派过滤池**（170 卡剔除其他 sense 偶像固有卡后的余量），实证层 88 卡为校准优先样本（第 4 节）。
- master 121 卡中 **32 张 Plan2/Plan3 卡为莉波路线遇不到的死代码卡**，从词典剔除（收缩误匹配面）。
- 白名单外候选仍走关键词兜底（见第 6 节）；実機观察到流派过滤池外的感性卡时，作为数据修正输入而非直接扩池。
- 残留问题：其他 sense 偶像固有卡的识别字段（`originSupportCardId` / id 模式）与剔除实现、82 张未实证卡的置信度处理，见第 7 节。

### 5.6 其他依赖

- **GUI 三层覆盖链接入点**：MFA input 17 框体系（`assets/tasks/produce_cn.json`「HIF 决策微调」组）。新模型参数（缩放系数、终盘权重等）如需暴露，沿用该组扩框，不改覆盖链语义。
- **中文翻译（可选）**：接 chinosk6/GakumasTranslationData 的 `masterTrans/ProduceCard.json`（约 20MB，按 `id` join），仅影响日志可读性，不影响评分。

## 6. 迁移路径

1. **卡名命中流派过滤池词典**（`planType ∈ {Plan1, Common}` 的 170 卡口径，剔除非莉波固有卡；含 + 档位拆分，`agent/hif/decisions/hand_meta.py` 已有按档位查 tier 的现成入口）→ **新模型评分**：效果与成本读 **diff 关联表 join 产物**（5.2 定案），OCR 读错效果文本不再影响分数。词典从 121 白名单扩到流派过滤池后，実機遇未实证感性卡不再降级。
2. **卡名 miss** → **退回现有关键词评分兜底**，行为与现状完全一致（升级前后断崖为零）。
3. **上线前离线回放**：用 2026-08-15 実機决策日志（`debug/decisions/session-20260815.jsonl`，63 条三选一相关记录）逐条跑新旧双评分，输出**新旧分数差异表人工审**——重点看排名翻转是否都发生在盲区案例（数值/成本/上下文）上，而非噪声翻转。
4. **关键词评分链路不拆除**：长期作为兜底 + 新模型的对照基线（差异表持续生成，供校准回归）。

## 7. 待定问题清单

| # | 问题 | 备注 |
| --- | --- | --- |
| 1 | ~~V 曲线具体形式与曲线族完整定义~~ **已关闭（第二轮 grill）** | 五族 + 修饰系数层定案（3.1），族内曲线形式定，具体参数留给校准（第 4 节） |
| 2 | 编辑距离 vs 字形相似度 | OCR 卡名变体兜底匹配，假名汉字混排效果待误读样本积累后验证 |
| 3 | 校准数据冲突仲裁规则细化 | 4 节只定了「HIF 场景共识优先」总原则 |
| 4 | ~~`produceDescriptions` 碎片重组 vs 关联表 join~~ **已关闭（第二轮 grill）** | 定案关联表 join（5.2），join 脚本实现为下一阶段任务 |
| 5 | 手牌跟踪（P2 读牌库）激活 synergy 层的时点 | 依赖 Round1 出牌闭环与决策日志回填 |
| 6 | ~~其他 sense 偶像固有卡的识别与剔除~~ **已关闭（2026-08-16 実機实证）** | 実機 88 卡实证层 origin 分布一锤定音：`i_card-hrnm-*` 7 张全在实证层（hrnm=姫崎莉波，保留）；`s_card-*` 支援卡固有 30 张全在实证层（支援编成带入，保留）；其余偶像固有（amao/fktn/hski 等）与 `originCharacterId=nasr`（「先生でアイドル！」）实证层零出现 → 标记 `is_idol_exclusive` 剔除（产物落盘 48 张） |
| 7 | ~~82 张未实证卡的置信度处理~~ **已关闭（2026-08-16）** | 产物逐卡落 `master_verified` 布尔标记（diff_ids 命中 88 卡 = 高置信）；未实证卡不降权，进词典享受模型外推，実機观察到异常时按 5.5 数据修正流程处理 |

## 参考

### 外部

- Game8 スキルカード tier 榜：<https://game8.jp/gakuen-idolmaster/609862>
- seesaawiki 決戦級編成一覧：<https://seesaawiki.jp/gakumasu/d/編成一覧>
- vertesan/gakumasu-diff（master.mdb dump）：<https://github.com/vertesan/gakumasu-diff>
- chinosk6/GakumasTranslationData：<https://github.com/chinosk6/GakumasTranslationData>

### 本仓库代码与数据

- `agent/hif/decisions/rewards.py` —— 现有关键词评分（升级后为兜底）
- `agent/hif/decisions/hand_meta.py` —— master 121 卡查表（含档位 tier）
- `agent/hif/adapters/card_dict.py` —— OCR 卡名词典（121 卡约束）
- `agent/custom/action/produce_hif.py` —— 三选一 action 与 `_get_health` 体力读取
- `assets/data/hif/decision_keywords.json` / `skill_cards_master.json` / `drinks.json`
- `assets/tasks/produce_cn.json` —— GUI「HIF 决策微调」17 输入框
- `debug/decisions/session-20260815.jsonl` —— 离线回放基线日志

### 关联文档

- [`scoring-model-implementation-plan.md`](scoring-model-implementation-plan.md) —— 实施计划（离线链 A→B→C，2026-08-16 批准）
- [`decision-override.md`](decision-override.md) —— 现有评分规则与三层覆盖
- [`finals-daily-log.md`](finals-daily-log.md) —— 2026-08-15 各実機会话记录
- [`round1-blockers.md`](round1-blockers.md) —— 実機验证清单与遗留问题
- [`evaluation.md`](evaluation.md) —— 審査基準与评价体系背景
- [`../superpowers/specs/2026-07-10-hif-basic-pipeline-design.md`](../superpowers/specs/2026-07-10-hif-basic-pipeline-design.md) —— HIF 首版管线设计（分层原则来源）
