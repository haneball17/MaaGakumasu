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

## 8. 进阶算法调研结论（2026-07-12）

本节用于记录后续决策器的技术选型，不表示下列算法已经在本项目实测有效。
论文或其他项目中的收益不能直接外推到 HIF；能否优于当前规则，首先取决于真实候选池、随机转移和识别状态是否被可靠记录。

结论是：当前最值得演进的方向是**带安全约束的随机滚动规划**，而不是直接训练端到端强化学习模型。

对离散候选动作，可将每个动作的目标写成：

```text
J(a) = E[最终收益 | a]
       - λ × P(失败 | a)
       - μ × CVaRα(低收益损失 | a)
```

其中 `CVaRα` 用于惩罚最差 `α` 比例结果的平均损失。`HardGate` 继续作为不可越过的约束：状态缺失、识别置信度不足、候选不唯一、预算不足或高风险动作均不进入评分和搜索。

## 9. 当前实现审计

当前 `BeamPlanner` 是确定性、有限深度的最大化搜索：对候选动作调用 `StateReducer`，递归累加即时分与未来分。

- 默认配置为 `lookahead_depth = 3`、`beam_width = 4`。
- `_beam_score()` 会排序并取 `top[0]` 返回；因此当前返回值只保留最高分路径，`beam_width` 不会改变最终分支选择。
- 这不是保留多条状态序列并逐层扩展的完整 Beam Search，也没有机会节点、随机采样或观测不确定性。
- 已存在 `observed_selected_action_id` 时，模拟器会优先回放该实测动作；它不是基于评分的自主决策。

因此，第一项算法改造应是让当前搜索器成为可验证的“真实 Beam / 随机 Rollout”实现，而不是立即替换成黑盒学习模型。

## 10. 方案对比

| 方案                                             | 适合解决的问题                               | 优势                                                                 | 主要代价与风险                                       | 当前建议                          |
| ------------------------------------------------ | -------------------------------------------- | -------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------- |
| 真实 Beam + 约束随机 Rollout（MPC / Expectimax） | 日程、奖励、Interval 等离散多步选择          | 每步只执行第一动作，重新观测后再规划；可直接纳入失败概率和低收益风险 | 需要经验转移分布；模拟器失真会系统性误导             | **首选**                          |
| MCTS / UCT                                       | 分支较多、深度较深、随机结果较多的路线规划   | 将搜索预算集中在有希望的分支，通常比穷举更可扩展                     | 仍需可用的状态转移生成器；采样数不足时结果不稳定     | 候选池和随机变量结构化后引入      |
| POMCP（部分可观测 MCTS）                         | OCR 有歧义、状态隐藏或随机状态无法直接读取   | 在信念状态上做搜索，可把识别置信度与观测结果一并纳入                 | 需要观测模型/生成器，调试和采样成本高                | ROI、OCR 与候选可信度稳定后再评估 |
| 示范学习 + 学习排序 / 价值模型                   | 已有高质量实机路线，希望快速比较屏幕上的候选 | 推理快、可先用轻量树模型，适合作为搜索叶节点估值或候选排序           | 仅模仿旧策略会继承偏差；未选择动作缺少反事实标签     | 在影子模式积累数据后实施          |
| 贝叶斯优化                                       | 体力阈值、权重、预设和搜索参数的全局调优     | 不改变运行时决策结构，样本效率高，适合昂贵的离线模拟实验             | 只能调全局参数，不能替代逐步策略                     | **近期可做**                      |
| 离线强化学习（如 CQL）                           | 长程收益不能由人工权重充分表达               | 可只使用已收集的离线轨迹学习策略；保守算法会降低分布外动作的价值高估 | 需要大量、覆盖多种策略的轨迹；奖励设计与离线评估困难 | 数据覆盖充分后再做                |
| MuZero 式学习模型 + MCTS                         | 希望同时学习转移、价值与策略的高上限方案     | 在复杂游戏中可将学习模型和树搜索结合                                 | 数据、算力和验证成本都很高；错误模型会带来高风险动作 | 当前不建议投入                    |

安全约束不是上述方案的替代项。无论采用何种搜索或学习方法，都应将 `HardGate`、OCR 置信度门槛、候选唯一性检查和前后帧验证保留在策略器外层，作为执行前的安全护栏。

## 11. 推荐落地顺序

### 阶段 A：修正当前离线规划器

1. 将当前搜索器重命名为“有限深度最大化搜索”，或实现真正的 Beam：每层保留 `B` 个完整 `SimulationState` 路径，再继续展开。
2. 为每个动作引入可重放的转移结果集合，而不是只调用确定性的 `StateReducer`。
3. 在结果中同时输出期望收益、失败概率、低分风险、命中的硬约束和回退原因。
4. 固定随机种子，保证同一 observed case 的搜索结果可重复。

### 阶段 B：用数据调优而非在线试错

1. 从 HIF Journal / 影子模式记录完整决策样本：页面、状态、OCR 置信度、所有可见候选、实际选择、下一状态、最终收益和失败原因。
2. 不把“未选择候选”误标成失败样本；它们没有反事实结果，只能作为候选覆盖信息。
3. 对已有规则的阈值和权重进行贝叶斯优化，以固定的回放集、成功率和风险指标作为黑盒目标。
4. 用按实机 session 划分的保留集验证，避免同一条路线的相邻步骤同时落入训练与验证集。

### 阶段 C：引入约束随机规划

1. 在日程、奖励、Interval 等低风险页面先运行影子 Rollout，输出推荐动作及其风险说明。
2. 仅当状态完整、候选唯一、动作收益优势超过阈值且风险低于上限时，才开放单步执行。
3. 每次执行后重新截图和读状态；一旦预测与实际偏离，停止并记录样本，而不是沿用旧计划连续点击。
4. 当候选数或有效深度使完整扩展过慢时，再以 MCTS / UCT 替代固定宽度搜索。

### 阶段 D：学习式策略作为增强，而非替换

1. 先训练候选排序或价值估计模型，用于修正人工 `SoftGate` 分数和给 MCTS 叶节点估值。
2. 只有在日志覆盖多个预设、多个资源状态和足够多失败/成功轨迹后，才评估 CQL 等离线强化学习。
3. MuZero 类方案必须先证明数据量、离线评测、风险控制和模型校准均已满足要求；不应把它作为当前 HIF 实机闭环的前置条件。

## 12. 验收指标

- 搜索正确性：`beam_width`、深度、随机种子和机会节点变化会产生可解释且可重放的差异。
- 安全性：所有状态缺失、低置信度、候选歧义和 `HardGate` 拒绝均不会触发点击。
- 离线效果：在未参与调参的 observed case 上，同时报告收益、完成率、失败率和低分风险；不只报告平均分。
- 执行效果：先比较影子建议与实测选择，再逐页开放单步动作；连续模式仍需独立验收。

## 13. 外部资料

以下资料于 2026-07-12 查阅，均用于算法适配与边界判断：

- [Browne et al., _A Survey of Monte Carlo Tree Search Methods_（IEEE，2012）](https://ieeexplore.ieee.org/document/6145622)
- [Silver & Veness, _Monte-Carlo Planning in Large POMDPs_（NeurIPS，2010）](https://proceedings.neurips.cc/paper_files/paper/2010/hash/edfbe1afcf9246bb0d40eb4d8027d90f-Abstract.html)
- [Williams et al., _Model Predictive Path Integral Control_（2015）](https://arxiv.org/abs/1509.01149)
- [Ross et al., _DAgger: A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning_（AISTATS，2011）](https://proceedings.mlr.press/v15/ross11a.html)
- [Kumar et al., _Conservative Q-Learning for Offline Reinforcement Learning_（NeurIPS，2020）](https://proceedings.neurips.cc/paper_files/paper/2020/hash/0d2b2061826a5df3221116a5085a6052-Abstract.html)
- [Snoek et al., _Practical Bayesian Optimization of Machine Learning Algorithms_（NeurIPS，2012）](https://proceedings.neurips.cc/paper_files/paper/2012/hash/05311655a15b75fab86956663e1819cd-Abstract.html)
- [Achiam et al., _Constrained Policy Optimization_（ICML，2017）](https://proceedings.mlr.press/v70/achiam17a.html)
- [Schrittwieser et al., _MuZero_（Nature / arXiv，2020）](https://arxiv.org/abs/1911.08265)
