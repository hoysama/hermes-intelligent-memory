from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .core.models import FactInput
from .core.store import MemoryStore

ENTRY_DELIMITER = "\n§\n"


@dataclass(frozen=True)
class MigrationReport:
    dry_run: bool
    builtin_candidates: int
    holographic_candidates: int
    imported: int
    deduplicated: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


class MemoryMigrator:
    """Idempotently import Built-in and Holographic memory with provenance."""

    def __init__(self, hermes_home: str | Path, *, store: MemoryStore, profile: str) -> None:
        self.hermes_home = Path(hermes_home)
        self.store = store
        self.profile = profile

    def migrate(self, *, dry_run: bool = False) -> MigrationReport:
        builtin = self._builtin_candidates()
        holographic, warnings = self._holographic_candidates()
        candidates = [*builtin, *holographic]
        if dry_run:
            return MigrationReport(
                dry_run=True,
                builtin_candidates=len(builtin),
                holographic_candidates=len(holographic),
                imported=0,
                deduplicated=0,
                warnings=tuple(warnings),
            )

        imported = 0
        deduplicated = 0
        for candidate in candidates:
            result = self.store.remember(candidate)
            if result.created:
                imported += 1
            else:
                deduplicated += 1
        return MigrationReport(
            dry_run=False,
            builtin_candidates=len(builtin),
            holographic_candidates=len(holographic),
            imported=imported,
            deduplicated=deduplicated,
            warnings=tuple(warnings),
        )

    def _builtin_candidates(self) -> list[FactInput]:
        results: list[FactInput] = []
        memories = self.hermes_home / "memories"
        for filename, target in (("MEMORY.md", "memory"), ("USER.md", "user")):
            path = memories / filename
            for index, content in enumerate(_read_entries(path), start=1):
                results.append(
                    FactInput(
                        content=content,
                        kind="preference" if target == "user" else "general",
                        target=target,
                        source="builtin",
                        source_ref=f"{filename}:{index}",
                        profile=self.profile,
                        confidence=0.95,
                        importance=0.85,
                    )
                )
        return results

    def _holographic_candidates(self) -> tuple[list[FactInput], list[str]]:
        path = self.hermes_home / "memory_store.db"
        if not path.exists():
            return [], []
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(facts)").fetchall()
            }
            required = {"fact_id", "content"}
            if not required.issubset(columns):
                return [], ["Holographic database has no compatible facts table"]
            rows = connection.execute("SELECT * FROM facts ORDER BY fact_id").fetchall()
        except sqlite3.Error as exc:
            return [], [f"Holographic database skipped: {exc}"]
        finally:
            if connection is not None:
                connection.close()

        results: list[FactInput] = []
        for row in rows:
            content = str(row["content"] or "").strip()
            if not content:
                continue
            category = str(row["category"] or "general") if "category" in columns else "general"
            tags = str(row["tags"] or "") if "tags" in columns else ""
            trust = float(row["trust_score"] or 0.5) if "trust_score" in columns else 0.5
            aliases = tuple(part.strip() for part in tags.split(",") if part.strip())
            results.append(
                FactInput(
                    content=content,
                    kind=category,
                    target="user" if category == "user_pref" else "memory",
                    aliases=aliases,
                    source="holographic",
                    source_ref=f"memory_store.db:{row['fact_id']}",
                    profile=self.profile,
                    confidence=max(0.0, min(1.0, trust)),
                    importance=0.65,
                )
            )
        return results, []


def _read_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [entry.strip() for entry in raw.split(ENTRY_DELIMITER) if entry.strip()]
