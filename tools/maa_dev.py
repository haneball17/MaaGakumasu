"""maa_dev — pipeline-autodev 无人化管线开发的原子工具 CLI。

供编排 agent（ZCode 主会话）以 Bash 调用，输出统一 JSON 信封：
    成功: {"ok": true, ...}（退出码 0）
    失败: {"ok": false, "error": "..."}（退出码 1）

子命令:
    snap                          连设备截图（BGR→RGB 修正）落盘
    ocr <image> [--roi X Y W H]   对本地截图跑 MaaFW OCR，输出 box/text/score
    som <image> --boxes B[;B..]   生成 SoM 编号叠加图（B 为 x,y,w,h）
    click X Y                     设备点击
    swipe X1 Y1 X2 Y2 [MS]        设备滑动
    crop <image> --box X,Y,W,H    裁模板图 + 登记 manifest
    reco <image> --type T --param JSON   即时识别测试（不跑管线，离线可用）
    test-node NODE [--n 3]        实机单节点连测 N 次（前后截图证据）
    replay --suite DIR            对基准截图逐节点离线识别，输出命中矩阵
    journal EVENT_JSON            追加事件到 run journal

环境变量:
    MAA_DEV_ADB   adb 可执行文件路径（默认 MuMu: E:\\game\\MuMu\\nx_device\\12.0\\shell\\adb.exe）
    MAA_DEV_ADDR  设备地址（默认 127.0.0.1:16416）

在线操作单驱动原则：探索循环的在线操作优先走 MaaMCP MCP server（持久连接）；
本脚本在线命令（snap/click/swipe/test-node）为脚本化场景备用，每次调用独立短连接。
"""

from __future__ import annotations

import os
import sys
import json
import time
import argparse
import datetime
from typing import Any
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESOURCE_BASE = REPO / "assets" / "resource" / "base"
PIPELINE_DIR = RESOURCE_BASE / "pipeline"
IMAGE_DIR = RESOURCE_BASE / "image"
AUTODEV_DIR = REPO / "debug" / "autodev"

DEFAULT_ADB = r"E:\game\MuMu\nx_device\12.0\shell\adb.exe"
DEFAULT_ADDR = "127.0.0.1:16416"

# 单节点连测的硬上限，防误传 --n 1000 之类长时间占用实机
TEST_NODE_MAX_N = 10
TEST_NODE_TIMEOUT_S = 60

RECO_LEAF_TYPES = {
    "OCR",
    "TemplateMatch",
    "FeatureMatch",
    "ColorMatch",
    "NeuralNetworkClassify",
    "NeuralNetworkDetect",
}

_TOOLKIT_READY = False


# ---------------------------------------------------------------------------
# 通用输出与环境
# ---------------------------------------------------------------------------

def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def fail(error: str) -> int:
    emit({"ok": False, "error": error})
    return 1


def adb_path() -> str:
    return os.getenv("MAA_DEV_ADB", DEFAULT_ADB)


def adb_addr() -> str:
    return os.getenv("MAA_DEV_ADDR", DEFAULT_ADDR)


def _init_toolkit() -> None:
    global _TOOLKIT_READY
    if not _TOOLKIT_READY:
        from maa.toolkit import Toolkit

        Toolkit.init_option(str(REPO))
        _TOOLKIT_READY = True


def _make_stub_controller() -> Any:
    """构造离线占位控制器（CustomController 实现）。

    maafw 的 Tasker 必须 inited（resource + 已连接 controller 齐备）才能跑
    post_recognition；pip 版 maafw 不附带 MaaDbgControlUnit.dll，故用
    CustomController 自实现等价物：connect 直接过、screencap 返回黑图、
    输入操作直接成功。识别时图片由 post_recognition 显式传入，不走 screencap。
    """
    from maa.controller import CustomController

    class _StubImpl(CustomController):
        def connect(self) -> bool:
            return True

        def connected(self) -> bool:
            return True

        def request_uuid(self) -> str:
            return "maa-dev-offline"

        def start_app(self, intent: str) -> bool:
            return True

        def stop_app(self, intent: str) -> bool:
            return True

        def screencap(self):
            import numpy as np

            return np.zeros((1280, 720, 3), dtype=np.uint8)

        def click(self, x: int, y: int) -> bool:
            return True

        def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> bool:
            return True

        def touch_down(self, contact: int, x: int, y: int, pressure: int) -> bool:
            return True

        def touch_move(self, contact: int, x: int, y: int, pressure: int) -> bool:
            return True

        def touch_up(self, contact: int) -> bool:
            return True

        def click_key(self, keycode: int) -> bool:
            return True

        def input_text(self, text: str) -> bool:
            return True

        def key_down(self, keycode: int) -> bool:
            return True

        def key_up(self, keycode: int) -> bool:
            return True

    return _StubImpl()


def bind(need_device: bool) -> tuple[Any, Any, Any]:
    """绑定 (controller, resource, tasker)。

    need_device=False 时供离线识别（ocr/reco/replay）：绑定 _make_stub_controller()
    构造的离线占位控制器（connect 直接过、输入直接成功），识别引擎照常可用，
    完全不占设备——Tasker 必须 inited 才能跑 post_recognition，所以离线路径
    也需要一个已连接的 controller。
    """
    from maa.tasker import Tasker
    from maa.resource import Resource
    from maa.controller import AdbController

    _init_toolkit()
    if need_device:
        ctrl: Any = AdbController(adb_path(), adb_addr())
        if not ctrl.post_connection().wait().succeeded:
            raise RuntimeError(f"设备连接失败: {adb_addr()}（模拟器是否已启动？）")
    else:
        ctrl = _make_stub_controller()
        if not ctrl.post_connection().wait().succeeded:
            raise RuntimeError("离线占位控制器连接失败")
    res = Resource()
    if not res.post_bundle(str(RESOURCE_BASE)).wait().succeeded:
        raise RuntimeError(f"资源加载失败: {RESOURCE_BASE}")
    tasker = Tasker()
    if not tasker.bind(res, ctrl):
        raise RuntimeError("tasker bind 失败")
    return ctrl, res, tasker


# ---------------------------------------------------------------------------
# 纯函数（离线可单测）
# ---------------------------------------------------------------------------

def clip_roi(box: list[int], expand: int, screen_w: int, screen_h: int) -> list[int]:
    """box [x,y,w,h] 四周扩 expand 像素并裁剪到屏幕内；非法时回退原 box。"""
    x, y, w, h = box
    rx = max(0, x - expand)
    ry = max(0, y - expand)
    rw = min(screen_w - rx, w + 2 * expand)
    rh = min(screen_h - ry, h + 2 * expand)
    if rw <= 0 or rh <= 0:
        return [x, y, w, h]
    return [rx, ry, rw, rh]


def draw_som(
    image: Any,
    boxes: list[list[int]],
    labels: list[str] | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    """在 PIL 图上为候选框画红框+编号角标，返回 (叠加图, 编号映射表)。"""
    from PIL import ImageDraw

    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    labels = labels or [""] * len(boxes)
    mapping: list[dict[str, Any]] = []
    for i, (box, label) in enumerate(zip(boxes, labels)):
        x, y, w, h = box
        draw.rectangle([x, y, x + w, y + h], outline=(255, 48, 48), width=3)
        tag = str(i)
        tx, ty = x, max(0, y - 14)
        draw.rectangle([tx, ty, tx + 9 + 8 * len(tag), ty + 14], fill=(255, 48, 48))
        draw.text((tx + 4, ty + 1), tag, fill=(255, 255, 255))
        mapping.append({"index": i, "box": [x, y, w, h], "label": label})
    return canvas, mapping


def journal_line(event: dict[str, Any], run_id: str, now: str | None = None) -> dict[str, Any]:
    """构造 journal.jsonl 单行记录。"""
    return {
        "ts": now or datetime.datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        **event,
    }


def build_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """由逐条 replay 结果构建命中矩阵汇总。"""
    hits = [r for r in rows if r["hit"]]
    misses = [r for r in rows if not r["hit"]]
    return {
        "total": len(rows),
        "hits": len(hits),
        "misses": len(misses),
        "pass": not misses,
        "detail": rows,
    }


def resolve_template_path(template: str) -> str:
    """模板路径解析：相对路径先按原样，再按 resource image 目录解析。"""
    p = Path(template)
    if p.is_absolute() and p.exists():
        return str(p)
    if p.exists():
        return str(p.resolve())
    candidate = IMAGE_DIR / template
    if candidate.exists():
        return str(candidate)
    return template


def recognition_from_node(node: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """从 pipeline 节点定义提取 (recognition_type, param_dict)。

    兼容 v2（recognition.type/param）与 v1（recognition 与字段平铺）两种格式。
    仅支持叶子识别类型；Custom/DirectHit/And/Or 返回 None（离线不可复现）。
    """
    reco = node.get("recognition", {})
    if isinstance(reco, str):
        # v1 格式：recognition 为类型字符串，参数平铺在节点层
        rtype = reco
        param = {k: v for k, v in node.items() if k != "recognition"}
    else:
        rtype = reco.get("type") or reco.get("recognition")
        if not rtype:
            return None
        param = reco.get("param", {})
        if not isinstance(param, dict):
            param = {}
    if rtype not in RECO_LEAF_TYPES:
        return None
    return (rtype, dict(param))


def param_to_dataclass(rtype: str, param: dict[str, Any], image_wh: tuple[int, int]) -> Any:
    """param dict → maafw 识别参数 dataclass；roi 缺省/零值时填全屏。"""
    import dataclasses

    import maa.pipeline as mp

    cls_map = {
        "OCR": mp.JOCR,
        "TemplateMatch": mp.JTemplateMatch,
        "FeatureMatch": mp.JFeatureMatch,
        "ColorMatch": mp.JColorMatch,
        "NeuralNetworkClassify": mp.JNeuralNetworkClassify,
        "NeuralNetworkDetect": mp.JNeuralNetworkDetect,
    }
    cls = cls_map[rtype]
    fields = {f.name for f in dataclasses.fields(cls)}
    kwargs = {k: v for k, v in param.items() if k in fields}
    roi = kwargs.get("roi")
    if not roi or (isinstance(roi, (list, tuple)) and len(roi) == 4 and roi[2] <= 0):
        kwargs["roi"] = [0, 0, image_wh[0], image_wh[1]]
    if rtype == "TemplateMatch" and "template" in kwargs:
        kwargs["template"] = [resolve_template_path(t) for t in kwargs["template"]]
    return cls(**kwargs)


def result_to_dict(r: Any) -> dict[str, Any]:
    """识别结果对象 → dict（box/text/label/score 防御性读取）。"""
    box = list(getattr(r, "box", None) or [0, 0, 0, 0])
    out: dict[str, Any] = {"box": [int(v) for v in box]}
    for key in ("text", "label"):
        val = getattr(r, key, None)
        if val is not None:
            out[key] = val
    score = getattr(r, "score", None)
    out["score"] = round(float(score), 4) if score is not None else None
    return out


# ---------------------------------------------------------------------------
# 离线识别核心
# ---------------------------------------------------------------------------

def run_recognition_offline(tasker: Any, rtype: str, param: dict[str, Any], image_path: Path) -> dict[str, Any]:
    """对本地截图执行一次识别。

    hit 用引擎的 RecognitionDetail.hit（含 expected/threshold 过滤语义）；
    results = filtered_results（命中相关），all_results 另附供诊断。
    """
    import numpy as np
    from PIL import Image
    from maa.pipeline import JRecognitionType

    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    reco_param = param_to_dataclass(rtype, param, img.size)
    job = tasker.post_recognition(JRecognitionType(rtype), reco_param, arr)
    td = job.wait().get()
    reco = tasker.get_node_detail(td.node_id_list[0]).recognition
    if not reco:
        return {"image": str(image_path), "type": rtype, "hit": False, "results": [], "all_results": []}
    return {
        "image": str(image_path),
        "type": rtype,
        "hit": bool(reco.hit),
        "results": [result_to_dict(r) for r in (reco.filtered_results or [])],
        "all_results": [result_to_dict(r) for r in (reco.all_results or [])],
    }


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def cmd_snap(args: argparse.Namespace) -> int:
    import numpy as np
    from PIL import Image

    ctrl, _, _ = bind(need_device=True)
    img = ctrl.post_screencap().wait().get()
    if img is None or not isinstance(img, np.ndarray) or img.size == 0:
        return fail("截图失败（post_screencap 返回空）")
    h, w = img.shape[:2]
    out = Path(args.out) if args.out else AUTODEV_DIR / "snaps" / f"snap-{int(time.time())}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    # post_screencap 返回 BGR 序，保存前翻转为 RGB
    Image.fromarray(img[..., ::-1]).save(out)
    emit({"ok": True, "path": str(out), "width": w, "height": h})
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    image = Path(args.image)
    if not image.exists():
        return fail(f"截图不存在: {image}")
    _, _, tasker = bind(need_device=False)
    param: dict[str, Any] = {}
    if args.roi:
        param["roi"] = list(args.roi)
    out = run_recognition_offline(tasker, "OCR", param, image)
    emit({"ok": True, **out})
    return 0


def cmd_som(args: argparse.Namespace) -> int:
    from PIL import Image

    image = Path(args.image)
    if not image.exists():
        return fail(f"截图不存在: {image}")
    boxes = [[int(v) for v in b.split(",")] for b in args.boxes.split(";")]
    labels = args.labels.split(";") if args.labels else None
    if labels and len(labels) != len(boxes):
        return fail(f"labels 数量({len(labels)})与 boxes 数量({len(boxes)})不一致")
    img = Image.open(image).convert("RGB")
    canvas, mapping = draw_som(img, boxes, labels)
    out = image.with_name(image.stem + "_som.png")
    canvas.save(out)
    emit({"ok": True, "som_image": str(out), "mapping": mapping})
    return 0


def cmd_click(args: argparse.Namespace) -> int:
    ctrl, _, _ = bind(need_device=True)
    ok = ctrl.post_click(args.x, args.y).wait().succeeded
    emit({"ok": True, "action": "click", "x": args.x, "y": args.y, "posted": bool(ok)})
    return 0 if ok else fail("click post 失败")


def cmd_swipe(args: argparse.Namespace) -> int:
    ctrl, _, _ = bind(need_device=True)
    ok = ctrl.post_swipe(args.x1, args.y1, args.x2, args.y2, args.ms).wait().succeeded
    emit({"ok": True, "action": "swipe", "posted": bool(ok)})
    return 0 if ok else fail("swipe post 失败")


def cmd_crop(args: argparse.Namespace) -> int:
    from PIL import Image

    image = Path(args.image)
    if not image.exists():
        return fail(f"截图不存在: {image}")
    box = [int(v) for v in args.box.split(",")]
    if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
        return fail(f"box 非法: {args.box}（应为 x,y,w,h 且 w/h>0）")
    name = args.name or f"crop-{int(time.time())}"
    dest_dir = Path(args.dest) if args.dest else IMAGE_DIR / "autodev"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{name}.png"
    img = Image.open(image).convert("RGB")
    cropped = img.crop((box[0], box[1], box[0] + box[2], box[1] + box[3]))
    cropped.save(out)

    manifest_path = dest_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = {
        "file": out.name,
        "source_image": str(image),
        "box": box,
        "image_size": list(img.size),
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": args.note or "",
    }
    manifest[name] = entry
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    emit({"ok": True, "template": str(out), "manifest": str(manifest_path), "entry": entry})
    return 0


def cmd_reco(args: argparse.Namespace) -> int:
    image = Path(args.image)
    if not image.exists():
        return fail(f"截图不存在: {image}")
    if args.type not in RECO_LEAF_TYPES:
        return fail(f"不支持的识别类型: {args.type}（可选: {sorted(RECO_LEAF_TYPES)}）")
    param = json.loads(args.param) if args.param else {}
    _, _, tasker = bind(need_device=False)
    out = run_recognition_offline(tasker, args.type, param, image)
    emit({"ok": True, **out})
    return 0


def cmd_test_node(args: argparse.Namespace) -> int:
    from PIL import Image

    n = max(1, min(args.n, TEST_NODE_MAX_N))
    ctrl, _, tasker = bind(need_device=True)
    evidence_dir = AUTODEV_DIR / f"test-node-{args.node}-{int(time.time())}"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    hits = 0
    for i in range(n):
        before = evidence_dir / f"run{i}-before.png"
        img = ctrl.post_screencap().wait().get()
        Image.fromarray(img[..., ::-1]).save(before)
        job = tasker.post_task(args.node, json.loads(args.override) if args.override else None)
        started = time.time()
        while not job.done and time.time() - started < TEST_NODE_TIMEOUT_S:
            time.sleep(0.5)
        if job.done:
            status_obj = job.status
            hit = bool(getattr(status_obj, "succeeded", False))
            status = getattr(getattr(status_obj, "_status", None), "name", None) or str(status_obj)
        else:
            tasker.post_stop().wait()
            hit = False
            status = "Timeout"
        img_after = ctrl.post_screencap().wait().get()
        after = evidence_dir / f"run{i}-after.png"
        Image.fromarray(img_after[..., ::-1]).save(after)

        reco_summary: list[dict[str, Any]] = []
        try:
            td = job.get()
            for node_info in getattr(td, "nodes", []) or []:
                nd = tasker.get_node_detail(node_info.node_id)
                if nd and nd.recognition and nd.recognition.filtered_results:
                    reco_summary = [result_to_dict(r) for r in nd.recognition.filtered_results]
                    break
        except Exception as exc:  # noqa: BLE001 — 证据采集失败不应中断连测
            reco_summary = [{"warning": f"recognition 证据采集失败: {exc}"}]
        hits += int(hit)
        runs.append({"run": i, "status": status, "hit": hit, "results": reco_summary,
                     "before": str(before), "after": str(after)})

    emit({
        "ok": True,
        "node": args.node,
        "n": n,
        "hits": hits,
        "pass": hits == n,
        "evidence_dir": str(evidence_dir),
        "runs": runs,
    })
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    spec_path = suite_dir / "suite.json"
    if not spec_path.exists():
        return fail(f"基准集定义不存在: {spec_path}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    _, _, tasker = bind(need_device=False)
    rows: list[dict[str, Any]] = []
    for case in spec.get("cases", []):
        image = suite_dir / case["image"]
        if not image.exists():
            rows.append({"image": case["image"], "node": "?", "hit": False, "reason": "截图缺失"})
            continue
        pipeline_file = case.get("pipeline")
        node_name = case["node"]
        node = _load_node(pipeline_file, node_name)
        if node is None:
            rows.append({"image": case["image"], "node": node_name, "hit": False, "reason": "节点未找到"})
            continue
        extracted = recognition_from_node(node)
        if extracted is None:
            rows.append({"image": case["image"], "node": node_name, "hit": False, "reason": "离线不可复现的识别类型"})
            continue
        rtype, param = extracted
        expect_hit = case.get("expect", "hit") == "hit"
        try:
            out = run_recognition_offline(tasker, rtype, param, image)
            actual_hit = bool(out["hit"])
            rows.append({
                "image": case["image"],
                "node": node_name,
                "expect": "hit" if expect_hit else "miss",
                "hit": actual_hit == expect_hit,
                "actual": "hit" if actual_hit else "miss",
                "results": out["results"],
            })
        except Exception as exc:  # noqa: BLE001 — 单条失败计入矩阵，不中断整批
            rows.append({"image": case["image"], "node": node_name, "expect": case.get("expect", "hit"),
                         "hit": False, "reason": f"{type(exc).__name__}: {exc}"})
    emit({"ok": True, "suite": str(suite_dir), **build_matrix(rows)})
    return 0


def _load_node(pipeline_file: str | None, node_name: str) -> dict[str, Any] | None:
    """从 pipeline 文件（相对 pipeline/ 目录或绝对路径）读节点定义。"""
    if pipeline_file:
        candidates = [Path(pipeline_file)]
        if not Path(pipeline_file).is_absolute():
            candidates = [PIPELINE_DIR / pipeline_file, Path(pipeline_file)]
    else:
        candidates = sorted(PIPELINE_DIR.glob("*.json"))
    for cand in candidates:
        if not cand.exists():
            continue
        data = json.loads(cand.read_text(encoding="utf-8"))
        if node_name in data:
            return data[node_name]
    return None


def cmd_journal(args: argparse.Namespace) -> int:
    event = json.loads(args.event)
    run_dir = AUTODEV_DIR / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    line = journal_line(event, args.run_id)
    with open(run_dir / "journal.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    emit({"ok": True, "journal": str(run_dir / "journal.jsonl"), "line": line})
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("snap", help="连设备截图（BGR→RGB 修正）落盘")
    p.add_argument("--out", default=None, help="输出路径（默认 debug/autodev/snaps/）")
    p.set_defaults(func=cmd_snap)

    p = sub.add_parser("ocr", help="对本地截图跑 MaaFW OCR")
    p.add_argument("image")
    p.add_argument("--roi", nargs=4, type=int, default=None, metavar=("X", "Y", "W", "H"), help="识别区域，默认全屏")
    p.set_defaults(func=cmd_ocr)

    p = sub.add_parser("som", help="生成 SoM 编号叠加图")
    p.add_argument("image")
    p.add_argument("--boxes", required=True, help="候选框，格式 x,y,w,h;x,y,w,h")
    p.add_argument("--labels", default=None, help="可选标签，分号分隔，与 boxes 等长")
    p.set_defaults(func=cmd_som)

    p = sub.add_parser("click", help="设备点击")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(func=cmd_click)

    p = sub.add_parser("swipe", help="设备滑动")
    p.add_argument("x1", type=int)
    p.add_argument("y1", type=int)
    p.add_argument("x2", type=int)
    p.add_argument("y2", type=int)
    p.add_argument("ms", type=int, nargs="?", default=500)
    p.set_defaults(func=cmd_swipe)

    p = sub.add_parser("crop", help="裁模板图 + 登记 manifest")
    p.add_argument("image")
    p.add_argument("--box", required=True, help="x,y,w,h")
    p.add_argument("--name", default=None, help="模板名（默认 crop-<ts>）")
    p.add_argument("--dest", default=None, help="输出目录（默认 assets/resource/base/image/autodev/）")
    p.add_argument("--note", default="", help="备注（来源页面等）")
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("reco", help="即时识别测试（离线）")
    p.add_argument("image")
    p.add_argument("--type", required=True, choices=sorted(RECO_LEAF_TYPES))
    p.add_argument("--param", default=None, help="识别参数 JSON（字段同 pipeline recognition.param）")
    p.set_defaults(func=cmd_reco)

    p = sub.add_parser("test-node", help="实机单节点连测 N 次")
    p.add_argument("node")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--override", default=None, help="运行时 pipeline_override JSON")
    p.set_defaults(func=cmd_test_node)

    p = sub.add_parser("replay", help="基准截图逐节点离线识别，输出命中矩阵")
    p.add_argument("--suite", required=True, help="基准集目录（含 suite.json）")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("journal", help="追加事件到 run journal")
    p.add_argument("event", help="事件 JSON")
    p.add_argument("--run-id", default="adhoc")
    p.set_defaults(func=cmd_journal)

    return parser


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
