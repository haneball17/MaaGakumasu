# 域文档

工程技能探索代码库时，如何消费本仓库的领域文档。

## 探索前先读

- 仓库根目录的 **`CONTEXT.md`**：本项目的中文领域术语表，每个词条带定义与 `_Avoid_` 反义词（禁用的近义说法）。
- **`docs/adr/`**：读与工作区域相关的 ADR（现有 0001 模拟器零拟合、0002 模拟器本地 WebUI 技术栈）。

任一文件不存在时**静默继续**：不要提示缺失，不要建议预先创建。`/domain-modeling` 技能（经 `/grill-with-docs`、`/improve-codebase-architecture` 触达）会在术语或决策真正落定时惰性创建它们。

## 文件结构

本仓库为单上下文（single-context）布局：

```
/
├── CONTEXT.md          ← 全仓库唯一术语表
├── docs/adr/           ← 架构决策记录
│   ├── 0001-simulator-zero-fitting.md
│   └── 0002-local-web-ui-stack-for-simulator.md
├── agent/
├── assets/
└── tools/
```

（不存在 `CONTEXT-MAP.md`；若未来出现，按多上下文规则改为每个 context 一份 `CONTEXT.md`。）

## 使用术语表的词汇

输出中出现领域概念时（issue 标题、重构提案、假设、测试名），使用 `CONTEXT.md` 定义的术语原词，不要漂移到词条显式 `_Avoid_` 的近义词。

例：说「选卡评分（rewards）」不说「培育选卡」；说「Round 模拟器（roundsim）」不说「离线模拟器」。

需要的概念不在术语表里时，这是一个信号：要么你在发明项目不用的语言（重新考虑），要么存在真实缺口（记下来交给 `/domain-modeling`）。

## 标注 ADR 冲突

输出与现有 ADR 矛盾时，显式标注而不是静默覆盖：

> _与 ADR-0001（模拟器零拟合）冲突，但值得重开，因为…_
