# HIF MVP 当前状态

_快照时间：2026-07-15；当前阶段：M1 并行能力（进行中）_

## 仓库状态

- 当前分支：`codex/hif-mvp-integration`。
- 创建基点：`fd4d72d docs: 拆分 HIF 决策算法计划`。
- 决策接口与审计规格已提交为 `6f318dd docs(hif): 冻结决策接口与审计规格`。
- 当前 HIF 实机实现、测试、数据、必要模板与文档已提交为 `166b62c feat(hif): 整理实机验证基线`。
- 另有 `.worktrees/hif-round1`，基于 `7c5a764` 分叉，包含一套旧的未提交 simulator/domain 重构；只读参考。
- 大量无关未跟踪目录与文件属于既有工作区状态，不得纳入本任务提交。

## 已完成

- 并行读取并总结两个历史 Codex 会话：
    - `019f639d-bcd4-7780-a416-1d61a1490efe`：决策算法与日志/接口规格，未实现新算法；
    - `019f6542-d40f-77a3-86f3-8df858d869b7`：Round1 指标读取与实机探针，未完成全流程。
- 逐项确认 MVP 范围、两阶段实测、资源边界、成功门槛、状态真值、评分器、`8+2`、并发所有权和版本控制策略。
- 创建集成分支和本任务集中式文档目录。
- 已完整读取并登记 `pipeline-guide`、`pipeline-generate`、`pipeline-option`、`pipeline-testing`；后续 Pipeline
  文档、节点、选项和测试必须按对应技能执行。
- 完成 M0 权威基线审查与分拆提交；未纳入 `debug/`、视频、模型、测试资源和无关未跟踪目录。
- 当前环境可用技能中缺少 `pipeline-testing`；后续以仓库的节点级测试、`hif_pipeline_check.py`、全 bundle 正式集成测试和控制器日志审计达到同等证据门槛，并持续记录该限制。

## M0 验证基线

- HIF 专项：`284 passed`。
- 全仓：`337 passed`。
- `python tools/hif_pipeline_check.py`：`ok=true, issue_count=0`。
- Python 编译：通过。
- `python -m ruff check ...`：通过，仅有 `pyproject.toml` 顶层配置弃用警告。
- 本次触及且采用仓库 Prettier 风格的 JSON/Pipeline 文件检查通过；全量 `assets/data/hif/**/*.json` 检查仍会命中 11 个历史格式不一致文件，其中多数未被本任务修改。为避免无关全文件重排，M0 不自动格式化这些历史数据文件。
- `git diff --check`：通过。

## 当前实机停点

最近可信证据来自：

- 运行目录：`debug/hif-live/hif-round1-score-multiplier-calibrated-20260715/`
- Journal：`debug/hif-journal/20260715T185253-45208.jsonl`

已知状态：

- 页面：Round1；剩余回合 `6`。
- `good_condition=47`、`focus=10`、`stamina=33`、`reprise=2`。
- `current_score=116611`。
- `stage_multiplier=3807%`。
- 可见手牌：`演出計画`、灰色 `眠気`、`祝福`、`祝福+`。
- 当前牌库数量尚未可靠重读。
- 指标面板关闭后已验证回到 Round1；本次规划与建档没有执行新的实机输入。

## 当前主要缺口

- 基线差异尚未按范围审查和提交。
- 普通决策链尚未稳定消费分数、倍率和所有动作必需状态。
- 牌库数量、卡牌详情和重启后账本对账仍需完成。
- 当前路线结构化卡牌效果与确定性评分器尚未完成。
- Round1 尚未达到 `8+2`；Round2 尚未开始独立采证。
- Interval、Round2 后续、奖励、Live、回忆和真实优胜结算仍缺完整闭环。
- 决策核心只有冻结规格，尚未实现。

## M1 下一步

1. 创建状态读取、路线评分器和 Pipeline 审计三个隔离 worktree，启动第一轮并发。
2. 主 agent 重新截图并审计当前 Round1 停点，但在状态/评分门禁完成前不执行出牌。
3. 审查并择取子提交，集成普通 `ProduceCardsHIF` 的完整可信状态和唯一决策/安全拒绝。
4. Pipeline 审计和后续修改按专项技能记录设计依据、ROI、节点测试与全 bundle 验证。

## 阻塞与风险

- 当前两个 worktree 的旧实现高度重叠，禁止整体合并。
- 实机是单一可变状态，只允许主整合 agent 串行输入。
- 当前 Round1 现场不可替代，任何动作前必须重新截图并核对停点。
- 子 agent 模型由平台分配，不能保证指定模型或 reasoning effort；通过窄任务、证据要求和主 agent 审查控制质量。
