# HIF Round1 Safe Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 HIF 在 MuMu `720x1280` 上按用户预设处理已观测的准备阶段页面，并在 Round1 初始页记录状态后安全停止。

**Architecture:** `finals-daily-log.md` 是页面与交互的唯一主流程依据；Pipeline 只负责按置信度路由页面和停止，Agent action 只执行预设已明确的单步选择。预设解析和候选排序放入零 MaaFramework 依赖的 `agent/hif/presets.py`，以便 pytest；`produce_hif.py` 只保留 Context、识别、点击和安全停止适配。

**Tech Stack:** Python 3.12、MaaFramework Pipeline / Agent Custom Action、YOLO `ProduceRecognitionCards`、OCR/TemplateMatch、pytest、maa-tools。

---

## File Structure

- Create: `agent/hif/presets.py`
  - HIF 预设 dataclass、JSON 参数解析和纯候选优先级函数。
- Modify: `agent/custom/action/produce_hif.py`
  - 以预设替换硬编码日程/首项回退；增加授業、奖励、变卡、咨询和 Round1 观察 action。
- Modify: `agent/custom/action/__init__.py`
  - 保持 HIF action 的 Agent 导入与导出声明一致。
- Modify: `assets/resource/base/pipeline/ProduceHIF.json`
  - 页面状态机、页面限定确认、Round1 观察停止与失败/未知安全停止。
- Modify: `assets/tasks/produce.json`, `assets/tasks/produce_cn.json`
  - 添加 HIF 预设选项，向 HIF custom action 注入相同 `custom_action_param`。
- Modify: `assets/lang/zh-CN.json`, `assets/lang/zh-Hant.json`
  - HIF 预设的中/繁体标签和安全行为说明。
- Modify: `tests/test_hif_decision.py`
  - 预设纯逻辑、Pipeline 图结构和 task override 的回归测试。
- Modify: `docs/superpowers/specs/2026-07-10-hif-basic-pipeline-design.md`
  - 明确 `finals-daily-log.md` 是主要流程来源，并列出页面证据映射。

### Task 1: 预设纯逻辑与流程证据追溯

**Files:**

- Create: `agent/hif/presets.py`
- Modify: `tests/test_hif_decision.py`
- Modify: `docs/superpowers/specs/2026-07-10-hif-basic-pipeline-design.md`

- [ ] **Step 1: 写失败的预设选择测试**

```python
from agent.hif.presets import choose_first_matching, parse_hif_preset


def test_hif_safe_preset_uses_observed_priority_and_never_falls_back_to_unknown():
    preset = parse_hif_preset('{"preset_id":"rinami_good_condition_safe"}')

    assert preset.schedule_priority == ("Da", "Vi", "Vo", "gift", "consult", "go_out")
    assert choose_first_matching(["Vo", "Da", "Vi"], preset.schedule_priority) == "Da"
    assert choose_first_matching(["unknown"], preset.schedule_priority) is None


def test_hif_preset_rejects_invalid_json_and_unknown_preset():
    assert parse_hif_preset("not-json").preset_id == "safe_default"
    assert parse_hif_preset('{"preset_id":"unknown"}').preset_id == "safe_default"
```

- [ ] **Step 2: 确认测试失败**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_hif_safe_preset_uses_observed_priority_and_never_falls_back_to_unknown -q
```

Expected: FAIL because `agent.hif.presets` does not exist.

- [ ] **Step 3: 实现预设模块**

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class HIFPreset:
    preset_id: str
    schedule_priority: tuple[str, ...]
    class_option_priority: tuple[str, ...]
    public_lesson_priority: tuple[str, ...]
    drink_name_priority: tuple[str, ...]
    skill_reward_names: tuple[str, ...]
    select_change_target_names: tuple[str, ...]
    select_change_source_names: tuple[str, ...]
    reroll_limit: int
    consult_policy: str
    round1_mode: str


SAFE_DEFAULT_PRESET = HIFPreset(
    preset_id="safe_default",
    schedule_priority=("Da", "Vi", "Vo", "gift", "consult", "go_out"),
    class_option_priority=("good_condition",),
    public_lesson_priority=("Da_sp", "Vi_sp", "Vo_sp"),
    drink_name_priority=("センブリソーダ",),
    skill_reward_names=("始まりの合図",),
    select_change_target_names=("始まりの合図",),
    select_change_source_names=("大胆不敵", "始まりの合図"),
    reroll_limit=2,
    consult_policy="finish_without_purchase",
    round1_mode="observe_and_stop",
)


RINAMI_GOOD_CONDITION_SAFE = HIFPreset(
    preset_id="rinami_good_condition_safe",
    **{field: getattr(SAFE_DEFAULT_PRESET, field) for field in SAFE_DEFAULT_PRESET.__dataclass_fields__ if field != "preset_id"},
)


_PRESETS = {preset.preset_id: preset for preset in (SAFE_DEFAULT_PRESET, RINAMI_GOOD_CONDITION_SAFE)}


def parse_hif_preset(raw: str | None) -> HIFPreset:
    try:
        payload: Any = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return SAFE_DEFAULT_PRESET
    preset_id = payload.get("preset_id") if isinstance(payload, dict) else None
    return _PRESETS.get(preset_id, SAFE_DEFAULT_PRESET)


def choose_first_matching(candidates: Iterable[str], priority: Iterable[str]) -> str | None:
    candidate_set = set(candidates)
    return next((name for name in priority if name in candidate_set), None)
```

同时在规格的“方案选择”前插入：`finals-daily-log.md` 是页面、候选、点击顺序和 ROI 的主流程依据；`hif-simulator-flow-design.md` 只描述后续建模边界。

- [ ] **Step 4: 运行预设测试**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_hif_safe_preset_uses_observed_priority_and_never_falls_back_to_unknown tests/test_hif_decision.py::test_hif_preset_rejects_invalid_json_and_unknown_preset -q
```

Expected: PASS.

### Task 2: Agent 预设动作和 Round1 观察停止

**Files:**

- Modify: `agent/custom/action/produce_hif.py`
- Modify: `agent/custom/action/__init__.py`
- Test: `tests/test_hif_decision.py`

- [ ] **Step 1: 写 HIF action 纯排序测试**

```python
from agent.hif.presets import RINAMI_GOOD_CONDITION_SAFE, choose_first_matching


def test_hif_observed_select_change_source_prefers_daitan_before_same_name_card():
    candidates = ["始まりの合図", "大胆不敵"]

    assert choose_first_matching(candidates, RINAMI_GOOD_CONDITION_SAFE.select_change_source_names) == "大胆不敵"
```

- [ ] **Step 2: 使 `produce_hif.py` 只通过预设决定候选**

在 `_ProduceHIFActionBase` 添加：

```python
    @staticmethod
    def _get_preset(argv: CustomAction.RunArg) -> HIFPreset:
        return parse_hif_preset(argv.custom_action_param)

    def _stop_unsupported(self, context: Context, screen_state: str, reason: str) -> bool:
        logger.warning(f"HIF 安全停止: screen_state={screen_state}, reason={reason}")
        context.run_task("ProduceHIFUnknownStop")
        return True
```

将 `_choose_best_event` 改为调用 `choose_first_matching`，并删除“第一个可用日程”回退。若不匹配，调用 `_stop_unsupported(context, "finals_action_select", "preset_no_matching_event")`。

新增以下 action，均先用 OCR/模板确认页面和目标候选，再点击；任何识别失败均调用 `_stop_unsupported`：

```python
@AgentServer.custom_action("ProduceChooseHIFClassOptionAuto")
class ProduceChooseHIFClassOptionAuto(_ProduceHIFActionBase):
    GOOD_CONDITION_OPTIONS = ("余裕です！", "長い道のりでした")

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        if "good_condition" not in self._get_preset(argv).class_option_priority:
            return self._stop_unsupported(context, "hif_class_options", "preset_no_class_option_policy")
        image = self._get_screenshot(context)
        for phrase in self.GOOD_CONDITION_OPTIONS:
            detail = self._run_ocr(context, image, "ProduceRecognitionHIFClassOption", [f".*{phrase}.*"], [40, 620, 640, 360])
            if detail and detail.hit:
                return self._click_box_center(context, detail.best_result.box, double=False)
        return self._stop_unsupported(context, "hif_class_options", "good_condition_option_not_found")
```

`ProduceChooseHIFDrinkRewardAuto` 仅选择 `preset.drink_name_priority` 中出现的饮料；`ProduceChooseHIFSkillRewardAuto` 最多按 `preset.reroll_limit` 点击 ROI `[540, 1030, 150, 90]` 中的 `再抽選`，命中 `preset.skill_reward_names` 后选择；`ProduceChooseHIFSelectChangeAuto` 分别在 target/source 页面选择 `preset.select_change_target_names` / `preset.select_change_source_names`，之后点击页面限定的 `次へ` / `チェンジ`；`ProduceHIFConsultAuto` 只在 `consult_policy == "finish_without_purchase"` 时点击 `終了`。

新增 Round1 观察 action：

```python
@AgentServer.custom_action("ProduceHIFRound1Observe")
class ProduceHIFRound1Observe(_ProduceHIFActionBase):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if preset.round1_mode != "observe_and_stop":
            return self._stop_unsupported(context, "round1_initial", "round1_mode_not_supported")
        reader = ExamStateReader.from_context(context)
        hand = reader.read_hand()
        logger.success(
            "HIF 已到达 Round1："
            f"good_condition_cards={hand.good_condition_card_count}, "
            f"shizen={hand.has_shizen_no_miryoku}, oneesan={hand.has_oneesan_no_kankaku}"
        )
        context.run_task("ProduceHIFRound1ReachedStop")
        return True
```

- [ ] **Step 3: 导出并验证纯逻辑测试**

在 `agent/custom/action/__init__.py` 的 `__all__` 添加全部 6 个新 action 名称。运行：

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_hif_observed_select_change_source_prefers_daitan_before_same_name_card -q
rtk proxy python -m py_compile agent/hif/presets.py agent/custom/action/produce_hif.py
```

Expected: PASS and exit code 0.

### Task 3: HIF Pipeline 页面状态机

**Files:**

- Modify: `assets/resource/base/pipeline/ProduceHIF.json`
- Modify: `tests/test_hif_decision.py`

- [ ] **Step 1: 写 Pipeline 图结构测试**

```python
def test_hif_pipeline_routes_round1_to_observe_stop_not_generic_card_action():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert payload["ProduceHIFRound1Flag"]["next"] == ["ProduceHIFRound1ObserveFlag"]
    assert payload["ProduceHIFRound1ObserveFlag"]["action"]["param"]["custom_action"] == "ProduceHIFRound1Observe"
    assert payload["ProduceHIFRound1ReachedStop"]["action"]["type"] == "StopTask"
    assert "ProduceCardsFlag" not in payload["ProduceHIFRound1Flag"]["next"]


def test_hif_pipeline_sends_unsupported_pages_to_safe_stop():
    payload = json.loads(Path("assets/resource/base/pipeline/ProduceHIF.json").read_text(encoding="utf-8"))

    assert payload["ProduceHIFDrinkOverflowFlag"]["next"] == ["ProduceHIFUnknownStop"]
    assert payload["ProduceHIFIntervalFlag"]["next"] == ["ProduceHIFUnknownStop"]
```

- [ ] **Step 2: 确认测试失败**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_hif_pipeline_routes_round1_to_observe_stop_not_generic_card_action tests/test_hif_decision.py::test_hif_pipeline_sends_unsupported_pages_to_safe_stop -q
```

Expected: FAIL because the current Round1 next target is `ProduceCardsFlag` and no unsupported-page flags exist.

- [ ] **Step 3: 定义页面限定节点**

修改 `ProduceEntryHIF.next`，将根路由排序固定为：失败/结束、Round1、Round2/Interval/饮料上限/结算等未覆盖页、已覆盖奖励页、授業选项、日程、P Item、通用页面限定确认、未知停止。新增的关键节点必须使用以下接口：

```json
"ProduceHIFRound1ObserveFlag": {
    "recognition": {"type": "DirectHit", "param": {}},
    "action": {
        "type": "Custom",
        "param": {"custom_action": "ProduceHIFRound1Observe"}
    },
    "next": ["ProduceHIFRound1ReachedStop"]
},
"ProduceHIFRound1ReachedStop": {
    "recognition": {"type": "DirectHit", "param": {}},
    "action": {"type": "StopTask", "param": {}},
    "focus": {
        "Node.Action.Succeeded": {
            "content": "✅ HIF 已安全到达 Round1，首版观察任务结束",
            "display": ["log", "notification"]
        }
    }
}
```

已覆盖的 `hif_class_options`、饮料奖励、技能奖励、变卡 target/source、咨询节点分别调用 Task 2 的 action；其 OCR 文案、ROI、按钮顺序严格采用 `docs/hif/finals-daily-log.md` 的 `720x1280` 记录。

`ProduceHIFDrinkOverflowFlag`、`ProduceHIFIntervalFlag`、`ProduceHIFRound2Flag`、`ProduceHIFScoreSettlementFlag` 和 `ProduceHIFMemoryFlag` 必须只识别、写 `focus`，并把 `next` 设为 `ProduceHIFUnknownStop`；它们不得接 `ProduceHIFButton`。

- [ ] **Step 4: 运行 Pipeline 测试和资源校验**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py::test_hif_pipeline_routes_round1_to_observe_stop_not_generic_card_action tests/test_hif_decision.py::test_hif_pipeline_sends_unsupported_pages_to_safe_stop -q
rtk proxy npx maa-tools check
```

Expected: pytest PASS; maa-tools does not report malformed nodes, missing custom actions, or invalid resources.

### Task 4: 用户预设、文案和完整回归

**Files:**

- Modify: `assets/tasks/produce.json`
- Modify: `assets/tasks/produce_cn.json`
- Modify: `assets/lang/zh-CN.json`
- Modify: `assets/lang/zh-Hant.json`
- Modify: `tests/test_hif_decision.py`

- [ ] **Step 1: 写 task override 回归测试**

```python
def test_hif_preset_option_injects_the_same_preset_into_round1_and_event_actions():
    task_payload = json.loads(Path("assets/tasks/produce.json").read_text(encoding="utf-8"))
    cases = task_payload["option"]["HIF预设"]["cases"]
    override = cases[1]["pipeline_override"]

    assert override["ProduceChooseHIFEventFlag"]["action"]["param"]["custom_action_param"]["preset_id"] == "rinami_good_condition_safe"
    assert override["ProduceHIFRound1ObserveFlag"]["action"]["param"]["custom_action_param"]["round1_mode"] == "observe_and_stop"
```

- [ ] **Step 2: 添加 HIF 预设选项**

在根任务 `option` 数组加入 `HIF预设`，在 `assets/tasks/produce.json` 与 `produce_cn.json` 创建两个 case：`安全默认` 与 `莉波好调（实验）`。后者向下列节点写同一个对象：

```json
{
    "preset_id": "rinami_good_condition_safe",
    "round1_mode": "observe_and_stop"
}
```

节点列表为 `ProduceChooseHIFEventFlag`、`ProduceHIFClassOptionFlag`、`ProduceHIFDrinkRewardFlag`、`ProduceHIFSkillRewardFlag`、`ProduceHIFSelectChangeTargetFlag`、`ProduceHIFSelectChangeSourceFlag`、`ProduceHIFConsultFlag`、`ProduceHIFRound1ObserveFlag`。补齐 `zh-CN` 与 `zh-Hant` 的标签、说明和“Round1 后安全停止”风险提示。

- [ ] **Step 3: 完整验证并进行 MuMu 观察模式验收**

Run:

```powershell
rtk proxy python -m pytest tests/test_hif_decision.py -q
rtk proxy python -m py_compile agent/hif/presets.py agent/custom/action/produce_hif.py
rtk proxy npx prettier --check "assets/tasks/produce.json" "assets/tasks/produce_cn.json" "assets/resource/base/pipeline/ProduceHIF.json"
rtk proxy npx maa-tools check
rtk proxy python -m pytest -q
```

实机按 MuMu `720x1280` 启动 HIF 的“莉波好调（实验）”预设。验收日志必须显示日程/选项动作及 `✅ HIF 已安全到达 Round1，首版观察任务结束`；若出现未覆盖页面，日志必须先显示 `HIF 安全停止`，且设备截图证明停止前没有后续点击。

### Self-Review

- 规格中的首版范围全部映射到 Task 1–4；Interval、Round2、结算和 Memory 只作为安全停止页，不伪装为已支持功能。
- `finals-daily-log.md` 是页面 ROI、文本和交互的主要依据；外部 MaaFramework 文档只约束 Pipeline/Agent 的实现机制。
- `HIFPreset`、`parse_hif_preset`、`choose_first_matching`、`ProduceHIFRound1Observe` 和 `ProduceHIFRound1ReachedStop` 在测试、实现和 Pipeline 中使用同名接口。
- 不修改 `README.md`、模拟器算法和通用培育的出牌逻辑。
