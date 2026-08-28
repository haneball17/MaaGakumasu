# AGENTS.md

本文件为在本仓库中工作的 AI/自动化代理提供项目上下文与协作规则。修改前请先阅读 `README.md`、`docs/zh_cn/功能说明.md`、`docs/zh_cn/开发相关.md` 以及本文件。

## 项目概览

MaaGakumasu 是基于 MaaFramework 的《学園アイドルマスター》自动化助手，采用 `JSON + 自定义逻辑扩展` 的开发模式。项目主要通过图像识别、OCR、YOLOv11 深度学习模型和模拟控制完成游戏日常、商店、社团、工作、竞赛与自动培育等任务。

目标运行环境以 Windows 为主，推荐 MuMu 模拟器 12，分辨率基准为 `1280x720 (240DPI)`。DMM 版和插件版汉化已适配，但部分组合仍未完全测试。

## 当前状态

主线功能（初/NIA 自动培育、竞赛、社团、工作、商店、更新检查）已上线；用户可见公告以 `assets/resource/Changelog.md` 为准（当前 v1.4.2，HIF 新选项尚未写入公告），`README.md` 的进度描述可能滞后。

HIF（学祭，即学園祭本战）培育为当前活跃开发方向（分支 `feat/hif`）。截至 2026-08-24：

- 実機全链闭环：培育→Round 対局→Interval→Round2→敗退/结算→メモリー→報酬→主页面 五轮実機走通（四轮主线零介入）；缺陷修复批次（GitHub Issues #1-#10）落地并通过総合验收轮。
- 已就绪：三选一双评分（模型 v2 + 关键词兜底）、决策参数覆盖链、全决策点落盘 `debug/decisions/`、Round 模拟器七里程碑（`agent/hif/roundsim/`，速览 `docs/hif/roundsim-implementation-plan.md`）。
- 未完成：完整出牌策略 `GarakutaRinamiStrategy`（`agent/hif/decisions/play.py`）已实现、未接线実機；探索分支与未取证页面由 `ProduceHIFUnknownStop` 兜底。
- 遗留与待实现全部建 GitHub Issues（含总纲 #27 验证债归还+Interval 自动购买）；特別指導接入点已勘察暂缓（`docs/hif/customize-integration-notes.md`）。

真源（HIF 工作前先读）：

- 轮次/验收/bug 全录：`docs/hif/five-round-validation-2026-08-21.md`；取证/验收报告：`debug/autodev/forensic-*.md`、`acceptance-report-*.md`（不入库）。
- 机制语义首要依据：`docs/hif/mechanics.md`；场景卡真源：`docs/hif/scenes.md`。
- 架构决策：`docs/adr/`；首版边界：`docs/superpowers/specs/2026-07-10-hif-basic-pipeline-design.md`；快慢路径设计（待实施）：`docs/superpowers/specs/2026-08-14-hif-fastpath-routing-design.md`。
- 流程依据：`docs/hif/finals-daily-log.md`（止于 2026-08-21，此后実機证据落 five-round-validation 与 debug/autodev/ 报告）。

## 目录职责

- `agent/`：Python 自定义逻辑扩展（MaaFramework Custom recognition/action）。培育通用逻辑在 `agent/custom/action/produce.py`；HIF 在 `produce_hif.py`（读预设经覆盖链解析、内联识别与双评分决策、决策落盘，未覆盖页面调 `ProduceHIFUnknownStop` 停止）；`agent/hif/` 分 `decisions/`（実機决策核心：评分/出牌/日程/日志查看）、`algorithms/`（离线模拟器，与実機管线解耦，入口 `orchestrator.py`）、`adapters/`（YOLO+词典 OCR 适配层）及顶层 `presets.py`（预设与覆盖链）。
- `assets/resource/base/pipeline/`：流水线。培育通用 `Produce.json`、NIA `ProduceNIA.json`、HIF `ProduceHIF.json`、共用 `ProduceUtils.json`；`assets/resource/base/image/` 为模板素材。
- `assets/data/hif/`：HIF 结构化数据（121 卡全表/效果池/饮料/关键词表等），由 `tools/sync_hif_master.py`、`sync_hif_effects.py` 从 gakumasu-diff 同步生成，**不要手改**；决策参数覆盖文件实际在 `assets/data/hif/decision_override.json`（`agent/hif/presets.py` 读取）。
- `assets/resource/model/`：YOLO 检测与 PP-OCRv6 OCR 模型，旧版备份 `ocr_v3_bak/` **发布打包时不要带上**。
- `assets/tasks/`：任务入口与选项定义（培育任务在 `produce.json` / `produce_cn.json`）；`assets/lang/` 翻译（新增选项同步 `zh-CN`、`zh-Hant` 等已有语言）。
- `assets/resource/Changelog.md`：发布给用户看的资源更新公告。
- `docs/hif/`：HIF 文档集，首要依据 `mechanics.md`（机制知识库）与 `scenes.md`（场景卡设计真源）；命名惯例：事件/报告类带日期后缀（`five-round-validation-2026-08-21.md`）、常青参考类无后缀。`docs/zh_cn/` 为用户与开发文档。
- `tools/`：维护脚本（HIF 决策/模拟器/回放/校验/数据同步等，文件名自解释；无人化管线开发工具 `maa_dev.py` 子命令见 `docs/hif/autodev-workflow.md`）。
- `debug/`：运行日志与调试输出（含 `debug/decisions/` HIF 决策日志），**不入库**。

## 开发环境

- Python `>=3.12`；依赖 `maafw`、`loguru`、`Pillow`；可选开发依赖 `pytest>=7.0`、`ruff>=0.1.0`。包版本信息在 `pyproject.toml`（当前 `1.3.8`）。
- Node 侧仅用于工具链，当前 `package.json` 包含 `prettier-plugin-multiline-arrays`。

常用检查命令：

```powershell
python -m py_compile agent
python -m pytest
python -m ruff check .
npx prettier --check "**/*.{json,yml,yaml}"
npx maa-tools check
```

如果本地缺少测试目录或依赖，说明无法完整执行对应检查即可，不要为了通过检查凭空创建无关测试。改动存量管线节点后必须跑回放基准集：`python tools/maa_dev.py replay --suite tests/replay_suite`。

実機开发调试细节由四个 skill 承载（触发加载，见各自 SKILL.md）：

- **pipeline-autodev**（无人化管线开发）：五角色循环、危险操作护栏、坐标裁决铁律（视觉模型只从 SoM 编号叠加图选编号，精确坐标一律取 OCR/模板/YOLO 检测框中心）、分段接力与死循环排障、验收清单。
- **maa-customaction-ipc-test**（Custom action 実機单点连测）：`tools/hif_ipc_runner.py` 直连协议、MaaMCP `run_pipeline` 竞态禁用与 JSONC 绕过、識別新件 probe ≥3 轮纪律、UI 约束清单前置、対局页动态锚定规则。
- **pipeline-testing / hif-manual-test**（手动单步验证与取证）：语义裁决铁律（UI 语义结论必须经用户指认或実機文本佐证，vision 形状描述只作辅助）、実機点击 `posted:true` ≠ 生效需 OCR 锚复核。

MuMu 的 adb 端口跨会话会漂移，実機操作前先 `adb devices` 查实际端口并经 `MAA_DEV_ADDR` 注入，不要假设默认端口。工作流详情见 `docs/hif/autodev-workflow.md` 与调研存档 `docs/hif/autodev-research.md`。

## 代码与格式约定

- Python 代码遵循 `pyproject.toml` 中 Ruff 配置：目标版本 `py312`，行宽 `144`，仅启用 `I`（isort）规则且开启 `length-sort`/`length-sort-straight`（按 import 长度排序）。改 import 时注意这一点。
- 大段重写类或函数后，必须 grep 旧标识符（旧常量名/方法名）确认已删除——Python 类体中后定义的方法会静默覆盖前者，旧 `run()` 残留会让新版从未执行且编译/单测全绿掩盖（2026-08-21 変卡重写実機教训，db1c772）。入口方法替换用 `inspect.getsource` 断言新逻辑确实在目标方法内。
- JSON/YAML 使用 Prettier 配置：默认缩进 4 空格，YAML 缩进 2 空格，JSON 覆盖配置使用 tab。
- Markdown 文档保持各文档现有风格；根目录 `AGENTS.md` 主要服务代理协作，优先清晰准确。
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
- agent 侧 OCR expected **禁止携带任何非 ASCII 字符**（2026-08-23 #65 実証：日文 expected 经 AgentClient IPC 偶发 GBK 乱码且进程级，不可编码字符概率最高）。统一模式：expected `[".*"]` 全量 OCR + Python 侧遍历 `all_results` 子串/正则匹配（`_find_in_all`/`_find_text_option` 既有范本，兼省 N-1 次 OCR）；纯 ASCII 的 `re.escape()` 元字符防护仍适用。跨 Custom 大包共享的状态放**全局 session 层**（`_write_session_state`）——round1 子树标记会被下一大包的 `_reset_round1_state` 清掉；Custom action 内发现上下文错配（如 round 参数错）**就地改参重入**，return False 交回路由会被同一 Flag 再接管回环。
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
- Flag 锚在多个页面共有时，页面专属锚必须排在通用锚前面（如 `ProduceHIFStartConfirmFlag` 先于 `ProduceHIFIdolSelectFlag`——步骤条「アイドル選択」文字在步骤 1/2 两页共有）；Custom action 的重试循环内先自检本页锚，锚失活即放行 `return True` 交回路由——转场/LOADING 窗口内 JumpBack 回环会重复路由命中同一 Flag，在未渲染页面上 miss 即 stop 是系统性失败模式（実機 2026-08-21 三处中招）。
- 无固定文案的封闭池页面（如 P 饮料弹窗，饮料名/效果随种类变）用数据源名称池做 OCR expected 锚（`drinks.json` 29 名称，静态 JSON 定义无 IPC 乱码风险），ROI 收窄到名称一行；不要用框架装饰模板（sparkle/横条在背景页无区分度，実機 2026-08-21）。
- 泛词锚与空白点击的死循环铁律（実機 2026-08-22 轮 1/2 三例）：`[JumpBack]` 回环命中即重置轮询，**永远走不到 timeout**——误命中的裸点击=无限空转且无任何报错。规则：①泛词锚（页面残留标题词：獲得/差し入れ/再開类）必须挂 ScheduleRoot 尾部兜底位或换专有词锚，禁止挂前部抢路由；②空白/中央点击类推进节点必须用 `ProduceHIFGuardedTapAuto`（Custom：锚验证→指纹对比→点击→验证推进，连续 3 次无变化 return False 段退），禁用裸 Click action；③新挂载节点先问「这个词在哪些**其他**页面也出现」再定位次；④**跨页共显锚**（HUD 标签同位同文，收窄无解，実機 2026-08-22 轮 7 #48：変卡页与授業页共享左上「授業」）：action 侧读空 stop 前先自检他页专有锚（如変卡弹窗「チェンジ」），命中即 return True 放行回路由让正主 Flag 接管；放行必带连续 N 次上限（回环重置轮询，无限放行=无限空转）。段边界演出窗口读空同理：画面指纹在变=动画中，等静止重读（`_wait_turn_reframe` 模式）而非立即 stop。
- agent 侧操作日志链（2026-08-22 轮 2 grill 裁决）：全部点击/滑动/按键必须走 `_tap/_swipe/_key` 守卫包装（`_ProduceHIFActionBase`）——记录坐标+操作后截图 `debug/decisions/ops/` + ops JSONL（含前后 64x64 指纹对比 scene_changed）；禁止直调 `controller.post_click/post_swipe`（IPC 点击丢失类 bug 复盘全靠此链）。管线侧 Click 节点的坐标在 `debug/maafw.log` 有事件记录可交叉查。
- 滚动枚举类读取（牌库网格/详情面板）判底必须「**整屏确认**」：滚动后读完整屏，全部条目 ∈ 已见才判到底；禁止用「滚动后首行/单点探针」预判——滚动重叠行必然全命中已见集合，会跳过真正的新内容（実機 2026-08-22 変卡牌库只读一排即断底教训）。
- 遮挡全画面的浮层（毛玻璃类：卡详情/メモリーアビリティ/buff効果一覧等）挡掉**全部锚**致路由根全 miss→段循环空退（実機 2026-08-22 四例 #34/#38/#41/#25）：此类浮层必须在 ScheduleRoot **前部有管线层关闭节点**（现 pos0-2 关闭组 StatePanel/MemAbility/CardDetail，锚用面板专有词如「(再演)括号格式」防背景状态带误命中）。Custom action 内的 dissolve 自愈只在其宿主节点可达时有效——「Custom 够不着」是浮层处理的边界，新浮层类型先加管线层节点再考虑 Custom 内兜底。
- 视觉按钮（pill 胶囊形）点击一律用**按钮几何中心**，OCR/小模板文字 box 中心系统性偏上 ~21px 且 hitbox 内缩（実機 2026-08-22 三例）；文字 box 只做存在判定。Custom action 首次点击前加入场稳定等待 SETTLE≥2s（入场动画窗口 agent 点击静默丢失，手动同坐标即中）。收紧路由根 next timeout 前必须先量「轮询一圈实际耗时」（节点数×单点识别耗时；模板 ~0.3s vs OCR ~2s），timeout ≥ 一圈+15s——40s 曾饿死第 11 位之后的全部锚。
- vision 语义结论三条边界（2026-08-24 批次沉淀）：①**假名形/平形（ヘ/へ）视觉不可区分**——锚词含同形对时用字符类 `[へヘ]` 或换更稳锚；②対局页立绘**持续动画**（待机呼吸/特效），像素 diff 判弹出面板恒误报——対局页面板判定用 OCR 专有词锚或面板边框模板，像素 diff 只用于静态页；③决策 session JSONL 按日期命名（`session-YYYYMMDD.jsonl`）**跨 0:00 切文件**——长局回放按日期目录收集全部 session 文件，禁止假设单文件含整局。

## 任务配置规则

- 培育任务定义在 `assets/tasks/produce.json`，中文版本在 `assets/tasks/produce_cn.json`；新增或重命名选项时两边都要同步。
- 选项清单以 `assets/tasks/produce.json` 为准（含 HIF 专属的 `HIF预设`、`培育倾向`、`HIF 决策微调` 等）；HIF 选项经 `pipeline_override` 注入 Flag 节点的 `custom_action_param`。
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

## 文档维护约定

- 新教训的**规则句**进 `MaaFramework 流水线规则` 等对应节（单条单源）；**案例叙事**（轮次经过/坐标/证据数字）落真源文档（`docs/hif/` 日期后缀报告、`debug/autodev/` 取证报告），规则内只留短日期标签。
- 「当前状态」节只更新状态快照（阶段/边界/待办指针），不追加轮次编年史；新缺陷建 GitHub issue，不在本文件堆积。
- 新增面向代理的常青参考优先放 `docs/`（事件报告带日期后缀、常青参考无后缀），本文件只留指针。

## Agent skills

### Issue tracker

Issues 存放在 GitHub Issues（origin fork `haneball17/MaaGakumasu`），操作用 `gh` CLI。见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认五标签词汇：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文布局：根 `CONTEXT.md`（中文术语表）+ `docs/adr/`。见 `docs/agents/domain.md`。
