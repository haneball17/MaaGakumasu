# AGENTS.md

本文件为在本仓库中工作的 AI/自动化代理提供项目上下文与协作规则。修改前请先阅读 `README.md`、`docs/zh_cn/功能说明.md`、`docs/zh_cn/开发相关.md` 以及本文件。

## 项目概览

MaaGakumasu 是基于 MaaFramework 的《学園アイドルマスター》自动化助手，采用 `JSON + 自定义逻辑扩展` 的开发模式。项目主要通过图像识别、OCR、YOLOv11 深度学习模型和模拟控制完成游戏日常、商店、社团、工作、竞赛与自动培育等任务。

目标运行环境以 Windows 为主，推荐 MuMu 模拟器 12，分辨率基准为 `1280x720 (240DPI)`。DMM 版和插件版汉化已适配，但部分组合仍未完全测试。

## 当前进度

最近更新以 `assets/resource/Changelog.md` 的 v1.4.2 公告和最近提交为准；`README.md` 中“等待 NIA 适配”等描述可能滞后。

已实现的主要功能包括：

- 启动游戏、领取活动费、邮箱礼物、任务奖励、每周免费礼包。
- 竞赛挑战，支持指定挑战、自动选择、无编队时自动编队。
- 社团互动，支持自动或指定请求。
- 安排工作，支持领取奖励、自动或指定偶像、指定时长。
- 商店购买，支持扭蛋、金币、AP 购买和自动免费刷新。
- 自动培育处于测试阶段，支持初 `REGULAR/PRO/MASTER`、NIA `PRO/MASTER`、指定偶像、自动选择、体力药、道具、卡片选择优先级、跟随老师建议、初流程失败重试和中断继续。
- Mirror 酱更新、插件版汉化、DMM 版适配、支援卡库存识别、i18n 繁体适配。

HIF（学祭，即学園祭本战）培育为当前活跃开发分支（`feat/hif`），状态为**实机决策闭环到 Round1（观察停止）**：

- 已实机打通 Day1→Round1 全链（2026-08-15 复验）：日程选择（授業色扫分类/公開レッスン/事件模板/低体力おでかけ）、授業选项、P 道具、三选一（饮料/技能卡/変卡目标与源卡）、SP 效果卡、相談、饮料上限取舍均自动决策。
- 三选一采用双评分：卡名命中效果池走结构化评分模型 v2（`agent/hif/decisions/scoring.py`，官方公式对齐的五族曲线），miss 退关键词评分（`decisions/rewards.py`）；未达阈值可重抽，支持名单优先。
- 决策参数覆盖链：GUI 选项 > `debug/decisions/decision_override.json` > 培育倾向基准 > preset 默认（`agent/hif/presets.py`）。
- 全决策点落盘 `debug/decisions/`（截图 + `session-*.jsonl` + 会话状态），`agent/hif/decisions/viewer.py` 自动生成 HTML 查看器，`tools/hif_replay_report.py` 出复盘总表。
- Round1 到达后仅观察初始手牌（`ProduceHIFRound1Observe` 读手牌后 `ProduceHIFRound1ReachedStop` 停止），**不出牌**；出牌策略 `GarakutaRinamiStrategy`（`agent/hif/decisions/play.py`）已实现并有 22 个测试，但未接线实机。
- 评分模型离线链 A/B 已完成（数据 join、双评分回放、Spearman 校准框架，当前 rho≈0.458）；C2 人工调参已被模拟器参数枚举取代（ADR-0001）。
- **Round 模拟器（`agent/hif/roundsim/`）七里程碑完成（2026-08-16，速览表见 `docs/hif/roundsim-implementation-plan.md`）**：ScenarioSpec 三层 + preset⊕override；效果引擎（effect_type 派发、预检硬失败、timer/enchant/condition 全在支持面）；S1 得分（逐级 ceil，kjirou 双算例回归）；专属 P item trigger（憧れ続けた輝き：好調≥8 + 每 4 张好調系卡）与 応援棒补卡；A/B runner（CRN 同批种子 + 対手独立 RNG 流、bootstrap CI、優勝组合模式，CLI `tools/simulate_round.py --ab A,B --n --combined`）；実機回放校验（`tools/calibrate_roundsim.py`：実機総合 475.6 万落点 100% 分位，归因 A9 三围快照/A10 构筑近似，**待実機数据补校准**）；本地 WebUI（`tools/round_sim_app.py` → localhost:8642，Vue3+ECharts 三视图 + 离线渲染 `tools/render_round_ui.py` + TS 契约 `tools/export_roundsim_schema.py`，node ≥22 与 fastapi/uvicorn 为新前置）。莉波 20 张构筑为重构近似（実機逐卡清单未録）；`decisions/play.py` 三修复已落地（SKIP 动作、DRAW/SWAP_HAND 废弃、`pick_playable_card` 具体选卡）。
- 机制知识库 `docs/hif/mechanics.md`（M1 起逐条带 A-D 置信度与実機验证状态）是机制语义的首要依据；数据链同步 gakumasu-diff 主干（`tools/sync_hif_master.py`、`sync_hif_effects.py`、`scrape_hif_tiers.py`）。
- **五轮全程验证完成（2026-08-22，`docs/hif/five-round-validation-2026-08-21.md`）**：主线 培育→R1 出牌→Interval→R2(12T)→敗退/结算→メモリー→報酬→主页面 全链実機走通×5 轮（轮 4/5 主线零介入×2）；Round1Play 参数化（total_turns/round/r2）双 Round 共包；灰卡过滤（四边环饱和度+hand 层）；対局资源读取件（P 饮料槽 ✓/P 道具详情/牌堆=探索待校准）；决策接口 p_items/p_drinks/deck 就绪（审计 `docs/hif/decision-interface-audit-2026-08-22.md`）；bug#1-43 修复沉淀；管线层浮层关闭组 pos0-2（StatePanel/MemAbility/CardDetail——毛玻璃面板挡锚是系统性失败模式）。
- **轮 6 稳定性复验完成（2026-08-22，六段接力 48 分钟主线零介入，连续第三轮）**：ops 守卫链 392/392 全绿；bug#45-47 增量——#45 turn 段边界瞬态已修（`_wait_turn_reframe` 指纹区分演出/真异常）、#46 ROUND_DEADLINE_S 未检查已修（循环头 stop `round_deadline_exceeded`）、#47 通信エラー弹窗暂缓待取证。
- **轮 7 修复验证完成（2026-08-22，六段接力 31 分钟主线零介入，连续第四轮）**：#45 验证 ✓（turn stop 基线 4→0 无回归，自愈路径待正面触发）、#46 ✓ 不误触；新发现 #48 変卡页与授業页共享左上「授業」HUD 致 ClassOptionFlag 誤入（2026-08-15 已知问题完整修复：`_handoff_to_change_flow` 自检「チェンジ」放行回路由+3 次上限防回环死循环），実機复验待下轮変卡时点。
- 仍由 `ProduceHIFUnknownStop` 兜底：探索分支（Interval 商店流/特別指導/再挑戦重打/メモリー再生成/R2 勝利流）与未取证页面；入口段（主页面→活動页→本戦 tab→開始）自动化为遗留 backlog（当前手动 4 步）。遗留清单见复盘文档尾节。
- 特別指導（カスタマイズ）接入点已勘察规划（`docs/hif/customize-integration-notes.md`），暂缓至 Round2 立项。
- 设计依据：`docs/superpowers/specs/2026-07-10-hif-basic-pipeline-design.md`（首版边界）与 `docs/superpowers/specs/2026-08-14-hif-fastpath-routing-design.md`（快慢路径路由，已确认待实机校准实施）；流程依据见 `docs/hif/finals-daily-log.md`。

近期自动培育重点更新：

- NIA 培育流程已上线，任务配置中通过 `培育难度` 选择 `初` 或 `NIA`。
- 新增考试失败自动重试开关 `启用培育失败重试`，当前覆盖初流程的 `ProduceFailedFlag`。
- 新增 `跟随老师的建议` 开关；事件选择逻辑优先参考老师建议，其次检查 SP 课程，再按角色状态、属性阈值、偏好和随机选择机制决策。
- 培育行动优先级、选秀逻辑、工作类型自动选择、商店购买流程、投票阈值、颜色识别和 `homeflag` 黑白模板识别都有近期修复。
- 培育界面资源图片在 `assets/resource/base/image/produce/` 有最近更新。

待实现或未完全完成的内容包括：

- 初 `LEGEND` 培育适配。
- HIF：Round1 出牌接线（`GarakutaRinamiStrategy`（已含 M4 三修复）→ 実機）、実機配合项补录（R1 最終得分/R2 初始状态/Round 卡组计数 → 重跑校准）、快慢路径路由实施、Round2/Interval/结算/メモリー、模拟器参数枚举（取代 C2，`simulate_round.py --ab` 网格扫描）。
- 更多语言与更多自动培育样本覆盖。

截至最近更新本文件时（2026-08-16），工作区存在未提交修改：

- `tools/ci/check_resource.py`、`tools/ci/setup_pip.py`、`tools/simulate_hif.py`、`tools/sync_support_cards.py`、`tools/update_cards.py`：仅 ruff import 长度排序自动修复，无逻辑变化。
- 未跟踪目录：`assets/resource/model/`（YOLO 检测 + PP-OCRv6 OCR 模型，含 `ocr_v3_bak/` 旧版备份，尚未入库）、`assets/resource/test/`、`assets/video/`、`include/`、`lib/`、`sample/`、`share/`、`.venv/`、`.zcode/`、`MaaGakumasu.egg-info/` 等（多为本地环境产物，提交前需甄别）。

不要覆盖或回退这些文件中的现有改动，除非用户明确要求。

## 目录职责

- `agent/`：Python 自定义逻辑扩展，供 MaaFramework 的 Custom recognition/action 调用。
- `agent/custom/action/produce.py`：自动培育事件、商店、选项等自定义动作逻辑，近期改动集中在行动优先级和 NIA 选择策略。
- `agent/custom/action/produce_hif.py`：HIF 培育自定义动作（约 15 个注册 action），读 `custom_action_param` 预设并经覆盖链解析，内联执行 OCR/模板/色扫识别与双评分决策，含决策落盘（`_archive_decision`）、会话状态、流转验证与防循环守卫；未覆盖页面调用 `ProduceHIFUnknownStop` 停止。
- `agent/hif/`：HIF 决策与离线模拟模块，分三块：
  - `decisions/`：实机决策核心。`scoring.py` 结构化评分模型 v2、`rewards.py` 关键词评分、`play.py` 出牌策略（未接线）、`schedule.py` 日程/授業选择、`viewer.py` 决策日志 HTML 查看器、`hand_meta.py` 卡牌元数据查表、`config.py`/`state.py` 数据结构。
  - `algorithms/`：离线模拟器（束搜索、门过滤、状态推进、评价报告），`orchestrator.py` 是编排入口，与实机管线解耦。
  - `adapters/exam_reader.py`：YOLO cards.onnx 定位 + 词典约束 OCR → `ExamState` 适配层；`card_dict.py` 生成 OCR 卡名词典。
  - 顶层 `presets.py`（预设与覆盖链）、`observed_case.py`（実機观测 case schema）、`simulator.py`（facade，re-export `algorithms`）。
- `assets/resource/base/pipeline/`：MaaFramework 任务流水线。自动培育通用核心逻辑在 `Produce.json`，NIA 相关流程在 `ProduceNIA.json`，HIF 相关流程在 `ProduceHIF.json`，共用节点在 `ProduceUtils.json`。
- `assets/resource/base/image/` 或相邻资源目录：模板匹配、图像识别所需素材。
- `assets/resource/model/`：YOLO 检测模型（`detect/cards.onnx`、`detect/choose.onnx`）与 PP-OCRv6 OCR 模型（`ocr/`，旧版备份在 `ocr_v3_bak/`）。
- `assets/data/`：结构化数据，例如偶像卡片数据 `idols_cards.json`；HIF 数据在 `assets/data/hif/`（`skill_cards_master.json` 121 卡全表、`skill_card_effects.json` 效果池、`drink_effects.json`、`drinks.json`、`decision_keywords.json` 关键词表、`produce_decision_data.json` 模拟器输入），由 `tools/sync_hif_master.py` / `sync_hif_effects.py` 从 gakumasu-diff 同步生成，不要手改。
- `assets/tasks/`：MFA/MaaFramework 任务入口与选项定义。培育任务入口在 `assets/tasks/produce.json`，中文任务配置在 `produce_cn.json`。
- `assets/lang/`：界面与任务选项翻译。新增任务选项时同步 `zh-CN` 和 `zh-Hant` 等已有语言。
- `assets/resource/Changelog.md`：发布给用户看的资源更新公告；当前内容已进入 v1.4.2 说明，本轮 HIF 新选项尚未写入公告。
- `docs/zh_cn/`：中文用户与开发文档。
- `docs/hif/`：HIF 文档集。首要依据：`mechanics.md`（机制知识库）、`scenes.md`（场景卡设计真源）、`finals-daily-log.md`（実機证据日志）、`scoring-model-design.md` 与 `scoring-model-implementation-plan.md`（评分模型）、`decision-override.md`（参数覆盖链）、`round1-blockers.md`（已完结）、`autodev-workflow.md` 与 `autodev-research.md`（无人化管线开发工作流与调研存档）。
- `tools/`：维护脚本。HIF 相关：`simulate_hif.py`（模拟器 CLI）、`hif_decision_viewer.py`（决策日志查看器）、`hif_replay_report.py`（复盘总表）、`replay_scoring.py`（双评分回放）、`calibrate_scoring.py`（tier 榜校准）、`scrape_hif_tiers.py`、`sync_hif_master.py`、`sync_hif_effects.py`、`hif_mine_ocr_variants.py`（OCR 变体挖掘）。无人化管线开发工具 `maa_dev.py`（snap/ocr/som/crop/reco/test-node/replay/journal，见 `docs/hif/autodev-workflow.md`）。
- `debug/`：运行日志和调试输出，不应作为功能改动的一部分提交；`debug/decisions/` 是 HIF 决策日志（截图 + JSONL + 会话状态 + `decision_override.json`），同样不入库。
- `deps/`、`install/`：依赖和打包相关内容，修改时需确认发布影响。

## 开发环境

- Python 版本：`>=3.12`。
- Python 依赖：`maafw`、`loguru`、`Pillow`。
- 可选开发依赖：`pytest>=7.0`、`ruff>=0.1.0`。
- Node 侧仅用于工具链，当前 `package.json` 包含 `prettier-plugin-multiline-arrays`。
- Python 包版本信息在 `pyproject.toml`，当前仍为 `1.3.8`；用户可见资源公告已更新到 `assets/resource/Changelog.md` 的 `v1.4.2`。

常用检查命令：

```powershell
python -m py_compile agent
python -m pytest
python -m ruff check .
npx prettier --check "**/*.{json,yml,yaml}"
npx maa-tools check
```

如果本地缺少测试目录或依赖，说明无法完整执行对应检查即可，不要为了通过检查凭空创建无关测试。

无人化管线开发调试走 pipeline-autodev 工作流（`.agents/skills/pipeline-autodev/SKILL.md`）：主 agent 按五角色循环自主完成"探索→裁素材→生成节点→实机连测→回归→报告"，危险操作（扭蛋/购买/确认弹窗/体力药/开战）必须同步等用户确认，超预算（单节点 5 次重试/15 分钟、会话 90 分钟）即停并落盘 `debug/autodev/`（不入库）。坐标裁决铁律：视觉模型只从 SoM 编号叠加图选编号，精确坐标一律取 OCR/模板/YOLO 检测框中心（vision-qwen 裸坐标实测中位误差 26px，2026-08-20 校准）。语义裁决铁律：UI 图标/按钮/数值的语义结论必须经用户指认或実機文本（详情页/日志原文）佐证，vision 的形状描述只作辅助不作依据（2026-08-20 好調图标「天鹅↔力量手势」翻案教训）。実機点击裁决：adb click `posted:true` 不等于生效（偶发静默失效），关键点击后必须用 OCR 锚或画面对比验证，无效先原坐标重试 1-2 次再怀疑坐标。回放基准集在 `tests/replay_suite/`，改动存量节点后必须 `python tools/maa_dev.py replay --suite tests/replay_suite`。详见 `docs/hif/autodev-workflow.md` 与调研存档 `docs/hif/autodev-research.md`。MuMu 的 adb 端口跨会话会漂移，实机操作前先 `adb devices` 查实际端口并经 `MAA_DEV_ADDR` 注入，不要假设 16416。

実機 Custom action 单点连测（不跑完整管线）走 `debug/autodev/round1/ipc_task.py <节点名>`（AgentClient 直连自管 agent 子进程：bind(res)→connect→register_sink→post_task）。不要用 MaaMCP `run_pipeline` 做此事——2026-08-21 实测其 agent 拉起有时序竞态，连续两次调用各带 Custom action 时第二次返回 succeeded 但 action 零执行。配套：interface.json 的 `agent.child_exec: "python"` 在本机被 Microsoft Store 别名劫持，跑前临时 patch 为 `.venv` 绝对路径、跑完恢复（正式 interface 勿留绝对路径）；MCP `run_pipeline` 的 `pipeline_path` 数组参数会被序列化成单字符串（改单文件多次调用 + `on_conflict: overwrite`，节点驻留可累积），`Produce*.json` 为 JSONC 会被其严格 json 预校验拒载（去注释+去尾逗号的 strict 副本绕过）。

実機分段驱动单例纪律（2026-08-22 轮1 双段互踩实证）：同一模拟器**同时只跑一个** hif_run 段——两段并行会交错点击同一画面（现象：画面来回跳变/turn 数震荡），且 `>/dev/null &` 吞输出导致段存活不可见。段一律 run_in_background 或输出落文件管理；重启段前用 `Get-CimInstance Win32_Process -Filter "name='python.exe'"` 按 CommandLine 匹配 `*hif_run*` 与 `*agent*main*` 清光全部进程（taskkill /T 杀 parent 常漏 agent 孙进程成孤儿，孤儿 agent 是下一段的隐形干扰源）。段内「卡死」排障：先查 `debug/maafw.log` 节点事件流（最后连续命中的节点名），agent 日志静默≠没在跑（[JumpBack] 回环死循环在 agent 侧零输出）。

識別新件（读数/枚举/面板交互类 Custom action 方法）的実機验证纪律：先 probe 直连（Tasker.post_recognition 同源调用，参照 debug/autodev/round1/probe_state*.py 模式）做单元验证——每件 ≥3 轮跨画面时点+关键件自一致性双跑，修复后该件轮次清零重计；全绿才接管线集成（2026-08-21 用户叫停「未验证就 PlayFlag 连测」确立，probe2/3/4 三次实践成型）。设计対局页识别方案前先向用户要已知 UI 约束清单（元素数量上下限/位置稳定性/溢出行为/形态随内容浮动）——P item 随养成增长、饮料格数 3-4 由亲密度决定、buff 溢出省略号、弹窗标题随内容浮动四个关键约束全部来自用户告知。

対局页（Round 対战）UI 动态锚定规则（2026-08-21 四连坑实证）：弹窗标题/瓶名随内容浮动（同弹窗不同瓶 y722/838）——先 OCR 锚定位再取锚相对带，禁固定 ROI；面板/buff 行入口 y 随状态增减漂移——从当次枚举动态取；关闭验证锚必须选背景不出现的词（「ターン内」状態带同词曾误报）；面板滚动 swipe 用容器右缘起点 (545,640)（中央起点落可交互条目会被消费致滚动时灵时不灵）；清单条目键去长音符 ー 归一化（ターン内/タン内 OCR 变体）。

## 代码与格式约定

- Python 代码遵循 `pyproject.toml` 中 Ruff 配置：目标版本 `py312`，行宽 `144`，仅启用 `I`（isort）规则且开启 `length-sort`/`length-sort-straight`（按 import 长度排序）。改 import 时注意这一点。
- 大段重写类或函数后，必须 grep 旧标识符（旧常量名/方法名）确认已删除——Python 类体中后定义的方法会静默覆盖前者，旧 `run()` 残留会让新版从未执行且编译/单测全绿掩盖（2026-08-21 変卡重写実機教训，db1c772）。入口方法替换用 `inspect.getsource` 断言新逻辑确实在目标方法内。
- JSON/YAML 使用 Prettier 配置：默认缩进 4 空格，YAML 缩进 2 空格，JSON 覆盖配置使用 tab。
- Markdown 文档遵循 `docs/.markdownlint.yaml`，但根目录 `AGENTS.md` 主要服务代理协作，优先清晰准确。
- 修改 JSON、JSONC 或流水线文件时保持原有排序、注释风格和缩进风格；不要做无关格式化。
- 新增用户可见文案时优先使用中文；涉及游戏内名称时保留日文原名，并在已有数据结构支持时补充中文字段。

## MaaFramework 流水线规则

- 先理解节点的 `recognition`、`action`、`next`、`timeout`、`pre_delay`、`post_delay`、`post_wait_freezes` 与 `focus`，再改流水线。
- `DirectHit` 节点通常用于流程入口或无条件跳转，不要随意替换成模板识别。
- `[JumpBack]` 节点用于在循环中回退重试，修改 `next` 顺序时要考虑优先级和误触风险。
- `TemplateMatch` 应明确模板路径、ROI、阈值和必要的匹配方法。新增模板时使用与现有资源一致的分辨率基准。
- `OCR` 只在文本稳定、语言明确时使用；游戏 UI 文案变动风险较高时优先保留模板或自定义识别。
- `Custom` recognition/action 名称必须与 `agent/` 中实现一致，参数结构要向后兼容。
- next 链尾的 `DirectHit` 兜底节点（如 UnknownStop）会**立即命中**，抢在前序识别节点的渲染等待窗口之前——「等内容渲染」用节点 `timeout`（next 全 miss 时按 timeout 轮询重试）+ `on_error` 兜底表达，不要把 DirectHit 混进会因内容未渲染而 miss 的 next 链（実機 2026-08-20 公開レッスン序列教训）。
- 非 `[JumpBack]` 前缀的子节点执行完成即**终止任务链**；需要执行完继续路由循环的推进节点（点击/翻页类），在引用它的 next 列表里加 `[JumpBack]` 前缀。
- agent 侧把字面文本（卡名/按钮文案）传入 OCR expected 前必须 `re.escape()`（`+`/`.`/`!` 等元字符会被 MaaFW regex_valid 拒掉整个 override）；超过 ~32 项的词典不要经 expected 传输（maafw IPC 对日文大列表有 UTF-8→GBK 乱码风险，5.11/5.12 均有），改为 expected `[".*"]` 全量 OCR + Python 侧子串匹配。
- 自动培育相关改动风险较高。修改 `Produce.json` 时重点验证：
  - 入口与中断继续流程：`Produce`、`ProduceLoop`、`ProduceSkipPreparation`、`ProduceEntry`。
  - 难度入口：`初` 走 `ProduceEntry`，`NIA` 走 `ProduceEntryNIA`；不要把 NIA 覆盖项误合到初流程。
  - 准备阶段：难度、偶像、支援、回忆、道具选择。
  - 培育阶段：事件选择、卡牌选择、饮料、道具、商店、强化、考试失败和结束流程。
  - 失败处理：初流程的 `ProduceFailedFlag` 可根据 `启用培育失败重试` 跳转到重试或停止流程；NIA 流程使用 `ProduceNIAFailedFlag`，当前失败后停止任务。
  - NIA 事件参数：每张卡片通过 `ProduceChooseNIAEventFlag.custom_action_param` 设置 `effect`、`first`、`second`，字段顺序和语义都要保持一致。
  - 弹窗和通用按钮处理：不要扩大 ROI 到容易误触的位置。

HIF 培育采用“Pipeline 页面路由 + Agent 预设动作”分层，改动时严格分层：

- `ProduceHIF.json`（当前约 37 节点）只负责高置信模板/OCR 路由页面，定义顺序、超时、回跳和安全停止；`ProduceEntryHIF` 是唯一入口，`ProduceHIFPrepRoot` / `ProduceHIFScheduleRoot` 是分段路由根。
- `agent/custom/action/produce_hif.py` 负责读 `custom_action_param` 中的用户预设（经 GUI > override 文件 > 倾向基准 > preset 默认覆盖链），识别候选并执行决策后单步点击；三选一类决策走双评分（模型分优先、关键词兜底）。
- 候选未命中、预设字段无效、候选并列无法消歧时，必须调用 `ProduceHIFUnknownStop` 停止并输出状态，**禁止猜测性点击**。
- `ProduceHIFRound1Observe` 只读初始手牌，随后 `ProduceHIFRound1ReachedStop` 停止任务；Round1 出牌（`GarakutaRinamiStrategy`）尚未接线，不要绕过观察停止边界直接接出牌点击。
- Round2Flag、IntervalFlag、ScoreSettlementFlag、MemoryFlag 目前只指向 `ProduceHIFUnknownStop`；实现这些页面时再改出边，保持兜底语义。
- 准备阶段循环子流程用 `[JumpBack]` 返回路由根节点；每个状态节点设置 `focus` 日志（页面名、预设 ID、匹配证据、下一动作）。
- 离线模拟器（`agent/hif/algorithms/` 束搜索与路线规划）与实机决策解耦，不要把未验证的模拟器输出直接接到管线；实机三选一已接的评分模型 v2 改动须跑 `tests/test_scoring_model.py` 并用 `tools/replay_scoring.py` 回放对比。
- 快慢路径路由（`docs/superpowers/specs/2026-08-14-hif-fastpath-routing-design.md`）实施时保持“降级全量”兜底：快路径未命中必须回落全量路由或安全停止，不允许新增猜测性点击。
- 横切页面（弹窗/演出页，可出现在任意行动后，如 P 饮料弹窗、支援卡事件弹窗）双层挂载：主路由根 `ProduceHIFScheduleRoot` 的 next 前部挂全量横切节点保证完备性；子序列宿主（如 `ProduceHIFPublicLessonResultFlag`）只挂已知会在此序列上下文出现的横切节点做快速路径。**子序列宿主的 `on_error` 一律指向上层路由根，禁止直指 `ProduceHIFUnknownStop`**——`UnknownStop` 只保留在最外层主路由的 `on_error`（実機 2026-08-21 结果序列孤岛教训：JumpBack 循环控制流回不到主路由，直指 UnknownStop 会切断收敛路径）。
- Flag 锚在多个页面共有时，页面专属锚必须排在通用锚前面（如 `ProduceHIFStartConfirmFlag` 先于 `ProduceHIFIdolSelectFlag`——步骤条「アイドル選択」文字在步骤 1/2 两页共有）；Custom action 的重试循环内先自检本页锚，锚失活即放行 `return True` 交回路由——转场/LOADING 窗口内 JumpBack 回环会重复路由命中同一 Flag，在未渲染页面上 miss 即 stop 是系统性失败模式（実機 2026-08-21 偶像选择/開始確認/相談三处中招）。
- 无固定文案的封闭池页面（如 P 饮料弹窗，饮料名/效果随种类变）用数据源名称池做 OCR expected 锚（`drinks.json` 29 名称，静态 JSON 定义无 IPC 乱码风险），ROI 收窄到名称一行；不要用框架装饰模板（sparkle/横条在背景页无区分度，実機 2026-08-21 负例 0.875 > 正例 0.847）。
- 泛词锚与空白点击的死循环铁律（実機 2026-08-22 轮 1/2 三例：ItemGainFlag「獲得」吸住変卡页、GiftTalkBlank「差し入れ」标题在事件全部子页面残留、両者均为裸 Click+[JumpBack] 回环）：`[JumpBack]` 回环命中即重置轮询，**永远走不到 timeout**——误命中的裸点击=无限空转且无任何报错。规则：①泛词锚（页面残留标题词：獲得/差し入れ/再開类）必须挂 ScheduleRoot 尾部兜底位或换专有词锚，禁止挂前部抢路由；②空白/中央点击类推进节点必须用 `ProduceHIFGuardedTapAuto`（Custom：锚验证→指纹对比→点击→验证推进，连续 3 次无变化 return False 段退），禁用裸 Click action；③新挂载节点先问「这个词在哪些**其他**页面也出现」再定位次。
- agent 侧操作日志链（2026-08-22 轮 2 grill 裁决）：全部点击/滑动/按键必须走 `_tap/_swipe/_key` 守卫包装（`_ProduceHIFActionBase`）——记录坐标+操作后截图 `debug/decisions/ops/` + ops JSONL（含前后 64x64 指纹对比 scene_changed）；禁止直调 `controller.post_click/post_swipe`（IPC 点击丢失类 bug 复盘全靠此链）。管线侧 Click 节点的坐标在 `debug/maafw.log` 有事件记录可交叉查。
- 滚动枚举类读取（牌库网格/详情面板）判底必须「**整屏确认**」：滚动后读完整屏，全部条目 ∈ 已见才判到底；禁止用「滚动后首行/单点探针」预判——滚动重叠行必然全命中已见集合，会跳过真正的新内容（実機 2026-08-22 変卡牌库只读一排即断底教训）。
- 遮挡全画面的浮层（毛玻璃类：卡详情/メモリーアビリティ/buff効果一覧等）挡掉**全部锚**致路由根全 miss→段循环空退（実機 2026-08-22 四例 #34/#38/#41/#25）：此类浮层必须在 ScheduleRoot **前部有管线层关闭节点**（现 pos0-2 关闭组 StatePanel/MemAbility/CardDetail，锚用面板专有词如「(再演)括号格式」防背景状态带误命中）。Custom action 内的 dissolve 自愈只在其宿主节点可达时有效——「Custom 够不着」是浮层处理的边界，新浮层类型先加管线层节点再考虑 Custom 内兜底。
- 视觉按钮（pill 胶囊形）点击一律用**按钮几何中心**，OCR/小模板文字 box 中心系统性偏上 ~21px 且 hitbox 内缩（実機 2026-08-22 終了/次へ/受け取る三例）；文字 box 只做存在判定。Custom action 首次点击前加入场稳定等待 SETTLE≥2s（入场动画窗口 agent 点击静默丢失，手动同坐标即中）。收紧路由根 next timeout 前必须先量「轮询一圈实际耗时」（节点数×单点识别耗时；模板 ~0.3s vs OCR ~2s），timeout ≥ 一圈+15s——40s 曾饿死第 11 位之后的全部锚。

## 任务配置规则

- 培育任务定义在 `assets/tasks/produce.json`，中文版本在 `assets/tasks/produce_cn.json`；新增或重命名选项时两边都要同步。
- 当前培育选项包括 `培育难度`、`HIF预设`、`培育倾向`、`HIF 决策微调`、`培育偶像`、`培育次数`、`使用体力药`、`使用道具`、`跳过选择偶像`、`启用自动回忆`、`启用关注租借`、`启用培育失败重试`、`跳过准备阶段`、`卡片选择优先级`、`跟随老师的建议`。
- `培育难度` 下 `初` 支持 `REGULAR/PRO/MASTER`，`NIA` 支持 `PRO/MASTER`，`HIF` 跳转 `ProduceEntryHIF`。
- HIF 专属选项：`HIF预设`（安全默认 / 莉波好调实验）、`培育倾向`（好调系/集中系/均衡）、`HIF 决策微调`（17 个输入：preset_id、preference、优先名单、day1~day6 日程序、权重、阈值、重抽上限、低体力百分比、scoring_scale、endgame_weight 等），经 `pipeline_override` 注入 Flag 节点的 `custom_action_param`。
- 任务选项通过 `pipeline_override` 调整节点属性；改选项时必须检查被覆盖节点在 `Produce.json`、`ProduceNIA.json`、`ProduceHIF.json` 或 `ProduceUtils.json` 中是否存在且语义匹配。
- `preset.json` 的一键培育默认仍以 `初` `PRO` 为主；新增默认项前先确认不会增加普通用户误触或长流程失败风险。

## 数据与资源规则

- `assets/data/idols_cards.json` 包含 SSR/SR/R 卡片数据和保存时间。更新时保持字段名称一致，包括 `卡片名称`、`偶像名称`、`歌曲名称`、`偶像中文`、`歌曲中文`、`推荐效果`、`体力`、`Vo`、`Da`、`Vi`、`奖励加成`、`登场日期`。
- 卡片或素材更新优先使用 `tools/` 下已有脚本，不要手工批量改写大数据文件，除非用户明确要求。
- YOLOv11 数据集当前基于 README 与开发文档记录：
  - `cards` 集用于出牌识别，样本约 902 份。
  - 早期用于上课和冲刺选项识别的 `button` 集已废弃，相关按钮识别已改为普通模板匹配。
- OCR 模型已换 PP-OCRv6 small（`assets/resource/model/ocr/`，tiny 档无日文故不用 small 以下）；旧 v3 备份在 `assets/resource/model/ocr_v3_bak/`，发布打包时注意不要把备份目录带上。
- 新增图像素材时应说明来源、截图环境和分辨率。不要提交游戏资源本体之外的非必要大文件。

## 测试与验证

改动完成后，根据影响范围选择验证：

- Python 自定义逻辑：至少运行 `python -m py_compile agent`，有测试时运行 `python -m pytest`。
- HIF 决策/模拟器：运行 `python -m pytest tests/test_hif_decision.py tests/test_play_decision.py tests/test_exam_reader.py tests/test_scoring_model.py`，四个文件覆盖 `agent/hif/` 的决策全链、出牌策略、ExamState 适配层和评分模型 v2，合计约 128 个用例。
- 流水线或资源：运行 `npx maa-tools check`，并在可能时进行实际 MaaFramework 调试。
- JSON/YAML：运行 Prettier 检查或格式化。
- 自动培育：需要真实设备或模拟器长流程验证；如果无法运行，必须在交付说明中明确未做实机验证。

调试时优先查看 `debug/maa.log`。自动培育一次通常约 30 分钟，会产生大量日志；不要提交日志文件。

## 协作注意事项

- 不要回退用户已有修改。当前工作区若有不相关改动，保持原样。
- 不要在未确认的情况下调整发布、安装、依赖打包或 Mirror 酱相关配置。
- 不要把 README 中标注为测试阶段的自动培育描述成稳定功能。
- README、功能说明与 Changelog 若存在冲突，先检查最近提交和 `assets/tasks/produce.json`；当前 NIA 状态应以 v1.4.2 Changelog 和任务配置为准。
- 不要改变项目许可证、免责声明或商业用途限制。
- 需要联网查询 MaaFramework、MFAAvalonia、Mirror 酱或 OpenAI 等外部信息时，优先使用官方文档，并在回复中说明来源。
- 对用户报告的运行问题，优先索要或检查 `debug/maa.log`、模拟器类型、分辨率、系统平台、游戏版本、是否 DMM/插件版汉化。
