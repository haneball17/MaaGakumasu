"""为 HIF 每日日志中的 ROI 生成可审阅的红框标注图。

只读取原始截图和 Markdown 日志；所有产物写入 ``debug/hif-daily-review``，
不会修改原图、ROI 配置或 Pipeline。
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "docs" / "hif" / "finals-daily-log.md"
DEFAULT_OUTPUT = ROOT / "debug" / "hif-daily-review"
ROI_RE = re.compile(r"^\|\s*(?P<label>[^|]+?)\s*\|[^|]*\|\s*`?\[(?P<roi>\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+)\]`?\s*\|", re.M)
HEADING_RE = re.compile(r"^(?P<level>#{2,4}) (?P<title>.+)$", re.M)
IMAGE_REF_RE = re.compile(r"`(?P<path>[A-Z]:/[^`\r\n]+?\.(?:png|jpg|jpeg))`", re.I)


@dataclass(frozen=True)
class Roi:
    label: str
    box: tuple[int, int, int, int]


# 每个 ROI 小节对应的、日志中可用的最具代表性原图。未列出表示日志没有可用原图。
PROFILE_SOURCES = {
    "`セレクトチェンジ` 第一阶段：选择目标卡 A": "MuMu-20260709-152801-851.png",
    "`セレクトチェンジ` 第二阶段：牌库选择卡 B": "MuMu-20260709-153732-418.png",
    "`セレクトチェンジ` 完成提示": "MuMu-20260709-153808-881.png",
    "第二天初始候选界面": "MuMu-20260709-154635-975.png",
    "公开 lesson 预览界面": "MuMu-20260709-154737-108.png",
    "公开 lesson 结果界面": "MuMu-20260709-154848-105.png",
    "第三天初始候选界面": "MuMu-20260709-160445-070.png",
    "P 饮料领取界面": "MuMu-20260709-160930-688.png",
    "技能卡领取界面": "MuMu-20260709-161156-812.png",
    "P 饮料持有上限界面": "MuMu-20260709-161544-579.png",
    "P item 技能卡变换界面": "MuMu-20260709-165339-056.png",
    "第四天初始候选界面": "MuMu-20260709-185430-593.png",
    "Vi 授業选项界面": "MuMu-20260709-185642-055.png",
    "Vi 授業选项预览": "MuMu-20260709-185718-892.png",
    "第四天 `セレクトチェンジ` 目标卡选择界面": "MuMu-20260709-185907-242.png",
    "第四天牌库选择 B 界面": "MuMu-20260709-190040-538.png",
    "第四天变更成功提示": "MuMu-20260709-190058-531.png",
    "第五天初始候选界面": "MuMu-20260709-190618-555.png",
    "第五天 P 饮料持有上限界面": "MuMu-20260709-190835-595.png",
    "第六天初始候选界面": "MuMu-20260709-190958-930.png",
    "第六天 `相談` 商店界面": "MuMu-20260709-191555-058.png",
    "本战 Round1 / 初始状态": "MuMu-20260709-192016-091.png",
    "Interval 商店初始界面": "MuMu-20260709-193916-663.png",
    "持有技能卡检查界面": "MuMu-20260709-194353-848.png",
    "强化界面": "MuMu-20260709-194719-967.png",
    "特别指导 / カスタマイズ界面": "MuMu-20260709-194832-988.png",
    "特别指导选项执行界面": "MuMu-20260709-194923-497.png",
    "回复确认界面": "MuMu-20260709-195452-789.png",
    # 以下 7 项的 PotPlayer 原始图已缺失，报告会显式列为待补图。
    "分数结算界面": "学マス(2).mp4_20260709_221803.047.jpg",
    "Live 页面": "学マス(2).mp4_20260709_221454.162.jpg",
    "回忆照片选择界面": "学マス(2).mp4_20260709_221510.780.jpg",
    "回忆照片确认界面": "学マス(2).mp4_20260709_222415.756.jpg",
    "回忆生成界面": "学マス(2).mp4_20260709_221532.348.jpg",
    "回忆卡预览界面": "学マス(2).mp4_20260709_221617.383.jpg",
}


def parse_profiles(markdown: str) -> dict[str, list[Roi]]:
    headings = list(HEADING_RE.finditer(markdown))
    profiles: dict[str, list[Roi]] = {}
    for index, heading in enumerate(headings):
        title = heading.group("title")
        if title not in PROFILE_SOURCES:
            continue
        level = len(heading.group("level"))
        following = next((item for item in headings[index + 1 :] if len(item.group("level")) <= level), None)
        end = following.start() if following else len(markdown)
        rois = []
        for match in ROI_RE.finditer(markdown[heading.end() : end]):
            x, y, width, height = (int(value.strip()) for value in match.group("roi").split(","))
            rois.append(Roi(match.group("label").strip(" `"), (x, y, width, height)))
        profiles[title] = rois
    return profiles


def find_source(filename: str) -> Path | None:
    candidates = [
        Path("C:/Users/haneball/Documents/MuMu共享文件夹/Screenshots"),
        Path("D:/software/PotPlayer64/Capture"),
        ROOT / "assets" / "resource" / "test",
    ]
    for directory in candidates:
        if directory.exists():
            found = list(directory.rglob(filename))
            if found:
                return found[0]
    return None


def draw_rois(source: Path, destination: Path, title: str, rois: list[Roi]) -> None:
    with Image.open(source) as original:
        image = original.convert("RGB")
    if image.size != (720, 1280):
        raise ValueError(f"{source} 尺寸为 {image.size}，不是 720x1280")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for number, roi in enumerate(rois, start=1):
        x, y, width, height = roi.box
        draw.rectangle((x, y, x + width, y + height), outline="red", width=4)
        label = str(number)
        label_box = draw.textbbox((0, 0), label, font=font)
        label_width = label_box[2] - label_box[0] + 6
        label_height = label_box[3] - label_box[1] + 4
        label_y = max(0, y - label_height)
        draw.rectangle((x, label_y, x + label_width, label_y + label_height), fill="red")
        draw.text((x + 3, label_y + 2), label, fill="white", font=font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, "PNG")
    index = destination.with_suffix(".txt")
    index.write_text(
        f"页面：{title}\n原图：{source}\n\n"
        + "\n".join(f"{number}. {roi.label}: {list(roi.box)}" for number, roi in enumerate(rois, start=1))
        + "\n",
        encoding="utf-8",
    )


def write_contact_sheets(output: Path, images: list[Path]) -> None:
    """每页四张，供人工快速总览；原始标注图仍保留为单独文件。"""

    font = ImageFont.load_default()
    for page, start in enumerate(range(0, len(images), 4), start=1):
        sheet = Image.new("RGB", (720, 1280), "white")
        draw = ImageDraw.Draw(sheet)
        for index, source in enumerate(images[start : start + 4]):
            with Image.open(source) as image:
                thumbnail = image.convert("RGB").resize((360, 640))
            x = (index % 2) * 360
            y = (index // 2) * 640
            sheet.paste(thumbnail, (x, y))
            draw.rectangle((x, y, x + 160, y + 18), fill="white")
            draw.text((x + 3, y + 3), source.stem[:28], fill="black", font=font)
        sheet.save(output / f"contact-sheet-{page:02d}.png", "PNG")


def write_source_contact_sheets(output: Path, markdown: str) -> int:
    """输出日志中所有仍存在原图的总览页，供逐张人工审阅。"""

    sources: list[Path] = []
    seen: set[Path] = set()
    for match in IMAGE_REF_RE.finditer(markdown):
        source = find_source(Path(match.group("path")).name)
        if source is not None and source not in seen:
            sources.append(source)
            seen.add(source)
    font = ImageFont.load_default()
    for page, start in enumerate(range(0, len(sources), 4), start=1):
        sheet = Image.new("RGB", (720, 1280), "white")
        draw = ImageDraw.Draw(sheet)
        for index, source in enumerate(sources[start : start + 4]):
            with Image.open(source) as image:
                thumbnail = image.convert("RGB").resize((360, 640))
            x = (index % 2) * 360
            y = (index // 2) * 640
            sheet.paste(thumbnail, (x, y))
            draw.rectangle((x, y, x + 190, y + 18), fill="white")
            draw.text((x + 3, y + 3), source.stem[:32], fill="black", font=font)
        sheet.save(output / f"source-contact-sheet-{page:02d}.png", "PNG")
    return len(sources)


def main() -> int:
    parser = argparse.ArgumentParser(description="为 HIF 日程日志的 ROI 生成红框审阅图")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    markdown = args.log.read_text(encoding="utf-8")
    profiles = parse_profiles(markdown)
    report = ["# HIF 每日流程 ROI 审阅产物", "", "红框编号与 ROI 名称、坐标见同名 `.txt` 文件。", "", "| ROI 小节 | 原图 | 状态 | 标注图 |", "| --- | --- | --- | --- |"]
    generated = missing = empty = 0
    generated_images: list[Path] = []
    for order, (title, filename) in enumerate(PROFILE_SOURCES.items(), start=1):
        rois = profiles.get(title, [])
        if not rois:
            empty += 1
            report.append(f"| {title} | {filename} | 日志未解析到 ROI | — |")
            continue
        source = find_source(filename)
        if source is None:
            missing += 1
            report.append(f"| {title} | {filename} | 原图缺失，待补 | — |")
            continue
        destination = args.output / f"{order:02d}-{Path(filename).stem}.png"
        draw_rois(source, destination, title, rois)
        generated_images.append(destination)
        generated += 1
        report.append(f"| {title} | {source} | 已生成（{len(rois)} 个 ROI） | [{destination.name}]({destination.name}) |")
    report.extend(["", f"汇总：已生成 {generated} 张；原图缺失 {missing} 项；未解析 ROI {empty} 项。"])
    (args.output / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_contact_sheets(args.output, generated_images)
    source_count = write_source_contact_sheets(args.output, markdown)
    with (args.output / "README.md").open("a", encoding="utf-8") as handle:
        handle.write(f"日志中仍可读取的原图：{source_count} 张；总览页：`source-contact-sheet-*.png`。\n")
    print(f"generated={generated} missing={missing} empty={empty} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
