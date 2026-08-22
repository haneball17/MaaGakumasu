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

## 轮 1：探索优先（2026-08-22 02:30-07:15）

### 时间线（要点）

| 时间 | 事件 |
| --- | --- |
| 02:30-02:55 | 入口段失败×3：StartUp 在主页 miss（改 --produce-only）；Produce 链不认日程页（改 --entry ScheduleRoot）；本戦 tab 点击丢失（手动）；FinalModeFlag ROI 右界截断「本戦」box 2px（ROI 放宽 [140,850,500,80]） |
| 02:55 | Day1 开场コミュ页 SKIP 手动（HIF 管线无コミュ节点，记录缺口） |
| 03:05-03:49 | Day1-3 自动推进：授業选项/日程选择/差し入れ事件（对话页无节点手动+补 GiftTalkBlank 节点）/P 饮料三选一/上限取舍/**p_drink_obtained Custom 実証**（goal 1.6 ✓） |
| 02:44-04:30 | **変卡"hang"三次**（实为 ItemGainFlag 泛锚「獲得」吸住変卡页循环点击空转）→根因修复：锚收窄「イテム獲得/アイテム獲得」+変卡 reroll=0（预防性） |
| 04:30-04:39 | 変卡源卡 scroll_back_failed 循环（残留カスタマイズ確認弹窗挡网格）→修复：源卡 Custom 入口弹窗接管（锚 y484 校准+点チェンジ (520,1157)） |
| 04:40-05:25 | 日付変更演出页卡（无节点+ROI 错位 y1036+挂载位太深 90s 轮不完）→修复：DayChangeBlank+ROI+前移横切节点（TapNext/DayChange/GiftTalk 至 pos 3-4） |
| 05:25 | **游戏画面冻结**（64s 零像素变化，Unity 卡死）→ force-stop 重启游戏→StartUp→プロデュース再開→Day5 继续 |
| 05:45-06:00 | Day5-6 自动推进；R2 対局两位数锚 ROI 太窄（12 box[29,66,72,47] 宽于预估）→R1 版 Play 误跑 R2 页 turn_counter_unreadable×3→修复：Round2Flag ROI [20,55,100,60]+Play ROI_TURN 同步放宽 |
| 06:00-06:30 | R1 出牌完成→応援棒→Interval→R2 優勝条件→R2 出牌 12T（P 饮料弹窗残留 turn None stop 一次→turn None 分支加 dissolve 自愈） |
| 06:35-07:10 | R2 敗退→再挑戦確認→終了→スター性→評価→MEMORY→完了→詳細→イテム→HIF 報酬（次へ点击段内多次丢失，段间接力推进） |
| 07:15 | **回到主页面 ✓ 轮 1 完整走完**（探索轮：含手动干预 8 次，符合轮 1-2 探索优先设计） |

### 是否按要求操作

- 主线：培育 Day1-6→R1 出牌→R2 出牌 12T→敗退→结算→メモリー→**主页面** 全通 ✓
- 危险操作：无（×タイトルヘ/再挑戦/ガシャへ 均未误触；ガシャ広告页未出现于敗退流）
- USE_P_DRINK 拦截：生效（初星黒酢/センブリソーダ 记录不点）✓
- p_drink_obtained 库匹配落盘 ✓（goal 1.6 実証）

### 意外 + 根因 + 修复（轮 1 新增 bug 清单 #14-22）

| # | 现象 | 根因 | 修复 | 验证 |
| --- | --- | --- | --- | --- |
| 14 | 本戦 tab/プロデュース終了 IPC 点击丢失 | adb 点击偶发静默丢失（入场动画窗口） | RetryConfirm 加 SETTLE_DELAY；入口 tab 手动+FinalModeFlag ROI 修正 | 部分手动 |
| 15 | 変卡页"hang"×3（实为空转） | ItemGainFlag 泛锚「獲得」吸住変卡页（说明文在 ROI），循环无效点击 | 锚收窄「イテム獲得」；変卡 reroll=0 预防 | 修复后変卡自动跑通 ✓ |
| 16 | 変卡源卡 scroll_back_failed 循环 | 段重启时残留カスタマイズ確認弹窗挡网格扫描 | 源卡 Custom 入口弹窗接管（チェンジ (520,1157)） | ✓ |
| 17 | 日付変更页卡死×5 段 | 无节点+ROI 错位（文字 y1036 vs ROI y200）+挂载第 29 位 90s 轮不到 | DayChangeBlank+ROI [30,930,500,160]+前移 | ✓ |
| 18 | 游戏画面冻结（非管线） | Unity 卡死（64s 零像素） | force-stop 重启+プロデュース再開续跑 | ✓ |
| 19 | R2 两位数锚 miss→R1 版误跑 R2 页 | 12 box[29,66,72,47] 宽于 ROI [35,60,55,55] 右界 | Round2Flag/ROI_TURN 放宽 [20,55,100,60] | ✓ |
| 20 | P 饮料弹窗残留→turn None stop | 槽探测弹窗渲染慢关失败（开局重入时） | turn None 分支加 _dissolve_blocking_overlays | ✓ |
| 21 | 報酬页次へ段内点击丢失 | IPC 点击丢失+次へ×2 多页 | 段间接力+手动 3 连点过 | 待轮 2 验证自动路径 |
| 22 | 开场コミュ无节点 | HIF 管线缺コミュ SKIP 处理 | 手动 SKIP；缺口记录（低频：仅局首） | 缺口 |

### 决策接口检查（轮 1 增量）

- p_drinks：P 饮料三选一（hif_drink_reward confirm）+获得捕获（p_drink_obtained）+上限取舍全链 ✓
- 変卡：select_change_source_deck deck_snapshot 落盘 ✓（全库扫描+名称归一）
- R2 出牌：round2 tag 12 回合参数化実証 ✓

## 轮 2：探索+稳健化（2026-08-22 07:30-11:20，完整走完）

### 结果

培育 Day1-6→R1 出牌→Interval→R2 出牌 12T→敗退→再挑戦確認→结算→メモリー→報酬序列→**主页面** ✓（含手动干预 ~6 次）

### 用户 grill 四裁决与落地（本轮核心产出）

| 裁决 | 落地 |
| --- | --- |
| 変卡扫描判底 bug（只读一排即断底） | 整屏确认模式重写（滚动后读完整屏，全部∈已见才到底）；+4 单测 |
| 操作日志（点击坐标+结果截图） | _tap/_swipe/_key 守卫链全量替换直调（ops JSONL+前后指纹对比+ops/ 截图） |
| 死循环系统性守卫 | GuardedTapAuto（锚验证→指纹→点击→验证，3 次无变化 False）+GiftTalk/DayChange 换装+泛词锚尾部铁律 |
| 每个动作加超时 | _wait_job(done 轮询 15s)+截图 20s+Round deadline 1500s；**超时链盘点后收紧**：ScheduleRoot 90→75s、_wait_round_exit 60→20s、段 timeout 1700→900s |
| 重试次数 | 段接力停滞检测（**页面关键词签名**去 OCR 噪声，连续 2 段即停+证据包含最近节点名）；action 内重试上限全覆盖 |
| 非必要不用 OCR（模板优先） | 首模板 hif_next_button.png（報酬次へ，1.0 自匹配）；OCR→模板 33 节点改造计划批准（轮 3 开发轮执行） |

### 新增 bug 清单（#23-31）

| # | 症状 | 根因 | 修复 |
| --- | --- | --- | --- |
| 23 | 報酬页「卡死」多段不推进 | **報酬是同构子页序列**（獲得アイテム→アチーブメント→…），中间页无锚；OCR 拆词 プロデース≠プロデュース 又 miss | RewardPageNextAuto 序列推进（循环点次へ到消失）+锚变体+**次へ按钮模板** |
| 24 | R2 后期 turn_counter_unreadable 循环 | buff 带行（37ターン）挤入 turn ROI 混读 M21；残り数字在圆环指示器内白字深蓝底 OCR 直读不出 | 合法性校验（0-13）+圆环区 [15,40,100,80] crop 放大重读 |
| 25 | 覚醒弹窗+P 饮料弹窗堆叠挡画面 | P item 触发演出自动弹+堆叠；dissolve 固定坐标 X 点击 IPC 丢失 | dissolve ×OCR 锚定（box 中心）+4 次/2s 循环 |
| 26 | 段重入反复点瓶位（用户观察「尝试喝饮料」） | 每段 reset 清槽缓存→重探測点瓶位弹窗 | p_drink_slots 跨段保留（reset 不清） |
| 27 | 再挑戦確認終了点击丢失×2 | IPC 点击丢失高发位 | SETTLE_DELAY 2.0+MAX_ROUNDS 8 |
| 28 | 40s 收紧饿死尾部锚 | 32 节点轮询一圈≈60s，RewardPageFlag 第 11 位轮不到就段退 | timeout 40→75s（一圈+余量）——**超时收紧必须先量轮询一圈耗时** |
| 29 | 停滞检测被噪声绕过 | OCR 前缀噪声（34H.1.F vs 2H.1.F）让逐字比较永不相同 | 页面关键词签名（日文词≥2字排序）比较 |
| 30 | 遊戏凍結（延续#18） | Unity 卡死 | 已有处置（force-stop 重启续跑） |
| 31 | RewardPageNextAuto 前 GuardedTap 单击不过 | 报酬页防抖/列表展开延迟假象——实为 #23 序列问题误诊 | 序列推进模式覆盖 |

### 実機验证达成项

- p_drink_obtained 庫匹配落盘 ✓（goal 1.6）
- 変卡整屏判底（轮 2 変卡多次触发，deck_snapshot 落盘）✓
- GuardedTap/操作日志链/超时层/停滞检测全部実機生效 ✓
- hif_next_button 模板（OCR→模板路线首件）✓

## 轮 3（开发轮：flag 记录+模板化）

## 轮 3（待跑）

## 轮 4（待跑）

## 轮 5（待跑）
