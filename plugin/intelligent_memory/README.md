# Hermes Intelligent Memory

Standalone local-first MemoryProvider for Hermes Agent.

## Properties

- SQLite canonical fact store under the active `HERMES_HOME`
- Arabic/English normalization and hybrid lexical retrieval
- provenance, confidence, importance, lifecycle, and supersession
- bounded per-turn recall without a local model
- optional selective cloud extraction through Hermes' configured provider
- no API keys owned by this plugin

## Activation

Copy this directory to `$HERMES_HOME/plugins/intelligent_memory`, then run:

```bash
hermes config set memory.provider intelligent_memory
```

Start a new Hermes process or session after activation.
