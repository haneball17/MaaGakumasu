# Plan: HIF 出牌决策算法

_Locked via grilling — 由用户与当前 Codex 代理于 2026-07-15 逐项确认；决策模块接口于同日二次 grilling 后冻结_

_Branch: `codex/decision-algorithm`_

本计划总结 `rinami_garakuta_road` 的 HIF Round1/Round2 出牌决策算法。它定义后续算法工程与上线门槛，
不扩大根目录 `PLAN.md` 已记录的当前实机授权，不允许绕过完整状态、唯一目标、两段式确认、语义后验或其他硬停止条件。

## 1. 范围与优化目标

- 首版只覆盖姫崎莉波 `ガラクタロード` 的 HIF Round1/Round2，不宣称支持其他偶像、流派或场景。
- 优化目标按词典序排列：
    1. 排除非法、灰牌、状态不完整、模型不支持和可能破坏关键循环的动作；
    2. 优先保证 HIF 优胜；
    3. 达到安全优胜线后，最大化 `1.2 × Round1 分数 + Round2 分数` 的期望值。
- 使用最差 10% 情景的平均加权总分 `CVaR₁₀` 衡量坏牌序风险，不以平均分单独决定动作。
- 动态目标线定义为：

    ```text
    基础目标 = max(可信实时对手目标, 当前配置档历史 P95 优胜线)
    安全目标 = 基础目标 + max(50,000, 基础目标 × 5%)
    ```

- 实时目标不可读时回退到历史 P95；历史样本不足时可暂用攻略经验值冷启动，但必须标记低置信度，
  不得将固定分数写成永久真值。
- 存在 `CVaR₁₀ >= 安全目标` 的动作时，只在这些安全动作中最大化期望总分；不存在时选择
  `CVaR₁₀` 最高的动作，优先降低失败损失。

## 2. 状态模型与真值来源

- 使用纯 Python、白名单式高保真牌局模拟器；TypeScript/Node 引擎只可作为离线参考或差分对照，
  不成为生产运行时依赖。
- 规划器只接受唯一、已验证、可规范化的 `BattleState`。至少包含：
    - Round、当前/剩余回合、当前审查属性与倍率；
    - 当前分数、体力、集中、好调及所有已支持持续状态；
    - 完整手牌及强化等级、牌库/弃牌堆/除外区的卡牌多重集合；
    - 卡牌使用次数、再演次数、关键卡已使用标记；
    - P 道具、P 饮料、额外抽牌/换手能力和跨 Round 资源。
- “下一张牌未知”按已知剩余牌组的无放回随机事件建模；剩余牌组组成不可信时不得启用搜索。
- 首版不维护多个 OCR 假设，不实现 belief state、POMDP 或 POMCP。识别冲突必须有限重读，仍不唯一则停止。
- 真值优先级：
    1. 当前游戏实机的动作前后状态轨迹；
    2. 解包得到的结构化 Master 数据；
    3. `gakumas-core` 等公开模拟器；
    4. Wiki、攻略与经验规则。
- 来源冲突时以实机为准；无法解释的卡牌、强化等级或效果必须移出白名单，不能猜测实现。

## 3. 状态转移与动作空间

- 为当前路线可能出现的卡牌、强化等级、P 道具和 P 饮料逐项实现显式状态转移；不要求首版覆盖全卡池。
- 合法动作统一包含：
    - 使用一张具体且可执行的卡牌；
    - 使用一个已支持的 P 饮料；
    - 已验证的额外抽牌；
    - 已验证的换手；
    - 结束当前行动。
- 不消耗正常出牌次数的资源动作使用独立动作阶段；每个消耗品最多使用一次，每个动作必须改变规范化状态，
  防止搜索产生零进展循环。
- 灰牌、条件不足、资源不足、重复使用和不支持效果由 Hard Gate 排除，搜索器无权覆盖这些规则。
- 状态完整但搜索超时、候选无法可靠区分或局部模型不支持时，只能回退到能产生唯一、显式、已验证目标的
  `GarakutaRinamiStrategy` 规则；状态不完整时不得使用启发式猜测。

## 4. 在线规划算法

- 核心算法冻结为“情景采样 Sparse Expectimax + 滚动时域重规划（MPC）”。
- 每次只执行当前最优动作；完成截图、状态重读和语义后验后，从真实新状态重新规划。
- 所有根动作使用同一随机数流生成未来牌序，避免候选因面对不同抽牌运气而产生比较偏差。
- 对关键卡早抽、晚抽、未抽到等低概率高影响事件进行分层采样，并按真实概率加权。
- 搜索调度：
    1. 128 个共同情景用于初步比较；
    2. 256 个共同情景作为基础完整比较；
    3. 候选接近、使用稀缺资源、接近终结窗口或优胜线时，按 64 个情景一批追加到 512～1024；
    4. 随机后继足够少时自动切换为精确枚举。
- 标准动作深度为 2～3；预算充足且前两名候选仍接近时，只对前两名选择性搜索深度 4。
- 只采用完整完成的深度和样本批次；不能把超时中断的半批结果混入最终统计。
- 12 秒软限制之后不再开启新深度或样本批次；16 秒硬限制必须返回最后一个完整批次的结果。
- 候选已可靠分离时允许提前返回，不得为了用满预算继续无收益计算。
- 性能上线门槛：决策耗时中位数不超过 4 秒，P95 不超过 12 秒，绝对最大值不超过 16 秒。

## 5. 叶节点估值与跨 Round 续局价值

- 已结束局面使用真实分数、动态优胜目标与最终优胜结果，不再调用近似估值。
- 未结束局面的可解释特征至少包括：
    - 当前分数、剩余回合、审查属性倍率和预计优胜缺口；
    - 集中、好调及其他持续状态在剩余回合中的未来收益；
    - 再演次数、关键卡位置、循环完整度和终结技可达概率；
    - 体力安全余量、P 饮料、额外抽牌/换手资源；
    - 手牌、牌库、弃牌堆、除外区和关键卡未来抽取概率。
- Round1 不搜索完整 21 回合，而在叶节点加入 Interval/Round2 续局价值；Round1 结束后读取真实分数、资源和牌组，
  重新规划 Interval 与 Round2。
- 不硬编码“必须留一瓶饮料”或“Round1 必须用光资源”；资源使用由总成绩的 `CVaR₁₀` 与续局价值决定。
- 特征由人设计并保持可解释；权重通过离线高预算搜索/完整模拟结果进行受约束校准，不训练神经价值网络。
- 权重训练牌序与验收牌序必须分离；每个特征、权重、分项值和最终值都写入可复算日志。

## 6. 可观测性、可复现性与决策审计

日志是执行安全协议的一部分，而不是附加的调试输出。详细契约见：

- [日志事件目录](logging/EVENT_CATALOG.md)
- [日志 Schema](logging/SCHEMA.md)
- [ADR-001：本地决策审计架构](logging/ADR-001-local-decision-audit.md)
- [日志术语表](logging/GLOSSARY.md)

### 6.1 追踪模型与动作生命周期

- 业务追踪层级固定为
  `run_id → round_id → turn_id → decision_id → action_attempt_id → event_id`；`session_id` 只表示一次进程会话，
  不再代替一次完整培育运行。
- `trace_id` 贯穿整个 `run_id`；搜索、审批、执行和验证使用有父子关系的 `span_id`/`parent_span_id`，便于以后映射到
  OpenTelemetry，但首版本地 JSONL 不依赖 OpenTelemetry SDK 或服务端。
- 每次动作必须经过
  `observed → normalized → planned → approved → intended → executed → verified`。不成功时使用
  `rejected`、`failed`、`timed_out`、`stopped` 或 `abandoned` 等明确终态；不适用的阶段记录 `skipped` 和原因，不能静默跳过。
- `verified` 必须比较动作后的语义状态与预期状态，不能只以截图像素发生变化作为成功依据。

### 6.2 四层日志与失败语义

- `audit`：状态、决策、审批、执行、验证、停止与恢复的最小审计主线。
- `decision`：候选评分、风险指标、采样、剪枝、预算和降级细节。
- `diagnostic`：识别、性能、组件异常等可丢失的诊断信息。
- `evidence`：截图、完整状态快照和逐情景明细等大对象；结构化日志只引用相对路径、类型、字节数和完整 SHA-256。
- 审计关键事件必须先通过 Schema 校验并成功持久化，才允许发送危险输入。决策输入、根候选评估摘要、最终决策、
  执行意图、控制器输入、语义后验、安全停止和恢复均属于关键事件。
- 关键事件写入失败时默认立即重试 2 次；主 journal 仍不可用时尝试本次运行的 `audit/emergency-<session_id>.jsonl`。
  备用 journal 也不可用则禁止点击并安全停止。若点击后 `action.executed` 回执无法落盘，立即停止后续输入；此前已持久化的
  `action.intended` 必须包含足以确认该次控制器命令的完整参数。
- `diagnostic` 写入失败可以继续，但必须在可用的 `audit` 通道写入 `telemetry_degraded` 并产生可见告警；不得静默吞掉。

### 6.3 事件契约与本地可靠性

- 所有事件使用版本化强制 Schema，公共信封至少包含事件契约、追踪 ID、UTC 事件时间与观察时间、单调时钟、严重级别、
  组件与代码/算法/配置版本、结构化主体、状态、原因码、错误和证据引用。
- `event_name`、字段名、状态和原因码是稳定机器契约；人类说明不能代替枚举。新增字段可以向前兼容，删除或改变语义必须提升版本。
- 审计事件使用严格递增的 `sequence_no`。每条 JSONL 只有在完整写入换行并刷新后才算提交；启动时隔离末尾残行并记录恢复事件。
- 首版不实现防恶意篡改的哈希链、数字签名或远端只追加存储。证据 SHA-256 只用于确认引用对象和支持确定性复算。
- 游戏相关截图、玩家名、OCR 文本无需脱敏；采集采用字段白名单，禁止记录访问令牌、Cookie、环境变量、系统凭据及其他与决策无关的秘密。

### 6.4 状态与搜索记录

- 随机种子由规范化状态哈希与完整版本快照生成，不使用当前时间、进程/运行 ID 或机器信息。
- 每个 `decision_id` 保存：
    - `observed_state`：识别器原始结果、候选值、置信度和截图引用；
    - `normalized_state`：实际传入算法的完整状态、Schema 版本和 SHA-256；
    - `state_diff`：相对上一有效状态的结构化变化及原因。
- 决策事件必须引用实际使用的 `normalized_state_hash`。识别状态与规范化状态冲突时有限重读；仍冲突则拒绝规划并安全停止，
  不允许用新值静默覆盖旧值。
- 每个根候选始终记录期望收益、`CVaR₁₀`、安全违规概率、置信区间、评分分解和排名；同时记录随机种子、情景生成器版本、
  分层、样本数、完整深度、批次、剪枝、软硬超时和降级原因。
- 正常决策保存获选动作与最接近竞争者的逐情景明细。分差过小、接近安全线、使用稀缺资源、超时、降级、异常或显式追踪时，
  保存全部根候选的逐情景明细；深层节点默认聚合，按 `decision_id` 显式开启详细追踪。
- 同一规范化状态、算法/数据/权重版本、配置、随机种子和完整批次序列必须得到相同候选顺序、评分和最终动作；
  在线模式因机器性能不同而完成的批次数可以不同，运行耗时无需一致。

### 6.5 存储、恢复、查询与保留

- 每个 `run_id` 使用独立目录，每个 `session_id` 新建日志分段；恢复事件引用上一 session、分段和最后 `sequence_no`。
- 重启后必须重新识别当前语义状态。只有状态能与上一已验证状态合理衔接时才延续原 `run_id`；否则终止旧运行并创建新运行。
  对停在 `intended` 或 `executed`、尚未 `verified` 的动作，必须先判定实际结果，不能直接重放点击。
- 提供轻量 CLI，支持按层级 ID/状态/原因筛选、生成单次决策时间线、查看根候选排名、校验 Schema/序号/引用/哈希、
  确定性离线重放，并生成带证据链接的人类可读 Markdown 报告。
- 运行完成后压缩逐情景明细和截图，`audit` JSONL 保持可直接读取。默认保留策略：
    - `audit` 与 `decision`：180 天且总量不超过 2 GB；
    - `diagnostic` 与 `evidence`：30 天且总量不超过 10 GB。
- 时间或容量任一超限时优先清理最早完成的运行；当前运行、异常退出尚未审查的运行和用户锁定的运行不得自动删除。
  清理动作记录被清理的 `run_id`、原因和释放空间；接近磁盘安全阈值时提前告警。

## 7. 决策模块接口契约

### 7.1 当前状态与模块边界

- 现有旧接口 `GarakutaRinamiStrategy.decide(ExamState) -> CardAction` 已实现并由 `ProduceCardsHIF` 调用，但其输入只有简化手牌摘要和
  部分数值，输出只有单一动作与人类理由，不能承载本计划的搜索、风险统计与重放要求。
- 本节定义的新接口已经完成设计冻结，但 Python 类型、JSON Schema、状态组装、搜索器以及与 HIF 管线的影子集成均尚未实现。
- 新规划器必须是纯 Python、同步、无 MaaFramework/UI/文件系统依赖的领域接口：

    ```python
    class DecisionBackend(Protocol):
        def plan(self, request: PlanningRequest) -> PlanningResult: ...
    ```

- OCR、截图、页面探测与打开/读取/关闭牌库属于 `ObservationOperation`；出牌、饮料、额外抽牌、换手和结束行动属于
  `BattleAction`。观察操作不得作为规划候选，状态不完整时必须先由观察编排层补齐或停止。
- 端到端数据流固定为：

    ```text
    ObservedBattleSnapshot + VerifiedRunKnowledge
        → BattleStateAssembler
        → StateReady | StateRejected
        → PlanningRequest
        → DecisionBackend.plan()
        → PlanningResult
        → DecisionExecutionPolicy
        → PlanningResultRevalidator
        → BattleActionResolver
        → ExecutionSafetyGate
        → BattleActionExecutor / CommandReceipt
        → BattlePostconditionVerifier / VerificationResult
    ```

### 7.2 `PlanningRequest`：正式输入

`PlanningRequest` 是不可变、可规范序列化的完整输入：

```python
@dataclass(frozen=True, slots=True)
class PlanningRequest:
    schema_version: str
    state: BattleState
    objective: ObjectiveSnapshot
    budget: OnlineBudget | ReplayBudget
    seed_material: SeedMaterial
    decision_seed: str
    versions: VersionSnapshot
```

- `BattleState` 只保存牌局事实：Round/回合、当前分数、审查属性与倍率、体力、集中/好调及全部白名单状态、完整手牌、牌库、
  弃牌堆、除外区、使用次数、关键卡标记、P 饮料、P 道具、额外抽牌/换手资源和跨 Round 资源。
- `DeckManifest` 是 Round1/Round2 搜索不可绕过的硬前提。它保存 `card_id`、强化等级、效果版本、重复数量、来源和证据，
  `total_count` 接受当前路线经验证的实际牌组数量（通常 22～25），不得写死固定张数。
- 卡牌分为 `CardSpec(card_id, upgrade_level, effect_version)`、逻辑实例 `CardInstance(deck_card_id, spec, state)` 和多重集合项
  `CardCount(spec, count)`。所有区域必须满足 `hand + draw_pile + discard_pile + exile_pile = DeckManifest`。
- `deck_card_id` 按 `<card_id>:<upgrade_level>:<copy_index>` 确定性生成并跨区域保持；当前截图的 `observation_target_id` 仅用于
  UI 映射，不进入领域状态哈希。
- `ObjectiveSnapshot` 与 `BattleState` 分离，保存实时目标及置信度/来源、历史 P95 及样本档案、基础目标、安全余量、安全目标、
  `CVaR` 的 `alpha=0.10` 和 `1.2 × S1 + S2` 公式版本。规划器不得自行读取 OCR 或历史文件。
- `OnlineBudget` 至少包含 12 秒软/16 秒硬限制、128/256 基础情景、64 批大小、1024 最大情景以及标准/选择性深度；
  `ReplayBudget` 保存需要严格重放的完整 `BatchSpec` 序列。
- `VersionSnapshot` 至少包含算法、规则、卡牌目录、估值器、权重、情景生成器和配置版本。注入依赖的实际版本与请求不一致时，
  返回 `STOPPED/version_mismatch`，不得静默使用当前版本解释旧请求。
- `PlanningRequest` 不包含截图、OCR 对象、识别置信度、点击坐标、MaaFramework `Context`、日志对象、模型对象或时钟对象。

规划器的 `BattleModel`、`StateEvaluator`、`ContinuationValueModel`、`ScenarioGenerator` 与 `MonotonicClock` 通过构造器注入；请求本身
必须能独立保存为 JSON。

### 7.3 状态组装接口

```python
class BattleStateAssembler(Protocol):
    def build(
        self,
        observed: ObservedBattleSnapshot,
        knowledge: VerifiedRunKnowledge,
    ) -> StateReady | StateRejected: ...
```

- `ObservedBattleSnapshot` 为每个字段保存值、候选值、置信度、识别器版本、帧/ROI 证据和观察时间。
- `VerifiedRunKnowledge` 只保存已验证事实：`DeckManifest`、当前区域账本、上一已验证状态、动作/转移、已用资源和跨 Round 资源；
  它必须支持跨进程持久化，不能只依赖当前内存 Session。
- `StateReady` 返回不可变 `BattleState`、`state_hash`、`StateDiff` 与 `InvariantReport`。
- `StateRejected` 返回缺失字段、冲突、未知实体、稳定原因码和是否值得重读。首版不向规划器传多个候选状态，不实现 belief state/POMDP。
- 识别与预测冲突时不得用模拟值覆盖实机值；有限重读后仍不唯一则停止。进程恢复、状态守恒失败、未知抽牌或跨 Round 牌组变化时，
  必须重新执行牌组观察操作并验证 Manifest。

### 7.4 `PlanningResult`：正式输出

```python
@dataclass(frozen=True, slots=True)
class PlanningResult:
    status: PlanningStatus
    selected_action: BattleAction | None
    candidates: tuple[CandidateEvaluation, ...]
    rejected_actions: tuple[RejectedAction, ...]
    search_summary: SearchSummary
    trace: DecisionTrace
    reason_code: PlanningReason | None
    planned_state_hash: str
    planned_round: BattleRound
    planned_turn: int
    versions: VersionSnapshot
```

- `PlanningStatus` 只有 `SELECTED`、`DEGRADED`、`STOPPED`。预期的超时、无合法动作、模型不支持和安全回退用类型化结果表达；
  状态守恒破坏、未知内部枚举、候选引用不存在实体或非确定性断言失败等程序契约缺陷才抛异常。编排层捕获异常后记录失败并安全停止。
- `CandidateEvaluation` 必须覆盖全部合法根候选，至少包含动作、稳定排名、情景数、均值、中位数、P10、`CVaR₁₀`、胜率、失败率、
  安全违规概率、安全线差值、置信区间、评分分解、资源投影、完成深度、状态和原因码。
- `RejectedAction` 保存被领域 Gate 排除的动作及稳定原因；不得把灰牌、资源不足或未知效果混入候选排名。
- `DecisionTrace` 保存状态哈希、种子、目标快照、版本、所有完整批次、情景生成信息、根候选统计、剪枝/超时/回退记录以及按策略保留的
  逐情景明细。规划器只返回结构化轨迹，不写日志或证据文件。
- `SearchSummary` 保存实际完整批次、深度、样本数、软硬预算状态、耗时和停止原因；半批次不得进入结果。
- `DEGRADED` 不自动取得执行权。`soft_budget_reached`/`hard_budget_reached` 只有达到最低完整样本并可靠分离时才可继续；
  `safe_fallback_used` 首版只允许影子或显式单步；`candidate_not_separable` 必须停止。

### 7.5 原子领域动作与后验契约

`PlanningResult` 每次最多选择一个原子动作：

```text
PlayCardAction(card_instance_id, expected_cost)
UseDrinkAction(resource_instance_id)
DrawAction(source_ability_id)
SwapHandAction(source_ability_id, card_instance_ids)
EndTurnAction(reason_code)
```

- 动作公共字段为确定性 `action_key`、`action_type`、`precondition_state_hash`、资源消耗和 `PostconditionSpec`。`action_key` 由前置状态哈希、
  动作类型与规范 payload 计算；随机 UUID `action_attempt_id` 只在实际执行尝试时创建，不参与排名、哈希或种子。
- `PostconditionSpec` 描述确定断言、随机合法结果集合、区域守恒、禁止结果和验证超时，不要求抽牌等随机动作命中一个预设的新状态。
- `CommandReceipt` 只证明控制器尝试发送输入；只有 `VerificationResult(status=verified, after_state, state_hash, diff, assertions, evidence)`
  才能更新 `VerifiedRunKnowledge`。验证失败或超时时不得直接重发可能已经生效的点击。
- 规划完成后必须使用最新页面和状态哈希重新验证；任何变化都将旧结果标记为 `abandoned/state_changed_before_execution` 并创建新
  `decision_id` 重新规划。

### 7.6 辅助 Protocol 的职责

| 接口                                           | 输入                                           | 输出与职责                                                   |
| ---------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------ |
| `BattleModel.legal_actions`                    | `BattleState`                                  | 唯一领域合法动作集；游戏规则 Hard Gate                       |
| `BattleModel.apply`                            | 状态、动作、`ScenarioRandomInput`              | 新不可变状态、哈希、资源/分数/状态变化与不变量报告           |
| `StateEvaluator.evaluate_leaf`                 | 状态、目标                                     | 当前 Round 可解释特征、权重、分项值和总叶节点价值            |
| `ContinuationValueModel.evaluate_continuation` | Round1 状态、跨 Round 资源、目标               | Round1 终值、Interval/Round2 续局价值、风险和资源影子价格    |
| `ScenarioGenerator.generate_batch`             | 种子、批号、索引范围、分层、牌组哈希           | 带真实概率权重和命名空间随机输入带的不可变情景批次           |
| `DecisionExecutionPolicy.evaluate`             | 规划结果、执行模式                             | 该状态/降级原因是否有资格进入执行安全 Gate                   |
| `PlanningResultRevalidator.revalidate`         | 结果、最新执行观察                             | 状态是否未变、是否必须重规划                                 |
| `BattleActionResolver.resolve`                 | 领域动作、绑定当前帧的观察                     | 唯一 `ResolvedAction` 或类型化拒绝；成功结果含精确控制器命令 |
| `ExecutionSafetyGate.approve`                  | 动作、最新状态/页面/目标/后验能力/日志提交状态 | 当前动作能否安全执行                                         |
| `BattleActionExecutor.execute`                 | `ResolvedAction`                               | 仅控制器层 `CommandReceipt`                                  |
| `BattlePostconditionVerifier.verify`           | 前状态、动作、后验约束、动作后观察             | `VerificationResult` 与唯一实机后状态                        |

`BattleModel` 不得在规划器内硬编码具体卡牌效果；相同状态、动作和随机输入必须得到相同转移。`ContinuationValueModel` 仅用于搜索估值，
实际进入 Interval/Round2 后仍必须以实机新状态重新规划。

### 7.7 情景、预算与确定性

- `DecisionSeedFactory` 使用规范化状态哈希、算法/规则/配置/情景生成器版本计算 SHA-256 主种子；不得加入时间、`run_id`、
  `session_id`、`decision_id` 或机器信息。
- 情景子种子按 `SHA-256(decision_seed + namespace + scenario_index)` 派生。抽牌、洗牌与随机效果使用独立命名空间，追加批次不得改变
  已有情景，所有根候选共享相同 `scenario_id`。
- 情景生成器输出 `random_tape` 而不是写死卡名序列；`BattleModel` 用当前稳定排序的合法牌库映射随机值，从而在换手、额外抽牌或除外后
  仍能合法使用共同随机输入。分层情景必须携带真实 `probability_weight`。
- 在线模式使用注入单调时钟，软限制后不启动新批次，硬限制返回最后完整批次；取消只在批次边界生效。
- 重放模式忽略墙上时间，严格执行日志保存的完整批次序列。因此确定性承诺是“相同状态、版本、配置、种子和完整批次序列得到相同结果”，
  不是承诺不同性能机器在同一秒数内完成相同工作量。
- `plan()` 对外保持纯函数语义。只允许单次决策内搜索缓存和带完整版本键的静态只读缓存；并行结果按稳定动作 payload 归并，
  不按线程完成顺序排名。

### 7.8 序列化、Schema 与兼容性

- 游戏离散量使用 JSON integer；倍率使用带显式 scale 的定点整数；概率、权重、CVaR 和置信区间使用规定精度的 `Decimal`，
  JSON 保存规范十进制字符串，禁止 NaN/Infinity 和未规定舍入的二进制浮点。
- 状态与动作哈希使用 UTF-8 规范 JSON：对象键排序、无多余空白、领域数组稳定排序，SHA-256 覆盖完整规范字节。
- 必须新增并版本控制 `battle-state.schema.json`、`battle-action.schema.json`、`objective-snapshot.schema.json`、
  `planning-request.schema.json` 和 `planning-result.schema.json`。
- 每次决策将完整请求与结果保存为 evidence；`planning.started`/终态事件引用其相对路径和 SHA-256。未知主版本拒绝执行，改变字段语义、
  类型或必填性必须提升主版本；历史产物只能通过显式离线迁移工具转换。
- 每个 Schema 必须有正常选牌、饮料、状态拒绝、超时降级和安全停止等合法示例，以及缺字段、错误类型和版本不匹配的非法样例。

### 7.9 旧策略迁移与完成定义

- 不修改旧 `decide(ExamState) -> CardAction` 来承载新算法。新增 `SparseExpectimaxBackend` 实现正式接口；
  `HeuristicFallbackAdapter` 包装旧策略，结果必须标记 `DEGRADED/safe_fallback_used`，不能伪造 CVaR 或候选统计。
- 状态不完整/冲突、未知效果、牌组不守恒、执行目标不唯一、日志失败或内部契约异常时禁止启发式回退。
- “接口设计完成”以本节字段/Protocol、JSON Schema、合法/非法示例、调用时序及字段来源/单位全部落盘为准。
- “接口已经实现”必须同时满足：Python dataclass/enum/Protocol、序列化/Schema 校验、规范状态哈希、动作/种子派生、旧策略适配器、
  `ProduceCardsHIF` 后端调用、影子请求/结果持久化、固定批次零偏差重放以及负向测试全部落地。
- 接口实现、模拟器规则覆盖、搜索算法完成和实机执行授权是四个独立里程碑；任何一个完成都不能冒充其余里程碑已完成。

## 8. 实施阶段

1. 按第 7 节实现 Python 契约、JSON Schema、规范序列化、合法/非法样例和 Protocol 契约测试，不实现搜索细节。
2. 冻结日志公共信封、事件目录、领域 ID、原因码和 Schema；将现有 `agent/hif/journal.py` 迁移到新契约，并先实现关键 journal 的
   原子追加、刷新、紧急备用文件、残行恢复与故障注入测试。
3. 实现 `DeckManifest`、不可变 `BattleState`、状态组装/差分/哈希/不变量和持久化 `VerifiedRunKnowledge`；补齐牌组、弃牌、除外与
   跨 Round 的观察证据。
4. 建立当前路线白名单和效果解释器，为普通得分、集中、好调、体力、抽牌、换手、除外、再演、使用次数追加、
   P 道具和 P 饮料补单元测试。
5. 实现合法动作生成、领域 Hard Gate、确定性状态转移、`PostconditionSpec` 和终局分数计算。
6. 实现分解式叶节点估值、独立 Round2 续局价值和配置化权重。
7. 实现确定性种子、随机输入带、分层采样、Sparse Expectimax、MPC、完整批次超时和状态缓存，并输出正式 `PlanningResult`。
8. 实现 `HeuristicFallbackAdapter`，将 `ProduceCardsHIF` 改为依赖 `DecisionBackend`；先接入影子模式并同时记录新旧结果。
9. 将正式规划器接入现有重新验证/动作解析/审批/执行/语义后验链；关键事件成功持久化是发送输入的前置条件。
10. 实现日志查询、Schema 校验、固定批次重放、报告、压缩、保留和跨 session 恢复工具。
11. 使用高预算离线结果校准估值权重，并在独立牌序上与当前启发式、深度 1 贪心和离线高预算基准比较。
12. 按“影子预测 → 单步实机 → 有界连续执行”逐级验证，不跨级开放权限。

建议目录边界：

```text
agent/hif/battle/state.py       # 规范化牌局状态
agent/hif/battle/effects.py     # 白名单效果与状态转移
agent/hif/battle/actions.py     # 合法动作生成与 Hard Gate
agent/hif/battle/evaluator.py   # 叶节点与续局价值
agent/hif/battle/planner.py     # 情景采样 Sparse Expectimax
agent/hif/battle/contracts.py   # 请求/结果/Protocol 与稳定枚举
agent/hif/battle/serialization.py # 规范 JSON、Schema 校验与哈希
agent/hif/battle/fallback.py    # 旧启发式降级适配器
agent/hif/adapters/battle_state.py # 观察与已验证知识的状态组装
agent/hif/observability/schema.py   # 事件 Schema 与稳定枚举
agent/hif/observability/journal.py  # 四层日志、关键写入和恢复
agent/hif/observability/replay.py   # 校验、重放与报告
tools/hif_log.py                   # 本地查询 CLI
```

## 9. 验证与上线门槛

- 每张白名单卡及其强化等级都有状态转移测试；每种特殊机制至少有一条实机黄金轨迹。
- 影子模式至少完整覆盖一轮 Round1 和一轮 Round2，所有已支持字段均无未解释预测偏差。
- 实机轨迹出现一次未解释偏差时立即停止并隔离对应效果；增加搜索预算不能替代模型修复。
- 使用未参与调权的独立牌序测试集，与现有启发式进行共同牌序、成对比较；测试持续到优胜率误差约为 ±1%。
- 模拟优胜率的保守估计必须达到 95%，`CVaR₁₀` 不低于现有启发式，平均加权总分应显著提高。
- 相对离线高预算基准，绝大多数局面的最终得分损失控制在 5% 以内。
- 所有测试中的非法动作、灰牌动作和不支持效果执行次数必须为 0。
- 接口契约测试必须覆盖请求/结果往返序列化、所有 Schema 示例、规范哈希、稳定动作键、版本不匹配、状态组装拒绝、固定情景批次、
  两层 Gate、控制器回执与语义后验的严格分离。
- 日志自动化测试必须覆盖全部事件 Schema、生命周期、追踪关系、状态快照/差异、证据引用、末尾残行、跨 session 恢复、
  保留清理、异常字符，以及磁盘满、无权限和写入中断等故障注入。
- 所有正常完成的决策必须审计关键事件零缺失；每个已发送的控制器输入都必须存在发送前已提交的 `action.intended`。
  固定输入的离线重放必须在候选顺序、评分与最终动作上零偏差。
- 审计关键写入失败测试必须证明控制器未收到输入；诊断日志失败测试必须产生 `telemetry_degraded` 告警。
- 基准测试必须统计日志开启前后的决策耗时和磁盘写入量。日志不得破坏 12 秒软、16 秒硬预算；预算不足时只能返回已完整持久化的
  安全结果或停止，不允许先点击后补日志。
- 满足模型、效果、统计、性能和实机后验全部门槛后，才允许连续模式替换当前正式策略。

## 10. 互联网依据

以下资料于 2026-07-15 查阅：

- [CEDEC 2024：学マス的 MDP、MCTS、PPO 与迁移学习实践](https://www.famitsu.com/article/202408/14977)
- [公开的学マス深度 3 滚动前瞻实现](https://github.com/katabami83/gakumas_contest_simulator)
- [公开学マス卡牌核心模拟引擎](https://github.com/kjirou/gakumas-core)
- [Berkeley CS188：Expectimax](https://inst.eecs.berkeley.edu/~cs188/textbook/games/expectimax.html)
- [Berkeley CS188：MCTS](https://inst.eecs.berkeley.edu/~cs188/textbook/games/monte-carlo.html)
- [HIF 两轮计分、Interval 与资源关系](https://seesaawiki.jp/gakumasu/d/H.I.F)
- [OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
