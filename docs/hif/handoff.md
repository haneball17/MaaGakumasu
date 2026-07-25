# HIF 实测任务交接（更新至 2026-07-15）

本文用于在新对话中恢复 HIF 实机验证。以当前工作区和当前模拟器画面为准；不要根据旧会话记录回退文件或猜测游戏状态。

## 2026-07-15：莉波感性压缩循环的 Round1 测试规范（下一会话执行）

本节是用户已确认的后续实施规格。下一会话先完成离线实现和验证，再恢复实机；不要在未完成第 1 步前继续出牌。

### 目标与范围

- 仅限当前一局的 `Round1`；达到样本目标后立即停止并输出可审计报告，**不得**自动进入 Round2 或后续日程。
- 测试期允许自动执行普通游戏操作，尽量减少用户介入；但**不得**消耗付费货币、付费刷新、钻石类货币或无法可靠判定是否稀缺的资源。
- 流派模型固定为“姬崎莉波・荆棘之路・感性压缩循环”：以好调收益、再演、压缩牌库、抽到/强化终结卡为长期核心；画面 Vo/Da/Vi 仅是运行时参数，不是该流派定义。
- 优化目标为最大化本局长期期望收益：先避免失败与体力风险，再维持/扩大好调与再演循环，随后压缩/抽取终结资源，最后在终结窗口最大化即时参数。信息增益可用于安全探索未知卡，但优先级低于长期收益、高于纯即时面板收益。
- 结算目标是 `S4+` 与 Round1 结算总分优化；当前参考目标为 `750000 × 1.2 = 900000`。`1.2` 必须视为可能变化的倍率，须实机读取或在结算页验证，禁止写死为通用常量。

### 数据与决策约束

- `assets/data/hif/skill_cards_master.json` 是可版本控制的基础对照；运行时以实机详情为准。
- 卡牌识别使用 YOLO 卡框 + 卡面/详情 OCR 标题映射；详情效果中的关键字段（消耗、条件、数值、抽牌/重抽/再演）须两次一致，或与卡表一致，才可作为新策略依据。
- 实机详情与卡表不一致时，保留原卡表，写入带截图、Journal、时间和置信度的候选观测覆盖层；不得直接覆盖主数据。
- 首版采用增量建模：仅对已观察到或随后抽到的卡建立结构化词条。未知卡可作为信息增益候选；效果未确认、标题不唯一、状态缺失或分数差距不明确时，只采样/记录并安全停止，不猜测出牌。
- 结构化词条至少覆盖：基础名和强化档位、体力/集中/使用次数消耗、即时参数、好调/集中/再演、持续/条件、抽牌/重抽/生成卡、减耗、负面风险、一次性/重叠限制以及 Vo/Da/Vi 参数关联。
- 评分必须解释“为什么该卡对莉波感性压缩循环有利”；模型先以当前状态和词条计算长期价值，再考虑可验证的信息增益。若第一名优势不足以证明唯一性，或模型无法可靠预测结算目标，则停止采样而非连续执行。

### 样本与通过标准

- 总计 10 个样本：至少 `8` 张成功出牌样本 + `2` 个正确拒绝样本。
- 成功样本按“基础卡名 + 强化档位”去重，`祝福` 和 `祝福+` 分别计数；同版本重复仅作回归证据。
- 每张成功样本须有完整闭环：唯一映射 → 首次选择 → 精确标题与 `SELECT` 双锚点 → 同目标二次确认 → 目标离手与稳定状态后验。首次完整闭环即可计数；OCR 低置信、后验缺字段、卡表不一致或运行异常时必须复测，且该次不计数。
- 两个拒绝样本必须覆盖不同原因：一个灰色/不可用卡（当前候选 `眠気`），一个标题/效果/状态不满足执行门槛的卡。
- 历史上只有部分后验或缺少完整闭环的操作保留为观测数据，**不补计**入 10 样本。

### 当前计数与证据

- 严格合格的成功样本为 `5/8`：`お姉さんの感覚`、`天賦の才+`、`自然体の魅力+`、`アイドル宣言+`、`存在感+`。
- 还需 `3` 张新的成功出牌样本和 `2` 个不同原因的正确拒绝样本。
- 历史 `至高のエンタメ`、`仕切り直し+`、`話題沸騰+` 等证据存在即时后验不可读、详情映射失败或闭环不完整的问题，只能用作模型和数据对照。
- 当前现场在 Round1 未选中手牌页：`演出計画 / 眠気 / 祝福 / 祝福+`；最近可信状态为 `turn=6 / good_condition=47 / focus=10 / stamina=33 / reprise=2`。最近 `存在感+` 后验中的 `deck_size=0` 是读取缺失时的非可信默认值，禁止作为状态事实或决策依据。

### 下一会话实施顺序

1. 先实现并校准 Round1 参数/实时分数读取、结算总分读取与动态倍率验证；当前 `ExamState.params` 未识别，不得假装可以实时优化 90 万目标。
2. 为已观察卡建立结构化词条与莉波感性压缩循环评分器，补离线单元测试、校准夹具和候选观测覆盖层。
3. 重新读取当前手牌、牌库和完整状态；先完成一个灰色卡拒绝样本及一个门槛拒绝样本。
4. 按受限单卡闭环完成剩余 3 张成功样本；每张的实机详情优先于卡表，且不消耗受限资源。
5. 达到 `8+2` 后停止，输出卡名/强化档位、效果观测、选择理由、前后状态、读取置信度、拒绝原因、结算分与倍率（若到达结算页）的报告。

### 2026-07-15：Round1 指标读数首轮实现与零输入复核

- 已新增 `agent/hif/round_metrics.py`：参数、局内分数、舞台倍率与结算页“基础分 + 加分”均采用显式、可审计解析；缺字段或混入其他数字时保持 `None`，不再以参考 `1.2` 或零值代替实测倍率。
- `roi_calibration.json` 已单独登记结算榜首分数对 ROI，证据为
  `assets/resource/test/学マス(2).mp4_20260709_221803.047.jpg`（SHA-256
  `5fff1e6bffd139f2e74738ab141a5259771700bf31c7377eecf303158d877c44`）。
  该帧可读 `4,756,391+2,692,097`，解析的最终分为 `7,448,488`，动态有效倍率为
  `7,448,488 / 4,756,391`；这不是通用常量。
- `ExamStateReader` 只有在 `param_vo`、`param_da`、`param_vi`、`current_score`、
  `stage_multiplier` 都来自已校准 ROI 时，才填充 `ExamState.params`、实时分数和倍率；
  不完整时将它们加入执行门槛缺失项。
- 已运行零输入命令：

  ```powershell
  python tools/hif_live_runner.py --adb 127.0.0.1:16416 --adb-path "D:\game\MuMuPlayer-12.0\nx_main\adb.exe" --single-step --round1-state-observe --seconds 30 --run-id hif-round1-metrics-observe-20260715
  ```

  运行目录为 `debug/hif-live/hif-round1-metrics-observe-20260715/`，Journal 为
  `debug/hif-journal/20260715T182200-38668.jsonl`。Maa 日志没有
  `MaaControllerPostClickV2`，因此本次未发生点击、滑动或出牌。
- 实际现场与上文旧“未选中手牌页”描述不一致：前后原始帧均为 Round1 的
  `演出計画` 已选详情态，`SELECT` 可见；其余手牌为灰色 `眠気`、`祝福`、`祝福+`。
  可信状态为 `turn=6 / good_condition=47 / focus=10 / stamina=33 / reprise=2`；
  牌库仍未读取。顶部可稳定看到 `ビジュアル 3807%`，但当前画面未提供经验证的
  Vo/Da/Vi 参数或局内总分 ROI；三张排名卡的数值不能当作参数。故本轮缺失
  `deck_size`、五个新指标字段，**不得继续出牌、不得开始两个拒绝样本**。
- 离线验证：`216 passed`，`python tools/hif_pipeline_check.py` 为
  `ok=true, issue_count=0`；新增模块编译、Ruff、ROI JSON Prettier 与
  `git diff --check` 均通过。

### 2026-07-15：Round1 实时分数与倍率校准收口（最新）

- 已确认底部“文档”图标 `(460,1198)` 打开的是可逆的指标/履历面板，而不是直接可用的旧 `hand_history_view` profile。该面板以 `獲得スコア` 和 OCR 会误读为 `審查基準` 的双锚点确认；关闭按钮中心为 `(360,1164)`，后验必须回到 Round1。
- 首次实现曾将该面板按旧 `hand_history_view` 或 `round_details` 识别，均以 `round_details_not_confirmed` 安全停止；没有选择手牌、出牌、使用饮料或消耗资源。随后已将运行器的 `--round1-details-observe --single-step` 固化为“打开 → 读数 → 关闭 → Round1 后验”的两次受限输入流程。
- 成功实机运行：`debug/hif-live/hif-round1-score-multiplier-calibrated-20260715/`；Journal 为 `debug/hif-journal/20260715T185253-45208.jsonl`。
  - 局内 `current_score=116611`，OCR 置信度 `0.998627`，面板 ROI `[42,145,135,38]`；
  - 主 Round `stage_multiplier=3807%`，OCR 置信度 `0.974869`，ROI `[65,75,150,48]`；
  - 面板关闭后确实回到 Round1，Journal 记录两次且仅两次控制器输入：打开指标页、关闭指标页。
- `assets/data/hif/roi_calibration.json` 已登记上述 `round_metrics.stage_multiplier` 与 `round_metrics_panel.current_score`；`ExamState.params` 的 Vo/Da/Vi 三维值在当前 Round UI 中仍不可见，继续保持缺失，**不得**以排名卡的三个人物分数替代。
- 结算页总分/动态有效倍率的解析与样本 ROI 已完成；本战尚未到达结算页，当前不得把历史结算样本或 `1.2` 参考值带入本局决策。
- 当前不可出牌原因缩小为：牌库数未重读、四张候选的完整详情/结构化评分尚未建立，且 Vo/Da/Vi 参数仍不可观测。下一步先完成已观察卡的结构化词条、评分器和离线夹具，再对 `眠気` 做零资源的灰卡拒绝样本；不得直接确认 `演出計画`、`祝福` 或 `祝福+`。
- 最新定向验证：`136 passed`，受影响 Python 模块编译与 Ruff 通过；本轮没有暂存、提交、推送或清理既有工作区改动。

## 2026-07-15：`存在感+` 用户指定单卡执行（最新）

- 用户明确指定尝试打出 `存在感+` 后，先保存零输入帧，确认其为未选中五卡页的第二张。
- 新增受限 CLI 入口 `--round1-hand-detail-map-deck-select-presence`：仅可将已授权的 `存在感` 在同进程完成五张详情映射、牌库与状态读取后进行首次选择；它不包含第二次确认。`hif-round1-presence-select-only-12` 的 Journal `debug/hif-journal/20260715T161201-49296.jsonl` 记录五张详情、牌库 21 和 `select_card=verified`，其中 `confirmation_clicks=0`。
- 将已实测的 `存在感` 加入 `--round1-confirm-selected-name` 白名单后，`hif-round1-presence-confirm-13` 正常完成。Journal `debug/hif-journal/20260715T161516-42860.jsonl` 记录 `confirm_selected_card=verified`：`存在感` 已从手牌移除；可信后验为 `turn=6 / good_condition=47 / stamina=33 / focus=10 / reprise=1`。
- 此快速后验的 `deck_size=0` 是读取缺失时的非可信默认值，禁止据此推导牌库状态或继续自动出牌。当前已停止全部控制输入；下一步必须先零输入重建新手牌及完整状态。
- 本次入口与白名单的定向离线检查为 `173 passed`，Ruff 与 `git diff --check` 通过。

## 2026-07-15：`アイドル宣言+` 单卡确认与新停点（最新）

- `hif-round1-idol-declaration-select-only-10` 已完整重建五张详情、状态与牌库，并只完成了 `アイドル宣言+` 的首次选择；Journal `debug/hif-journal/20260715T150013-46492.jsonl` 明确记录 `confirmation_clicks=0`，未确认出牌。
- 零输入截图随后确认当前仍为该卡的详情选中态：Round1、剩余 6 回合、好调 47、集中 5、体力 33、再演 2、牌库 21。
- 已扩展 `--round1-confirm-selected-name` 白名单以允许经过详情映射验证的 `アイドル宣言`，并新增 CLI 绑定测试。离线门禁为 `171 passed`，Ruff 与 `git diff --check` 通过。
- `hif-round1-idol-declaration-confirm-11` 以已选卡二次确认入口重新验证 Round 页面、精确标题、`SELECT` 和唯一 YOLO 卡框后，执行唯一一次确认。Journal `debug/hif-journal/20260715T154939-45900.jsonl` 的 `confirm_selected_card=verified` 记录：`アイドル宣言` 已离手，后验首帧即得到新手牌 `演出計画 / 存在感+ / 眠気 / 祝福 / 祝福+`，且状态仍为 `turn=6 / good_condition=47 / focus=5 / stamina=33 / reprise=2 / deck_size=21`。
- 运行器在已写入成功后验后触及 60 秒总时限并报告 `timeout_stopped`；不得将该运行器结果单独视作失败，Journal 的已验证后验和结束帧为准。
- 当前局停在未选中 Round1 的新五卡页。后续不得直接出牌；应先为这组新手牌建立独立、唯一、可复算的策略及两段确认/后验设计。

## 2026-07-15：`仕切り直し+` 恢复确认与后验停点（最新）

- 修复 `hand_details_map_deck_play_one` 首次确认错误硬编码 `話題沸騰` 的问题，现改为核验本次实际目标名；恢复 CLI 白名单新增已验证目标 `仕切り直し`。
- 运行 `hif-round1-shikirinaoshi-confirm-fix-02` 已通过 `仕切り直し+` 的标题与 `SELECT` 双锚点执行第二次点击。结束帧显示该卡已离手、手牌已重抽；未执行第二张。Journal：`debug/hif-journal/20260715T124431-7880.jsonl`。
- 自动后验随后因新手牌中的 `眠気` 未进入详情 OCR 词典而停止。已将其加入“仅 OCR 识别、不可决策”的已观察基础卡词典；离线回归通过后，`hif-round1-post-shikirinaoshi-readonly-03` 只读枚举仍因当前已选 `アイドル宣言+` 无法唯一回配到 YOLO 框而以 `round_hand_probe_selected_target_not_unique` 停止，未确认出牌。
- 当前局停在 Round1 重抽后的新手牌详情态。后续不得直接出牌；应先修复“已选详情标题到唯一 YOLO 框”的回配，并用只读枚举完成所有新手牌标题映射后，才能把本次目标离手和新手牌集合写作完整自动后验。

### 后续只读枚举已完成

- `hif-round1-post-shikirinaoshi-readonly-07` 成功完成五张重抽后手牌详情映射，Journal：`debug/hif-journal/20260715T143501-37628.jsonl`；无 `safe_stop`，未执行卡牌确认。
- 已验证映射：`アイドル宣言+ / 演出計画 / 存在感+ / 眠気 / 祝福`。首张 `アイドル宣言+` 的卡面 OCR 与详情标题均为 `0.9992+`，并由 `SELECT` 标记 `[68,1102,82,29]` 唯一回配至第一张 YOLO 框；其余四张逐张详情确认。
- 为完成该验证，`眠気` 与 `アイドル宣言` 已加入“仅 OCR 识别、不可决策”的已观察词典。`SELECT` 几何回配仅在标题 OCR 缺失或歧义时启用，且必须唯一命中一个 YOLO 卡框。
- 当前枚举结束时最后一张 `祝福` 处于详情选中态。没有经批准的下一张出牌策略，后续必须先完成新状态的独立策略与两段确认/后验设计，不得直接确认 `祝福`。

## 2026-07-15：`話題沸騰+` 单卡执行与后验安全停点（最新）

- 已在 `turn=6 / good_condition=47 / focus=5 / stamina=33 / reprise=2 / deck_size=21` 的未选中五卡 Round1 页面，运行受限同进程入口 `--round1-hand-detail-map-deck-play-one --single-step`。
- 首次实机尝试因详情映射已补齐 `hand_names` 后未同步刷新 `screen_confidence`，以 `screen_confidence_too_low` 停止；没有点击 `SELECT` 或出牌。修复为仅在所有缺失字段消除后将置信度设为 `1.0`，并新增拒绝/恢复测试。
- 重试已实际两段式执行 `話題沸騰+`：稳定截图和前后两次详情枚举证明该卡从五张手牌中移除，当前手牌为 `鳴り止まない拍手+ / 夏夜に咲く思い出 / 仕切り直し+ / 始まりの合図`，牌库仍为 `21`，页面仍为 Round1 第 `6` 回合。
- 重试 Journal `debug/hif-journal/20260715T101554-47620.jsonl` 的自动后验因出牌后四张手牌框位变宽、旧详情映射不再匹配而以 `post_hand_not_readable` 安全停止；它没有继续第二张。后续只读/枚举审计 Journal `debug/hif-journal/20260715T102028-35956.jsonl` 记录了四张精确详情、完整状态和 `controller_inputs=4`，确认不存在 `話題沸騰`。
- 当前不得继续出下一张。下一阶段需要先实现并测试“目标离手后，用当前四卡 YOLO 框重新枚举详情 → 与目标前手牌集合做语义差分 → 记录零消耗卡的有效后验”的受限后验路径；不得使用 CLI 注入历史手牌、坐标或状态。
- 本次代码验证：`python -m pytest -q tests -k hif` 为 `268 passed, 52 deselected`；`python tools/hif_pipeline_check.py` 为 `ok=true`；相关 `py_compile`、Ruff 与 `git diff --check` 通过。未提交、暂存、推送或清理既有改动。

## 2026-07-15：本次恢复检查

- 已用零输入 ADB 探针保存 `debug/hif-runtime/resume-current-20260715.png`。当前为未选中 `Round1` 五卡手牌页，画面显示剩余 `6` 回合；未发送任何出牌、资源领取或页面推进输入。
- 已重新运行直接相关门禁：`python -m pytest -q tests -k hif` 为 `259 passed`，`python tools/hif_pipeline_check.py` 为 `ok=true, issue_count=0`，`git diff --check` 无输出。
- 当前工作区仍包含既有的大量 HIF 未提交修改与无关未跟踪资源，必须保留原样；本次未暂存、提交、推送、清理或回退文件。
- `--round1-hand-detail-map-deck-play-one` 的测试与实现尚未完成，未进行实机单卡执行。恢复时应继续遵循下节的“下一阶段实施计划”，先以失败测试固定同进程映射、完整状态、唯一目标、两段式确认和语义后验的契约。

## 2026-07-15：下一阶段实施计划（最新）

当前停点不是普通 `--round1-play-one` 的适用场景。该入口在新进程启动后没有本轮五张详情到 YOLO 框的映射，
不能把最新 Journal 的卡名或坐标当作输入参数复用。下一阶段必须按以下顺序完成：

1. 先从当前 Round1 未选中手牌页保存零输入原始帧，并重跑直接相关的 HIF 测试、Pipeline 校验、编译、Ruff 和
   `git diff --check`。任何状态偏差先只读分类，不出牌。
2. 为一个新的、与 `--round1-play-one` 互斥的 `--single-step` 入口补失败测试。入口在**同一次运行**中必须完成
   五卡详情映射、牌库读取、完整状态读取、唯一决策、两段式确认和一张卡的后验；缺失映射、`SELECT` 已存在、
   灰牌、非唯一目标、校准不可执行、状态缺失或后验失败必须停止。
3. 实现该入口并保留现有 `HIFRunSession` 详情映射，禁止从 CLI 传入目标卡名、坐标或历史状态。仅当完整状态满足
   `round1 / good_condition >= 8 / 非灰且唯一 話題沸騰 / 所有必需字段存在` 时，
   `choose_high_good_condition_topic_card()` 才可产生精确目标。
4. 单步实机执行前重跑门禁；第一次点击仅验证同一目标的精确标题和 `SELECT`，第二次才确认。执行后必须验证
   `話題沸騰` 离开手牌、仍处于已知 Round1 页面且回合或可信状态字段出现机制一致变化。动画期仅按有限重读等待，
   不得以帧变化判定成功，也不得在一次运行内继续第二张。
5. 成功或失败后都先进行零输入观察和 Journal/控制器输入审计；只有完整后验成功后，才根据新的手牌和状态规划下一张。
   Round 循环、Interval、Round2 与后续日程不在本阶段授权范围内。

当前唯一待验证候选仍为 `話題沸騰`，来自 `debug/hif-journal/20260715T052515-16536.jsonl`，状态为
`turn=6 / good_condition=47 / focus=5 / stamina=33 / reprise=2 / deck_size=21`。此条仅定义受限单卡实现和测试目标，
不等同于已经批准或已经完成的出牌。

## 2026-07-15：五卡完整状态同进程采证成功（最新）

- 新增 `--round1-hand-detail-map-deck-observe`。它在同一运行内依次读取五张详情、用 IoU 匹配将标题回填到初始 YOLO 框、读取牌库并确认选中态已被牌库面板清除；始终为观察模式。
- 实机 run `debug/hif-live/hif-round1-five-card-map-deck-retry-20260715-051108/` 成功：Journal `debug/hif-journal/20260715T051112-5384.jsonl` 的 `mapped_hand` 为 `話題沸騰 / 鳴り止まない拍手 / 夏夜に咲く思い出 / 仕切り直し / 始まりの合図`，`deck_size=21`，`missing_after=[]`。
- 该 run 的全部输入可审计为五次详情选中和两次牌库面板开关；没有 `SELECT`、资源领取、出牌或通用根路由点击。
- 当前局返回未选中 Round1 手牌页。下一步先将完整候选集接入同一进程的精确策略与受限单张执行入口；不得在新进程中丢弃详情映射后直接使用普通 `--round1-play-one`。
- 最新复合观察 `debug/hif-journal/20260715T052515-16536.jsonl` 已给出唯一下一目标 `話題沸騰`；状态为 `turn=6 / good_condition=47 / focus=5 / stamina=33 / reprise=2 / deck_size=21`。此结论仅授权后续同进程、受限单张入口，尚未执行该卡。

## 2026-07-15：Round1 两张单卡实测与五卡手牌停点（最新）

- `天賦の才+` 已通过两段绑定、目标离手和新手牌后验；证据为 `debug/hif-journal/20260715T035513-7008.jsonl`。
- `自然体の魅力+` 点击后的即时帧仍保留目标，旧后验错误停止；随后只读稳定帧确认其实际生效并进入第 6 回合（体力 `33`、集中 `5`、好调 `47`、使用次数 `3`、手牌重抽）。后验现改为最多 8 次、每秒重读，覆盖“再演/动画中暂留目标后最终替换”的测试；原 run 证据为 `debug/hif-journal/20260715T035943-43200.jsonl`。
- 当时局仍在 Round1、第 6 回合。五张手牌的详情已采证：`話題沸騰+ / 鳴り止まない拍手+ / 夏夜に咲く思い出 / 仕切り直し+ / 始まりの合図`。当时停在 `夏夜に咲く思い出` 选中详情态，最后一次实机输入仅为选中该卡，未点击 `SELECT`；该状态已被上方“五卡完整状态同进程采证成功”中的未选中 Round1 手牌页证据覆盖。
- 五卡压缩布局已修复窄标题 ROI、`話題沸騰鳴 → 話題沸騰` OCR 变体和底部手牌带之外 YOLO 伪框抑制；但批量详情探针仍会在中间卡标题确认处停止，普通手牌 OCR 也尚不能稳定命名全部五张。因此 `hand_names` 继续缺失，任何出牌仍必须安全停止。
- 下一步先实现“同一进程的详情标题映射 → 完整状态 → 唯一目标”受限路径，并为五卡布局、选中态映射、标题失败和零确认输入补测试；不要通过放宽 `hand_names` 门禁继续。

## 2026-07-15：Round1 数值重建与安全停止（最新）

本节覆盖下文“当前现场与禁止事项”中的旧选中态描述。当前画面为**未选中**的 Round1 手牌页；继续前仍先做只读截图与 Journal 审计。

- 已在同一 MuMu 原始 `720x1280` 帧中重建完整状态：`turn=7`、`good_condition=40`、`focus=4`、`reprise=2`、`stamina=30`、`flow=Vi`、`deck_size=21`。最终完整证据为 `debug/hif-journal/20260715T034021-44112.jsonl`；牌库探针的两次点击仅用于打开/关闭已验证的信息面板。
- 回合数字 `7` 使用 `assets/resource/base/image/produce/HIF/turn_digits/7.png` 的高置信模板兜底；好调和再演 ROI 已更新到 `assets/data/hif/roi_calibration.json`，并登记实机帧 SHA-256。普通数值读取改为三次中至少两次解析一致；三种冲突读数会保留缺失状态，不得执行。
- 新增 `--round1-state-observe`，隔离根路由为 `Round1Flag → Round1Action → Stop`。此前普通观察入口曾错误触发 `Click_1 (29,28)`；随后只读截图确认现场未变。新的隔离入口已实测 `controller_inputs=0`。
- 当前非灰手牌为 `天賦の才+` 与 `シュプレヒコール+`，灰色 `自然体の魅力+` 继续禁止执行。策略目前只返回“出好调卡”的泛化动作，未给出精确卡名；因此新增 `card_decision_target_not_explicit` 硬门，任何泛化动作均安全停止，禁止猜选。
- 下一步是先为这两个候选补充可复算的、卡名级决策规则及离线测试，再以完整状态重新观察；没有唯一精确目标、两段式确认和语义后验时，不得执行任何一张牌。

## 2026-07-15：Round1 实机推进与当前恢复点

本节总结任务 `019f6156-856d-7a91-81e7-c750f7c798d2`。它是当前恢复工作的权威入口；下文 2026-07-13～14 的停点仅作为历史证据，不再代表模拟器现状。继续前仍须先只读截图，并以当前画面、Journal、`PLAN.md` 和工作区 diff 交叉确认。

### 当前现场与禁止事项

- 当前局位于 Round1，最近可靠的未选中事故帧显示 `turn=7`、`flow=Vi`、`good_condition=40`、`focus=4`、`stamina=30`。
- 当前画面停在 `シュプレヒコール++` 的选中详情态，尚未进行绑定确认。详情页显示的 `good_condition=46 / focus=2` 是出牌预览值，不能写回当前状态。
- 当前实际手牌已逐张采证为 `自然体の魅力+ / 天賦の才+ / シュプレヒコール++`。用户确认灰色手牌表示当前无法打出；`自然体の魅力+` 当前为灰牌，必须保留识别证据，但不得成为任何出牌目标。
- 详情探针曾意外执行三张牌，导致 `reprise`、技能使用次数和牌库数量均已变化。旧的“首牌后 `reprise=0`”恢复规则已失效，禁止复用；在完整状态重建前不得确认 `シュプレヒコール++`，也不得切换并执行其他牌。
- 不得开启下一局、进行付费操作、提交 `debug/`、清理未跟踪资源、reset、push，或把当前实验入口当作连续自动出牌授权。

### 本次会话完成的实机进展

1. Day1 过渡至 Round1

   - 新增 `finals_ranking_transition` 双锚点（`現在順位`、`タップして次へ`）以及专用继续节点。
   - 扩大过紧 OCR ROI 后，实机仅点击一次底部提示并确认进入 Round1；证据目录为
     `debug/hif-live/hif-finals-ranking-goal-20260715-002/`。

2. Round1 初始状态和手牌采证

   - 初始手牌稳定识别为 `静かな意志+ / 至高のエンタメ+ / 始まりの合図+`；Journal 保留 YOLO 原始框、标签与置信度、OCR 原文与置信度、强化后缀及重叠伪框标记。
   - 只读牌库探针确认正确入口 ROI 为 `[519,1174,80,82]`，`deck_size=20`，OCR 原文为 `スキルカード(20)`、置信度约 `0.999133`。
   - 首回合完整状态为 `turn=9, flow=Vi, good_condition=6, focus=6, stamina=28, deck_size=20, reprise=0`；`reprise=0` 只在首回合 `turn == total_turns` 时按机制安全推导。证据为
     `debug/hif-journal/20260715T012316-33684.jsonl`。
   - 回合、流派、体力、好调、集中等 ROI 已写入校准数据；普通 OCR 对当前回合数字样式仍不稳定。

3. 两张预期卡的受控执行

   - `至高のエンタメ+` 采用“两段式绑定确认”：首次点击必须命中精确卡名、消耗和 `SELECT`，第二次才执行。稳定后验确认 `turn 9→8`、`focus 6→4`、`flow Vi→Vo`，目标离开手牌。即时采样落在抽牌动画时保守记录 `post_hand_not_readable`，后续零点击观察才确认成功。
   - 首牌后四张手牌稳定识别为 `仕切り直し+ / 自然体の魅力+ / お姉さんの感覚 / 鳴り止まない拍手+`；`仕切り直し+` 已加入仅识别词典，没有补猜测性策略元数据。
   - `お姉さんの感覚` 随后也通过绑定标题与 `SELECT` 的两段式确认执行。后验确认目标离开手牌；稳定观察得到 `turn=7, flow=Vi, good_condition=19, focus=4, stamina=30`，但普通 OCR 曾把画面中的 7 误读为 1，因此没有据此继续自动出牌。

4. 手牌详情探针事故与收口

   - `hif-round1-hand-detail-probe-20260715-001` 读取不存在的 `reader._card_dict` 后抛异常，MaaFramework 重复执行节点，产生 7 次左侧点击。
   - 逐帧证据证明实际顺序为：选中并执行 `スポットライト+`、选中并执行 `スリリング+`、选中并执行 `国民的アイドル+`，最后只选中 `自然体の魅力+`。事故未结束回合、未进入下一局，也没有付费操作。
   - 事故后加入独立卡名字典、探针前拒绝已有 `SELECT`、session 一次性锁、动作内异常转安全停止四项保护；后续未再发生重复点击。
   - 当前三张手牌详情证据：`debug/hif-journal/20260715T021109-14704.jsonl` 记录 `自然体の魅力+ / 天賦の才+`，`debug/hif-journal/20260715T021428-31988.jsonl` 以零控制器输入补录 `シュプレヒコール++`。

### 已落实的关键实现

- 新增排名过渡、Round 详情、手札信息确认、持有技能卡页面识别和只读牌库探针。
- 卡名 OCR 改读卡牌底部标题栏，支持 `+ / ++` 强化后缀；被完整高置信卡框覆盖的窄伪框记为 `overlap_duplicate`，不删除原始证据。
- 数值 OCR 使用有限重读；出牌后手牌落在动画中不可读时最多等待重读 4 次，不把帧变化当作成功。
- 出牌执行要求：Round 页面成立、目标唯一且可打出、首次点击命中精确标题与 `SELECT`、绑定二次点击、目标离开手牌且手牌集合发生语义变化。
- YOLO `useless` 标签已成为执行硬门：灰牌仍计入手牌存在和详情证据，但从默认目标、绑定确认及所有可执行目标集合排除。
- 运行器已包含 Round1 牌库探针、单牌实验和选中态恢复等显式开关；它们都必须与 `--single-step` 及对应状态门禁配合，不能用于无界连续执行。

### 验证基线

- 最新 HIF 门禁：`245 passed, 45 deselected`。
- `python tools/hif_pipeline_check.py`：`ok=true, issue_count=0`。
- 相关 Ruff 与 `compileall` 通过。
- 工作区仍有大量既有修改和无关未跟踪资源；本会话没有提交、stage 或 push。主要改动覆盖 `ProduceHIF.json`、`produce_hif.py`、HIF adapters/session/calibration、运行器、ROI/profile/observed case、技能卡目录和对应测试。

### 新会话的第一批操作

1. 只读截取当前 `720x1280` 原始帧，确认仍在 `シュプレヒコール++` 选中详情态；审计当前工作区 diff，禁止根据本节直接假定模拟器未变化。
2. 为已采证的 `turn=9/8/7` 建立数字模板或专用图像分类。零输入多 ROI 探针
   `debug/hif-journal/20260715T023353-45248.jsonl` 的 5 组候选均为空，不能继续依赖普通 OCR。
3. 根据详情证据、事故前后帧和牌库探针，重建当前 `reprise`、三张意外执行卡的技能使用次数及当前牌库数量；任何字段不能可靠恢复时保持安全停止。
4. 为上述恢复规则补成功与拒绝测试，并重跑 HIF 专项、Pipeline、编译、Ruff；随后重新做一次零点击完整状态观察。
5. 只有“完整状态 + 唯一非灰目标 + 两段式绑定 + 语义后验”重新成立后，才能决定是否确认当前 `シュプレヒコール++`。之后仍按一张一停推进 Round1，再分别验证 Interval、Round2 和最终结算。

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

## 2026-07-25：Day1 セレクトチェンジ数据阻塞

- 候选详情可稳定读到 `頂点へ / タフネス / プライド`，但三者不在 `skill_cards_master.json`；没有效果、标签或评分输入时只能记录并停止，不能以名称或槽位猜选。
- 当前首个源牌 `夏夜に咲く思い出` 的名称识别置信度为 `0.999865`，但效果 OCR 最低置信度仅 `0.087514`。它可用于名称绑定的临时页面链路，不能作为源牌效果评分依据。
- 正式接入前须补齐候选主数据、源牌全量枚举与可信效果解析，再以唯一评分决定 A/B；临时固定卡对不得进入正式路由。

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
