# HIF 模拟器实现交接

## 当前目标

根据 `docs/hif/hif-simulator-flow-design.md` 完成 HIF 模拟器实现。验收条件是：实现符合设计文档，并且能成功跑通一次 observed case replay。

当前已经完成了第一条可运行链路：

- 从结构化 observed case JSON 加载实机观测流程。
- 转换为现有 `RouteStep` / `CandidateAction`。
- 使用 `replay_hif_case` 跑通一次。
- replay 时强制选择 observed case 中记录的真实 `selected_action_id`。
- replay 后同步 observed `state_after` 到 `SimulationState`，并保存在 `snapshots["observed_state_after"]`。
- CLI 能输出 observed case 摘要、随机事件类型和识别 screen states。

## 当前工作区状态

已知未提交状态：

- `README.md`
  - 这是用户已有修改，不要回退或覆盖。
- `agent/hif/simulator.py`
  - 修改了 `replay_hif_case`、Interval HardGate、observed replay 强制选择和 observed state 同步。
- `tests/test_hif_decision.py`
  - 新增 observed case loader、schema、replay、强制选择、state sync、recognition hints、random events 测试。
- `agent/hif/observed_case.py`
  - 新增 observed case adapter。
- `assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json`
  - 新增第一条结构化 HIF observed case。
- `docs/hif/finals-daily-log.md`
  - 新增实机流程记录文档。
- `docs/hif/hif-simulator-flow-design.md`
  - 新增全流程设计文档。
- `docs/superpowers/plans/2026-07-09-hif-observed-case-replay.md`
  - 新增第一阶段实施计划。
- `handoff.md`
  - 本交接文档。

## 已完成实现

### `agent/hif/observed_case.py`

已新增：

- `ObservedCaseStep`
- `ObservedRandomEvent`
- `RecognitionHint`
- `ObservedHIFCase`
- `load_observed_hif_case`
- `validate_observed_hif_case`
- `build_initial_state_from_observed_case`
- `build_route_steps_from_observed_case`

已支持：

- 读取 JSON observed case。
- 校验：
  - `schema_version == 1`
  - `case_id` 非空
  - steps 非空
  - 每个 step 至少有一个 candidate
  - `selected_action_id` 必须存在于 candidates
  - random event 必须有 `event_type`
  - recognition hint 必须有 `screen_state`
- 将 observed case 转为现有模拟器路线。
- 将 `state_before` / `state_after` 写入 candidate 和 step metadata。

### `agent/hif/simulator.py`

已修改：

- `HardGate`
  - Interval 阶段不再只允许 `interval_budget`。
  - 现在允许：
    - `interval_budget`
    - `shop_purchase`
    - `select_change`
    - `drink`
    - `skill_upgrade`
    - `skill_customize`
    - `stamina_recover`
    - `finish_interval`

- `BeamPlanner.choose`
  - 如果 step metadata 存在 `observed_selected_action_id`，则强制选择该 action。
  - `rule_hits` 会加入 `observed_replay_forced_choice`。
  - 仍保留所有 candidate score，用于比较 planner 偏好和实机选择。

- `StateReducer`
  - 新增 `_apply_observed_state_after`。
  - 如果 candidate metadata 有 `observed_state_after`，同步已知状态字段：
    - `stamina`
    - `max_stamina`
    - `p_points`
    - `star_value`
    - `deck_size`
    - `trial_readiness`
    - `memory_quality`
    - `deck_quality`
    - `finals_readiness`
    - `interval_budget`
    - `support_event_progress`
  - 完整 observed state 存入：
    - `state.snapshots["observed_state_after"][step_id]`

- `replay_hif_case`
  - 改为读取 `ObservedHIFCase`。
  - 使用 observed initial state。
  - 输出新增：
    - `observed_case.case_id`
    - `observed_case.profile`
    - `observed_case.step_count`
    - `observed_case.random_event_types`
    - `observed_case.recognition_screen_states`
    - `observed_case.open_questions`

### `assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json`

当前是压缩版 observed case，已经能跑通一次。包含：

- Day 关键帧：
  - Vi 授業 / セレクトチェンジ
  - Da/SP 公開レッスン
  - 相談 skip
- Round1 手动打分
- Interval `シュプレヒコール+` カスタマイズ
- Round2 手动打分
- memory preview

已包含 random events：

- `day3_drink_overflow`
  - `drink_capacity = 4`
  - `free_slots_before = 1`
  - `new_drink_count = 2`
  - `selected_keep_count = 4`
  - `initial_prompt = "あと1個選択"`
  - `completion_prompt = "あと0個選択"`
- `day4_select_change`
  - `target_card = "始まりの合図"`
  - `source_card = "始まりの合図"`
  - `result = "始まりの合図 -> 始まりの合図"`

已包含 recognition hints：

- `select_change_target`
- `select_change_source_deck`
- `drink_overflow`
- `interval_shop`
- `skill_deck_view`
- `skill_customize`
- `score_settlement`
- `memory_preview`

## 已验证命令

最近一次验证均通过：

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py -q
```

结果：

```text
14 passed
```

```powershell
rtk proxy python -m pytest -q
```

结果：

```text
55 passed
```

```powershell
rtk proxy python -m py_compile agent/hif/simulator.py agent/hif/observed_case.py tools/simulate_hif.py
```

结果：exit code 0。

CLI replay 验收命令：

```powershell
rtk proxy python tools/simulate_hif.py replay_hif_case --case-file assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json --output json
```

关键输出已确认包含：

- `case_id = rinami_garakuta_road_20260709`
- `memory_preview`
- `stamina = 34`
- `p_points = 260`
- `memory_rank = "S4+"`
- `observed_replay_forced_choice`
- random event types:
  - `drink_overflow_resolution`
  - `select_change`
- recognition screen states:
  - `select_change_target`
  - `select_change_source_deck`
  - `drink_overflow`
  - `interval_shop`
  - `skill_deck_view`
  - `skill_customize`
  - `score_settlement`
  - `memory_preview`

## 下一步建议

### 1. 扩完整 observed case steps

当前 JSON 是压缩关键帧。下一步应把 `docs/hif/finals-daily-log.md` 的完整链路展开到 JSON：

- Day1：
  - 三个授業候选
  - 选项 `余裕です！`
  - `大胆不敵 -> 始まりの合図`
- Day2：
  - 三个 SP 公開レッスン
  - Da 公开 lesson 预览和结算
- Day3：
  - `差し入れ`
  - P 饮料选择
  - 技能卡奖励和重抽
  - P ドリンク所持上限
  - P item セレクトチェンジ
- Day4：
  - Vi 授業
  - `長い道のりでした`
  - `始まりの合図 -> 始まりの合図`
- Day5：
  - Da/SP 公開レッスン
  - P ドリンク所持上限
- Day6：
  - `相談`
  - 商店 skip
- Round1 / Interval / Round2 / memory：
  - 当前已有关键帧，后续可补更多候选和状态。

目标：让 JSON 从“能跑通一次”变成“完整实机 replay 数据”。

### 2. 为 observed case 增加 state diff/report

建议新增一个小工具函数：

- 输入：`ObservedHIFCase`
- 输出：
  - phase 顺序
  - step count
  - random event count
  - recognition hint count
  - 每步 `state_before -> state_after` diff
  - planner choice 与 observed choice 是否一致

可以放在 `agent/hif/observed_case.py` 或 `tools/simulate_hif.py` 的 text 输出里。

### 3. 实现 Interval 决策评分模块

设计文档中的下一个核心模块是 `IntervalDecisionPlanner`。

优先支持：

- deck count < 22 时买卡优先。
- key 卡 `カスタマイズ` 高优先。
- P 点不足时保守。
- `回復` 按体力缺口评分。
- `リフレッシュ` 作为低成本重新抽候选动作。

先不要接 OCR，只在 observed case 的结构化商店候选上评分。

### 4. 实现 drink overflow scorer

对 `drink_overflow_resolution` 事件做保留饮料评分：

- 输入：
  - 新获得饮料
  - 已持有饮料
  - `drink_capacity`
  - 当前阶段
- 输出：
  - 保留列表
  - 弃置列表
  - 评分理由

### 5. 实现 select change scorer

对 `select_change` 做两阶段评分：

- 目标卡 A：变换后获得的卡。
- 源卡 B：从牌库里被替换的卡。

重点：

- 好调路线 key 卡
- 出牌次数追加
- 抽牌
- 删除低价值/冗余卡
- 同名替换是否允许但收益待确认

### 6. memory preview scorer

对 memory preview 做再生成判断：

- `memory_rank`
- `memory_skill`
- `memory_abilities`
- `regenerate_available_count`

当前 case 里可见：

- `memory_rank = S4+`
- `memory_skill = 存在感+`
- `memory_abilities`
  - `ダンスパラメータボーナス+2.8%`
  - `初期ビジュアル上昇+15`
  - `初期Pポイント+30`

## 注意事项

- 所有 shell 命令继续加 `rtk` 前缀。
- 不要回退 `README.md`。
- 不要把当前实现描述为“完整真实 HIF 成绩预测器”。
- 当前实现是 observed replay 第一阶段，不是完整自动化。
- CLI 输出中日文在当前终端可能乱码，但 JSON 结构和 ASCII 字段可验证。
- 修改 JSON 时保持 4 空格缩进。
- 修改 Python 后至少跑：

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py -q
rtk proxy python -m py_compile agent/hif/simulator.py agent/hif/observed_case.py tools/simulate_hif.py
```

完成较大改动后跑：

```powershell
rtk proxy python -m pytest -q
```

