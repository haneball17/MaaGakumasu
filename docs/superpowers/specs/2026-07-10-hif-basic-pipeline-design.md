# HIF 基础管线设计

**状态：** 已确认首版验收边界；2026-08-14 设计评审回填（见文末）。  
**日期：** 2026-07-10（回填 2026-08-14）

## 目标

首版 HIF 以“用户预设执行”替代在线策略优化：从 HIF 培育入口开始，稳定识别并处理已覆盖的准备阶段页面，安全推进至 Round1 初始出牌画面。

当页面、候选、关键文本或坐标不在已覆盖范围内时，任务必须停止、输出当前 screen state 与原因，且不得执行猜测性点击。

## 非目标

- 不在首版实现 Interval、饮料上限、セレクトチェンジ、回忆卡的**最优评分**；但饮料上限取舍与セレクトチェンジ的**安全预设交互**属于首版必经路径，已纳入首版（2026-08-14 回填：实机日志确认 Day1/Day3/Day4/Day5 必经这些页面，不做则无法到达 Round1）。
- 不把 HIF 离线模拟器接入实机决策；它只继续服务 observed case、页面规范和回归数据。
- 不承诺完成 Round1 出牌、Round2、结算或整局自动培育。
- 不以泛用按钮匹配作为未知页面的兜底点击方案。

## 方案选择

`docs/hif/finals-daily-log.md` 是本设计的主要流程依据：页面名称、候选类型、交互顺序、日文 OCR 文案、初版 ROI 和“已确认/未知”边界均以该实机记录为准。`docs/hif/hif-simulator-flow-design.md` 仅用于说明后续模拟与决策模块的边界；MaaFramework 官方文档只约束 Pipeline 和 Agent 的实现机制。

采用“Pipeline 页面路由 + Agent 预设动作”的分层方案。

- Pipeline 只负责以高置信模板/OCR 路由页面，定义顺序、超时、回跳和安全停止。
- Agent Custom Action 负责读取 `custom_action_param` 中的用户预设，识别候选后执行明确的单步点击。
- HIF 出牌层与 `ExamStateReader` 在第二阶段接入，首版到达 Round1 后停在观察状态，不出牌。

这比纯 JSON 排序更容易维护候选与复杂交互，也比直接接入模拟器评分更早获得可实机验证的闭环。

## 预设接口

新增一个 HIF 专用任务选项，向所有 HIF Custom Action 注入同一结构；首版提供一个保守默认预设和一个莉波好调实验预设。

```json
{
    "preset_id": "rinami_good_condition_safe",
    "schedule_priority": ["Da", "Vi", "Vo", "gift", "consult", "go_out"],
    "class_option_priority": ["good_condition", "attribute_gain", "safe"],
    "public_lesson_priority": ["Da_sp", "Vi_sp", "Vo_sp"],
    "consult_policy": "finish_without_purchase",
    "round1_mode": "observe_and_stop"
}
```

每个 action 必须校验 preset 字段；字段无效、候选未命中或候选并列而预设无法消歧时调用 `ProduceHIFUnknownStop`。

## 页面路由

`ProduceEntryHIF` 保留为唯一入口。路由按三段子流程组织（2026-08-14 回填）：

- **主根 `ProduceEntryHIF`**：终态（Exit/Finished/Failed）、Round1/Round2 Flag、段入口（准备段根、日程段根）、`ProduceHIFUnknownStop`。
- **准备段根**：アイドル選択 → 開始確認 →（PItem 若存在）→ 衔接日程段。
- **日程段根**：Day1-Day6 各场景 Flag（日程候选、授業选项、公開レッスン、差し入れ奖励、饮料上限、セレクトチェンジ、相談）。
- **Round1 段**：`ProduceHIFRound1Flag` → Observe → ReachedStop。

节点优先级与识别顺序按场景卡（`docs/hif/scenes.md` 固定日程树）组织：

1. 任务终止、失败、生成完成等终态。
2. Round1 初始页；记录状态后进入首版终止节点。
3. 已覆盖准备阶段：日程候选、授業三选项、公开 lesson、差し入れ奖励、饮料上限取舍、咨询商店。
4. 已发现但首版不执行的复杂页：Interval、Round2、结算、Memory；记录为未覆盖状态后停止。
5. 通用确认按钮仅作为已知页面 action 完成后的后继节点，不得在路由根节点直接点击。
6. 所有识别超时走 `on_error` 到安全停止节点。

准备/日程阶段的循环子流程使用 `[JumpBack]` 返回所属段根；每个状态节点设置 `focus` 日志，包含页面名、预设 ID、匹配证据和下一动作。

**后验断言（2026-08-14 回填）**：点击/Custom 动作节点的 `next` 指向预期场景 Flag（概率分支并列），节点自身 `timeout`（15-30s 覆盖演出）超时后经 `on_error → ProduceHIFUnknownStop` 安全停止；不在 `next` 尾部挂 DirectHit 兜底（DirectHit 会在首个轮询周期立即命中，等于无等待窗口）。已知长演出（授業演出、结算动画）另设过渡特征白名单节点，命中则等待，避免超时误停。协议依据：`on_error` 在 next 识别超时或动作失败时进入；`[JumpBack]` 在错误处理路径不回跳。

## Action 边界

- `ProduceChooseHIFEventAuto` 改为完全由 preset 的日程优先级选择，不再使用当前固定优先级或“第一个候选”回退。
- 新增 `ProduceChooseHIFClassOptionAuto` 与 `ProduceChooseHIFPublicLessonAuto`，分别处理授業三选项和公开 lesson；只点击已识别且被预设选择的候选。
- 新增 `ProduceHIFConsultAuto`，首版只支持 `finish_without_purchase`，防止消耗本战前 P 点。
- 新增 `ProduceHIFRound1Observe`，读取并记录可见的 Round1 标题、体力、剩余回合、手牌 YOLO 结果；随后停止，不执行出牌。
- Agent action 的纯候选排序与 Context/点击逻辑分离，以便无设备单测。

## 识别和坐标约束

HIF 当前实测资料为 MuMu 竖屏 `720x1280`，HIF 节点和后续 `ExamStateReader` 的坐标必须以该尺寸作为首版基准。任意非该分辨率或比例的设备在入口处给出不支持提示并停止。

模板与 OCR 先使用现有 `assets/resource/base/image/produce/` 资源；缺少 HIF 页面特征时，只新增从实测截图裁出的最小页面/按钮素材，并记录截图来源和基准分辨率。识别样本放在测试夹具中，运行日志与用户账号数据不入库。

## 验证与验收

离线验证：

- HIF 预设解析、候选排序、未知候选拒绝和 Round1 观察停止均有 pytest。
- Pipeline JSON 解析后确认所有 HIF 路由节点存在，未覆盖页面只能到 `ProduceHIFUnknownStop`。
- 使用已记录 MuMu 截图验证每种已覆盖 screen state 的识别；`npx maa-tools check` 通过。

实机验收：

1. 使用 MuMu `720x1280`、HIF 和默认安全预设启动。
2. 日程、授業选项、公开 lesson、差し入れ或咨询商店仅按预设选择。
3. 到达 Round1 初始页后记录 Round1 信息并停止。
4. 未覆盖页面在任何点击前停止，日志显示当前页面与失败原因。

## 后续扩展顺序

达到首版验收后，依次接入：Round1 预设出牌执行、Interval、Round2、结算/Memory；每一类页面先离线识别、再观察模式、最后允许点击。模拟器评分只在这些交互稳定后用于替换具体预设规则（饮料上限与セレクトチェンジ的预设交互已在首版，其评分化归入此处）。

## 2026-08-14 设计评审回填

本节记录 grill 评审锁定的 8 项决策与联网调研事实，场景级细节见 `docs/hif/scenes.md`（场景卡，设计真源）。

**锁定决策：**

1. 场景卡全量记录：`docs/hif/scenes.md` 每场景一卡（锚/按钮/转移/证据/状态）；pipeline JSON 仍是执行唯一真源。
2. 模板优先：静态 UI/图标/按钮一律 TemplateMatch；OCR 仅用于页面文案锚（必须实机取证，禁止推测）与数字。已实机验证的 OCR 锚不回退改造（增量改造原则）。
3. 文档+后验断言：见「页面路由」节回填段。
4. 首版边界扩大承认：到 Round1 含准备+日程中间页的安全预设交互；Round1 到达即停、不出牌不变。
5. 分段子流程拓扑：见「页面路由」节。
6. timeout+白名单过渡容忍：见「页面路由」节回填段。
7. 离线定稿+实机补录：先建场景卡/改拓扑/静态检查全过，实机会话专注取证推进与补录缺口。
8. reroll 参数拆分：変卡（授業场景，重抽上限 3）与差し入れ·P item 奖励（重抽上限 2）分场景独立配置，来自实机日志观察。

**调研事实（学マス wiki / game8，2026-08-14 查阅）：**

- 本战为固定 7 日脚本：Day1 授業 → Day2 公開レッスン → Day3 おでかけ/差し入れ（玩家二选一）→ Day4 授業 → Day5 公開レッスン → Day6 相談 → 当天 Round1（9 回合）→ インターバル → Round2（12 回合）→ 結果発表。真随机仅：Day3 二选一、公開レッスン SP 与否当日决定、変卡候选内容。
- Round1 对局页无「Round 1」字样；可靠锚为左上「残りターン」盘与右侧 SKIP 按钮。`ProduceHIFRound1Flag` 的 `.*Round\s*1.*` 推测文案废弃，改双锚。
- 「選抜試験モード」/「本戦モード」二词零外部证据且实机链未经过，两 Flag 按存在性待取证处置（不遇则删）。
- HIF 2026-05-16 实装（2 周年），至 Ver 3.2.3 无 UI 改版记载；本战 AP 20，败北可无限再挑战（保持選抜試験メモリー），Round1 前体力自动回复 50%。
- 已知 bug 备查：Round2 败北时「結果発表準備中」卡死（game8），不在首版范围。

## 外部依据

- MaaFramework 官方《任务流水线协议》：`next` 按顺序识别、`on_error` 超时处理、`[JumpBack]` 回跳、`focus` 节点通知以及 Custom Action 参数机制（本地镜像 `docs/maa-framework-official/3.1-任务流水线协议.md`，commit `2bf1ae6`）。  
  <https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md>
- MaaFramework 官方《Custom & Agent》：复杂、独立迭代的业务动作应由 Agent 承载，以隔离框架核心并提高可维护性。  
  <https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.3-Custom%26Agent.md>
- 学マス wiki「H.I.F」：本战固定日程表、セレクトチェンジ机制、AP 消耗、败北再挑战规则（2026-08-14 查阅）。  
  <https://seesaawiki.jp/gakumasu/d/H.I.F>
- game8「学園アイドルマスター HIF 攻略」：日程结构、実装时间线、已知 bug（2026-08-14 查阅）。  
  <https://game8.jp/gakuen-idolmaster/783836>

以上资料于 2026-07-10 查阅。
