---
name: maa-customaction-ipc-test
description: 用 MaaFramework AgentClient/AgentServer IPC 実機验证 Python CustomAction。需要对单个 Custom action 节点做实机执行验证（不跑完整管线）、排查 action 未执行/静默失败，或以 nekosu.maa-support 在 VS Code 断点观察时使用。
---

# Maa CustomAction 调试

优先用 `tools/hif_ipc_runner.py` 做実機单点连测（AgentClient 直连自管 agent 子进程，2026-08-21 实测跑通；取代 19370a3 已删除的 hif_live_runner.py）。它验证的是 CustomAction 的实际 IPC 路径。

## 纯代码 IPC 测试

设备地址经 `MAA_DEV_ADDR` 注入（MuMu 端口会漂移，先 `adb devices` 查实际端口；adb 在 `E:\game\MuMu\nx_device\12.0\shell\adb.exe`）：

```bash
MAA_DEV_ADDR=127.0.0.1:16448 .venv/Scripts/python.exe tools/hif_ipc_runner.py \
    ProduceHIFSelectChangeSourceFlag 240
```

参数：节点名（通常为 DirectHit→Custom 的 Flag 节点）+ 可选超时秒数（默认 240）。

### IPC 协议要点（自行改脚本或排障时需要）

- `AgentClient(identifier=uuid)` 走 Named Pipe；子进程 `sys.executable -u agent/main.py <uuid>`（cwd=仓库根，main.py 取 argv[-1] 作 socket_id）
- **`bind(res)` 必须在 `connect()` 之前**——顺序反了报 `resource is not bound`
- connect 需循环重试（agent 依赖检查+import 约 3-8s）
- `register_sink(res, ctrl, tasker)` 之后 post_task 的 Custom action 才经 IPC 分发到 agent

### 不要用 MaaMCP run_pipeline 跑 Custom action（2026-08-21 实测三坑）

1. **agent 拉起时序竞态**：连续两次调用各带 Custom action 时，第二次返回 `succeeded` 但 action 零执行——比失败更危险，因为看起来成功了。
2. `interface.json` 的 `agent.child_exec: "python"` 被 Microsoft Store 别名劫持（本机），agent `connect()` 返回 False。
3. `pipeline_path` 数组参数被序列化成单字符串；`Produce*.json` 为 JSONC 被其严格 json 预校验拒载。

（若必须用 MCP 跑纯识别节点：单文件多次调用 + `on_conflict: overwrite` 利用节点驻留；JSONC 先做去注释+去尾逗号的 strict 副本；child_exec 临时 patch 为 `.venv` 绝对路径、跑完恢复。）

## 验收三件套（全部满足才算执行成功）

1. **runner 输出**：`TASK_DONE status=succeeded` 与耗时合理。
2. **custom 日志**：`debug/custom/YYYY-MM-DD.log` 出现目标 action 的业务日志。**零痕迹=零执行**——任务状态成功不代表 action 跑了（MCP 竞态就是这样骗过状态检查的）。只有「AgentServer 启动」「IPC 已连接」同样不算。
3. **决策落盘 + 画面后态**：`debug/decisions/session-*.jsonl` 出现该 action 的决策记录（若有落盘逻辑），且実機画面 OCR 与该单步的预期后态一致。

只看 manifest/journal 的旧验收法已随 hif_live_runner.py 消亡，勿再寻找那两类文件。

## 前置与安全

1. 阅读目标任务入口、预期页面锚点和唯一允许动作；只执行用户授权的节点。grill 定案后的长链路可按用户「全自动」授权执行，但接管/放权切换时必须同步清理自动化状态（停任务+还原临时 patch）。
2. 确认 ADB 可连接、设备有画面，且游戏正处于入口要求的页面。未知页面、无画面或后态未知时停止。
3. 大段重写过的 action 先做静态自检再上実機：grep 旧标识符（旧常量/方法名）确认已删——Python 类体后定义的方法会静默覆盖前者，旧 `run()` 残留会让新版从未执行且编译/单测全绿掩盖（2026-08-21 変卡重写教训 db1c772）。

## VS Code 断点观察

只用 nekosu.maa-support 断点观察，不作为常规执行接口。把包含测试 `interface.json` 的目录本身作为 VS Code 工作区打开（仓库根工作区会优先加载正式 `assets/interface.json`，看不到测试任务）。interface 的 `agent.child_args` 只保留 Python 参数和 `agent/main.py`，不要填 `{AGENT_ID}`（插件自动追加）；断点启动配置的 args 必须保留 `{AGENT_ID}`，`cwd` 设仓库根。断点命中或 custom 日志出现该 action 事件才算 CustomAction 成功。

## 证据与收尾

日志和截图仅保留在 `debug/`，不提交。実機失败取证要趁早——每次 maa_dev 识别命令都会触发 maafw 日志滚动覆盖，先拷贝/摘录再跑后续操作。超时、识别失败和未知页面均保留证据后停止，不要盲目重试或放宽页面锚点。
