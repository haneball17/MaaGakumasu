"""HIF 实机运行时的设备与截图契约。

HIF 页面模板、ROI 与点击坐标均来自 MuMu 的竖屏 ``720x1280`` 截图。
本模块保持与 MaaFramework 解耦，便于在接入真实控制器前测试截图对象的尺寸解析。
"""

from __future__ import annotations

from typing import Any
from dataclasses import dataclass

HIF_FRAME_SIZE = (720, 1280)


@dataclass(frozen=True, slots=True)
class HIFFrameTransform:
    """将控制器原始截图映射到 HIF 标准坐标的显式裁剪契约。

    正式 Pipeline 仍只接受 :data:`HIF_FRAME_SIZE`。本对象只为控制器诊断、
    离线回放和专用运行器提供可审计的转换信息，避免把 MuMu 外框偏移散落到
    ROI 或点击代码中。
    """

    source_size: tuple[int, int]
    crop: tuple[int, int, int, int]
    target_size: tuple[int, int] = HIF_FRAME_SIZE

    @property
    def valid(self) -> bool:
        source_width, source_height = self.source_size
        x, y, width, height = self.crop
        return (
            self.target_size == (width, height)
            and x >= 0
            and y >= 0
            and width > 0
            and height > 0
            and x + width <= source_width
            and y + height <= source_height
        )

    def to_source_point(self, x: int, y: int) -> tuple[int, int] | None:
        """把标准 HIF 点击坐标映射到控制器原始坐标。"""

        if not self.valid or not _point_in_size(x, y, self.target_size):
            return None
        crop_x, crop_y, _, _ = self.crop
        return crop_x + x, crop_y + y

    def to_source_roi(self, roi: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
        """把标准 HIF ROI 映射到控制器原始截图，越界时拒绝猜测。"""

        if not self.valid or not _roi_in_size(roi, self.target_size):
            return None
        crop_x, crop_y, _, _ = self.crop
        x, y, width, height = roi
        return crop_x + x, crop_y + y, width, height


@dataclass(frozen=True, slots=True)
class HIFFrameValidation:
    """一次截图尺寸校验的结果。"""

    ok: bool
    width: int | None
    height: int | None
    reason: str = ""


def get_image_size(image: Any) -> tuple[int, int] | None:
    """尽可能从 Pillow、ndarray 或 MaaFramework 图片对象取出 ``(width, height)``。

    不同 MaaFramework Python 绑定版本返回的截图对象不同。这里仅做无副作用的
    属性读取，识别不到尺寸时交给调用方安全停止，绝不猜测坐标系。
    """

    if image is None:
        return None

    size = getattr(image, "size", None)
    if isinstance(size, (tuple, list)) and len(size) >= 2:
        parsed = _positive_pair(size[0], size[1])
        if parsed:
            return parsed

    shape = getattr(image, "shape", None)
    if isinstance(shape, (tuple, list)) and len(shape) >= 2:
        # ndarray/OpenCV 的 shape 顺序为 height, width[, channels]。
        parsed = _positive_pair(shape[1], shape[0])
        if parsed:
            return parsed

    width = _read_dimension(image, "width")
    height = _read_dimension(image, "height")
    parsed = _positive_pair(width, height)
    if parsed:
        return parsed

    # OpenCV 风格对象有时使用 cols/rows。
    parsed = _positive_pair(_read_dimension(image, "cols"), _read_dimension(image, "rows"))
    if parsed:
        return parsed

    get_size = getattr(image, "get_size", None)
    if callable(get_size):
        try:
            result = get_size()
        except (AttributeError, TypeError, ValueError):
            result = None
        if isinstance(result, (tuple, list)) and len(result) >= 2:
            return _positive_pair(result[0], result[1])

    return None


def validate_hif_frame(image: Any, expected_size: tuple[int, int] = HIF_FRAME_SIZE) -> HIFFrameValidation:
    """验证 HIF 模板和点击坐标可安全使用。"""

    actual = get_image_size(image)
    if actual is None:
        return HIFFrameValidation(False, None, None, "无法从控制器截图读取尺寸")

    width, height = actual
    expected_width, expected_height = expected_size
    if actual == expected_size:
        return HIFFrameValidation(True, width, height)
    if actual == (expected_height, expected_width):
        return HIFFrameValidation(
            False,
            width,
            height,
            f"截图方向错误：HIF 需要竖屏 {expected_width}x{expected_height}，当前为 {width}x{height}",
        )
    return HIFFrameValidation(
        False,
        width,
        height,
        f"截图尺寸不匹配：HIF 需要 {expected_width}x{expected_height}，当前为 {width}x{height}",
    )


def propose_hif_frame_transforms(image: Any, expected_size: tuple[int, int] = HIF_FRAME_SIZE) -> tuple[HIFFrameTransform, ...]:
    """枚举包含额外窗口边框时可人工确认的无缩放裁剪候选。

    顶栏和底栏仅从尺寸无法区分，因此绝不假定居中裁剪。调用方应使用页面
    模板或原始截图确认候选，再把唯一结果写入设备专用配置。
    """

    size = get_image_size(image)
    if size is None:
        return ()
    source_width, source_height = size
    target_width, target_height = expected_size
    if source_width != target_width or source_height < target_height:
        return ()
    extra_height = source_height - target_height
    if extra_height < 0:
        return ()
    if extra_height == 0:
        transform = HIFFrameTransform(size, (0, 0, target_width, target_height), expected_size)
        return (transform,) if transform.valid else ()
    candidates = (
        HIFFrameTransform(size, (0, 0, target_width, target_height), expected_size),
        HIFFrameTransform(size, (0, extra_height, target_width, target_height), expected_size),
    )
    return tuple(candidate for candidate in candidates if candidate.valid)


def _read_dimension(image: Any, name: str) -> Any:
    value = getattr(image, name, None)
    if callable(value):
        try:
            return value()
        except (AttributeError, TypeError, ValueError):
            return None
    return value


def _positive_pair(width: Any, height: Any) -> tuple[int, int] | None:
    if isinstance(width, bool) or isinstance(height, bool):
        return None
    try:
        parsed_width = int(width)
        parsed_height = int(height)
    except (TypeError, ValueError):
        return None
    if parsed_width <= 0 or parsed_height <= 0:
        return None
    return parsed_width, parsed_height


def _point_in_size(x: int, y: int, size: tuple[int, int]) -> bool:
    width, height = size
    return 0 <= x < width and 0 <= y < height


def _roi_in_size(roi: tuple[int, int, int, int], size: tuple[int, int]) -> bool:
    x, y, width, height = roi
    frame_width, frame_height = size
    return x >= 0 and y >= 0 and width > 0 and height > 0 and x + width <= frame_width and y + height <= frame_height
