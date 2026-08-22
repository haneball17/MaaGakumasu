# learnings.md — 会话教训滚动记录（上限 10 条）

## 工作流

- [2026-08-21] 症状：汇报「读取层完成」但 buff/P 饮料/P item 枚举全没实现，用户两次抓出；根因：把「第一批完成」汇报成「设计完成」，批次边界没明示；规则：完成度汇报必须对照设计清单逐项标注（实现/验证/未动），分批推进时明说「本批不含什么」
- [2026-08-21] 症状：新读取件未実機验证直接 PlayFlag 集成连测两败；根因：跳过单元验证省的 10 分钟换来两次启动周期+排查；规则：识别新件先 probe 直连单元验证（多轮+修复清零重计）全绿才接管线；复刻版只作首验探路（维护两份逻辑必然漂移），最终以手动实证流程固化版为准
- [2026-08-21] 症状：识别方案设计的关键 UI 约束（P item 随养成增长/饮料格数随亲密度/溢出省略号等）全部来自用户主动告知；规则：设计対局页识别方案前先向用户要已知 UI 约束清单，用户游戏知识是最高优先级事实源
- [2026-08-22] 症状：管线「卡死」三例（変卡/技能卡页）agent 日志全程静默、无 timeout 无报错；根因：[JumpBack] 回环命中即重置轮询永远走不到 timeout，泛词锚在同类页面残留命中+裸点击无效=无限空转；规则：死循环排障第一步查 `debug/maafw.log` 节点事件流（最后连续命中的节点名=元凶），agent 日志静默≠没在跑；泛词锚+空白点击必须 GuardedTap 守卫（AGENTS 铁律）

## 踩坑

- [2026-08-20] 症状：adb click posted:true 但界面无变化；根因：adb/IPC 点击偶发静默失效（実機 2026-08-22 轮1/2 反复出现：本戦 tab/プロデュース終了/報酬次へ）；规则：关键点击后必须用 OCR 锚/画面变化验证，原坐标重试 1-2 次；agent 侧已全量走 _tap 守卫包装（坐标+结果截图+指纹变化落盘 ops JSONL）
- [2026-08-21] 症状：対战页 UI 浮动四连坑（弹窗标题/瓶名随内容浮动、面板入口 y 漂移、关闭锚词与背景同词、swipe 起点被消费）；规则：対局页 UI 一律动态锚定（先 OCR 锚再取锚相对带）；关闭验证锚选背景不出现的词；面板滚动用容器右缘起点；入口坐标从当次枚举动态取
- [2026-08-22] 症状：変卡牌库扫描只读一排即断底（用户実機抓出）；根因：滚动后「首行探针」判底——重叠行（旧屏第三排）必然全命中已见集合即 break，跳过新屏二三排；规则：滚动枚举判底必须整屏确认（读完整屏、全部 ∈ 已见才到底），禁用单行/单点探针预判（AGENTS 铁律）；同类坑：两位数 OCR box 宽于一位数（12 実測 72px vs 一位数 ~55px），ROI 勿按一位数校准后直接复用
- [2026-08-22] 症状：段重启后変卡源卡 scroll_back_failed 死循环、P 饮料弹窗残留挡仪表 turn None stop；根因：段退出/重入時画面残留弹窗（カスタマイズ確認/Pドリンク詳細/buff 面板）遮挡后续识别，Custom 重入不感知；规则：有弹窗交互的 Custom 入口先探测并接管残留弹窗（変卡确认弹窗=直接点チェンジ完成）；读数异常分支（hand 空/turn None）先跑浮层自愈 dissolve 再判失败；游戏画面疑似冻结用两帧像素 diff=0 判定（64s 零变化=Unity 卡死，force-stop 重启续跑）

## 工具链

- [2026-08-21] 症状：MaaMCP run_pipeline 连续调用各带 Custom action 第二次零执行；根因：MCP 自管 agent 子进程拉起竞态；规则：実機 Custom action 连测一律走 `tools/hif_ipc_runner.py`（AgentClient 直连）；MCP 另有数组参数展平/JSONC 拒载/child_exec 劫持三坑（绕法见 AGENTS.md）
- [2026-08-22] 症状：produce_cn.json 选项表缺「Round1 出牌/使用体力药」定义，override 合并空转走了 Observe；根因：produce_cn.json 只含本地化子集，完整定义在 produce.json；规则：build override 时以 produce.json 为底表合并；default_case 可能是 list 需兼容
- [2026-08-22] 症状：双段并行互踩（画面交错 turn12/3 跳变）+taskkill 后孤儿 agent 进程残留；根因：`>/dev/null &` 吞输出看不出段存活，taskkill /T 杀 parent 漏 agent 孙进程；规则：同一模拟器同时只跑一个段；段一律 run_in_background/输出落文件管理；重启段前 `Get-CimInstance Win32_Process` 按 CommandLine 清 `*hif_run*`+`*agent*main*` 全部进程
- [2026-08-22] 症状：maafw Job.wait() 无限阻塞，controller/IPC 卡死时 agent 线程永久挂起；规则：全操作走 _wait_job（done 轮询+15s 超时）已落地；run_recognition 是同步调用无法外部超时——长循环（出牌大包/全库扫描）必须带全局 deadline（Round1Play 45min 上限）；maafw Python `Job.wait()` 无 timeout 参数是接口事实，升级 maafw 前不变
