from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .core.store import MemoryStore

ENTRY_DELIMITER = "\n§\n"


@dataclass(frozen=True)
class ProjectionResult:
    backup_dir: Path
    memory_chars: int
    user_chars: int
    memory_entries: int
    user_entries: int


class ProjectionManager:
    """Materialize bounded Built-in memory views with verified rollback."""

    def __init__(
        self,
        hermes_home: str | Path,
        *,
        store: MemoryStore,
        memory_char_limit: int = 2_200,
        user_char_limit: int = 1_375,
        keep_backups: int = 20,
    ) -> None:
        self.hermes_home = Path(hermes_home)
        self.store = store
        self.memory_char_limit = max(1, int(memory_char_limit))
        self.user_char_limit = max(1, int(user_char_limit))
        self.keep_backups = max(2, int(keep_backups))

    def materialize(self) -> ProjectionResult:
        memory_entries = self._bounded_entries("memory", self.memory_char_limit)
        user_entries = self._bounded_entries("user", self.user_char_limit)
        backup_dir = self._create_backup()
        memories = self.hermes_home / "memories"
        memories.mkdir(parents=True, exist_ok=True)
        memory_text = ENTRY_DELIMITER.join(memory_entries)
        user_text = ENTRY_DELIMITER.join(user_entries)
        _atomic_write(memories / "MEMORY.md", memory_text.encode("utf-8"))
        _atomic_write(memories / "USER.md", user_text.encode("utf-8"))
        return ProjectionResult(
            backup_dir=backup_dir,
            memory_chars=len(memory_text),
            user_chars=len(user_text),
            memory_entries=len(memory_entries),
            user_entries=len(user_entries),
        )

    def rollback(self, backup_dir: str | Path) -> None:
        backup = Path(backup_dir)
        manifest_path = backup / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Missing backup manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise ValueError("Invalid backup manifest")
        memories = self.hermes_home / "memories"
        memories.mkdir(parents=True, exist_ok=True)
        for filename in ("MEMORY.md", "USER.md"):
            record = files.get(filename)
            source = backup / filename
            if not isinstance(record, dict) or not source.is_file():
                raise ValueError(f"Incomplete backup for {filename}")
            payload = source.read_bytes()
            expected = str(record.get("sha256") or "")
            if hashlib.sha256(payload).hexdigest() != expected:
                raise ValueError(f"Backup integrity check failed for {filename}")
            _atomic_write(memories / filename, payload)

    def _bounded_entries(self, target: str, limit: int) -> list[str]:
        selected: list[str] = []
        for fact in self.store.list_active(target=target):
            candidate = [*selected, fact.content]
            if len(ENTRY_DELIMITER.join(candidate)) > limit:
                continue
            selected.append(fact.content)
        return selected

    def _create_backup(self) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = self.hermes_home / "intelligent_memory" / "backups" / f"projection-{timestamp}"
        backup.mkdir(parents=True, exist_ok=False)
        files: dict[str, dict[str, object]] = {}
        memories = self.hermes_home / "memories"
        for filename in ("MEMORY.md", "USER.md"):
            source = memories / filename
            payload = source.read_bytes() if source.exists() else b""
            destination = backup / filename
            destination.write_bytes(payload)
            files[filename] = {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "existed": source.exists(),
            }
        manifest = {
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "files": files,
        }
        (backup / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._prune_backups(backup.parent)
        return backup

    def _prune_backups(self, root: Path) -> None:
        backups = sorted(
            (path for path in root.glob("projection-*") if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        for stale in backups[self.keep_backups :]:
            for child in sorted(stale.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            stale.rmdir()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temp_name)
        raise
