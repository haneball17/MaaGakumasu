"""HIF 决策日志查看器 CLI 薄壳:手动生成/更新 debug/decisions/decisions.html。

生成逻辑在 agent/hif/decisions/viewer.py(决策存档后会自动刷新,本命令用于手动重建)。
"""

from agent.hif.decisions.viewer import main

if __name__ == "__main__":
    raise SystemExit(main())
