# pipeline-autodev：无人化管线开发调试工作流

状态：已实机验证（2026-08-20 首次端到端演练 3/3 连测 + 4/4 回归，报告见
`debug/autodev/autodev-drill-01/report.md`，演练产物不入库）。

## 一句话

对 agent 说"用 autodev 给 XX 页面做节点"，agent 按
[.agents/skills/pipeline-autodev/SKILL.md](../../.agents/skills/pipeline-autodev/SKILL.md)
固化的五角色循环（感知/执行/反思/记录/管理）自主完成：探索页面 → 精确定位元素 →
裁模板/生成节点 → 实机连测 → 回放回归 → 证据报告。人工只在危险操作确认、超预算升级、
终审时介入。

## 分层

```
编排层  pipeline-autodev skill（ZCode 主 agent 驱动）
工具层  tools/maa_dev.py（原子 CLI） + MaaMCP MCP server（仓库 .zcode/config.json 注册）
底座    maafw binding + MuMu adb
```

## 工具速查（tools/maa_dev.py，统一 JSON 输出）

| 子命令 | 在线/离线 | 用途 |
|---|---|---|
| `snap` | 在线 | 截图（BGR→RGB 修正）落盘 |
| `ocr <img> [--roi X Y W H]` | 离线 | 全量文本 box/text/score（坐标真值来源） |
| `som <img> --boxes ...` | 离线 | SoM 编号叠加图（视觉模型只选编号） |
| `click` / `swipe` | 在线 | 设备输入 |
| `crop <img> --box ...` | 离线 | 裁模板 + manifest 登记（image/autodev/） |
| `reco <img> --type T --param JSON` | 离线 | 即时识别测试（TemplateMatch/OCR/ColorMatch/NN，不跑管线） |
| `test-node <node> --n 3` | 在线 | 单节点实机连测，前后截图证据 |
| `replay --suite tests/replay_suite` | 离线 | 基准截图回归命中矩阵 |
| `journal <json> --run-id <id>` | 离线 | 追加 debug/autodev/<run-id>/journal.jsonl |

环境变量：`MAA_DEV_ADB`（adb 路径）、`MAA_DEV_ADDR`（设备地址，默认 127.0.0.1:16416；
MuMu 每次启动端口可能变化，以 `adb devices` 实际为准）。

## 坐标裁决（核心设计）

视觉模型（vision-qwen）裸坐标实测中位误差 26px、最大 81px（2026-08-20 校准，
`debug/autodev/m3-calib/report.md`），**永不直接产出点击坐标**：

1. 文本 UI：OCR box → SoM 编号 → 视觉选编号 → 坐标取 box 中心
2. 图标 UI：模板匹配 / YOLO 检测出框 → 同上
3. 兜底：两阶段 crop-zoom
4. 每次点击后截图三态判定（成功/进错页/无变化）

## 护栏

单节点 5 次重试/15 分钟，会话 90 分钟；三重终止（迭代 40/连续错误 3/重复动作 3）；
危险操作白名单（扭蛋/购买/确认弹窗/体力药/开战）同步等用户确认；
设备不在线即停不重试超过 2 次；全程 journal 落盘。

## 验收口径

`test-node --n 3` 全中 + `replay` 回归通过 + `pytest tests/test_maa_dev.py` +
`tools/ci/check_resource.py` + prettier check（改动文件）。

## 可视化调试（人工审阅用，agent 不依赖）

- **MaaDebugger**（已装 venv，`pip install MaaDebugger`）：`MaaDebugger.exe` 起本地 Web
  （默认 8011），看节点执行链与识别详情。
- **MaaLogAnalyzer**：VS Code 插件市场安装，或桌面版；对 `debug/maa.log` 出流程图回放与
  节点统计。注意日志含本地路径，勿用在线版上传。
- MaaMCP MCP server：`.zcode/config.json` 已注册（串行模式 `maa-mcp`），新会话自动连接，
  提供 ocr/screencap/click/run_pipeline 等工具直调（持久连接）。

## 首次演练记录

2026-08-20 主页「プロデュース」OCR 节点：离线 sweep 选 ROI[258,969,202,60]（expand=5，
四档全 0.998+）→ 实机连测 3/3（score 0.9993+）→ 回归 4/4 → 期间自修复 1 处工具 bug
（test-node 状态判定）。临时节点与证据存 `debug/autodev/autodev-drill-01/`。
