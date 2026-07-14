from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from installer import verify_integrity


@dataclass(frozen=True)
class DoctorResult:
    integrity: bool
    discovery: bool
    database: bool
    details: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return self.integrity and self.discovery and self.database


def run_doctor(
    hermes_home: str | Path,
    *,
    hermes_source: str | Path | None = None,
    python_executable: str = sys.executable,
) -> DoctorResult:
    home = Path(hermes_home)
    plugin = home / "plugins" / "intelligent_memory"
    details: list[str] = []
    integrity = False
    discovery = False
    database = False

    try:
        verify_integrity(plugin)
        integrity = True
    except Exception as exc:
        details.append(f"integrity: {exc}")

    if hermes_source is not None:
        script = (
            "from plugins.memory import load_memory_provider; "
            "p=load_memory_provider('intelligent_memory'); "
            "assert p is not None and p.name == 'intelligent_memory'; "
            "print('ok')"
        )
        env = os.environ.copy()
        env["HERMES_HOME"] = str(home)
        env["PYTHONPATH"] = str(Path(hermes_source))
        completed = subprocess.run(
            [python_executable, "-c", script],
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        discovery = completed.returncode == 0
        if not discovery:
            details.append(f"discovery: {(completed.stderr or completed.stdout).strip()}")
    else:
        details.append("discovery: Hermes source path not provided")

    try:
        database_path = home / "intelligent_memory" / "memory.db"
        database_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3

        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA quick_check").fetchone()
        connection.close()
        database = True
    except Exception as exc:
        details.append(f"database: {exc}")

    return DoctorResult(integrity, discovery, database, tuple(details))


def doctor_json(result: DoctorResult) -> str:
    return json.dumps(
        {
            "healthy": result.healthy,
            "integrity": result.integrity,
            "discovery": result.discovery,
            "database": result.database,
            "details": result.details,
        },
        ensure_ascii=False,
        indent=2,
    )
