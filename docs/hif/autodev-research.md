# pipeline-autodev 调研纪要（2026-08-20）

为"无人工介入的 MaaFW 管线开发调试工作流"做的 5 路调研结论与来源存档。
决策记录（10 项）见仓库 skill 与工作流文档。

## 1. MaaFramework 生态：哪些现成、哪些空白

**现成**：

- [MaaMCP](https://github.com/MAA-AI/MaaMCP)（v1.2.3，AGPL-3.0，MistEO）：MCP server +
  Python 库双形态；screencap/ocr/click/swipe/run_pipeline/load/save_pipeline；
  README 的"Pipeline 智能生成"（操作→JSON→验证迭代修复）即本工作流雏形。
- 官方工具链：[MaaDebugger](https://github.com/MaaXYZ/MaaDebugger)（节点执行链+识别详情，
  无单步/断点）、[MaaLogAnalyzer](https://github.com/MaaXYZ/MaaLogAnalyzer)（日志回放/节点统计）、
  [MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)（运行配置，非开发）。
- 协议级调试原语：`on_error`/`timeout`/`focus` 回调/`pipeline_override`/`attach` +
  AgentServer/AgentClient 事件 sink（[Pipeline 协议](https://maafw.com/docs/3.1-PipelineProtocol/)、
  [集成接口](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.2-集成接口一览.md)）。
- 周边：[MaaMCP_CC](https://github.com/Arcelibs/MaaMCP_CC)（grid 截图/crop_template/test_recognition）、
  [maafw-cli](https://github.com/otowa-kotori/maafw-cli)（daemon+reco+element 引用）、
  [Everything-Maa](https://github.com/KhazixW2/Everything-Maa)（12 skills 全流程编排，预发布）、
  [MaaPracticeBoilerplate](https://github.com/MaaXYZ/MaaPracticeBoilerplate)、
  [MaaHub](https://github.com/MaaXYZ/MaaHub)。

**空白（需自建）**：单步/断点调试器（生态明确没有；"单节点任务+override+前后截图"即最佳实践）、
节点级离线 mock、MaaMCP 缺独立模板匹配工具（自建 `maa_dev.py reco` 补位）、
"pipeline 变更自动回归"（自建 `replay`）。官方框架层 AI 集成仅
[issue #896](https://github.com/MaaXYZ/MaaFramework/issues/896) 构想，无 PR。

## 2. 视觉模型坐标定位（grounding）与补偿

- 裸坐标不可信是共识：GPT-4o ScreenSpot-Pro 裸测 0.8 分，配 OmniParser 后 39.6
  （[微软 OmniParser V2](https://www.microsoft.com/en-us/research/articles/omniparser-v2-turning-any-llm-into-a-computer-use-agent/)）；
  SeeClick 论文测 GPT-4V 仅 16.2%（[arXiv:2401.10935](https://arxiv.org/abs/2401.10935)）。
- Qwen 系坐标系三代变更（0-1000 归一化 ↔ 绝对像素 ↔ 0-1000）是系统性偏移主因
  （[Qwen3-VL cookbook](https://github.com/QwenLM/Qwen3-VL/blob/main/cookbooks/2d_grounding.ipynb)、
  [issue #1485](https://github.com/QwenLM/Qwen3-VL/issues/1485)、
  [Qwen2.5-VL smart_resize 逆映射](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct/discussions/13)）。
- **成熟补偿范式（Mobile-Agent 全系）**：OCR/检测器出框 + VLM 只选编号（SoM）+ bbox 中心点击
  + 点击后截图反思（[arXiv:2401.16158](https://arxiv.org/html/2401.16158v2)）；
  SoM 使 grounding 从回归变选择题（[arXiv:2310.11441](https://arxiv.org/abs/2310.11441)）。
- 本机校准（M3，19 要素）：vision-qwen 中位 26px/最大 81px/32% 超 40px，系统性偏移弱，
  另有同形文本混淆（メモリ/メモ）——证实"选编号"优于"报坐标"。
- 本地 grounding 模型后手（RTX 5090 D 32GB 可跑，暂不引入）：
  [UI-TARS-1.5-7B](https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B)（ScreenSpot-v2 94.2）、
  [GUI-G1-3B](https://arxiv.org/html/2505.15810v2)（ScreenSpot 90.3）；注意训练分布是系统
  App/网页，手游立绘 UI 需实测。

## 3. 自主 agent 循环架构（照抄范本）

- [Mobile-Agent-E](https://arxiv.org/abs/2501.11733)（NeurIPS 2025）五角色
  （Manager/Perceptor/Operator/Action Reflector/Notetaker）+ 结构化短期记忆 + Tips/Shortcuts
  长期记忆 + 分级错误升级（k=2 上报）+ 五种终止出口（最大 40 轮/连续错误 3/重复动作 3/解析失败/
  自报完成）。自曝教训：错误 Shortcuts 会传播错误——自愈必须回放验证。
- [Agent S2](https://arxiv.org/abs/2504.00906)：Manager-Driver-Evaluator 触发重规划。
- [AppAgent](https://arxiv.org/html/2312.13771v2)：探索期文档化=知识库生成先例。
- 游戏：[Lap](https://arxiv.org/abs/2507.09490)（OpenCV 识别→结构化状态→LLM 只消费状态，
  不让 LLM 直接看图）；Cradle 的 icon→文本预处理。

## 4. 自愈（诊断优先，防假通过）

- [QA Wolf 六类自愈分类学](https://www.qawolf.com/blog/self-healing-test-automation-types)：
  Timing ~30%/Selector ~28%/Test Data/Visual/Interaction/Runtime——先诊断归类再按类施治。
- [Healenium](https://healenium.io/)：成功基线库 + 候选相似度打分 + 人工复核报告。
- 修复阶梯映射：放宽阈值→重截模板→换识别算法→补前置导航→等待重试。

## 5. 护栏清单（多家综合）

动作白名单+默认拒绝、会话级累计预算熔断、三重终止、低层重试 k 次后升级、
修改前 git 快照回滚、自愈结果验证门槛、安全锚点页面
（[guardrails 纵深](https://www.prismor.dev/ai-agent-guardrails)、
[Bedrock 预算控制](https://aws.amazon.com/blogs/machine-learning/control-agent-behaviors-and-cost-beyond-a-single-action-new-capabilities-in-amazon-bedrock-agentcore/)）。

## 6. 同类先例确认

"LLM agent 自动生成/维护 MaaFramework pipeline"在公开域无成熟项目；
最接近：MaaMCP 智能生成、[Everything-Maa](https://github.com/KhazixW2/Everything-Maa)（预发布）、
[MAAplusAgent](https://github.com/FleurDeLysFDl/MAAplusAgent)（手游自由探索+探索记忆图+BFS
导航+双层护栏）。本工作流属自行组合落地。
