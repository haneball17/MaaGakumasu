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
- 评分模型离线链 A/B 已完成（数据 join、双评分回放、Spearman 校准框架，当前 rho≈0.458），C2 人工调参待做。
- 机制知识库 `docs/hif/mechanics.md`（M1 起逐条带 A-D 置信度与実機验证状态）是机制语义的首要依据；数据链同步 gakumasu-diff 主干（`tools/sync_hif_master.py`、`sync_hif_effects.py`、`scrape_hif_tiers.py`）。
- 尚未实现：Round1 出牌执行、Round2、Interval、结算、メモリー（回忆卡）评分、整局自动培育；这些页面仍由 `ProduceHIFUnknownStop` 兜底停止。
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
- HIF：Round1 出牌接线（`GarakutaRinamiStrategy` → 实机）、评分模型 C2 人工调参、快慢路径路由实施、Round2/Interval/结算/メモリー、模拟器立项（输入需含偶像卡）。
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
- `docs/hif/`：HIF 文档集。首要依据：`mechanics.md`（机制知识库）、`scenes.md`（场景卡设计真源）、`finals-daily-log.md`（実機证据日志）、`scoring-model-design.md` 与 `scoring-model-implementation-plan.md`（评分模型）、`decision-override.md`（参数覆盖链）、`round1-blockers.md`（已完结）。
- `tools/`：维护脚本。HIF 相关：`simulate_hif.py`（模拟器 CLI）、`hif_decision_viewer.py`（决策日志查看器）、`hif_replay_report.py`（复盘总表）、`replay_scoring.py`（双评分回放）、`calibrate_scoring.py`（tier 榜校准）、`scrape_hif_tiers.py`、`sync_hif_master.py`、`sync_hif_effects.py`、`hif_mine_ocr_variants.py`（OCR 变体挖掘）。
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

## 代码与格式约定

- Python 代码遵循 `pyproject.toml` 中 Ruff 配置：目标版本 `py312`，行宽 `144`，仅启用 `I`（isort）规则且开启 `length-sort`/`length-sort-straight`（按 import 长度排序）。改 import 时注意这一点。
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
