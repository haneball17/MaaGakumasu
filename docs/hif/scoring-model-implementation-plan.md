# HIF 评分模型实施计划（离线链 A→B→C）

**日期：** 2026-08-16
**状态：** A/B 阶段完成（2026-08-16 实施会话），C 阶段框架就绪待人工调参
**依据：** [`scoring-model-design.md`](scoring-model-design.md)（两轮 grill 定案）
**范围：** 评分模型离线链（数据链路 → 评分实现 → 校准）串行主推；D 线（Round1 出牌闭环、synergy 激活）本阶段不做。

## 实施结果速览（2026-08-16）

| 任务 | 状态 | 关键产出/结论 |
| --- | --- | --- |
| A1 join 脚本 | ✅ | `tools/sync_hif_effects.py` → `skill_card_effects.json`（170 卡/653 档）+ `drink_effects.json`（29 饮料/17 in_pool）；unmapped 0；M1 对账全过（121 卡命中/88 实证/軽い足取り数值/plan 100% 一致） |
| A2 流派池词典 | ✅ | `card_dict.py` 词典 467 条（122 卡×档位变体）；NFKC 统一命名空间（全角＆差异消除）；32 张 Plan2/3 死代码剔除 |
| A3 tier 榜 | ⚠️ | `tools/scrape_hif_tiers.py`：Game8 176 卡成功；seesaawiki 整站 403（IP 封锁），解析器已备好，换网络重跑 `--source seesaawiki` 可补齐 |
| B1 scoring.py | ✅ | 五族曲线 + 修饰层 + C 层（stamina 比率折罚 + 集中/好調系 cost_type 折罚）+ synergy 占位；17 单测全过 |
| B2+B3 接线 | ✅ | `_choose_keyword_reward`：HUD 体力 + session 日数 → `DecisionContext`；命中效果池走模型分、miss 退关键词（断崖为零）；123 存量+新测试全过 |
| B4 GUI 扩框 | ✅ | 「HIF 决策微调」19 框（+缩放系数/终盘权重），9 节点接线，zh-Hant 同步 |
| B5 离线回放 | ✅ | `tools/replay_scoring.py`：0815 基线 28 记录/84 候选；卡侧模型命中 9/12（drink 候选実機卡名全空→兜底，符合预期）；翻转 1 例=数值盲修正（パラメータ+40 旧表仅 2 分）；viewer 加模型/关键词双分列 |
| C1 校准框架 | ✅ | `tools/calibrate_scoring.py`：Spearman 相关 + 四分位分歧清单 + 参数网格；**默认 rho=0.066，网格最优 0.217（k_buff=5/w_cycle=12/w_parameter=0.5/cond_factor=1.0）** |
| C2 人工复核 | ⬜ | 材料在 `.scrape/calibration-report.json`；已知系统性缺口：①enchant 容器内行动经济效果未计分（SS 循环卡「アイドル魂」仅元気 3 分）②纯参数直加大数字卡（スタートダッシュ+30）社区榜圏外但模型高估 → w_parameter 调低方向 |

环境备注（2026-08-16 实施时）：主会话 python/git/Node 因环境故障丢失；python 经 `~/.local/bin/python.exe` + 项目 `.venv`（清华镜像装依赖）恢复；node/npx 缺失，prettier 与 `maa-tools check` 未跑，JSON 以语法校验 + diff 最小化代替；実機验证未做（离线链交付）。

## 0. 前置：环境恢复确认

2026-08-16 会话实测环境故障快照（实施前须逐项确认恢复）：

| 项 | 故障现象 | 恢复判据 |
| --- | --- | --- |
| 子代理沙箱 | F: 盘全盘不可达（Read 报 not exist、Bash 报 `cmd.exe ENOENT`） | Explore 子代理可读 `F:\code\MaaGakumasu` |
| 主会话 shell | Git Bash 丢失，降级 cmd.exe；`python`/`git` 不在 PATH，注册表无安装记录 | `python --version` 与 `git log --oneline -1` 可执行 |
| Read/Write 工具 | 已恢复（F: 盘可读写） | — |

环境未恢复时停止实施，不降级手工改数据文件。

## 1. 阶段 A：数据链路

### A1. join 脚本（核心，估 1-2 会话）⬜

1. 首日自查两项：
   - 读 `tools/sync_hif_master.py` 现状（已确认存在，8118 字节，2026-08-15），定挂载方式：扩子命令 vs 新建 `tools/sync_hif_effects.py`（按仓库薄封装先例，倾向新建——`data_pipeline.py` 定位是 seesaawiki/翻译库 → `assets/data/` 根 master，与 diff 关联表 join 属不同上游）。
   - 抽 `.scrape/gakumasu-diff/` 的 `playEffects` / `produceCardStatusEffectId` / `produceDrinkEffect` 表各 3 条记录摸字段结构。
2. 实现：join 出流派过滤池（`planType ∈ {Plan1, Common}`）全量结构化效果数值；输出落 `assets/data/hif/`，schema 对齐 `drinks.json` 的 `{tag,op,value,unit,scope}` 风格 + `plan` 字段。
3. 顺带关闭设计文档待定 #6/#7：产物带固有卡标记（`originSupportCardId` / id 模式识别非莉波固有）与实证层标记（master 88 卡命中 → 高置信）。
4. CI：扩 `tools/data_pipeline.py` 的 `validate_all` 覆盖新文件主键唯一性（现状 `assets/data/hif/` 不在校验范围，但新产物进 `assets/**` 必触发 workflow）。
5. **风险预案**：若关联表碎片化超预期（设计文档 5.2 警告过），降级为 master 121 卡 `effect_raw` 正则抽取作 P1 过渡，join 继续排期——不阻塞 B 阶段。

### A2. 流派池词典 ⬜（估 0.5 会话）

`agent/hif/adapters/card_dict.py` 词典源从 121 卡扩到流派过滤池（剔除非莉波固有卡与 32 张 Plan2/Plan3 死代码）；词典文件由 A1 产物派生，运行时加载。

### A3. tier 榜抓取 ⬜（估 0.5 会话）

Game8 + seesaawiki 編成表抓取脚本 → `.scrape/`（校准输入；与 B 阶段无强依赖，可与 B 并行）。

### M1 验证（阶段 A 完成门槛）

- join 产物过 CI（`python ./tools/data_pipeline.py validate`）。
- 121 卡数值与 `effect_raw` 抽查对账（例：軽い足取り = パラメータ+6 好調2ターン）。
- 里程碑 commit：数据与词典。

## 2. 阶段 B：评分实现

- **B1. 新模块 `agent/hif/decisions/scoring.py` ⬜（估 1 会话）**：V 层五族曲线（log 饱和 / 线性 / 乘子 / 上下文敏感，见设计文档 3.1 定案表）+ 修饰系数层 + C 层成本折算；synergy 恒 1.0 占位；分值量级经全局缩放对齐现有 ≈8 分档（设计文档 3.5）。
- **B2. 局面信号接线 ⬜（估 0.5 会话）**：剩余日数 HUD 读取（`_get_health` 已有体力侧，日数侧接线待做）→ 终盘衰减系数（设计文档 3.4 修正版）。
- **B3. 接入决策链 ⬜（估 0.5 会话）**：`rewards.py` 命中新词典走新评分、miss 退关键词兜底；决策链与重抽逻辑不变（设计文档 1.1/第 6 节）。
- **B4. GUI 扩框 ⬜（估 0.5 会话）**：17 框体系扩「缩放系数 / 终盘权重」两参数（`assets/tasks/produce_cn.json`「HIF 决策微调」组）。
- **B5. 离线回放 ⬜（估 0.5-1 会话）**：`debug/decisions/session-20260815.jsonl` 63 条新旧双评分差异表，接决策日志 viewer 展示（评分明细 / 截图 / JSONL 三件套）；人工审排名翻转是否都发生在四盲区案例（数值/成本/上下文/手牌）上，而非噪声翻转。

### M2 验证（阶段 B 完成门槛）

- `scoring.py` 单测全过（五族各曲线 + 兜底链 + 量级对齐）；`python -m pytest` 存量测试不破。
- 回放差异表人工审通过。
- 里程碑 commit：评分与回放。

## 3. 阶段 C：校准（估 1-2 会话，含人工）

- **C1. ⬜** 88 实证卡 + tier 榜分级喂入调参（曲线参数 + 缩放系数），最大化模型输出排序与社区共识排序的相关性（设计文档第 4 节）。
- **C2. ⬜** 分歧样本（模型与榜差 ≥2 档）人工复核，输出曲线修正清单。

### M3 验证（阶段 C 完成门槛）

- 相关性达标；分歧复核归档。
- 里程碑 commit：校准参数。

## 4. 本阶段不做

D 线 Round1 出牌闭环、synergy 层激活（设计文档待定 #5）、MFA 界面端到端实测（B4 后用户配合跑一次）。

## 5. 进度跟踪

| 任务 | 状态 | 产出 |
| --- | --- | --- |
| 环境恢复确认 | ✅ | python(.venv)/git 恢复;node 仍缺 |
| A1 join 脚本 | ✅ | `skill_card_effects.json` + `drink_effects.json` + CI 校验扩展 |
| A2 流派池词典 | ✅ | `card_dict.py` 词典源切换(467 条) |
| A3 tier 榜抓取 | ⚠️ | Game8 成功;seesaawiki 403 待换网重跑 |
| B1-B5 评分实现 | ✅ | `scoring.py`(17 单测)+ 接线 + GUI + 回放 + viewer |
| C1-C2 校准 | 🔶 | C1 框架+基线报告就绪;C2 人工复核待做(材料 `.scrape/calibration-report.json`) |

已确认事实（2026-08-16 自查，供 A1 直接消费）：

- `tools/sync_hif_master.py` 头部 docstring 自述「深度数值解析待关联表 join，另立项」——本计划 A1 即该立项；可复用 `_load_yaml` / `TIER_KEYS` / `_effect_text` / `_diff_commit`。
- 卡表现状以 121 卡 name 白名单过滤合并 tiers；A1 输出以 `diff_ids` 直连（master↔diff planType 已验证 100% 一致），不依赖 name join。
