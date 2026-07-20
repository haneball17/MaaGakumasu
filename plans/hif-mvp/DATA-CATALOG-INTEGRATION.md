# HIF MVP 与统一数据目录 v2 接入方案

_状态：待确认的实施提案，记录于 2026-07-16。_

本文件不替代已冻结的 `PLAN.MD` 或 `plans/data-catalog-v2/PLAN.md`，也不授权新的实机输入、连续执行、发布或扩大路线。它只定义一个窄的 HIF 数据消费者迁移切片：让当前路线评分器消费可追溯、版本化的卡牌效果投影，同时保留 HIF 的状态读取、目标绑定和动作后验门禁。

## 1. 融合目标

HIF 主线负责“当前画面是否可信、哪张手牌对应哪个 UI 目标、动作后是否真的发生了领域变化”；统一数据目录负责“该卡是谁、当前强化档和效果版本是什么、证据来自哪里、是否允许被建模”。

首个切片只覆盖 `rinami_garakuta_road` 当前实证白名单。它不等待全卡池建模，也不把 `partial`、`unknown` 或仅可识别的条目送入评分器。

```text
OCR / YOLO / 同局账本
        |
        v
稳定实体 + 强化档 + UI target_id
        |
        v
HIF 受限效果投影 <--- canonical / overlay / effect_version / evidence
        |
        v
RouteBattleState -> RinamiGarakutaRouteScorer -> 排序或安全拒绝
        |
        v
独立执行审批 + 单卡领域后验 -> ProduceCardsHIF
```

评分结果始终不是点击许可。数据完整性也不能替代状态可信度、唯一目标或动作后语义后验。

## 2. 当前事实与先决阻断

| 事实                                                                              | 结论                                                                                                     |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `assets/data/catalog/` 已建立四层目录和旧 JSON 兼容派生，运行时仍通过旧接口加载。 | 可把 v2 作为权威事实源，但不能直接让 `ProduceCardsHIF` 读取 canonical。                                  |
| `agent/hif/route_scoring/catalog.py` 维护当前路线的手写 `CardSpec` 白名单。       | 与 v2 并存会造成事实与版本漂移，必须改为受限投影的消费者。                                               |
| `始まりの合図` 已进入 HIF 手写可执行模型，而 overlay 中仍为 `modeled`。           | `python tools/data_catalog.py validate --profile hif-release` 当前失败；在修复前不得接入该卡的执行路径。 |
| 通用 `agent/hif/catalog.py` 默认选择无印或第一个 tier。                           | 它不能作为强化档和效果版本的唯一绑定器。                                                                 |
| HIF 当前处于 M2 Round1 `8+2` 的单步/观察阶段。                                    | 本接入不能缩短 `8+2`、开放循环，或绕过单卡后验。                                                         |

第一个阻断项的正确修复是补足来源断言、完整 AST、可执行状态转移和测试，再通过晋升记录提升支持度。不得仅修改 `runtime_support` 字段，或让手写白名单继续领先于 canonical。

## 3. 单一职责与接口边界

| 层             | 拥有内容                                                                                            | 明确不拥有                                       |
| -------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| 数据目录       | `entity_id`、来源键、别名、强化档、`effect_version_id`、AST、证据、支持度、HIF overlay 与确定性派生 | OCR 置信度、UI 坐标、运行时账本、点击和后验      |
| HIF 效果适配器 | 将已批准 AST 严格投影为当前评分器可消费的 `CardSpec`；校验版本、强化档、支持度和哈希                | 猜测未支持 AST、修改 canonical、用显示名合并实体 |
| HIF 观测与评分 | UI `target_id`、当前状态、合法性、路线价值、拒绝原因和影子比较                                      | 将“可评分”解释为“可点击”                         |
| 执行层         | 两段式目标确认、输入审计、动作后领域断言、`UnknownStop`                                             | 从数据目录取得任何隐式执行授权                   |

运行时需要的最小投影记录为：

```text
route_id, entity_id, ja_name, ocr_aliases, tier,
effect_version_id, effect_catalog_version, runtime_support,
parse_status, resolved_effect_ast, projected_card_effect,
stamina_cost, focus_cost, lesson_once, evidence_assertion_ids
```

身份为 `(entity_id, tier, effect_version_id)`；`ja_name` 和 OCR 文本只用于受 profile 约束的匹配。`target_id` 只标识当前画面中的按钮，不能代替卡牌身份。

投影进入评分器前必须同时满足：唯一身份、目标 HIF profile 内别名无碰撞、`runtime_support=executable`、`parse_status=complete`、无影响状态转移的 `unknown` 节点、支持的 AST 操作集、与 overlay 一致的场景/路线约束，以及投影哈希和 catalog 版本一致。

## 4. 分阶段接入

### F0：收敛数据与路线模型的事实差异

1. 将 `始まりの合図` 的手写模型、canonical 效果版本和 overlay 支持度对账；补证并晋升，或撤销其可执行路线模型并安全拒绝。
2. 清理新策略路径中的模糊机器标签，特别是不得继续把体力恢复和元气都表示为 `recovery`。
3. 将 HIF 路线所需语义声明为可静态扫描的代码契约；扫描器合并路线模型、精确规则、奖励优先级和 OCR profile，生成而非手抄 `required_semantics`。
4. 通过 `validate --profile hif-release`、`derive --check`、数据目录测试和既有 HIF 路线测试。

完成条件：数据门禁为绿；新增或修改的 HIF 可执行语义都能追溯到 effect version 和证据断言。

### F1：生成受限 HIF 效果投影

1. 在 `tools/data_catalog/derive.py` 增加确定性 `hif_route_effect_catalog` 产物及其版本/哈希报告，不改变现有兼容 JSON 的语义。
2. 产物仅包含当前路线、当前 profile 和实际 required 集合中的可执行实体；其余项不因“已入库”而进入投影。
3. 在 `agent/hif/catalog.py` 增加只读的版本化投影加载接口，保持现有 `HIFCatalog` 行为不变。
4. 为缺失实体、强化档、效果版本、支持度、AST 操作或哈希分别提供稳定拒绝原因码。

完成条件：同一 canonical 输入生成字节级一致的投影；投影与旧兼容产物无未解释差异；加载失败只能安全拒绝。

### F2：影子绑定到路线评分器

1. `agent/hif/adapters/card_dict.py` 与 `route_state.py` 在影子路径中将 OCR 结果解析为唯一的 `entity_id + tier`，同时保留 UI `target_id`。
   首个切片只映射当前评分器已支持的 `base/+`；`++/+++` 或其他未映射档位必须明确拒绝，不能降级猜测。
2. `RinamiGarakutaRouteScorer` 改为依赖注入的效果目录；生产路径不再维护第二套手写 `_SPECS`，旧对象只保留为测试 golden/对照夹具。
3. 对当前已实证卡、`祝福+`、灰卡、未知卡、同名/同档冲突、成本不足和版本不匹配做逐候选比较。任何不一致都只记录并拒绝，不执行输入。

完成条件：固定夹具上的选卡、拒绝原因和分项评分与批准基线一致；未知或不完整项仍阻断整手评分；尚未改变 `ProduceCardsHIF` 的执行权限。

### F3：版本化审计与单卡后验对齐

1. 每个路线决策记录 `entity_id`、`effect_version_id`、`effect_catalog_version`、OCR/profile、`policy_version` 和投影哈希。
2. 单卡后验按该精确版本断言消耗、得分、状态、手牌和必要的活跃效果联动；静态 AST 不可替代实机后验。
3. catalog 版本、强化档或 profile 改变后，旧 Journal 只能回放，不可复用为新动作授权。

完成条件：同一观测、版本和随机种子可重放；版本不匹配、低置信 OCR、未知效果或后验不完整均在输入前停止。

### F4：并入 HIF M2 门禁

在某张卡被纳入 Round1/Round2 的严格成功样本前，除现有 HIF 门禁外还必须通过：

1. `python tools/data_catalog.py validate --profile hif-release`；
2. `python tools/data_catalog.py derive --check`；
3. 对应投影、评分和后验的定向测试；
4. 现有 HIF catalog、route scorer、route state、postcondition 和 action safety 回归；
5. 实机前后帧、Journal、控制器日志与资源审计。

F4 只让数据门禁成为 HIF 的附加前置条件。Round1/Round2 的独立 `8+2`、两段式目标确认和动作后语义验证保持不变；连续执行仍需依既有计划另行满足条件。

### F5：MVP 之后的扩展

完成 HIF MVP 后，才按数据目录计划的消费者迁移路线扩大至通用 OCR、`HIFCatalog`、route planner 和 simulator。饮料、P 道具、奖励和全局模拟不混入 F0-F4，除非它们进入已确认路线的 required 集合并重新评审范围。

## 5. 预计改动面与所有权

| 区域                                                                                                                       | F0-F4 可改内容                                                   | 禁止内容                       |
| -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------ |
| `assets/data/catalog/`、`tools/data_catalog/`、`tests/data_catalog/`                                                       | AST、overlay、派生投影、报告、校验与夹具                         | 直接手改兼容 JSON 绕过晋升记录 |
| `agent/hif/catalog.py`、`agent/hif/adapters/card_dict.py`、`agent/hif/adapters/route_state.py`、`agent/hif/route_scoring/` | 只读适配、身份绑定、影子比较、评分器依赖注入与测试               | 猜测名称或未支持效果           |
| `agent/custom/action/produce_hif.py`、`ProduceHIF.json`                                                                    | F0-F3 不改；F4 仅在既有 HIF 主线已明确授权时接收已验证决策元数据 | 用数据通过替代点击审批或后验   |

数据目录与路线评分器可以并行开发，但实机输入、Pipeline 和 `produce_hif.py` 仍由 HIF 主整合路径串行控制。

## 6. 验证矩阵

| 层   | 必测结果                                                                     |
| ---- | ---------------------------------------------------------------------------- |
| 数据 | Schema、晋升记录、required 扫描、AST 完整性、HIF release gate、确定性 derive |
| 投影 | 稳定排序/哈希、实体/别名/tier/version 唯一性、unsupported 与 unknown 拒绝    |
| 评分 | 当前观测夹具与旧 golden 一致；灰卡、未知、并列、成本不足、版本不匹配均拒绝   |
| 后验 | 每种可执行卡的正常、条件拒绝和边界状态转移；活跃效果联动不能由静态值猜测     |
| HIF  | `tests -k hif`、`tools/hif_pipeline_check.py`、编译、Ruff、格式和控制器审计  |

F0-F3 的验收只允许离线与影子模式。任何实机状态改变动作仍必须遵守 HIF MVP 的原始 `8+2`、资源和停止条件。

## 7. 回滚与变更规则

- 运行时缺少投影、哈希不符或数据门禁失败时，生产路径必须安全拒绝，不能自动回退到过期手写效果表。
- 旧 JSON 兼容产物在数据目录既有 M5 期间继续保留，便于语义差分与回滚；测试可使用注入的 golden `CardSpec`，但不得成为生产事实源。
- 任一新 HIF 可执行卡效必须在同一审查单元内同时更新：来源/证据、canonical 效果版本、overlay 支持度、投影、路线测试和后验测试。
- 不允许通过提升标签、修改报告或跳过 `hif-release` 校验来临时解除阻断。

## 8. 后续决策点

本提案本身不启动 F0-F4。开始实现前需要确认：

1. 以 F0 为最近工作项，先修复当前 `始まりの合図` 的数据门禁失败；
2. F1-F3 仅以离线/影子模式接入，不新增实机执行权限；
3. F4 作为 HIF M2 的附加门禁，而不是替代既有 `8+2` 验收；
4. 获批后同步更新已冻结的 HIF `PLAN.MD`、`DECISIONS.md` 与数据目录计划的 M6 边界。
