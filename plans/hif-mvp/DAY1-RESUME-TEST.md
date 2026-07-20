# HIF Day1 续接测试记录

状态：2026-07-16。范围：正式 `Produce` 入口从已在 HIF 本战准备页的游戏状态续接；只验证 Day1 红色 Vo 课程。Round1 出牌不在本用例授权范围内。

## 已确认链路

1. `Produce` 进入 `ProduceLoop`。
2. HIF 选项覆盖将 `ProduceHIFFinalsPrepareResumeFlag` 放在首位。
3. 节点仅在顶部 OCR 命中“本戦/本战 + 剩余日数”时进入 HIF 路由；普通主页、弹窗和未知页继续走原有节点。
4. `ProduceChooseHIFEventFlag` 读取 `finals_prepare` 状态和底部候选。
5. `day_remaining=6` 时，`HIF Day1课程=Vo（红）` 覆盖预设路线；候选必须同时存在 `Vo`，否则安全停止。
6. `HIF执行模式=观测（默认）` 只记录决策和截图，必须以 `page_execution_mode_not_single_step` 停止；这是预期安全结果。
7. `HIF执行模式=单步执行（实验）` 才允许一次课程点击。点击后必须重新截屏、确认画面变化，再确认仍是已知 HIF 页面；任一失败都停止，不重复点击。

## 本次实测证据

运行：`debug/hif-journal/20260716T224522-37748.jsonl`

- 页面：`finals_prepare`，动作状态：`finals_action_select`。
- OCR 候选：`Vo, Da, Vi`。
- 决策：`Vo`，原因：`Day1课程=Vo`。
- 执行模式：`observe_and_stop`。
- 结果：无控制器点击，安全停止 `page_execution_mode_not_single_step`。
- 截图：`debug/hif-journal/20260716T224522-37748-0001-finals_action_select_before.png`。

原始 Journal 与 PNG 属本地实测证据，不复制进版本库。

## 单步测试用例

启动选项：

```text
培育难度：HIF
HIF预设：莉波好调（实验）
HIF执行模式：单步执行（实验）
HIF Day1课程：Vo（红）
```

通过条件：

1. 日志出现 `HIF 可用日程（OCR）: Vo, Da, Vi`。
2. 日志出现 `HIF 选择事件: Vo`。
3. Journal 同一 `session_id` 依次保存 `before`、`selected`，若需要确认则保存 `confirmed` 截图。
4. 仅发送一次课程点击；后态为已知 HIF 页面。

停止条件：候选缺失、状态字段不可读、页面变化未验证、后态未知、或动作数超过一次。停止后不补点。

## 后续节点与测试顺序

`finals_prepare` 之后依次补实帧、状态读取、单步动作和前后截图：

1. `class_options`：课程选项页，默认只读确认。
2. `public_lesson_preview`：预览页，确认体力和属性变化后才允许一次确认。
3. `public_lesson_result`：结果页，读取结果后返回 HIF 路由。
4. Day2 至 Day6：每一天独立用例，不复用上一天的后态假设。
5. `finals_ranking_transition`：仅确认后态为 `round1`；到达后停止。

Round1 当前仅观察，不自动出牌。
