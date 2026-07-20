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

- [`../game-knowledge/hif.md`](../game-knowledge/hif.md)
  - 当前可复核的 HIF 核心机制条目
- [`summary.md`](summary.md)
  - HIF 已知信息、工程状态与待验证项的详细总复盘
- [`evaluation.md`](evaluation.md)
  - 评价体系、属性分配、本战权重、星星地位
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

### 实现与资源

- [`mvp.md`](mvp.md)
  - HIF MVP 范围与验收口径
- [`resources.md`](resources.md)
  - HIF 识别资源与模板清单
- [`observations.md`](observations.md)
  - 从本战每日记录提炼的原子观察与升级状态
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
- 星星不是普通附属项，更接近 HIF 的核心资源或乘区
- `HIFボーナス` 是 HIF 特有的成长层，当前对路线和资源节奏影响很大
- HIF 参数上限已由当前日文原版实机 UI 多日记录为 `3200`
- 属性占比不是固定 `33/33/33`
  - 受当场审查倍率影响
- HIF 有固定骨架，但仍存在：
  - 公开课收益波动
  - 支援卡事件随机
  - 奖励候选随机
  - 对战抽牌随机

如果想先看可复核的整体机制，请先看：

- [`../game-knowledge/hif.md`](../game-knowledge/hif.md)

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
- 出牌模拟
- 多角色泛化
- 精确最终高评价公式

## 6. 当前文档使用约定

- **核心机制事实** 写在：
  - [`../game-knowledge/hif.md`](../game-knowledge/hif.md)
- **HIF 的详细解释、评价与随机性建模** 写在：
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

## 7. 与项目文档库的归属

HIF 的核心机制收束在 `../game-knowledge/hif.md`；本目录保留详细来源、专项设计与运行资料，避免同一结论复制两次：

- 游戏机制知识：`../game-knowledge/hif.md`；`summary.md`、`evaluation.md`、`randomness.md`、`research.md` 作为详细解释与来源；
- 当前实现与设计：`algorithm.md`、`architecture.md`、`decisions.md`、`mvp.md`、`hif-simulator-flow-design.md`、`maaframework-json-development-research.md`、`roi-integration-plan.md`；
- 测试、复盘与运行经验：`day2-lesson-retrospective.md`、`finals-daily-review.md`、`testing.md`、`runtime-calibration.md`；
- 资源、原始观察与运行记录：`resources.md`、`finals-daily-log.md`、`observations.md`、`handoff.md`、`dmm-baseline.md`。

其中 `finals-daily-log.md` 和 `handoff.md` 是证据/运行记录，不应绕过复核直接作为自动化动作依据；DMM 基线是历史兼容记录，不覆盖 MuMu 主线。
