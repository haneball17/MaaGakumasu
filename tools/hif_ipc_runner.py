"""実機 Custom action 单点连测 runner（AgentClient 直连自管 agent 子进程）。

取代已删除的 tools/hif_live_runner.py（19370a3 删除后 skill 引用悬空一个月）。
用途：不跑完整管线，对单个 pipeline 节点（通常 DirectHit→Custom action 的
Flag 节点）做実機执行验证。

为什么不用 MaaMCP run_pipeline（2026-08-21 实测）：
- agent 拉起时序竞态——连续两次调用各带 Custom action 时，第二次返回
  succeeded 但 action 零执行（custom 日志无痕迹、页面不动）
- interface.json 的 agent.child_exec 在本机被 Store python 别名劫持
- pipeline_path 数组参数被序列化成单字符串、JSONC 被严格 json 预校验拒载

用法（设备地址经 MAA_DEV_ADDR 注入，MuMu 端口会漂移先 adb devices）：
    MAA_DEV_ADDR=127.0.0.1:16448 .venv/Scripts/python.exe tools/hif_ipc_runner.py \
        ProduceHIFSelectChangeSourceFlag [timeout_s]

IPC 协议要点（坑位实测）：
- AgentClient(identifier=uuid) 走 Named Pipe；子进程 `python -u agent/main.py <uuid>`
  （cwd=仓库根），main.py 取 argv[-1] 作 socket_id
- **bind(res) 必须在 connect() 之前**——顺序反了报 "resource is not bound"
- connect 需循环重试（agent 依赖检查+import 约 3-8s）
- register_sink(res, ctrl, tasker) 转发事件后 post_task 的 Custom action 才会
  经 IPC 分发到 agent

验收三件套（对应 maa-customaction-ipc-test skill）：
1. 本脚本 TASK_DONE status 与耗时
2. debug/custom/YYYY-MM-DD.log 出现目标 action 的业务日志（**零痕迹=零执行**，
   任务状态成功不代表 action 跑了）
3. debug/decisions/session-*.jsonl 决策落盘 + 実機画面 OCR 后态
"""

import sys
import time
import uuid
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from maa_dev import bind  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: hif_ipc_runner.py <entry_node> [timeout_s=240]")
        return 1
    entry = sys.argv[1]
    timeout_s = int(sys.argv[2]) if len(sys.argv) > 2 else 240

    from maa.agent_client import AgentClient

    ctrl, res, tasker = bind(need_device=True)
    identifier = str(uuid.uuid4())
    agent_proc = subprocess.Popen(
        [sys.executable, "-u", str(REPO_ROOT / "agent" / "main.py"), identifier],
        cwd=str(REPO_ROOT),
    )
    client = AgentClient(identifier)
    try:
        ok = False
        for _ in range(15):  # agent 依赖检查+import ~3-8s，留足窗口
            if client.bind(res) and client.connect():
                ok = True
                break
            time.sleep(1)
        if not ok:
            print("AGENT_CONNECT_FAIL")
            return 1
        if not client.register_sink(res, ctrl, tasker):
            print("REGISTER_SINK_FAIL")
            return 1
        print(f"agent ok (pid={agent_proc.pid}), posting task: {entry}")

        job = tasker.post_task(entry)
        started = time.time()
        while not job.done and time.time() - started < timeout_s:
            time.sleep(2)
        if not job.done:
            tasker.post_stop().wait()
            print("TASK_TIMEOUT")
            return 2
        status = getattr(getattr(job.status, "_status", None), "name", None) or str(job.status)
        print(f"TASK_DONE status={status} elapsed={time.time() - started:.1f}s")
        td = job.get()
        for node in getattr(td, "nodes", []) or []:
            print("node:", node.node_id, node.name)
        return 0
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        agent_proc.terminate()
        try:
            agent_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            agent_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
