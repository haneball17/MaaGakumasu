---
name: maa-customaction-ipc-test
description: 用 MaaFramework AgentServer/AgentClient IPC 实机验证 Python CustomAction；需要用纯代码运行 HIF 等独立 Pipeline，或以 nekosu.maa-support 在 VS Code 断点观察时使用。
---

# Maa CustomAction 调试

优先用 `tools/hif_live_runner.py --agent-mode ipc` 做 Codex 可执行的实机验证。该模式启动项目正式 `agent/main.py`，通过 Maa `AgentClient` 注册 `resource`、`controller`、`tasker` 三个 sink，再运行 Pipeline；它验证的是 CustomAction 的实际 IPC 路径。

使用 VS Code 只为断点观察。`nekosu.maa-support` 不能作为 Codex 自动化 Agent 的常规执行接口，也不能仅凭 Agent 终端输出判断 Action 已执行。

## 实机前置

1. 阅读目标任务入口、预期页面锚点和唯一允许动作；HIF 只执行用户明确授权的单步测试。
2. 确认 ADB 可连接、设备有画面，并由用户确认游戏正处于入口要求页面。未知页面、无画面或后态未知时停止。
3. 确认 `agent/main.py` 和所测 CustomAction 已随当前工作区加载；不要修改正式 `assets/interface.json` 或正式用户任务来测试。

## 纯代码 IPC 测试

在仓库根运行，替换 ADB、入口和时限。需要触发点击时附加 `--single-step`，不要扩大授权范围：

```powershell
python tools/hif_live_runner.py `
  --adb 127.0.0.1:16416 `
  --adb-path "D:\MuMu\shell\adb.exe" `
  --task TestHIFDay1ChangeDeckEntry `
  --agent-mode ipc `
  --seconds 30
```

运行后检查 `debug/hif-live/<run-id>/manifest.json`、同目录的前后截图，以及 `debug/hif-journal/` 和 Maa 日志。完成条件必须同时具备：

1. `manifest.json` 记录任务完成且未失败；
2. Journal 或 Maa 日志出现目标 CustomAction 的调用或返回；
3. `after.png` 与该单步的预期后态一致。

只看到 `AgentServer 启动`、IPC 已连接或任务仍在运行，都不代表 CustomAction 已执行。超时会请求停止任务并清理 Agent 子进程；超时、识别失败和未知页面均应保留证据后停止，不要盲目重试或放宽页面锚点。

## VS Code 断点观察

将包含测试 `interface.json` 的目录本身作为 VS Code 工作区打开。插件只会加载工作区内的 interface；仓库根工作区会优先使用正式 `assets/interface.json`，看不到 `hif_test/interface.json` 的任务。

1. 确认测试 interface 的资源路径、`agent.child_exec` 和 `agent.child_args` 可用。interface 的 `agent.child_args` 只保留 Python 参数和 `agent/main.py`，不要填 `{AGENT_ID}`；插件会自动追加 UUID，Agent 入口将最后一个参数作为 UUID。
2. 打开测试目录，例如 `D:\code\MaaGakumasu\hif_test`，不要打开仓库根。
3. 从命令面板执行 `Maa: 执行任务`，选择测试任务；或在一个临时 VS Code 开发扩展中调用：

```js
vscode.commands.executeCommand("maa.launch-task", "HIF Day1 牌库入口");
```

`maa.launch-task` 的参数是 interface 中的任务 `name`，不是 Pipeline 的 `entry`。

插件任务显示成功不等于 Action 证据完整。检查最新 Journal 的目标事件、`image_type`、`fingerprint`、点击预算和停止原因；截图句柄没有像素数据时，VS Code 只可用于断点或已授权的固定候选卡 OCR 后验，不能验证 `次へ`、源牌或提交。需要可复核的端到端证据时，改用 `hif_live_runner.py --agent-mode ipc`。

## CustomAction 断点

在目标 Action 的 `run()` 设置断点。插件启动时会追加 Agent UUID；仅 VS Code 调试启动配置的 `args` 必须保留 `{AGENT_ID}`，不要把该占位符复制到 interface 的 `agent.child_args`，`cwd` 设为仓库根。断点命中或 Journal 出现该 Action 的事件才算 CustomAction 成功；任务“跟随中”时先检查 ADB 控制器与当前游戏页。

## 安全与收尾

HIF 测试只允许用户授权的单步动作。日志和截图仅保留在 `debug/`，不提交。临时开发扩展仅用于调用验证，完成后删除，不放入项目源码或正式 interface。
