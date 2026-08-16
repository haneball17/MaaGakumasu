# HIF 开发资料总览

这组文档用于支撑《学园偶像大师》`HIF`（初星アイドルフェスティバル）剧本的后续开发。

当前主线目标固定为：

- 角色卡：`姫崎 莉波（ガラクタロード）`
- 剧本：`HIF`
- 路线：`感性·好调`
- 环境：`MuMu 模拟器 12 + ADB + 日文原版`
- 当前实现重点：离线 `CLI` 决策模拟、评价报表、后续接回自动化

## 1. 这套资料回答什么问题

这组文档主要服务开发，不是玩家向攻略大全。

它重点回答：

- HIF 的完整结构是什么
- 已知评价体系是什么
- 哪些机制能直接写入配置或评分器
- 哪些地方存在随机性
- 当前代码和文档已经落实到什么程度
- 还有哪些信息必须等实机验证

## 2. 资料可信度分层

后续阅读时统一按下面 4 层判断：

1. **官方 / 游戏内可确认**
   - 官方站点、官方问答、游戏内机制说明
2. **攻略站共识**
   - Game8、Wikiwiki 等资料站长期稳定结论
3. **社区经验**
   - note、博客、玩家复盘
4. **当前工程假设**
   - 为了实现模拟器和自动化而做的开发抽象

如果不同来源冲突，优先级按上面顺序处理。

## 3. 建议阅读顺序

### 机制与资料

- [`summary.md`](summary.md)
  - 当前 HIF 已知信息的总复盘
- [`evaluation.md`](evaluation.md)
  - 评价体系、属性分配、本战权重、星性地位
- [`randomness.md`](randomness.md)
  - HIF 随机要素与开发建模建议
- [`research.md`](research.md)
  - 资料来源、来源层级、结论出处

本轮新补的关键机制主要集中在：

- HIF 前置条件与系统边界
- 选拔 / 本战固定日程骨架
- 本战第 3 日的 `おでかけ / 差し入れ`
- `HIFボーナス` 的当前定位
- 随机项与非随机项的边界

### 算法与决策

- [`algorithm.md`](algorithm.md)
  - 决策算法、对象模型、CLI 模拟主流程
- [`decisions.md`](decisions.md)
  - 决策点分层与优先级
- [`architecture.md`](architecture.md)
  - 当前架构与后续实现边界
- [`roundsim-design.md`](roundsim-design.md)
  - Round 模拟器设计定案（2026-08-16，四轮 grill + 两轮复盘）：出牌级考试模拟、A/B 平台、実機回放校验、Vue/FastAPI 可视化前端；含 ScenarioSpec、假设清单与里程碑 M1-M5/M-UI。未开工。

### 实现与资源

- [`mvp.md`](mvp.md)
  - HIF MVP 范围与验收口径
- [`resources.md`](resources.md)
  - HIF 识别资源与模板清单
- [`dmm-baseline.md`](dmm-baseline.md)
  - DMM 冻结基线记录

### 角色路线

- [`profiles/rinami-garakuta-kansei-good-condition.md`](profiles/rinami-garakuta-kansei-good-condition.md)
  - `姫崎 莉波（ガラクタロード）` 的当前主路线资料
- [`high-score.md`](high-score.md)
  - 高评价 / `S4+` 方向，非当前第一优先级

## 4. 当前最关键的已知结论

- HIF 分为：
  - `選抜試験モード`（20 日，3 次试验）
  - `本戦モード`（7 日，`Round1` → `Interval` → `Round2`）
- HIF 入口前当前可确认的最低参与条件是：
  - 角色 `親愛度27`
- HIF 当前文档默认会把剧本内的 `カスタムPアイテム` 视为正式机制输入
- 选拔总属性奖励结构可拆成：
  - 固定部分 `600`
  - 按得分占比分配部分 `500`
  - 总计 `1100`
- 本战总分结构可拆成：
  - `Round1 × 1.2`
  - `Round2 × 1.0`
- 星性不是普通附属项，更接近 HIF 的核心资源或乘区
- `HIFボーナス` 是 HIF 特有的成长层，当前对路线和资源节奏影响很大
- HIF 参数上限当前按攻略站资料记为 `3000`
- 属性占比不是固定 `33/33/33`
  - 受当场审查倍率影响
- HIF 有固定骨架，但仍存在：
  - 公开课收益波动
  - 支援卡事件随机
  - 奖励候选随机
  - 对战抽牌随机

如果想先看整体机制，请先看：

- [`summary.md`](summary.md)

如果想先看评价体系与前置条件，请看：

- [`evaluation.md`](evaluation.md)

如果想先区分随机与非随机，请看：

- [`randomness.md`](randomness.md)

## 5. 当前开发状态

当前已经有：

- HIF 入口与主流水线骨架
- HIF `CustomAction` 骨架
- 离线 `CLI` 决策模拟器
- HIF 评价报表
- `HIFEvaluationConfig`
- `SelectionSnapshot`
- `SelectionMemoryProfile`

当前还没有：

- 实机驱动下的 HIF 全流程稳定闭环
- 真实奖励池与真实 HIF 固定日程的完整接入
- 出牌模拟（Round 模拟器已设计定案，见 [`roundsim-design.md`](roundsim-design.md)，未开工）
- 多角色泛化
- 精确最终高评价公式

## 6. 当前文档使用约定

- **机制事实** 尽量写在：
  - `summary.md`
  - `evaluation.md`
  - `randomness.md`
- **实现方案** 尽量写在：
  - `algorithm.md`
  - `decisions.md`
  - `architecture.md`
- **来源出处** 统一回到：
  - `research.md`

这样后续开发时，能把“事实、抽象、实现”分开看。
