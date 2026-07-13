# ADR 0001: Canonical Store With Built-in Projections

- Status: Accepted
- Date: 2026-07-13
- Decision version: 1.0.0

## Context

Hermes Built-in memory guarantees bounded always-on context but has limited capacity. Holographic adds deeper local recall but duplicates Built-in additions and does not faithfully propagate replace/remove operations. Running both as independent sources permits stale conflicts and repeated context.

## Decision

Use one profile-scoped SQLite database as the canonical memory store. Treat `MEMORY.md` and `USER.md` as bounded materialized projections containing only active, high-confidence, high-importance facts that must be present in every session.

The provider will import existing Built-in and Holographic data with provenance. It will never delete source files during migration. Projection writes require an on-disk backup, file lock, deterministic rendering, character-budget enforcement, and atomic replacement.

## Consequences

- Hermes keeps its reliable Built-in system-prompt injection.
- Deep facts are recalled only when relevant.
- Replace/remove operations have explicit lifecycle semantics.
- Projection drift and external edits must be detected and reconciled.
- The canonical database becomes the backup/restore authority after migration.

## Reversal

Disable the provider and restore the latest projection backup. Source Built-in files and imported Holographic database are retained, so rollback does not require reconstructing user data.
