# HIF MVP 任务文档

本目录是 `rinami_garakuta_road` HIF MVP 全流程闭环任务的唯一新增文档目录。

## 文档索引

- `PLAN.MD`：已锁定的总计划、并发拆解、验收条件与安全边界。
- `STATUS.md`：当前阶段、仓库/实机停点、验证结果、阻塞与下一步。每个里程碑必须更新。
- `DECISIONS.md`：用户逐项确认的范围与工程决策。
- `HANDOFF.md`：实机操作、Journal、截图、失败证据及恢复信息。

## 更新规则

1. 本任务新产生的计划、审计、进度和交接文档必须放在本目录或其子目录下。
2. `STATUS.md` 保持为可快速恢复上下文的最新快照，不堆叠已经失效的操作指令。
3. 达到里程碑时，先完成验证，再更新 `STATUS.md`；涉及实机状态时同步更新 `HANDOFF.md`。
4. 新增或改变用户决策时同步更新 `DECISIONS.md` 和 `PLAN.MD`。
5. 既有根 `PLAN.md`、`docs/hif/handoff.md` 和 `plans/decision-algorithm/**` 仅作为历史与专项资料引用，不移动、不覆盖。
6. `debug/`、Journal、日志、视频和原始截图不是计划文档，不得复制到本目录或提交入库；文档只记录其本地证据路径和结论。
7. 涉及 Pipeline 设计、OCR 节点、任务选项或节点测试时，必须使用 `pipeline-guide`、`pipeline-generate`、
   `pipeline-option`、`pipeline-testing` 中适用的技能，并在里程碑记录中注明使用范围和验证结果。
