---
name: pipeline-testing
description: "在真机或窗口上单步验证 MaaFramework Pipeline 节点的识别、动作和导航。用于 OCR/模板匹配调试、ROI 验证、节点点击后的安全返回，以及保存截图证据时使用。"
---

# Pipeline Testing

用 `run_pipeline` 验证单个节点；Pipeline 设计、识别字段和状态机规则见 [pipeline-guide](../pipeline-guide/SKILL.md)。

## 流程

1. 连接 ADB 或窗口控制器，加载目标 Pipeline。
2. 从已知页面开始，逐个运行节点。
3. 判断结果：`succeeded` 且 `recognition.all_results` 非空才算识别成功。
4. Click 节点测试后，使用项目的可靠返回节点（通常是 `BackButton_500ms`）恢复页面；先确认它实际返回的页面。
5. 失败、低分或页面异常时，先保存截图并调用 `ocr()` 观察实际画面，再改 `expected` 或 ROI。

## OCR ROI sweep

OCR 失败时先扫 ROI，不要直接改用 TemplateMatch：

1. 使用 `pipeline-generate/generate_sweep.py` 生成候选节点。
2. `expected` 使用游戏实际显示的文本。
3. 逐个测试，选择稳定命中且不覆盖相邻元素的最小 ROI。
4. 用 `generate_node.py` 写回正式节点，再重新测试。

OCR 有非确定性；单次结果不足以定论。可滚动列表按视图测试，统一的大 ROI 必须覆盖滚动区。

## 安全

- 不测试购买、升级、供奉、开战或其他资源消耗确认按钮。
- Click 后不要假设仍在原页面；每次返回或切换后重新确认页面。
- `run_pipeline` 长时间无返回时停止并查看截图，不盲目扩大 ROI 或重复点击。

## 记录

记录设备、初始页面、节点、结果、分数、截图路径与失败原因。跨文件 `next` 引用需要通过完整 resource bundle 的 GUI/CLI 集成测试；单文件 `run_pipeline` 仅用于无跨文件依赖的节点。
