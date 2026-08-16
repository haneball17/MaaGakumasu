"""Round 模拟器本地 Web UI 入口(ADR-0002,M-UIa/M-UIb)。

用法:
    python tools/round_sim_app.py            # http://localhost:8642
    python tools/round_sim_app.py --port 9000

架构(§8.2):
- 开发模式:ui/ 下 `npm run dev`(Vite HMR,代理 /api 到本服务);
- 驱动模式(默认):本服务托管 ui/dist 构建产物 + /api/*;
- 离线降级:tools/render_round_ui.py 把 trace 注入自包含模板(规避 file:// CORS)。

API(M-UIa 只读 + M-UIb 驱动):
- GET  /api/presets                 内置预设清单
- GET  /api/trace?preset&seed&strategy      单局 trace
- GET  /api/distribution?preset&strategy&n  批量分布(N≤200 同步)
- POST /api/simulate                M-UIb:配置驱动(N≤200 同步;大 N/网格异步任务)
- GET  /api/tasks/{id} / POST /api/tasks/{id}/cancel       异步任务轮询/取消
- GET  /api/schema                  ScenarioSpec JSON Schema(pydantic 真源导出)
"""

from __future__ import annotations

import sys
import json
import uuid
import argparse
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.hif.roundsim import PRESETS, ScenarioSpec, run_exam, build_spec  # noqa: E402
from agent.hif.roundsim.strategies import make_strategy  # noqa: E402

UI_DIST = Path(__file__).resolve().parents[1] / "ui" / "dist"
CUSTOM_PRESETS_DIR = Path(__file__).resolve().parents[1] / "debug" / "roundsim" / "presets"
SYNC_N_LIMIT = 200

app = FastAPI(title="HIF Round Simulator", version="0.1")


def _all_presets() -> dict[str, ScenarioSpec]:
    """内置 + 用户自定义预设(debug/roundsim/presets/*.json,与 CLI 完全同源,§4.3)。"""
    merged = dict(PRESETS)
    if CUSTOM_PRESETS_DIR.exists():
        for path in sorted(CUSTOM_PRESETS_DIR.glob("*.json")):
            try:
                merged[path.stem] = ScenarioSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001 — 坏文件跳过并在清单标注
                merged[path.stem] = None  # type: ignore[assignment]
                print(f"[warn] 自定义预设 {path.name} 解析失败: {exc}")
    return merged


@app.get("/api/custom-presets")
def list_custom_presets() -> dict:
    items = []
    if CUSTOM_PRESETS_DIR.exists():
        for path in sorted(CUSTOM_PRESETS_DIR.glob("*.json")):
            items.append({"id": path.stem})
    return {"dir": str(CUSTOM_PRESETS_DIR), "presets": items}


@app.post("/api/custom-presets")
def save_custom_preset(body: dict) -> dict:
    """保存用户配置:{name, preset, overrides} → debug/roundsim/presets/<name>.json。"""
    name = (body.get("name") or "").strip()
    if not name or not all(ch.isalnum() or ch in "-_" for ch in name):
        raise HTTPException(400, "预设名仅限字母数字-_")
    base_id = body.get("preset", "hif_r1_rinami")
    if base_id not in PRESETS:
        raise HTTPException(404, f"未知预设 {base_id}")
    spec = build_spec(base_id, body.get("overrides"))
    CUSTOM_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    out = CUSTOM_PRESETS_DIR / f"{name}.json"
    out.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return {"saved": str(out)}

# ---------------------------------------------------------------------------
# 异步任务仓(M-UIb:大 N / 网格)
# ---------------------------------------------------------------------------

_TASKS: dict[str, dict] = {}
_TASK_LOCK = threading.Lock()


def _run_task(task_id: str, spec: ScenarioSpec, strategies: list[str], n: int, combined: bool, spec_r2: ScenarioSpec | None) -> None:
    from agent.hif.roundsim.ab import run_ab

    try:
        stats = run_ab(spec, strategies, n=n, preset_name="", spec_r2=spec_r2, bootstrap=True)
        with _TASK_LOCK:
            _TASKS[task_id].update(status="done", result=[s.summary() for s in stats])
    except Exception as exc:  # noqa: BLE001 — 任务失败要回传给前端
        with _TASK_LOCK:
            _TASKS[task_id].update(status="error", error=str(exc))


# ---------------------------------------------------------------------------
# M-UIa:只读 API
# ---------------------------------------------------------------------------


@app.get("/api/presets")
def list_presets() -> dict:
    merged = _all_presets()
    return {
        "presets": [
            {
                "id": pid,
                "turns": spec.exam_settings.turns if spec else 0,
                "deck_size": len(spec.scenario.deck) if spec else 0,
                "note": (spec.note if spec else "(解析失败,见服务端日志)"),
                "custom": pid not in PRESETS,
            }
            for pid, spec in merged.items()
        ]
    }


@app.get("/api/trace")
def get_trace(preset: str = "hif_r1_rinami", seed: int = 42, strategy: str = "garakuta_rinami") -> dict:
    merged = _all_presets()
    if preset not in merged or merged[preset] is None:
        raise HTTPException(404, f"未知预设 {preset}")
    try:
        strat = make_strategy(strategy) if strategy != "skip" else None
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    doc = run_exam(merged[preset], seed=seed, strategy=strat, preset_name=preset)
    return doc.model_dump()


@app.get("/api/distribution")
def get_distribution(preset: str = "hif_r1_rinami", strategy: str = "garakuta_rinami", n: int = 100) -> dict:
    n = max(1, min(n, SYNC_N_LIMIT))
    merged = _all_presets()
    if preset not in merged or merged[preset] is None:
        raise HTTPException(404, f"未知预设 {preset}")
    spec = merged[preset]
    scores = []
    for seed in range(n):
        doc = run_exam(spec, seed=seed, strategy=make_strategy(strategy), preset_name=preset)
        scores.append(doc.final.total_score)
    return {"preset": preset, "strategy": strategy, "n": n, "scores": scores}


# ---------------------------------------------------------------------------
# M-UIb:模拟驱动 + 异步任务 + schema
# ---------------------------------------------------------------------------


class SimulateRequest(BaseModel):
    """POST /api/simulate 载荷:ScenarioSpec 覆盖 + 运行参数(M-UIb 三档表单的消费端)。"""

    preset: str = "hif_r1_rinami"
    overrides: dict | None = None
    strategies: list[str] = ["garakuta_rinami"]
    n: int = 50
    seed0: int = 0
    combined: bool = False
    async_run: bool = False


@app.post("/api/simulate")
def simulate(req: SimulateRequest) -> dict:
    merged = _all_presets()
    if req.preset in merged and merged[req.preset] is not None:
        spec = build_spec(merged[req.preset], req.overrides)
    elif req.preset in PRESETS:
        spec = build_spec(req.preset, req.overrides)
    else:
        raise HTTPException(404, f"未知预设 {req.preset}")
    spec_r2 = build_spec("hif_r2_rinami") if req.combined and req.preset == "hif_r1_rinami" else None
    if req.async_run or req.n > SYNC_N_LIMIT:
        task_id = uuid.uuid4().hex[:12]
        with _TASK_LOCK:
            _TASKS[task_id] = {"status": "running", "n": req.n}
        threading.Thread(
            target=_run_task, args=(task_id, spec, req.strategies, req.n, req.combined, spec_r2), daemon=True
        ).start()
        return {"mode": "async", "task_id": task_id}
    from agent.hif.roundsim.ab import run_ab

    stats = run_ab(spec, req.strategies, n=req.n, preset_name=req.preset, spec_r2=spec_r2)
    return {"mode": "sync", "stats": [s.summary() for s in stats]}


@app.get("/api/tasks/{task_id}")
def task_status(task_id: str) -> dict:
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
    if task is None:
        raise HTTPException(404, f"未知任务 {task_id}")
    return task


@app.post("/api/tasks/{task_id}/cancel")
def task_cancel(task_id: str) -> dict:
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if task and task["status"] == "running":
            task["status"] = "cancelled"
    return {"ok": True}


@app.get("/api/schema")
def spec_schema() -> dict:
    return ScenarioSpec.model_json_schema()


# ---------------------------------------------------------------------------
# 静态托管(构建产物;未构建时 404 提示)
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    if (UI_DIST / "index.html").exists():
        return FileResponse(UI_DIST / "index.html")
    raise HTTPException(404, "ui/dist 不存在——先在 ui/ 下执行 npm install && npm run build,或用 npm run dev 开发模式")


if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")


def main() -> int:
    parser = argparse.ArgumentParser(description="HIF Round 模拟器本地 Web UI")
    parser.add_argument("--port", type=int, default=8642)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"roundsim UI → http://{args.host}:{args.port}(ui/dist 未构建时仅 /api 可用)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
