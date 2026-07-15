"""HIF 出牌 ROI 校准辅助工具。

先使用 MuMu 的原始 ``720x1280`` 截图确认字段位置，再以显式 ``--write``
更新版本化校准文件。默认只打印拟写入内容，不修改仓库资源。
"""

from __future__ import annotations

import json
import hashlib
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATION = ROOT / "assets" / "data" / "hif" / "roi_calibration.json"
FRAME_SIZE = (720, 1280)
EXAM_NUMERIC_FIELDS = ("good_condition", "reprise", "focus", "turn", "flow", "deck_size", "p_drinks", "stamina")
ROUND_METRIC_FIELDS = ("param_vo", "param_da", "param_vi", "current_score", "stage_multiplier")
SETTLEMENT_METRIC_FIELDS = ("leader_score_pair", "multiplier")
CALIBRATION_KINDS = {
    "exam_numeric": EXAM_NUMERIC_FIELDS,
    "round_metrics": ROUND_METRIC_FIELDS,
    "settlement_metrics": SETTLEMENT_METRIC_FIELDS,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校准 MaaGakumasu HIF 出牌数值 ROI")
    parser.add_argument("--image", type=Path, help="用于校验分辨率的 MuMu 原始截图")
    parser.add_argument("--kind", choices=tuple(CALIBRATION_KINDS), default="exam_numeric", help="ROI 所属读数类别")
    parser.add_argument("--field", help="要校准的字段；可选值随 --kind 变化")
    parser.add_argument("--roi", help="ROI，格式 x,y,width,height")
    parser.add_argument("--source", default="MuMu 12 实机截图", help="写入的校准来源说明")
    parser.add_argument("--device-id", help="稳定设备标识；执行级校准必须提供")
    parser.add_argument("--controller-kind", choices=("adb", "win32"), help="截图控制器类型")
    parser.add_argument("--game-version", help="截图对应游戏版本")
    parser.add_argument("--locale", help="截图语言，例如 ja-JP")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION, help="校准 JSON 路径")
    parser.add_argument("--write", action="store_true", help="确认写入；缺省时只打印拟写入结果")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_sha256 = ""
    if args.image:
        try:
            from PIL import Image
        except ImportError as error:
            raise SystemExit("读取截图需要 Pillow；请使用项目打包环境或安装 Pillow") from error

        with Image.open(args.image) as image:
            if image.size != FRAME_SIZE:
                raise SystemExit(f"截图尺寸错误：需要 {FRAME_SIZE[0]}x{FRAME_SIZE[1]}，实际为 {image.size[0]}x{image.size[1]}")
            print(f"截图尺寸已确认：{image.size[0]}x{image.size[1]}")
        image_sha256 = hashlib.sha256(args.image.read_bytes()).hexdigest()

    if not args.field and not args.roi:
        return 0
    if not args.field or not args.roi:
        raise SystemExit("更新 ROI 时必须同时提供 --field 与 --roi")
    if args.field not in CALIBRATION_KINDS[args.kind]:
        choices = ", ".join(CALIBRATION_KINDS[args.kind])
        raise SystemExit(f"--field {args.field!r} 不属于 {args.kind}；可选：{choices}")

    roi = parse_roi(args.roi)
    payload = json.loads(args.calibration.read_text(encoding="utf-8"))
    if payload.get("frame_size") != list(FRAME_SIZE):
        raise SystemExit("校准文件 frame_size 不匹配，拒绝写入")
    payload.setdefault(args.kind, {})[args.field] = list(roi)
    payload["source"] = args.source
    payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.device_id:
        payload["device_id"] = args.device_id
    if args.controller_kind:
        payload["controller_kind"] = args.controller_kind
    if args.game_version:
        payload["game_version"] = args.game_version
    if args.locale:
        payload["locale"] = args.locale
    if image_sha256:
        payload["evidence_sha256"] = image_sha256
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if not args.write:
        print("Dry run：以下为拟写入内容；确认后追加 --write。")
        print(rendered)
        return 0
    args.calibration.write_text(rendered, encoding="utf-8")
    print(f"已写入 {args.calibration}: {args.kind}.{args.field}={roi}")
    return 0


def parse_roi(raw: str) -> tuple[int, int, int, int]:
    try:
        x, y, width, height = (int(part.strip()) for part in raw.split(","))
    except ValueError as error:
        raise SystemExit("--roi 必须为 x,y,width,height 四个整数") from error
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > FRAME_SIZE[0] or y + height > FRAME_SIZE[1]:
        raise SystemExit(f"ROI 超出 {FRAME_SIZE[0]}x{FRAME_SIZE[1]} 范围：{raw}")
    return x, y, width, height


if __name__ == "__main__":
    raise SystemExit(main())
