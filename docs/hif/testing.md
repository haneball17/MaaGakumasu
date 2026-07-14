# HIF 自动化测试说明

本文描述当前 `rinami_garakuta_road` HIF 路线的离线测试边界。HIF 仍处于开发与验证阶段，测试通过不代表已经完成完整连续培育或新的实机闭环。

## 覆盖矩阵

`assets/data/hif/pipeline_coverage.json` 是当前 HIF Pipeline 的机器可检查覆盖矩阵。它要求 `ProduceHIF.json` 的每个节点恰好登记一次，并为每组节点声明：

- 节点类别与实机证据等级；
- 成功、拒绝/安全停止、动作后验失败三类场景，或不适用理由；
- 终止策略与对应测试模块。

`python tools/hif_pipeline_check.py` 会同时检查节点/Custom 注册、跳转引用、覆盖矩阵、OCR 正则、ROI 边界和 TemplateMatch 文件引用。新增或删除 HIF 节点后，必须同步更新矩阵，否则检查失败。

## 真实帧夹具

`tests/fixtures/hif/frames/` 只保存经过审阅的最小 `720x1280` 帧集。每项的来源、采集日期、SHA-256、页面、ROI 和适配器预期均记录在覆盖矩阵的 `fixtures` 中；测试会拒绝内容被替换但清单未更新的夹具。

这些帧含游戏内偶像、卡片、饮料和本局数值等状态数据，但不含账号标识或凭据；仅用于离线尺寸、ROI 和 OCR 适配器文本回放。它们不执行 Maa OCR，也不连接控制器，因此不得表述为 OCR 或点击的端到端实机验证。

禁止将 `debug/`、Journal、日志、视频、压缩包或损坏截图作为测试夹具提交。

## 安全后验

需要点击的 HIF Action 不得只凭“帧发生变化”判定成功。当前测试覆盖以下安全约束：

- 空白推进、日程一/二次确认、公开课结算、饮料展示和开始培育必须命中已知下一页或已注册的过渡识别；未知帧立即进入 `ProduceHIFUnknownStop`。
- 饮料满仓恢复必须带显式 `single_step` 权限。
- 变卡源卡确认必须持有同一运行期记录的目标卡；不能从 Action 参数重建丢失状态。
- 奖励页 Custom Recognition 的 `box` 与 `detail` 在命中、无框命中和未命中时均有离线契约测试。
- Round 单步出牌尚无“手牌/回合/数值确实更新”的实机后验，因此审批器固定声明 `postcondition_supported=false`，即使 ROI 与候选完整也不得点击。
- Live 快进尚无目标页后验，`skip_once` 只记录并安全停止；不得把动画帧变化当作快进成功。
- 回忆照片、生成、预览和结算按钮必须依次命中声明的下一页面；变化后的未知帧进入 `ProduceHIFUnknownStop`。

未获得实机证据的页面、其他路线、Round 自动出牌和连续模式保持安全停止。

## 本地检查

```powershell
python -m pytest -q tests -k hif
python tools/hif_pipeline_check.py
python -m py_compile agent/hif/*.py agent/hif/adapters/*.py agent/custom/action/produce_hif.py tools/hif_*.py
python -m ruff check agent/custom/action/produce_hif.py agent/hif tests/test_hif_*.py tools/hif_pipeline_check.py
npx prettier --check "assets/data/hif/pipeline_coverage.json"
```

全仓验证仍应在交付前执行 `python -m pytest`。若存在与 HIF 无关的既有失败，必须保留输出证据，不要借机扩大修复范围。
