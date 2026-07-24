# HIF 管线现状调研（2026-07-23）

## 范围与证据口径

本报告只使用仓库中的源码、文档与 Git 历史。已提交基线为 `cc05a6d5f24b7c8bd9d2025d50efe0f5e4d00b9c`（2026-07-20）；当前工作区含未提交的 HIF 动作、测试管线、运行器及测试改动，故下文把它们视为“当前工作区实现”，不归因于该提交。

## 结论

HIF 已有从任务入口到部分页面动作、离线决策和单步测试的工程链路，但不是可连续运行的自动培育：默认模式为观测并安全停止；Round 出牌、未采证页面和连续模式均未获执行授权。

| 层级 | 已有能力 | 当前边界 |
| --- | --- | --- |
| 入口与状态机 | `HIF` 难度入口跳转 `ProduceEntryHIF`；存在准备、本战、Round、Interval、Live 等分支。 | 未知页面路由至 `ProduceHIFUnknownStop`；Interval 目前到达即停止。 [任务配置](../../assets/tasks/produce.json#L50-L62)；[状态机](../../assets/resource/base/pipeline/ProduceHIF.json#L124-L168)；[Interval](../../assets/resource/base/pipeline/ProduceHIF.json#L972-L978) |
| 页面动作 | 已覆盖事件、P Item、课程、奖励、变卡、咨询等 Custom Action。 | 每次点击须命中已知后态；缺少证据或截图失败即停止。 [动作基类](../../agent/custom/action/produce_hif.py#L54-L96)；[测试约束](testing.md#L29-L44) |
| Round | 有 ExamState 读取、候选决策和 `observe` / `single_step` 审批模型。 | 尚无“手牌、回合、数值已更新”的实机后验，审批固定不支持出牌点击。 [读取器](../../agent/hif/adapters/exam_reader.py#L609-L734)；[审批器](../../agent/hif/execution.py#L9-L54)；[测试说明](testing.md#L37-L40) |
| 验证 | 有节点覆盖矩阵、静态检查、离线夹具和 HIF 测试集。 | 离线回放不等同于控制器端到端实机验证。 [覆盖要求](testing.md#L11-L27)；[本地检查](testing.md#L96-L104) |

## 运行和授权边界

- 默认预设为 `observe_and_stop`；任务配置另提供实验性的单步执行覆盖。 [配置](../../assets/tasks/produce.json#L95-L147)；[执行模式](../../assets/tasks/produce.json#L156-L243)
- 除非用户在当前任务明确授权，不得连接设备、启动 `tools/hif_live_runner.py` 或提交 Pipeline；零输入观察也在授权范围内。 [ADR](../decisions/ADR-20260720-hif-live-pipeline-authorization.md#L7-L19)
- 能力升级需按 `unverified → offline_replay → shadow → single_step` 逐级取得证据；`continuous` 当前未开放。 [升级门槛](testing.md#L82-L94)

## 当前优先缺口

1. 校准并复核 Round 的手牌、回合、数值 ROI，建立真实动作后的可识别后验，才可评估单步出牌。
2. 补齐 Interval 商品/价格、饮料满仓、Live 快进与选拔候选池的实机页面证据；现阶段不得用延迟或坐标猜测跨越页面。
3. 取得跨页面、跨回合的重复实机回归与异常出口证据后，才讨论连续模式。

这些缺口与现有文档一致：未获实机证据的页面、其他路线、Round 自动出牌和连续模式均保持安全停止。 [测试说明](testing.md#L41-L44)；[运行校准](runtime-calibration.md#L44-L60)

## Git 演进证据

- `f1fe330`（2026-06-29）：引入 HIF 状态机基础。
- `c229a6b`（2026-07-10）：接入本战入口。
- `8c5471b`（2026-07-14）：补充安全测试闭环。
- `09936af`（2026-07-15）：移除根路由中的隐藏输入。
- `aeee1f8`（2026-07-20）：补充测试基线与管线，新增/更新 `ProduceHIF.json`、任务配置、覆盖矩阵、测试与 HIF 文档。
- `cc05a6d`（2026-07-20）：采证变卡牌库入口与快照，新增 `agent/hif/change_snapshot.py`，并更新 Day1 测试入口与契约测试。

## 文档归档依据

`docs/README.md` 将 HIF 的页面证据、实现和测试归入 `docs/hif/`，将核心机制限定在 `docs/game-knowledge/hif.md`，并禁止把单次原始观察直接升级为自动化动作依据。故本“工程现状”报告置于本目录，不改写机制事实或来源调研。 [文档总览](../README.md#L7-L13)；[写入规则](../README.md#L28-L35)；[HIF 资料入口](README.md#L149-L175)
