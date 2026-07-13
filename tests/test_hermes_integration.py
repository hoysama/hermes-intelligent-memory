from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERMES_SOURCE = Path(
    os.environ.get(
        "HERMES_SOURCE",
        "C:/Users/HoySa/AppData/Local/hermes/hermes-agent",
    )
)


@pytest.mark.skipif(not HERMES_SOURCE.exists(), reason="Hermes source checkout is required")
def test_real_hermes_user_plugin_discovery(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    plugin_source = project_root / "plugin" / "intelligent_memory"
    plugin_target = tmp_path / "plugins" / "intelligent_memory"
    shutil.copytree(plugin_source, plugin_target)

    script = """
from plugins.memory import discover_memory_providers, load_memory_provider
names = {name: available for name, _desc, available in discover_memory_providers()}
provider = load_memory_provider('intelligent_memory')
assert names.get('intelligent_memory') is True, names
assert provider is not None
assert provider.name == 'intelligent_memory'
print('DISCOVERY_OK')
"""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(HERMES_SOURCE)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "DISCOVERY_OK" in completed.stdout
