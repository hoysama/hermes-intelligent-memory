from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .core.store import MemoryStore
from .migration import MemoryMigrator
from .projection import ProjectionManager


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="intelligent-memory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "migrate", "project"):
        child = subparsers.add_parser(command)
        child.add_argument("--hermes-home", type=Path, default=None)
        if command == "migrate":
            child.add_argument("--dry-run", action="store_true")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--hermes-home", type=Path, default=None)
    rollback.add_argument("--backup", type=Path, required=True)
    return parser


def run_command(args: argparse.Namespace) -> int:
    home = args.hermes_home or _hermes_home()
    database = home / "intelligent_memory" / "memory.db"
    store = MemoryStore(database, profile=_profile_name())
    try:
        if args.command == "status":
            _print_json(
                {
                    "provider": "intelligent_memory",
                    "database": str(database),
                    "active_facts": store.active_count(),
                }
            )
            return 0
        if args.command == "migrate":
            report = MemoryMigrator(home, store=store, profile=_profile_name()).migrate(
                dry_run=bool(args.dry_run)
            )
            _print_json(report.__dict__)
            return 0
        if args.command == "project":
            result = ProjectionManager(home, store=store).materialize()
            _print_json(
                {
                    **result.__dict__,
                    "backup_dir": str(result.backup_dir),
                }
            )
            return 0
        if args.command == "rollback":
            if not args.backup.is_dir():
                _print_json({"error": f"backup not found: {args.backup}"})
                return 2
            ProjectionManager(home, store=store).rollback(args.backup)
            _print_json({"restored": True, "backup": str(args.backup)})
            return 0
        _print_json({"error": f"unknown command: {args.command}"})
        return 2
    finally:
        store.close()


def register_cli(subparser: argparse.ArgumentParser) -> None:
    build_parser(subparser)
    subparser.set_defaults(func=intelligent_memory_command)


def intelligent_memory_command(args: argparse.Namespace) -> None:
    raise SystemExit(run_command(args))


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home  # type: ignore[import-untyped]

    return Path(get_hermes_home())


def _profile_name() -> str:
    try:
        from hermes_cli.profiles import get_active_profile_name  # type: ignore[import-untyped]

        return str(get_active_profile_name())
    except Exception:
        return "default"


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
