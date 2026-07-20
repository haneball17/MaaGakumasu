# HIF MVP 手动测试方案

_状态：探路与建模用测试方案，记录于 2026-07-16。_

范围：MuMu 12、日文原版、`720x1280`、`rinami_garakuta_road`。目标是高效采集可复盘证据，补全数据目录、状态读取和单卡后验；不是完成正式 HIF 验收。

本方案不改写 `PLAN.MD` 的资源、停止或 `8+2` 规则。人工点击、鼠标操作或独立 ADB 操作均不得用于最终新局验收。

## 1. 两类运行

| 类别         | 输入                                           | 可产出                                        | 不可产出                                     |
| ------------ | ---------------------------------------------- | --------------------------------------------- | -------------------------------------------- |
| `D` 发现运行 | 人工 UI 操作；最多一个不可逆游戏动作           | 卡面原文、状态联动、ROI、页面流、候选后验假设 | `8+2` 成功样本、自动执行授权、正式端到端证据 |
| `V` 验证运行 | 正式 Pipeline 的受限单步；控制器/Journals 完整 | 可审查的单卡成功或拒绝样本                    | 连续执行授权，除非既有 `8+2` 条件全部满足    |

任何手动操作都标记 `D`。`V` 只有同时具备正式入口、唯一 `run_id`、前后原始帧、Journal、控制器日志、目标绑定和领域后验时，才可能计入既有 `8+2`；本方案不改变其计数口径。

## 2. 通用规则

1. 一个 `run_id` 只验证一个假设；一个不可逆动作后立即停止。
2. 一个时刻只有一个操作者和一个控制器连接模拟器。
3. 每次状态改变前保存至少三张连续稳定原始帧；稳定由同一页面和关键字段一致证明，不由等待秒数证明。
4. 每个输入写入人工输入日志：时间、操作者、页面、目标文本/槽位、动作、预期、实际结果。
5. 不使用付费宝石、现实货币、账号操作、主动放弃、重开局刷样本或未确认购买。
6. 页面、目标、文本、状态、效果版本、ROI 或结果不唯一时停止；不补点、不猜测、不从历史值补全。
7. `debug/`、Journal、原始截图和视频只作本地证据，不提交 Git；结论、路径和最小测试夹具写入 Handoff/测试。

## 3. 每例必采字段

**环境**：游戏版本、语言、模拟器、ADB 地址、原始帧尺寸、分支/提交、`run_id`。

**动作前**：页面分类、回合、分数、倍率、体力、好调、集中、元气、牌库、再演/使用次数、全部可见手牌及灰卡标记、全部活跃效果详情。

**动作本体**：UI 槽位/目标、完整日文卡名、强化档、卡面费用、卡面效果原文、是否已选中、是否确认。

**动作后**：同一字段重读；手牌/牌库/已使用状态；当前页面；活跃效果变化；控制器日志；Journal 记录；资源变化。

仅记录“画面变化”不算成功。严格后验至少覆盖实际依赖的消耗、得分/参数、状态、手牌和页面语义。

## 4. 用例层级

| ID      | 类型 | 目标                             | 输入上限              | 通过条件                                                      |
| ------- | ---- | -------------------------------- | --------------------- | ------------------------------------------------------------- |
| `MT-00` | 只读 | 帧尺寸、设备、当前页面           | 0                     | `720x1280`、环境/页面可唯一识别                               |
| `MT-10` | 只读 | 指标与状态稳定性                 | 仅打开/关闭已校准详情 | 三帧关键字段一致；每个效果有完整原文和关闭后回到 Round 的证据 |
| `MT-20` | 可逆 | 手牌身份与强化档映射             | 仅选择/取消，不确认   | 槽位、标题、OCR、`entity_id + tier` 唯一；无资源变化          |
| `MT-30` | 发现 | 单卡效果与状态联动               | 一次人工确认          | 完整前后状态；结果只作为建模证据，不计 `8+2`                  |
| `MT-40` | 拒绝 | 灰卡、未知卡、歧义、缺状态       | 0                     | 没有输入；类型化拒绝原因可复现                                |
| `MT-50` | 页面 | Interval、奖励、Live、回忆、结算 | 默认 0                | 新页面先建档、采帧、写失败测试；不靠首次遇到页面继续推进      |
| `MT-60` | 验证 | 已建模单卡正式单步               | 正式 Pipeline 一次    | 满足 `V` 全部证据，才候选计入 HIF 既有门禁                    |

## 5. 当前 Round1 首轮

权威停点当前为：Round1、剩余回合 `6`、分数 `137665`、倍率 `3807%`、体力 `29`、好调 `50`、集中 `10`；手牌为 `演出計画`、灰色 `眠気`、`始まりの合図`。

按以下顺序执行，不混合用例：

1. `MT-00-R1`：用只读控制器探测保存原始帧，确认设备/页面/三张手牌。
2. `MT-10-R1`：读取指标面板、牌库、全部活跃效果详情；每个详情必须关闭并确认回到相同 Round1。
3. `MT-20-R1`：逐张只选择 `演出計画`、`眠気`、`始まりの合図`，记录槽位、完整标题、灰卡状态、强化档和卡面原文；每次取消后确认数值不变。
4. `MT-40-R1`：记录 `眠気` 灰卡拒绝；不尝试确认或绕过不可用状态。
5. `MT-30-R1-StartSignal`：仅在明确接受本局变更后，人工确认一次 `始まりの合図`。记录全部活跃效果、费用、手牌、分数、好调、体力和页面变化。当前数据目录对此卡的 release gate 为红，此例只能补 AST/后验证据，不能算严格成功样本。
6. 确认后立即停止。先离线复盘、补测试和数据裁决；不在同一局连续试第二张卡。

`演出計画` 效果尚未达到当前严格可执行条件，只做 `MT-20`。`眠気` 永不执行。`祝福+` 既有样本受活跃效果联动影响，先以 `MT-10` 补全状态模型，再另建独立用例。

## 6. 发现运行转验证运行门槛

将某张卡从 `D` 转为 `V` 前，必须全部通过：

1. 数据目录中精确 `entity_id + tier + effect_version_id` 的 AST 完整，无影响转移的 `unknown`。
2. `python tools/data_catalog.py validate --profile hif-release` 通过。
3. `python tools/data_catalog.py derive --check` 通过。
4. OCR/profile 唯一绑定，手牌 UI `target_id` 与稳定身份分离记录。
5. 前后领域后验、边界和拒绝路径已有离线测试。
6. 当前帧的全部决策依赖字段可信、同局账本未过期。
7. 正式单步动作具有明确后继识别；失败返回 `UnknownStop`，不重试点击。

`MT-60` 后执行 `python tools/hif_journal_audit.py <journal>`。结果不通过、前后帧缺失、控制器输入多于声明或页面未回到预期状态时，样本作废并停止。

## 7. 工具与输入边界

每次 `MT-00` 前先运行以下离线前检；任一失败，记录结果并停止，不连接或操作模拟器：

```powershell
python -X utf8 tools/hif_screen_profile_check.py
python -X utf8 tools/hif_pipeline_check.py
```

`MT-60` 还必须满足第 6 节的数据目录门槛。当前 `hif-release` 失败时，仍可进行 `MT-00` 至 `MT-40` 的发现与拒绝采样，但不得执行正式单步。

当前已知阻塞：`hif_screen_profile_check.py` 仍硬编码审阅段数量 `34`，而当前 profile 与
`tests/test_hif_screen_profiles.py` 均为 `35`。先对齐检查脚本、配置和测试，再开始 `MT-00`；不得跳过此检查或把失败归为设备异常。

默认只读工具：

```powershell
python -X utf8 tools/hif_controller_probe.py --adb <address> --adb-path <adb.exe> --save <frame.png>
python -X utf8 tools/hif_journal_audit.py <journal.jsonl>
python -X utf8 tools/hif_roi_calibration.py --image <frame.png> --kind <kind> --field <field> --roi <x,y,w,h>
```

`hif_roi_calibration.py` 不带 `--write` 时只输出候选校准。当前 `hif_daily_roi_review.py` 缺少 Pillow 时不可用，不作为人工测试阻塞项。

`hif_live_runner.py` 的观察类开关，如 `--round1-state-observe`、`--round1-details-observe`、`--round1-turn-roi-probe`、`--round1-status-effect-probe`，只在先审阅对应实现、指定唯一 `run_id` 后使用。它们仍需审计控制器日志。

以下开关属于状态改变输入，不用于普通发现采集：`--round1-play-one`、`--round1-confirm-selected`、`--round1-hand-detail-map-deck-play-one`、`--source-deck-confirm-target`、`--skill-reward-receive`、`--drink-overflow-keep-black-vinegar`、`--hif-from-home`。只有单独批准的 `MT-60` 才可使用其中与当前用例匹配的一项。

## 8. 记录模板

```text
case_id: MT-xx
class: D | V
run_id:
operator:
environment: game_version / locale / emulator / frame_size / commit
hypothesis:
before: page / score / multiplier / stamina / statuses / hand / deck
input: none | exact UI target and one action
after: page / score / multiplier / stamina / statuses / hand / deck
expected_postcondition:
observed_postcondition:
evidence: before frames / after frames / journal / controller log / Maa log
result: pass | reject | inconclusive
stop_reason:
next_allowed_action:
```

`D` 例结束后，将可确认事实写成断言候选、ROI 样本或最小测试夹具。`V` 例结束后，先审计再更新 `HANDOFF.md`；达到既有里程碑才更新 `STATUS.md`。无论哪类例，均不提交原始证据文件。
