# Intelligent Memory Architecture

## Goal

Build a standalone Hermes MemoryProvider that combines a bounded always-on projection with deep, scoped recall. The canonical SQLite store is the source of truth. `MEMORY.md` and `USER.md` remain compatible Hermes projections, not competing databases.

## Constraints

- No Hermes core edits.
- No local language or embedding model.
- Local deterministic read/write and retrieval must work when cloud inference fails.
- Cloud inference is selective and never blocks a normal Hermes turn.
- Arabic and mixed Arabic/English content are first-class.
- Storage is profile-scoped under the active `HERMES_HOME`.
- Existing Built-in and Holographic data must be migratable and rollback-safe.

## Data Flow

1. Hermes starts the provider through `memory.provider: intelligent_memory`.
2. The provider opens `$HERMES_HOME/intelligent_memory/memory.db` in WAL mode.
3. Existing Built-in entries are imported idempotently with source provenance.
4. `system_prompt_block()` emits only stable provider guidance and status.
5. `prefetch(query)` performs bounded local hybrid retrieval and returns active facts only.
6. Explicit memory tools write structured facts into the canonical store.
7. Built-in `memory` writes are mirrored through `on_memory_write`, including add, replace, and remove semantics.
8. Session-end extraction may use Hermes' cloud auxiliary client in selective mode; failures are queued and never block shutdown.
9. High-confidence, high-importance global facts are materialized into bounded `MEMORY.md` and `USER.md` projections using atomic writes and backups.

## Retrieval

Candidate generation:

- normalized exact hash
- FTS5/BM25 when available
- normalized token overlap
- character trigrams for Arabic and mixed-language substring recall
- aliases and structured subject/predicate/object fields

Ranking:

- lexical relevance
- scope match
- confidence
- importance
- freshness
- explicit feedback
- status filtering

Cloud inference is not on the hot retrieval path. It is reserved for ambiguous extraction, deduplication, conflict classification, and optional reranking of a small candidate set.

## Memory Lifecycle

Facts are immutable records with lifecycle links:

- `active`: eligible for recall
- `superseded`: replaced by a newer fact
- `archived`: deliberately forgotten from active recall
- `rejected`: blocked by validation or security policy

Updates create a new active fact and link the old fact through `supersedes_id`. Provenance remains append-only.

Tiering and maintenance operations:
- `archive_stale()`: automated aging and isolation of stale or negatively evaluated facts.
- `compress_archived()`: epoch compression rolling up historical archived entries into structured summary facts.
- `vacuum()`: B-tree defragmentation, inverted FTS index optimization, and page recovery.

## Hermes Integration

The provider implements the official `MemoryProvider` lifecycle:

- `initialize`
- `system_prompt_block`
- `prefetch`
- `sync_turn`
- `on_session_end`
- `on_pre_compress`
- `on_memory_write`
- `on_delegation`
- `on_session_switch`
- `shutdown`

Provider tools are kept narrow: remember, recall, revise, forget, feedback, and status.

## Diagnostic & CLI Administration

- **Self-Healing Diagnostics (`doctor.py`)**: Automatic verification of plugin integrity, runtime discovery, SQLite health, automatic index reconstruction (`facts_fts`), and missing projection view regeneration (`MEMORY.md` / `USER.md`) with `--fix`.
- **Administrative CLI (`intelligent_memory.cli`)**: Native commands for `status`, `migrate`, `project`, `rollback`, direct semantic terminal `search`, multi-format `export` (JSON, JSON-LD, Markdown), and batch `import`.
