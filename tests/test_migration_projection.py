from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from intelligent_memory.core.store import MemoryStore
from intelligent_memory.migration import MemoryMigrator
from intelligent_memory.projection import ProjectionManager

DELIMITER = "\n§\n"


def _write_builtin(home: Path) -> tuple[bytes, bytes]:
    memories = home / "memories"
    memories.mkdir(parents=True)
    memory_bytes = DELIMITER.join(
        [
            "Project uses Cloudflare Workers and D1",
            "Use Bun for package management",
        ]
    ).encode()
    user_bytes = DELIMITER.join(
        [
            "User's name is Abdullah",
            "User prefers detailed Arabic explanations",
        ]
    ).encode()
    (memories / "MEMORY.md").write_bytes(memory_bytes)
    (memories / "USER.md").write_bytes(user_bytes)
    return memory_bytes, user_bytes


def _write_holographic(home: Path) -> None:
    connection = sqlite3.connect(home / "memory_store.db")
    connection.execute(
        """CREATE TABLE facts (
        fact_id INTEGER PRIMARY KEY,
        content TEXT NOT NULL,
        category TEXT,
        tags TEXT,
        trust_score REAL,
        created_at TEXT,
        updated_at TEXT
        )"""
    )
    connection.executemany(
        "INSERT INTO facts VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        [
            (1, "Use Bun for package management", "tool", "bun,packages", 0.8),
            (2, "Nabeh uses email OTP verification", "project", "nabeh,otp", 0.9),
        ],
    )
    connection.commit()
    connection.close()


def test_dry_run_reports_sources_without_writing(tmp_path) -> None:
    _write_builtin(tmp_path)
    _write_holographic(tmp_path)
    store = MemoryStore(tmp_path / "intelligent_memory" / "memory.db", profile="default")
    migrator = MemoryMigrator(tmp_path, store=store, profile="default")

    report = migrator.migrate(dry_run=True)

    assert report.builtin_candidates == 4
    assert report.holographic_candidates == 2
    assert report.imported == 0
    assert store.active_count() == 0
    assert list((tmp_path / "intelligent_memory").glob("backups/*")) == []
    store.close()


def test_migration_is_idempotent_and_preserves_provenance(tmp_path) -> None:
    _write_builtin(tmp_path)
    _write_holographic(tmp_path)
    store = MemoryStore(tmp_path / "intelligent_memory" / "memory.db", profile="default")
    migrator = MemoryMigrator(tmp_path, store=store, profile="default")

    first = migrator.migrate()
    second = migrator.migrate()

    assert first.imported == 5
    assert first.deduplicated == 1
    assert second.imported == 0
    assert second.deduplicated == 6
    bun = store.search("Bun package management")[0]
    assert store.provenance_count(bun.fact_id) >= 2
    assert store.active_count() == 5
    store.close()


def test_projection_is_bounded_atomic_and_backed_up(tmp_path) -> None:
    original_memory, original_user = _write_builtin(tmp_path)
    store = MemoryStore(tmp_path / "intelligent_memory" / "memory.db", profile="default")
    migrator = MemoryMigrator(tmp_path, store=store, profile="default")
    migrator.migrate()
    projection = ProjectionManager(
        tmp_path,
        store=store,
        memory_char_limit=90,
        user_char_limit=70,
    )

    result = projection.materialize()

    memory_path = tmp_path / "memories" / "MEMORY.md"
    user_path = tmp_path / "memories" / "USER.md"
    assert len(memory_path.read_text(encoding="utf-8")) <= 90
    assert len(user_path.read_text(encoding="utf-8")) <= 70
    assert result.backup_dir.exists()
    manifest = json.loads((result.backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["MEMORY.md"]["sha256"] == hashlib.sha256(original_memory).hexdigest()
    assert manifest["files"]["USER.md"]["sha256"] == hashlib.sha256(original_user).hexdigest()
    assert (result.backup_dir / "MEMORY.md").read_bytes() == original_memory
    assert (result.backup_dir / "USER.md").read_bytes() == original_user
    store.close()


def test_rollback_restores_original_bytes(tmp_path) -> None:
    original_memory, original_user = _write_builtin(tmp_path)
    store = MemoryStore(tmp_path / "intelligent_memory" / "memory.db", profile="default")
    MemoryMigrator(tmp_path, store=store, profile="default").migrate()
    projection = ProjectionManager(tmp_path, store=store)
    result = projection.materialize()
    (tmp_path / "memories" / "MEMORY.md").write_text("corrupted", encoding="utf-8")
    (tmp_path / "memories" / "USER.md").write_text("corrupted", encoding="utf-8")

    projection.rollback(result.backup_dir)

    assert (tmp_path / "memories" / "MEMORY.md").read_bytes() == original_memory
    assert (tmp_path / "memories" / "USER.md").read_bytes() == original_user
    store.close()


def test_invalid_holographic_schema_is_skipped_without_breaking_builtin_import(tmp_path) -> None:
    _write_builtin(tmp_path)
    sqlite3.connect(tmp_path / "memory_store.db").close()
    store = MemoryStore(tmp_path / "intelligent_memory" / "memory.db", profile="default")

    report = MemoryMigrator(tmp_path, store=store, profile="default").migrate()

    assert report.imported == 4
    assert report.warnings
    assert store.active_count() == 4
    store.close()
