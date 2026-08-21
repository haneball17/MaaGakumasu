"""HIF 会话状态 round1 子树单测（D1，_ProduceHIFActionBase）。

验证 round1 命名空间读写：
- 读写只动 state["round1"] 子树，不污染顶层字段（day_remaining 等）
- patch 合并语义（未提及的旧键保留、同键覆盖）
- session-state 文件缺失时安全降级为空 dict

所有测试离线可跑；_SESSION_STATE_FILE 重定向到 tmp_path，不碰 debug/decisions/ 真实会话文件。
"""

from __future__ import annotations

import sys
from pathlib import Path
from importlib import import_module


def _load_produce_hif_module():
    # 与 test_hif_decision.py 相同的加载方式：agent/ 进 sys.path 以满足 produce_hif 内 `from utils import logger`
    agent_path = str(Path("agent").resolve())
    sys.path.insert(0, agent_path)
    try:
        return import_module("agent.custom.action.produce_hif")
    finally:
        sys.path.remove(agent_path)


def _fresh_base(monkeypatch, tmp_path):
    """加载 _ProduceHIFActionBase 并把会话文件重定向到 tmp_path。"""
    produce_hif = _load_produce_hif_module()
    monkeypatch.setattr(produce_hif._ProduceHIFActionBase, "_SESSION_STATE_FILE", tmp_path / "session-state.json")
    return produce_hif._ProduceHIFActionBase


def test_read_round1_state_missing_file_returns_empty(monkeypatch, tmp_path) -> None:
    """session-state 文件不存在时 round1 子树返回空 dict（安全降级，不抛异常）。"""
    base = _fresh_base(monkeypatch, tmp_path)
    assert base._read_round1_state() == {}


def test_write_round1_state_patch_merge(monkeypatch, tmp_path) -> None:
    """round1 写入为 patch 合并：未提及的旧键保留，同键覆盖。"""
    base = _fresh_base(monkeypatch, tmp_path)
    base._write_round1_state({"cards_played": 1, "oneesan_used": False, "reprise_count": 0})
    base._write_round1_state({"cards_played": 2})  # 只推进 cards_played
    state = base._read_round1_state()
    assert state["cards_played"] == 2
    assert state["oneesan_used"] is False
    assert state["reprise_count"] == 0


def test_round1_state_does_not_pollute_top_level(monkeypatch, tmp_path) -> None:
    """round1 读写不污染顶层字段；round1 字段也不泄漏到顶层。"""
    base = _fresh_base(monkeypatch, tmp_path)
    base._write_session_state({"day_remaining": 6, "select_change_active": False})
    base._write_round1_state({"cards_played": 3, "oneesan_used": True})

    state = base._read_session_state()
    assert state["day_remaining"] == 6  # 顶层日程字段不受 round1 写入影响
    assert state["select_change_active"] is False
    assert state["round1"] == {"cards_played": 3, "oneesan_used": True}
    assert "cards_played" not in state  # round1 字段不泄漏到顶层
    assert base._read_round1_state() == {"cards_played": 3, "oneesan_used": True}
    assert base._read_session_day() == 6  # 顶层 day 读取不受影响


def test_round1_state_fields_cover_task_fields() -> None:
    """ROUND1_STATE_FIELDS 覆盖 D1 任务五字段（turn/cards_played/oneesan_used/natural_finisher_used/reprise_count）。"""
    base = _load_produce_hif_module()._ProduceHIFActionBase  # 只读类常量，无需重定向会话文件
    assert base.ROUND1_STATE_FIELDS == (
        "turn",
        "cards_played",
        "oneesan_used",
        "natural_finisher_used",
        "reprise_count",
    )


def test_reset_round1_state_clears_previous_run(monkeypatch, tmp_path) -> None:
    """_reset_round1_state：整体替换 round1 子树（上局残留清零，Phase 2 新局入口调用）。"""
    base = _fresh_base(monkeypatch, tmp_path)
    # 模拟上局残留 + 局外脏键
    base._write_round1_state({"turn": 9, "cards_played": 11, "oneesan_used": True, "stale_key": "x"})
    base._write_session_state({"day_remaining": 2})

    base._reset_round1_state()

    state = base._read_round1_state()
    assert state == {
        "turn": 0,
        "cards_played": 0,
        "oneesan_used": False,
        "natural_finisher_used": False,
        "reprise_count": 0,
    }  # 脏键一并清除（整体替换而非 patch 合并）
    assert base._read_session_state()["day_remaining"] == 2  # 顶层字段不受影响
