"""Round 中活跃效果列表的保守结构化读取。

效果列表的 OCR 行顺序会随图标位置改变，不能再把固定 ROI 的数字当作再演次数。
本模块只接受已实机验证的完整文本模式；缺失、歧义或冲突一律保留为 ``None``。
"""

from __future__ import annotations

import re
from typing import Iterable
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ActiveEffectSnapshot:
    """同一帧效果列表中能够交叉确认的、会影响动作后验的效果。"""

    score_increase_percent: int | None = None
    score_increase_turns: int | None = None
    stamina_cost_reduction_percent: int | None = None
    stamina_cost_reduction_turns: int | None = None
    excellent_turns: int | None = None
    reservation_count: int | None = None
    reservation_turns: int | None = None
    source_lines: tuple[str, ...] = ()

    @property
    def execution_ready(self) -> bool:
        """当前已知的四项联动均明确时，才允许作为严格后验输入。"""

        return all(
            value is not None
            for value in (
                self.score_increase_percent,
                self.score_increase_turns,
                self.stamina_cost_reduction_percent,
                self.stamina_cost_reduction_turns,
                self.excellent_turns,
                self.reservation_count,
                self.reservation_turns,
            )
        )

    def to_journal(self) -> dict[str, object]:
        """返回可 JSON 序列化的审计字段。"""

        return {**asdict(self), "execution_ready": self.execution_ready}


def parse_active_effects(lines: Iterable[str]) -> ActiveEffectSnapshot:
    """从同一张效果列表的 OCR 行构造快照，不对不完整值做默认填充。"""

    source_lines = tuple(_normalize(line) for line in lines if _normalize(line))
    joined = "\n".join(source_lines)
    score_increase_percent = _unique_int(
        re.findall(r"スコア上昇量を\s*(\d+)\s*[%％]\s*増加", joined)
    )
    stamina_cost_reduction_percent = _unique_int(
        re.findall(r"消費体力を\s*(\d+)\s*[%％]\s*軽減", joined)
    )

    return ActiveEffectSnapshot(
        score_increase_percent=score_increase_percent,
        score_increase_turns=_effect_turns(source_lines, "パラメータ上昇量増加"),
        stamina_cost_reduction_percent=stamina_cost_reduction_percent,
        stamina_cost_reduction_turns=_effect_turns(source_lines, "消費体力減少"),
        excellent_turns=_effect_turns(source_lines, "絶好調"),
        reservation_count=_effect_count(source_lines, "発動予約"),
        reservation_turns=_effect_turns(source_lines, "発動予約"),
        source_lines=source_lines,
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).replace("％", "%").replace("体カ", "体力")


def _unique_int(values: Iterable[str]) -> int | None:
    parsed = {int(value) for value in values}
    return next(iter(parsed)) if len(parsed) == 1 else None


def _effect_turns(lines: tuple[str, ...], effect_name: str) -> int | None:
    return _effect_suffix_value(lines, effect_name, r"(\d+)ターン")


def _effect_count(lines: tuple[str, ...], effect_name: str) -> int | None:
    return _effect_suffix_value(lines, effect_name, r"(\d+)回")


def _effect_suffix_value(lines: tuple[str, ...], effect_name: str, pattern: str) -> int | None:
    try:
        index = next(index for index, line in enumerate(lines) if effect_name in line)
    except StopIteration:
        return None
    # 标题与数值说明相邻；扩大窗口会把下一个效果（例如绝好调）的时长混入。
    nearby = "\n".join(lines[index : index + 3])
    return _unique_int(re.findall(pattern, nearby))
