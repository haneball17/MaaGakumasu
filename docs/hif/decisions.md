# HIF 决策点

本页只负责说明 HIF 里哪些地方需要引入决策，以及优先级如何划分。

背景机制请看：

- [`summary.md`](summary.md)
- [`evaluation.md`](evaluation.md)
- [`randomness.md`](randomness.md)

## 1. 当前原则

当前项目还没有独立全局 `DecisionEngine`。

HIF 当前落地方式是：

- `pipeline + CustomAction`
- 离线 `CLI` 模拟器

所以当前的决策设计，优先目标不是抽象出一个大而全的策略系统，而是先把 HIF 局部决策做正确。

## 2. `P0`：当前必须做的决策

### 2.1 阶段识别

至少要能区分：

- `選抜試験モード`
- `本戦モード`
- `Round1`
- `Interval`
- `Round2`
- 失败 / 结算 / 未知页

### 2.2 路线选择

当前必须做的路线决策包括：

- 选拔日程选择
- 本战前 6 日准备
- `Interval` 预算分配

### 2.3 HIF P 道具选择

当前必须能做：

- 推荐项优先
- 星星 / 卡牌 / P 点相关收益区分

### 2.4 `SelectionSnapshot / SelectionMemoryProfile`

当前必须把选拔结果真正沉淀成：

- `SelectionSnapshot`
- `SelectionMemoryProfile`

否则本战阶段就无法稳定消费选拔结果。

### 2.5 评价报表

当前已经进入 `P0` 的还有：

- `selection_evaluation`
- `finals_evaluation`
- `star_evaluation`
- `overall_assessment`

因为后续开发要依赖这些报表理解 simulator 在做什么。

## 3. `P1`：下一轮应做的决策

### 3.1 奖励决策

包括：

- 拿卡
- 强化
- 删除
- 奖励候选排序

### 3.2 随机性建模

包括：

- 支援卡事件触发
- 奖励候选池
- 日程收益波动

### 3.3 真实候选池

当前 simulator 还是样本候选池。  
下一轮需要把：

- 真实 HIF 固定日程
- 真实候选类型
- 更接近实机的奖励池

接入模拟。

## 4. `P2`：长期目标

- 完整出牌决策
- 多角色泛化
- 高评价最优化
- 更强搜索器
- 全局 `DecisionEngine`
- 自动化实机闭环下的统一策略层

## 5. 当前不做的事

当前不应把以下内容混入 `P0`：

- 完整高评价公式还原
- 全角色统一评分器
- 所有随机变量一次建完
- 实机层、识别层、评分层同时大改

## 6. 一句话总结

当前 HIF 决策的开发顺序应理解成：

> 先把阶段、路线、P 道具、选拔产物和评价报表做稳，再逐步补奖励决策与随机性。
