# HIF 架构设计

本页只负责模块边界与实现落点。

机制事实请看：

- [`summary.md`](summary.md)
- [`evaluation.md`](evaluation.md)
- [`randomness.md`](randomness.md)

## 1. 当前项目里的 HIF 架构

当前项目里，HIF 相关内容分成 3 层：

### 1.1 MaaFramework 流水线层

- 负责任务调度与页面跳转
- HIF 主入口在：
  - `ProduceEntryHIF`
- HIF 当前仍是独立流水线边界

### 1.2 `CustomAction` 层

- 负责局部页面中的自动选择
- 当前 HIF 已有：
  - `ProduceChooseHIFEventAuto`
  - `ProduceChooseHIFPItemAuto`

### 1.3 离线模拟层

- 当前新增的 HIF `CLI` 决策模拟器
- 不直接依赖截图、OCR、控制器
- 负责：
  - 路线模拟
  - 奖励模拟
  - 评价报表

## 2. 当前有没有全局决策引擎

结论很明确：

- **当前没有独立全局 `DecisionEngine`**

现状是：

- 实机层：`pipeline + CustomAction`
- 离线层：`simulator + CLI`

所以当前更准确的说法是：

- 已经有 HIF 局部决策能力
- 但还没有统一全局决策系统

## 3. 当前离线模拟层结构

当前离线模拟层主要由这些对象构成：

- `ScenarioConfig`
- `HIFEvaluationConfig`
- `ProduceProfile`
- `SimulationState`
- `SelectionSnapshot`
- `SelectionMemoryProfile`

以及这些流程组件：

- `PhaseResolver`
- `CandidateBuilder`
- `HardGate`
- `SoftGate`
- `ImmediateScorer`
- `BeamPlanner`
- `StateReducer`
- `SnapshotBuilder`
- `MemoryProjector`

## 4. 当前文档与代码的边界

当前这套 HIF 文档的作用，是把 3 件事分开：

- 机制事实
- 决策抽象
- 代码落点

不要把：

- HIF 机制细节
- CLI 样本实现
- 实机自动化入口

混成一层看。

## 5. 当前主线环境

当前 HIF 主线仍然是：

- `MuMu 模拟器 12`
- `Adb`
- 日文原版
- `1280x720 (240DPI)` 作为主要基准

DMM 当前保留为冻结旁支，不是主线。

## 6. 后续演进方向

当前比较合理的演进顺序是：

1. 先稳定文档、数据、CLI 模拟器
2. 再补真实候选池与随机性
3. 再把评价体系更深入地接回主评分器
4. 再把离线结论接回 `produce_hif.py`
5. 最后再评估是否抽全局 `DecisionEngine`

## 7. 一句话总结

当前 HIF 架构最合适的理解是：

> 实机层负责执行，离线层负责推演，文档层负责把机制、抽象和实现边界稳定下来。
