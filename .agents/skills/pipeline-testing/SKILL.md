---
name: pipeline-testing
description: "在真机或窗口上单步验证 MaaFramework Pipeline 节点的识别、动作和导航。用于 OCR/模板匹配调试、ROI 验证、节点点击后的安全返回、保存截图证据，以及新页面 UI 元素取证与深度遍历记录（snap→OCR→vision→安全试点→文档落盘）时使用。"
---

# Pipeline Testing

用 `run_pipeline` 验证单个节点；Pipeline 设计、识别字段和状态机规则见 [pipeline-guide](../pipeline-guide/SKILL.md)。

> **自动化路径**：单节点实机连测已封装为 `tools/maa_dev.py test-node <节点> --n 3`
> （自动前后截图 + 命中报告，证据落 debug/autodev/）；无人化整循环见
> [pipeline-autodev](../pipeline-autodev/SKILL.md)。本 skill 为手动降级路径。

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

## 新页面 UI 取证模板（深度遍历）

进入未见过的页面时按此流程取证并落盘（2026-08-20 HIF 结算链 7+ 页实测提炼）：

1. **snap + 全屏 OCR**：`maa_dev.py ocr <img>` 全量（node 单行提取 `box+text` 全列表）——先拿文字锚和按钮 box。
2. **小 ROI 精读**：数值区（表盘数字/体力/计数）用紧裁 ROI 单独读；小号数字宽 ROI 会因图形干扰掉分（实测 0.455→紧裁 0.999）。
3. **vision 布局记录**：派 vision 子代理描述区块/样式/图标时**传本地绝对路径**让它自己 Read——主会话 Read 上传的 CDN URL 有时效，子代理收到会 401。vision 的形状/语义描述只作辅助（38×35 图标曾把天鹅误述成「力量手势」），图标语义以用户指认或详情页実機原文为准。
4. **安全按钮试点**：按钮中心取 OCR 文字 box 中心（vision 给的按钮中心仅参考）；每次点击后用 OCR 锚验证变化——adb click `posted:true` ≠ 生效（偶发静默失效），无效先原坐标重试 1-2 次。危险区（扭蛋/购买/有償/提交类）只记录不点击。
5. **弹窗交互**记录齐全：打开条件、是否自动消失、关闭按钮坐标（实测弹窗 ✕ 常在底部下方非直觉位置，需裁图定位）。
6. **文档落盘**：`docs/<域>/<page>-ui-inventory.md`，表格式（元素/box/语义/识别方案/置信度）+ 页面流转图 + 交互实测记录；截图证据留 debug/ 不入库。
