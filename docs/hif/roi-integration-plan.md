# HIF 已审阅 ROI 融入管线计划

## 目标与边界

将 [finals-daily-log.md](finals-daily-log.md) 中已审阅的 34 组 ROI 转化为可复用、可回放、可审计的 HIF 页面能力。目标不是把截图中的固定坐标直接变成点击脚本，而是建立下列闭环：

```text
页面锚点识别 → 页面配置匹配 → 状态/候选读取 → 纯决策 → 安全批准 → 单一动作 → 前后帧验证 → Journal
```

所有新页面默认进入 `observe_and_stop`。只有在对应页面的识别、状态、唯一目标、动作前后验证均通过后，才针对该页面开放实验性 `single_step`；连续模式继续关闭。

## 当前基线

- [ProduceHIF.json](../../assets/resource/base/pipeline/ProduceHIF.json) 已有 Round、Interval、奖励、变卡、咨询、结算、Live、Memory 的页面分支。
- [produce_hif.py](../../agent/custom/action/produce_hif.py) 已实现多处“文字唯一命中 + 前后帧验证”的受控动作。
- [hif_state_reader.py](../../agent/hif/adapters/hif_state_reader.py) 已读取本战准备页的日期、体力、P 点、属性；Round 数值校准仍为空。
- [rinami_garakuta_road_20260709.json](../../assets/data/hif/observed_cases/rinami_garakuta_road_20260709.json) 已保存部分回放案例和 UI 按钮提示。
- [finals-daily-review.md](finals-daily-review.md) 已完成 34/34 ROI 小节的视觉复核；红框证据位于 `debug/hif-daily-review-20260712/`。

## 实施状态（离线阶段）

- [x] 新增 `assets/data/hif/screen_profiles/rinami_garakuta_road_20260709.json`：记录 34 个审阅小节、23 类页面的锚点、区域、按钮和风险级别。
- [x] 新增 `screen_profiles.py`、`observation.py`：校验 ROI 边界，要求唯一锚点命中才确认页面。
- [x] `HIFStateReader` 使用页面配置读取本战准备/Interval 状态，并将页面观察结果交给调用方。
- [x] `HIFUiMap` 合并已观察案例与页面配置，Action 不再为已审阅区域维护第二份坐标。
- [x] 已把奖励确认和结果页 `次へ` 的 Pipeline 直接点击改成前后帧验证型 Custom Action。
- [x] 非 Round 验证型点击默认 `observe_and_stop`；只有显式传入 `execution_mode=single_step` 才会尝试点击。
- [x] 新增 `tools/hif_screen_profile_check.py` 与离线测试，验证 34/34 记录、按钮映射与 Pipeline 引用。
- [ ] 实机 OCR 命中率、候选唯一性和动作后置条件验证（等待环境）。

## 先解决的结构问题

当前 ROI 分散在日志、`HIFStateReader`、`observed_case` 与 Action 常量中。接入前先建立唯一机器可读来源：

```text
assets/data/hif/screen_profiles/
  rinami_garakuta_road_20260709.json  # 离线证据/候选配置
agent/hif/screen_profiles.py           # 解析、尺寸校验、页面配置查找
agent/hif/adapters/hif_screen_reader.py # OCR、候选框、数值读取
```

每个 `screen_profile` 至少应有：

```json
{
  "screen_id": "public_lesson_select",
  "frame_size": [720, 1280],
  "evidence": ["MuMu-20260709-154635-975.png"],
  "anchors": [{"kind": "ocr", "text": "H.I.F本戦まで", "roi": [32, 25, 160, 145]}],
  "regions": [{"id": "candidates", "roi": [84, 920, 552, 196]}],
  "buttons": [{"id": "rest", "text": "休む", "roi": [600, 805, 92, 98]}],
  "risk": "stateful_choice"
}
```

`evidence` 仅用于回放和审计，不作为运行时模板文件的依赖。运行时仍需基于当前帧的 OCR、模板/卡牌检测结果确认；截图中的 ROI 不可直接替代当前 MuMu 设备的 Round 执行级校准。

## ROI 到页面能力的映射

| 页面族 | 已审阅 ROI 覆盖 | 现有能力 | 接入后的首个能力 |
| --- | --- | --- | --- |
| 本战准备日程 | 前 6 日到前 1 日的候选、体力/P 点、老师建议、属性、休息 | 日程模板识别与 `ProduceChooseHIFEventAuto` | 读取全部可见候选，影子输出路线排序与拒绝原因 |
| 授业/公开课 | 三选项、预览、结算 | 好调选项和公开课结果分支 | 验证候选属性、体力代价、SP 标志；先只建议，不自动确认 |
| 差し入れ奖励 | 饮料三选一、技能卡三选一、重抽 | 预设名称查找和重抽框架 | 候选卡/饮料结构化读取，唯一目标才单步领取 |
| P 饮料满仓 | 新旧饮料列表、勾选、剩余选择、保留按钮 | 仅观察 | 读取所有可见饮料和已选数，影子计算“保留四瓶”；不自动改勾选 |
| セレクトチェンジ | 目标卡 A、牌库卡 B、滚动、确认、成功提示 | 两阶段 Action 框架 | 目标/源卡候选检测、滚动可达性与结果文本验证 |
| 相談 | 商品、价格、强化/删除、交换、结束 | 仅“结束且不购买” | 保持该安全动作；商品读取只进入影子评估 |
| Round 1/2 | 局内状态、手牌、饮料、菜单 | 影子决策 + 实验性单牌 | 单独完成实机数值 ROI 校准后再推进 |
| Interval | 商店、牌库、强化、特别指导、回复 | 状态读取 + 只允许结束 | 先读取候选和预算，输出全商店影子决策 |
| 结算/Live/Memory | 结算、Live、照片选择/确认、生成、预览 | 多数已有受控动作 | 先做影子页面识别，再逐页单步验证无资源动作 |

## 分阶段实施

### 阶段 0：配置收敛与离线回放

1. 从 34 组 ROI 标注生成 `screen_profiles` 数据，不复制原图进生产资源。
2. 扩展 `HIFScreenState`，至少新增 `FINALS_SCHEDULE`、`CLASS_OPTIONS`、`PUBLIC_LESSON_SELECT`、`DRINK_REWARD`、`SKILL_REWARD`、`SELECT_CHANGE_TARGET`、`SELECT_CHANGE_SOURCE`、`CONSULT`、`INTERVAL_*`。
3. 让 `HIFStateReader` 接收页面配置，而不是维护 `_FINALS_ROI` 常量。
4. 用 55 张已审阅截图做离线测试：每张至少验证“页面分类唯一、所有必需 ROI 在边界内、目标文字/按钮存在或明确缺失”。
5. 扩展 `observed_case`：补齐 Day 6 至 Day 1、奖励、满仓、变卡、Interval、结算和 Memory 的真实证据链；不要将单次观察伪装为概率或通用收益规律。

验收：静态检查通过；55 张回放图均得到预期页面类型或明确的 `UNKNOWN`；无任何 Pipeline 行为变化。

### 阶段 1：全页面影子模式

1. Pipeline 只用窄 OCR/模板锚点跳入对应 Custom Action；由 Custom Action 再以页面配置二次确认。
2. 新增统一 `HIFPageObservation`：页面、置信度、原始 OCR、候选、资源、截图证据、缺失字段。
3. 每次观测写 Journal，并记录策略建议、候选排序和停止原因。
4. 将目前 Pipeline 中的直接 `Click`（如奖励确认、已知 `次へ`）改为带前后帧验证的 Custom Action；在此之前不扩大其适用范围。

验收：实机只运行影子模式；每个已接页面能在 Journal 中出现“页面确认 → 状态/候选 → 决策/停止”；不能确认时只能到 `ProduceHIFUnknownStop`。

### 阶段 2：本战准备日程

按风险从低到高接入：

1. `相談` 的“保留 P 点并结束”：已有明确单一目标，先做实机单步回归。
2. 公开课/授业候选读取：读取属性、体力、SP、老师建议和当前属性；策略输出排序但不执行。
3. 授业三选项：读取每项文字、代价、`トラブル追加` 标志和预览；仅在策略明确选中、候选唯一、预览字段齐全时开放单步确认。
4. 公共课结算：读取结果数值，用于校验“预览收益”和“实际收益”分离，回写 Journal/Observed Case。

验收：连续 10 次影子样本中页面分类和候选数无错配；单步动作后需观察到预期的日数/体力/属性或页面迁移。

### 阶段 3：奖励、饮料上限与变卡

1. 奖励页引入逐卡/逐饮料候选模型：`id/name/effects/cost/once/rerollable/box/confidence`。
2. `再抽選` 作为消耗性动作：先读取剩余次数，单独 Journal 记录；目标未唯一时停止。
3. 饮料满仓先实现只读保留建议；随后实现“当前勾选状态 → 目标集合 → 最少切换 → `あと0個選択` → `残す`”的单步闭环。
4. 变卡分两次提交：目标 A 选择 + 后帧验证，源 B 选择/滚动 + `チェンジ` + 成功文案验证。两阶段之间的 Session 必须持久化目标 A、重抽数和截图证据。

验收：没有目标卡/源卡明确 OCR 或检测结果时零点击；每个成功变卡均在 Journal 中保存 A、B、确认文本与前后帧哈希。

### 阶段 4：Interval 商店

1. 先建 `IntervalObservation`：P 点、体力、牌库数量、商品、价格、可用次数、刷新代价、强化/指导候选。
2. 策略层输出“买卡 / 指导 / 饮料 / 变卡 / 回复 / 结束”的排序和预算，不直接执行。
3. 首个可执行动作保持为 `结束`；之后按“低歧义、低损耗、可验证”开放单步：牌库查看/关闭 → 特别指导候选选择 → 指导选项 → 确认。
4. 购买、刷新、回复属于资源消耗动作，必须有单独 feature flag 与实机回归样本后才能开放。

验收：每次 Interval 先完成牌库数量和 P 点读取；缺失任一关键字段时不购买、不刷新、不回复。

### 阶段 5：结算、Live 与 Memory 收尾

1. 结算只允许点击中间 `次へ`，禁止误触 `再挑戦`；核对排名页已消失才继续。
2. Live 保持观察，先针对横向画面做当前设备的单独截图契约；快进必须用识别到的唯一按钮，不复用竖屏固定坐标。
3. Memory：照片默认保持当前选择；`次へ`、`決定`、`生成`、预览 `次へ` 分页开放，每一步均验证下一页面锚点。
4. `再生成` 是带随机与资源语义的动作，先只做评分建议，默认不点。

验收：从结算到主页的每一次推进都有明确的下一页锚点；任何横竖屏契约变化均停止。

### 阶段 6：Round 独立闭环

Round 不和上述日程页面混用执行级 ROI：

1. 在当前 MuMu、当前游戏版本、当前语言下重新采集 Round 1/2 原始帧。
2. 用 `hif_roi_calibration.py` 完整校准 `good_condition`、`reprise`、`focus`、`turn`、`flow`、`deck_size`、`p_drinks`。
3. 先运行影子出牌和 Journal 审计，再只开放一张唯一目标卡的单步点击。
4. `DRAW`、`SWAP_HAND`、`USE_P_DRINK` 要各自拥有按钮定位、能力确认与结果验证后才能执行。

验收：Round 的校准证据绑定当前设备/版本/语言/截图 SHA-256；连续模式仍须单独评审。

## 数据与代码改动顺序

1. `screen_profiles` schema、加载器和离线校验测试。
2. `screens.py` 页面枚举与分类测试。
3. `hif_screen_reader.py` / `HIFPageObservation`，接入 Journal。
4. 将 Pipeline 直接点击改成验证型 Custom Action。
5. 逐页面接入影子模式，再逐页面开放单步开关。
6. 最后才修改任务 UI 中的默认执行选项；默认始终为观察模式。

## 回滚与发布约束

- 每个页面能力以独立开关控制，例如 `daily_mode`、`reward_mode`、`interval_mode`、`live_mode`、`memory_mode`、`round*_mode`。
- 任一识别置信度不足、状态缺失、候选不唯一、前后帧未变化，立即停止并写 Journal。
- 不把 `debug/` 中截图、视频或 Journal 提交为资源；仅提交配置、代码、测试与审阅文档。
- 每个阶段最少执行：`python -m pytest -q`、`python tools/hif_pipeline_check.py`、相关 Python 编译；有真实设备时再审计 `hif_journal_audit.py`。
