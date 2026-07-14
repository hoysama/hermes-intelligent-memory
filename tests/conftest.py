from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "plugin"
for path in (PROJECT_ROOT, PLUGIN_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
