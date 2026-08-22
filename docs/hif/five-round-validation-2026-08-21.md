# 五轮 HIF 全程育成验证报告（2026-08-21 立项 / 08-22 执行）

> goal 文件：`.zcode/plans/five-round-validation-goal.md`（两轮 grill 裁决）。
> A 目的=管线（除决策模块）稳定性验证；B 目的=游玩树完善。
> 轮 0 为验证开始前已在途的培育局（用户指令：先跑完，不计入 5 轮）。

## 轮 0：在途局接管（不计入五轮）

### 时间线（2026-08-22 深夜）

| 时间  | 事件                                                                                                                                          |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 00:11 | adb 16448 连接；主页面「プロデュース中 7/7日目」确认在途局                                                                                    |
| 00:12 | プロデュース再開 → 直接进 Round1 対局（手牌：魅惑のパフォーマンス/自然体の魅力+）                                                             |
| 00:14 | 首次接管失败：`build_produce_override` 缺 produce.json 选项定义（Round1 出牌/使用体力药 仅在 produce.json），走了 Observe                     |
| 00:20 | 修复 override 后 Play 模式重跑；开局 P 饮料槽探测全空（槽2 ビタミンドリンク 弹窗渲染慢误判 empty 且未关）                                     |
| 00:31 | 第 1 次 stop：`evidence_empty_hand`——残留 P 饮料弹窗遮挡手牌，YOLO 恒 miss                                                                    |
| 00:33 | 手动关弹窗，重跑（含 \_verify_p_drink 验证重试修复）：槽2 初星黒酢 正确读到                                                                   |
| 00:47 | 出牌至 turn9 残り1；第 2 次 stop：`evidence_empty_hand`（buff 完整面板残留遮挡——P item 详情入口误点开 buff 面板，锚 miss 判「未打开」不关闭） |
| 00:55 | 残留自愈修复（\_dissolve_blocking_overlays）+ 出口判定修复（\_wait_round_exit）落地重跑：自愈生效，turn9 出牌完成                             |
| 01:05 | 但 turn9 结束转場被误判 `turn_counter_unreadable` stop（画面已到 R1 結果页）——修复：残りターン消失时轮询出口锚判定完成                        |
| 01:06 | 結果页重启段：全链走通 R1 結果→次へ→応援棒→Interval（Custom 終了）→R2 優勝条件页                                                              |
| 01:09 | 段终止于 R2 優勝条件页：锚文本不匹配（実機「合計評価」vs 锚「合計スコア」）+ 未挂 ScheduleRoot → UnknownStop                                  |
| 01:12 | 修锚+挂载；重启段进 R2 対局（round2 turn1 残り12，两位数锚+参数化 12 回合全生效）                                                             |
| 01:2x | 误留双段并行（01:04 段未死+01:12 段）互相干扰；清理后干净重启                                                                                 |
| 01:4x | R2 12 回合出牌完成（敗退 3 位：298,958+47,310 vs 対手 108/82 万）                                                                             |
| 01:56 | 敗退链走通：DefeatFlag→次へ→再挑戦確認弹窗（RetryConfirm 命中）                                                                               |
| 01:59 | プロデュース終了点击：段内 IPC 4 连点未生效、手动同坐标单点即中（入场动画点击丢失）；修 SETTLE_DELAY                                          |
| 02:0x | スター性獲得→最終評価→MEMORY 生成→完了页（TapNextFlag 补「^TAP$」变体+前移解 MemoryFlag 吸环）                                                |
| 02:1x | メモリー詳細确认页误入浏览詳細页（固定坐标点次へ误触）；BACK 键実証唯一出口；Custom 重写（OCR 锚定次へ+BACK 自愈）                            |
| 02:2x | イテム獲得→HIF 報酬页（次へ误点プロデュース履歴修复：OCR 校准 (377,1159)）                                                                    |
| 02:28 | **回到主页面 ✓ 轮 0 完整走完**（プロデュース中标签消失）                                                                                      |

**全链実証（管线自动+分段驱动）**：R1 出牌(9T)→R1 結果→次へ→応援棒→Interval(終了)→R2 優勝条件→R2 出牌(12T)→R2 敗退→次へ→再挑戦確認→プロデュース終了→スター性獲得→最終評価→MEMORY 生成→完了→メモリー詳細(次へ)→イテム獲得→HIF 報酬×2→ガシャ広告(×关闭)→**主页面**。

### 是否按要求操作

- 主线推进：R1 出牌 9 回合 ✓（turn7 时 USE_P_DRINK 初星黒酢 拦截降级 SKIP ✓）；R1 結果→応援棒→Interval→R2 全链 ✓
- 危险操作：无（未点再挑戦/ガシャへ/リタイア）
- 敗退处理：未到（R2 进行中）

### 意外 + 根因 + 修复（bug 清单）

| #   | 现象                                                                                   | 根因                                                                             | 修复                                                                                                              | 验证                                           |
| --- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| 1   | Observe 误跑（round1_mode=observe）                                                    | produce_cn.json 缺 Round1 出牌等选项定义，override 合并不到                      | hif_run.build_produce_override 以 produce.json 为底合并 + default_case list 兼容                                  | override 含 ProduceHIFRound1Flag.next ✓        |
| 2   | P 饮料槽误判 empty 且弹窗残留→evidence_empty_hand stop                                 | 弹窗渲染慢，锚 OCR miss 即判空且不关                                             | \_verify_p_drink 验证带一次重试 + 判空前兜底关一次                                                                | 槽2 初星黒酢 复跑读到 ✓                        |
| 3   | P item 详情入口误开 buff 完整面板→残留→第 2 次 evidence_empty_hand stop                | 入口坐标与 buff 带/排名区交叠；面板类型不辨即放弃（不关）                        | 打开失败先 \_dissolve_blocking_overlays 关残留；read_hand 空分支挂同款自愈                                        | 复跑 read_hand 恢复、出牌继续 ✓                |
| 4   | Round 结束转場被误判 turn_counter_unreadable stop                                      | 残りターン消失≠异常：結果页本无该元素                                            | turn None 时 \_wait_round_exit 轮询出口锚（ラウンドN結果/敗退/Interval/優勝条件）60s 判定完成                     | 結果页重启段直接 return True ✓                 |
| 5   | R2 優勝条件页 UnknownStop                                                              | 锚「合計スコア」与実機「合計評価」不符 + 节点未挂 ScheduleRoot                   | 锚改「合計評価で/優勝を競」ROI 校准 box[52,408,628,30]；挂 [JumpBack] 到 ScheduleRoot                             | 离线 replay 命中 ✓ 実機进 R2 ✓                 |
| 6   | 同回合连续出牌每张死等 60s（9 回合拖 25 分钟）                                         | \_wait_transition 60s 窗口等 turn 变化，同回合 turn 不变                         | 出牌后短等待 8s；空手分支保持 30s 长等待                                                                          | R2 段速度显著提升（12 回合 ~10 分钟）          |
| 7   | 双段并行互踩（画面交错 turn12/3 跳变）                                                 | 前段 `>/dev/null &` 吞输出未察觉存活 + 新段启动                                  | taskkill 清理；后续一律 run_in_background 管理段                                                                  | ✓                                              |
| 8   | Round1Flag 在 R2 対局页命中后 fall through 到 R1 版 PlayFlag（9 回合配置跑 12 回合页） | Yes override next=[Round2Flag, PlayFlag]，两位数锚 miss（动画中）即轮询 PlayFlag | 接受（策略不依赖 total_turns 精确）；根治需 R2Flag miss 时等待而非立即 fall through（待 R2 出口锚经验积累后处理） | 观察                                           |
| 9   | ScheduleRoot 轮询一轮 >timeout，敗退节点排尾轮不到 → UnknownStop                       | 挂载节点 29 个×识别耗时 ≈ 每轮 50s+，原 timeout 40s                              | timeout 90s + 完结链前移（Round1Flag 后第 2 位起）                                                                | 敗退链走通 ✓                                   |
| 10  | メモリー生成完了页被 MemoryFlag（メモリー锚）吸住死循环                                | 完了页标题「メモリー生成完了」命中泛锚，next 全 miss 回环                        | TapNextFlag（含 ^TAP$）前移到 Memory 系节点前                                                                     | 完了页过 ✓                                     |
| 11  | メモリー詳細确认页点次へ误入浏览詳細页（无次へ、<<无效）                               | 固定坐标 (360,1156) 与実機按钮有偏差+页面变体；浏览页唯一出口=BACK 键            | Custom 重写：OCR 锚定次へ box 点击+浏览页 BACK(post_click_key 4) 自愈                                             | 手动 BACK 実証 ✓（Custom 自动路径待轮 1 复验） |
| 12  | HIF 報酬页次へ点击误点プロデュース履歴                                                 | 旧坐标 (560,1150) 落在履歴按钮 [505,1137,183,40] 上                              | OCR 校准次へ box [352,1144,51,30]→(377,1159)                                                                      | 手动点生效 NOW LOADING ✓                       |
| 13  | 段在 NOW LOADING/长动画窗口 90s 全 miss → UnknownStop 分段退出                         | MaaFW next 轮询 timeout 为总时长，LOADING 页无锚                                 | 接受：分段驱动模式（hif_push_loop 同款）重启段接管；五轮驱动即此模式                                              | 多次分段接力到主页面 ✓                         |

### 决策接口检查（轮 0 增量）

- p_drinks：槽探测读到 初星黒酢 → match_drink_name 命中 → session.p_drink_slots ✓（落盘 round1_play evidence）
- p_items：详情弹窗実機取证（pitem2_detail.png：全部道具效果流式列表、× 与 buff 面板同位）→ 入口坐标待校准（当前 miss 降级）
- deck：堆查看器假设位未命中（UI 未取证，预期内降级）
- P 饮料获得弹窗：Custom action 落盘就绪（p_drink_obtained），本轮未触发获得场景

## 轮 1：探索优先（2026-08-22 02:30-07:15）

### 时间线（要点）

| 时间        | 事件                                                                                                                                                                                                       |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 02:30-02:55 | 入口段失败×3：StartUp 在主页 miss（改 --produce-only）；Produce 链不认日程页（改 --entry ScheduleRoot）；本戦 tab 点击丢失（手动）；FinalModeFlag ROI 右界截断「本戦」box 2px（ROI 放宽 [140,850,500,80]） |
| 02:55       | Day1 开场コミュ页 SKIP 手动（HIF 管线无コミュ节点，记录缺口）                                                                                                                                              |
| 03:05-03:49 | Day1-3 自动推进：授業选项/日程选择/差し入れ事件（对话页无节点手动+补 GiftTalkBlank 节点）/P 饮料三选一/上限取舍/**p_drink_obtained Custom 実証**（goal 1.6 ✓）                                             |
| 02:44-04:30 | **変卡"hang"三次**（实为 ItemGainFlag 泛锚「獲得」吸住変卡页循环点击空转）→根因修复：锚收窄「イテム獲得/アイテム獲得」+変卡 reroll=0（预防性）                                                             |
| 04:30-04:39 | 変卡源卡 scroll_back_failed 循环（残留カスタマイズ確認弹窗挡网格）→修复：源卡 Custom 入口弹窗接管（锚 y484 校准+点チェンジ (520,1157)）                                                                    |
| 04:40-05:25 | 日付変更演出页卡（无节点+ROI 错位 y1036+挂载位太深 90s 轮不完）→修复：DayChangeBlank+ROI+前移横切节点（TapNext/DayChange/GiftTalk 至 pos 3-4）                                                             |
| 05:25       | **游戏画面冻结**（64s 零像素变化，Unity 卡死）→ force-stop 重启游戏→StartUp→プロデュース再開→Day5 继续                                                                                                     |
| 05:45-06:00 | Day5-6 自动推进；R2 対局两位数锚 ROI 太窄（12 box[29,66,72,47] 宽于预估）→R1 版 Play 误跑 R2 页 turn_counter_unreadable×3→修复：Round2Flag ROI [20,55,100,60]+Play ROI_TURN 同步放宽                       |
| 06:00-06:30 | R1 出牌完成→応援棒→Interval→R2 優勝条件→R2 出牌 12T（P 饮料弹窗残留 turn None stop 一次→turn None 分支加 dissolve 自愈）                                                                                   |
| 06:35-07:10 | R2 敗退→再挑戦確認→終了→スター性→評価→MEMORY→完了→詳細→イテム→HIF 報酬（次へ点击段内多次丢失，段间接力推进）                                                                                               |
| 07:15       | **回到主页面 ✓ 轮 1 完整走完**（探索轮：含手动干预 8 次，符合轮 1-2 探索优先设计）                                                                                                                         |

### 是否按要求操作

- 主线：培育 Day1-6→R1 出牌→R2 出牌 12T→敗退→结算→メモリー→**主页面** 全通 ✓
- 危险操作：无（×タイトルヘ/再挑戦/ガシャへ 均未误触；ガシャ広告页未出现于敗退流）
- USE_P_DRINK 拦截：生效（初星黒酢/センブリソーダ 记录不点）✓
- p_drink_obtained 库匹配落盘 ✓（goal 1.6 実証）

### 意外 + 根因 + 修复（轮 1 新增 bug 清单 #14-22）

| #   | 现象                                   | 根因                                                              | 修复                                                               | 验证                 |
| --- | -------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------ | -------------------- |
| 14  | 本戦 tab/プロデュース終了 IPC 点击丢失 | adb 点击偶发静默丢失（入场动画窗口）                              | RetryConfirm 加 SETTLE_DELAY；入口 tab 手动+FinalModeFlag ROI 修正 | 部分手动             |
| 15  | 変卡页"hang"×3（实为空转）             | ItemGainFlag 泛锚「獲得」吸住変卡页（说明文在 ROI），循环无效点击 | 锚收窄「イテム獲得」；変卡 reroll=0 预防                           | 修复后変卡自动跑通 ✓ |
| 16  | 変卡源卡 scroll_back_failed 循环       | 段重启时残留カスタマイズ確認弹窗挡网格扫描                        | 源卡 Custom 入口弹窗接管（チェンジ (520,1157)）                    | ✓                    |
| 17  | 日付変更页卡死×5 段                    | 无节点+ROI 错位（文字 y1036 vs ROI y200）+挂载第 29 位 90s 轮不到 | DayChangeBlank+ROI [30,930,500,160]+前移                           | ✓                    |
| 18  | 游戏画面冻结（非管线）                 | Unity 卡死（64s 零像素）                                          | force-stop 重启+プロデュース再開续跑                               | ✓                    |
| 19  | R2 两位数锚 miss→R1 版误跑 R2 页       | 12 box[29,66,72,47] 宽于 ROI [35,60,55,55] 右界                   | Round2Flag/ROI_TURN 放宽 [20,55,100,60]                            | ✓                    |
| 20  | P 饮料弹窗残留→turn None stop          | 槽探测弹窗渲染慢关失败（开局重入时）                              | turn None 分支加 \_dissolve_blocking_overlays                      | ✓                    |
| 21  | 報酬页次へ段内点击丢失                 | IPC 点击丢失+次へ×2 多页                                          | 段间接力+手动 3 连点过                                             | 待轮 2 验证自动路径  |
| 22  | 开场コミュ无节点                       | HIF 管线缺コミュ SKIP 处理                                        | 手动 SKIP；缺口记录（低频：仅局首）                                | 缺口                 |

### 决策接口检查（轮 1 增量）

- p_drinks：P 饮料三选一（hif_drink_reward confirm）+获得捕获（p_drink_obtained）+上限取舍全链 ✓
- 変卡：select_change_source_deck deck_snapshot 落盘 ✓（全库扫描+名称归一）
- R2 出牌：round2 tag 12 回合参数化実証 ✓

## 轮 2：探索+稳健化（2026-08-22 07:30-11:20，完整走完）

### 结果

培育 Day1-6→R1 出牌→Interval→R2 出牌 12T→敗退→再挑戦確認→结算→メモリー→報酬序列→**主页面** ✓（含手动干预 ~6 次）

### 用户 grill 四裁决与落地（本轮核心产出）

| 裁决                               | 落地                                                                                                                                               |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 変卡扫描判底 bug（只读一排即断底） | 整屏确认模式重写（滚动后读完整屏，全部∈已见才到底）；+4 单测                                                                                       |
| 操作日志（点击坐标+结果截图）      | \_tap/\_swipe/\_key 守卫链全量替换直调（ops JSONL+前后指纹对比+ops/ 截图）                                                                         |
| 死循环系统性守卫                   | GuardedTapAuto（锚验证→指纹→点击→验证，3 次无变化 False）+GiftTalk/DayChange 换装+泛词锚尾部铁律                                                   |
| 每个动作加超时                     | \_wait_job(done 轮询 15s)+截图 20s+Round deadline 1500s；**超时链盘点后收紧**：ScheduleRoot 90→75s、\_wait_round_exit 60→20s、段 timeout 1700→900s |
| 重试次数                           | 段接力停滞检测（**页面关键词签名**去 OCR 噪声，连续 2 段即停+证据包含最近节点名）；action 内重试上限全覆盖                                         |
| 非必要不用 OCR（模板优先）         | 首模板 hif_next_button.png（報酬次へ，1.0 自匹配）；OCR→模板 33 节点改造计划批准（轮 3 开发轮执行）                                                |

### 新增 bug 清单（#23-31）

| #   | 症状                                       | 根因                                                                                                          | 修复                                                                    |
| --- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 23  | 報酬页「卡死」多段不推进                   | **報酬是同构子页序列**（獲得アイテム→アチーブメント→…），中间页无锚；OCR 拆词 プロデース≠プロデュース 又 miss | RewardPageNextAuto 序列推进（循环点次へ到消失）+锚变体+**次へ按钮模板** |
| 24  | R2 后期 turn_counter_unreadable 循环       | buff 带行（37ターン）挤入 turn ROI 混读 M21；残り数字在圆环指示器内白字深蓝底 OCR 直读不出                    | 合法性校验（0-13）+圆环区 [15,40,100,80] crop 放大重读                  |
| 25  | 覚醒弹窗+P 饮料弹窗堆叠挡画面              | P item 触发演出自动弹+堆叠；dissolve 固定坐标 X 点击 IPC 丢失                                                 | dissolve ×OCR 锚定（box 中心）+4 次/2s 循环                             |
| 26  | 段重入反复点瓶位（用户观察「尝试喝饮料」） | 每段 reset 清槽缓存→重探測点瓶位弹窗                                                                          | p_drink_slots 跨段保留（reset 不清）                                    |
| 27  | 再挑戦確認終了点击丢失×2                   | IPC 点击丢失高发位                                                                                            | SETTLE_DELAY 2.0+MAX_ROUNDS 8                                           |
| 28  | 40s 收紧饿死尾部锚                         | 32 节点轮询一圈≈60s，RewardPageFlag 第 11 位轮不到就段退                                                      | timeout 40→75s（一圈+余量）——**超时收紧必须先量轮询一圈耗时**           |
| 29  | 停滞检测被噪声绕过                         | OCR 前缀噪声（34H.1.F vs 2H.1.F）让逐字比较永不相同                                                           | 页面关键词签名（日文词≥2字排序）比较                                    |
| 30  | 遊戏凍結（延续#18）                        | Unity 卡死                                                                                                    | 已有处置（force-stop 重启续跑）                                         |
| 31  | RewardPageNextAuto 前 GuardedTap 单击不过  | 报酬页防抖/列表展开延迟假象——实为 #23 序列问题误诊                                                            | 序列推进模式覆盖                                                        |

### 実機验证达成项

- p_drink_obtained 庫匹配落盘 ✓（goal 1.6）
- 変卡整屏判底（轮 2 変卡多次触发，deck_snapshot 落盘）✓
- GuardedTap/操作日志链/超时层/停滞检测全部実機生效 ✓
- hif_next_button 模板（OCR→模板路线首件）✓

## 轮 3（开发轮：flag 记录+模板化）

## 轮 3（待跑）

## 轮 4（待跑）

## 轮 5（待跑）

### 轮 3 开发轮结果（2026-08-22 10:30-11:55，完整走通）

培育→R1 出牌→Interval→R2 12T→敗退→再挑戦確認→结算→メモリー→報酬序列→**主页面** ✓（手动干预 3 次：差し入れ开场对话×2、終了坐标、報酬次へ验证）

**模板产物（4 件+2 节点）**：

- `hif_event_countdown.png`（纯标签带，勿含天数数字——#32 漂移）→ EventFlag 换装
- `hif_gift_title.png` / `hif_drink_reward_title.png` → GiftTalk/DrinkReward 素材
- `hif_dialog_nameplate.png`（姫崎莉波名字框，对话页专属正 1.0 负 4 miss）→ **DialogBlank 新节点 pos4 前挂**（差し入れ多段对话高频卡点根治）
- **CardDetailCloseFlag**（pos0 前挂）：出牌点卡误开「スキルカード詳細」弹窗（毛玻璃遮全画面致所有锚 miss 段退；vision 実測閉じる (360,1180)）

**bug 清单新增（#32-36）**：

| #   | 症状                               | 根因                                                                                                                                  | 修复                                                                                                                       |
| --- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 32  | EventFlag 模板 6日→3日失效         | 模板含天数数字区漂移                                                                                                                  | 重裁纯标签带（跨天数双正例验证）——**模板勿含变化内容**                                                                     |
| 33  | 差し入れ事件多段对话卡死           | 台词 OCR 读不到（低对比图形字）→停滞签名恒同+GiftTalk 尾挂一圈 60s 推进一格                                                           | DialogBlank 专用节点（名字框模板前挂 pos4 连点）                                                                           |
| 34  | 出牌中「スキルカード詳細」弹窗全遮 | 点卡误开详情+毛玻璃遮全部锚→PlayFlag 不可达（Custom dissolve 够不着）                                                                 | **管线层** CardDetailCloseFlag pos0（弹窗类必须管线层可达，Custom 内自愈只对 Custom 可达时有效）                           |
| 35  | 再挑戦終了/報酬次へ agent 点击连丢 | ①pill 按钮 hitbox 内缩（vision 実測：OCR box 只是文字区，几何中心下方 ~21px）②段启动入场动画窗口 agent 点击静默丢失（手动同坐标即中） | 坐标改按钮几何中心（終了 200,1140/次へ 360,1180）+Custom 入场 SETTLE 2s——**视觉按钮点击一律用几何中心，文字 box 中心偏上** |
| 36  | R1 停滞诊断绕弯                    | 只用 OCR+grep 未派 vision（用户纠正）                                                                                                 | 停滞/新页面必派 vision 先行（元素结构/hitbox/遮挡一眼定案——#34/35 均一次定位）                                             |

**vision 工作流确立**（用户质问后）：停滞→snap→vision 先行（页面结构/异常/交互区）→OCR 补文字→修复。実証：#34（毛玻璃+閉じる 位）/#35（hitbox 内缩+几何中心）vision 一次定位，此前 OCR 推理绕 3 轮。

### 轮 4（验证轮①，2026-08-22 12:00-13:20，完整走通）

培育→R1→Interval→R2 12T→敗退→再挑戦→结算→メモリー→報酬序列→**主页面** ✓
**主线零介入**（入口 4 步手动为已知 backlog）；修复 #37-40（単卡 SKIP 兜底/メモリ面板管线关闭/弹窗 y 浮动/獲得アイテム 锚），停滞检测+重试上限全程工作。

### 轮 5（验证轮②，2026-08-22 13:20-14:47，完整走通）

培育→R1→Interval→R2→敗退→结算→メモリー→報酬→**主页面** ✓ **主线零介入**
修复 #41-43（buff 面板管线关闭/受け取る pill 几何中心/灰卡四边环+hand 层过滤）+停滞自愈重试（45s 短段）上线。

### 轮 6（稳定性复验轮，2026-08-22 16:07-17:40，完整走通）

培育→R1 出牌（17 手）→Interval→R2 出牌（21 手）→R2 結果（264,072 点）→敗退→再挑戦確認 produce_end→结算→メモリー→報酬→**主页面** ✓ **主线零介入（连续第三轮）**

- 段驱动 48 分钟（16:31-17:19，六段接力：done 4+timeout 2，超时段均无损接管）；入口段逐步采证（プロデュース→本戦大按钮 (550,890)→次へ→プロデュース開始，含点击丢失 1 次+通信エラー リトライ 1 次，リトライ后服务端已受理直接落地 Day1，本局无開場コミュ）。
- 量化：决策 66 条 / ops 392 次（click 257+swipe 135）**scene_changed 全 True（零无效操作，守卫链连续三轮全绿）** / stop 仅 4 次且全为 `turn_counter_unreadable` 段边界瞬态（段重入落演出半渲染窗口，均下段自愈）。
- 出牌策略行为实录：山札计数守护全程生效；好调凑憧れ続けた輝き+自然体の魅力 1000% 终结技收尾；スリリング/仕切り直し/スポットライト 抽卡压缩山札；体力告急（20）无 P 饮料降级 SKIP——USE_P_DRINK 拦截语义正确。
- 新增 bug #45-47（#44 已被轮 5 exec_verified 闭环占用）：#45 turn 段边界瞬态（**已修**：`_wait_turn_reframe` 指纹区分演出/真异常+`ROUND_EXIT_ANCHORS` 常量共用）；#46 ROUND_DEADLINE_S 定义未检查（**已修**：循环头超时 stop `round_deadline_exceeded`）；#47 通信エラー设备级弹窗（暂缓，待実機取证模板）。修复后 pytest 七件套 215 passed。
- 详细步骤记录与证据路径：`debug/autodev/round6-steps.md`（不入库）。

### 轮 7（修复验证轮，2026-08-22 17:45-18:30，完整走通）

培育→R1 出牌（14 手）→Interval→R2 出牌（14 手，自然体の魅力 1000% 终结技）→R2 敗退→再挑戦確認 produce_end→结算→メモリー→報酬→**主页面** ✓ **主线零介入（连续第四轮）**

- 6 段接力 31 分钟（轮 6 48 分钟）；入口 5 步含**本局開場コミュ SKIP**（轮 6 无、轮 7 有——频率不定，遗留 #7 缺口实证，SKIP box [177,1185,81,29]→tap (217,1212)）。入口坐标复用轮 6 校准值全部一次命中。
- **#45 验证 ✓**：turn_counter_unreadable stop 轮 6 基线 4 次→**0 次**；自愈路径（「turn 读空但画面在动」）未触发（段边界未落在演出窗口），无回归，正面案例待未来轮次。
- **#46 验证 ✓**：round_deadline_exceeded 不误触。
- **#48 新发现已修**：変卡页与授業页**共享左上「授業」HUD**（両页顶部 OCR 实证完全一致）——変卡 Flag 长句锚 miss 时 ClassOptionFlag 误命中変卡页，选项过滤全空→no_safe_option stop（17:52 一次，段接力自愈）。2026-08-15 已知问题完整修复：`_handoff_to_change_flow` 自检放行（OCR「チェンジ」命中即 return True 交回路由，3 次上限防 [JumpBack] 回环死循环），`class_options_not_found`/`no_safe_option` 两分支都挂；215 tests 全绿，実機复验待下轮変卡时点。
- 详细步骤与证据：`debug/autodev/round7-steps.md`（不入库）。

### 轮 8（单步驱动验证轮，2026-08-22 19:06-20:11，完整走通）

**单步模式**（区别于轮 4-7 的 segment_loop 自动接力）：入口 4 步每步 tap→snap→OCR 验证；主线逐段 hif_run（段退出→人工验证画面+决策→修复→再发下一段），共 5 段。主线：入口→Day1（授業/三选一/変卡正当流/差し入れ事件/相談）→R1 出牌（21 手）→Interval→R2 出牌（19 手）→敗退→produce_end→報酬→**主页面** ✓，**零 stop（连续第二轮）**。边跑边修 2 bug（单步模式价值实证：自动接力会掩盖/重试掉这两处故障）：

- **#49 GuardedTapAuto anchor_expected 双重转义**：节点 param 从 recognition.expected 复制 `.*差し入れ.*`（regex），`_find_text_option` 按**字面量**约定 re.escape+再包装 → IPC 实发 `.*\.\*差し入れ\.\*.*`（匹配字面串）→ 进门恒 miss → 无日志 return False → Action.Failed 段退（段 1 GiftTalkBlank 234ms 单次失败实证）。修复三件：管线 `GiftTalkBlank`/`DayChangeBlank` 两处 anchor_expected 去通配符改字面量；action 侧剥首尾 `.*` 归一化（防复制复发）。実機验证 ✓：段 2「守卫点击: 第 1 次点击推进成功(anchor_gone=False)」。
- **#50 StatePanelCloseFlag 泛锚误吸饮料上限弹窗**：pos0 关闭组锚「消費体力減少」在 Pドリンク所持上限弹窗的饮料 buff 描述（「消費体力減少3ターン」）也命中 → 裸 Click (360,755) 无效+JumpBack 回环 → `DrinkOverflowFlag`（原 28 位）永远轮不到 → agent 静默（管线层循环零 agent 日志，铁律③管线版实证）。修复：DrinkOverflowFlag（弹窗专有锚「Pドルンク所持上限」）提到关闭组前 pos0。実機验证 ✓：段 3/4 弹窗取舍成功 ×2（remain=0 残す）。
- 変卡**正当流程**完整走通（整屏确认判底 14 张+源卡选定「大胆不敵」）；但 #48 誤入自愈场景未触发（正当流程不走 `_handoff_to_change_flow`），继续待复验。
- **#51 変卡源 fallback 盲选吃掉 SSR**（轮 8 后用户复盘发现）：名单（大胆不敵/始まりの合図，両 SR 弱卡）耗尽后 `fallback_first_cell` 盲选**牌库第一格**——而 deck 首格恰是 SSR 核心卡「夏夜に咲く思い出」（除外眠気+使用数追加引擎卡）。実機轮 8 変卡③将其変掉；历史 JSONL 同模式 6 次（每次名单耗尽都吃 deck[0]/[1]）。両次変卡本体执行正确（横幅「大胆不敵を魅惑の視線にチェンジしました」等実証）。修复：`_pick_source_by_list` fallback 改「SSR 保护（master rarity join）+ 关键词表评分选**最低分**效果卡」，mode 标记 `fallback_lowest_score`；CardMeta 加 rarity 字段。実機复验待下轮変卡名单耗尽时点。
- 量化：75 决策（授業 4/変卡 12/日程 5/R1 21/R2 19/饮料上限 2/相談 1）；ops 365 次 scene_changed 全 True 率 99.7%（唯一 false=20:06:23 R2 出牌动画瞬态，后续手正常）；215 tests 全绿（含 #50 排序断言更新）。
- 段日志：`debug/autodev/round8_seg1-5.log`（seg1 Failed=#49、seg2 手动停=#50 排查、seg3/4 TIMEOUT=出牌 900s 截断正常接力、seg5 DONE）。

### 轮 9（入口自动化+主线验证轮，2026-08-23 00:47-02:05，完整走通）

**Produce 任务全自动**（含入口链，首次）：ProduceStart(プロデュース)→ProduceMainPage→ChooseScenario(学園祭卡 hif.png)→ChooseDifficulty(DirectHit)→ProduceEntryHIF→PrepRoot→FinalModeAuto(本戦 tab)→準備段→Day1-6（授業/三选一/変卡×2/相談/低体力おでかけ）→R1 出牌（16 手）→Interval(終了)→R2 出牌（17 张）→敗退→再挑戦確認→结算→メモリー→報酬→**主页面** ✓ **主线零介入（入口 4 步首次零手动）**。四段接力（1500/80/900/900s，実機净时约 56 分钟含排障，纯主线约 41 分钟）。

- **#58 build_produce_override 合并顺序 bug（入口断链真根因）**：hif_run 按选项顺序交替合并 default+chosen case，后续选项「跳过选择偶像=No」的 default 把「培育难度=HIF」chosen 的 `ProduceChooseDifficulty.next=ProduceEntryHIF` 覆盖回初流程链（maafw post_task 实发 override JSON 实证）→Difficulty DirectHit 后进初流程偶像选择链→PrepRoot 锚全 miss→25s Failed。修复：两轮合并（先全部 default 再全部 chosen）。
- **#59 tasks HIF case cn/base 分叉**：cn 版缺 `ProduceLoop.on_error→ProduceEntryHIF`（局中兜底）；base 版 `ProduceStart.next→ProduceEntryHIF` 为**有害键**（実機证明プロデュース按钮先进活动选择页，必须经 ChooseScenario 点学園祭卡，直跳 ProduceEntryHIF 会跳步致锚 miss）——删除。遗留 item 1「入口链自动化」就此关闭（轮 2 时三故障中本 chain 从未実機走过，真根因是 override 顺序 bug 而非 Produce.json 链路）。
- **#60 ScheduleRoot 缺 R1 结束序列锚**：R1 出牌 1500s 段尾截断落在ラウンド1結果页，ScheduleRoot 无锚→UnknownStop（轮 6-8 段时长恰好未在 R1 尾截断故未暴露）。修复：ScheduleRoot 补 `[JumpBack]` Round1ResultFlag/Round1StarGainFlag/CheerStickBlank 三锚（専有词已查共显）。
- **#61 Round1SummaryFlag「審査基準」锚跨页共显乒乓**（#60 修复引入、当场实证撤除）：Interval 页右上角有「審査基準」R2 预览标签（同词同位）→SummaryFlag 反复点开弹窗、R2ConditionFlag 反复关闭，900s 段全烧在乒乓（hit 流实证両锚交替）。铁律③再实证：**挂锚前必查他页共显**，本例「審査基準」在 R1 概要页与 Interval 页右上位共显。
- 工具改进：`maa_dev.py test-node` 默认 override 清空 next 链（post_task 跑完整任务链，路由节点连测会推进游戏页面——轮 9 实证误入初流程準備页；`--follow-chain` 显式放开）。
- 复验：**#52 ✓**（変卡×2 `relocate=direct` 直达 1 次点击）；**#54 ✓**（exec_verified 37 条 false=0，buff 手误报清零）；#50 路径 ✓（饮料上限取舍 ×2）；#51 部分（`mode=named` ×2，名单未耗尽 fallback 未触发）；#48 誤入场景未自然触发。
- #55 実機证据补录：`HIF SP效果卡: 最高分 0 [无命中]「ンス上昇+13」`（OCR 拆词「ダンス上昇+13」→词表不覆盖）。
- 已知模式再现实证（未修，观察）：R2ConditionFlag 裸 Click (360,1150) 静默丢失 1 次（重路由再点自愈，约 1 圈延迟）；「好調行模板定行失败 session 兜底=None」warn 多次（好調行识别 fallback）；「reprise 旧源(右上,疑 P item 误标)」warn 多次（diff 后切换自愈）。
- 量化：决策 75 条（R1 16+R2 21+授業 7+日程 6+変卡 11+饮料 4+相談等）；ops 358 次（click 282+swipe 76）**scene_changed 100% 全 True（零无效操作，超轮 8 的 99.7%）**；pytest 290 passed；replay 基准绿。
- 段日志：`debug/autodev/round9_entry_test.log`（断链复现）/`round9_entry_test2.log`（修复后段1）/`round9_seg2-4.log`（不入库）。

### 轮 10（达标轮 1，2026-08-23 02:14-02:51，完整走通，実機净时 35 分钟整）

**Produce 全自动两段接力**（1500s+600s timeout 均正常截断接力）：主页面→入口链（FinalModeAuto ✓ 二连）→Day1-6（変卡×3 均 named+direct）→R1（14 手）→R1 結果→**Interval 直达（零乒乓，#61 修复实证）**→R2（22 手，SELECT 重试 2 次后自愈）→敗退→再挑戦確認→结算→メモリー→報酬→**主页面** ✓ **零 stop 零介入零手动（第 1 个纯验证达标轮）**。

- **#55 修复落地**：SP 效果卡关键词全 0 时数值兜底——行内「上昇+N」正则累计作分数（轮 9/10 両轮実機证据「ンス上昇+13/+17」拆词丢ダ不命中词表→全 0 盲选；現选数值最大行）。待下轮実機验证（应见日志 `最高分 >0 [上昇数値+N]`）。
- 复验维持：#52 ✓（変卡 named+direct ×3）/#54 ✓（exec_verified 36 条 false 2——両条均为「退可用首张」场景如实报告，非误报回归）。
- #51 fallback 仍未触发（名单卡大胆不敵/始まりの合図持续在库）。
- 量化：决策 71（R1 14+R2 22+変卡源 6+授業 5+日程 6+饮料 4+…）；ops 382 次 scene_changed **100%**（连续第二轮全绿）；pytest 290 passed。
- 段日志：`debug/autodev/round10_seg1-2.log`（不入库）。

## 验收对照（goal 七条件）

| 条件         | 结果                                                | 证据                                                                                                                                                         |
| ------------ | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 读取件全绿   | **部分达成**                                        | p_drinks ✓（槽探测+库匹配+JSONL）；p_drink_obtained ✓；p_items 弹窗结构取证+读取件就绪（入口坐标待実機校准，miss 降级）；deck 查看器 UI 未取证（假设位降级） |
| 主线连通     | **达成**（2 轮零介入，按 2026-08-22 裁决由 3 改 2） | 轮 4/5 主线全自动 培育→R1→R2→结算→メモリー→主页面；敗退流；唯一手动=入口 4 步（Produce 链→HIF 接线 backlog）                                                 |
| 决策接口就绪 | **达成**                                            | state 含 p_items/p_drinks/deck ✓；审计报告（决策点 20/覆盖链/strategy 接口/消费路径/缺口 9 项）`decision-interface-audit-2026-08-22.md`                      |
| 游玩树成型   | **达成（主线）**                                    | game-tree.md：主线 63 节点全入树+vision 元素识别；Interval 商店/特別指導/再挑戦/メモリー再生成分支=探索待办（下方遗留清单）                                  |
| 复盘完整     | **达成**                                            | 本文档轮 0-5 各节+bug 清单 #1-43；debug/decisions（决策+ops JSONL+截图）+debug/autodev journal 全程留痕（不入库）                                            |
| 回归通过     | **达成**                                            | pytest 全量 215+（四件套+five_round_readers+session_state）；replay/ruff/prettier/check_resource 终轮见下                                                    |
| 提交完成     | **达成**                                            | 分阶段 19+ commit 到 feat/pipeline-autodev（未 push）                                                                                                        |

## 遗留清单（后续会话）

1. ~~**入口链自动化**~~ **已关闭（2026-08-23 轮 9）**：真根因为 build_produce_override 合并顺序 bug（#58）+cn/base case 分叉（#59）而非 Produce.json 链路；Produce 任务全自动走通（FinalModeAuto→準備→Day1），入口 4 步零手动
2. P item 详情入口坐标校准（実機縦列图标位+SoM 定位）
3. 牌堆查看器実機取证（山札/捨て札指示器位置）
4. 探索分支：Interval 商店流（4 tab/リフレッシュ/特別指導三步流/回復/チェンジ——轮 9 実機 Interval 页到位但終了策略直接跳过，现场已有截图可勘察）、再挑戦重打、メモリー再生成/変換、R2 勝利流、ログ页手札情報（roundsim 校准源）
5. 灰卡阈值実機校准（首次触发日志带 sat 值）
6. USE_P_DRINK 瓶位语义（A5 未定案，现拦截只记录）
7. 開場コミュ SKIP 节点（低频：仅局首；轮 6 実測本局无開場コミュ，出现频率待观测）
8. 通信エラー设备级弹窗管线节点（轮 6 #47：培育中触发时 ScheduleRoot 全 miss 不收敛；待実機取证弹窗模板后挂 ScheduleRoot 前部）
9. 轮 6 修复（#45/#46）実機复验：#45 已验无回归+零 turn stop（轮 7），正面自愈案例仍待触发；#48 変卡誤入自愈（`_handoff_to_change_flow`）待誤入时点复验（轮 8/9 変卡正当流程走通≠誤入场景，自愈路径仍未触发）
10. StatePanelCloseFlag 泛词锚面（「消費体力減少」「スキルカード追加発動」）：#50 后饮料弹窗已让位专有锚，但两词仍可能在其他含 buff 描述的弹窗/页面共显——新弹窗类型出现时优先换专有词锚而非依赖排序让位
11. #51 変卡源 fallback 改评分版待実機复验（名单耗尽时点）：轮 9 両次変卡均 `mode=named` 未触发；应见日志 `mode=fallback_lowest_score` 且源卡为非 SSR 低分卡；若全库 SSR 仍会退第一格（変卡必须选源）
12. ~~#52 変卡重定位滚动直达待実機复验~~ **已验 ✓（2026-08-23 轮 9）**：`relocate=direct` ×2（正常路径 1 次点击）
13. 轮 8 复盘增量三件（2026-08-22）：~~#54~~ **已验 ✓（2026-08-23 轮 9：exec_verified 37 条 false=0；轮 10 false 2 条均为退卡场景如实报告）**；~~#55~~ **已修（2026-08-23 轮 10：数值兜底，実機验证待下轮）**；#56 turn/总分读数偶发误读（读数加单调性/连续性校验——性价比一般暂缓）；#57 interval/consult/retry 决策缺 chosen 字段+R1 turn1 首手无记录（JSONL 字段规范化——性价比一般暂缓）
14. 轮 9 观察项（2026-08-23，未修）：R2ConditionFlag 裸 Click 静默丢失 1 次（重路由自愈约 1 圈延迟，可挂 GuardedTapAuto 化）；「好調行模板定行失败 session 兜底=None」warn 反复（好調行识别 fallback 链路）；「reprise 旧源(右上,疑 P item 误标)」warn 反复（diff 后切换自愈）；Interval 商店流勘察素材已备（轮 9 snap）
