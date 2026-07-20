# 当前开发决策

这里记录仍然有效、会影响多个文件、Pipeline 安全边界或后续开发方向的工程决策。小型局部实现取舍留在代码或对应规格中即可。

每项决策至少写明：

- 标识与日期；
- 决定了什么、为何如此；
- 影响的代码、Pipeline、数据或文档；
- 复核条件或失效条件；
- 若替代旧项，旧项的归档链接。

现有 HIF `docs/hif/decisions.md` 描述策略优先级，不是本目录的决策历史；现有 `docs/superpowers/` 与 `plans/` 是冻结规格或执行计划，不能覆盖这里的当前决定。

决策失效时移至 [archive/](archive/README.md)，保留替代项、废弃原因与影响，保证可复盘。

## 当前有效决策

- [`ADR-20260718-documentation-direct-write.md`](ADR-20260718-documentation-direct-write.md)：完成任务的代理直接维护本任务范围内的权威文档。
- [`ADR-20260720-hif-live-pipeline-authorization.md`](ADR-20260720-hif-live-pipeline-authorization.md)：HIF 实机管线验证必须由用户在当前任务显式授权。

## 已有关联材料

以下材料继续在 HIF 目录维护，避免将同一实现取舍复制成两份：

- 当前策略优先级：[`../hif/decisions.md`](../hif/decisions.md)；
- 当前架构和 MVP 边界：[`../hif/architecture.md`](../hif/architecture.md)、[`../hif/mvp.md`](../hif/mvp.md)；
- Pipeline 与页面能力设计：[`../hif/hif-simulator-flow-design.md`](../hif/hif-simulator-flow-design.md)、[`../hif/roi-integration-plan.md`](../hif/roi-integration-plan.md)；
- MaaFramework JSON 的实现边界：[`../hif/maaframework-json-development-research.md`](../hif/maaframework-json-development-research.md)。

它们是当前 HIF 的专项权威文档；跨领域、需独立替代与归档的决定才在本目录新增决策记录。
