# Plan: HIF MVP 全流程闭环

_经用户与 Codex 于 2026-07-15 逐项确认。未经新的用户决策，不扩大路线、资源或发布范围。_

## 1. 目标

在 MuMu 模拟器 12、日文原版、ADB 原始 `720x1280` 环境下，使
`rinami_garakuta_road` 从正式 HIF 入口启动，经正式 MaaFramework Pipeline 完成必经主链与不可规避的随机页面，
取得 `優勝` 结算并回到可控状态。

最终验收必须由一次新的 HIF 培育完成，并满足：

- 单次正式任务从 HIF 入口运行至 `優勝` 结算；
- 不使用 ADB 手工点击、`hif_live_runner` 调试入口或人工拼接续跑；
- 通信错误只允许由正式恢复路径恢复同一局；
- 任何 `UnknownStop`、人工接管、调试探针介入或非优胜结算均判定本次验收失败。

## 2. 范围

### 2.1 本轮包含

- HIF 正式入口、选拔、本战准备及日程推进；
- Round1、Interval、Round2；
- 当前预设的必经页面和无法由策略规避的随机页面类别；
- 奖励、Live、回忆、结算与返回可控状态；
- 当前路线所需的状态读取、卡牌效果模型和确定性路线评分器；
- 失败页安全停止、通信错误恢复和动作语义后验；
- 实机证据、离线测试、覆盖矩阵和最终验收报告。

### 2.2 本轮不包含

- 其他偶像、流派、语言或 DMM 泛化；
- 穷举所有可选商店、资源消耗和非当前预设分支；
- 特定高评价等级或目标分数；
- Sparse Expectimax、高保真全局模拟器或多角色通用决策引擎作为 MVP 阻塞项；
- 发布、打包、推送、PR 或主线同步。

未进入当前验收路径的可选分支可以保持安全停止，但必须记录限制，不能宣称通用 HIF 支持。

## 3. 权威基线与版本控制

- 集成分支：`codex/hif-mvp-integration`。
- 创建基点：`fd4d72d docs: 拆分 HIF 决策算法计划`。
- 当前主工作区中已经过实机采证和离线验证的 HIF 差异是唯一待整理的实现基线。
- `.worktrees/hif-round1` 基于更早分叉点，只允许只读比较和按功能择取；禁止整体合并。
- 不回退、覆盖或清理用户已有修改和无关未跟踪文件。

基线收口顺序：

1. 审查并单独提交 `plans/decision-algorithm/**` 中尚未提交的冻结规格。
2. 在 `codex/hif-mvp-integration` 上按逻辑整理当前 HIF 源码、测试、配置、资源和文档差异。
3. 排除 `debug/`、日志、Journal、视频、模型、压缩包和无关未跟踪文件。
4. 通过基线门禁后建立各子任务 worktree。

允许本地中文 Conventional Commits。子 agent 只在自己的分支形成小而完整的提交，由主整合 agent 审查后择取。
未经用户再次确认，不 push、不创建 PR、不发布。

## 4. 并发模型

当前并发上限为 4 个活动 agent（含主 agent）。所有子 agent 使用平台分配的模型；工具不支持指定
`gpt-5.6-terra` 或 reasoning effort。每个任务提示必须明确要求高深度分析、完整取证、最小改动和严格验证。

### 4.1 主整合 agent

独占：

- `agent/custom/action/produce_hif.py`
- `assets/resource/base/pipeline/ProduceHIF.json`
- `tools/hif_live_runner.py`
- HIF Session、正式根路由及主路由测试
- 模拟器控制、Journal 审计和本目录文档

职责：

- 建立基线与 worktree；
- 审查、择取并集成子提交；
- 串行执行全部实机输入；
- 补齐页面 Action、正式 Pipeline 和语义后验；
- 维护里程碑文档并完成最终验收。

### 4.2 状态读取 agent

独占：

- `agent/hif/adapters/**` 中经任务明确分配的读取器；
- `agent/hif/calibration.py`
- `agent/hif/round_metrics.py`
- `assets/data/hif/roi_calibration.json`
- 对应的独立测试文件。

交付：

- 当前分数、倍率、回合、体力、状态、手牌、灰卡、牌库数量和必要参数的严格读取；
- 动作所需字段的完整性报告；
- 重启后的状态重建与账本对账纯逻辑；
- 成功、缺失、冲突和过期状态测试。

不得直接修改正式 Pipeline、实机 Action 或调试 runner；需要新实机帧时向主 agent 请求。

### 4.3 路线评分器 agent

独占新的路线策略/卡牌模型目录及专属测试，不直接接入 Pipeline。

交付：

- 当前路线卡牌与强化等级的结构化效果；
- 基于可信状态和可打手牌的确定性评分器；
- 硬门禁、可解释分项、唯一目标和并列拒绝；
- observed case 与负向夹具。

禁止硬编码当前局固定出牌顺序、截图指纹、历史坐标或过期状态。未知卡、状态缺失、灰卡或目标不唯一时必须拒绝。

### 4.4 Pipeline 审计 agent

首轮只读，负责：

- 审计 Round1 之后到结算的正式节点、路由优先级、Action、后验和覆盖矩阵；
- 区分必经、不可规避随机、可规避和历史孤立分支；
- 只读比较 `.worktrees/hif-round1`，列出可取能力和冲突文件；
- 向主 agent 提交证据化缺口清单。

若后续补充测试或夹具，只能新增经主 agent 分配的独立文件。

### 4.5 决策核心 agent

Pipeline 审计释放并发槽位后，在干净的 `codex/decision-core` worktree 中启动：

- 仅修改 `agent/decision_algorithm/**`、`decision_algorithm_tests/**` 和本任务明确分配的决策规格；
- 决策日志与 `HIFJournal` 完全隔离，通过 `run_id / decision_id / action_id` 关联；
- 不接入 HIF Pipeline，不阻塞 MVP，不修改 HIF 热点文件。

### 4.6 Pipeline 专项技能

涉及 Pipeline 文档、节点、选项或测试时，主 agent 和对应子 agent 必须先使用以下技能：

- `C:\Users\haneball\.codex\skills\pipeline-guide`：设计、修改和审查 Pipeline JSON；
- `C:\Users\haneball\.codex\skills\pipeline-generate`：基于设备 OCR 生成新文本节点并通过 ROI sweep 校准；
- `C:\Users\haneball\.codex\skills\pipeline-option`：新增或修改用户选项、override 和预定义节点；
- `C:\Users\haneball\.codex\skills\pipeline-testing`：节点级实测、页面恢复和资源保护。

使用约束：

- 技能中的示例仓库路径、通用节点名和 `assets/interface.json` 结构来自其他项目，只采用协议和工作流，不得原样复制；
- 本仓库仍以 `AGENTS.md`、`assets/tasks/produce.json`、`assets/tasks/produce_cn.json`、
  `assets/resource/base/pipeline/ProduceHIF.json` 及现有 HIF 工具为准；
- 有限页面流程优先使用 `next + [JumpBack]` 状态机，Python 只承载无法由 Pipeline 表达的运行时业务逻辑；
- OCR 节点先检查当前原始帧和 OCR 结果，再做受限 ROI sweep；不得因首次 OCR 失败直接改用 TemplateMatch；
- 用户选项必须同步选项定义、任务注册、预定义节点和已有语言/任务变体；能用 pure override 时不新增 Flag + Python 分支；
- `run_pipeline` 的单文件结果不能证明跨文件引用正确；跨文件状态机必须通过全资源 Pipeline 检查和正式 GUI/CLI 集成测试；
- Click/Swipe 测试必须确认返回路径和资源影响，禁止为测试点击付费、购买、开局确认或其他不可逆控件；
- 技能依赖的 `maa-mcp` 或脚本不可用时，记录限制，并使用仓库现有等价工具完成同等证据门槛，不安装来源不明的替代实现。

## 5. 状态真值与评分器约束

### 5.1 状态真值

采用“当前画面观测 + 同一局已验证账本”：

- 画面可见字段必须重新读取；
- 无法持续显示的字段只能由已验证动作后验和持久化局内账本推导；
- 禁止用默认 `0`、历史样本或过期 Session 补值；
- 重启后必须重新扫描并对账，无法证明一致就安全停止；
- 每个动作只要求其决策和后验真正依赖的字段完整，不以无关字段阻塞。

### 5.2 最小路线评分器

- 每个动作前从最新可信状态重新评分；
- 使用显式硬门禁、确定性加权和有限短视评估；
- 输出唯一、可解释的卡牌目标或类型化拒绝；
- 暂不要求完整牌局模拟器或 Sparse Expectimax；
- 决策输出不能绕过目标绑定、两段式确认和动作后语义验证。

## 6. 实机策略

### 6.1 两阶段实测

1. 当前局是探路样本：允许受限单步探针，用于补齐 Round1 后续、Interval、Round2 和结算证据。
2. 缺口修复后另开一局：只能使用正式 Pipeline，从入口无人工拼接地完成最终验收。

当前局包含历史手工恢复、独立探针和误点击，不能作为最终端到端成功证明。

### 6.2 证据门槛

- 历史视频和旧截图只允许建立页面分类、候选 ROI 和离线测试；
- 新的状态改变 Action 必须有当前探路局原始帧、唯一前置目标和动作后语义后验；
- 首次遇到未实证页面时必须停止、采证、写失败测试、最小修复并回归后再恢复；
- 不以帧变化、动画结束、按钮消失或动作次数推断成功。

### 6.3 Round 开放门槛

Round1 与 Round2 分别独立达到：

- 至少 8 个完整状态、唯一目标和语义后验均成立的单卡成功样本；
- 至少 2 个不同原因的零危险输入拒绝样本；
- 拒绝至少覆盖灰卡和状态/标题门槛不满足。

达到各自 `8+2` 前只能单步。达到后才允许该 Round 的有界循环，并继续保留每步重读、重新决策、动作绑定和后验。

## 7. 资源和执行授权

在已确认路线、设备和账号内，主整合 agent 无需逐页请示，可以：

- 只读采证、修改代码、补测试和运行验证；
- 对具备唯一目标、明确前置和语义后验的动作执行受限输入；
- 使用当前局或最终验收局内的 P 点、饮料、道具和免费重试；
- 消耗一次正常新 HIF 培育所需的体力、票券或免费次数；
- 通信错误时恢复同一局。

始终禁止：

- 付费宝石、现实货币、付费补充或购买；
- 登录凭据、账号切换、账号设置或其他账户级操作；
- 猜测页面、按钮、候选、坐标、文本或时序；
- 为获取覆盖率主动进入可规避的资源消耗分支；
- 主动放弃后反复开局；
- 未经确认的 push、PR、发布或打包。

## 8. 里程碑

### M0：权威基线

- 决策规格与当前 HIF 差异按范围形成可审查本地提交；
- 集成分支和三个隔离 worktree 建立；
- 基线验证通过；
- 更新 `STATUS.md`。

### M1：并行能力完成并集成

- 状态读取、最小路线评分器和 Pipeline 审计完成；
- 子提交经主 agent 审查并集成；
- 普通 `ProduceCardsHIF` 能消费完整可信状态并输出唯一决策或安全拒绝；
- 更新 `STATUS.md`，涉及实机证据时同步 `HANDOFF.md`。

### M2：Round1 `8+2`

- Round1 达到独立 `8+2`；
- 有界循环安全开放；
- 当前探路局进入已识别的 Interval 或后续页面；
- 更新 `STATUS.md` 和 `HANDOFF.md`。

### M3：当前探路局闭环

- Interval、Round2 独立 `8+2`、后续主链和结算均完成实证；
- 当前局到达正常结算，所有经过页面具备前置、输入和后验；
- 正式 Pipeline 具备启动最终验收局的条件；
- 更新 `STATUS.md` 和 `HANDOFF.md`。

### M4：最终 MVP 验收

- 新局由正式任务从 HIF 入口无人工干预运行；
- 到达 `優勝` 结算并回到可控状态；
- 完整审计 Journal、控制器日志、资源使用和恢复记录；
- 全部离线与结构门禁通过；
- 更新 `STATUS.md`、`HANDOFF.md` 和最终限制说明。

## 9. 验证门禁

基线、每次子提交集成和每个里程碑至少运行：

```powershell
python -m pytest -q tests -k hif
python tools/hif_pipeline_check.py
python -m py_compile agent/hif/*.py agent/hif/adapters/*.py agent/custom/action/produce_hif.py tools/hif_*.py
python -m ruff check agent/custom/action/produce_hif.py agent/hif tests/test_hif_*.py tools/hif_pipeline_check.py tools/hif_live_runner.py
npx prettier --check "assets/data/hif/*.json" "assets/data/hif/**/*.json"
git diff --check
```

最终交付前运行：

```powershell
python -m pytest -q
```

每次实机输入前后还必须审计：

- 唯一 `run-id`；
- 原始 `720x1280` 前后帧；
- Journal 中的状态、决策、审批、输入和停止原因；
- Maa 日志中的全部 Click/Swipe；
- 动作后的页面与领域语义；
- 是否存在未声明输入或资源消耗。

Pipeline 改动还必须按专项技能增加以下门禁：

- 节点遵循“识别 → 操作 → 识别”，每个状态改变动作具有明确后继识别；
- 所有 ROI、目标和模板以 ADB 原始 `720x1280` 为基准；
- OCR 新节点保存 sweep 候选、最终 ROI、置信度和当前页面证据；
- 新选项同步任务定义、任务 option 注册、预定义节点及 `produce.json / produce_cn.json`；
- 单节点测试与全 bundle 集成测试分开记录，跨文件引用不得只用单文件 `run_pipeline` 验收；
- 测试前后核对页面恢复路径和所有控制器输入，确认没有未授权资源操作。

## 10. 硬停止条件

出现以下任一情况，保存证据并停止：

- 页面、按钮、候选或目标不唯一；
- 必需状态缺失、冲突或无法与账本对齐；
- 点击后无法建立领域语义后验；
- 需要付费、账号操作、主动放弃或反复开局；
- ADB 指向不同实例或恢复页面不能证明属于同一局；
- 当前局发生无法从实机与 Journal 重建的外部变化；
- 修复需要越过已确认路线、文件所有权或 MVP 范围。

## 11. 完成定义

只有同时满足以下条件才完成：

- M0～M4 全部完成并有文档记录；
- 正式新局从入口到 `優勝` 结算无人工拼接；
- Round1、Round2 分别通过独立 `8+2`；
- 实际经过的全部页面具有可审计前置、输入和后验；
- 全仓测试、HIF 专项、Pipeline、编译、Ruff、格式和差异检查通过；
- 未提交 `debug/`、Journal、日志、视频、模型或无关文件；
- 当前限制、未覆盖分支和后续决策核心状态均如实记录；
- 未经用户确认不 push、不发布。

## 12. Day1 场景3变卡专项设计（测试流程）

_经用户于 2026-07-20 逐项确认。本节仅定义 `TEST_HIF_day1.json` 的 Day1 场景3测试闭环；在取得专项实机证据前，不接入正式 `ProduceHIF.json`。_

### 12.1 范围与入口

- 入口是 `hif_day1_场景3_标志`，仅接受当前日文原版、MuMu 模拟器 12、ADB 原始 `720x1280` 的变卡候选页。
- 现有测试文件中三个无识别的硬坐标槽位点击仅是历史探索，不可复用为正式页面契约。
- 正式流程已有 `ProduceChooseHIFSelectChangeTargetAuto`、`ProduceChooseHIFSelectChangeSourceAuto` 和结果观察器；专项实现应复用其截图、OCR、YOLO 网格扫描、来源确认和 Journal 骨架，不另建 Python 编排器。
- 所有输入只在测试入口、用户已明确授权且执行模式允许时发送。每个不可逆点击仍遵循本计划第 6、7、9、10 节的单击、后验和安全停止要求。

### 12.2 已确认状态机

```text
hif_day1_场景3_标志
  -> TestHIFDay1ChangeDeckSnapshot
  -> TestHIFDay1ChangeCandidatesAndDecision
  -> TestHIFDay1ChangeSelectTarget
  -> TestHIFDay1ChangeSourceFlag
  -> TestHIFDay1ChangeSelectSource
  -> TestHIFDay1ChangeResultObserve
  -> unknownstop
```

1. `TestHIFDay1ChangeDeckSnapshot` 在候选页打开右下角牌库入口，完整浏览来源牌库，关闭后确认已回到同一候选页。该动作是原子的：打开、扫描、关闭或回页任一环节失败，快照作废并进入 `unknownstop`。
2. `TestHIFDay1ChangeCandidatesAndDecision` 读取再抽次数，依次点击左、中、右三个候选槽位并读取详情，然后一次性做出决策。它绝不点击“再抽选”。
3. `TestHIFDay1ChangeSelectTarget` 基于当前帧和已落盘决策选中目标候选卡，点击“次へ”，且后态只能是来源牌库页。
4. `TestHIFDay1ChangeSourceFlag` 以来源页双锚点确认页面和顶部目标预览，禁止沿用候选页坐标。
5. `TestHIFDay1ChangeSelectSource` 重新扫描并定位来源实例，选中后验证选中态，再单击“チェンジ”。后态只能是变卡结果页。
6. `TestHIFDay1ChangeResultObserve` OCR 验证“来源卡 -> 目标卡”，记录结果并停在结果页；不关闭弹窗、不继续日程。

页面锚点、唯一目标、执行模式、前后帧或领域后验任一项缺失，均不得猜测下一步，直接安全停止。

### 12.3 牌库、候选与决策契约

牌库扫描必须到达底部。到底由滚动条底部或重复页面签名确认，且有安全页数上限。每张已识别牌记录：`card_id`、规范化日文名、强化状态、详情校验文本、页签名、页码、槽位和置信度。身份由日文名与详情交叉校验映射到本地卡牌字典，不能只靠卡名。

- 未识别卡允许出现在牌库中，快照设置 `deck_complete=false` 并记录 `missing_slots`；决策和点击不得使用未知卡。
- 同一 `card_id + 强化状态` 的重复卡可互换；最终来源页选择最先重新验证到的实例。
- 同一槽位最多点击一次；点击后详情 OCR 最多补读一次。仍无法识别时标为未知，不重试点击，不把上一个槽位的详情当作当前卡。
- 再抽次数仅作为 `ChangeContext.reroll_count` 的决策数据。用户手动再抽后，必须重新确认候选页锚点并只重扫候选卡、重新决策；已有牌库快照保留。未发生再抽时，不做冗余的候选预验证。

决策模块同进程接收 `ChangeContext`，返回一个结构化 `ChangeDecision`：

```text
kind: preferred_select | forced_fallback | blocked
target: 候选 card_id + 当前槽位
source: 已识别来源实例
reasons: 可审计的评分与并列决策依据
```

- 不存在“跳过变卡”结果。可识别组合存在时，`forced_fallback` 选择损失最小的组合并在测试模式下提交；候选并列按左、中、右，来源并列按页码小、槽位靠前。
- 只有没有任何已识别、可提交组合时才返回 `blocked` 并停止。流程完成优先，但未知卡绝不被自动选择。

### 12.4 快照、日志与恢复

- 继续复用 `HIFJournal` 的 `debug/hif-journal/<session_id>.jsonl` 与证据帧；每次读取、点击、滑动、页面切换、决策和停止均写入结构化事件，并向 `debug/maa.log` 写一行人类可读摘要。
- 每个 session 另写 `debug/hif-snapshots/<session_id>.json`，通过临时文件后原子替换。它是审计和显式恢复记录，不取代当前帧识别或 Maa Pipeline 状态。
- 快照只保存恢复必需字段：版本、`session_id`、阶段、候选、来源实例、`missing_slots`、`deck_complete`、再抽次数、决策、证据帧引用和更新时间；原始 PNG 仍只由 Journal 保存。
- 恢复必须显式提供 `resume_session_id`。读取快照后重验当前页面、目标预览和待执行阶段；任何不匹配都停止，不能从旧坐标或旧内存继续点击。
- `verified` 只用于具有动作前后帧且帧已变化的动作。纯结果读取写为 `observed`，避免现有 Journal 审计把“缺少 after 帧的 verified 记录”误判为成功。

### 12.5 实机证据门槛

下列页面证据尚未完整采集，实施前不得补猜 ROI、模板、按钮坐标或滑动参数：

1. 候选页点击右下角牌库入口后的页面；
2. 牌库底部及到底判据；
3. 关闭牌库后重新回到候选页；
4. 提交“チェンジ”后的结果页，且能读取替换前后卡名。

每张证据需记录游戏版本、日文原版、MuMu、`720x1280`、任务选项、分支/提交和 `session_id`。原始截图、Journal 与 Maa 日志只留在 `debug/`，不提交。

### 12.6 实施与验收顺序

1. 先补齐第 12.5 节的实机页面证据和测试夹具，建立候选页、牌库页、来源页、结果页的明确契约。
2. 为牌库完整扫描、未知卡排除、重复实例重定位、手动再抽仅重扫候选、快照原子读写与恢复页不匹配分别新增离线失败测试。
3. 在 `TEST_HIF_day1.json` 落最小状态链和 `on_error: ["unknownstop"]`，再改造已有变卡 CustomAction；不得先接入正式流程。
4. 运行 HIF 专项 Pipeline/Action 测试、`python -m py_compile agent/custom/action/produce_hif.py`、JSON 检查与 `git diff --check`。
5. 只在上述门禁通过且用户再次授权实机输入后，执行一次完整测试链路，并用 `tools/hif_journal_audit.py` 审计前后帧、决策、点击和结果页停止。

完成测试闭环后，才更新 `docs/hif/testing.md`、`docs/hif/architecture.md` 及与实机证据对应的 `docs/hif/resources.md` / `docs/hif/observations.md`；在此之前，本节是待实施规格，不把单次观察升级为游戏机制事实。
