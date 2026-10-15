---
name: hif-manual-test
description: 规范 MaaGakumasu HIF 本战准备、课程、转场与 Round1 到达前的手动探索和正式单步测试。用于分析 HIF 日志或 Journal、补 Pipeline 状态节点/动作/测试、采集截图证据、安全复测 Day1 至 Round1 链路，或经用户授权批量推进対局回合（SKIP 循环）时使用。
---

# HIF 手动测试

用于可审计 HIF 测试。默认不控制设备；只有用户明确授权且满足单步前置条件，才通过正式 Maa 任务发送一次输入。

## 先建证据

1. 记录环境：游戏版本、语言、模拟器、分辨率、分支或提交、任务选项、`session_id`。
2. 从 Maa 日志和 `debug/hif-journal/<session>.jsonl` 提取：当前节点、页面、候选、决策、停止原因、控制器点击数。
3. 原始 PNG 和 Journal 只留 `debug/`。文档可记录相对路径和结论，但不复制证据文件进版本库。
4. 仅把正式 Maa Pipeline 的控制器日志、Journal、点击前后帧算作端到端证据；人工点击或独立 ADB 探测只算探索。

## 页面续接

从中途页面启动 `Produce` 时，先在 `ProduceLoop` 添加窄场景锚点，再进入既有 HIF 路由。不要用 `DirectHit` 直接进入 `ProduceEntryHIF`，否则主页或未知页会被误当成 HIF。

HIF 本战准备页标准链：

```text
ProduceLoop
  -> ProduceHIFFinalsPrepareResumeFlag
  -> ProduceChooseHIFEventFlag
  -> ProduceChooseHIFEventAuto
```

锚点必须确认“本戦/本战 + 剩余日数”；动作必须再次确认 `finals_prepare` 状态。任一字段缺失、候选为空、或页面不唯一，进入 `ProduceHIFUnknownStop`。

## 日程与执行模式

- `day_remaining=6` 是 Day1。
- 课程候选使用 OCR 和彩色角标分类为 `Vo`、`Da`、`Vi`。
- `HIF Day1课程` 只在 Day1 覆盖预设。目标课程不可见时停止 `configured_day1_lesson_not_visible`。
- `HIF执行模式=观测（默认）` 必须停止 `page_execution_mode_not_single_step`；它仍应记录决策和 `before` 截图。这不是识别失败。
- 仅 `HIF执行模式=单步执行（实验）` 允许一次点击。

复合单步仅适用于隔离测试中的无提交选择链路。变卡完整发现链为“枚举候选 → 临时进入牌库 → 浏览完整源牌库 → 取消返回候选 → 重选目标 → 次へ → 回放目标页 → 重选源牌”，终点必须停在 `チェンジ` 前。入口必须声明精确点击预算、顺序、终点与最终禁止点击的提交按钮；每次点击仍须有对应后验。不得把资源提交、确认或连续流程并入复合单步。

## 单步动作与截图

对每个不可逆页面动作：

1. 确认唯一页面、唯一目标、执行模式和用户授权。
2. 保存 `before`。
3. 发送一次点击，不得盲目双击或重试。
4. 保存 `selected`；若需要确认，再保存 `confirmed`。
5. 重新读取页面和关键字段。仅已知后态可通过；画面未变化、后态未知、截屏失败或点击失败均安全停止。

若 VS Code Agent 只提供不可导出截图句柄而无法产生帧指纹，默认仍停止。唯一例外是隔离测试中预先绑定精确名称的无提交选择点击：页面锚点仍成立且点击后 OCR 精确匹配该名称时，可将该 OCR 作为该次选择后验。记录 `image_type` 与例外原因；不得用于 `次へ`、源牌、提交按钮、决策路由或连续模式。

变卡等跨页选择先完成两份运行期快照：枚举候选，以临时选择进入牌库并浏览完整源牌库，再取消回候选页；纯函数或测试预设只在两份快照完整后选择卡对。执行层只消费槽位身份，重选候选、点击 `次へ`、回放源牌页并重新 OCR 复核。未知元数据、评分并列、槽位缺失或快照变化一律停止，不能继承机械回归中的槽位顺序兜底。

日程点击至少检查：目标候选、一次点击、帧变化、已知 HIF 后态。不要把“画面变化”单独当成功。

## 页面推进顺序

每页独立采证、建节点、建动作、建失败测试：

1. `finals_prepare`
2. `class_options`
3. `public_lesson_preview`
4. `public_lesson_result`
5. Day2 至 Day6
6. `finals_ranking_transition`
7. `round1`

Round1 到达后默认停止观察。除非用户另行授权且卡牌模型、目标绑定、后验和单步边界完整，不自动出牌。

## 対局快速推进循环（批量授权例外）

仅当用户明确授权批量推进（如"完成 Round2""快速推到结算"，且接受 0 分敗退）时使用；单步模式下仍遵循上文规则。循环模式（2026-08-20 実機验证，R1/R2 全程走通）：

1. **双锚确认待输入**：OCR `.*残りターン.*` roi [0,0,180,60] 命中 **且** OCR `.*SKIP.*` roi [600,770,100,60] 命中。演出/対手回合 SKIP 隐藏——「残りターン」标题常驻、`Round1Flag` 持续命中，单独不能当待输入判据。
2. **读状态**（可选记录）：残りターン数字 [35,60,50,50]（紧 ROI 必需，宽 ROI 分数掉到 0.45）、表盘类型+倍率 [100,40,130,90]、体力 [560,195,80,55]。
3. **推进**：SKIP 按钮 click (650,800)。SKIP=空过 1 回合+回复 2 体力（按钮内绿心+2 即此提示）；逐回合流行タイプ+倍率轮换（无 stage 串联）。
4. **轮询回现**：sleep 2.5 后 snap+OCR SKIP 锚，回现即下一回合；10 轮（约 25s）超时说明页面变化（Round 结束/弹窗），停下人工检查。
5. 模板脚本 `debug/autodev/r1_loop.sh`（不入库），每回合约 6-10s。
6. adb click `posted:true` ≠ 生效（偶发静默失效）：推进无变化时原坐标重试 1-2 次再怀疑坐标。

## 代码与验证

改 Pipeline 前读取 `pipeline-guide`；新增 UI 选项时读取 `pipeline-option`；需要从实时 OCR 生成节点时读取 `pipeline-generate`。

每次修改至少执行：

```powershell
python -m pytest tests/test_hif_pipeline_validation.py tests/test_hif_action_safety.py -q
python -m py_compile agent/custom/action/produce_hif.py
git diff --check
```

增加回归测试，覆盖：入口覆盖、页面锚点、执行模式安全闸、唯一目标、前后帧、未知后态停止。不要为绕过安全停止而放宽 OCR、扩大 ROI 或把未知页列为成功。
