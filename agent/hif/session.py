"""同一次 HIF 运行内的最小跨页面状态。"""

from __future__ import annotations

from dataclasses import field, dataclass


@dataclass(frozen=True, slots=True)
class HIFPendingReward:
    """已完成候选确认、等待点击领取按钮的奖励。"""

    kind: str
    name: str
    slot: str


@dataclass(frozen=True, slots=True)
class HIFPendingSelectChange:
    """已验证进入源卡牌库前实际选中的目标卡。"""

    target_name: str


@dataclass(slots=True)
class HIFRunSession:
    """仅保存已经由点击后验确认的事实，不保存推测状态。"""

    selected_p_items: list[tuple[str, int]] = field(default_factory=list)
    played_cards: dict[str, set[str]] = field(default_factory=dict)
    pending_reward: HIFPendingReward | None = None
    pending_select_change: HIFPendingSelectChange | None = None
    safe_advance_count: int = 0
    safe_advance_fingerprints: set[str] = field(default_factory=set)
    round_hand_probe_started: bool = False
    round_post_hand_probe_started: bool = False
    round_hand_detail_names: dict[tuple[int, int, int, int], str] = field(default_factory=dict)

    def record_p_item(self, name: str, stage: int) -> None:
        self.selected_p_items.append((name, stage))

    def latest_p_item(self, stage: int) -> str | None:
        return next((name for name, item_stage in reversed(self.selected_p_items) if item_stage == stage), None)

    def record_card(self, round_key: str, card_name: str) -> None:
        self.played_cards.setdefault(round_key, set()).add(card_name)

    def card_was_played(self, round_key: str, card_name: str) -> bool:
        return card_name in self.played_cards.get(round_key, set())

    def set_pending_reward(self, kind: str, name: str, slot: str) -> None:
        self.pending_reward = HIFPendingReward(kind=kind, name=name, slot=slot)

    def clear_pending_reward(self) -> None:
        self.pending_reward = None

    def set_pending_select_change(self, target_name: str) -> None:
        self.pending_select_change = HIFPendingSelectChange(target_name=target_name)

    def clear_pending_select_change(self) -> None:
        self.pending_select_change = None

    def record_safe_advance(self, fingerprint: str | None) -> bool:
        """记录一次空白推进；重复帧代表路由已经陷入循环。"""

        if fingerprint and fingerprint in self.safe_advance_fingerprints:
            return False
        if fingerprint:
            self.safe_advance_fingerprints.add(fingerprint)
        self.safe_advance_count += 1
        return True

    def reset_safe_advance(self) -> None:
        self.safe_advance_count = 0
        self.safe_advance_fingerprints.clear()

    def record_hand_detail_name(self, box: tuple[int, int, int, int], name: str) -> None:
        if name:
            self.round_hand_detail_names[box] = name

    def hand_detail_name(self, box: tuple[int, int, int, int]) -> str | None:
        direct = self.round_hand_detail_names.get(box)
        if direct:
            return direct
        matches = [
            name
            for recorded_box, name in self.round_hand_detail_names.items()
            if _box_iou(box, recorded_box) >= 0.8
        ]
        return matches[0] if len(matches) == 1 else None


def _box_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    overlap_width = max(0, min(left_x + left_width, right_x + right_width) - max(left_x, right_x))
    overlap_height = max(0, min(left_y + left_height, right_y + right_height) - max(left_y, right_y))
    overlap = overlap_width * overlap_height
    union = left_width * left_height + right_width * right_height - overlap
    return overlap / union if union else 0.0


_RUNTIME_SESSION = HIFRunSession()


def get_runtime_hif_session() -> HIFRunSession:
    return _RUNTIME_SESSION


def reset_runtime_hif_session() -> HIFRunSession:
    global _RUNTIME_SESSION
    _RUNTIME_SESSION = HIFRunSession()
    return _RUNTIME_SESSION
