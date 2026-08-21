# Round1 出牌管线集成计划

- 日期：2026-08-21
- 状态：已裁决待执行（grilling 两轮 15 项决策全确认，実機 Round1 界面待命）
- 前置：Round1 观察链已通（cbae402，`Round1Flag→Observe→ReachedStop`）；出牌策略 `GarakutaRinamiStrategy`（`agent/hif/decisions/play.py`）已实现含 26 测试，**本计划不动决策模块本身**。
- 范围：补全决策模块以外全部缺口（缺口清单 A–I，见 `AGENTS.md` 与本文「缺口索引」），达成一局完整 9 回合自动出牌，到 Interval 入口安全停止。

## 目标与边界

**做**：実機取证（A）、识别适配（B）、状态装配（C）、会话状态（D）、pipeline 节点（E）、执行层（F）、任务选项（G）、测试（H）、文档（I）。

**不做**：出牌策略逻辑改动；Round2 / Interval / 结算 / メモリー 实现（保持 `ProduceHIFUnknownStop` 兜底语义）；评分模型调整。

## 已裁决决策（15 项）

| # | 决策点 | 裁决 |
| --- | --- | --- |
| 1 | 取证驱动 | autodev（`tools/maa_dev.py`）由 agent 驱动，逐步 snap→OCR→click，每步落盘 |
| 2 | 禁区边界 | 仅「菜单/退出/中断」类按钮禁点；未知弹窗先 OCR/vision 自助理解后可直接点击，**不找用户确认** |
| 3 | 取证期出牌 | dry-run：snap→组装 `ExamState`→跑策略出建议→按建议点 |
| 4 | 本局节奏 | 全程 9 回合逐步取证，每回合出牌前后各 snap+OCR |
| 5 | 模式开关 | 任务选项「Round1 出牌」默认关（保持观察停止现状），开发期 override 打开 |
| 6 | 真值源 | 画面优先：turn/好調/集中/体力/flow 以 OCR 为准；session 只存画面外字段（`oneesan_used`/`cards_played`/`reprise_count`）；冲突信画面+告警+保守重置 |
| 7 | Round1 出口 | 打完 9 回合→結果页→`TapNextFlag`→中盘順位→Interval 入口触发 `ProduceHIFUnknownStop` |
| 8 | 验收标准 | 一局完整 9 回合自动出牌（turn 对齐残りターン 9→0、每回合决策落盘、无中途 UnknownStop）+ 回归全绿 + 新单测 |
| 9 | P 饮料 | 取证局一律拦截（只记录不执行）；验收局真点 |
| 10 | 阶段顺序 | Phase 0 取证 ∥ Phase 1 纯代码 → Phase 2 管线 → Phase 3 单节点连测 → Phase 4 验收局 → Phase 5 回归+文档 |
| 11 | 节点架构 | 单 Custom action 大包（`ProduceHIFRound1Play` 内联读→决策→点→验证→落盘），pipeline 只做路由 |
| 12 | 点击失败 | 原坐标重试 2 次→仍失败 `UnknownStop`；`evidence_empty`（手牌读不出）直接停，禁止盲点 |
| 13 | 转场窗口 | 出牌后等新回合单窗口 60s 超时停；Phase 0 实测动画时长后收紧为实测×2 |
| 14 | 取证局复用 | 前 2–3 回合手动取证，素材足够即切新管线实跑剩余回合；切不过去则手动走完，不阻塞取证 |
| 15 | 弹窗名单 | 白名单（はい/OK/確認/閉じる/タップして次へ/次へ）直接点；黑名单语义（購入/ガチャ/消費/リタイア/中断 + 资源数字）`UnknownStop`；两者不沾→vision 理解后点 |

## 缺口索引与阶段映射

| 缺口组 | 内容 | 阶段 |
| --- | --- | --- |
| A1–A5 | 実機取证：出牌交互流程 / 数值 ROI / SKIP ROI / 山札可读性 / P 饮料栏 | Phase 0 |
| B1–B6 | exam_reader：坐标基准 / flow 日文映射 / P 饮料解析 / 好调判定 / OCR 变体 / 体力归属 | Phase 1（B5 実機后） |
| C1–C3 | 装配：跨回合字段注入 / reprise 来源 / read_exam_state 调用方 | Phase 1 + Phase 2 |
| D1 | session-state Round 局内字段 | Phase 1 |
| E1–E4 | pipeline：Play 节点 / 转场锚 / 出口路由 / 残りターン判定 | Phase 2 |
| F1–F4 | 执行：点击验证 / 卡名→box 点击 / 落盘 schema / 循环守卫 | Phase 0（F3 schema）+ Phase 2 |
| G1–G2 | 任务选项「Round1 出牌」 | Phase 2 |
| H1–H3 | 单测 / 会话测试 / replay 回归 | Phase 1 + Phase 5 |
| I1 | 文档更新 | Phase 5 |

## Phase 0 実機取证（当前局，autodev 驱动）

### 准备

1. `adb devices` 发现 MuMu 实际端口（跨会话漂移，不假设 16416），`MAA_DEV_ADDR` 注入。
2. 首屏 snap 验证当前确在 Round1 対战页（残りターン锚），记录本局初始状态（手牌 3 张、体力、好調/集中）。
3. 取证目录：`debug/autodev/round1/`（不入库），命名 `turnNN_<step>.png`。

### 每回合取证循环（9 回合逐步，dry-run）

每回合执行以下步骤，全部落盘截图 + JSONL：

1. **pre-snap**：全屏 `turnNN_pre.png`。
2. **数值 ROI 校准**（A2）：逐项 OCR 残りターン `[13,43,120,128]`、体力 `[553,204,115,55]`、好調/集中 `[14,237,88,360]` 带内、表盘属性 `[101,74,125,47]`；记录 OCR 原文与解析值，9 回合形成校准样本集（含好調/集中衰减轨迹）。
3. **手牌读取**：跑 `ProduceRecognitionCards`（YOLO）+ 每框卡名 OCR（框底 84%–100% 带），记录 box+卡名+label。
4. **dry-run 决策**：手动组装 `ExamState`（Phase 1 未落地前临时脚本，落地后走新链路）→ `GarakutaRinamiStrategy.decide()` → 记录 `CardAction`（kind/target_card/reason）。
5. **执行**：`PLAY_CARD` 点目标卡 YOLO 框中心；`SKIP` 点按钮（ROI 本局裁定，A3）；`USE_P_DRINK` **拦截**，仅记录（Q9）。
6. **点击验证**（F1）：snap 对比 + OCR 锚（残りターン/手牌变化）；无效则原坐标重试（≤2 次，Q12）。
7. **转场记录**：结算动画期连续 snap（200ms 间隔），实测动画时长→Q13 窗口收紧依据；记录「新回合就绪」的可判定信号（候选：残りターン数值变化 / 手牌区 YOLO 稳定 / 动画元素消失——E2 取证后定）。
8. **JSONL 落盘**（F3，对齐 roundsim `ManualTurnRecord` 字段）：`turn / flow / played_cards / good_condition_turns / stamina / turn_score / action / reason`。

### 循环内专项取证

- **A1 出牌交互**：步骤 5–7 自然覆盖；重点记录有无确认弹窗、结算页形态、回合推进转场画面。
- **A3 SKIP ROI**：策略建议 SKIP 的回合实测；若无，安排一回合手动 SKIP 验证 `[625,742,80,80]` vs `[635,786]` 冲突。
- **A4 山札张数**：点开底部「牌库」查看按钮（非关键可点，看完关闭），确认剩余张数可读性→`deck_size` 供给方式（画面 vs 自维护）。
- **A5 P 饮料栏**：底部 4 瓶 `[24,1178,360,78]` 逐瓶 OCR，定「逐瓶 OCR vs 位置映射」方案。
- **横切弹窗**：出现任何弹窗按 Q15 规则自助处理，并把弹窗形态记入横切清单（→Phase 2 节点化）。

### 本局收尾

9 回合后依次取证：結果页 → `タップして次へ`（TapNextFlag 实锚）→ 中盘順位展示页 → Interval 入口（标题/P点/終了按钮）→ **停止**（Interval 未实现，Q7）。全程页面锚点+ROI 落盘。

### 切换点（Q14）

回合 ≥3 时评估：若 Phase 2 最小出牌循环（Round1Flag→PlayFlag→JumpBack）已可运行，剩余回合切管线实跑；不可用则继续手动走完，取证优先。

## Phase 1 纯代码修复（与 Phase 0 并行，subagent）

全部改动跑 `python -m py_compile agent` + 相关单测（`.venv/Scripts/python.exe`）：

1. **B2 flow 日文映射**：`exam_reader.py` `_parse_numeric` flow 分支加 `ビジュアル→Vi / ダンス→Da / ボーカル→Vo`；单测覆盖日文/英文/混合单位文本。
2. **B4 好调判定改效果池**：`card_dict.py` `is_good_condition_card` 改读 `skill_card_effects.json`（`ExamParameterBuff` 族）判定，硬编码名单降为 fallback；单测。
3. **B6 体力归属**：`_NUMERIC_ROI` 加 `stamina` 项；`read_exam_state` 的 `stamina` 参数改 `int | None = None`（None 时读 ROI），签名向后兼容。
4. **B1 坐标基准**：`exam_reader.py:57` 注释改竖屏 720×1280，消除横屏误导。
5. **C1+D1 会话字段**：`produce_hif.py` session-state 加 `round1` 命名空间（`turn / cards_played / oneesan_used / natural_finisher_used / reprise_count`），helper 复用 `_read/_write_session_state`；`build_exam_state` 加可选 `session: dict | None` 参数注入跨回合字段（None 保持现默认）。
6. **F3 落盘 schema**：出牌记录对齐 `ManualTurnRecord`（`adapter.py:113-123`），含 `dry_run` 标记与 `evidence`（box/OCR 原文）。
7. **B5（実機后）**：跑 `tools/hif_mine_ocr_variants.py` 回填 `OCR_VARIANTS`。

## Phase 2 管线节点与选项（`ProduceHIF.json` + `produce_hif.py`）

- **E1 `ProduceHIFRound1Play`**：`ProduceHIFRound1PlayFlag`（DirectHit → Custom action）单 action 大包（Q11）：读画面（ExamStateReader）→ 会话合并（画面优先，Q6）→ `decide()` → 执行点击（卡名→YOLO box 匹配；`target=None` 走 `pick_playable_card`）→ 验证重试（Q12）→ 落盘 → 更新 session → 回合推进等待（E2）→ 返回循环。next 走 `[JumpBack]ProduceHIFRound1Flag`。模式分流：选项关闭时保持原 Observe 链（分流机制实施时二选一：选项 override 替换 `Round1Flag` 的 next / PlayFlag 内读选项决定行为）。
- **E2 转场锚**：形态为 `timeout` 轮询等待节点（DirectHit 不进渲染等待链铁律）；具体信号 Phase 0 取证后补定（候选见上）；窗口 60s 起步，实测后收紧 ×2。
- **E3 出口路由**：残りターン=0 → 結果页锚 → `TapNextFlag` → 順位页锚 → `ProduceHIFIntervalFlag`（新）→ `ProduceHIFUnknownStop`。
- **E4 残りターン读数**：action 内 OCR 数值判定 9→0（与 A2 同 ROI）。
- **G1 任务选项**：`assets/tasks/produce.json` + `produce_cn.json` 同步新增「Round1 出牌」（default false）+ `assets/lang/` zh-Hant 翻译；经 `pipeline_override` 注入。
- **F4 循环守卫**：连续 2 回合画面无进展或 `evidence_empty` → `UnknownStop`。

## Phase 3 单节点实机连测

| 节点 | 测试 |
| --- | --- |
| `HIFNumeric_*` 各 ROI | 用 Phase 0 定标坐标逐项 test-node 验证读数 |
| `ProduceHIFRound1PlayFlag` | dry 模式实跑一回合全链（读→决策→点→验证） |
| 转场锚节点 | 出牌后等待新回合就绪，计时 |
| SKIP 点击+验证 | 实测 ROI（A3 裁定值） |
| `TapNextFlag` 路由 | 結果页→順位页推进 |
| 横切弹窗节点（若有） | 按 Phase 0 记录的弹窗形态逐个验证 |

## Phase 4 全程验收局

前置：完整培育跑到 Round1（Day1 链已通）。全程自动 9 回合，**P 饮料真点**（Q9 已确认可耗）。验收清单（Q8）：

- [ ] turn 计数与画面残りターン 9→0 全程对齐
- [ ] 每回合决策落盘（JSONL + 截图 + viewer 可读）
- [ ] 无中途 `UnknownStop`
- [ ] 结束链走通：結果页→タップして次へ→順位→Interval 入口停止
- [ ] session 字段（`cards_played` 等）全程一致
- [ ] 失败处理：修复后重跑整局

## Phase 5 回归与文档

```bash
.venv/Scripts/python.exe -m py_compile agent
.venv/Scripts/python.exe -m pytest tests/test_hif_decision.py tests/test_play_decision.py tests/test_exam_reader.py tests/test_scoring_model.py
.venv/Scripts/python.exe tools/maa_dev.py replay --suite tests/replay_suite
npx prettier --check "**/*.{json,yml,yaml}"
```

（`npx maa-tools check` 本机 404，可用时补跑。）

文档更新：`docs/hif/mechanics.md` 补出牌流程実機条目；`docs/hif/finals-daily-log.md` 补本局取证记录；`AGENTS.md` 当前进度改「Round1 出牌已接线」；本计划状态更新；`assets/resource/Changelog.md` 视发布节奏。

## 风险与回退

| 风险 | 缓解 |
| --- | --- |
| 取证局误点禁区废局 | 黑名单兜底；废局则 Day1 链重跑（已验证，约 30 分钟） |
| 验收局 fail | 同上重跑；dry-run 取证局已预演全链 |
| 数值 ROI 定标不稳 | Q6 反向降级：ROI 失败时 session 推算 + 告警 |
| 弹窗误解点错 | 白/黑名单 + 每步落盘可追溯 |
| 坐标系混乱 | 全程竖屏 720×1280（B1 已修注释） |

## 取证后补定项（依赖 Phase 0 事实，非决策）

1. 转场锚具体信号与 timeout 收紧值（E2）。
2. 横切弹窗节点清单（Phase 2 节点化范围）。
3. SKIP 按钮唯一 ROI（A3）。
4. `deck_size` 供给方式：画面可读 vs 自维护（A4）。
5. P 饮料瓶识别方案：逐瓶 OCR vs 位置映射（A5）。
6. `reprise_count` 供给方式：画面 vs 自维护（C2，与 A4 同批取证）。
