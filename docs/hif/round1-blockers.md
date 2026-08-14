# HIF 管线 Round1 阻断清单

**日期：** 2026-08-14
**状态：** 待实机验证（MuMu 720×1280 竖屏）
**结论：** HIF 管线（`ProduceHIF.json` + `produce_hif.py`）当前**无法到达 Round1**。路由骨架完整、模板图零缺失、测试全过，但关键 OCR 文案、ROI 和点击坐标从未在实机验证，其中 4 项为流程阻断级。

本文档是实机验证 checklist：连 MuMu 后按"截图采集清单"逐项取证，回来对照修改。

## 一、阻断级断点（不修必卡死）

### 1. ProduceHIFRound1Flag 的 OCR 文案是推测的

- **位置：** `assets/resource/base/pipeline/ProduceHIF.json` `ProduceHIFRound1Flag`
- **当前值：** expected `.*Round\s*1.*` / `.*ROUND\s*1.*` / `.*1st.*Round.*`，ROI `[40,40,640,220]`（画面顶部）
- **问题：** `finals-daily-log.md` 的 Round1 截图记录只显示左上"残りターン 9 / ビジュアル 3807%"，**未记录顶部有"Round 1"字样**。若实机无此字样，本 Flag 永不命中 → 永远到不了 `ProduceHIFRound1ObserveFlag`，首版目标直接失败。
- **需要：** Round1 开局整页截图（720×1280），确认画面上的回合指示元素及其文案。
- [ ] 已取证：Round1 开局顶部实际文案 = ______________
- [ ] 已按实测修正 expected / ROI

### 2. SelectionMode / FinalMode 两个 Flag 的文案是推测的

- **位置：** `ProduceHIF.json` `ProduceHIFSelectionModeFlag` / `ProduceHIFFinalModeFlag`
- **当前值：**
  - SelectionMode：expected `.*選抜試験モード.*` / `.*選抜試験.*`，ROI `[40,40,640,220]`
  - FinalMode：expected `.*本戦モード.*` / `.*本戦.*`，ROI `[40,40,640,220]`
- **问题：** 日志完全没记录这两个模式判定页。且 `.*本戦.*` 宽泛正则可能误命中日数面板"H.I.F本戦まで"（该面板在 `[40,40,640,220]` ROI 内），导致路由误判页面。
- **需要：** 选拔模式页、本战模式页整页截图各一张，确认顶部标题文案。
- [ ] 已取证：选拔页顶部文案 = ______________
- [ ] 已取证：本战页顶部文案 = ______________
- [ ] 已修正 expected（含去除误命中风险）

### 3. ProduceChooseDifficulty override 硬编码坐标是推测的

- **位置：** `agent/custom/action/produce_hif.py` `ProduceHIFChooseFinalModeAuto.FINAL_MODE_BUTTON`
- **当前值：** `[360, 824, 360, 171]`，点击中心 (540, 909)
- **问题：** 坐标推测自原 MASTER 按钮 ROI（横屏时代位置），日志无本战模式选择页截图。点错位置 → 进不了本战。
- **需要：** 本战模式选择页截图，确认"本戦"按钮的实际 box。
- [ ] 已取证：本戦按钮实际 box = ______________
- [ ] 已修正坐标

### 4. ProduceHIFGenerationFlag 文案与实测不符

- **位置：** `ProduceHIF.json` `ProduceHIFGenerationFlag`
- **当前值：** expected `.*メモリー生成.*`，ROI `[260,900,200,120]`
- **问题：** 日志记录的回忆生成界面是"MEMORY"标题 + "生成"按钮（`[275,900,170,170]`）两个分离元素，不存在"メモリー生成"连续文案。回忆生成页可能识别不到。
- **需要：** 回忆生成页截图。
- [ ] 已取证：页面实际文案 = ______________
- [ ] 已修正 expected / ROI

## 二、策略失效级（不卡死，但行为错误）

### 5. 日程选择默认双击

- **位置：** `produce_hif.py` `ProduceChooseHIFEventAuto._execute_event`（`_click_box_center` 默认 `double=True`）
- **问题：** 日志记录日程候选是单击进入；双击可能在进入后立即误触下一层。
- **需要：** 实机观察双击日程候选的实际效果；若误触，改 `double=False`。
- [ ] 已验证行为：______________
- [ ] 已修正

### 6. 体力识别 ROI 是横屏坐标

- **位置：** `ProduceUtils.json` `ProduceRecognitionHealth`（ROI `[276,56,170,50]`），被 `produce_hif.py` `_get_health` 调用
- **问题：** 该 ROI 是横屏 NIA 流程的体力位置；HIF 竖屏日志体力在 `[285,16,150,85]`。后果：读不到体力 → 兜底 34/34 → 低体力优先おでかけ分支永不触发。
- **需要：** HIF 日程页截图确认体力显示位置；HIF 应改用独立 recognition 节点，不能复用横屏 ROI。
- [ ] 已取证：HIF 体力实际 box = ______________
- [ ] 已为 HIF 增加独立体力识别并接入

### 7. セレクトチェンジ牌库 OCR 读小字卡名

- **位置：** `produce_hif.py` `ProduceChooseHIFSelectChangeSourceAuto`（DECK_ROI `[60,600,600,500]`，找"大胆不敵""始まりの合図"）
- **问题：** 牌库卡牌缩略图约 118×118，卡名文字极小，OCR 能否稳定读出未验证。读不出 → 找不到源卡 → StopTask。
- **需要：** 牌库展开页截图，放大验证卡名可读性；必要时改用模板匹配定位源卡。
- [ ] 已验证 OCR 命中率：______________
- [ ] 已修正（如需）

### 8. 变卡 reroll 次数与游戏不一致

- **位置：** `agent/hif/presets.py` `reroll_limit=2`
- **问题：** 日志 Day1 显示"あと3回"（实际可重抽 3 次），预设只重抽 2 次，少 1 次机会，可能选不到目标卡。
- **需要：** 确认实机重抽次数是否恒为 3；若恒为 3，预设改 3。
- [ ] 已确认实机次数：______________
- [ ] 已修正

## 三、观察级（Round1 到达后）

### 9. cards.onnx 在 HIF 手牌上的检测效果

- **位置：** `ProduceUtils.json` `ProduceRecognitionCards`（model `cards.onnx`，已确认存在于 `assets/resource/base/model/detect/`）
- **问题：** YOLO 训练样本来自初培育出牌画面，HIF Round1 手牌区（日志 `[49,884,190,248]` 等 3 张）是否同分布未验证。
- **需要：** Round1 开局截图跑一次检测，核对 3 张手牌 box。
- [ ] 已验证：检测到 ___ / 3 张

### 10. _NUMERIC_ROI 全占位

- **位置：** `agent/hif/adapters/exam_reader.py` `_NUMERIC_ROI`（7 字段全 `(0,0,0,0)`）
- **问题：** 已知占位，代码安全跳过。首版观察任务不依赖数值（手牌元数据靠 YOLO labels），但后续出牌闭环的前置。
- **附带问题：** 该文件注释写"1280×720"，HIF 实际 720×1280 竖屏，坐标系描述需更正。
- [ ] 已校准 7 字段 ROI（出牌闭环阶段做）

## 四、已确认项（日志核实过，大概率直接通过）

以下节点文案与 ROI 均有 `finals-daily-log.md` 实机记录支撑：

| 节点 | 文案 | 日志 ROI | 管线 ROI |
| --- | --- | --- | --- |
| ProduceHIFClassOptionFlag | 余裕です！/長い道のりでした | 选项 y∈[658,953] | `[40,620,640,360]` ✅ |
| ProduceHIFDrinkRewardFlag | 受け取るPドリンクを選んでください | `[145,620,430,45]` | `[80,560,560,180]` ✅ |
| ProduceHIFSkillRewardFlag | 受け取るスキルカードを選んでください | `[132,588,456,44]` | `[80,560,560,180]` ✅ |
| ProduceHIFRewardConfirmFlag | 受け取る | `[230,1052,260,84]` | `[200,1000,320,150]` ✅ |
| ProduceHIFSelectChangeTargetFlag | チェンジで獲得するスキルカードを選んでください | `[84,292,545,42]` | `[60,260,600,110]` ✅ |
| ProduceHIFSelectChangeSourceFlag | チェンジするスキルカードを選択してください | `[100,579,520,42]` | `[80,540,560,110]` ✅ |
| ProduceHIFConsultFlag | Pポイントと交換するものを選んでください | `[124,299,470,40]` | `[100,250,520,120]` ✅ |
| ProduceHIFPublicLessonResultFlag | 公開レッスン | `[32,36,160,105]` | `[20,20,340,140]` ✅ |
| ProduceHIFDrinkOverflowFlag | Pドリンク所持上限 | `[58,96,330,50]` | `[40,70,400,100]` ✅ |
| ProduceHIFIntervalFlag | インターバル | `[32,25,160,145]` | `[20,20,360,150]` ✅ |
| ProduceHIFScoreSettlementFlag | 優勝 | `[30,30,150,85]` | `[20,20,240,160]` ✅ |
| ProduceHIFMemoryFlag | MEMORY / メモリー | 日志已确认 | `[20,120,680,220]` ✅ |

模板资源核查：管线与 action 引用的 23 个 png 模板全部存在；`cards.onnx` 存在。**零缺失**。

## 五、截图采集清单（连 MuMu 后按序执行）

按解锁阻断项的价值排序，每张需 720×1280 原始分辨率：

| # | 目标页面 | 解锁断点 | 备注 |
| --- | --- | --- | --- |
| 1 | 本战模式选择页（进 HIF 后首个选择点） | #2、#3 | 同时确认按钮位置和顶部文案 |
| 2 | 选拔模式判定页顶部 | #2 | 若与 1 同页则合并 |
| 3 | Round1 开局整页 | #1、#9 | **首版成败关键** |
| 4 | 回忆生成页 | #4 | MEMORY 标题 + 生成按钮 |
| 5 | 日程页（带体力显示） | #6 | 体力数字位置 |
| 6 | 牌库展开页（セレクトチェンジ源卡） | #7 | 验证小字卡名可读性 |
| 7 | 公開レッスン结算页"次へ"按钮 | 已确认项复核 | 当前 ROI 为推测 |

## 六、背景说明

- 管线骨架（28 节点路由 + 10 个 CustomAction）逻辑完整，测试 66 passed。
- 修改规范见 `AGENTS.md`：`ProduceHIF.json` 只做高置信路由，action 校验预设后单步点击，未知一律 `ProduceHIFUnknownStop`，禁止猜测性点击。
- 实机测试方法参考 `.agents/skills/hif-manual-test/SKILL.md`。
