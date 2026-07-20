# 项目文档总览

本目录记录可长期复用的信息。先按任务选择权威入口，避免复制同一结论。

| 目的 | 入口 | 规则 |
| --- | --- | --- |
| 游戏机制事实 | [game-knowledge/](game-knowledge/README.md) | 记录结论、范围、可信度、来源和验证日期。 |
| 当前开发决策 | [decisions/](decisions/README.md) | 仅保留有效取舍；被替代项进入归档。 |
| 可复用经验 | [experience/](experience/README.md) | 记录复盘和陷阱，不把经验当机制事实。 |
| HIF 专项资料 | [hif/](hif/README.md) | 页面证据、实现、测试与路线资料；核心机制见 [game-knowledge/hif.md](game-knowledge/hif.md)。 |
| 冻结规格与计划 | [superpowers/](superpowers/) 与 `plans/` | 不是当前有效决策的权威来源。 |
| 程序消费的数据 | `assets/data/` | 文档链接数据，不重复维护字段。 |
| 原始截图、Journal、Maa 日志 | `debug/` | 仅作证据，不提交、不自动晋升为知识。 |

## 现有内容归类

| 现存资料 | 文档库归属 | 权威位置 |
| --- | --- | --- |
| MaaFramework 协议、集成与构建说明 | 框架参考 | `zh_cn/`、`en_us/`；它们是上游框架文档，不写入游戏知识或项目决策。 |
| HIF 核心机制 | 游戏机制事实 | [game-knowledge/hif.md](game-knowledge/hif.md)；HIF 专项文档提供详细解释与证据。 |
| HIF 路线、实现、实测与资源 | HIF 专项资料 | [hif/README.md](hif/README.md)；该入口按工程、经验和证据分组。 |
| HIF 当前工程取舍 | 当前开发决策 | [decisions/README.md](decisions/README.md) 的 HIF 索引；细节仍在 HIF 权威文档。 |
| HIF 复盘、测试与运行校准 | 开发与测试经验 | [experience/README.md](experience/README.md) 的 HIF 索引；不复制专项原文。 |
| HIF Round1 规格与执行计划 | 冻结规格与计划 | `superpowers/specs/`、`superpowers/plans/`；需要重新批准才可成为当前决策。 |
| DMM 基线与任务交接 | 历史/运行记录 | `hif/dmm-baseline.md`、`hif/handoff.md`；不作为当前 MuMu 主线依据。 |
| `0711.md` | 原始会话转储 | 不属于长期文档库，不从中自动提炼知识、决策或经验。 |

## 写入规则

完成开发、发现机制、修改 Pipeline 或完成实机测试后，完成该任务的代理应直接写入本任务范围内的权威文档；不需要为普通文档维护另行等待用户确认。

1. 可复核游戏事实直接写入对应知识入口；HIF 核心机制写入 `game-knowledge/hif.md`，详细来源和页面证据保留在 `hif/`。
2. 工程取舍、授权边界或假设变化直接写入当前决策；替代旧决策时一并归档。
3. 可复用的测试或实现教训直接写入经验库或对应专项复盘。
4. 单次截图、Journal 或未复核现象直接写入观察/证据层，不能越级写成机制事实或自动点击依据。
5. 没有新增长期信息时不创建日志；交付时标明“无文档增量”。

只有结论超出用户任务范围、来源相互冲突且无法安全归类，或写入会引入新的外部授权时，才暂停并请求方向。

开发代理应使用 `maagakumasu-documentation` Skill；任务结束的 Hook 只确保完成上述检查。
