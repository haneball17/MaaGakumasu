# 决策契约 Schema

本目录固定首版 `1.0.0` 的五个领域 Schema：牌局状态、原子动作、目标快照、规划请求和规划结果。
它们只描述纯领域 JSON，不包含截图、OCR、坐标、MaaFramework 对象或日志写入对象。

合法与非法样例是 `decision_algorithm_tests/test_contracts.py` 中的可执行夹具，覆盖：

- 正常选牌与饮料动作；
- 请求、结果的规范 JSON 往返；
- 硬预算超时降级和状态缺失安全停止；
- 五个 Schema 的缺字段、错误类型和未知主版本拒绝。

首版运行时不新增第三方依赖。`serialization.validate_schema()` 实现这些 Schema 实际使用的 JSON Schema
2020-12 子集，并支持本目录内的相对 `$ref`。新增 Schema 关键字时必须先扩展校验器及其负向测试，不能静默忽略。
