# M1 HIF Pipeline 首轮审计

_审计日期：2026-07-15；范围：Round1 后至返回可控状态；本轮只读、未控制模拟器。_

## 结论

当前正式 HIF 任务尚不能满足 M4。静态结构检查通过只说明节点引用和字段合法，不能证明没有隐藏输入、路由互斥、动作语义后验或全 bundle 可达性。

## 硬阻塞

1. HIF 根路由曾把跨文件 `ProduceExit` 放在首位；其 Custom recognition `ProduceShowStart` 在判断横竖屏前调用 `Click_1`，会产生未记入 HIF Journal 的隐藏点击，并可能在横屏 Live 时抢占 HIF 专用路由。已在集成分支提交 `09936af fix(hif): 移除根路由隐藏输入`，定向测试 `128 passed`、Pipeline 检查 `issue_count=0`。
2. Round1/Round2 默认 `execution_mode=observe_and_stop`；continuous 明确拒绝，single-step 每张牌后停止。正式任务选项没有把两轮、Interval、Live、结算和回忆串成可验收的有界连续模式。
3. `ProduceHIFLiveFlag` 默认只观察并停止，且尚无当前实帧校准的唯一继续目标与领域后验；即使不被通用节点抢占也无法通过 M4。
4. Round1 OCR 含通用 `.*残りターン.*` 且优先于 Round2，可能误吞 Round2。Round2 尚无当前实帧或互斥锚点证据，不能只靠调整顺序掩盖。
5. Interval 默认观察停止；现有“结束”点击未限定 Round2 等语义后继。结算与回忆动作虽已存在，但正式节点没有获得所需执行权限。
6. 不可规避的技能奖励、强化结果、饮料溢出、Select Change 等随机链权限不完整；当前触发会停止。
7. 正式通信错误恢复路径尚不存在，无法证明恢复同一局并与账本对齐。

## 覆盖与验证债

- `pipeline_coverage.json` 把尚未完成实机闭环的 Round2、Live、Memory、Settlement 标为 `observed`；后续应拆分为 `historical_frame/classification_only/current_action_verified/e2e_verified`，在取得当前动作证据前降级。
- `hif_pipeline_check.py` 尚不检查 Custom recognition 副作用、Round 路由重叠、状态改变动作的语义后继、正式 override 可达性或 coverage 与 `STATUS.md` 的一致性。
- ROI 均在 ADB 原始 `720x1280` 边界内，但 Round2/Live/Memory OCR 缺少当前原始 box、ROI sweep、最终置信度和页面恢复证据。
- `pipeline-testing` 技能当前不可用；`npx maa-tools check` 因本地包不可用/npm 404 未执行。后续必须用仓库节点测试、`hif_pipeline_check.py`、正式全 bundle GUI/CLI、原始帧与控制器日志达到同等证据门槛。

## 路径分类

- 必经主链：正式入口/本战准备 → Round1 → Interval 结束 → Round2 → 優勝结算 → Live → Memory photo select/confirm → Memory generate/preview → finished → home。
- 不可规避或状态依赖随机：class option、public lesson result、gift result、drink/skill reward/reveal、skill enhanced、drink overflow、select-change。
- 可规避：Interval 购买/刷新/强化/回复、Consult 购买、reward reroll、再生成/再挑战；MVP 应选择不购买/结束路径。
- 历史孤立：coverage 已声明 unreachable 的早期入口/过渡/Generation/HIFButton/Round1Observe/KnownNext 节点，不能计入正式主链证明。

## 旧 worktree 结论

`.worktrees/hif-round1` 的 Pipeline/Action 已被当前实现超越，不整体合并。未跟踪 simulator-v2 属于独立决策/模拟器能力，且与当前 Windows 文件/目录命名存在冲突，不是本轮 Pipeline blocker；如后续需要只能逐能力重实现或择取无冲突提交。

## 后续顺序

1. 先完成可信状态、评分器接入和 Round1 独立 `8+2`。
2. 取得 Round2 当前实帧，建立 Round1/Round2 互斥识别，再完成 Round2 `8+2`。
3. 逐页采证并修复 Interval、Live、结算、回忆和不可规避随机链；所有动作遵循识别 → 操作 → 语义识别。
4. 增加正式执行模式/override 与通信错误恢复，并用全 bundle 单任务证明从入口到 home。
