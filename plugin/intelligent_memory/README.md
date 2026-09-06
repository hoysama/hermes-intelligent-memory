# Hermes Intelligent Memory

Standalone local-first MemoryProvider for Hermes Agent.

## Properties

- SQLite canonical fact store under the active `HERMES_HOME`
- Arabic/English normalization and hybrid lexical retrieval
- provenance, confidence, importance, lifecycle, and supersession
- staleness auto-archiving, epoch compression, and index vacuuming
- bounded per-turn recall without a local model
- optional selective cloud extraction through Hermes' configured provider
- standalone CLI for terminal search, multi-format export, and import
- self-healing diagnostics with automatic repair (`doctor.py --fix`)
- no API keys owned by this plugin

## Activation & Configuration

Copy this directory to `$HERMES_HOME/plugins/intelligent_memory`, then configure `~/.hermes/config.yaml`:

```yaml
memory:
  provider: intelligent_memory
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 35000  # Prevents false "memory full (X/2200)" lockouts
  user_char_limit: 35000
  intelligent_memory:
    cloud_mode: 'off'       # 'off' | 'selective' | 'session'
    max_recall_facts: 6
    max_recall_chars: 1800
    db_path: "$HERMES_HOME/intelligent_memory/memory.db"
```

Start a new Hermes process or session after activation.
