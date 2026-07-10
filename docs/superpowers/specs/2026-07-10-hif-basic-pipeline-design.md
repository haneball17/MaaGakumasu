# HIF 基础管线设计

**状态：** 已确认首版验收边界。  
**日期：** 2026-07-10

## 目标

首版 HIF 以“用户预设执行”替代在线策略优化：从 HIF 培育入口开始，稳定识别并处理已覆盖的准备阶段页面，安全推进至 Round1 初始出牌画面。

当页面、候选、关键文本或坐标不在已覆盖范围内时，任务必须停止、输出当前 screen state 与原因，且不得执行猜测性点击。

## 非目标

- 不在首版实现 Interval、饮料上限、セレクトチェンジ、回忆卡的最优评分。
- 不把 HIF 离线模拟器接入实机决策；它只继续服务 observed case、页面规范和回归数据。
- 不承诺完成 Round1 出牌、Round2、结算或整局自动培育。
- 不以泛用按钮匹配作为未知页面的兜底点击方案。

## 方案选择

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

`ProduceEntryHIF` 保留为唯一入口，节点按以下优先级识别：

1. 任务终止、失败、生成完成等终态。
2. Round1 初始页；记录状态后进入首版终止节点。
3. 已覆盖准备阶段：日程候选、授業三选项、公开 lesson、差し入れ奖励、咨询商店。
4. 已发现但首版不执行的复杂页：饮料上限、セレクトチェンジ、Interval、Round2、结算、Memory；记录为未覆盖状态后停止。
5. 通用确认按钮仅作为已知页面 action 完成后的后继节点，不得在路由根节点直接点击。
6. 所有识别超时走 `on_error` 到安全停止节点。

准备阶段的循环子流程使用 `[JumpBack]` 返回路由根节点；每个状态节点设置 `focus` 日志，包含页面名、预设 ID、匹配证据和下一动作。

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

达到首版验收后，依次接入：Round1 预设出牌执行、饮料上限与セレクトチェンジ的安全交互、Interval、Round2、结算/Memory；每一类页面先离线识别、再观察模式、最后允许点击。模拟器评分只在这些交互稳定后用于替换具体预设规则。

## 外部依据

- MaaFramework 官方《任务流水线协议》：`next` 按顺序识别、`on_error` 超时处理、`[JumpBack]` 回跳、`focus` 节点通知以及 Custom Action 参数机制。  
  <https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md>
- MaaFramework 官方《Custom & Agent》：复杂、独立迭代的业务动作应由 Agent 承载，以隔离框架核心并提高可维护性。  
  <https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.3-Custom%26Agent.md>

以上资料于 2026-07-10 查阅。
