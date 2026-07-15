"""HIF 重启状态重建与局内账本对账的纯逻辑。

画面可见字段必须来自当前扫描；只有调用方明确声明为不可持续显示的字段，
才允许由同一局、未过期且经过动作后验验证的账本恢复。任何不一致都返回
类型化问题，不选择一个看似合理的值继续运行。
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping
from datetime import datetime, timedelta
from dataclasses import dataclass

StateValue = int | float | str | bool | tuple[str, ...]


class StateIssueCode(str, Enum):
    """可信状态无法建立的原因。"""

    MISSING = "missing"
    CONFLICT = "conflict"
    STALE = "stale"
    RUN_MISMATCH = "run_mismatch"
    UNVERIFIED_LEDGER = "unverified_ledger"
    LEDGER_NOT_ALLOWED = "ledger_not_allowed"


@dataclass(frozen=True, slots=True)
class StateIssue:
    field: str
    code: StateIssueCode
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ObservedField:
    value: StateValue
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class StateObservation:
    """一次当前画面扫描；同字段多候选由 ``conflicts`` 显式携带。"""

    run_id: str
    captured_at: datetime
    fields: Mapping[str, ObservedField]
    conflicts: Mapping[str, tuple[StateValue, ...]]


@dataclass(frozen=True, slots=True)
class LedgerField:
    value: StateValue
    verified_at: datetime
    action_id: str
    postcondition_verified: bool


@dataclass(frozen=True, slots=True)
class StateLedger:
    run_id: str
    fields: Mapping[str, LedgerField]


@dataclass(frozen=True, slots=True)
class ReconciledState:
    run_id: str
    values: Mapping[str, StateValue]
    sources: Mapping[str, str]
    issues: tuple[StateIssue, ...]

    @property
    def is_trusted(self) -> bool:
        return not self.issues


def reconcile_state(
    observation: StateObservation,
    ledger: StateLedger | None,
    *,
    required_fields: frozenset[str],
    ledger_fields: frozenset[str],
    now: datetime,
    max_observation_age: timedelta,
    max_ledger_age: timedelta,
) -> ReconciledState:
    """按“当前观测优先、同局已验证账本受限补齐”建立可信状态。"""

    values: dict[str, StateValue] = {}
    sources: dict[str, str] = {}
    issues: list[StateIssue] = []
    observation_stale = now - observation.captured_at > max_observation_age
    if observation_stale:
        issues.append(StateIssue("*", StateIssueCode.STALE, "当前画面扫描已过期"))

    ledger_run_matches = ledger is not None and ledger.run_id == observation.run_id
    if ledger is not None and not ledger_run_matches:
        issues.append(StateIssue("*", StateIssueCode.RUN_MISMATCH, "账本不属于当前 run_id"))

    for field in sorted(required_fields):
        conflicts = observation.conflicts.get(field, ())
        if conflicts:
            issues.append(StateIssue(field, StateIssueCode.CONFLICT, repr(conflicts)))
            continue

        observed = observation.fields.get(field)
        if observed is not None:
            if observation_stale or now - observed.observed_at > max_observation_age:
                issues.append(StateIssue(field, StateIssueCode.STALE, "字段观测已过期"))
                continue
            values[field] = observed.value
            sources[field] = "screen"
            ledger_value = ledger.fields.get(field) if ledger_run_matches and ledger is not None else None
            if ledger_value is not None and ledger_value.postcondition_verified and ledger_value.value != observed.value:
                issues.append(StateIssue(field, StateIssueCode.CONFLICT, "当前画面与已验证账本不一致"))
            continue

        if field not in ledger_fields:
            issues.append(StateIssue(field, StateIssueCode.MISSING, "当前画面未读取且禁止账本补值"))
            continue
        if not ledger_run_matches or ledger is None:
            issues.append(StateIssue(field, StateIssueCode.MISSING, "没有同局账本"))
            continue
        ledger_value = ledger.fields.get(field)
        if ledger_value is None:
            issues.append(StateIssue(field, StateIssueCode.MISSING, "账本缺少字段"))
        elif not ledger_value.postcondition_verified:
            issues.append(StateIssue(field, StateIssueCode.UNVERIFIED_LEDGER, ledger_value.action_id))
        elif now - ledger_value.verified_at > max_ledger_age:
            issues.append(StateIssue(field, StateIssueCode.STALE, "账本字段已过期"))
        else:
            values[field] = ledger_value.value
            sources[field] = f"ledger:{ledger_value.action_id}"

    return ReconciledState(observation.run_id, values, sources, tuple(issues))


def rebuild_after_restart(
    observation: StateObservation,
    ledger: StateLedger | None,
    *,
    visible_fields: frozenset[str],
    ledger_fields: frozenset[str],
    now: datetime,
    max_observation_age: timedelta,
    max_ledger_age: timedelta,
) -> ReconciledState:
    """重启后重建状态；所有可见字段都强制当前重扫，账本不得覆盖。"""

    result = reconcile_state(
        observation,
        ledger,
        required_fields=visible_fields | ledger_fields,
        ledger_fields=ledger_fields,
        now=now,
        max_observation_age=max_observation_age,
        max_ledger_age=max_ledger_age,
    )
    # 防止调用方错误地把可见字段同时列为账本字段。
    overlap = visible_fields & ledger_fields
    if not overlap:
        return result
    issues = (*result.issues, *(StateIssue(field, StateIssueCode.LEDGER_NOT_ALLOWED) for field in sorted(overlap)))
    return ReconciledState(result.run_id, result.values, result.sources, issues)
