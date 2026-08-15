# HIF 管线 Round1 阻断清单

**日期：** 2026-08-14
**状态：** ✅ 实机验证完成（2026-08-15 凌晨，MuMu 720×1280 竖屏）；✅ 决策升级复验完成（2026-08-15 下午，关键词评分制全程驱动 Day1→Round1）
**结论：** ~~HIF 管线当前无法到达 Round1~~ → **已到达 Round1 并停在观察终点**（`ProduceHIFRound1ReachedStop` 实机执行，00:06:45；下午会话再次到达）。

## 2026-08-15 实机验证总结（Day1 中续接 → Round1 全链打通）

| # | 原阻断项 | 处置结果 |
|---|---|---|
| 1 | Round1Flag 推测文案 | ✅ 页面无"Round 1"字样；实测锚=「残りターン」box [10,7,100,25]，ROI 修正为 [5,0,180,60]（比日志记录偏上） |
| 2 | SelectionMode/FinalMode 推测 | ✅ 全程未出现（实机链：选剧本→アイドル選択→開始確認→Day1，无模式页）；节点保留在准备段待后续观察，FinalModeButton 坐标未用 |
| 3 | 难度 override 横屏坐标 | ✅ 已由 `26338e5` 提前修复（DirectHit+DoNothing 直入路由），本次实机复验通过 |
| 4 | GenerationFlag 文案 | ✅ 已删除节点（死代码+文案矛盾，结算流程归 MemoryFlag 记录后停） |
| 5 | 日程双击误触 | ✅ 双击=选中+执行，实测无害且正好覆盖「选中→预览→确认」两步交互 |
| 6 | 体力横屏 ROI | ✅ 已改竖屏 override [285,16,150,85]，实机读取正常（35/35→22/35 等多值验证） |
| 7 | 牌库小字 OCR | ✅ SourceAuto 改「预设优先+第一格回退」，不再依赖小字卡名精度 |
| 8 | reroll_limit 语义混淆 | ✅ 已拆分 select_change(3)/reward(2)，实测両场景次数与日志一致 |
| 9 | cards.onnx 分布 | ⏳ Round1Observe 读牌执行成功（good_condition_cards=0），同分布性待样本积累 |
| 10 | _NUMERIC_ROI 占位 | ⏳ 代码安全跳过路径验证过，字段校准待 Round2 阶段 |

**本次新发现并已修复（管线演化记录）：**

- maafw `post_screencap` 返回 **BGR 序**（非 RGB）——色扫描需翻转通道
- 授業候选识别改**两步法**：渐变带定位卡片列+扇形平均色分类 Vo/Da/Vi（模板法对纯色小图标区分度不足，实测 0.55-0.65）
- EventFlag 锚改 **OCR「H.I.F本戦まで」倒计时面板**（渐变模板是全局 UI 风格，事件页选项按钮同款渐变 0.93 误中；初培育 chat/lesson 等模板也在 HIF 页面 0.72+ 误中，均已移除）
- ClassOptionFlag 锚改 **「授業/おでかけ」标题**（选项文案随事件而变不可穷举，メンタルケア事件文案与日志完全不同）；选择策略=好调文案优先+first_safe（首个非トラブル、含≥2日文字符）回退
- 新场景 **SP 课程效果选择页**（公開レッスン后，点卡即执行）→ `ProduceHIFSPCardFlag`
- 新场景 **通信エラー弹窗**（リトライ [521,1157] 人工恢复；管线未覆盖，待节点化）
- 饮料上限页：标题**全角Ｐ**「Ｐドリンク所持上限」（expected 需字符类 [PＰ]）；勾选框在**行右侧 x≈493**；点击=切换勾选（收敛算法：remain 下降保留/上升撤销+滚动轮）

## 2026-08-15 下午遗留（决策升级会话，详见 finals-daily-log.md 同日节）

| # | 项 | 状态 |
|---|---|---|
| 11 | 相談商店「終了」按钮 finish_button_not_found 一次 | ⏳ 根因未查（后续轮次流转过） |
| 12 | Day5 上限页勾选框 x=620 布局变体 | ⏳ x 自适应已加仍失败一次；灰描边/橙实心两种勾选态语义待建模 |
| 13 | ClassOptionFlag 转场竞态（残留授業标题误命中） | ⏸ 顺序+防重复守卫缓解，锚特异性根治待做 |
| 14 | SP效果卡页=Pドリンク 列表选择（证实） | ✅ 关键词评分选择实机生效（选中初星ブーストエナジー） |
- Round1 前有**开场对白页**（「いよいよ、本戦がはじまるな」点空白推进，本次人工辅助，待节点化）
- `_stop_unknown` 改 `return False`（`run_task(UnknownStop)` 只停子任务流，父管线会继续轮询）
- 变卡/饮料/技能卡预设未命中时**回退策略**（第一候选/第一瓶/第一格）——首版推进优先

**遗留待节点化（下版）：** 通信エラー自动恢复、Round1 前对白页点空白、変卡完成页锚实测、公開レッスン结算页 KnownNextButton 实测。

---

以下为原始清单（留档）：

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
