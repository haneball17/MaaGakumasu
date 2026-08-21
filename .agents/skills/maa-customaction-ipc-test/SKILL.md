---
name: maa-customaction-ipc-test
description: 用 MaaFramework AgentClient/AgentServer IPC 実機验证 Python CustomAction。需要对单个 Custom action 节点做实机执行验证（不跑完整管线）、对新写的识别读取方法做 probe 单元実機验证（多轮纪律）、排查 action 未执行/静默失败，或以 nekosu.maa-support 在 VS Code 断点观察时使用。
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

## 识别新件单元验证（probe 模式，管线集成前的前置关卡）

新写的识别/读取类方法（OCR 读数、枚举、面板交互）**先 probe 直连单元验证，全绿才接管线**——纸面实现+单测绿≠実機可用（2026-08-21 用户叫停「未验证就 PlayFlag 连测」确立；probe2/3/4 三轮实践抓出 11 个実機 bug）。参照模板：`debug/autodev/round1/probe_state.py`（数值/手牌）、`probe_state2.py`（分带/面板/双源）、`probe3.py`（槽探测/枚举/懒定案）、`probe4.py`（面板滚动+自一致性）。

probe 要点：

1. **线上同源调用**：`maa_dev.bind(need_device=True)` + `tasker.post_recognition(JRecognitionType.X, JX(...), img)`——与 agent 线上 run_recognition 同引擎同参数；截图用 `ctrl.post_screencap().wait().get()`（BGR，与线上一致）。结果取法：`job.wait().get()` → `tasker.get_node_detail(td.node_id_list[0]).recognition`。
2. **不能 import produce_hif**：`@AgentServer` 装饰器会把 maa 库切到 AgentServer 模式，与 AdbController 互斥（MaaAgentServerNotImpl）——常量内联并注明「与 Play 类同步」。
3. **多轮纪律**：每件 ≥3 轮跨画面时点（実機画面活跃，轮间自然变化；件间加画面稳定检查——探测类操作 40s 期间可能转场拍到空帧）；验证标准=「读出值与该时点放大复核/vision 交叉一致」而非固定数值；**修复后该件轮次清零重计**（杜绝修一次验一次就过）。
4. **自一致性双跑**：同一画面完整读两次，清单比对须一致——差异条目先查 OCR 变体（长音符 ー 归一化后再判），残余 ≤1 条属单次漏检（双跑并集可达全量）。
5. **复刻漂移警告**：probe 复刻正式方法逻辑两度与真实行为分叉——复刻版只作首验，最终验证以「手动实证流程固化的简化版」为准，复杂复刻弃用。
6. **UI 约束前置**：写识别方案前先向用户要已知 UI 约束（元素数量上下限/位置稳定性/溢出行为/形态随内容浮动）——实测撞出来代价高（弹窗标题随瓶浮动、P item 随养成增长、buff 溢出省略号等约束全部来自用户告知）。

対局页动态锚定（四连坑实证）：弹窗标题/瓶名随内容浮动→先 OCR 锚定位再取相对带（禁固定 ROI）；入口 y 漂移→从当次枚举动态取；关闭验证锚选背景不出现的词；面板滚动用右缘起点 (545,640)（中央起点落可交互条目会被消费致滚动时灵时不灵）；清单条目键去长音符归一化。

## 前置与安全

1. 阅读目标任务入口、预期页面锚点和唯一允许动作；只执行用户授权的节点。grill 定案后的长链路可按用户「全自动」授权执行，但接管/放权切换时必须同步清理自动化状态（停任务+还原临时 patch）。
2. 确认 ADB 可连接、设备有画面，且游戏正处于入口要求的页面。未知页面、无画面或后态未知时停止。
3. 大段重写过的 action 先做静态自检再上実機：grep 旧标识符（旧常量/方法名）确认已删——Python 类体后定义的方法会静默覆盖前者，旧 `run()` 残留会让新版从未执行且编译/单测全绿掩盖（2026-08-21 変卡重写教训 db1c772）。

## VS Code 断点观察

只用 nekosu.maa-support 断点观察，不作为常规执行接口。把包含测试 `interface.json` 的目录本身作为 VS Code 工作区打开（仓库根工作区会优先加载正式 `assets/interface.json`，看不到测试任务）。interface 的 `agent.child_args` 只保留 Python 参数和 `agent/main.py`，不要填 `{AGENT_ID}`（插件自动追加）；断点启动配置的 args 必须保留 `{AGENT_ID}`，`cwd` 设仓库根。断点命中或 custom 日志出现该 action 事件才算 CustomAction 成功。

## 证据与收尾

日志和截图仅保留在 `debug/`，不提交。実機失败取证要趁早——每次 maa_dev 识别命令都会触发 maafw 日志滚动覆盖，先拷贝/摘录再跑后续操作。超时、识别失败和未知页面均保留证据后停止，不要盲目重试或放宽页面锚点。
