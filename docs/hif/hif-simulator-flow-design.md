# HIF 模拟器全流程设计

本文档设计 HIF 离线模拟器从“样例沙盘”升级到“可复现实机流程的真实度优先模拟器”的整体路线。目标不是一步到位预测最高分，而是先让模拟器能读取一条真实观测 case，稳定复现流程、状态变化、随机事件和关键决策点，再逐步加入概率池和策略评分。

## 参考资料

### 本仓库实机资料

- `docs/hif/finals-daily-log.md`
  - 记录了本战前 6 日到 1 日、Round1 初始、Interval、结算与回忆卡生成。
  - 包含截图来源、时间线、ROI/OCR 初版、建模含义和待补证据。
- `agent/hif/simulator.py`
  - 当前已有 `CandidateAction`、`RouteStep`、`SimulationState`、`RewardScorer`、`BeamPlanner`、`StateReducer` 等基础结构。
  - 当前 `build_sample_hif_case` 仍是样例路线，不是从真实观测 case 加载。
- `tests/test_hif_decision.py`
  - 当前覆盖默认 profile、路线快照、低体力避险、奖励排序、评估报告字段。

### 外部资料

- Game8 HIF 攻略：`https://game8.jp/gakuen-idolmaster/783836`
  - HIF 本战重点包括强力 memory、22 枚目标、参数调整、Round1/Round2 合计、Interval 最后调整。
- 学マス wiki H.I.F：`https://seesaawiki.jp/gakumasu/d/H.I.F`
  - 可作为 HIF bonus、P ドリンク所持上限、セレクトチェンジ等规则名和候选来源参考。
- Game8 メモリー厳選：`https://game8.jp/gakuen-idolmaster/613860`
  - 说明 memory 携带技能与再生成的基本价值。
- Yahoo 知恵袋 P ドリンク上限问答：`https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q13328406913`
  - 作为“4 瓶上限可能与亲爱度/模式条件相关”的弱证据，仍以实机截图为准。
- morishimemo HIF 攻略笔记：
  - `https://morishimemo.com/gakumasu-memo-38`
  - `https://morishimemo.com/gakumasu-memo-39`
  - 可作为集中/好调关键卡、カスタマイズ价值和 deck 构筑策略参考。
- note HIF 攻略资料：
  - `https://note.com/mk_vignette1010/n/n7f2604ce4f03`
  - `https://note.com/nuo195/n/n61045e81865e`
  - 可作为 P item 触发饮料/セレクトチェンジ、使用数追加、抽牌和 key 卡优先级的参考。

外部资料只用于补全规则假设和策略启发；真实流程、ROI/OCR 和数值变化以本仓库实机截图记录为最高优先级。

## 总体目标

1. 支持读取结构化真实观测 case，而不是只使用 `build_sample_hif_case`。
2. 支持 replay：按真实选择复现 Day1-Day6、Round1、Interval、Round2、结算、回忆卡生成。
3. 支持决策替换：在真实候选池上让 planner 替代部分人工选择。
4. 支持随机模拟：P item、饮料、技能卡奖励、回忆卡生成等可多次采样。
5. 支持 ROI/OCR 管线接入：每个流程节点都有可识别 screen state、按钮和下一步动作。

## 设计原则

- 真实观测优先：先复现一条可靠实机流程，再泛化多角色、多路线。
- 结构化优先：所有候选、收益、成本、ROI、随机事件都进入 JSON/YAML case。
- 可回放优先：replay 结果必须能解释体力、P 点、属性、牌库、饮料、技能变化。
- 决策模块独立：路线选择、Interval 商店、局内出牌、回忆再生成分别评分，避免一个巨型 scorer。
- 不把玩家经验硬编码为绝对规则：例如“买卡 > key 牌指导 > 饮料 > 变卡 > 其他强化”先作为启发权重，最终由评分模块结合上下文决策。

## 流程状态机

```text
selection_memory_seed
  -> finals_prepare_day_6
  -> finals_prepare_day_5
  -> finals_prepare_day_4
  -> finals_prepare_day_3
  -> finals_prepare_day_2
  -> finals_prepare_day_1
  -> round1
  -> interval
  -> round2
  -> score_settlement
  -> live_skip
  -> memory_photo_select
  -> memory_photo_confirm
  -> memory_generate
  -> memory_preview
  -> finish
```

当前实机记录已经覆盖：

- Day1：授業、好调选项、セレクトチェンジ。
- Day2：Da/SP 公開レッスン，属性加成结算。
- Day3：差し入れ、饮料、技能卡、P ドリンク所持上限、P item セレクトチェンジ。
- Day4：Vi 授業、好调选项、同名セレクトチェンジ。
- Day5：Da/SP 公開レッスン、P ドリンク所持上限。
- Day6：相談商店，跳过购买，保留 P 点。
- Round1：初始局内状态。
- Interval：商店、牌库检查、强化、カスタマイズ、回复、刷新。
- End：结算、重试、Live、memory 生成、memory 预览。

## 结构化 case schema

建议新增文件：

```text
assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json
```

顶层结构：

```json
{
    "schema_version": 1,
    "case_id": "rinami_garakuta_road_20260709",
    "profile": {
        "idol_name_jp": "姫崎 莉波",
        "song": "ガラクタロード",
        "route_plan": "好調",
        "source_doc": "docs/hif/finals-daily-log.md"
    },
    "initial_state": {},
    "steps": [],
    "observed_random_events": [],
    "recognition_hints": [],
    "open_questions": []
}
```

### `ObservedStep`

每个节点对应一次界面/行动：

```json
{
    "step_id": "finals_day3_gift",
    "phase": "finals_prepare",
    "day_remaining": 4,
    "screen_state": "finals_action_select",
    "selected_action_id": "gift",
    "state_before": {},
    "state_after": {},
    "candidates": [],
    "events": [],
    "recognition": {},
    "evidence": []
}
```

关键字段：

- `phase`
  - `finals_prepare`
  - `round1`
  - `interval`
  - `round2`
  - `score_settlement`
  - `memory_generation`
- `state_before/state_after`
  - `stamina`
  - `max_stamina`
  - `p_points`
  - `attributes`
  - `attribute_bonus`
  - `deck_count`
  - `drink_count`
  - `skill_cards`
  - `p_drinks`
  - `score`
- `evidence`
  - 截图路径
  - 用户说明
  - OCR 文案
  - 手动推断说明

### `ObservedCandidate`

候选行动：

```json
{
    "candidate_id": "day5_public_lesson_da_sp",
    "name": "Da.公開レッスン",
    "category": "public_lesson",
    "attribute": "Da",
    "is_sp": true,
    "cost": {"stamina": 8, "p_points": 0},
    "preview_delta": {},
    "result_delta": {"Da": 287, "Vi": 114, "p_points": 50},
    "tags": ["sp", "main_attribute", "cap_safe"],
    "roi": {}
}
```

### `ObservedEvent`

随机/派生事件：

```json
{
    "event_id": "day3_drink_overflow",
    "event_type": "drink_overflow_resolution",
    "trigger": "p_item_drink_reward",
    "before": {"drink_count": 3, "free_slots": 1},
    "reward": {"new_drinks": 2},
    "resolution": {
        "drink_capacity": 4,
        "selected_keep_count": 4,
        "prompt_done": "あと0個選択"
    }
}
```

事件类型先支持：

- `select_change`
- `drink_overflow_resolution`
- `drink_reward`
- `skill_reward`
- `shop_refresh`
- `skill_upgrade`
- `skill_customize`
- `stamina_recover`
- `memory_regenerate`

### `RecognitionHint`

每个 screen state 的识别线索：

```json
{
    "screen_state": "interval_shop",
    "title_ocr": "インターバル",
    "primary_text_ocr": "Pポイントで利用するものを選んでください",
    "buttons": [
        {"id": "refresh", "text": "リフレッシュ", "roi": [19, 1048, 180, 47]},
        {"id": "finish", "text": "終了", "roi": [565, 1045, 155, 84]}
    ],
    "regions": []
}
```

ROI 坐标全部以 `720x1280` 为基准，实机接入前必须校准。

## 与现有模拟器的映射

当前结构可以保留，但需要新增 observed case 适配层。

### 新增 loader

建议新增：

```text
agent/hif/observed_case.py
```

职责：

- 读取 `assets/data/hif/observed_cases/*.json`
- 验证 schema
- 转换为现有 `RouteStep` / `CandidateAction`
- 保留 richer metadata 给 report 和后续 OCR 管线使用

核心 API：

```python
def load_observed_hif_case(path: str | Path) -> ObservedHIFCase: ...
def build_route_steps_from_observed_case(case: ObservedHIFCase) -> list[RouteStep]: ...
def build_initial_state_from_observed_case(case: ObservedHIFCase) -> SimulationState: ...
```

### 扩展 `SimulationState`

现有状态偏抽象，需要逐步增加真实字段：

- `attributes: {"Vo": int, "Da": int, "Vi": int}`
- `attribute_bonus: {"Vo": float, "Da": float, "Vi": float}`
- `drink_capacity`
- `p_drinks`
- `skill_cards`
- `memory_card`
- `round_scores`
- `retry_count`

短期可以先放进 `snapshots` / `metadata`，避免一次性重构太大。

### 扩展 `CandidateAction`

新增 metadata 约定：

- `screen_state`
- `attribute`
- `is_sp`
- `preview_delta`
- `result_delta`
- `roi`
- `evidence`
- `random_event_type`
- `shop_item_type`
- `decision_policy_hint`

先不急着改 dataclass 字段，避免破坏当前测试。

## 决策模块拆分

### 1. 本战准备日决策

负责 Day1-Day6：

- 授業
- 公開レッスン
- 差し入れ
- 相談
- P item 触发事件
- セレクトチェンジ
- 饮料上限取舍

主要评分因素：

- 主属性/得意属性
- SP 标志
- 是否超过 `3200` 上限
- 体力安全
- P 点需求
- 好调/集中/key 卡路线
- 牌库质量和牌库数量

### 2. セレクトチェンジ决策

分两阶段：

1. 选择目标卡 A，也就是变换后获得的卡。
2. 从牌库选择源卡 B，也就是被替换的卡。

评分：

- A 的路线价值
- B 的保留价值
- 是否同名
- 是否删除低价值/トラブル/冗余卡
- 是否提升循环稳定性

### 3. 饮料上限决策

输入：

- 新获得饮料列表
- 已持有饮料列表
- 上限容量
- Round1/Round2/Interval 阶段

输出：

- 保留哪些饮料
- 丢弃哪些饮料

评分：

- 参数爆发
- 抽牌
- 使用次数追加
- 体力成本
- 当前阶段是否来得及用
- 与 key 卡/最终回合组合的配合

### 4. Interval 决策

Interval 是复合决策点，建议单独模块：

```text
IntervalDecisionPlanner
```

决策顺序不是硬编码，而是约束求解：

1. 先读取 deck count。
2. 若 deck count < 22，买卡优先级上升。
3. 若 deck count >= 22，普通买卡惩罚，key 卡例外。
4. 评估カスタマイズ。
5. 评估饮料。
6. 评估セレクトチェンジ。
7. 评估强化。
8. 评估回复。
9. 评估刷新。
10. 决定是否 `終了`。

玩家经验优先级可作为初始权重：

```text
buy_card > key_card_customize > drink > select_change > other_enhance
```

但最终要结合 P 点、候选质量、Round2 需求和 deck count。

### 5. 局内出牌决策

Round1/Round2 出牌模拟目前应保持与 `agent/hif/decisions/play.py` 分离，但设计上需要桥接：

- 路线模拟器提供：
  - 初始牌库
  - 初始饮料
  - 初始状态
  - Round 属性
  - 对手分数
- 局内模块返回：
  - Round1 分数
  - Round2 分数
  - 体力消耗
  - 饮料使用
  - 是否建议 retry

### 6. 回忆卡再生成决策

输入：

- 评级
- 携带技能
- HIF 专用能力
- 词条列表
- 可再生成次数

评分：

- 是否携带 key skill
- 是否有 `スキルカード使用数追加+1`
- 参数 bonus 是否命中主属性
- 初始 P 点、初始属性、初始饮料等词条价值
- 本次 memory 是否用于 HIF 下一轮，还是通用继承

## OCR/模板管线设计

每个 screen state 需要三个层级：

1. 页面识别
   - 标题 OCR
   - 固定图标模板
   - 主提示文案
2. 候选提取
   - 候选卡/饮料/按钮 ROI
   - OCR 名称和价格
   - 图像模板或卡牌识别
3. 行动执行
   - 点击候选
   - 点击确认
   - 处理空白点击推进
   - 滚动列表

优先落地 screen states：

1. `finals_action_select`
2. `select_change_target`
3. `select_change_source_deck`
4. `drink_overflow`
5. `interval_shop`
6. `skill_deck_view`
7. `skill_customize`
8. `score_settlement`
9. `memory_preview`

## 测试计划

### 阶段 1：schema 和 replay

- 新增 observed case fixture。
- 测试 loader 能读取 case。
- 测试转换后的 `RouteStep` 数量和 phase 顺序。
- 测试 replay 后关键状态符合观测：
  - Day4 Vi `1881 -> 2061`
  - Day5 Da `2633 -> 2920`
  - Day6 P 点 `380`
  - Interval P 点 `580`
  - 特别指导后 P 点 `260`

### 阶段 2：局部决策替换

- Day5 公开 lesson：确认 planner 会选 Da/SP 且不超过 `3200`。
- Day6 相談：确认 planner 可以选择 `finish_without_purchase`。
- Interval：deck count 为 20 时买卡优先级高于普通强化。
- 饮料上限：`あと0個選択` 前不可提交，完成后可提交。

### 阶段 3：随机模拟

- P item 饮料奖励采样。
- セレクトチェンジ候选采样。
- 回忆卡再生成采样。
- 输出期望分、方差和 top 决策理由。

### 阶段 4：OCR/模板接入

- 先用截图做离线识别单测。
- 再接 MuMu 实机。
- 每个 screen state 至少有：
  - 成功识别样本
  - 失败/未知 fallback
  - ROI 校准记录

## 落地顺序

1. 创建 observed case schema 和一条 JSON case。
2. 写 loader，把 JSON 转成 `RouteStep` 和初始 state。
3. 给 `simulate_hif_route` 增加从 observed case 运行的 CLI。
4. 为 replay 添加单测。
5. 拆出 Interval 决策评分。
6. 拆出饮料上限评分。
7. 拆出セレクトチェンジ评分。
8. 设计 memory preview / regenerate 评分。
9. 最后接 OCR/模板 screen state。

## 当前不做的事

- 不直接改 `agent/hif/decisions/play.py` 的局内出牌逻辑。
- 不直接做实机点击自动化。
- 不立刻泛化多角色。
- 不把攻略站策略硬编码为绝对规则。
- 不把 ROI 初版当成最终坐标。

## 开放问题

- Round2 初始状态和完整局内过程还缺截图。
- P item 各触发事件的概率、候选池和条件还未结构化。
- Interval 中 P 点 `580 -> 260` 的完整消费流水还需要补证据。
- セレクトチェンジ同名卡变更是否有隐藏收益仍未确认。
- 回忆卡再生成评分需要更多样本。
- 饮料上限 4 瓶是否对所有用户/阶段稳定，仍需更多证据。

