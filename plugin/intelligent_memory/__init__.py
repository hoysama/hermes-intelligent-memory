from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    class MemoryProvider:
        """Typing-only stand-in for Hermes runtime MemoryProvider ABC."""
        pass
else:
    try:
        from agent.memory_provider import MemoryProvider
    except ImportError:
        class MemoryProvider:  # type: ignore[no-redef]
            """Standalone fallback when running CLI or tests without Hermes runtime."""
            pass

from .cloud import CloudMemoryAnalyzer
from .core.models import Fact, FactInput
from .core.store import MemoryStore

logger = logging.getLogger(__name__)

REMEMBER_SCHEMA = {
    "name": "intelligent_memory_remember",
    "description": "Store one durable structured fact in intelligent memory with optional project, tags, and category.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The fact or rule content to remember."},
            "kind": {
                "type": "string",
                "enum": ["preference", "fact", "lesson", "correction", "project", "general"],
                "description": "Category of the fact.",
            },
            "project": {
                "type": "string",
                "description": "Project or repository name associated with this fact (e.g. 'hermes-agent', 'sentinel').",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Domain or topic tags (e.g. ['payments', 'production', 'api']).",
            },
            "target": {"type": "string", "enum": ["memory", "user"], "description": "Target memory scope."},
            "aliases": {"type": "array", "items": {"type": "string"}, "description": "Alternative search terms or keywords."},
            "confidence": {"type": "number", "description": "Confidence score between 0.0 and 1.0."},
            "importance": {"type": "number", "description": "Importance score between 0.0 and 1.0."},
        },
        "required": ["content"],
    },
}
RECALL_SCHEMA = {
    "name": "intelligent_memory_recall",
    "description": "Search active intelligent-memory facts relevant to a query with fast in-process semantic reranking and optional project/kind filtering.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query in natural language or keywords."},
            "target": {"type": "string", "enum": ["memory", "user"], "description": "Filter by target scope."},
            "project": {"type": "string", "description": "Filter facts associated with a specific project name."},
            "kind": {
                "type": "string",
                "enum": ["preference", "fact", "lesson", "correction", "project", "general"],
                "description": "Filter facts by category.",
            },
            "limit": {"type": "integer", "description": "Maximum number of facts to return (default 8, max 50)."},
        },
        "required": ["query"],
    },
}
STATUS_SCHEMA = {
    "name": "intelligent_memory_status",
    "description": "Report intelligent-memory provider status without exposing facts.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["check"]}
        },
        "required": ["action"],
    },
}
REVISE_SCHEMA = {
    "name": "intelligent_memory_revise",
    "description": "Replace one durable fact while preserving its history.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact_id": {"type": "integer", "description": "The ID of the fact to replace."},
            "content": {"type": "string", "description": "The updated fact content."},
            "project": {"type": "string", "description": "Updated project name."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Updated tags."},
        },
        "required": ["fact_id", "content"],
    },
}
FORGET_SCHEMA = {
    "name": "intelligent_memory_forget",
    "description": "Archive one fact without deleting its history.",
    "parameters": {
        "type": "object",
        "properties": {"fact_id": {"type": "integer"}},
        "required": ["fact_id"],
    },
}
FEEDBACK_SCHEMA = {
    "name": "intelligent_memory_feedback",
    "description": "Record whether a recalled fact was useful.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact_id": {"type": "integer"},
            "helpful": {"type": "boolean"},
        },
        "required": ["fact_id", "helpful"],
    },
}


class IntelligentMemoryProvider(MemoryProvider):
    """Local-first bilingual memory provider with selective cloud enrichment."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        cloud_analyzer: Callable[[Sequence[dict[str, Any]]], list[FactInput]] | None = None,
    ) -> None:
        self.config = dict(config or {})
        self._apply_config(self.config)
        self.agent_context = "primary"
        self.profile = "default"
        self.session_id = ""
        self.platform = "cli"
        self.database_path = Path("memory.db")
        self.store: MemoryStore
        self.last_cloud_error = ""
        self._cloud_analyzer = cloud_analyzer
        self._closed = False

    @property
    def name(self) -> str:
        return "intelligent_memory"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        hermes_home = Path(str(kwargs.get("hermes_home") or "."))
        file_config = _load_provider_config(hermes_home)
        self.config = {**file_config, **self.config}
        self._apply_config(self.config)
        self.profile = str(kwargs.get("agent_identity") or "default")
        self.session_id = session_id
        self.platform = str(kwargs.get("platform") or "cli")
        self.agent_context = str(kwargs.get("agent_context") or "primary")
        configured_path = self.config.get("db_path")
        self.database_path = (
            Path(str(configured_path).replace("$HERMES_HOME", str(hermes_home))).expanduser()
            if configured_path
            else hermes_home / "intelligent_memory" / "memory.db"
        )
        self.store = MemoryStore(self.database_path, profile=self.profile)
        self._register_auxiliary_task()
        self._closed = False

    def _apply_config(self, config: dict[str, Any]) -> None:
        self.cloud_mode = _cloud_mode(config.get("cloud_mode", "selective"))
        self.max_recall_facts = max(1, min(50, int(config.get("max_recall_facts", 25))))
        self.max_recall_chars = max(200, int(config.get("max_recall_chars", 10000)))

    @staticmethod
    def _register_auxiliary_task() -> None:
        try:
            from hermes_cli.plugins import (  # type: ignore[import-untyped]
                PluginContext,
                PluginManifest,
                get_plugin_manager,
            )

            manifest = PluginManifest(
                name="intelligent_memory",
                kind="exclusive",
                key="intelligent_memory",
            )
            context = PluginContext(manifest, get_plugin_manager())
            context.register_auxiliary_task(
                key="intelligent_memory",
                display_name="Intelligent memory",
                description="Selective multilingual memory extraction and reconciliation",
                defaults={"provider": "auto", "timeout": 30},
            )
        except Exception as exc:
            logger.debug("Auxiliary memory task registration skipped: %s", exc)

    def system_prompt_block(self) -> str:
        return (
            "# Intelligent Memory\n"
            "Active local-first memory. Relevant facts are recalled per turn; "
            "use intelligent_memory_remember for durable facts (with optional project and tags) "
            "and intelligent_memory_recall for explicit deep recall."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        facts = self.store.search(query, limit=self.max_recall_facts)
        if not facts:
            return ""
        lines = ["# Relevant memory"]
        for fact in facts:
            tags_part = f" [tags: {', '.join(fact.tags)}]" if fact.tags else ""
            proj_part = f" [proj: {fact.project}]" if fact.project else ""
            line = f"- [{fact.fact_id}; confidence={fact.confidence:.2f}]{proj_part}{tags_part} {fact.content}"
            candidate = "\n".join((*lines, line))
            if len(candidate) > self.max_recall_chars:
                break
            lines.append(line)
        result = "\n".join(lines)
        return result[: self.max_recall_chars]

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        return None

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        if self.agent_context != "primary" or self.cloud_mode not in {"selective", "session"}:
            return
        try:
            analyzer = self._cloud_analyzer or CloudMemoryAnalyzer().extract
            for fact in analyzer(messages):
                self.store.remember(
                    FactInput(
                        **{
                            **fact.__dict__,
                            "profile": self.profile,
                            "source_ref": self.session_id,
                        }
                    )
                )
            self.last_cloud_error = ""
        except Exception as exc:
            self.last_cloud_error = str(exc)
            logger.warning("Intelligent memory cloud extraction failed: %s", exc)

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.agent_context != "primary":
            return
        metadata = dict(metadata or {})
        old_text = str(metadata.get("old_text") or "")
        if action == "add" and content:
            self.store.remember(
                FactInput(
                    content=content,
                    target=target,
                    source="builtin",
                    source_ref=str(metadata.get("session_id") or self.session_id),
                    profile=self.profile,
                    confidence=0.95,
                    importance=0.8,
                    metadata=metadata,
                )
            )
        elif action == "replace" and content and old_text:
            old = self.store.find_active_by_fragment(old_text, target=target)
            self.store.remember(
                FactInput(
                    content=content,
                    target=target,
                    source="builtin",
                    source_ref=str(metadata.get("session_id") or self.session_id),
                    profile=self.profile,
                    confidence=0.95,
                    importance=0.8,
                    supersedes_id=old.fact_id if old else None,
                    metadata=metadata,
                )
            )
        elif action == "remove" and old_text:
            self.store.archive_matching(old_text, target=target)

    def on_delegation(
        self, task: str, result: str, *, child_session_id: str = "", **kwargs: Any
    ) -> None:
        return None

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        rewound: bool = False,
        **kwargs: Any,
    ) -> None:
        self.session_id = new_session_id

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        return ""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            REMEMBER_SCHEMA,
            RECALL_SCHEMA,
            STATUS_SCHEMA,
            REVISE_SCHEMA,
            FORGET_SCHEMA,
            FEEDBACK_SCHEMA,
        ]

    def _ensure_store(self) -> None:
        if not hasattr(self, "store") or self.store is None:
            try:
                from hermes_constants import get_hermes_home
                hermes_home = get_hermes_home()
            except Exception:
                hermes_home = Path.home() / ".hermes"
            self.database_path = hermes_home / "intelligent_memory" / "memory.db"
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile = getattr(self, "profile", "default") or "default"
            self.store = MemoryStore(self.database_path, profile=self.profile)

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        self._ensure_store()
        try:
            if tool_name == "intelligent_memory_remember":
                aliases_raw = args.get("aliases")
                aliases = (
                    tuple(str(value).strip() for value in aliases_raw if str(value).strip())
                    if isinstance(aliases_raw, list)
                    else ()
                )
                tags_raw = args.get("tags")
                tags = (
                    tuple(str(value).strip() for value in tags_raw if str(value).strip())
                    if isinstance(tags_raw, list)
                    else ()
                )
                project = str(args.get("project") or "").strip()
                result = self.store.remember(
                    FactInput(
                        content=str(args.get("content") or ""),
                        kind=str(args.get("kind") or "general"),
                        target=str(args.get("target") or "memory"),
                        project=project,
                        tags=tags,
                        aliases=aliases,
                        source="provider_tool",
                        source_ref=self.session_id,
                        profile=self.profile,
                        confidence=_number(args.get("confidence"), 0.9),
                        importance=_number(args.get("importance"), 0.7),
                    )
                )
                payload: dict[str, Any] = {
                    "success": True,
                    "done": True,
                    "fact_id": result.fact_id,
                    "created": result.created,
                }
                if result.conflict_fact is not None:
                    cf = result.conflict_fact
                    payload["conflict_detected"] = True
                    payload["warning"] = (
                        f"Conflict detected with active fact #{cf.fact_id}: '{cf.content}'"
                    )
                    payload["conflicting_fact"] = {
                        "fact_id": cf.fact_id,
                        "content": cf.content,
                        "project": cf.project,
                        "kind": cf.kind,
                    }
                    payload["suggestion"] = (
                        f"If this new fact supersedes fact #{cf.fact_id}, "
                        f"call intelligent_memory_revise(fact_id={cf.fact_id}, content=...)"
                    )
                return _json(payload)

            if tool_name == "intelligent_memory_recall":
                limit = max(1, min(50, int(args.get("limit") or self.max_recall_facts)))
                project_arg = str(args["project"]).strip() if args.get("project") else None
                kind_arg = str(args["kind"]).strip() if args.get("kind") else None
                target_arg = str(args["target"]).strip() if args.get("target") else None
                facts = self.store.search(
                    str(args.get("query") or ""),
                    target=target_arg,
                    project=project_arg,
                    kind=kind_arg,
                    limit=limit,
                )
                return _json(
                    {
                        "success": True,
                        "facts": [self._fact_payload(fact) for fact in facts],
                    }
                )

            if tool_name == "intelligent_memory_status":
                return _json(
                    {
                        "success": True,
                        "provider": self.name,
                        "profile": self.profile,
                        "active_facts": self.store.active_count(),
                        "cloud_mode": self.cloud_mode,
                        "last_cloud_error": self.last_cloud_error,
                    }
                )

            if tool_name == "intelligent_memory_revise":
                fact_id = _required_int(args.get("fact_id"))
                old = self.store.get_fact(fact_id)
                project = (
                    str(args["project"]).strip()
                    if args.get("project") is not None
                    else old.project
                )
                tags = (
                    tuple(str(v).strip() for v in args["tags"] if str(v).strip())
                    if isinstance(args.get("tags"), list)
                    else old.tags
                )
                result = self.store.remember(
                    FactInput(
                        content=str(args.get("content") or ""),
                        kind=old.kind,
                        target=old.target,
                        project=project,
                        tags=tags,
                        subject=old.subject,
                        predicate=old.predicate,
                        value=old.value,
                        aliases=old.aliases,
                        scope=old.scope,
                        source="provider_tool",
                        source_ref=self.session_id,
                        profile=self.profile,
                        confidence=old.confidence,
                        importance=old.importance,
                        supersedes_id=fact_id,
                    )
                )
                return _json({"success": True, "done": True, "fact_id": result.fact_id})

            if tool_name == "intelligent_memory_forget":
                fact_id = _required_int(args.get("fact_id"))
                self.store.archive(fact_id)
                return _json({"success": True, "done": True, "fact_id": fact_id})

            if tool_name == "intelligent_memory_feedback":
                fact_id = _required_int(args.get("fact_id"))
                fact = self.store.record_feedback(
                    fact_id, helpful=bool(args.get("helpful"))
                )
                return _json(
                    {
                        "success": True,
                        "done": True,
                        "fact_id": fact.fact_id,
                        "confidence": fact.confidence,
                    }
                )
            return _json({"success": False, "error": f"Unknown tool: {tool_name}"})
        except Exception as exc:
            return _json({"success": False, "error": str(exc)})

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "cloud_mode",
                "description": "Cloud intelligence mode",
                "default": "selective",
                "choices": ["off", "selective", "session"],
            }
        ]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        return None

    def shutdown(self) -> None:
        if not self._closed and hasattr(self, "store"):
            self.store.close()
            self._closed = True

    @staticmethod
    def _fact_payload(fact: Fact) -> dict[str, Any]:
        return {
            "fact_id": fact.fact_id,
            "content": fact.content,
            "kind": fact.kind,
            "target": fact.target,
            "project": fact.project,
            "tags": list(fact.tags),
            "confidence": fact.confidence,
            "importance": fact.importance,
            "source": fact.source,
        }


def register(ctx: Any) -> None:
    provider = IntelligentMemoryProvider()
    if hasattr(ctx, "register_memory_provider"):
        ctx.register_memory_provider(provider)

    tools = [
        ("intelligent_memory_remember", REMEMBER_SCHEMA),
        ("intelligent_memory_recall", RECALL_SCHEMA),
        ("intelligent_memory_status", STATUS_SCHEMA),
        ("intelligent_memory_revise", REVISE_SCHEMA),
        ("intelligent_memory_forget", FORGET_SCHEMA),
        ("intelligent_memory_feedback", FEEDBACK_SCHEMA),
    ]
    for name, schema in tools:
        if hasattr(ctx, "register_tool"):
            ctx.register_tool(
                name=name,
                toolset="memory",
                schema=schema,
                handler=lambda args, _name=name, **kw: provider.handle_tool_call(_name, args or {}, **kw),
            )


def _cloud_mode(value: Any) -> str:
    candidate = str(value or "selective").lower()
    return candidate if candidate in {"off", "selective", "session"} else "selective"


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _required_int(value: Any) -> int:
    if value is None:
        raise ValueError("missing required integer argument")
    return int(value)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _load_provider_config(hermes_home: Path) -> dict[str, Any]:
    candidates = (
        hermes_home / "config.yaml",
        hermes_home / "config.yml",
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            try:
                from ruamel.yaml import YAML
                yaml = YAML(typ="safe")
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.load(f)
            except ImportError:
                import yaml
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            if isinstance(data, dict):
                memory = data.get("memory")
                if isinstance(memory, dict):
                    settings = memory.get("intelligent_memory")
                    if isinstance(settings, dict):
                        return dict(settings)
        except Exception as exc:
            logger.warning("Could not parse config from %s: %s", path, exc)
    return {}
