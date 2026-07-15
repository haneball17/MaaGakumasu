# HIF 决策日志事件目录

本目录定义首版稳定事件名、产生时机和审计级别。公共字段遵循 [SCHEMA.md](SCHEMA.md)。表中的“关键”表示事件写入失败时不得继续发送游戏输入。

## 运行与日志设施

| `event_name`             | 关键 | 产生时机                       | `body` 必填字段                                                                         |
| ------------------------ | ---- | ------------------------------ | --------------------------------------------------------------------------------------- |
| `run.started`            | 是   | 新培育运行建立后               | `mode`、`route`、`initial_state_ref`                                                    |
| `run.resumed`            | 是   | 新 session 确认能续接旧 run 后 | `previous_session_id`、`previous_segment`、`previous_sequence_no`、`recovery_state_ref` |
| `run.ended`              | 是   | 运行正常、失败或停止结束时     | `result`、`reason_code`、`last_verified_state_ref`                                      |
| `journal.segment_opened` | 是   | session 日志分段可用后         | `segment`、`write_target`、`start_sequence_no`                                          |
| `journal.tail_recovered` | 是   | 启动时发现并隔离末尾残行       | `segment`、`quarantine_path`、`discarded_bytes`                                         |
| `telemetry.degraded`     | 是   | 非关键日志或证据通道降级时     | `channel`、`reason_code`、`fallback`                                                    |
| `telemetry.restored`     | 是   | 降级通道恢复时                 | `channel`、`degraded_duration_ms`                                                       |
| `safety.stopped`         | 是   | 安全规则阻止继续执行时         | `trigger_event_id`、`reason_code`、`last_verified_state_ref`                            |
| `retention.completed`    | 否   | 一轮清理完成后                 | `deleted_run_ids`、`freed_bytes`、`reason`                                              |

## 观察与状态规范化

| `event_name`           | 关键 | 产生时机                   | `body` 必填字段                                                                                       |
| ---------------------- | ---- | -------------------------- | ----------------------------------------------------------------------------------------------------- |
| `observation.captured` | 是   | 一次决策观察完成时         | `screen_state`、`recognizer_results`、`confidence`、`frame_ref`                                       |
| `state.normalized`     | 是   | 得到唯一算法输入后         | `observed_state_ref`、`normalized_state_ref`、`normalized_state_hash`、`state_diff_ref`、`invariants` |
| `state.rejected`       | 是   | 状态冲突、缺失或不受支持时 | `observed_state_ref`、`reason_code`、`retry_count`、`conflicts`                                       |

## 搜索与决策

| `event_name`               | 关键 | 产生时机                           | `body` 必填字段                                                                        |
| -------------------------- | ---- | ---------------------------------- | -------------------------------------------------------------------------------------- |
| `planning.started`         | 是   | 搜索开始前                         | `normalized_state_hash`、`seed`、`search_config`、`budget`                             |
| `planning.batch_completed` | 否   | 一个完整深度/样本批次完成后        | `batch_no`、`depth`、`scenario_count`、`elapsed_ms`、`candidate_summary_ref`           |
| `planning.completed`       | 是   | 至少一个完整批次产生最终结果时     | `completed_batches`、`root_candidates`、`selected_action`、`stop_reason`、`detail_ref` |
| `planning.degraded`        | 是   | 搜索超时或模型限制触发安全回退时   | `reason_code`、`last_complete_batch`、`fallback_policy`、`fallback_action`             |
| `planning.failed`          | 是   | 无可用完整结果且不能安全回退时     | `reason_code`、`last_complete_batch`、`error`                                          |
| `decision.approved`        | 是   | Hard Gate 和执行策略允许推荐动作时 | `selected_action`、`approval_mode`、`rules_checked`、`normalized_state_hash`           |
| `decision.rejected`        | 是   | 推荐动作未通过审批时               | `selected_action`、`reason_code`、`failed_rules`                                       |

`planning.completed.body.root_candidates` 的每项至少包含 `action`、`rank`、`mean`、`median`、`p10`、`cvar10`、`failure_rate`、
`safety_violation_probability`、`target_margin`、`confidence_interval` 和 `score_components`。

## 执行与语义后验

| `event_name`       | 关键 | 产生时机                     | `body` 必填字段                                                                   |
| ------------------ | ---- | ---------------------------- | --------------------------------------------------------------------------------- |
| `action.intended`  | 是   | 向控制器发送输入之前         | `action`、`target`、`controller_command`、`expected_transition`、`pre_state_hash` |
| `action.executed`  | 是   | 控制器返回发送结果后         | `action`、`controller_command`、`controller_result`、`attempt_no`                 |
| `action.verified`  | 是   | 动作后语义状态符合预期时     | `pre_state_hash`、`post_state_ref`、`post_state_hash`、`semantic_assertions`      |
| `action.failed`    | 是   | 控制器失败或后验不符合预期时 | `stage`、`reason_code`、`observed_result`、`retry_allowed`                        |
| `action.timed_out` | 是   | 执行或验证超过限制时         | `stage`、`timeout_ms`、`last_observation_ref`                                     |
| `action.abandoned` | 是   | 重启恢复时确认旧动作不应重试 | `original_action_event_id`、`reason_code`、`recovery_observation_ref`             |

## 稳定原因码

首版至少定义以下原因码；新增原因码可以向前兼容，重命名或改变语义必须提升事件版本：

- 状态：`state_incomplete`、`state_conflict`、`unsupported_effect`、`recovery_state_mismatch`
- 搜索：`soft_budget_reached`、`hard_budget_reached`、`no_complete_batch`、`candidate_too_close`、`safe_fallback_used`
- 执行：`target_not_unique`、`controller_error`、`semantic_postcondition_failed`、`verification_timeout`
- 日志：`audit_write_failed`、`diagnostic_write_failed`、`evidence_write_failed`、`schema_validation_failed`、`disk_space_low`

自由文本说明可以补充上下文，但不能替代稳定原因码。
