# HIF 决策日志 Schema

## 1. 公共事件信封

每行 JSONL 是一个完整 JSON 对象，UTF-8 编码，以 `\n` 结束。所有事件必须包含以下字段；不适用于当前事件的层级 ID 或耗时使用 `null`，不能省略。

| 字段                 | 类型与约束                                                              | 说明                                     |
| -------------------- | ----------------------------------------------------------------------- | ---------------------------------------- |
| `schema_version`     | 字符串，首版 `1.0.0`                                                    | 公共信封版本                             |
| `event_name`         | 稳定枚举                                                                | 见事件目录                               |
| `event_version`      | 正整数                                                                  | 单个事件主体契约版本                     |
| `event_id`           | UUIDv4 字符串                                                           | 全局唯一事件 ID；首版不引入 UUIDv7 依赖  |
| `sequence_no`        | 非负整数                                                                | `run_id` 内严格递增                      |
| `run_id`             | UUID 字符串                                                             | 一次完整培育运行                         |
| `session_id`         | UUID 字符串                                                             | 一次程序进程会话                         |
| `round_id`           | 字符串或 `null`                                                         | 例如 `round1`、`round2`                  |
| `turn_id`            | UUID 字符串或 `null`                                                    | 一次出牌阶段                             |
| `decision_id`        | UUID 字符串或 `null`                                                    | 同一状态上的一次规划                     |
| `action_attempt_id`  | UUID 字符串或 `null`                                                    | 一次具体执行尝试                         |
| `trace_id`           | 32 个小写十六进制字符                                                   | 与 W3C Trace Context 兼容，整个 run 不变 |
| `span_id`            | 16 个小写十六进制字符                                                   | 当前操作 span                            |
| `parent_span_id`     | 16 个小写十六进制字符或 `null`                                          | 父操作 span                              |
| `timestamp`          | RFC 3339 UTC 字符串                                                     | 领域事件发生时间                         |
| `observed_timestamp` | RFC 3339 UTC 字符串                                                     | 日志系统观察到事件的时间                 |
| `monotonic_ns`       | 非负整数                                                                | 仅用于同一 session 内排序和计时          |
| `duration_ms`        | 非负数或 `null`                                                         | 有明确起止的操作耗时                     |
| `severity`           | `DEBUG/INFO/WARN/ERROR/FATAL`                                           | 稳定严重级别                             |
| `component`          | 非空字符串                                                              | 例如 `planner`、`executor`、`journal`    |
| `code_version`       | 非空字符串                                                              | Git commit 或可追踪构建版本              |
| `algorithm_version`  | 字符串或 `null`                                                         | 决策算法版本                             |
| `config_hash`        | 64 位小写 SHA-256 或 `null`                                             | 规范化配置哈希                           |
| `status`             | `started/succeeded/rejected/failed/timed_out/stopped/abandoned/skipped` | 事件结果                                 |
| `reason_code`        | 稳定枚举或 `null`                                                       | 机器可查询原因                           |
| `body`               | JSON 对象                                                               | 事件专属字段                             |
| `attributes`         | JSON 对象                                                               | 非核心扩展属性                           |
| `error`              | 对象或 `null`                                                           | 白名单化错误信息                         |
| `evidence_refs`      | 数组                                                                    | 证据对象引用                             |

`error` 只允许 `type`、`message`、`stack`、`retryable` 字段；不得直接序列化异常对象、环境变量或进程上下文。

## 2. 证据引用

每个 `evidence_refs` 元素必须包含：

```json
{
    "evidence_id": "018f0000-0000-7000-8000-000000000001",
    "kind": "frame",
    "path": "evidence/frames/turn-07-before.png",
    "media_type": "image/png",
    "size_bytes": 483210,
    "sha256": "64-lowercase-hex-characters",
    "schema_version": null
}
```

- `path` 必须相对 `run_id` 目录，禁止绝对路径和 `..`。
- `kind` 至少支持 `frame`、`observed_state`、`normalized_state`、`state_diff`、`candidate_summary`、`scenario_detail`、`report`。
- 结构化 JSON 证据必须填写自身 `schema_version`；图片可为 `null`。
- 写入日志前先完整落盘证据并计算 SHA-256；审计关键事件引用的必需证据失败时，视同关键日志失败。

## 3. 状态证据

`observed_state` 保留识别器输出、候选值、置信度、ROI/帧引用和识别器版本。`normalized_state` 只包含规划器实际读取的规范字段，必须可按规范 JSON 编码稳定计算 SHA-256。`state_diff` 使用字段级操作：

```json
{
    "schema_version": "1.0.0",
    "from_state_hash": "...",
    "to_state_hash": "...",
    "changes": [
        {"op": "replace", "path": "/score", "before": 120000, "after": 168000, "reason": "verified_action_effect"}]
}
```

数组或多重集合必须在规范化前使用领域定义的稳定排序；浮点数必须规定精度，不允许依赖平台默认字符串格式。

## 4. 写入提交协议

1. 构造事件并执行 Schema 校验。
2. 先写入事件依赖的证据临时文件，刷新后原子重命名到最终相对路径。
3. 将单行 JSON 一次追加到对应 journal，并写入结尾换行。
4. 审计关键事件刷新文件缓冲区；刷新成功后才返回“已提交”。主 journal 失败时立即重试 2 次，再尝试
   `audit/emergency-<session_id>.jsonl`；全部失败则返回不可执行。
5. 只有“已提交”的 `action.intended` 才能解锁对应的控制器输入；它必须包含动作、目标、精确控制器命令和预期状态转移。
6. 控制器返回后同步提交 `action.executed`。若回执无法提交，禁止任何后续输入并进入恢复流程，但不能声称此前输入未发生。

启动时若最后一行没有完整换行或无法解析，将原始字节复制到隔离文件并截断到上一条完整记录，然后写入 `journal.tail_recovered`。中间行损坏不得自动修复，必须停止自动续跑。

## 5. 兼容规则

- 增加可选字段：保持 `schema_version`。
- 增加必填字段、删除字段、改变类型或语义：提升主版本。
- 新增 `event_name` 或原因码：向前兼容，但旧读取器必须保留未知事件而不是丢弃。
- 每个事件版本必须在事件目录中有一个合法样例和至少一个非法测试样例。

## 6. 目录布局

```text
debug/hif-runs/<run_id>/
  run.json
  audit/<session_id>-0001.jsonl
  decision/<session_id>-0001.jsonl
  diagnostic/<session_id>-0001.jsonl
  evidence/frames/
  evidence/states/
  evidence/scenarios/
  reports/
  quarantine/
```

`run.json` 仅保存运行索引、保护标记、创建/结束时间和分段列表；事实主线仍以 `audit` 事件为准。
