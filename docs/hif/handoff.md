# HIF 开发工作交接（2026-06-29）

> 本文档为 feat/hif 分支当前进展与后续计划的交接记录，供新会话无缝接手。

## 一、当前状态（已核实）

- **工作目录**：`F:\code\MaaGakumasu`（fork 仓库）
- **分支**：`feat/hif`，工作区干净，本地与远程已同步
- **测试**：全套 **47 个全过**（0 失败）
- **远程**：`origin → haneball17/MaaGakumasu`，`upstream → SuperWaterGod/MaaGakumasu`

## 二、整体架构（融合后）

```
F:\code\MaaGakumasu\agent\hif\
├── decisions/          ← 出牌大脑（纯逻辑，零 maafw，已移植完成）
│   ├── state.py        #   ExamState/HandSummary/CardAction 数据结构
│   ├── config.py       #   ProfilePayload 角色配置（已瘦身去 pydantic）
│   ├── hand_meta.py    #   卡名→消耗查表
│   └── play.py         # ★ GarakutaRinamiStrategy 再演压缩流（7条分支）
├── adapters/           ← 适配层（YOLO+OCR→ExamState，已建完成）
│   ├── card_dict.py    #   OCR 卡名词典 + 好调卡判定
│   └── exam_reader.py  # ★ ExamStateReader（纯逻辑可单测 + maafw 适配器分离）
└── simulator.py        ← 日程决策模拟器（已有工作，BeamPlanner）

F:\code\Maa-gakumas-bot\（老仓库）→ 归档保留，出牌大脑已掏空移植过来
```

### 关键设计原则（务必遵守）

- `decisions/` 层**零 maafw 依赖**，只吃 dataclass 吐 `CardAction`
- `adapters/` 是**唯一**接触 maafw 的层，通过 `OcrPort` 协议抽象
  （实机用 `_MaafwOcrAdapter`，单测用 mock）
- 纯逻辑组装函数（`build_hand_summary`/`build_exam_state`）与 maafw 调用分离

## 三、已完成的工作（10 个 commit，全在 feat/hif）

| commit | 内容 | 阶段 |
|---|---|---|
| `4ae19f1` | 决策模拟器（1457行） | 收拢已有 |
| `8541c6b` | 13篇HIF设计文档+单测 | 收拢已有 |
| `635cb05` | master数据+生成流水线 | 收拢已有 |
| `f1fe330` | pipeline状态机+实机action | 收拢已有 |
| `d30d21a` | 集成进pipeline/lang/CI | 收拢已有 |
| `985d4f4` | **出牌决策大脑移植**（206行） | **Step 1** |
| `0dea8ca` | **22个出牌测试** | **Step 1** |
| `532fbf0` | **ExamStateReader适配层** | **Step 2** |
| `57b50a7` | **19个适配层测试** | **Step 2** |
| `c28c27d` | isort格式统一 | 清理 |

## 四、剩余工作计划

### Step 3：实机 ROI 校准（⚠️ 需 MuMu 真机）

适配层里 7 个数值字段的 ROI 坐标现在是**占位 `(0,0,0,0)`**
（代码已做安全处理：全 0 跳过 OCR），需要实机截图定位真实坐标。

**待校准的字段**（在 `exam_reader.py` 的 `_NUMERIC_ROI`）：

```python
_NUMERIC_ROI = {
    "good_condition": NumericROI("好调ターン数", (0,0,0,0)),  # ← 待校准
    "reprise":       NumericROI("再演次数",     (0,0,0,0)),  # ← 待校准
    "focus":         NumericROI("集中值",       (0,0,0,0)),  # ← 待校准
    "turn":          NumericROI("回合计数",     (0,0,0,0)),  # ← 待校准
    "flow":          NumericROI("当前流",        (0,0,0,0)),  # ← 待校准
    "deck_size":     NumericROI("山札张数",     (0,0,0,0)),  # ← 待校准
    "p_drinks":      NumericROI("持有Pドリンク",(0,0,0,0)),  # ← 待校准
}
```

**操作方式**：连 MuMu → 进 HIF 本戦出牌画面 → 截图 → 定位坐标
（可参考老仓库 `F:\code\Maa-gakumas-bot\backend\scripts\` 下的
`sample_from_video.py` / `_probe_template_match.py` 抽帧校准方法）。

### Step 4：写 ProduceCardsHIF action + 接 ProduceHIF.json（部分需真机）

**现状**：`ProduceHIF.json` 的 Round1/Round2 现在调用的是**通用**
`ProduceCardsFlag → ProduceCardsAuto`（用 YOLO 数卡数，无策略），
需要改成调用**新的** `ProduceHIFCardsFlag → ProduceCardsHIF`
（用我们的ガラクタロード策略）。

**需在 `agent/custom/action/produce_hif.py` 追加**：

```python
@AgentServer.custom_action("ProduceCardsHIF")
class ProduceCardsHIF(CustomAction):
    def run(self, context, argv):
        reader = ExamStateReader.from_context(context)
        state = reader.read_exam_state(round_, total_turns, stamina)
        action = GarakutaRinamiStrategy(ProfilePayload.default()).decide(state)
        # 翻译 action → 点击执行
```

**出牌动作的点击执行**（打出哪张卡怎么点）依赖实机 ROI 校准。

**建议先做 Step 4 的 action 骨架**（不依赖 ROI 的部分：出牌循环、决策调用、
接 pipeline），真机调试时只填坐标——这样无需真机也能推进大半。

### Step 5：实机验证 + 调优（需 MuMu 真机）

- 连真机跑 Round1/Round2 出牌循环
- OCR 误识变体补充（`card_dict.py` 的 `OCR_VARIANTS`，实机根据误识样本填）
- 打磨到稳定拿 S4

## 五、给新会话的接手指引

我在 `F:\code\MaaGakumasu`（fork 仓库）的 `feat/hif` 分支上做 HIF 出牌开发。

1. 出牌决策大脑（Step 1）+ 适配层 ExamStateReader（Step 2）已完成，47 测试全过。
2. 请先读 `agent/hif/decisions/play.py`（出牌大脑）和
   `agent/hif/adapters/exam_reader.py`（适配层）了解现状。
3. 下一步是 **Step 4：写 ProduceCardsHIF action 骨架**
   （`agent/custom/action/produce_hif.py` 追加出牌 CustomAction，调用
   ExamStateReader + GarakutaRinamiStrategy，接进 ProduceHIF.json），
   先写不依赖真机 ROI 的部分。
4. 关键约束：`decisions/` 层零 maafw 依赖；`adapters/` 是唯一接触 maafw 的层。
5. 数值字段 ROI 坐标（`_NUMERIC_ROI`）现在是占位，Step 3 实机校准。

**老仓库 `F:\code\Maa-gakumas-bot`**：出牌大脑已掏空移植，作为归档保留，不用管它。
