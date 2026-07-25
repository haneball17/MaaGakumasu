# HIF 自动化测试说明

本文描述当前 `rinami_garakuta_road` HIF 路线的离线测试边界。HIF 仍处于开发与验证阶段，测试通过不代表已经完成完整连续培育或新的实机闭环。

## 实机验证授权

除非用户在当前任务明确要求，代理不得连接设备、启动 `tools/hif_live_runner.py`、提交 Maa Pipeline 任务或发送控制器输入；零输入观察同样属于实机管线验证。离线 JSON、截图、ROI、单元测试和静态契约检查不受此限制。

一次明确授权只覆盖用户指定的任务与输入范围，不能外推为后续页面、额外点击或连续运行的授权。`TEST_HIF_2.json` 的单步节点供用户手动验证时使用，代理默认不运行。

## 覆盖矩阵

`assets/data/hif/pipeline_coverage.json` 是当前 HIF Pipeline 的机器可检查覆盖矩阵。它要求 `ProduceHIF.json` 的每个节点恰好登记一次，并为每组节点声明：

- 节点类别与实机证据等级；
- 成功、拒绝/安全停止、动作后验失败三类场景，或不适用理由；
- 终止策略与对应测试模块。

`python tools/hif_pipeline_check.py` 会同时检查节点/Custom 注册、跳转引用、覆盖矩阵、OCR 正则、ROI 边界和 TemplateMatch 文件引用。新增或删除 HIF 节点后，必须同步更新矩阵，否则检查失败。

## 真实帧夹具

`tests/fixtures/hif/frames/` 只保存经过审阅的最小帧集：常规 HIF 页面为竖屏 `720x1280`；唯一横屏例外是 `Round2` 结束后播放的 Live 视频，尺寸为 `1280x720`，且必须使用独立页面契约。每项的来源、采集日期、SHA-256、页面、ROI 和适配器预期均记录在覆盖矩阵的 `fixtures` 中；测试会拒绝内容被替换但清单未更新的夹具。

这些帧含游戏内偶像、卡片、饮料和本局数值等状态数据，但不含账号标识或凭据；仅用于离线尺寸、ROI 和 OCR 适配器文本回放。它们不执行 Maa OCR，也不连接控制器，因此不得表述为 OCR 或点击的端到端实机验证。

禁止将 `debug/`、Journal、日志、视频、压缩包或损坏截图作为测试夹具提交。

## 安全后验

需要点击的 HIF Action 不得只凭“帧发生变化”判定成功。当前测试覆盖以下安全约束：

- 空白推进、日程首次选择、公开课结算、饮料展示和开始培育必须命中已知下一页或已注册的过渡识别；日程首击仅进入选中态时立即停止，确认必须另起任务；未知帧立即进入 `ProduceHIFUnknownStop`。
- 饮料满仓恢复必须带显式 `single_step` 权限。
- 变卡源卡确认必须持有同一运行期记录的目标卡；不能从 Action 参数重建丢失状态。
- 奖励页 Custom Recognition 的 `box` 与 `detail` 在命中、无框命中和未命中时均有离线契约测试。
- Round 单步出牌尚无“手牌/回合/数值确实更新”的实机后验，因此审批器固定声明 `postcondition_supported=false`，即使 ROI 与候选完整也不得点击。
- `--round1-state-observe` 必须隔离根路由；它只允许 `Round1Flag → Round1Action → Stop`，以免正式根路由的通用 `Click_1` 进入观察任务。实机 Maa 日志必须没有 `MaaControllerPostClickV2` / `MaaControllerPostSwipeV2` 记录。
- 已采证回合数字可使用高置信模板兜底；其余 Round 数值要求三次采样中至少两次解析为同一数值，三种不同读数或无法解析时必须写入 `missing_fields`，禁止出牌。
- 即使状态完整，`CardAction.target_card` 为空的泛化策略动作也必须以 `card_decision_target_not_explicit` 安全停止；不得从多个同类非灰手牌中猜选。
- Live 是 `Round2` 结束后唯一允许的横屏页面；快进尚无目标页后验，`skip_once` 只记录并安全停止；不得把动画帧变化当作快进成功。
- 回忆照片、生成、预览和结算按钮必须依次命中声明的下一页面；变化后的未知帧进入 `ProduceHIFUnknownStop`。

未获得实机证据的页面、其他路线、Round 自动出牌和连续模式保持安全停止。

## Day3 日程观察

`assets/resource/base/pipeline/test/TEST_HIF_2.json` 的 `test_hif_day3_entry` 仅接受“`H.I.F本戦まで` + `4日`”页面，调用 `ProduceChooseHIFEventAuto` 的 `observe` 模式记录 `おでかけ / 差し入れ` 候选和决策后停止；不会发送点击。

同一文件的 `test_hif_day1_entry`、`test_hif_day4_entry` 至 `test_hif_day6_entry`、`test_hif_ranking_entry` 与 `test_hif_round1_entry` 是零输入检查点：分别只验证 `6/3/2/1日`、排名页和 Round1 锚点后停止。`test_hif_round1_entry` 会记录 Round1 状态后停止；不会出牌。`test_hif_class_options_observe`、`test_hif_public_lesson_result_observe`、`test_hif_gift_bags_observe`、`test_hif_gift_reward_result_observe`、`test_hif_drink_reward_observe`、`test_hif_skill_reward_observe`、`test_hif_drink_overflow_observe`、`test_hif_select_change_target_observe`、`test_hif_select_change_source_observe` 与 `test_hif_consult_observe` 分别探测已知子页后停止。它们不把未采证日程、领奖、变卡、咨询购买或排名推进动作伪装成闭环。

`test_hif_day1_select_entry` 是 Day1 红色 `Vo` 课程的用户手动单步入口：必须同时命中 HIF 标题与 `6日`，并完整、唯一识别 `Vo / Da / Vi` 三个候选后才允许一次首次选择；选中态、未知后态或任一候选缺失均停止。该节点受上方的实机验证授权规则约束。

`test_hif_day3_entry` 使用 Python Custom Action，须通过下列运行器启动以加载 `agent` 注册；MaaPipelineEditor 未加载 Agent 时会在 Custom action 阶段失败，不是 Day3 OCR 未命中。

```powershell
python tools/hif_live_runner.py --adb <地址> --adb-path "<MuMu adb.exe>" --task test_hif_day3_entry --seconds 30 --run-id hif-day3-observe
```

2026-07-19 已在 MuMu 12 的 `AdbController` 截图通道复测：运行 `hif-day3-observe-20260719` 成功，帧为 `720×1280`，读取到 `おでかけ / 差し入れ`；默认路线决策为 `おでかけ`，随后因 observe 模式以 `page_execution_mode_not_single_step` 安全停止。该运行不发送日程点击；原始帧与 Journal 仅保留在 `debug/`。

`test_hif_day3_gift_select_entry` 是已授权的单步入口：仅在同一 `4日` 锚点且安全预设唯一选择 `差し入れ` 时发送一次首次选择点击，确认选中态后停止。它不确认日程；确认必须使用新的、具备后态校验的独立测试任务。

`test_hif_day3_gift_confirm_entry` 是该选中态的独立确认任务：它额外要求右侧窄 ROI 的 `SELECT`，再发送一次确认点击。动作后只接受已注册的 HIF 过渡页；未命中时安全停止并保留前后帧。

`test_hif_gift_bags_advance_entry` 仅在礼袋模板命中时调用已有的 `ProduceHIFSafeAdvanceAuto`，以单步模式点击一次已校准空白区。它不重试、不循环，后态未知时停止。

`test_hif_gift_reward_result_advance_entry` 同样只在 `Pドリンク獲得 / スキルカード獲得` 展示层命中时单步推进一次；它不选择奖励。

`test_hif_drink_reward_preview_left`、`_center`、`_right` 各自只选中一个饮料槽位，并要求回到已知的饮料详情态后停止；三者均不点击 `受け取る`。

`test_hif_drink_reward_receive_black_vinegar_entry` 是当前样本的窄领取路径：只有已选中 `初星黒酢` 且 `受け取る` 同时命中时，才点击一次领取；后态必须命中饮料展示页。候选变动、名称不符或展示页未命中均停止。

`test_hif_drink_reward_reveal_wait_entry` 只等待已验证的饮料展示动画结束；它不点击瞬态展示层。

`test_hif_drink_reward_reveal_wait_10s` 仅用于复测当前展示动画的稳定时长；它设置 10 秒等待但不发送输入，不能作为其他页面的通用延迟模式。

若展示层在独立等待任务后仍存在，`test_hif_drink_reward_reveal_confirm_entry` 只允许在该层已识别时点击一次 `受け取る`，并要求后态为技能卡奖励页；这条路径用于验证“需确认而非自动结束”的假设。

2026-07-19 的 `初星黒酢` 领取展示层在两次零输入等待及一次 10 秒等待后仍存在；随后一次 `受け取る` 位置点击也未改变页面。该假设未获证实，当前测试以该帧安全停止，不再尝试其他坐标。后续需从标准截图通道采集唯一有效的确认交互与已知后态，才能扩展正式动作。

## Day1 牌库往返

`TestHIFDay1ChangeDeckEntry` 仅从 Day1 场景3启动。它先确认场景3锚点和牌库入口，再在显式 `single_step` 下打开一次 `所持スキルカード`，采证后点击一次 `閉じる`；只有重新命中场景3锚点才成功结束。任一中间页、关闭按钮或返回锚点不成立时进入 `unknownstop`，不得选卡、换卡或继续日程。

返回锚点必须同时命中场景3模板和牌库入口模板；仅命中场景3模板（例如换卡候选页的误匹配）不视为已恢复。

2026-07-24 已以 MuMu 12 / `127.0.0.1:16416` 实测 `hif-day1-change-deck-roundtrip-20260724-retry`：三帧依次为 Day1 场景3、`所持スキルカード`、原 Day1 场景3。Journal `20260724T214908-2276.jsonl` 记录 `open_skill_deck` 与 `close_skill_deck` 均为 `verified`。原始帧仅保留在 `debug/hif-journal/`。

早期 `hif-day1-change-deck-read-visible-v2-20260724` 以 `cards.onnx` 只枚举出当前视口的 15 张，低于标签总数 `17`；该检测模型漏掉了第二行第四列，不能再作为枚举依据。

2026-07-24 的 IPC 实机回归 `hif-day1-change-deck-full-17-20260724-final` 读取标签 `スキルカード(17)`，按固定 4×4 槽位读取首屏 16 张，验证一次网格内上滑后读取第 17 张，并关闭返回 Day1 场景3。Journal `20260724T230815-24560.jsonl` 记录 `open_skill_deck`、`scroll_skill_deck`、`close_skill_deck` 均为 `verified`，`read_visible_skill_card` 的逻辑序号完整覆盖 `1..17`。原始帧仅保留在 `debug/`。

VS Code 插件测试：以 `hif_test/` 作为工作区打开，执行 `Maa: 执行任务` 并选择 `HIF Day1 牌库完整读取（单步）`。该入口内置 `single_step`，完成后 Agent 日志输出 JSON 汇总（`expected_total`、`read_count`、`cards`、`returned_to`）；同一汇总也写入 Journal 的 `close_skill_deck.details`。只在 Day1 场景3执行；入口或返回锚点不成立时安全停止。

### 实现经验与边界

- `cards.onnx` 只可辅助识别，不能决定牌库枚举数量；本页以总数标签、固定 `4×4` 槽位和逻辑序号为准，同名卡不得去重。
- 当前已校准范围是 `1..20` 张：首屏最多 16 张，超过 16 张只允许一次网格内上滑；滑动后必须同时确认牌库标题、网格指纹与总数不变。超过范围或任一后验失败时关闭并安全停止，不能猜测分页。
- Maa 任务“完成”不等于动作闭环成功。验收必须同时检查 Agent 汇总的 `read_count == expected_total`、Journal 的 `open_skill_deck / scroll_skill_deck / close_skill_deck` 结果，以及 `after` 帧已回到 Day1 场景3。
- `hif_test/interface.json` 的 `agent.child_args` 只保留 Python 参数和 `agent/main.py`；Maa VS Code 插件会自行追加 Agent UUID。手工加入 UUID 占位符会导致 Agent IPC 连接超时。

## Day1 换卡配对选择

`HIF Day1 换卡配对选择（单步）` 是隔离的 VS Code 测试任务。仅从 Day1 换卡候选页、且未选中候选卡时启动；它不属于正式 `Produce` 路由。

动作固定只发送三次单步点击：候选卡、`次へ`、牌库源卡。候选位按从左到右、源牌按已确认占用的逻辑槽位升序决定；并列会写入 `tie_break_fallback`。动作不重抽、不滚动、不恢复中间状态，也绝不点击 `チェンジ`。

成功时，Agent 日志与 Journal 的 `select_change_pair_ready` 包含候选卡与源卡标题、槽位、`controller_click_sequence: [candidate, next, source]`、`change_visible: true` 和 `change_click_count: 0`。测试任务随后只识别确认页的 `チェンジ` 锚点并结束；任一页面、OCR、源槽位或确认锚点不成立时进入 `unknownstop` 并停在原地。

使用方式：以 `hif_test/` 打开 VS Code 测试工作区，先手动到达 Day1 换卡候选页，再在 `Maa: 执行任务` 中选择该任务。运行前确保没有候选卡已被选中；该任务不会提交换卡，若需要继续游戏请由人工决定是否点击 `チェンジ` 或返回。

## 页面能力升级门槛

页面与动作分别升级：同一页面的“结束”通过单步验证，不代表购买、刷新或其他资源消耗动作也获得授权。截图方向须符合 [`resources.md`](resources.md) 的契约；`Round2` 后 Live 是唯一横屏例外，仍从观察级开始。

| 级别             | 最少证据                                                         | 运行时允许行为                                 | 升级或回退条件                                                          |
| ---------------- | ---------------------------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------- |
| `unverified`     | 没有经审阅的帧，或页面/状态不能唯一确认。                        | `ProduceHIFUnknownStop`，不发送输入。          | 补原始帧、页面锚点和必需状态读取后，才可进入离线回放。                  |
| `offline_replay` | 经审阅的最小帧、唯一页面锚点、ROI 边界和覆盖矩阵检查。           | 离线分类、字段读取和契约测试；不连接控制器。   | 在真实设备上确认页面与字段，写入 Journal 后才能进入影子观测。           |
| `shadow`         | 当前设备的页面确认、关键状态/候选读取和 Journal 记录。           | 只读策略排序与停止原因；不发送输入。           | 用户明确授权且目标唯一、前置状态完整、后态锚点已知时，才可申请单步。    |
| `single_step`    | 当前截图契约、唯一目标、显式执行模式、动作前后证据和可识别后态。 | 仅发送一次已批准输入，并立刻重新读取关键字段。 | 任一缺字段、目标歧义、后态未知/未变化或截图失败，立即停止，不重试点击。 |
| `continuous`     | 所有相关动作已有重复实机回归、异常出口和回滚证据，并经单独评审。 | 当前 HIF 未开放。                              | 缺少任何一项时退回 `shadow` 或 `single_step`，不以单页成功外推。        |

每次降级都应保留 Journal、前后帧和停止原因；不得用固定延迟、复点或坐标猜测跨过升级门槛。

## 本地检查

```powershell
python -m pytest -q tests -k hif
python tools/hif_pipeline_check.py
python -m py_compile agent/hif/*.py agent/hif/adapters/*.py agent/custom/action/produce_hif.py tools/hif_*.py
python -m ruff check agent/custom/action/produce_hif.py agent/hif tests/test_hif_*.py tools/hif_pipeline_check.py
npx prettier --check "assets/data/hif/pipeline_coverage.json"
```

全仓验证仍应在交付前执行 `python -m pytest`。若存在与 HIF 无关的既有失败，必须保留输出证据，不要借机扩大修复范围。
