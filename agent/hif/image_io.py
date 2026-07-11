"""HIF 截图证据的轻量 PNG 写入器，不依赖 Pillow/OpenCV。"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any


def save_hif_image(image: Any, path: str | Path) -> None:
    """保存 Pillow 风格图片或 uint8 ndarray 为 PNG。"""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    save = getattr(image, "save", None)
    if callable(save):
        save(destination)
        return

    shape = getattr(image, "shape", None)
    dtype = getattr(image, "dtype", None)
    if not isinstance(shape, tuple) or len(shape) not in (2, 3) or str(dtype) != "uint8":
        raise TypeError(f"不支持保存截图类型: {type(image).__name__}")
    height, width = int(shape[0]), int(shape[1])
    channels = int(shape[2]) if len(shape) == 3 else 1
    if width <= 0 or height <= 0 or channels not in (1, 3, 4):
        raise ValueError(f"不支持截图形状: {shape}")

    if channels == 1:
        color_type = 0
        data = image
    elif channels == 3:
        color_type = 2
        # Maa/OpenCV 常见返回 BGR；显式转换为 PNG 规定的 RGB。
        data = image[:, :, [2, 1, 0]]
    else:
        color_type = 6
        # Maa/OpenCV 常见返回 BGRA；显式转换为 RGBA。
        data = image[:, :, [2, 1, 0, 3]]
    rows = b"".join(b"\x00" + data[row].tobytes() for row in range(height))
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(rows)) + _png_chunk(b"IEND", b"")
    destination.write_bytes(png)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
