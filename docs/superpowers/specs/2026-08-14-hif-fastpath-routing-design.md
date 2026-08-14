# HIF 快慢路径路由设计

**状态：** 方案已确认，待实机校准后实施。  
**日期：** 2026-08-14  
**前置：** `2026-07-10-hif-basic-pipeline-design.md`（首版预设执行）、`docs/hif/round1-blockers.md`（阻断清单）

## 目标

将 HIF 管线的路由模式从「每个动作后回根全量识别」优化为「快慢路径」：

- 子动作执行完，**优先识别预期场景**（1~2 个节点，快路径）。
- 预期未命中时**降级到路由根做全量识别**（慢路径），而不是停止。
- 缩小误命中面、减少每轮识别开销，并让「预期不中」成为可观测的实机诊断信号。

## 非目标

- 不改变首版的安全边界：未知页面仍由根节点兜底 `ProduceHIFUnknownStop` 停止，禁止猜测性点击。
- 不在场景判定文案校准之前实施（见「实施时机」）。
- 不为分支过多的动作节点强行配置预期（如日程选择）。

## 现状与动机

当前 `ProduceEntryHIF` 是集中路由根：每个子动作节点无 `next`，执行完自动 `[JumpBack]` 回根，对最新截图**串行尝试 next 数组里全部 20 个识别节点**（8 个 OCR + 十余个模板）。

问题：

1. **误命中面叠加**。每个识别节点都是独立误命中源，扫描 20 个相比扫描 2 个，偏航概率高一个量级。场景判定文案目前多为推测（见阻断清单 #1~#4），风险进一步放大。
2. **识别开销**。PaddleOCR 单次推理量级在百毫秒（估计值，未实测），全量一轮可能达秒级；整局培育含数百次路由决策，累计开销可观。
3. **调试信号弱**。回根全量时日志是一串识别尝试，无法区分「预期流程正常推进」与「误打误撞命中」。

## 方案选择

MaaFramework 的 `next` 数组本身就是「按序识别、命中即走」的语义，快慢路径无需新机制，纯 JSON 结构调整：

```json
"ProduceHIFClassOptionFlag": {
    "next": [
        "ProduceHIFPublicLessonResultFlag",
        "ProduceEntryHIF"
    ]
}
```

命中预期节点则直接走它；预期未命中则轮到裸写的 `ProduceEntryHIF`（DirectHit 必中）进入根，走全量 next。相比「给每个节点硬编码完整跳转链」，该方案保留了全量兜底，安全性不变。

## 统一约定

动作节点的 `next` 遵循：

```
next = [ 预期场景 × ≤2, "ProduceEntryHIF" ]
```

规则：

1. **预期最多 2 个**，只列最高概率去向。分支过多的节点（预期收益低）直接裸回根，不配预期。
2. **兜底永远是裸写根节点 `"ProduceEntryHIF"`**（不带 `[JumpBack]` 前缀）。它是 DirectHit 必中，进入即走全量识别。
3. **移除局部 `ProduceHIFUnknownStop`**。现状 `ProduceHIFDrinkRewardFlag.next = [RewardConfirmFlag, UnknownStop]` 这类「预期不达即停」改为 `[RewardConfirmFlag, 根]`。停止职责统一收归根节点：全量识别都不中才停止，比现状更宽容也更一致。

## 各节点预期表

| 动作节点 | 预期 1 | 预期 2 | 兜底 | 依据 |
| --- | --- | --- | --- | --- |
| `ProduceHIFSelectChangeTargetFlag` | `ProduceHIFSelectChangeSourceFlag` | — | 根 | 最佳候选：日志确认的两阶段固定流程 |
| `ProduceHIFSelectChangeSourceFlag` | `ProduceChooseHIFEventFlag` | — | 根 | 变卡完成回日程 |
| `ProduceHIFClassOptionFlag` | `ProduceHIFPublicLessonResultFlag` | — | 根 | 授業后进结算（日志流程） |
| `ProduceHIFPublicLessonResultFlag` | `ProduceChooseHIFEventFlag` | — | 根 | 结算确认回日程 |
| `ProduceHIFConsultFlag` | `ProduceChooseHIFEventFlag` | — | 根 | 退商店回日程 |
| `ProduceHIFDrinkRewardFlag` | `ProduceHIFRewardConfirmFlag` | — | 根（替换现有 UnknownStop） | 日志已确认 |
| `ProduceHIFSkillRewardFlag` | `ProduceHIFRewardConfirmFlag` | — | 根（替换现有 UnknownStop） | 日志已确认 |
| `ProduceChooseHIFEventFlag` | — | — | 直接回根 | 分支过多（授業/相談/差し入れ/外出），快路径不划算 |
| `ProduceChooseHIFPItemFlag` | — | — | 直接回根 | 日志无此页流程记录，纯推测，不叠预期 |

保持不变：终态节点（`ProduceExit` / `ProduceHIFFinishedFlag` / `ProduceHIFFailedFlag`）、`ProduceHIFRound1Flag → Round1ObserveFlag → Round1ReachedStop` 链、4 个未覆盖 Flag（DrinkOverflow / Interval / ScoreSettlement / Memory）仍直接 `UnknownStop`。

## 收益与风险

收益：

1. 误命中面缩小（最直接的鲁棒性收益）。
2. 「快路径命中率」成为实机诊断指标：日志中「预期不中 → 降级全量」的模式直接暴露哪个预期配错。
3. 流程意图在管线中显式可读，断链可静态发现。

风险与对策：

1. **双层推测叠加**——预期场景的判定文案目前也是推测的，改完无法离线验证路由效果。对策：遵守实施时机，先校准后优化。
2. **协议细节待确认**——`[JumpBack]` 前缀引用的节点自带 `next` 时，回跳与 next 的交互行为需查官方文档或实机确认后再定稿。
3. **维护面扩大**——28 个节点的 next 需逐一推演。对策：不变式静态检查（见下）。

## 不变式与静态检查

从任何节点沿 `next` 链有限步内必达以下三者之一，不得成环、不得悬空引用：

1. 路由根 `ProduceEntryHIF`；
2. 终态（`StopTask` 或转外部节点如 `ProduceFinished`）；
3. 语义终点（`ProduceHIFUnknownStop` / `ProduceHIFRound1ReachedStop`）。

建议以脚本解析 `ProduceHIF.json` 做图检查，纳入 `npx maa-tools check` 之外的补充校验（放在 `tools/` 或 CI）。

## 实施时机

**先实机校准场景判定文案（阻断清单 #1~#4），再实施本方案；若同批实施，必须分开提交。**

理由：场景判定文案目前是推测值。在其上叠加预期链等于双层推测，实机调试时无法区分「文案错」与「预期链错」，变量耦合。正确顺序：

1. 实机取证，修正场景判定文案与 ROI；
2. 在已验证的文案上实施本方案；
3. 第二轮实机回归，观察快路径命中率。

## 验证与验收

离线：

- `npx maa-tools check` 通过；
- 不变式静态检查通过（无环、无悬空、所有路径达根或终态）；
- 现有 pytest 全过（本方案不触 Python 层）。

实机：

- 正常流程日志中，动作节点命中预期场景的比例（快路径命中率）作为观测指标记录；
- 预期未命中的场景，日志出现「降级全量」且最终由根正确路由或安全停止；
- 无任何因快路径引入的误点击。

## 外部依据

- MaaFramework《任务流水线协议》：`next` 按顺序识别、命中即走、`[JumpBack]` 回跳语义。  
  <https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md>
