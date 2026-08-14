# VS Code MAA 插件调试 HIF 管线指南

用 [nekosu.maa-support](https://marketplace.visualstudio.com/items?itemName=nekosu.maa-support) 插件人工调试 HIF 管线（`ProduceHIF.json` 路由 + `agent/custom/action/produce_hif.py` CustomAction 断点）。

## 链路结构

```
VS Code（打开 debug/vscode_maa/，不是仓库根）
 └─ 插件递归扫描工作区 → interface.json（HIF 调试任务集）
     ├─ resource/base → junction → assets/resource/base（管线/模板改动即时生效）
     ├─ 任务启动 → 插件自带 MaaFramework native 跑 pipeline
     └─ 需要 Agent 时按 .vscode/mse_config.json 的 agent.debug 映射
         → 读 .vscode/launch.json 的 "HIF Agent" 配置
         → 把 args 里的 {AGENT_ID} 替换为本次 AgentServer UUID
         → 以 debugpy 调试会话拉起 agent/main.py（断点可用）
```

工作区搭建/重建：`python tools/make_vscode_debug_ws.py`（幂等；任务与预设选项每次从 `assets/tasks/produce_cn.json` 重新提取）。

## 首次配置（一次）

1. VS Code 装 nekosu.maa-support 和 ms-python.debugpy 扩展。
2. `python tools/make_vscode_debug_ws.py` 生成 `debug/vscode_maa/`。
3. VS Code **单独打开 `debug/vscode_maa` 目录**。打开仓库根时插件会命中正式 `assets/interface.json`，看不到调试任务。
4. 命令面板（Ctrl+Shift+P）→ `Maa: 打开控制面板`，控制器选「模拟器」，配 ADB 路径与 MuMu 地址（本机为 `E:\game\MuMu\nx_device\12.0\shell\adb.exe` + `127.0.0.1:16416`），连接。

## 调试任务集

interface.json 内置 6 个任务，按当前游戏页面选择入口：

| 任务 | entry | 适用页面 |
| --- | --- | --- |
| 启动游戏 | `StartUp` | 游戏未开，从桌面冷启动 |
| HIF 全链路（主页→Round1） | `Produce`（含 HIF 改道 override） | 游戏主页 |
| HIF 入口直入（准备页） | `ProduceEntryHIF` | 偶像选择/HIF 准备页 |
| HIF 准备路由 | `ProduceHIFPrepRoot` | 准备阶段中途页面 |
| HIF 日程路由 | `ProduceHIFScheduleRoot` | 日程页（Day1 授業等） |
| HIF Round1 识别 | `ProduceHIFRound1Flag` | Round1 出牌画面 |

「HIF预设」选项与正式任务一致：安全默认（无 override）/ 莉波好调（实验）。

## 断点调试步骤

1. 在 `agent/custom/action/produce_hif.py` 目标 Action 的 `run()` 设断点（测试工作区窗口里 File → Open File 打开仓库文件即可，断点按绝对路径生效）。
2. 游戏就位：跑「启动游戏」或手动把游戏开到目标页面。
3. 命令面板 → `Maa: 执行任务`（maa.launch-task）→ 选任务。参数是 interface 里的任务 `name`，不是 pipeline entry。
4. 插件拉起 debugpy 会话（终端标题 HIF Agent），pipeline 走到 CustomAction 时断点命中。
5. 断点期间 MaaFW 侧任务挂起等待返回，属于预期行为；放行后继续。

任务显示成功 ≠ Action 已执行。验证要看断点命中或 agent 终端里出现目标 Action 的调用日志。

## 已知约束

- `interface.json` 的 `agent.child_args` 不填 `{AGENT_ID}`（插件自动追加）；只有 launch.json 的 args 保留该占位符。
- launch.json 的 `cwd`/`PYTHONPATH` 必须是仓库根：`agent/main.py` 的 `from agent.hif...` 绝对导入依赖。
- 插件设置 `maa.agentTimeout`（默认 30000ms）是等 Agent 连上的超时；debugpy 冷启动慢时可调大。
- HIF 实机单步操作需遵守 `ProduceHIFUnknownStop` 安全停止边界（见 `.agents/skills/hif-manual-test`），未知页面停止排查，不猜测点击。
- 需要 Codex/脚本自动化验证端到端证据时，用 `debug/hif_run.py --entry <节点>`（AgentClient IPC 模式），VS Code 插件只用于人工断点观察。
