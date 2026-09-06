from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .core.models import FactInput
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

    search = subparsers.add_parser("search")
    search.add_argument("query", type=str, help="Search query string")
    search.add_argument("--hermes-home", type=Path, default=None)
    search.add_argument("--target", choices=["memory", "user"], default=None)
    search.add_argument("--limit", type=int, default=8)

    export = subparsers.add_parser("export")
    export.add_argument("--hermes-home", type=Path, default=None)
    export.add_argument(
        "--format",
        choices=["json", "json-ld", "markdown"],
        default="json",
        help="Export format (json, json-ld, markdown)",
    )
    export.add_argument(
        "--status",
        choices=["active", "archived", "superseded", "all"],
        default="active",
        help="Filter by fact lifecycle status",
    )
    export.add_argument("--target", choices=["memory", "user"], default=None)
    export.add_argument(
        "--output", type=Path, default=None, help="Output destination file (default: stdout)"
    )

    import_cmd = subparsers.add_parser("import")
    import_cmd.add_argument("file", type=Path, help="File to import memories from")
    import_cmd.add_argument("--hermes-home", type=Path, default=None)
    import_cmd.add_argument(
        "--format",
        choices=["auto", "json", "markdown"],
        default="auto",
        help="Input format (auto detects from extension)",
    )
    import_cmd.add_argument(
        "--target",
        choices=["memory", "user"],
        default="memory",
        help="Default target memory view",
    )

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
        if args.command == "search":
            facts = store.search(args.query, target=args.target, limit=args.limit)
            _print_json(
                {
                    "query": args.query,
                    "count": len(facts),
                    "results": [fact.__dict__ for fact in facts],
                }
            )
            return 0
        if args.command == "export":
            status_filter = None if args.status == "all" else args.status
            facts = store.list_facts(status=status_filter, target=args.target, limit=10_000)
            if args.format == "json":
                serialized = json.dumps(
                    [fact.__dict__ for fact in facts],
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            elif args.format == "json-ld":
                graph = {
                    "@context": {
                        "@vocab": "https://schema.org/",
                        "content": "text",
                        "confidence": "ratingValue",
                        "created_at": "dateCreated",
                    },
                    "@graph": [
                        {
                            "@type": "IntelligentMemoryFact",
                            "identifier": fact.fact_id,
                            "kind": fact.kind,
                            "content": fact.content,
                            "subject": fact.subject,
                            "predicate": fact.predicate,
                            "value": fact.value,
                            "target": fact.target,
                            "confidence": fact.confidence,
                            "importance": fact.importance,
                            "status": fact.status.value,
                            "created_at": fact.created_at,
                        }
                        for fact in facts
                    ],
                }
                serialized = json.dumps(graph, ensure_ascii=False, indent=2, default=str)
            else:  # markdown
                lines = ["# Exported Intelligent Memory Facts", ""]
                for fact in facts:
                    lines.append(
                        f"- **[{fact.fact_id}]** (`{fact.status.value}` | `{fact.target}`): "
                        f"{fact.content}"
                    )
                    if fact.subject or fact.predicate or fact.value:
                        triple = f"`{fact.subject}` -> `{fact.predicate}` -> `{fact.value}`"
                        lines.append(f"  - Structured: {triple}")
                serialized = "\n".join(lines) + "\n"

            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(serialized, encoding="utf-8")
                _print_json(
                    {"exported": len(facts), "format": args.format, "file": str(args.output)}
                )
            else:
                print(serialized)
            return 0
        if args.command == "import":
            if not args.file.is_file():
                _print_json({"error": f"input file not found: {args.file}"})
                return 2

            fmt = args.format
            if fmt == "auto":
                ext = args.file.suffix.lower()
                fmt = "markdown" if ext in {".md", ".markdown", ".txt"} else "json"

            imported = 0
            if fmt == "json":
                payload = json.loads(args.file.read_text(encoding="utf-8"))
                items = (
                    payload
                    if isinstance(payload, list)
                    else payload.get("@graph", payload.get("facts", []))
                )
                for item in items:
                    if isinstance(item, dict) and "content" in item:
                        content_str = str(item["content"]).strip()
                        if content_str:
                            store.remember(
                                FactInput(
                                    content=content_str,
                                    kind=str(item.get("kind") or "general"),
                                    target=str(item.get("target") or args.target),
                                    subject=str(item.get("subject") or ""),
                                    predicate=str(item.get("predicate") or ""),
                                    value=str(item.get("value") or ""),
                                    source="cli_import",
                                    profile=_profile_name(),
                                )
                            )
                            imported += 1
            else:  # markdown
                raw_text = args.file.read_text(encoding="utf-8")
                for line in raw_text.splitlines():
                    trimmed = line.strip()
                    if trimmed.startswith(("- ", "* ")) and len(trimmed) > 3:
                        text_fact = trimmed[2:].strip()
                        # Clean markdown formatting if present
                        if text_fact.startswith("**[") and "]:" in text_fact:
                            text_fact = text_fact.split("]:", 1)[1].strip()
                        if text_fact:
                            store.remember(
                                FactInput(
                                    content=text_fact,
                                    target=args.target,
                                    source="cli_import",
                                    profile=_profile_name(),
                                )
                            )
                            imported += 1

            _print_json({"imported": imported, "file": str(args.file), "format": fmt})
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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run_command(args))


if __name__ == "__main__":
    main()
