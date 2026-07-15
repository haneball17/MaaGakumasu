"""目录 v2 的轻量核心类型。Schema 仍是持久化契约的最终定义。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from dataclasses import field, asdict, dataclass


class ParseStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    CORROBORATED = "corroborated"
    IN_GAME_VERIFIED = "in_game_verified"
    REJECTED = "rejected"


class RuntimeSupport(StrEnum):
    DISPLAY_ONLY = "display_only"
    RECOGNIZABLE = "recognizable"
    MODELED = "modeled"
    EXECUTABLE = "executable"
    UNSUPPORTED = "unsupported"


class AliasType(StrEnum):
    OFFICIAL_NAME = "official_name"
    TRANSLATION = "translation"
    SOURCE_VARIANT = "source_variant"
    DISPLAY_VARIANT = "display_variant"
    HISTORICAL_NAME = "historical_name"
    OCR_ERROR = "ocr_error"
    LEGACY_KEY = "legacy_key"


@dataclass(frozen=True, slots=True)
class SourceKey:
    source_id: str
    key: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Assertion:
    assertion_id: str
    entity_id: str
    field_path: str
    value: Any
    raw_value: Any
    source_id: str
    source_locator: str
    observed_at: str
    source_confidence: str
    parse_status: ParseStatus
    verification_status: VerificationStatus
    runtime_support: RuntimeSupport
    parser_version: str
    content_hash: str
    schema_version: str = "2.0"
    effective_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    decision_id: str
    entity_id: str
    field_path: str
    selected_assertion_ids: tuple[str, ...]
    retained_conflict_ids: tuple[str, ...]
    reason: str
    decided_at: str
    affected_derived: tuple[str, ...] = ()
    schema_version: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Term:
    entity_id: str
    code: str
    names: dict[str, str]
    source_keys: tuple[SourceKey, ...] = ()
    schema_version: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Alias:
    entity_id: str
    target_entity_id: str
    alias_type: AliasType
    value: str
    locale: str
    profile: str | None = None
    evidence_assertion_ids: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
