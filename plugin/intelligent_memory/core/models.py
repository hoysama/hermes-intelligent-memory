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
    project: str = ""
    tags: tuple[str, ...] = ()
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
    project: str = ""
    tags: tuple[str, ...] = ()
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
    status: FactStatus = FactStatus.ACTIVE
    supersedes_id: int | None = None
    conflicts_with_id: int | None = None
    created_at: str = ""
    updated_at: str = ""
    retrieval_count: int = 0
    helpful_count: int = 0
    unhelpful_count: int = 0


@dataclass(frozen=True)
class RememberResult:
    fact_id: int
    created: bool
    fact: Fact
    conflict_fact: Fact | None = None


@dataclass(frozen=True)
class Provenance:
    fact_id: int
    source: str
    source_ref: str
    profile: str
    metadata: dict[str, Any]
    created_at: str
