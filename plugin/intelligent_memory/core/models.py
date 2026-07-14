from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FactStatus(StrEnum):
    ACTIVE = "active"
    CONFLICTED = "conflicted"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    REJECTED = "rejected"


@dataclass(frozen=True)
class FactInput:
    content: str
    kind: str = "general"
    target: str = "memory"
    subject: str = ""
    predicate: str = ""
    value: str = ""
    aliases: tuple[str, ...] = ()
    scope: str = "global"
    source: str = "user"
    source_ref: str = ""
    profile: str = "default"
    confidence: float = 0.5
    importance: float = 0.5
    supersedes_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Fact:
    fact_id: int
    content: str
    normalized_content: str
    kind: str
    target: str
    subject: str
    predicate: str
    value: str
    aliases: tuple[str, ...]
    scope: str
    source: str
    source_ref: str
    profile: str
    confidence: float
    importance: float
    status: FactStatus
    supersedes_id: int | None
    conflicts_with_id: int | None
    created_at: str
    updated_at: str
    retrieval_count: int
    helpful_count: int
    unhelpful_count: int


@dataclass(frozen=True)
class RememberResult:
    fact_id: int
    created: bool
    fact: Fact


@dataclass(frozen=True)
class Provenance:
    fact_id: int
    source: str
    source_ref: str
    profile: str
    metadata: dict[str, Any]
    created_at: str
