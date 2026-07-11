"""只读诊断 MaaFramework 控制器与 HIF 截图契约。"""

from __future__ import annotations

import sys
import json
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from maa.define import MaaWin32ScreencapMethodEnum
from maa.toolkit import Toolkit
from maa.controller import AdbController, Win32Controller

from agent.hif.runtime import get_image_size, propose_hif_frame_transforms, validate_hif_frame
from agent.hif.image_io import save_hif_image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="枚举或只读探测 HIF 控制器；不会发送点击、滑动或键盘输入")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--adb", help="要探测的 ADB 地址，例如 127.0.0.1:16384")
    group.add_argument("--hwnd", type=int, help="要探测的 Win32 窗口句柄")
    parser.add_argument("--adb-path", type=Path, help="ADB 可执行文件绝对路径；系统 PATH 未配置 adb 时必填")
    parser.add_argument("--save", type=Path, help="显式保存本次只读截图；用于后续 ROI 校准")
    parser.add_argument(
        "--win32-method",
        choices=("all", "dxgi", "gdi", "framepool", "printwindow", "screendc"),
        default="all",
        help="Win32 截图方式；默认让 MaaFramework 依次选择可用实现",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.adb:
        adb_path = resolve_adb_path(args.adb_path)
        if adb_path is None:
            print(
                json.dumps(
                    {
                        "controller": "adb",
                        "connected": False,
                        "reason": "adb_executable_not_found",
                        "hint": "使用 --adb-path 指向 MuMu 自带 adb.exe，或将 adb 加入 PATH",
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        controller = AdbController(adb_path=str(adb_path), address=args.adb)
        controller_kind = "adb"
    elif args.hwnd is not None:
        method = {
            "all": MaaWin32ScreencapMethodEnum.All,
            "dxgi": MaaWin32ScreencapMethodEnum.DXGI_DesktopDup,
            "gdi": MaaWin32ScreencapMethodEnum.GDI,
            "framepool": MaaWin32ScreencapMethodEnum.FramePool,
            "printwindow": MaaWin32ScreencapMethodEnum.PrintWindow,
            "screendc": MaaWin32ScreencapMethodEnum.ScreenDC,
        }[args.win32_method]
        controller = Win32Controller(hWnd=args.hwnd, screencap_method=method)
        controller_kind = "win32"
    else:
        print(json.dumps(list_candidates(), ensure_ascii=False, indent=2))
        return 0

    connection = controller.post_connection()
    if connection.failed:
        print(json.dumps({"controller": controller_kind, "connected": False}, ensure_ascii=False))
        return 2
    try:
        image = controller.post_screencap().wait().get()
    except Exception as error:
        print(
            json.dumps(
                {
                    "controller": controller_kind,
                    "connected": True,
                    "screencap": False,
                    "error": str(error),
                },
                ensure_ascii=False,
            )
        )
        return 4
    validation = validate_hif_frame(image)
    proposed_transforms = propose_hif_frame_transforms(image)
    save_error = ""
    if args.save:
        try:
            save_screenshot(image, args.save)
        except (AttributeError, ImportError, OSError, TypeError, ValueError) as error:
            save_error = str(error)
    print(
        json.dumps(
            {
                "controller": controller_kind,
                "connected": True,
                "image_size": get_image_size(image),
                "hif_frame_valid": validation.ok,
                "reason": validation.reason,
                "suggested_transforms": [
                    {
                        "source_size": list(transform.source_size),
                        "crop": list(transform.crop),
                        "target_size": list(transform.target_size),
                        "production_ready": False,
                    }
                    for transform in proposed_transforms
                ],
                "saved_to": str(args.save) if args.save and not save_error else None,
                "save_error": save_error or None,
            },
            ensure_ascii=False,
        )
    )
    return 0 if validation.ok else 3


def list_candidates() -> dict[str, list[dict[str, object]]]:
    return {
        "adb": [
            {"address": device.address, "name": device.name, "adb_path": device.adb_path}
            for device in Toolkit.find_adb_devices()
        ],
        "windows": [
            {"hwnd": window.hwnd, "class_name": window.class_name, "window_name": window.window_name}
            for window in Toolkit.find_desktop_windows()
        ],
    }


def resolve_adb_path(explicit: Path | None) -> Path | None:
    """解析可执行 ADB 路径，绝不把不存在的字符串交给 MaaFramework。"""

    if explicit is not None:
        return explicit if explicit.is_file() else None
    from_path = shutil.which("adb")
    return Path(from_path) if from_path else None


def save_screenshot(image, path: Path) -> None:
    """将控制器截图保存为 PNG；仅由显式 ``--save`` 调用。"""

    save_hif_image(image, path)


if __name__ == "__main__":
    raise SystemExit(main())
