# MaaFramework 外置 JSON 开发方法调研

本文整理 MaaFramework 的资源 JSON、任务配置 JSON 与 Custom 扩展的职责边界，供 HIF 流程开发使用。结论基于 MaaFramework 官方文档（调研日期：2026-07-18）。

## 一句话结论

JSON 管“固定流程”和“用户预设”，Custom 管“当前屏幕的实时观察与判断”，`CustomRecognition.detail` 是传递本次识别结果的原生信封。

不应把某一次截图读出的课程数值写回外置 JSON：它会在下一局过期，也不是 MaaFramework 用于传递运行时结果的通道。

## 三类 JSON 的通俗分工

| 类型 | 类比 | 适合放什么 | 不适合放什么 |
| --- | --- | --- | --- |
| `pipeline/**/*.json` | 流程单 | 识别页面、点击位置、下一步、异常停止 | 每局实时识别到的数值 |
| `interface.json`、任务 JSON | 设置页 | 下拉选项、开关、玩家偏好、`pipeline_override` | 现场截图结果 |
| `default_pipeline.json[c]` | 默认规则 | 后续节点共用的超时、阈值等默认值 | 业务流程分支 |

例如，HIF 的“看到 Day2 日程页 → 切换某个课程预览 → 读取数值 → 停止”属于 Pipeline；“玩家指定优先 Vo/Da/Vi”属于任务选项；“这次 Da 课程实际为 `Da +120、Vi +20、体力 -8`”属于运行时识别详情。

## Pipeline JSON 能做什么

Pipeline 是有限页面状态机。一个节点包含：

- `recognition`：当前画面是否是这个状态；可使用模板、OCR、颜色、YOLO、`And`、`Or`、`Custom`。
- `action`：命中后做什么；可点击、滑动、输入、启动/停止应用、`StopTask`、Shell、`Custom`。
- `next`：动作后允许进入的后续状态；按顺序尝试识别。
- `on_error`：未识别或动作失败时的安全分支。

常见的纯 JSON 流程如下：

```text
场景 A 被识别
  → 点击按钮 1
  → 识别场景 B
  → 继续下一步

场景 B 未出现或出现未知画面
  → on_error
  → StopTask
```

`[JumpBack]` 适合处理弹窗、加载页等临时页面：处理结束后回到父节点继续找原定下一步。对于页面和分支可枚举的流程，应优先用这种 JSON 状态机，不要在 Python 中手写一套流程调度器。

## 任务选项和 `pipeline_override`

任务 JSON 可以用 `select`、`input`、`checkbox` 等字段生成用户设置，再通过 `pipeline_override` 覆盖预先定义节点的字段。

适用例子：

```text
用户选择“优先 Da”
  → 覆盖预定义节点的 next、enabled 或 custom_action_param
  → 任务按这个预设运行
```

它适合把“用户已经知道且愿意承担后果的选择”注入流程。覆盖优先级由任务选项、控制器选项、资源选项和全局选项决定；应优先使用单任务覆盖，避免修改共享资源的全局状态。

不适用例子：把本局 OCR 得到的 `Da +120` 写进任务 JSON，再让后续节点读取。那会混淆配置和现场数据，并遗留过期状态。

## 运行时覆盖

当流程在运行中必须调整下一步或某个节点参数时，MaaFramework 提供覆盖 API：

- 资源级：`MaaResourceOverridePipeline`。
- 单任务级：`MaaTaskerPostTask`、`MaaTaskerOverridePipeline`。
- Custom 内：`MaaContextOverridePipeline`、`MaaContextOverrideNext`、`MaaContextRunRecognition`。

选择原则：

- 玩家启动任务前的偏好：任务选项的 `pipeline_override`。
- 某次任务里的临时分支：Custom 内的 Context 覆盖。
- 需要影响所有后续任务的资源修正：资源级覆盖；除非确有必要，不使用。

## Custom 与 `detail`

纯 JSON 已经能描述的固定识别和动作，不需要 Custom。出现以下情况时再使用 Custom：

- 一张画面要组合多次 OCR、模板或颜色识别，才能形成业务结果。
- 需要校验识别结果是否完整、唯一、安全。
- 后续路径取决于实时识别值，而不是固定节点顺序。

`CustomRecognition` 可以返回命中框和任意 JSON `detail`。它用于携带一次识别的结构化结果，例如：

```json
{
    "candidate": "Da",
    "stamina": -8,
    "star": 30,
    "vo": 0,
    "da": 120,
    "vi": 20,
    "verified": true
}
```

对 HIF，`HIFPublicLessonPreviewDetail` 应只负责读取已选中公开课的预览数值并返回这张“结果单”；它不负责决定选哪一课，也不确认上课。

注意：Custom Action 的 C API 只返回成功或失败，不能像 Custom Recognition 一样直接产出 action-detail JSON。因此，“读取结果”优先建模为 Custom Recognition；需要消费结果时，由 Custom 读取前序识别详情后调用 Context 覆盖下一步，或由任务调用方从识别回调中读取 `detail`。

## HIF Day2 的落地边界

当前 Day2 只做安全观察，测试管线采用：

```text
确认 Day2 日程页且三项均未选中
  → 切换 Vo 预览 → HIFPublicLessonPreviewDetail(Vo)
  → 切换 Da 预览 → HIFPublicLessonPreviewDetail(Da)
  → 切换 Vi 预览 → HIFPublicLessonPreviewDetail(Vi)
  → StopTask
```

这三次切换只用于显示预览，未点击最终确认，不应执行课程结算。任一识别失败、课程已预选中或画面未知时，立即停止。测试节点保持蛇形命名；正式 Pipeline 继续按项目既有 PascalCase 规范。

本期不接入：能力上限、试镜能力线、P-item 追加属性、后续收益估计和自动课程决策。这些都依赖更完整且经实机验证的输入，后续可作为独立决策模块消费 `detail`。

## 开发选择表

| 需求 | 首选实现 |
| --- | --- |
| 固定页面跳转、点按钮、等待下一页 | Pipeline JSON 的 `recognition + action + next` |
| 处理加载/弹窗后回原流程 | `[JumpBack]` |
| 玩家选择优先属性或开关 | 任务选项 + `pipeline_override` |
| 从复杂画面读出多项实时数据 | `CustomRecognition.detail` |
| 根据实时数据改本次后续节点 | Custom + Context 运行时覆盖 |
| 结果不完整、候选不唯一、页面未知 | `StopTask`，不猜测、不点击 |

## 官方资料

- [快速开始：Pure JSON / JSON + Custom / Full Code](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.1-%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md)
- [任务流水线协议](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md)
- [Project Interface V2 协议](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.3-ProjectInterfaceV2%E5%8D%8F%E8%AE%AE.md)
- [集成接口一览](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.2-%E9%9B%86%E6%88%90%E6%8E%A5%E5%8F%A3%E4%B8%80%E8%A7%88.md)
