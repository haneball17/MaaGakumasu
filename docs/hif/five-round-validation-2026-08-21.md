# 五轮 HIF 全程育成验证报告（2026-08-21 立项 / 08-22 执行）

> goal 文件：`.zcode/plans/five-round-validation-goal.md`（两轮 grill 裁决）。
> A 目的=管线（除决策模块）稳定性验证；B 目的=游玩树完善。
> 轮 0 为验证开始前已在途的培育局（用户指令：先跑完，不计入 5 轮）。

## 轮 0：在途局接管（不计入五轮）

### 时间线（2026-08-22 深夜）

| 时间 | 事件 |
| --- | --- |
| 00:11 | adb 16448 连接；主页面「プロデュース中 7/7日目」确认在途局 |
| 00:12 | プロデュース再開 → 直接进 Round1 対局（手牌：魅惑のパフォーマンス/自然体の魅力+） |
| 00:14 | 首次接管失败：`build_produce_override` 缺 produce.json 选项定义（Round1 出牌/使用体力药 仅在 produce.json），走了 Observe |
| 00:20 | 修复 override 后 Play 模式重跑；开局 P 饮料槽探测全空（槽2 ビタミンドリンク 弹窗渲染慢误判 empty 且未关） |
| 00:31 | 第 1 次 stop：`evidence_empty_hand`——残留 P 饮料弹窗遮挡手牌，YOLO 恒 miss |
| 00:33 | 手动关弹窗，重跑（含 _verify_p_drink 验证重试修复）：槽2 初星黒酢 正确读到 |
| 00:47 | 出牌至 turn9 残り1；第 2 次 stop：`evidence_empty_hand`（buff 完整面板残留遮挡——P item 详情入口误点开 buff 面板，锚 miss 判「未打开」不关闭） |
| 00:55 | 残留自愈修复（_dissolve_blocking_overlays）+ 出口判定修复（_wait_round_exit）落地重跑：自愈生效，turn9 出牌完成 |
| 01:05 | 但 turn9 结束转場被误判 `turn_counter_unreadable` stop（画面已到 R1 結果页）——修复：残りターン消失时轮询出口锚判定完成 |
| 01:06 | 結果页重启段：全链走通 R1 結果→次へ→応援棒→Interval（Custom 終了）→R2 優勝条件页 |
| 01:09 | 段终止于 R2 優勝条件页：锚文本不匹配（実機「合計評価」vs 锚「合計スコア」）+ 未挂 ScheduleRoot → UnknownStop |
| 01:12 | 修锚+挂载；重启段进 R2 対局（round2 turn1 残り12，两位数锚+参数化 12 回合全生效） |
| 01:2x | 误留双段并行（01:04 段未死+01:12 段）互相干扰；清理后干净重启 |
| 01:4x | R2 12 回合出牌完成（敗退 3 位：298,958+47,310 vs 対手 108/82 万） |
| 01:56 | 敗退链走通：DefeatFlag→次へ→再挑戦確認弹窗（RetryConfirm 命中） |
| 01:59 | プロデュース終了点击：段内 IPC 4 连点未生效、手动同坐标单点即中（入场动画点击丢失）；修 SETTLE_DELAY |
| 02:0x | スター性獲得→最終評価→MEMORY 生成→完了页（TapNextFlag 补「^TAP$」变体+前移解 MemoryFlag 吸环） |
| 02:1x | メモリー詳細确认页误入浏览詳細页（固定坐标点次へ误触）；BACK 键実証唯一出口；Custom 重写（OCR 锚定次へ+BACK 自愈） |
| 02:2x | イテム獲得→HIF 報酬页（次へ误点プロデュース履歴修复：OCR 校准 (377,1159)） |
| 02:28 | **回到主页面 ✓ 轮 0 完整走完**（プロデュース中标签消失） |

**全链実証（管线自动+分段驱动）**：R1 出牌(9T)→R1 結果→次へ→応援棒→Interval(終了)→R2 優勝条件→R2 出牌(12T)→R2 敗退→次へ→再挑戦確認→プロデュース終了→スター性獲得→最終評価→MEMORY 生成→完了→メモリー詳細(次へ)→イテム獲得→HIF 報酬×2→ガシャ広告(×关闭)→**主页面**。

### 是否按要求操作

- 主线推进：R1 出牌 9 回合 ✓（turn7 时 USE_P_DRINK 初星黒酢 拦截降级 SKIP ✓）；R1 結果→応援棒→Interval→R2 全链 ✓
- 危险操作：无（未点再挑戦/ガシャへ/リタイア）
- 敗退处理：未到（R2 进行中）

### 意外 + 根因 + 修复（bug 清单）

| # | 现象 | 根因 | 修复 | 验证 |
| --- | --- | --- | --- | --- |
| 1 | Observe 误跑（round1_mode=observe） | produce_cn.json 缺 Round1 出牌等选项定义，override 合并不到 | hif_run.build_produce_override 以 produce.json 为底合并 + default_case list 兼容 | override 含 ProduceHIFRound1Flag.next ✓ |
| 2 | P 饮料槽误判 empty 且弹窗残留→evidence_empty_hand stop | 弹窗渲染慢，锚 OCR miss 即判空且不关 | _verify_p_drink 验证带一次重试 + 判空前兜底关一次 | 槽2 初星黒酢 复跑读到 ✓ |
| 3 | P item 详情入口误开 buff 完整面板→残留→第 2 次 evidence_empty_hand stop | 入口坐标与 buff 带/排名区交叠；面板类型不辨即放弃（不关） | 打开失败先 _dissolve_blocking_overlays 关残留；read_hand 空分支挂同款自愈 | 复跑 read_hand 恢复、出牌继续 ✓ |
| 4 | Round 结束转場被误判 turn_counter_unreadable stop | 残りターン消失≠异常：結果页本无该元素 | turn None 时 _wait_round_exit 轮询出口锚（ラウンドN結果/敗退/Interval/優勝条件）60s 判定完成 | 結果页重启段直接 return True ✓ |
| 5 | R2 優勝条件页 UnknownStop | 锚「合計スコア」与実機「合計評価」不符 + 节点未挂 ScheduleRoot | 锚改「合計評価で/優勝を競」ROI 校准 box[52,408,628,30]；挂 [JumpBack] 到 ScheduleRoot | 离线 replay 命中 ✓ 実機进 R2 ✓ |
| 6 | 同回合连续出牌每张死等 60s（9 回合拖 25 分钟） | _wait_transition 60s 窗口等 turn 变化，同回合 turn 不变 | 出牌后短等待 8s；空手分支保持 30s 长等待 | R2 段速度显著提升（12 回合 ~10 分钟）|
| 7 | 双段并行互踩（画面交错 turn12/3 跳变） | 前段 `>/dev/null &` 吞输出未察觉存活 + 新段启动 | taskkill 清理；后续一律 run_in_background 管理段 | ✓ |
| 8 | Round1Flag 在 R2 対局页命中后 fall through 到 R1 版 PlayFlag（9 回合配置跑 12 回合页） | Yes override next=[Round2Flag, PlayFlag]，两位数锚 miss（动画中）即轮询 PlayFlag | 接受（策略不依赖 total_turns 精确）；根治需 R2Flag miss 时等待而非立即 fall through（待 R2 出口锚经验积累后处理） | 观察 |
| 9 | ScheduleRoot 轮询一轮 >timeout，敗退节点排尾轮不到 → UnknownStop | 挂载节点 29 个×识别耗时 ≈ 每轮 50s+，原 timeout 40s | timeout 90s + 完结链前移（Round1Flag 后第 2 位起） | 敗退链走通 ✓ |
| 10 | メモリー生成完了页被 MemoryFlag（メモリー锚）吸住死循环 | 完了页标题「メモリー生成完了」命中泛锚，next 全 miss 回环 | TapNextFlag（含 ^TAP$）前移到 Memory 系节点前 | 完了页过 ✓ |
| 11 | メモリー詳細确认页点次へ误入浏览詳細页（无次へ、<<无效） | 固定坐标 (360,1156) 与実機按钮有偏差+页面变体；浏览页唯一出口=BACK 键 | Custom 重写：OCR 锚定次へ box 点击+浏览页 BACK(post_click_key 4) 自愈 | 手动 BACK 実証 ✓（Custom 自动路径待轮 1 复验） |
| 12 | HIF 報酬页次へ点击误点プロデュース履歴 | 旧坐标 (560,1150) 落在履歴按钮 [505,1137,183,40] 上 | OCR 校准次へ box [352,1144,51,30]→(377,1159) | 手动点生效 NOW LOADING ✓ |
| 13 | 段在 NOW LOADING/长动画窗口 90s 全 miss → UnknownStop 分段退出 | MaaFW next 轮询 timeout 为总时长，LOADING 页无锚 | 接受：分段驱动模式（hif_push_loop 同款）重启段接管；五轮驱动即此模式 | 多次分段接力到主页面 ✓ |

### 决策接口检查（轮 0 增量）

- p_drinks：槽探测读到 初星黒酢 → match_drink_name 命中 → session.p_drink_slots ✓（落盘 round1_play evidence）
- p_items：详情弹窗実機取证（pitem2_detail.png：全部道具效果流式列表、× 与 buff 面板同位）→ 入口坐标待校准（当前 miss 降级）
- deck：堆查看器假设位未命中（UI 未取证，预期内降级）
- P 饮料获得弹窗：Custom action 落盘就绪（p_drink_obtained），本轮未触发获得场景

## 轮 1（待跑）

## 轮 2（待跑）

## 轮 3（待跑）

## 轮 4（待跑）

## 轮 5（待跑）
