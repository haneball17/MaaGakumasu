# HIF 决策算法

本页只负责算法与对象模型，不再承担 HIF 背景机制总览。

机制结论请看：

- [`summary.md`](summary.md)
- [`evaluation.md`](evaluation.md)
- [`randomness.md`](randomness.md)

## 1. 当前目标

当前算法主目标固定为：

- 角色：`姫崎 莉波（ガラクタロード）`
- 剧本：`HIF`
- 路线：`感性·好调`
- 形态：离线 `CLI` 模拟

当前重点仍是：

- 路线决策
- P 道具选择
- 奖励选择
- 评价报表

不包含：

- 实机截图联动
- 完整出牌模拟
- 多角色泛化

## 2. 主流程

当前 simulator 使用的主流程是：

1. `PhaseResolver`
2. `CandidateBuilder`
3. `HardGate`
4. `SoftGate`
5. `ImmediateScorer`
6. `BeamPlanner`
7. `StateReducer`
8. `SnapshotBuilder`
9. `MemoryProjector`

## 3. 关键对象

### 3.1 场景与配置

- `ScenarioConfig`
  - 决策阶段、目标值、经验权重
- `HIFEvaluationConfig`
  - HIF 评价体系配置
  - 选拔属性结构
  - 本战权重
  - 星性相关结构
- `ProduceProfile`
  - 角色卡、路线、支援卡、标签偏好

### 3.2 状态对象

- `SimulationState`
  - 模拟过程中的即时状态
- `SelectionSnapshot`
  - 选拔结束时的完整摘要
- `SelectionMemoryProfile`
  - 本战消费的压缩摘要

### 3.3 输出对象

- `DecisionResult`
  - 当前步的决策结果
- `selection_evaluation`
  - 选拔评价报表
- `finals_evaluation`
  - 本战评价报表
- `star_evaluation`
  - 星性评价报表
- `overall_assessment`
  - 当前样本复盘结果

## 4. 当前评分方式

当前路线评分仍是工程化近似，不是官方公式。

主要结构是：

- `immediate_value`
- `target_gap_score`
- `synergy_score`
- `risk_penalty`

再配合：

- `HardGate`
  - 处理非法 / 强制 / 低体力禁止项
- `SoftGate`
  - 处理 build 偏好、主副属性、P 点缺口、星性缺口等
- `BeamPlanner`
  - 处理 2~3 步浅层前瞻

## 5. 当前评价体系与算法的关系

当前文档口径统一为：

- `ScenarioConfig`
  - 主要承载“当前评分器怎么打分”
- `HIFEvaluationConfig`
  - 主要承载“HIF 已知评价体系是什么”

这两者暂时还没有完全合并。

也就是说：

- 当前 simulator 已能输出 HIF 评价报表
- 但还没有把整套 HIF 评价体系完全回灌到主评分器

这是后续的下一阶段工作。

## 6. 当前已知不足

- 候选池还是样本级，不是真实 HIF 候选池
- 奖励池不是真实随机奖励池
- 随机性还没有完整参数化
- 对战随机没有正式建模
- 最终高评价总公式未知

## 7. 当前使用建议

如果后续继续改 simulator，建议顺序是：

1. 先接真实候选池
2. 再接随机变量
3. 再把 `HIFEvaluationConfig` 真正接回主评分器
4. 最后才做更强搜索器或出牌模拟
