# upstream v1.5.2 同步合并记录（2026-10-15）

事件类文档：记录 fork main 快进同步与 dev 分支整合的全过程裁决。规则句已按文档维护约定进 AGENTS.md 对应节，本文只留叙事与证据。

## 背景与基线

- fork `origin/main`（v1.4.5, d9afb82）落后 upstream（SuperWaterGod/MaaGakumasu）89 提交、领先 0；upstream 已发 v1.5.0 → v1.5.1 → v1.5.2（7bb97ba）。
- 开发分支 `feat/pipeline-autodev`（ca0611d）相对旧 main 领先 167、落后 51。
- 经两轮 grill 敲定：两阶段执行（先 FF main 后整合 dev）、merge 而非 rebase（分支已推送）、冲突裁决 = 上游优先 + fork 白名单、验证 = 阶段1 轻量 + 阶段2 全套、分支终局 = dev 定期合回 main。

## 阶段1：工作区落位 + main 快进（低风险，~30 分钟）

1. 工作区 38 个脏条目清零：3 个修改文件（两个 SKILL.md + CONTEXT.md）、autodev 素材 21 件、docs/showcase 调研报告分别 commit；`.gitignore` 增补本地环境产物与不加载素材目录；`nul`（MCP 日志重定向事故产物）删除。
2. `git merge upstream/main --ff-only`：main 从 ad26b59 快进到 7bb97ba（v1.5.2），push origin。
3. 轻验证：compileall agent/tools 通过；prettier 检查跳过（upstream v1.5.2 删除了 `.prettierrc`，格式约束已移除）。

## 阶段2：merge main 进 dev（15 文件冲突，29 个冲突块）

预估 35 个双改文件，实际 15 个进入手工冲突（其余 20 个 git 自动合并成功）。

### 逐文件裁决表

| 文件 | 冲突块 | 裁决 | 说明 |
| --- | --- | --- | --- |
| `.github/workflows/check.yml`、`install.yml`、`.vscode/settings.json` | 1-2 | theirs | fork 零语义改动 |
| `assets/interface.json`、`assets/tasks/preset.json`、`shopping.json` | 1 | theirs | `git diff -w` 证实 fork 侧纯缩进重排 |
| `assets/lang/zh-CN.json`、`zh-Hant.json` | 1 | 键级合并 | upstream 新键全收 + fork 51 个 HIF 文案键回插 |
| `assets/tasks/produce.json`、`produce_cn.json` | 1 | 结构合并 | upstream v1.5.2 任务树为底 + fork 10 个 HIF 选项与 `培育难度` 的 HIF case 回插；task option 数 23 |
| `agent/main.py` | 1 | theirs+保留 | upstream 新增函数内 import；fork 的 parent_dir sys.path 注入与异常消息经自动合并保留 |
| `agent/custom/action/produce.py` | 1 | theirs+补丁 | upstream 893 行重构为底；回插 `_get_suggestion` 的 IPC 乱码防御（`expected: [".*"]` + `all_results` Python 侧匹配，适配新返回结构） |
| `tools/update_cards.py` | 3 | ours | fork 已重写为 `data_pipeline` 薄壳（HIF 数据链）；upstream 对旧单体逻辑的修复列入回移植审查 |
| `README.md` | 4 | 手工融合 | 功能表上游优先+保留 HIF 行；HIF 节修正过时数字（37→73 节点、出牌已可选）；TODO 两边并 |
| `AGENTS.md` | 9 | 手工融合 | HIF 主干保留；upstream 编年史按文档维护约定不入库；`tests/` 定位改写（见下） |

### 结构性风险与处置

1. **upstream `.gitignore` 新增 `/tests/`**（把 tests 当临时目录）：与本 fork 的正式测试套件（323 用例 + replay 基准集）直接冲突。处置：删除该 ignore 行，AGENTS.md 明确本 fork `tests/` 为正式套件、临时测试放 `.scratch/`。
2. **upstream OCR 模型升级**（det 4.7M→9.9M、rec 16.5M→21M，即本地曾试验的 v6 同款正式入库）：replay 发现 `ProduceHIFMemoryConvertPageFlag` miss——新模型把「メモリー」识为「メモリ-」（长音符→短横）。处置：两处锚正则放宽为 `.*メモリ.*変換.*`（32388aa），replay 恢复 14/14。**同类风险**：v6 模型对其他小字/长音符文本的识别行为可能与 v5 不同，実機验证轮需关注 OCR 锚的命中率。
3. **版本口径**：`pyproject.toml` 1.3.8（upstream 未改，无冲突，保留）；资源版本 v1.5.2；AGENTS.md 已注明两个口径的语义。
4. **maafw 锁定**：`>=5.11.1,<5.12` 保留（5.13–5.14.3 release notes 逐版核对无 IPC 乱码修复）。5.14.3 的 Agent 请求/响应按 ID 匹配、5.14.0 DirectHit 跳截图、5.13.1 并发竞态修复为将来升级的验证点。

### 验证结果

- `compileall agent tools`：通过。
- `tools/ci/check_resource.py ./assets/resource/base/`：通过（MaaFW Resource 成功加载合并后管线）。
- `pytest tests/`：**323 passed**（39s）。
- `maa_dev.py replay --suite tests/replay_suite`：锚修复后 **14/14 pass**。
- HIF 任务 override 目标节点存在性：全部命中（378 个管线节点中无缺失）。
- 実機验证：本轮未做（无设备会话）；按计划由 #27 批次的実機轮覆盖整合回归。

### 遗留：上游修复回移植审查清单

- `9499323`（偶像卡识别特殊符号 NFKC 归一化）：改在 `agent/custom/reco/produce.py`（自动合并，已在）；`tools/update_cards.py` 侧的对应修复因 fork 重写为 data_pipeline 薄壳未带入——下次跑数据同步时确认 `data_pipeline.py` 是否需要等价归一化。
- upstream `produce.py` 的 15 秒出牌兜底/手牌区域过滤与 HIF Round 出牌 Custom action 的交互：未实测，#27 実機轮观察。

## 后续路线

1. #27（验证债归还 + Interval 自动购买）在合并后基线上开工，実機轮顺带覆盖整合回归。
2. dev 验证通过后合回 main 打 tag（fork 发布线 = upstream + HIF）。
3. 下轮 upstream 同步：冲突面应显著缩小（35→预计<10 文件）。
