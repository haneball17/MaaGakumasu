---
name: pipeline-autodev
description: 无人工介入的 MaaFW 管线开发调试循环。当用户要求"用 autodev 给某页面做节点/补识别/调管线"，或需要自主探索游戏页面、裁模板、生成节点、实机连测并出证据报告，以及"再跑一轮/复验一轮/验证修复"类整局実機验证时使用。以五角色循环（感知/执行/反思/记录/管理）驱动，坐标由 OCR/模板/YOLO 出框、视觉模型只选编号，危险操作同步等用户确认。
---

# pipeline-autodev：无人化管线开发调试循环

主 agent 是编排器。工具：`tools/maa_dev.py`（原子 CLI，见 `--help`）+ MaaMCP MCP server
（仓库 `.zcode/config.json` 注册，下会话直连；本会话用 CLI/库形态）+ 本 skill 固化流程。

## 坐标裁决分层（铁律：视觉模型永不直接产出点击坐标）

2026-08-20 校准（19 要素，OCR box 真值）：vision-qwen 裸坐标中位误差 26px、最大 81px、
32% 超 40px，且存在同形文本混淆（メモリ/メモ）。系统性偏移弱（dx+12/dy+8），常量修正无收益。

1. **文本 UI**：`maa_dev.py ocr` 拿全量 box → 需要语义选择时 `maa_dev.py som` 生成编号叠加图
   → vision-qwen 只回答编号 → 坐标取对应 OCR box 中心。
2. **图标/图像 UI**：已有模板用 `reco --type TemplateMatch`；卡牌区域可用 NeuralNetworkDetect
   （cards.onnx）；候选框同样走 SoM 选编号。
3. **兜底**（1、2 都无候选时）：两阶段 crop-zoom——vision-qwen 粗判区域 → 裁剪放大 → 二次判读
   → 仍需落到具体像素时用该区域内的 OCR/模板精定位。
4. 每次在线点击后截图对比，三态判定：成功（预期页面）/进错页（回退）/无变化（重试或换目标）。

## 五角色循环

对每个开发目标（一个节点或一段流程）：

1. **感知 Perceive**：`snap` 截图（或 MCP screencap）→ `ocr` 全量 box → 需要语义分类/枚举时
   派 vision-qwen（带 720x1280 或 1280x720 基准说明；竖屏 HIF 是 720x1280）。
   页面路由判断必须 OCR 锚点复核，不信视觉单源结论。
2. **执行 Operate**：
   - 模板素材：`crop`（自动登记 manifest：来源截图/box/日期/分辨率）。
   - OCR 节点：`.agents/skills/pipeline-generate/generate_sweep.py` 选 ROI 扩边 + `generate_node.py` 写入。
   - 节点设计与接线规范：遵循 pipeline-guide skill（v2 格式、next 状态机、[JumpBack]）。
   - 模板即时验证：`reco --type TemplateMatch --param '{"template":["autodev/xxx.png"]}'`。
3. **反思 Reflect**：`test-node <节点> --n 3` 实机连测（需设备）。三态判定看 runs[].status 与
   before/after 截图。失败进修复阶梯（见下）。
4. **记录 Note**：每个关键动作 `journal '{"event":"...","node":"...","hit":true}' --run-id <id>`
   落 `debug/autodev/<run-id>/journal.jsonl`；证据截图由 test-node 自动落盘。
5. **管理 Manage**：主 agent 自身——连续 2 次同类失败即升级（换方案重规划），不再原样重试。

## 护栏（超限即停，落盘失败证据，禁止猜测性点击）

- 预算：单节点 5 次重试 / 15 分钟；单会话实机总时长 90 分钟。
- 三重终止：最大迭代 40 / 连续错误 3 / 连续重复同一动作 3。
- **危险操作白名单**（探索导航时遇到，先 AskUserQuestion 同步确认，绝不明点）：
  扭蛋、购买、确认弹窗（決定/購入/実行类）、体力药使用、开战/供奉、任何"消耗性/不可逆"按钮。
  HIF 生产管线红线不变：未知页面 ProduceHIFUnknownStop。
- 回滚：会话开工前确认在专用分支（如 feat/pipeline-autodev），节点级改动可 `git checkout -- <file>` 单独回退。
- 设备前置：MuMu 未启动/adb 无设备 → 停止并报告，不重试连接超过 2 次。

## 修复阶梯（诊断优先，防"假通过"）

失败先归类再修，每次修复后必须重跑 `test-node` 验证：

| 诊断 | 症状 | 修复 |
|---|---|---|
| Timing | 偶发 miss、动画中 | 加 pre/post_delay、post_wait_freezes、重试 |
| 模板漂移 | score 在阈值边缘 | 放宽 threshold（0.7→0.6）→ 重截模板（crop）→ 换 FeatureMatch/OCR |
| OCR 词表 | 文字识别但节点 miss | expected 补变体（`tools/hif_mine_ocr_variants.py`） |
| 缺前置 | 节点本身好但到不了 | 补导航节点/修 next 接线 |
| ROI 侵占 | 误命中相邻元素 | 缩 ROI（sweep 重选） |

## 单驱动原则（避免抢控制器）

在线操作（探索循环、test-node）与离线分析分通道：
- MCP server 在线时：在线操作优先走 MCP 工具（持久连接）。
- MCP 不可用（本会话）：`maa_dev.py` 短连接即可，但**不要**同时跑两个会话各持一条连接操作同一设备。
- `ocr/reco/replay` 是离线命令（stub 控制器），随时可与在线操作并存。

## 分段接力与死循环排障（长流程実機验证，2026-08-22 五轮验证沉淀）

长流程（整局培育 30-60 分钟）不追求单段跑通，用**分段接力**：每段 `hif_run.py --entry <路由根> --timeout <s>`，
段退出（DONE/UnknownStop/超时皆可）后由 `debug/autodev/segment_loop.py` 判画面（snap+OCR 找终点锚）→
未到终点自动发下一段。段退出≠失败——LOADING/长动画窗口内 next 全 miss 走 timeout 是正常模式，
接力重启即恢复。

**分段单例纪律**（違反即双段互踩：画面来回跳变/状态数震荡）：
- 同一模拟器同时只跑一个段；后台段一律输出落文件（`>/dev/null &` 吞输出=段存活不可见）。
- 重启段前清进程：`Get-CimInstance Win32_Process -Filter "name='python.exe'"` 按 CommandLine 匹配
  `*hif_run*` 与 `*agent*main*` 全杀——`taskkill /T` 杀 parent 常漏 agent 孙进程，孤儿 agent 是下一段隐形干扰。

**死循环排障链**（症状：agent 日志静默、无 timeout 无报错、画面不动）：
1. 查 `debug/maafw.log` 节点事件流（`grep -a 'Succeeded' | tail`）——最后**连续命中同一节点**=元凶；
   agent 日志静默≠没在跑。
2. 根因模式几乎总是：泛词锚（页面残留标题词：獲得/差し入れ/本戦类）在同类子页面命中 +
   裸点击无效 + `[JumpBack]` 回环**命中即重置轮询、永远走不到 timeout**=无限空转不报错。
3. 修复（系统性，不打地鼠）：泛词锚挂路由尾部队兜底位或换专有词；空白点击类推进节点换
   `ProduceHIFGuardedTapAuto`（锚验证→指纹对比→点击→验证推进，连续 3 次无变化 return False 段退）。
   节点设计三问：这个词在哪些**其他**页面也出现？点击无效时谁兜底？回环会不会吞 timeout？

**操作可追溯与超时层**（agent 侧已固化，新 Custom 直接复用）：
- 全点击/滑动/按键走 `_tap/_swipe/_key`（坐标+操作后截图 `debug/decisions/ops/` + ops JSONL 前后指纹
  对比），禁直调 `controller.post_*`——IPC 点击静默丢失的归因全靠此链。
- `Job.wait()` 无限阻塞是 maafw 接口事实：`_wait_job`（done 轮询 15s）已包装；长循环（出牌/全库扫描）
  必须带全局 deadline。

## 轮驱动验证（整局実機稳定性验证，2026-08-22 轮 6-7 沉淀）

「再跑一轮/复验一轮/验证修复」类请求：一轮 = 环境三件套 + 入口段 + 主线 segment_loop 段接力 +
量化统计 + 复盘六件。累计 7+ 轮实证（轮 4-7 主线零介入）。

1. **环境三件套**（开工必查，顺序固定）：
   - `adb devices`——MuMu adb 在 `E:\game\MuMu\nx_device\12.0\shell\adb.exe`，端口跨会话漂移先查再连；
   - python 残留：`Get-CimInstance Win32_Process -Filter "name='python.exe'"` 按 CommandLine 匹配
     `*hif_run*`/`*agent*main*` 清光（maa-mcp 常驻不算）；
   - `maa_dev.py snap` + OCR 判画面：干净主页面=理想起点，有在途局先问用户处置。
2. **入口段**（手动 backlog，坐标链两轮实测稳定）：プロデュース(360,997)→本戦(550,890)→
   次へ(367,1078)→プロデュース開始(370,1113)；開場コミュ SKIP(217,1212)（出现频率不定）；
   通信エラー リトライ(522,1165)（设备级偶发，重试后服务端已受理直达 Day1）。
   每步 `adb shell input tap` → sleep 3-6 → snap → OCR 验证推进（posted≠生效铁律；
   点击丢失原坐标重试 1-2 次）。
3. **主线段驱动**（run_in_background，一轮约 6 段 31-48 分钟；单段超时被接力无损接管是正常模式）：
   ```bash
   MAA_DEV_ADDR=127.0.0.1:<port> HIF_RUN_CHOICES='{"Round1 出牌":"Yes"}' \
     .venv/Scripts/python.exe -u debug/autodev/segment_loop.py \
     --segments 12 --tag round<N> --timeout 900 > debug/autodev/round<N>_loop.log 2>&1
   ```
4. **周期监控**（≤290s 间隔；Bash 调用记得设 timeout 参数防 120s 默认截断）：
   - `tail debug/autodev/round<N>_loop.log`——段进度+每段起止画面签名；
   - 决策 JSONL tail：`debug/decisions/session-<date>.jsonl` 末 3-5 条（screen/action/chosen/reason）；
   - 当前段 agent 日志 `debug/hif-live/agent-subprocess.log` grep 自愈标志（如「turn 读空但画面在动」
     「检出変卡弹窗」）——**该文件按段 "w" 重写，只反映当前段**，跨段统计去决策 JSONL/maafw.log。
5. **量化统计**（轮结束）：**时间窗过滤必须用 `ts[:5]`**（ts 是纯 'HH:MM:SS'，与日期串比较恒 False/
   恒 True——実機轮 7 假结果 0 条教训）；统计前先打印首末条记录验证字段格式，结果与监控观察矛盾
   先怀疑过滤器。指标：决策数/出牌手数/stop 分布（screen+reason 逐条归因：段边界瞬态 vs 真异常 vs
   误入）/ops `scene_changed` 全 True 率/段数/总时长。
6. **复盘六件**：bug 编号先 grep 占用（编号会被代码注释占用，如 bug#44）→ 修复（agent/管线层，
   优先模式级系统性解法）→ 回归（pytest 七件套 215 基线：hif_decision/play_decision/exam_reader/
   scoring_model/five_round_readers/change_source/session_state）→ 文档（验证报告加轮节+遗留清单
   增量）→ commit（Conventional Commits，Conventional 风格参照仓库近史）→ 记忆更新。
   步骤明细落 `debug/autodev/round<N>-steps.md`（时间线/量化/证据路径，不入库）。

## vision 先行诊断（2026-08-22 五轮验证 ≥6 次实证）

実機停滞/新页面/点击无效时，**先派 vision 子智能体读图，再用 OCR/日志补充**——不要只用 OCR+grep 推理。
实证对比：毛玻璃面板遮挡（#34）、pill 按钮 hitbox 内缩（#35）、面板关闭按钮位（#41）三类问题 vision
一次定位，纯 OCR 推理各绕 2-3 轮。

流程：
1. `snap` 截图 → 派 vision-qwen（子智能体）读图，问四件事：**页面结构**（什么面板/弹窗/遮挡，边界在哪）、
   **可交互元素**（按钮形状/颜色/可点击区 x-y 范围——注意 pill 形按钮 hitbox 与 OCR 文字 box 不同）、
   **异常状态**（灰化/禁用/加载中/毛玻璃）、**推进方式**（点哪里/关闭按钮在哪）。
2. vision 结论与 SoM 铁律不冲突：vision 给的坐标只做参考，**精确点击坐标仍取 OCR/模板检测框**
   （或 vision 指认后用 OCR box 复核）；选择类交互走 SoM 编号叠加图。
3. OCR 补文字细节（卡名/数值/标题词），maafw.log 节点事件流定位循环元凶——三者互补，vision 负责
   「看不见结构」类问题（遮挡/形状/布局），OCR 负责「读得到文字」类，日志负责「谁在循环」。
4. 修复后落 ops 留痕；同类问题第二次出现提系统性方案（守卫/管线层节点/几何中心），不打地鼠。

典型问题→vision 一次定案清单：全屏遮挡类（毛玻璃面板/演出动画）、按钮点不动（hitbox 内缩/灰化/
坐标偏上）、画面冻结（两帧像素 diff=0 判 Unity 卡死）、未知页面首见（元素清单+推进方式）。

## 验收（一个节点/流程"通过"）

1. `test-node --n 3` 全中（3/3）。
2. 改动涉及存量节点时跑 `replay`（基准集见 debug/autodev/replay-suite/ 或 M5 建立的集）。
3. 静态：`python -m pytest tests/test_maa_dev.py`（工具纯函数）+ `python tools/ci/check_resource.py ./assets/resource/base/`。
4. JSON 格式：`npx prettier --check`（新改的 pipeline 文件）。
5. 证据归档：journal + test-node evidence_dir + 总结报告（写入 `debug/autodev/<run-id>/report.md`）。

## 产出物约定

- 模板图：`assets/resource/base/image/autodev/<name>.png` + 同目录 `manifest.json` 登记。
- 新节点：写入对应功能 pipeline 文件（HIF → ProduceHIF.json），命名 PascalCase，遵循现有排序。
- 会话产物：`debug/autodev/<run-id>/`（journal.jsonl、report.md、证据截图），不入库。
