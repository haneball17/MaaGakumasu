# HIF 实测任务交接（2026-07-13）

本文用于在新对话中恢复 HIF 实机验证。以当前工作区和当前模拟器画面为准；不要根据旧会话记录回退文件或猜测游戏状态。

## 2026-07-14：离线测试与安全后验补充

- 新增 `assets/data/hif/pipeline_coverage.json`：覆盖当前 `ProduceHIF.json` 的全部 54 个节点，并由 `python tools/hif_pipeline_check.py` 校验节点集合、场景声明、OCR 正则、ROI 与模板文件。
- 新增 9 个最小真实帧夹具到 `tests/fixtures/hif/frames/`；来源和限制见 `docs/hif/testing.md`。它们只用于离线尺寸、ROI 和 OCR 适配器回放，不代表新的实机点击或 OCR 端到端验证。
- 空白推进、日程一/二次确认、饮料展示等待、公开课结算和开始培育的后验均已收紧：帧变化但未命中已知页面/已注册过渡节点时必须安全停止。
- 变卡源卡确认不能再用 Action 参数重建丢失的目标卡状态；饮料满仓恢复也必须显式使用 `single_step`。
- 本轮未连接或点击模拟器；尚未采证页面、其他路线和 Round 自动出牌继续保留安全停止。

## 本次续跑证据（2026-07-13 18:12）

- 当前模拟器停在 Day6 的 Vo `授業`三选页，未提交任何授业选项。当前可见选项为：
  `飲食物のチェック`、`基礎の確認`、`声の細かいチェック`；第三项带 `トラブル追加`。
- `hif-schedule-anchor-observe-07`：只读正式路由暴露旧 `Vo/Da/Vi` 模板在原始 `720x1280` 帧上的最高相似度仅 `0.495`，不能作为日程入口依据，未发生点击。
- 已把本战页标题改为独立的 `H.I.F本戦まで` 与 `[1-6]日` OCR 锚点，并改用日程文字 OCR + 三张 `授業`卡的粉/蓝/黄角标识别 `Vo/Da/Vi`。`hif-schedule-ocr-observe-08` 在观测模式唯一读取到三项候选，未点击。
- `hif-day6-lesson-two-stage-09`：正式单步管线按 Day6 预设选择 `Vo`。Journal
  `debug/hif-journal/20260713T180528-38020.jsonl` 记录了首次选中态与第二次确认态的前后帧，随后进入上述授业选项页。
  该次旧路由因未知交互页被空白推进误接管；空白点 `[341,204]` 共点击 4 次，均未提交授业选项，但人物动画导致全帧指纹变化，运行器超时。不要把这 4 次记录作为有效页面推进。
- 已修复该保护：`授業`标题现在优先路由到授业选项观察节点，且空白推进在发现任一已知交互页面时直接拒绝。
  `hif-day6-unknown-class-stop-10` 在默认观测模式下只记录当前三项并以
  `good_condition_option_not_found` 停止；Journal 为
  `debug/hif-journal/20260713T181235-42876.jsonl`，审计结果 `ok=true`、无执行点击。
- `docs/0711.md` 与 `finals-daily-log.md` 已有同类实测：顶部选项 `飲食物のチェック` 的**预览**与旧文案
  `余裕です！`一致，显示 `体力 -5`、`ボーカル上昇+180`、
  `トラブルカード以外のスキルカードを選択して異なる好調関係のスキルカードにセレクトチェンジ`。
  这可以支持未来“先预览、命中全部效果锚点后才二次确认”的独立实现，但当前单步授权尚未包含该确认动作。

### 后续前置条件

在获得将“授业预览验证后二次确认”加入单步实验授权的明确指示前，不得选择上述任一授业选项、不得触碰 `セレクトチェンジ`、Round 或技能卡。可继续执行只读截图、Journal 审计和离线测试。

## 当前状态

- 分支：`feat/hif`；工作区有大量用户未提交改动，禁止使用 `git reset --hard`、`git checkout --` 或覆盖无关文件。
- MuMu 12 已连接，HIF 原始帧契约通过：ADB 截图为竖屏 `720x1280`。
- 已进入 HIF 本战准备的“本战还有 4 日”。实测选择了 `差し入れ`，进入双奖励袋页面；上方奖励已领取，结果为 `Pドリンク獲得`。
- 当前停在下方奖励的 P 饮料三选一页面，尚**未**点击 `受け取る`：左侧已读取为 `初星黒酢`，中间为 `ミックススムージー`，右侧尚未读取。当前高亮中间仅表示 UI 默认/当前选中，不表示策略推荐。
- 新对话恢复后，首先读取右侧饮料的名称与效果；这一步仅切换候选，不领取。随后基于三项效果决定唯一目标，再点击 `受け取る` 并验证结果页。

## 已验证的环境

| 项目 | 值 |
| --- | --- |
| MuMu 安装目录 | `D:\game\MuMuPlayer-12.0` |
| 实例 | `1` / `MuMu安卓设备-1` |
| ADB 地址 | `127.0.0.1:16416` |
| ADB 可执行文件 | `D:\game\MuMuPlayer-12.0\nx_main\adb.exe` |
| 控制器 | MaaFramework `AdbController` |
| 截图尺寸 | `720x1280` |

只读复测：

```powershell
python tools/hif_controller_probe.py --adb 127.0.0.1:16416 --adb-path "D:\game\MuMuPlayer-12.0\nx_main\adb.exe" --save "debug\hif-runtime\resume.png"
```

探测工具已修复 ADB 列表中 `WindowsPath` 无法 JSON 序列化的问题；`tools/hif_controller_probe.py` 是本会话的未提交修改，已通过 `python -m py_compile`。

## 当前页面与实测证据

调试截图都在 `debug/hif-runtime/`，不可提交：

- `day4-raw.png`：本战还有 4 日行动选择页；体力 `22/35`、P 点 `250`。
- `day4-after-gift-tap.png`：首次点击 `差し入れ` 后的选中态。
- `day4-gift-confirmed.png`：第二次确认后进入双奖励袋。
- `day4-gift-upper-collected.png`：上方袋子奖励结果，`Pドリンク獲得`。
- `day4-drink-left-preview.png`：左饮料 `初星黒酢`：从弃牌堆选一张技能卡移入手牌；下一张使用的技能卡体力消耗变为 0（2 次）；体力消耗 2、消耗体力增加 1 回合。
- 用户提供的 `MuMu-20260713-083113-517.png`：中间饮料 `ミックススムージー`：将手牌全部替换，体力回复 2。

## 已发现的实现问题

### 1. 日程选择是两段式交互

`差し入れ` 的首次点击只进入选中态；第二次点击才进入事件。当前 `ProduceChooseHIFEventAuto` 的 `_click_box_with_verification` 只要发现前后帧变化就认为成功，可能把“选中态”误判为已进入事件。

修复方向：为日程候选增加“已选中但仍在同一日程页面”的中间状态；仅在检测到下一个页面锚点后完成事件选择，或在同一唯一候选已选中时再允许一次确认点击。

### 2. P 饮料候选名称不在候选卡槽内

`ProduceChooseHIFDrinkRewardAuto` 复用了 `_choose_named_reward`，该方法在候选 ROI 内 OCR 名称；但当前 UI 只展示**已选中**饮料的标题与效果，标题/详情位于 `details` 区域。故现有实现无法可靠按名称选择，应该安全停止。

建议实现“受控枚举 + 领取确认”：

1. 用 `drink_reward` 的提示文字确认页面。
2. 逐一选择左、中、右槽位（这不领取资源），每次 OCR `details` 区域中的名称与效果，并确认橙色选中框/详情变化。
3. 将 `name/effect/slot/confidence` 写入 Journal，按 `assets/data/hif/drinks.json` 与当前状态评分；未知名称或解析失败则停止。
4. 再选中唯一目标，OCR 定位 `受け取る`，点击后验证奖励结果文字或下一页锚点，不能只验证帧变化。

当前 `720x1280` 配置可保存在 `screen_profile`：

- 三个候选槽：左 `[158, 822, 127, 127]`、中 `[297, 822, 127, 127]`、右 `[436, 822, 127, 127]`；
- 详情区：`[118, 506, 500, 230]`；
- `受け取る`：`[230, 1052, 260, 84]`。

坐标仅用于页面锚定后的候选槽定位，不能作为无条件点击坐标。

## 安全约束

1. 所有 Round 数值 ROI 仍为 `null`；Round 只允许 `observe_and_stop`，不能开启单步或连续出牌。
2. 未确认页面、候选不唯一、OCR 为空、按钮无唯一命中、点击后无目标页面/结果验证时，必须进入 `ProduceHIFUnknownStop`。
3. 不把窗口外框偏移写进正式 Pipeline；仅接受 ADB 原始 `720x1280` 帧。
4. `debug/` 下日志、截图、Journal 只用于本地证据，禁止提交。
5. 目前没有运行中的 MaaGakumasu 任务前端；本会话为采集证据而使用 ADB 手动推进。不要将该手动推进误报为 Pipeline 闭环成功。

## 新对话的首个操作

1. 用上面的只读命令截取当前屏幕，确认仍是 P 饮料三选一。
2. 点击右槽中心约 `(500, 885)`，截图并读取名称/效果；不要点 `受け取る`。
3. 比较三项饮料后，向用户报告推荐与理由；得到确认或策略已具备唯一结论时才领取。
4. 随后优先实现并测试 P 饮料候选枚举，不要跳到 Round 自动出牌。

## 推荐本地检查

```powershell
python tools/hif_pipeline_check.py
python -m pytest -q
python -m py_compile agent/hif/*.py agent/hif/adapters/*.py agent/custom/action/produce_hif.py tools/hif_*.py
```

## 2026-07-13 21:04–21:07：Day6 `セレクトチェンジ` 源卡牌库只读闭环

### 当前实机状态

- MuMu ADB 原始帧仍为 `720x1280`，页面为 `select_change_source_deck`。
- 目标卡 A 为 `始まりの合図`；左侧源卡 B 槽仍是 `+`，`チェンジ` 按钮保持不可用。
- 本轮未点击任何源卡、未滚动牌库、未点击 `チェンジ`，游戏状态未推进。

### 页面锚点实测与修正

- Pipeline 入口先在标题 ROI `[0, 28, 285, 58]` 命中 `チェンジ`，仅用于将控制权路由到受限动作。
- 受限动作再要求同一帧同时满足以下双锚点，避免把其他变卡页误判为源卡牌库：
  - `[100, 570, 150, 55]`：`チェンジする`，实机 OCR 置信度 `0.999937`；
  - `[490, 570, 140, 55]`：`てください`，实机 OCR 置信度 `0.999990`。
- `hif-day6-source-observe-15` 先揭示首锚点实际文本为 `チェンジする`；
  `hif-day6-source-observe-16` 再揭示末锚点为 `てください`。两次均因后验不完整而安全停止，未发生输入。

### 正式只读复测

- 运行目录：`debug/hif-live/hif-day6-source-observe-17/`
- 前后帧：`before.png`、`after.png`；执行日志：`maafw.log`。
- Journal：`debug/hif-journal/20260713T210652-12960.jsonl`，审计结果：
  `entry_count=3`、`verified_execution_count=0`、`failures=()`。
- Journal 中记录 `observe_source_deck`，并保存帧
  `debug/hif-journal/20260713T210652-12960-0001-select_change_source_deck_observed.png`。
- 受限动作随后以 `source_card_selection_not_authorized` 进入 `ProduceHIFUnknownStop`；
  `maafw.log` 未出现 `post_click` 或 `post_swipe`。

### 已落实的保护

- `ProduceChooseHIFSelectChangeTargetAuto` 从目标卡页点击 `次へ` 后，使用有限重取帧的双锚点后验确认源卡页。
- `ProduceChooseHIFSelectChangeSourceAuto` 改为无条件只记录并停止，即使运行参数是 `single_step` 也不会选择、滚动或确认源卡。
- 源卡选择、牌库滚动、`チェンジ` 提交及结果页验证仍需独立的实机证据与显式授权，当前不得开启。

### 本轮验证

```powershell
python -m pytest -q tests/test_hif_screen_profiles.py tests/test_hif_pipeline_validation.py tests/test_hif_decision.py
# 53 passed
python tools/hif_pipeline_check.py
# ok=true, issue_count=0
python -m py_compile agent/custom/action/produce_hif.py agent/hif/screen_profiles.py tools/hif_live_runner.py
python -m ruff check agent/custom/action/produce_hif.py agent/hif/screen_profiles.py tools/hif_live_runner.py tests/test_hif_decision.py tests/test_hif_screen_profiles.py tests/test_hif_pipeline_validation.py
```

## 2026-07-13 21:16–21:36：源卡详情采样与一次滚动枚举

### 受限调试入口

- 普通 `single_step` 仍不能操作源卡牌库。
- 仅 `tools/hif_live_runner.py` 提供三个互斥的显式实验开关：
  - `--source-deck-probe`：首张完整可见卡详情采样后停止；
  - `--source-deck-enumerate-visible`：当前可见 12 槽枚举后停止；
  - `--source-deck-scroll-enumerate-visible`：向上滑动一次并枚举新可见区域后停止。
- 三者都要求 `--single-step`；均不授权 `チェンジ` 点击、结果页验证或任何 Round/技能卡领取动作。
- 名称 OCR 必须命中 `build_card_name_dict()` 词典；残片、未知名或空详情会安全停止。

### 首张卡详情采样

- 运行目录：`debug/hif-live/hif-day6-source-probe-18/`
- Journal：`debug/hif-journal/20260713T211654-38784.jsonl`。
- 首卡为 `夏夜に咲く思い出`，名称 OCR 置信度由 Maa 日志记录为 `0.995729`；它不是预设优先源卡。
- 详情帧：`debug/hif-journal/20260713T211654-38784-0002-select_change_source_deck_probe_after.png`。
- 该次只产生源卡选择态，`チェンジ` 虽可用但未点击，并以
  `source_deck_probe_complete_stop` 停止。

### 初始可见区枚举

- 运行目录：`debug/hif-live/hif-day6-source-visible-enumeration-19/`
- Journal：`debug/hif-journal/20260713T212412-41740.jsonl`，审计：
  `entry_count=15`、`verified_execution_count=0`、`failures=()`。
- 12 槽记录的可识别名称包括：
  `夏夜に咲く思い出`、`祝福+`、`話題沸騰+`、`自然体の魅力+`、
  `アイドル宣言+`、`仕切り直し+`、`タイミングの基本`、`スポットライト+`、
  `演出計画`、`静かな意志`、`始まりの合図+`。
- 其中没有 `大胆不敵`；`始まりの合図+` 虽属于旧预设的备用名称，但不能在未验证强化语义时视为可替换目标。

### 一次滚动后的关键证据

- 运行目录：`debug/hif-live/hif-day6-source-scroll-enumeration-20/`
- Journal：`debug/hif-journal/20260713T213601-20100.jsonl`，审计：
  `entry_count=16`、`verified_execution_count=1`（唯一一次已验证滑动）、`failures=()`。
- 已验证滑动：`(360,1040) -> (360,680)`，时长 `300ms`，方向向上，仅执行一次。
- 新可见区 `visible_slot_r2c3`（ROI `[374, 786, 120, 120]`）精确识别到：
  - 源卡 B：`大胆不敵`；名称置信度 `0.998934`；
  - 详情：`好調3ターン`、`集中+5`、`スキルカード使用数追加+1`、
    `眠気を山札のランダムな位置に生成`、`重複不可`；
  - 详情截图：`debug/hif-journal/20260713T213601-20100-0017-select_change_source_deck_visible_slot_r2c3_after.png`。
- 运行日志的所有触点为标题区、一次滑动起点和 12 个卡位中心；确认按钮 ROI
  `[373,1119,255,82]` 命中次数为 `0`。未点击 `チェンジ`，未发生卡牌替换。

### 当前停止点与后续决策

- 枚举结束时最后一个采样卡处于选中态，不是 `大胆不敵`；这不是提交状态。
- 已具备“重新精确选中 `大胆不敵`”的坐标与详情证据，但**尚不具备自动点击 `チェンジ` 的授权或结果后验实现**。
- 若后续明确允许提交，必须单独实现：精确重选 `大胆不敵` → 点击 `チェンジ` →
  OCR 验证完成提示 `大胆不敵を始まりの合図にチェンジしました`；任一步失败立即停止。

## 2026-07-14：Day4 差し入れ → P 饮料 → 技能卡领取页闭环

### 当前安全停点

- 当前画面已稳定在“`受け取るスキルカードを選んでください。`”技能卡领取页。
- 三张候选、`再抽選`、`受け取る`均**未点击**；Round 也没有进入执行。
- 最新只读证据目录：`debug/hif-live/hif-day4-skill-observe-35/`；前后帧均为原始 `720x1280`。
- 最新 Journal：`debug/hif-journal/20260714T091509-36412.jsonl`：
  - `observe_skill_reward=observed`，`mode=observe_and_stop`；
  - 随后以 `skill_reward_selection_not_enabled` 安全停止；
  - Maa 日志未出现技能卡、重抽或领取按钮的 Click Action。

### 实机过程与证据

1. 已选中 P 饮料详情态的路由修复

   - `hif-day4-drink-resume-enumerate-29` 曾把已选中详情态漏判为未知页，受限空白点累计点击 4 次后安全停止；未领取资源。
   - 新增 `ProduceHIFDrinkRewardPage` Custom Recognition：接受“初始提示”，或“已收录饮料详情 + 受け取る”双锚点。
   - `hif-day4-drink-resume-enumerate-30` 已实机命中该已选中态，证明修复生效。

2. 本次真实饮料枚举与选择

   `hif-day4-recovery-gift-32` 的 Journal：
   `debug/hif-journal/20260714T084557-42676.jsonl`。

   | 槽位 | 识别结果 | OCR 置信度 | 结果 |
   | --- | --- | ---: | --- |
   | 左 | `パワフル漢方ドリンク` | 0.906547 | 唯一最高分，重选 |
   | 中 | `リカバリードリンク`（体力回复 6） | 0.979607 | 未选 |
   | 右 | `初星ブーストエキス`（好调 2 回合、手牌全置换） | 0.989426 | 未选 |

   - 路线决策将左槽 `パワフル漢方ドリンク`作为唯一最高分候选，决策置信度 `0.89`。
   - 首次点击 `受け取る`后，画面进入金色饮料展示动画；随后底部库存新增该蓝色饮料图标。

3. 展示动画的实际语义

   - 展示动画中会短暂出现同名金色展示条和“受け取る”；它不是稳定的第二个资源提交控件。
   - `hif-day4-drink-reveal-confirm-33` 先以展示条 ROI
     `[72,840,576,76]`准确识别 `パワフル漢方ドリンク`（日志 OCR `0.998575`），但 Action 重新取帧时该控件已消失；该次**没有点击**，以 `drink_reward_reveal_page_not_confirmed`停止。
   - 后帧 `debug/hif-live/hif-day4-drink-reveal-confirm-33/after.png` 显示动画已自行进入礼袋过渡，且饮料库存图标已出现。
   - 因此 `ProduceHIFDrinkRewardRevealAuto`已改为“等待动画自行结束”，不会二次点击该瞬态文本；动画帧不变或仍可见时仍安全停止。

4. 差し入れ过渡到技能卡页

   - `hif-day4-drink-after-reveal-34` 从礼袋过渡使用一次受限空白点击 `[341,204,0,3]`，Journal
     `debug/hif-journal/20260714T090003-46240.jsonl`记录为 `safe_advance=verified`。
   - 之后正式根路由 OCR 精确命中 `受け取るスキルカードを選んでください。`，进入技能卡领取页；未点击任何卡片。
   - 最初技能页 profile 的 ROI `[132,588,456,44]`裁掉了文字下缘，实机误读为`受は取る...`并停止。现已校正为：
     - ROI：`[112,585,510,66]`；
     - 模式：`受[けは]取るスキルカードを選んでください`；
     - Pipeline OCR 同步使用该受限容错模式。

### 登录互斥恢复记录

- `hif-day4-drink-resume-enumerate-30` 首次领取后出现“通信エラー：别的设备登录或访问令牌已过期”。这是账户会话外部状态，不是卡牌或饮料 OCR 问题；管线在未命中技能页后停止，未操作卡牌。
- 按用户授权已重启游戏进程，进入标题页后点击 `Tap to Start`，在“プロデュース再開”中确认 HIF 本战 `3/7日`、距本战 4 日，并点击“再開する”。
- 恢复截图均在 `debug/hif-live/hif-day4-recovery-31/`：
  `after_restart.png`、`after_tap_to_start.png`、`after_resume_produce.png`。

### 代码与验证

- 新增 `agent/hif/reward_pages.py`、`agent/custom/reco/hif.py`，并将自定义 Recognition 注册也纳入 `agent/hif/pipeline_validation.py`。
- `ProduceHIFDrinkRewardRevealFlag`优先于普通饮料页路由；普通 P 饮料页支持提示态与已选中详情态。
- pending P 饮料仅在已确认技能卡领取页后由观察节点清除；技能卡观察动作仍会立刻安全停止。
- 最新离线验证：

  ```powershell
  python -m pytest -q tests/test_hif_reward_pages.py tests/test_hif_screen_profiles.py tests/test_hif_pipeline_validation.py tests/test_hif_live_runner.py tests/test_hif_decision.py
  # 79 passed
  python tools/hif_pipeline_check.py
  # ok=true, issue_count=0
  python -m py_compile agent/hif/reward_pages.py agent/custom/reco/hif.py agent/custom/action/produce_hif.py
  python -m ruff check agent/hif/reward_pages.py agent/custom/reco/hif.py agent/custom/reco/__init__.py agent/custom/action/__init__.py agent/custom/action/produce_hif.py tools/hif_live_runner.py tests/test_hif_reward_pages.py tests/test_hif_screen_profiles.py tests/test_hif_pipeline_validation.py tests/test_hif_live_runner.py tests/test_hif_decision.py
  ```

### 后续限制

- 未获得新的明确方案与实机证据前，不得选择技能卡、不得重抽、不得点击技能页领取按钮，也不得推进到 Round。
- `debug/`中的截图、Journal 与 Maa 日志为本轮复盘证据，禁止提交。

### 2026-07-14：技能卡领取页审计与下一阶段门槛

- 当前现场停留在 `skill_reward`，已由原始 `720x1280` 截图、
  `debug/hif-journal/20260714T091509-36412.jsonl` 与
  `debug/hif-live/hif-day4-skill-observe-35/maafw.log` 三方核验：三张候选、`再抽選`、`受け取る`均无 Click Action。
- 现有 `ProduceChooseHIFSkillRewardAuto` 的实现是刻意的只读停点：确认提示锚点后记录
  `skill_reward_selection_not_enabled` 并停止。`tools/hif_live_runner.py` 的单步覆盖也不包含
  `ProduceHIFSkillRewardFlag`，因此不能把“全程测试授权”错误地当成可跳过识别、决策和后验的实现授权。
- 资料中仅有技能卡领取页的提示、候选总区域、详情区域、重抽次数和两个按钮 ROI；当前没有：
  1. 三个独立候选卡槽的稳定 ROI 与卡名 OCR 采样；
  2. 候选卡均可归一到 `HIFSkillCard` 目录后的唯一决策规则；
  3. 重抽次数、重抽后候选变化和领取后下游页面的完整后验；
  4. 对应的离线夹具和实机单步动作。
- Round 也仍为受限状态：正式 Pipeline 的 `Round1/2` 均传入 `execution_mode=observe_and_stop`。
  虽然 `ProduceCardsHIF` 有单张牌的实验性执行分支，但它还要求设备专属出牌 ROI 校准、唯一手牌目标、完整状态字段和点击后验证；这些条件没有以当前实机证据满足。
- 本次审计后的离线回归结果：
  `python -m pytest -q tests/test_hif_reward_pages.py tests/test_hif_screen_profiles.py tests/test_hif_pipeline_validation.py tests/test_hif_live_runner.py tests/test_hif_decision.py tests/test_hif_route_planner.py tests/test_hif_session.py tests/test_hif_screens.py tests/test_hif_state_reader.py`
  为 `98 passed`；`python tools/hif_pipeline_check.py` 为 `ok=true`；相关 Python 编译与 Ruff 检查通过。
- 下一阶段必须先实现“只读枚举三张技能卡 -> 全部名称/详情可验证 -> 唯一决策或安全停止”的独立闭环，
  再单独开启一次“选中 -> 领取 -> 命中下一已知页面”的受限实机测试。Round 需要在该阶段之后另行校准，不能与技能卡领取混测。

### 2026-07-14：技能卡候选枚举闭环

- 新增显式实验开关 `--skill-reward-enumerate --single-step`。它只允许逐槽选中以读取详情，
  不重抽、不点击 `受け取る`、不进入 Round；默认和普通 `single_step` 仍维持技能卡页安全停止。
- 候选被选中后，原始提示文本会被详情替换。为此新增 `ProduceHIFSkillRewardSelectedPage`：
  同时要求详情标题命中收录卡名及 `受け取る` 按钮命中，才将详情态路由回
  `ProduceChooseHIFSkillRewardAuto`；它排在安全空白推进前。
- 实机探针过程及发现的问题：
  - `hif-day4-skill-enumerate-36`：首次点击左槽 `(221,885)` 后进入 `意地` 详情态，
    原提示锚点消失，触发 `skill_reward_page_lost_after_slot_selection` 安全停止。未点击重抽或领取。
  - `hif-day4-skill-enumerate-37`：详情态还未接入根路由，安全空白推进识别到已知
    `skill_reward` 页面并以 `safe_advance_blocked_by_known_page:skill_reward` 拦截，未发生输入。
  - `hif-day4-skill-enumerate-38`：已接入详情态路由，但运行器遗漏向该节点传递探针参数；
    以默认 `skill_reward_selection_not_enabled` 停止，未发生输入。
  - `hif-day4-skill-enumerate-39`：修复后完成三槽枚举并以
    `skill_reward_probe_complete_stop` 停止。实际输入只有中槽 `(360,885)` 与右槽 `(499,885)`；
    左槽为已知选中态，仅重新读取详情。
- 最终 Journal：`debug/hif-journal/20260714T094407-38892.jsonl`。候选证据如下：

  | 槽位 | 卡名 | 已识别详情 | 置信度 |
  | --- | --- | --- | ---: |
  | 左 | `意地` | `元気+3`、`集中+4`、`レッスン中1回` | 0.999722 |
  | 中 | `トークタイム` | `好調状態の場合、使用可`、`パラメータ+27`、`レッスン中1回` | 0.999443 |
  | 右 | `祝福` | `体力消費4`、`パラメータ+26`、`好調1ターン`、`レッスン中1回` | 0.999575 |

- 成功运行目录为 `debug/hif-live/hif-day4-skill-enumerate-39/`；中、右卡详情帧分别为
  `debug/hif-journal/20260714T094407-38892-0003-skill_reward_candidate_center_after.png` 与
  `debug/hif-journal/20260714T094407-38892-0005-skill_reward_candidate_right_after.png`。
  Maa 日志未出现领取或重抽按钮的 Click Action。
- 本阶段离线验证：`96 passed`，`python tools/hif_pipeline_check.py` 为
  `ok=true, issue_count=0`，相关编译与 Ruff 检查通过。
- 当前只证明“枚举与详情态恢复”闭环。尚未将三张卡接入唯一评分、选中后重校验、领取后下游页后验；
  因而不得根据当前候选自动领取，也不得开始 Round。

### 2026-07-14：技能卡纯决策复测与根路由隔离验证

- 在运行前以 `debug/hif-runtime/skill-reward-before-decide-41.png` 确认仍处于技能卡领取页，
  中槽 `トークタイム` 已选中。原始 ADB 帧为 `720x1280`。
- 已运行受限命令：

  ```powershell
  python tools/hif_live_runner.py --adb 127.0.0.1:16416 --adb-path "D:\game\MuMuPlayer-12.0\nx_main\adb.exe" --single-step --skill-reward-decide --skill-reward-initial-slot center --seconds 30 --run-id hif-day4-skill-decide-41
  ```

  运行目录为 `debug/hif-live/hif-day4-skill-decide-41/`，Journal 为
  `debug/hif-journal/20260714T104111-45992.jsonl`。它以
  `skill_reward_decision_recorded_stop` 安全结束。
- `tools/hif_live_runner.py` 的根路由隔离补丁已获实机验证：实际 `MaaControllerPostClickV2`
  仅有候选槽左 `(221,885)` 和右 `(499,885)` 两次点击。未再出现通用 `ProduceExit`
  导致的 `(28,27)` 点击，也没有 `受け取る`、`再抽選` 或 Round 相关点击。
- 三张候选及唯一决策与前次枚举一致：

  | 槽位 | 卡名 | 关键详情 | 结论 |
  | --- | --- | --- | --- |
  | 左 | `意地` | `元気+3`、`集中+4` | 未选 |
  | 中 | `トークタイム` | `好調状態の場合、使用可`、`パラメータ+27` | 未选 |
  | 右 | `祝福` | `体力消費4`、`パラメータ+26`、`好調1ターン` | 唯一推荐 |

  对莉波好调路线，`祝福`直接提供 `好調`，优先于依赖已有 `好調` 的
  `トークタイム`；记录的决策置信度为 `0.61`。
- 结束帧 `debug/hif-live/hif-day4-skill-decide-41/after.png` 显示右槽 `祝福` 已选中，
  但 `受け取る` 仍未点击，游戏尚未领取资源也未进入 Round。
- 离线验证结果：定向测试 `117 passed`；Ruff、
  `python -m py_compile agent/hif/catalog.py agent/hif/route_planner.py agent/custom/action/produce_hif.py tools/hif_live_runner.py`
  与 `python tools/hif_pipeline_check.py` 均通过（后者 `ok=true, issue_count=0`）。
- 后续限制：`--skill-reward-receive` 会产生不可逆的游戏内领取；除非用户再次明确授权领取
  `祝福`，不得运行该命令。当前可继续做离线验证或只读审计。

### 2026-07-14：变卡跨页目标状态修复

- 修复了源卡提交完成后验可能错误使用运行器硬编码目标卡名的问题。
  `ProduceChooseHIFSelectChangeTargetAuto` 仅在“目标卡已重新选中、点击 `次へ` 且源卡牌库双锚点确认”后，
  将本次实际确认的 `target_name` 写入运行期 `HIFRunSession.pending_select_change`。
- `ProduceChooseHIFSelectChangeSourceAuto` 的受限 `confirm_source_card` 模式现在只读取该运行期状态；
  不接受 `target_card_name` 参数，也不会回退到预设的首选目标。缺失、无效或与当前 preset 不符时，以
  `selected_target_card_missing_or_invalid` 安全停止。成功 OCR 完成提示后才清除状态。
- `tools/hif_live_runner.py --source-deck-confirm-target` 保留明确的源卡 `大胆不敵`，
  但不再注入目标卡名。完成提示会校验为实际选中的卡，例如
  `大胆不敵をスポットライトにチェンジしました`，而非固定的 `始まりの合図`。
- 离线验证：

  ```powershell
  python -m pytest -q tests/test_hif_session.py tests/test_hif_live_runner.py tests/test_hif_decision.py tests/test_hif_route_planner.py tests/test_hif_pipeline_validation.py tests/test_hif_reward_pages.py tests/test_hif_screen_profiles.py tests/test_hif_screens.py tests/test_hif_state_reader.py
  # 121 passed
  python tools/hif_pipeline_check.py
  # ok=true, issue_count=0
  python -m py_compile agent/hif/session.py agent/hif/catalog.py agent/hif/route_planner.py agent/custom/action/produce_hif.py tools/hif_live_runner.py
  python -m ruff check agent/hif/session.py agent/custom/action/produce_hif.py tools/hif_live_runner.py tests/test_hif_session.py tests/test_hif_live_runner.py tests/test_hif_decision.py
  ```

- 当前实机仍停留在技能卡领取页，唯一策略推荐是右槽 `祝福`，且 `受け取る` 尚未点击。
  下一次实机推进会领取该卡并验证进入 `Round1`，这是不可逆的游戏内操作，需要用户再次明确授权；
  在授权前仅允许只读审计和离线测试。

## 2026-07-14：HIF 自动化覆盖矩阵与安全后验收口

- 本阶段严格按离线边界执行，没有连接或点击模拟器，也没有读取/改变当前游戏状态。
- `assets/data/hif/pipeline_coverage.json` 现在完整登记 `ProduceHIF.json` 的 54 个节点，声明成功、拒绝/安全停止、后验失败或不适用理由，并登记正式入口、动态 `run_task` 终止节点、历史孤立链、Action 内部停止节点和安全推进前的路由优先级。
- `tools/hif_pipeline_check.py` 除节点/Custom 注册和跳转外，还检查覆盖矩阵、OCR 正则、`720x1280` ROI 与模板文件引用。任务配置测试同时核对 `produce.json` / `produce_cn.json` 的 HIF override 一致性和默认观察权限。
- 新增 9 张最小真实帧夹具，覆盖课程预览、饮料奖励/满仓、变卡目标/源卡、技能卡详情/展示以及回忆照片两态。清单记录 MuMu 12 来源、游戏状态数据声明与 SHA-256；测试只做尺寸、ROI、页面分类和已记录 OCR 适配器回放，不宣称 Maa OCR E2E。
- 修复并固化以下安全缺口：
  - 空白推进、日程一/二次确认、公开课结算、饮料展示和开始培育不能再仅凭帧变化成功，必须命中已知下一页或正式过渡识别。
  - 饮料满仓恢复缺少 `single_step` 时零点击并安全停止。
  - 变卡源卡确认不能用 Action 参数重建丢失的目标卡运行状态。
  - Round 单步出牌在缺少手牌/回合/数值后验时固定拒绝执行；Live `skip_once` 同样在目标页后验完成前保持安全停止。
  - 回忆照片选择、确认、生成、预览及结算继续动作要求命中各自允许的下一页面。
- 最终离线结果：HIF 专项 `199 passed`，全仓 `241 passed`，`python tools/hif_pipeline_check.py` 为 `ok=true, issue_count=0`；Python 编译、Ruff 与覆盖清单 Prettier 检查通过。
