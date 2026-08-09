---
name: pipeline-option
description: "为 MaaFramework interface.json 添加可持久化的 select、switch、checkbox 或 input 运行时选项。用于将 UI 选项注册到任务，并以 pipeline_override 或 Python CustomAction 读取其运行时配置时使用。"
---

# Pipeline Option

Pipeline 节点和跨页面状态机规则见 [pipeline-guide](../pipeline-guide/SKILL.md)。优先复用现有选项模式，保持默认值与旧行为一致。

## 先选实现方式

| 需求 | 方式 |
| --- | --- |
| 只改变现有节点的 `next`、`expected`、`action`、`roi` 等字段 | pure `pipeline_override` |
| Python 业务逻辑需要条件分支 | 预定义 Flag 节点 + `context.get_node_data()` |
| 多个互斥值 | `select` 覆盖 OCR 节点的 `expected` |
| 自由文本 | `input` 注入 `custom_action_param` |
| 多个独立开关 | `checkbox` 覆盖多个预定义 Flag 的 `enabled` |

能 pure override 就不加 Flag 或 Python 代码。

## 必做检查

每个选项同时完成：

1. 在 `assets/interface.json` 的 `option` 中定义 type、默认 case 和 cases。
2. 在目标 task 的 `option` 数组注册它。
3. 对所有 override 目标，先在 Pipeline JSON 中定义节点；`pipeline_override` 只合并字段，不创建节点。
4. 只有 Python 分支需要时才读取节点数据，并在对应业务函数入口读取。
5. 为 task `doc` 添加用户可读说明。

`switch` 的 case 使用 `Yes` / `No`；Pipeline 节点名使用英文，用户可见 option 名使用中文。

## 最小示例

```jsonc
"自动接受": {
    "type": "switch",
    "default_case": "No",
    "cases": [
        { "name": "Yes", "pipeline_override": { "Join": { "next": ["Confirm"] } } },
        { "name": "No", "pipeline_override": { "Join": { "next": ["Cancel"] } } }
    ]
}
```

以上示例只改变已存在 `Join` 节点的后继，不需要 Python 或 Flag。

## 验证

依次执行 JSON 语法检查、`check_resource.py`，再用 [pipeline-testing](../pipeline-testing/SKILL.md) 验证默认 case 和每个非默认 case。含跨文件引用的流程使用完整 resource bundle 集成测试。
