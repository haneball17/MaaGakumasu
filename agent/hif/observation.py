"""从已收集的 OCR 文本产生可审计的 HIF 页面观察结果。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.hif.screen_profiles import RiskLevel, HIFScreenProfiles, load_hif_screen_profiles


@dataclass(frozen=True, slots=True)
class HIFPageObservation:
    screen_id: str | None
    risk: RiskLevel | None
    confidence: float
    matched_screen_ids: tuple[str, ...]
    raw_texts: tuple[str, ...]

    @property
    def is_unique(self) -> bool:
        return self.screen_id is not None and self.confidence == 1.0


def observe_hif_page(
    texts: tuple[str | None, ...] | list[str | None],
    profiles: HIFScreenProfiles | None = None,
) -> HIFPageObservation:
    """仅在唯一命中页面配置时返回可用于后续动作的页面类型。"""

    normalized = tuple(text.strip() for text in texts if isinstance(text, str) and text.strip())
    matched = (profiles or load_hif_screen_profiles()).classify(normalized)
    if len(matched) != 1:
        return HIFPageObservation(
            screen_id=None,
            risk=None,
            confidence=0.0,
            matched_screen_ids=tuple(profile.screen_id for profile in matched),
            raw_texts=normalized,
        )
    profile = matched[0]
    return HIFPageObservation(
        screen_id=profile.screen_id,
        risk=profile.risk,
        confidence=1.0,
        matched_screen_ids=(profile.screen_id,),
        raw_texts=normalized,
    )
