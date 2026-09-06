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
    fixes: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        return self.integrity and self.discovery and self.database


def run_doctor(
    hermes_home: str | Path,
    *,
    hermes_source: str | Path | None = None,
    python_executable: str = sys.executable,
    fix: bool = False,
    plugin_source: str | Path | None = None,
) -> DoctorResult:
    home = Path(hermes_home)
    plugin = home / "plugins" / "intelligent_memory"
    details: list[str] = []
    fixes: list[str] = []
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

    database_path = home / "intelligent_memory" / "memory.db"
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3

        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA quick_check").fetchone()
        connection.close()
        database = True
    except Exception as exc:
        details.append(f"database: {exc}")

    if fix:
        # 1. Fix integrity if broken and plugin source is provided
        if not integrity and plugin_source is not None:
            try:
                from installer import install_plugin

                install_plugin(plugin_source, home)
                verify_integrity(plugin)
                integrity = True
                fixes.append(f"Restored plugin files from {plugin_source}")
                details = [d for d in details if not d.startswith("integrity:")]
            except Exception as exc:
                details.append(f"fix integrity failed: {exc}")

        # 2. Fix database indices (FTS5 rebuild and vacuum)
        try:
            if database_path.exists():
                import sqlite3

                conn = sqlite3.connect(database_path)
                try:
                    conn.execute("INSERT INTO facts_fts(facts_fts) VALUES ('rebuild')")
                    conn.commit()
                    fixes.append("Rebuilt facts_fts search index")
                except Exception:
                    pass
                conn.execute("PRAGMA optimize")
                conn.close()
                database = True
                details = [d for d in details if not d.startswith("database:")]
        except Exception as exc:
            details.append(f"fix database index failed: {exc}")

        # 3. Fix missing or unbuilt projection views
        try:
            if database_path.exists():
                StoreCls, ProjCls = _load_memory_classes()
                store = StoreCls(database_path)
                try:
                    memories = home / "memories"
                    memory_file = memories / "MEMORY.md"
                    user_file = memories / "USER.md"
                    missing_projections = not memory_file.exists() or not user_file.exists()
                    if missing_projections or memory_file.stat().st_size == 0:
                        proj = ProjCls(home, store=store)
                        result = proj.materialize()
                        fixes.append(
                            f"Rebuilt projections ({result.memory_entries} memory, "
                            f"{result.user_entries} user entries)"
                        )
                finally:
                    store.close()
        except Exception as exc:
            details.append(f"fix projections failed: {exc}")

    return DoctorResult(integrity, discovery, database, tuple(details), tuple(fixes))


def _load_memory_classes() -> tuple[type, type]:
    try:
        from intelligent_memory.core.store import MemoryStore
        from intelligent_memory.projection import ProjectionManager

        return MemoryStore, ProjectionManager
    except ImportError:
        plugin_path = Path(__file__).resolve().parent / "plugin"
        if str(plugin_path) not in sys.path:
            sys.path.insert(0, str(plugin_path))
        from intelligent_memory.core.store import MemoryStore
        from intelligent_memory.projection import ProjectionManager

        return MemoryStore, ProjectionManager


def doctor_json(result: DoctorResult) -> str:
    return json.dumps(
        {
            "healthy": result.healthy,
            "integrity": result.integrity,
            "discovery": result.discovery,
            "database": result.database,
            "details": result.details,
            "fixes": result.fixes,
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="doctor",
        description="Diagnostic and self-healing doctor for Hermes Intelligent Memory",
    )
    parser.add_argument("--hermes-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--hermes-source", type=Path, default=None)
    parser.add_argument("--plugin-source", type=Path, default=None)
    parser.add_argument(
        "--fix", action="store_true", help="Automatically repair detected issues"
    )
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    result = run_doctor(
        args.hermes_home,
        hermes_source=args.hermes_source,
        fix=args.fix,
        plugin_source=args.plugin_source,
    )
    if args.json:
        print(doctor_json(result))
    else:
        status_str = "HEALTHY" if result.healthy else "ISSUES DETECTED"
        print(f"Intelligent Memory Doctor: {status_str}")
        print(f"  Integrity: {'OK' if result.integrity else 'FAILED'}")
        print(f"  Discovery: {'OK' if result.discovery else 'SKIPPED/FAILED'}")
        print(f"  Database:  {'OK' if result.database else 'FAILED'}")
        if result.fixes:
            print("Fixes applied:")
            for fix in result.fixes:
                print(f"  [+] {fix}")
        if result.details:
            print("Details:")
            for detail in result.details:
                print(f"  [-] {detail}")
    sys.exit(0 if result.healthy else 1)


if __name__ == "__main__":
    main()
