---
name: pipeline-generate
description: "通过 Maa MCP 的 OCR 结果生成并合并 MaaFramework OCR Pipeline 节点；用于从连接设备上的目标文字取得 box、计算 ROI、扫 ROI 扩边并写入目标 pipeline 文件时使用。"
---

# Pipeline OCR 节点生成

只处理 OCR 文本节点。节点规范、动作选择和状态机设计见 [pipeline-guide](../pipeline-guide/SKILL.md)；真机验证见 [pipeline-testing](../pipeline-testing/SKILL.md)。

> **自动化路径**：无人化循环（截图→OCR 取 box→sweep→写入→连测）已固化为
> [pipeline-autodev](../pipeline-autodev/SKILL.md)，优先走它；本 skill 的手动流程保留为降级路径。

## 工具

本目录脚本：

- `generate_sweep.py`：生成多种 ROI 扩边的候选节点。
- `generate_node.py`：生成一个正式 OCR 节点并合并到目标 Pipeline。

依赖 `maa-mcp`：连接设备后调用 `ocr()` 取得 box；它已包含截图，不要额外截图。

## 最短流程

1. 确认设备位于目标页面，OCR 找到实际显示的目标文本。
2. 先运行 `generate_sweep.py`，用 `pipeline-testing` 选择稳定且最小的 ROI。
3. 用 `generate_node.py <text> <PascalCaseNode> <file> --expand <n>` 写入正式节点。
4. 运行 `load_pipeline` 或项目资源校验，并实机复测该节点。

## 约束

- 使用游戏实际文本作为 `expected`，不是翻译 key。
- ROI 在 720×1280（竖屏 720p）坐标系内裁剪；目标必须完整包含在 ROI 内。
- OCR 失败先缩小或 sweep ROI；ROI 不是越大越好。
- 节点已存在时默认不覆盖；仅在确认替换后传 `--overwrite`。
- 可滚动列表使用覆盖滚动区的统一 ROI，并由父级 Pipeline 状态机负责翻页；不要把翻页节点接到目标 Click 节点后造成循环。
- 跨文件流程用完整 resource bundle 集成测试，不能仅依赖单文件 `run_pipeline`。
