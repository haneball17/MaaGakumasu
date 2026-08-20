"""maa_dev 原子工具纯函数单测（pipeline-autodev 工作流）。

覆盖：clip_roi 扩边裁剪、draw_som 编号叠加、journal 行构造、replay 命中矩阵、
pipeline 节点 → 离线识别参数的映射。全部离线，不依赖 MaaFrame 运行时与设备。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from PIL import Image

from tools.maa_dev import (
    clip_roi,
    draw_som,
    build_matrix,
    journal_line,
    result_to_dict,
    param_to_dataclass,
    recognition_from_node,
    resolve_template_path,
)


def test_clip_roi_expand_and_clamp() -> None:
    # 常规扩边
    assert clip_roi([100, 200, 50, 30], 20, 720, 1280) == [80, 180, 90, 70]
    # 左上角起点裁剪到屏幕内（宽度不因 clamp 缩减，与 generate_node compute_roi 语义一致）
    assert clip_roi([5, 5, 50, 30], 20, 720, 1280) == [0, 0, 90, 70]
    # 右下角不越界
    assert clip_roi([700, 1260, 15, 15], 20, 720, 1280) == [680, 1240, 40, 40]


def test_clip_roi_invalid_fallback() -> None:
    # 扩边后宽非法（x 超出屏幕）回退原始 box
    assert clip_roi([730, 100, 50, 30], 0, 720, 1280) == [730, 100, 50, 30]


def test_draw_som_mapping_and_canvas() -> None:
    img = Image.new("RGB", (720, 1280), (30, 30, 30))
    boxes = [[10, 20, 100, 40], [300, 400, 80, 60]]
    canvas, mapping = draw_som(img, boxes, labels=["次へ", "キャンセル"])
    assert canvas.size == img.size
    assert [m["index"] for m in mapping] == [0, 1]
    assert mapping[0]["box"] == boxes[0]
    assert mapping[0]["label"] == "次へ"
    # 叠加图与原图不同（画了框）
    assert canvas.tobytes() != img.tobytes()


def test_journal_line_fields() -> None:
    line = journal_line({"event": "node_test", "node": "A", "hit": True}, "run-1", now="2026-08-20T10:00:00")
    assert line["ts"] == "2026-08-20T10:00:00"
    assert line["run_id"] == "run-1"
    assert line["event"] == "node_test"
    assert line["hit"] is True


def test_build_matrix_pass_and_fail() -> None:
    rows: list[dict[str, Any]] = [
        {"image": "a.png", "node": "N1", "hit": True},
        {"image": "b.png", "node": "N1", "hit": False, "reason": "未命中"},
    ]
    matrix = build_matrix(rows)
    assert matrix["total"] == 2
    assert matrix["hits"] == 1
    assert matrix["misses"] == 1
    assert matrix["pass"] is False


def test_recognition_from_node_v2_and_v1() -> None:
    node_v2 = {"recognition": {"type": "OCR", "param": {"expected": ["次へ"], "roi": [0, 1200, 720, 80]}}}
    assert recognition_from_node(node_v2) == ("OCR", {"expected": ["次へ"], "roi": [0, 1200, 720, 80]})
    node_v1 = {"recognition": "OCR", "roi": [0, 0, 720, 100]}
    assert recognition_from_node(node_v1) == ("OCR", {"roi": [0, 0, 720, 100]})


def test_recognition_from_node_unsupported() -> None:
    # Custom / And / Or / DirectHit 离线不可复现 → None
    assert recognition_from_node({"recognition": {"type": "Custom", "param": {}}}) is None
    assert recognition_from_node({"recognition": {"type": "DirectHit", "param": {}}}) is None
    assert recognition_from_node({}) is None


def test_param_to_dataclass_roi_default_fullscreen() -> None:
    param = param_to_dataclass("OCR", {}, (720, 1280))
    assert list(param.roi) == [0, 0, 720, 1280]
    # 显式 roi 保留
    param2 = param_to_dataclass("OCR", {"roi": [10, 20, 30, 40]}, (720, 1280))
    assert list(param2.roi) == [10, 20, 30, 40]


def test_param_to_dataclass_ignores_unknown_fields() -> None:
    # pipeline 侧字段（如 expected 正则列表）超出 dataclass 字段时不应抛错
    param = param_to_dataclass("TemplateMatch", {"template": ["back.png"], "nonexistent": 1}, (720, 1280))
    # back.png 在 resource image 目录存在 → 解析为绝对路径
    assert len(param.template) == 1
    from pathlib import Path

    assert Path(param.template[0]).is_absolute()
    assert Path(param.template[0]).name == "back.png"


def test_resolve_template_path_missing_returns_original() -> None:
    assert resolve_template_path("definitely/not/exist.png").endswith("definitely/not/exist.png")
    # 绝对路径存在时原样返回
    from tools.maa_dev import IMAGE_DIR

    existing = next(IMAGE_DIR.glob("*.png"))
    assert resolve_template_path(str(existing)) == str(existing)


def test_result_to_dict_defensive() -> None:
    r = SimpleNamespace(box=[1, 2, 3, 4], text="次へ", score=0.98765)
    d = result_to_dict(r)
    assert d == {"box": [1, 2, 3, 4], "text": "次へ", "score": 0.9877}
    # 缺 text/score 的对象（如模板匹配结果）不抛错
    d2 = result_to_dict(SimpleNamespace(box=[0, 0, 10, 10]))
    assert d2["box"] == [0, 0, 10, 10]
    assert "text" not in d2
    assert d2["score"] is None
