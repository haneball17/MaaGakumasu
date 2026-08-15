"""重建 nekosu.maa-support 调试工作区 debug/vscode_maa/。

工作区本身在 debug/ 下不入库；本脚本把搭建过程固化，丢失或升级管线后可一键重建。
生成内容：

- resource/base  → junction 到 assets/resource/base（管线/模板改动即时生效）
- interface.json → HIF 调试任务集（任务与预设选项从 assets/tasks/produce_cn.json 提取）
- .vscode/launch.json   → debugpy 断点配置（{AGENT_ID} 由插件替换）
- .vscode/mse_config.json → agent.debug 映射（child_exec → 调试配置名）

用法：
    python tools/make_vscode_debug_ws.py            # 幂等，已存在文件跳过
    python tools/make_vscode_debug_ws.py --force    # 覆盖已生成文件（junction 不删）

详见 docs/hif/vscode-maa-debug.md。
"""

from __future__ import annotations

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WS = REPO / "debug" / "vscode_maa"

LAUNCH_JSON = """{
    // HIF Agent 断点调试配置：由 nekosu.maa-support 插件通过 mse_config.json 的
    // agent.debug 映射拉起。{AGENT_ID} 由插件替换为本次 AgentServer 的 UUID，
    // 其余为 debugpy 常规配置。cwd/PYTHONPATH 必须是仓库根（agent/main.py 的
    // from agent.hif... 绝对导入依赖）。
    "version": "0.2.0",
    "configurations": [
        {
            "name": "HIF Agent",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/../../agent/main.py",
            "args": ["{AGENT_ID}"],
            "cwd": "${workspaceFolder}/../..",
            "console": "integratedTerminal",
            "justMyCode": false,
            "env": {
                "PYTHONPATH": "${workspaceFolder}/../.."
            }
        }
    ]
}
"""

MSE_CONFIG_JSON = """{
    // nekosu.maa-support 插件配置：键=interface.json 里 agent.child_exec，
    // 值=launch.json 中调试配置名。存在此映射时，插件跑任务需要 Agent 就会以
    // VS Code 调试会话（F5 断点可用）拉起 agent，而不是普通终端 Task。
    "agent.debug": {
        "python": "HIF Agent"
    }
}
"""

README_MD = """# MaaGakumasu HIF 调试工作区（nekosu.maa-support）

本目录是 VS Code MAA 插件的独立工作区，**不要在仓库根窗口里找这里的任务**。
使用说明见 `docs/hif/vscode-maa-debug.md`（仓库根）。

工作区损坏时运行 `python tools/make_vscode_debug_ws.py` 重建。
"""


def build_interface() -> dict:
    """从 assets/tasks/produce_cn.json 提取 HIF 任务与预设，组装测试 interface。"""
    produce = json.loads((REPO / "assets" / "tasks" / "produce_cn.json").read_text(encoding="utf-8"))
    opts = produce["option"]

    hif_case = next(c for c in opts["培育难度"]["cases"] if c["name"] == "HIF")
    hif_entry_override = hif_case["pipeline_override"]

    preset_cases = [
        {"name": c["name"], **({"pipeline_override": c["pipeline_override"]} if c.get("pipeline_override") else {})}
        for c in opts["HIF预设"]["cases"]
    ]
    tendency_cases = [
        {"name": c["name"], **({"pipeline_override": c["pipeline_override"]} if c.get("pipeline_override") else {})}
        for c in opts["培育倾向"]["cases"]
    ]

    def hif_options():
        return ["HIF预设", "培育倾向"]

    return {
        "interface_version": "1.0",
        "name": "MaaGakumasu HIF Debug",
        "controller": [{"name": "模拟器", "type": "Adb"}],
        "resource": [{"name": "官服-base", "path": ["./resource/base"], "controller": ["模拟器"]}],
        "agent": {
            "child_exec": "python",
            "child_args": ["-u", "./../../agent/main.py"],
        },
        "task": [
            {"name": "启动游戏", "entry": "StartUp"},
            {
                "name": "HIF 全链路（主页→Round1）",
                "entry": "Produce",
                "option": hif_options(),
                "pipeline_override": hif_entry_override,
            },
            {"name": "HIF 入口直入（准备页）", "entry": "ProduceEntryHIF", "option": hif_options()},
            {"name": "HIF 准备路由", "entry": "ProduceHIFPrepRoot", "option": hif_options()},
            {"name": "HIF 日程路由", "entry": "ProduceHIFScheduleRoot", "option": hif_options()},
            {"name": "HIF Round1 识别", "entry": "ProduceHIFRound1Flag", "option": hif_options()},
        ],
        "option": {
            "HIF预设": {
                "type": "select",
                "default_case": opts["HIF预设"]["default_case"],
                "cases": preset_cases,
            },
            "培育倾向": {
                "type": "select",
                "default_case": opts["培育倾向"]["default_case"],
                "cases": tendency_cases,
            },
        },
    }


def write_file(path: Path, content: str, force: bool) -> bool:
    if path.exists() and not force:
        print(f"skip(已存在): {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"write: {path}")
    return True


def make_junction(force: bool) -> None:
    link = WS / "resource" / "base"
    target = REPO / "assets" / "resource" / "base"
    if link.exists():
        print(f"skip(junction 已存在): {link}")
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, MSYS2_ARG_CONV_EXCL="*")
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[FATAL] mklink 失败: {r.stdout} {r.stderr}")
        sys.exit(1)
    print(f"junction: {link} -> {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="覆盖已生成的文件（junction 不删）")
    args = parser.parse_args()

    make_junction(args.force)
    write_file(WS / "interface.json", json.dumps(build_interface(), ensure_ascii=False, indent=4) + "\n", args.force)
    write_file(WS / ".vscode" / "launch.json", LAUNCH_JSON, args.force)
    write_file(WS / ".vscode" / "mse_config.json", MSE_CONFIG_JSON, args.force)
    write_file(WS / "README.md", README_MD, args.force)
    print("\n完成。VS Code 打开该目录（不是仓库根）后即可用 MAA 插件调试，见 docs/hif/vscode-maa-debug.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
