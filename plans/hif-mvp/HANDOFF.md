# HIF MVP 实机交接

_最后更新：2026-07-16；M2 单步探针后安全停点。_

## 2026-07-20 连接复核

- 运行：`hif-mvp-m2-state-observe-20260720`，命令仅请求 `--single-step --round1-state-observe`。
- 控制器在初始化时无法连接 `127.0.0.1:16416`（MuMu ADB 返回错误），未进入 Maa Pipeline，未保存本次 Journal 或前后帧。
- 因此没有 Click、Swipe、选牌、确认或资源消耗；当前页面和 2026-07-16 停点均未重新验证。
- 恢复前先确认同一 MuMu 实例的 ADB 可达，再从只读状态观测重新建立当前局证据；不得使用历史状态继续输入。

## 2026-07-20 Day1 场景3候选采证

- 运行：`hif-day1-change-candidates-enumerate-20260720`，正式受限入口 `--single-step --select-change-target-enumerate`。
- 当前候选页三张卡均经详情 OCR 读取：左 `大声援`、中 `祝福`、右 `立ち位置チェック`；再抽次数为 `3`。
- Journal：`debug/hif-journal/20260720T230920-8768.jsonl`；审计 `ok=true`，三次已验证候选读取，未执行“次へ”、再抽选、チェンジ或其他资源操作。
- 三张候选均是可识别目标，现有选择器按 `multiple_target_cards_observed` 前的枚举停点停止。后续必须先完成来源牌库快照，并按计划的 `forced_fallback` 规则构造唯一组合；不得从候选页直接提交。

## 当前权威停点

- 环境：MuMu 模拟器 12，ADB `127.0.0.1:16416`，原始帧 `720x1280`。
- 路线：`rinami_garakuta_road`。
- 页面：Round1，最近零输入帧显示剩余回合 `6`。
- 状态：`good_condition=50`、`focus=10`、`stamina=29`；再演不能再由固定 ROI 推断。
- 指标：`current_score=137665`、`stage_multiplier=3807%`。
- 手牌：`演出計画`、灰色 `眠気`、`始まりの合図`。
- 牌库数量：技能卡详情页同一运行验证为 `21`。
- 元气：主画面右上 `22`，用户已确认其语义为元气；不得再标记为牌库数。

## 最近实机证据

- `20260716T091431` 的单步运行本应只为「始まりの合図」采集确认后证据，却因错误地将路线评分结果升级为执行授权，确认出牌了评分器选择的「祝福」。严格后验以 `post_state_not_readable` 安全停止，故不计入成功样本；运行前后的稳定可见状态为分数 `121485→137665`、体力 `31→29`、好调 `49→50`，且「祝福」离手。
- 原因已在本地修复：`hand_details_map_deck_play_one` 现于任何详情、面板或手牌输入前以 `round1_detail_route_execution_not_supported` 停止。路线评分只可排序，不能代替逐卡、已验证的动作后验授权。
- 本次运行 Journal：`debug/hif-journal/20260716T091435-36404.jsonl`；运行目录：`debug/hif-live/20260716T091431/`。控制器日志记录了详情、牌库、指标面板和两次「祝福」点击；此后没有追加游戏输入。

- `祝福+` 模型发现运行：`debug/hif-live/hif-mvp-m2-blessing-plus-closed-loop-20260715/`，Journal `debug/hif-journal/20260715T232450-42392.jsonl`。
- 动作前完整状态与目标绑定成立，`祝福+` 已完成两段式确认并离手；动作后正式后验在动画期打开牌库失败，因此本次不计入严格成功样本。
- 最新零输入复核：`debug/hif-live/hif-mvp-m2-zero-input-recheck-20260716.png`。未发送触控、按键或 Pipeline 指令；确认上述 Round1 停点和手牌仍稳定。
- 状态效果详情探针已随 `a01d5d4 feat(hif): 记录状态效果详情探针` 落地。当前列表的实机证据确认：`参数上升量增加 30% / 1ターン`、`消費体力を50%軽減 5ターン`、`絶好調 / 2ターン` 与 `発動予約 / 1回 1ターン`；其数值必须作为后验输入，禁止回退到固定 `reprise` ROI。
- `15d9574 feat(hif): 结构化读取活跃效果` 将上述列表转为严格快照。运行 `hif-mvp-m2-active-effects-sorted-close-20260716` 的 Journal `debug/hif-journal/20260716T002051-49616.jsonl` 记录 `execution_ready=true`，并在关闭后回到未选中 Round1；没有手牌、SKIP 或奖励输入。
- `hif-mvp-m2-post-effects-state-observe-20260716` 的详情映射在不完整 `ExamState` 上触发了旧代码异常并于 45 秒超时停止；结束帧仍为未选中 Round1。已修复为 `round_hand_probe_state_unreadable` 类型化安全停止，禁止该路径重试或继续点击。
- 分离的稳定后状态证据为：分数 `116611→121485`、体力 `33→31`、好调 `47→49`、集中 `10`、回合 `6`、牌库 `21`、元气 `22`。结构化记录见 `assets/data/hif/observed_cases/blessing_plus_round1_20260715.json`。
- 实测增量 `+4874/-2/+2` 与卡表基础 `显示3731/体力4/好调1` 不同，证明当前活跃状态存在未建模联动。普通出牌后验已重新关闭；完成状态图标动态定位与联动模型前禁止下一张牌。

- M1 可信绑定运行目录：`debug/hif-live/hif-mvp-m1-consensus-bind-stop-20260715/`
- M1 可信绑定 Journal：`debug/hif-journal/20260715T225918-6632.jsonl`
- 同一运行完整决策字段：`turn=6`、`good_condition=47`、`focus=10`、`stamina=33`、`reprise=2`、`deck_size=21`、`current_score=116611`、`stage_multiplier=3807%`。
- 多 ROI 交叉一致修正了窄 ROI 将好调 `47` 读成 `7`、集中 `10` 读成 `1` 的稳定误读；剩余回合使用当前帧裁出的 `6.png` 高阈值模板。
- 当前手牌唯一评分目标为 `hand-4 = 祝福+`；灰色 `眠気` 的低饱和占比为 `0.700`，被 `gray_card` Hard Gate 排除。
- 运行仅包含打开/关闭技能卡详情页与分数面板的四次已声明输入；没有手牌点击。最终以 `postcondition_not_supported` 安全停止。

- M1 零输入复核运行目录：`debug/hif-live/hif-mvp-m1-stop-recheck-20260715/`
- M1 Journal：`debug/hif-journal/20260715T214307-25052.jsonl`
- M1 原始帧仍为 Round1 未选中四卡页：`演出計画`、灰色 `眠気`、`祝福`、`祝福+`；右上 `22` 后经用户确认为元气，不是牌库数。
- 旧影子策略的“山札0枚”污染已经移除；缺失或冲突状态现在类型化拒绝。
- M1 运行目录的 `maafw.log` 不含 Click/Swipe，本次未改变游戏状态或资源。

- 运行目录：`debug/hif-live/hif-round1-score-multiplier-calibrated-20260715/`
- Journal：`debug/hif-journal/20260715T185253-45208.jsonl`
- 分数 ROI：`[42,145,135,38]`，OCR `116611`，置信度 `0.998627`。
- 倍率 ROI：`[65,75,150,48]`，OCR `3807%`，置信度 `0.974869`。
- 本次运行包含打开和关闭指标面板两次控制器输入；关闭后已验证回到 Round1。

## 继续前必须完成

1. 重新保存当前原始帧，确认页面、回合、状态和手牌仍与权威停点一致。
2. 审计最新 Journal、Maa 控制器日志和当前工作区差异。
3. 完成 M0 基线门禁；不得用历史测试结果代替当前验证。
4. 为当前三张手牌重新建立同运行期状态和唯一目标；逐卡语义后验落地前，禁止确认出牌。
5. 在语义后验落地前继续禁止手牌点击；不得用“目标离手”单独代替分数、好调、体力等领域变化。

## 当前禁止事项

- 不使用历史 `deck_size=0`、默认值或过期 Session 补状态。
- 不执行灰色 `眠気`。
- 不让多个 agent 或进程同时控制模拟器。
- 不用普通 `--round1-play-one`、历史坐标或外部卡名参数绕过同运行期映射。
- 不把路线评分器的排序结果当作执行授权；必须由当前卡的显式语义后验单独批准。
- 未完成门禁前不开放 Round1 连续模式。
- 不把当前探路局描述为正式端到端验收成功。

## 里程碑记录模板

后续每次实机里程碑在本文件追加或更新以下信息：

- 时间、分支和提交；
- 运行命令与唯一 `run-id`；
- 前后页面及关键状态；
- Journal、截图和 Maa 日志路径；
- 所有控制器输入及资源变化；
- 决策、审批和语义后验；
- 测试与静态检查结果；
- 当前安全停点、剩余缺口和下一条唯一允许操作。
