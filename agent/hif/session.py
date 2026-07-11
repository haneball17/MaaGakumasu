"""同一次 HIF 运行内的最小跨页面状态。"""

from __future__ import annotations

from dataclasses import field, dataclass


@dataclass(slots=True)
class HIFRunSession:
    """仅保存已经由点击后验确认的事实，不保存推测状态。"""

    selected_p_items: list[tuple[str, int]] = field(default_factory=list)
    played_cards: dict[str, set[str]] = field(default_factory=dict)

    def record_p_item(self, name: str, stage: int) -> None:
        self.selected_p_items.append((name, stage))

    def latest_p_item(self, stage: int) -> str | None:
        return next((name for name, item_stage in reversed(self.selected_p_items) if item_stage == stage), None)

    def record_card(self, round_key: str, card_name: str) -> None:
        self.played_cards.setdefault(round_key, set()).add(card_name)

    def card_was_played(self, round_key: str, card_name: str) -> bool:
        return card_name in self.played_cards.get(round_key, set())


_RUNTIME_SESSION = HIFRunSession()


def get_runtime_hif_session() -> HIFRunSession:
    return _RUNTIME_SESSION


def reset_runtime_hif_session() -> HIFRunSession:
    global _RUNTIME_SESSION
    _RUNTIME_SESSION = HIFRunSession()
    return _RUNTIME_SESSION
