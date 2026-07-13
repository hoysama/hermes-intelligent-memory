# Threat Model

## Assets

- User identity and preferences
- Project and environment facts
- Conversation-derived decisions
- Provider credentials and secrets
- Cross-profile isolation
- Prompt integrity

## Threats And Controls

### Persistent prompt injection

Memory content is untrusted data. New content is scanned with Hermes strict threat patterns when available. Recalled context is fenced as data, stripped of instruction-like markup, length-bounded, and never inserted into the stable identity tier.

### Secret leakage to cloud intelligence

Cloud calls are opt-in by mode. Inputs are candidate facts only, never raw databases, `.env` files, full terminal output, or unrestricted tool results. Secret-like values and high-entropy tokens are redacted before transmission. Calls have character and count budgets and local audit metadata.

### Provenance poisoning

Every fact records source, source reference, profile, session, and timestamps. Assistant-inferred facts start below explicit user statements in confidence. Tool output is never promoted to global user preference without explicit confirmation.

### Cross-profile bleed

All paths derive from the `hermes_home` argument passed to `initialize`. The database stores a profile scope key and rejects writes whose runtime profile differs from the opened store.

### Stale conflicts

Facts are not overwritten silently. A correction supersedes the old fact. Retrieval excludes superseded facts by default and can surface conflict history for audit.

### Concurrent SQLite access

SQLite uses WAL where supported, foreign keys, busy timeout, short transactions, and a process-local re-entrant lock. A WAL fallback keeps the provider usable on incompatible filesystems.

### Projection corruption

Projection files are written under a lock with backup, drift check, budget validation, and atomic replace. A failed write leaves the previous file intact.

### Denial of service

Recall has hard result and character limits. Cloud work is off the turn-critical path, time-bounded, rate-limited, cached, and fail-open to deterministic local behavior.
