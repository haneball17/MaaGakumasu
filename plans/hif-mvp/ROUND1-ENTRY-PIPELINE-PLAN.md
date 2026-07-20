# HIF 本战入口至 Round1 管线补全方案

_状态：实施提案。2026-07-16。未替代已冻结的 `PLAN.MD`；不授权实机输入、连续出牌、发布或推送。_

## 1. 目标和边界

首期正式验收目标固定为：在 MuMu 12、日文原版、ADB 原始 `720x1280` 下，正式 MaaFramework 任务从游戏主界面进入 HIF 本战，完成本战准备剩余 `6` 至 `1` 日和实际遇到的必经页面，到达 Round1 后由 `ProduceHIFRound1ReachedStop` 停止。

本期不包含：Round1 出牌、Interval、Round2、优胜结算、扩展偶像/路线、DMM/汉化泛化。`Day1` 至 `Day20` 是离线选拔模拟的日程，不是本战入口；本方案只处理本战准备的剩余日。

Round1 是边界而非失败：当前卡牌语义后验和动态效果读取未达到自动输入门槛，必须继续保持单步观察/安全停止。

## 2. 管线设计

```text
主界面
  | ProduceEntryHIF
  v
HIF 入口 / 本战模式 / 偶像和支援选择 / 开始确认
  | 每次输入后回到总路由器重新识别
  v
本战准备（remaining_day=6..1）
  | 日程选择 + 二次确认 + 后页语义后验
  +-- 课程 / 奖励 / 饮料满仓 / Select Change / 咨询
  |       `-- [JumpBack] ProduceEntryHIF
  v
本战前排名
  | 只接受后态 round1
  v
Round1
  `-- ProduceHIFRound1ReachedStop / StopTask
```

`ProduceEntryHIF` 继续是单一总路由器。JSON Pipeline 负责有限页面状态机、识别优先级和 `[JumpBack]` 返回；Python Custom Action 只负责状态读取、路线选择、二次确认、前后语义后验和 Journal。不得用 Python 循环模拟跨页路由，也不得用固定延迟或 `SafeAdvance` 穿过未知页。

所有状态改变路径遵循：`识别 -> 唯一目标 -> 输入 -> 后态识别 -> 领域语义后验 -> 回到总路由器`。未知页面、候选不唯一、状态缺失或后态无法解释均进入 `ProduceHIFUnknownStop`。

## 3. 实施工作包

### P0：基线和结构门禁

1. 修复 `tools/hif_screen_profile_check.py` 的 `review_sections` 预期值 `34/35` 漂移；以 profile 契约和 `tests/test_hif_screen_profiles.py` 的 `35` 为准，不删 profile 条目迎合旧工具。
2. 增加工具回归测试：正确 profile 通过；少一个 section 时稳定失败并输出原因码。
3. 记录当前 HIF 范围、脚本版本和限制；不纳入 `debug/`、Journal、视频、模型或其他既有未跟踪文件。

完成条件：profile check、HIF 定向测试、Pipeline check 均绿，且无运行时行为扩大。

### P1：入口至开始确认

1. 为主界面、HIF 入口、本战模式、偶像/支援、`プロデュース開始` 建立页面分类正反 fixture。
2. 审计 `assets/tasks/produce.json` 的 `ProduceEntryHIF` 覆盖和 `ProduceHIFChooseFinalModeAuto` 参数传递；只允许 `entry_mode=finals`。
3. 每个确认动作补后态断言：下一个已知入口页、局内 run id 或开始确认页；禁止仅凭按钮消失判成功。
4. 入口重复触发、错误模式、分辨率非 `720x1280`、未知页面必须零输入停止。

完成条件：离线证明入口只能走本战；实机采样后可受控进入本战准备 `remaining_day=6`。

### P2：本战准备日程闭环

1. 将 `remaining_day=6..1` 作为本战唯一日程键；读取失败、超范围或候选缺失时拒绝。
2. 对每种实际出现的日程分支建立最小闭环：日程页识别、候选读取、唯一选择、首次选中、二次确认、目标后页验证、返回日程/总路由器。
3. 覆盖当前路线可能经过的课程、奖励、饮料满仓、Select Change、咨询和弹窗；未遇到分支保留 `UnknownStop`，不猜页面。
4. 页面识别优先级保持“确认/阻塞页优先于日程页”；所有子页处理完以 `[JumpBack]` 回到 `ProduceEntryHIF`，避免局部状态机漂移。

完成条件：Day6 至 Day1 每个实际经过分支均有正向 fixture、负向 fixture、输入前后帧和 Journal 后验；无分支使用盲点按或固定等待绕过。

### P3：排名至 Round1 停止点

1. 为本战前排名页补真实帧 fixture 与反例，固定 `ProduceHIFRankingsAuto` 的唯一后态为 `round1`。
2. 页面不为 Round1、排名点击无变化、出现未知过渡页时停止并保留证据。
3. `ProduceHIFRound1Observe` 仅读取和记录状态，立即调用 `ProduceHIFRound1ReachedStop`；任何评分结果、卡牌识别或手牌详情不得发出点击。

完成条件：正式 Pipeline 到达 Round1 后有明确 `StopTask`，控制器日志中不存在 Round1 卡牌、SKIP、奖励或详情输入。

### P4：数据目录的非阻塞接入

1. 按 `DATA-CATALOG-INTEGRATION.md` 先完成 F0：解决 `始まりの合図` 的 `hif-release` 门禁漂移，补来源/AST/测试或降级为拒绝；不得只改支持标签。
2. F1-F3 仅生成受限效果投影、影子绑定和版本化 Journal；不改 `ProduceHIF.json`、不扩大执行权限。
3. P1-P3 只依赖页面路由和日程策略，不等待 Round1 卡牌目录变绿；数据投影将来只作为 Round1 单卡门禁的附加前置。

完成条件：入口管线与卡牌建模解耦；任一 catalog 缺失只能阻断出牌，不能阻断“到 Round1 后停止”。

### P5：正式端到端验收

1. 先完成全部离线门禁和逐段实机采样，再开始一局新的验收局。
2. 从主界面仅启动正式任务，不允许 ADB 手点、`hif_live_runner` 拼接、人工接管或调试探针续跑。
3. 每个不可逆动作保存原始前后帧、run id、Journal、Maa 控制器日志、页面分类和领域后验。
4. 到达 Round1 立即停止；审计无未声明输入、无 `UnknownStop`、无人工接管，才判通过。

## 4. 测试矩阵

| 层 | 覆盖 | 必须失败的反例 |
| --- | --- | --- |
| 页面分类 | 入口、开始确认、Day6..1、课程、奖励、饮料、换卡、咨询、排名、Round1 | 相邻页面、错误分辨率、缺关键 ROI |
| Action | 日程两段确认、子页返回、排名转场、Round1 停止 | 目标不唯一、候选缺失、后态错误、过期 state |
| Pipeline | `next` 优先级、`[JumpBack]`、跨文件引用、UnknownStop | 路由漏页、重复确认、非 Round1 后态 |
| 实机 | 每个实际分支的前后语义与控制器审计 | 未见页面、状态冲突、日志存在额外输入 |

每次代码改动至少运行：

```powershell
python -m pytest -q tests -k hif
python tools/hif_screen_profile_check.py
python tools/hif_pipeline_check.py
python -m py_compile agent/hif/*.py agent/hif/adapters/*.py agent/custom/action/produce_hif.py tools/hif_*.py
python -m ruff check agent/custom/action/produce_hif.py agent/hif tests/test_hif_*.py tools/hif_pipeline_check.py
npx prettier --check "assets/data/hif/*.json" "assets/data/hif/**/*.json"
git diff --check
```

变更 `ProduceHIF.json` 后另跑全资源 Pipeline 集成检查；单文件节点测试不可替代跨文件引用验证。

## 5. 实机采样协议

真实设备单控制器串行。每个新分支只允许一次受限单步：先截图和读取，确认唯一目标后输入，立即采后帧并写 Journal；若后态不能由页面与领域状态共同解释，停止而非继续。

采样顺序：入口/开始确认，Day6 至 Day1 按实际出现顺序，子页返回，排名，Round1 停止。随机分支不要求人为刷取；未在路线中出现的页面继续安全停止，作为下一轮样本缺口。

人工接管可用于恢复和采样，但不能计为 P5 正式验收。不得花付费宝石、切换账号、主动放弃或为了覆盖率进入可规避消耗分支。

## 6. 预计改动面和顺序

| 顺序 | 主要文件 | 目的 |
| --- | --- | --- |
| P0 | `tools/hif_screen_profile_check.py`、对应测试 | 先恢复静态门禁可信度 |
| P1-P3 | `assets/resource/base/pipeline/ProduceHIF.json`、`agent/custom/action/produce_hif.py`、HIF 定向测试/fixtures | 补状态、Action 后验和安全路由 |
| P1-P3 | `assets/data/hif/screen_profiles/*.json`、`assets/data/hif/pipeline_coverage.json` | 只加入已采证 ROI/覆盖记录 |
| P4 | `assets/data/catalog/**`、`tools/data_catalog/**`、`agent/hif/**` | 离线/影子数据投影，不碰执行权限 |
| P5 | `plans/hif-mvp/HANDOFF.md`、验收报告 | 记录可复核最终证据 |

热点文件由单一整合者串行修改；页面 fixture、独立测试和数据目录投影可并行，但实机输入不可并行。

## 7. 里程碑和完成定义

- E0：P0 完成，profile/Pipeline 静态门禁可信。
- E1：主界面至 `remaining_day=6` 经过离线与实机逐段验证。
- E2：实际遇到的 Day6..1 和子页全部闭环，未知页始终安全停止。
- E3：排名后命中 Round1，并由 `ProduceHIFRound1ReachedStop` 停止。
- E4：一局新局从主界面正式 Pipeline 无人工拼接达到 E3；日志无额外输入。

E4 才是本方案完成。此后才重新评审 Round1 单卡后验、数据目录 F4 和 `8+2`；不能把 E4 宣称为完整 HIF 优胜闭环。

## 8. 风险和决策点

- 真实随机页覆盖不足：保留停止而非扩大猜测；后续样本触发最小补丁。
- OCR/ROI 漂移：以原始 `720x1280` 帧、正反 fixture 和 profile review section 共同约束。
- 重复点击：用后继识别和 `[JumpBack]`，不用延迟重试。
- 数据目录红灯：只隔离 Round1 执行，不得使入口路由回退到手写猜测。
- 既冻结 `PLAN.MD` 的“优胜”目标与本方案冲突：批准实施前需将本文件确认为较小的 E0-E4 阶段计划，或将其并入原计划的前置里程碑；两者不可同时作为同一轮验收标准。
