from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

from .models import Fact, FactInput, FactStatus, Provenance, RememberResult
from .normalize import character_ngrams, jaccard, normalize_text, tokens

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS facts (
    fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    normalized_content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    predicate TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL DEFAULT 'global',
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    profile TEXT NOT NULL,
    confidence REAL NOT NULL,
    importance REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    supersedes_id INTEGER REFERENCES facts(fact_id),
    conflicts_with_id INTEGER REFERENCES facts(fact_id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retrieval_count INTEGER NOT NULL DEFAULT 0,
    helpful_count INTEGER NOT NULL DEFAULT 0,
    unhelpful_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(profile, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_facts_profile_status ON facts(profile, status);
CREATE INDEX IF NOT EXISTS idx_facts_profile_target ON facts(profile, target);
CREATE INDEX IF NOT EXISTS idx_facts_subject_predicate
    ON facts(profile, subject, predicate, status);
CREATE TABLE IF NOT EXISTS fact_provenance (
    provenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL REFERENCES facts(fact_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    profile TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_provenance_fact ON fact_provenance(fact_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_provenance_identity
    ON fact_provenance(fact_id, source, source_ref, metadata_json);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    content, aliases_json, subject, predicate, value,
    content='facts', content_rowid='fact_id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, aliases_json, subject, predicate, value)
    VALUES (new.fact_id, new.content, new.aliases_json, new.subject, new.predicate, new.value);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, aliases_json, subject, predicate, value)
    VALUES (
        'delete', old.fact_id, old.content, old.aliases_json,
        old.subject, old.predicate, old.value
    );
    INSERT INTO facts_fts(rowid, content, aliases_json, subject, predicate, value)
    VALUES (new.fact_id, new.content, new.aliases_json, new.subject, new.predicate, new.value);
END;
"""


class MemoryStore:
    """Profile-scoped SQLite canonical store for structured memory facts."""

    def __init__(self, path: str | Path, *, profile: str = "default") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,
            timeout=10.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 10000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.executescript(_SCHEMA)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Apply additive, idempotent migrations to persistent user databases."""
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(facts)").fetchall()
        }
        migrations = {
            "subject": "TEXT NOT NULL DEFAULT ''",
            "predicate": "TEXT NOT NULL DEFAULT ''",
            "value": "TEXT NOT NULL DEFAULT ''",
            "conflicts_with_id": "INTEGER REFERENCES facts(fact_id)",
        }
        for column, declaration in migrations.items():
            if column not in columns:
                self._connection.execute(
                    f"ALTER TABLE facts ADD COLUMN {column} {declaration}"
                )
        fts_columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(facts_fts)").fetchall()
        }
        if "aliases" in fts_columns or "aliases_json" not in fts_columns:
            self._connection.executescript(
                """
                DROP TRIGGER IF EXISTS facts_ai;
                DROP TRIGGER IF EXISTS facts_au;
                DROP TABLE IF EXISTS facts_fts;
                CREATE VIRTUAL TABLE facts_fts USING fts5(
                    content, aliases_json, subject, predicate, value,
                    content='facts', content_rowid='fact_id', tokenize='unicode61'
                );
                CREATE TRIGGER facts_ai AFTER INSERT ON facts BEGIN
                    INSERT INTO facts_fts(
                        rowid, content, aliases_json, subject, predicate, value
                    ) VALUES (
                        new.fact_id, new.content, new.aliases_json,
                        new.subject, new.predicate, new.value
                    );
                END;
                CREATE TRIGGER facts_au AFTER UPDATE ON facts BEGIN
                    INSERT INTO facts_fts(
                        facts_fts, rowid, content, aliases_json, subject, predicate, value
                    ) VALUES (
                        'delete', old.fact_id, old.content, old.aliases_json,
                        old.subject, old.predicate, old.value
                    );
                    INSERT INTO facts_fts(
                        rowid, content, aliases_json, subject, predicate, value
                    ) VALUES (
                        new.fact_id, new.content, new.aliases_json,
                        new.subject, new.predicate, new.value
                    );
                END;
                """
            )
        self._connection.execute("INSERT INTO facts_fts(facts_fts) VALUES ('rebuild')")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def remember(self, item: FactInput) -> RememberResult:
        content = item.content.strip()
        if not content:
            raise ValueError("content must not be empty")
        if item.profile != self.profile:
            raise ValueError("fact profile does not match the opened memory profile")
        normalized = normalize_text(content)
        if not normalized:
            raise ValueError("content must contain searchable text")
        if _unsafe_memory_content(content):
            raise ValueError("unsafe memory content: persistent prompt-injection pattern")
        content_hash = normalized
        aliases = tuple(dict.fromkeys(alias.strip() for alias in item.aliases if alias.strip()))
        with self._lock:
            existing = self._connection.execute(
                "SELECT * FROM facts WHERE profile = ? AND content_hash = ?",
                (self.profile, content_hash),
            ).fetchone()
            if existing is not None:
                fact = self._row_to_fact(existing)
                self._add_provenance(fact.fact_id, item)
                return RememberResult(fact.fact_id, False, fact)

            near_duplicate = (
                self._find_near_duplicate(item, normalized)
                if item.supersedes_id is None
                else None
            )
            if near_duplicate is not None:
                self._add_provenance(near_duplicate.fact_id, item)
                return RememberResult(near_duplicate.fact_id, False, near_duplicate)

            status = FactStatus.ACTIVE
            supersedes_id = item.supersedes_id
            conflicts_with_id: int | None = None
            structured_conflict = self._find_structured_conflict(item)
            if structured_conflict is not None and supersedes_id is None:
                if (
                    item.source == "cloud_extraction"
                    and item.confidence < structured_conflict.confidence
                ):
                    status = FactStatus.CONFLICTED
                    conflicts_with_id = structured_conflict.fact_id
                else:
                    supersedes_id = structured_conflict.fact_id

            now = self._connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
            cursor = self._connection.execute(
                """INSERT INTO facts (
                    content, normalized_content, content_hash, kind, target,
                    subject, predicate, value, aliases_json, scope, source,
                    source_ref, profile, confidence, importance, status, supersedes_id,
                    conflicts_with_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    content,
                    normalized,
                    content_hash,
                    item.kind,
                    item.target,
                    item.subject,
                    item.predicate,
                    item.value,
                    json.dumps(aliases, ensure_ascii=False),
                    item.scope,
                    item.source,
                    item.source_ref,
                    item.profile,
                    _clamp(item.confidence),
                    _clamp(item.importance),
                    status.value,
                    supersedes_id,
                    conflicts_with_id,
                    now,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a fact id")
            fact_id = int(cursor.lastrowid)
            if supersedes_id is not None:
                self._connection.execute(
                    "UPDATE facts SET status = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE fact_id = ? AND profile = ?",
                    (FactStatus.SUPERSEDED.value, supersedes_id, self.profile),
                )
            self._add_provenance(fact_id, item)
            fact = self.get_fact(fact_id)
            return RememberResult(fact_id, True, fact)

    def get_fact(self, fact_id: int) -> Fact:
        row = self._connection.execute(
            "SELECT * FROM facts WHERE fact_id = ? AND profile = ?",
            (fact_id, self.profile),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown fact_id: {fact_id}")
        return self._row_to_fact(row)

    def archive(self, fact_id: int) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE facts SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE fact_id = ? AND profile = ?",
                (FactStatus.ARCHIVED.value, fact_id, self.profile),
            )

    def record_feedback(self, fact_id: int, *, helpful: bool) -> Fact:
        """Record explicit usefulness feedback and adjust confidence."""
        with self._lock:
            self.get_fact(fact_id)
            if helpful:
                self._connection.execute(
                    """UPDATE facts
                    SET helpful_count = helpful_count + 1,
                        confidence = MIN(1.0, confidence + 0.05),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE fact_id = ? AND profile = ?""",
                    (fact_id, self.profile),
                )
            else:
                self._connection.execute(
                    """UPDATE facts
                    SET unhelpful_count = unhelpful_count + 1,
                        confidence = MAX(0.0, confidence - 0.10),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE fact_id = ? AND profile = ?""",
                    (fact_id, self.profile),
                )
            return self.get_fact(fact_id)

    def archive_matching(self, old_text: str, *, target: str | None = None) -> int | None:
        """Archive the best active fact containing a normalized text fragment."""
        match = self.find_active_by_fragment(old_text, target=target)
        if match is None:
            return None
        self.archive(match.fact_id)
        return match.fact_id

    def find_active_by_fragment(self, old_text: str, *, target: str | None = None) -> Fact | None:
        fragment = normalize_text(old_text)
        if not fragment:
            return None
        params: list[object] = [self.profile, FactStatus.ACTIVE.value, f"%{fragment}%"]
        target_clause = ""
        if target:
            target_clause = " AND target = ?"
            params.append(target)
        row = self._connection.execute(
            f"""SELECT * FROM facts
            WHERE profile = ? AND status = ? AND normalized_content LIKE ? {target_clause}
            ORDER BY importance DESC, fact_id DESC LIMIT 1""",
            params,
        ).fetchone()
        return self._row_to_fact(row) if row is not None else None

    def active_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM facts WHERE profile = ? AND status = ?",
            (self.profile, FactStatus.ACTIVE.value),
        ).fetchone()
        return int(row[0])

    def list_active(self, *, target: str | None = None, limit: int = 1_000) -> list[Fact]:
        """List active profile facts in projection priority order."""
        params: list[object] = [self.profile, FactStatus.ACTIVE.value]
        target_clause = ""
        if target:
            target_clause = " AND target = ?"
            params.append(target)
        params.append(max(1, int(limit)))
        rows = self._connection.execute(
            f"""SELECT * FROM facts
            WHERE profile = ? AND status = ? {target_clause}
            ORDER BY importance DESC, confidence DESC, updated_at DESC, fact_id DESC
            LIMIT ?""",
            params,
        ).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def search(self, query: str, *, target: str | None = None, limit: int = 8) -> list[Fact]:
        if limit < 1:
            return []
        query_tokens = tokens(query)
        query_ngrams = character_ngrams(query)
        if not query_tokens and not query_ngrams:
            return []
        with self._lock:
            rows = self._candidate_rows(query, target=target, limit=max(limit * 8, 32))
            scored: list[tuple[float, Fact]] = []
            for row in rows:
                fact = self._row_to_fact(row)
                haystack = " ".join(
                    (fact.content, fact.subject, fact.predicate, fact.value, *fact.aliases)
                )
                token_score = jaccard(query_tokens, tokens(haystack))
                ngram_score = jaccard(query_ngrams, character_ngrams(haystack))
                exact_bonus = 0.25 if normalize_text(query) in fact.normalized_content else 0.0
                score = (
                    token_score * 0.45
                    + ngram_score * 0.25
                    + fact.confidence * 0.15
                    + fact.importance * 0.15
                    + exact_bonus
                )
                if score > 0:
                    scored.append((score, fact))
            scored.sort(key=lambda pair: (-pair[0], -pair[1].importance, pair[1].fact_id))
            for _, fact in scored[:limit]:
                self._connection.execute(
                    "UPDATE facts SET retrieval_count = retrieval_count + 1 WHERE fact_id = ?",
                    (fact.fact_id,),
                )
            return [fact for _, fact in scored[:limit]]

    def provenance_count(self, fact_id: int) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM fact_provenance WHERE fact_id = ?", (fact_id,)
        ).fetchone()
        return int(row[0])

    def list_provenance(self, fact_id: int) -> list[Provenance]:
        rows = self._connection.execute(
            "SELECT * FROM fact_provenance WHERE fact_id = ? ORDER BY provenance_id",
            (fact_id,),
        ).fetchall()
        return [
            Provenance(
                fact_id=int(row["fact_id"]),
                source=row["source"],
                source_ref=row["source_ref"],
                profile=row["profile"],
                metadata=json.loads(row["metadata_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _find_near_duplicate(self, item: FactInput, normalized: str) -> Fact | None:
        """Merge wording variants without merging corrections or negations."""
        rows = self._connection.execute(
            """SELECT * FROM facts
            WHERE profile = ? AND status = ? AND kind = ? AND target = ?
            ORDER BY fact_id DESC LIMIT 200""",
            (self.profile, FactStatus.ACTIVE.value, item.kind, item.target),
        ).fetchall()
        incoming_tokens = tokens(normalized)
        incoming_ngrams = character_ngrams(normalized)
        incoming_negative = _contains_negation(normalized)
        best: tuple[float, Fact] | None = None
        for row in rows:
            fact = self._row_to_fact(row)
            if incoming_negative != _contains_negation(fact.normalized_content):
                continue
            score = (
                jaccard(incoming_tokens, tokens(fact.normalized_content)) * 0.65
                + jaccard(incoming_ngrams, character_ngrams(fact.normalized_content)) * 0.35
            )
            if score >= 0.72 and (best is None or score > best[0]):
                best = (score, fact)
        return best[1] if best else None

    def _find_structured_conflict(self, item: FactInput) -> Fact | None:
        subject = normalize_text(item.subject)
        predicate = normalize_text(item.predicate)
        value = normalize_text(item.value)
        if not subject or not predicate or not value:
            return None
        rows = self._connection.execute(
            """SELECT * FROM facts
            WHERE profile = ? AND status = ?
              AND subject = ? AND predicate = ?
            ORDER BY confidence DESC, fact_id DESC""",
            (self.profile, FactStatus.ACTIVE.value, item.subject, item.predicate),
        ).fetchall()
        for row in rows:
            fact = self._row_to_fact(row)
            if normalize_text(fact.value) != value:
                return fact
        return None

    def _candidate_rows(self, query: str, *, target: str | None, limit: int) -> list[sqlite3.Row]:
        normalized = normalize_text(query)
        params: list[object] = [self.profile, FactStatus.ACTIVE.value]
        target_clause = ""
        if target:
            target_clause = " AND f.target = ?"
            params.append(target)
        try:
            match = " OR ".join(f'"{token}"' for token in tokens(query))
            if match:
                params.extend([match, limit])
                return self._connection.execute(
                    f"""SELECT f.* FROM facts f JOIN facts_fts ON facts_fts.rowid = f.fact_id
                    WHERE f.profile = ? AND f.status = ? {target_clause}
                    AND facts_fts MATCH ? LIMIT ?""",
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            pass
        like = f"%{normalized}%"
        params.extend([like, like, like, limit])
        return self._connection.execute(
            f"""SELECT * FROM facts WHERE profile = ? AND status = ? {target_clause}
            AND (normalized_content LIKE ? OR aliases_json LIKE ? OR value LIKE ?) LIMIT ?""",
            params,
        ).fetchall()

    def _add_provenance(self, fact_id: int, item: FactInput) -> None:
        self._connection.execute(
            """INSERT OR IGNORE INTO fact_provenance
            (fact_id, source, source_ref, profile, metadata_json)
            VALUES (?, ?, ?, ?, ?)""",
            (
                fact_id,
                item.source,
                item.source_ref,
                item.profile,
                json.dumps(item.metadata, ensure_ascii=False),
            ),
        )

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> Fact:
        return Fact(
            fact_id=int(row["fact_id"]),
            content=row["content"],
            normalized_content=row["normalized_content"],
            kind=row["kind"],
            target=row["target"],
            subject=row["subject"],
            predicate=row["predicate"],
            value=row["value"],
            aliases=tuple(json.loads(row["aliases_json"])),
            scope=row["scope"],
            source=row["source"],
            source_ref=row["source_ref"],
            profile=row["profile"],
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            status=FactStatus(row["status"]),
            supersedes_id=row["supersedes_id"],
            conflicts_with_id=row["conflicts_with_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            retrieval_count=int(row["retrieval_count"]),
            helpful_count=int(row["helpful_count"]),
            unhelpful_count=int(row["unhelpful_count"]),
        )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions\b", re.IGNORECASE),
    re.compile(r"\breveal\s+(?:the\s+)?system\s+prompt\b", re.IGNORECASE),
    re.compile(r"\b(?:system|developer)\s+(?:message|override)\b", re.IGNORECASE),
    re.compile(r"تجاهل\s+(?:كل\s+)?التعليمات", re.IGNORECASE),
)


def _unsafe_memory_content(content: str) -> bool:
    return any(pattern.search(content) for pattern in _INJECTION_PATTERNS)


def _contains_negation(content: str) -> bool:
    normalized = normalize_text(content)
    return bool(
        re.search(r"(?:^|\s)(?:لا|ليس|لن|لم|never|not|no)(?:\s|$)", normalized, re.IGNORECASE)
    )
