from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERMES_SOURCE = Path(
    os.environ.get(
        "HERMES_SOURCE",
        "C:/Users/HoySa/AppData/Local/hermes/hermes-agent",
    )
)
HERMES_PYTHON = HERMES_SOURCE / "venv" / "Scripts" / "python.exe"


@pytest.mark.skipif(
    not HERMES_SOURCE.exists() or not HERMES_PYTHON.exists(),
    reason="Hermes Windows runtime is required",
)
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
provider.initialize('s1', hermes_home=r'__HOME__', platform='cli', agent_identity='default')
from hermes_cli.plugins import get_plugin_auxiliary_tasks
assert any(item['key'] == 'intelligent_memory' for item in get_plugin_auxiliary_tasks())
provider.shutdown()
print('DISCOVERY_OK')
""".replace('__HOME__', str(tmp_path).replace('\\', '\\\\'))
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(HERMES_SOURCE)
    completed = subprocess.run(
        [str(HERMES_PYTHON), "-c", script],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "DISCOVERY_OK" in completed.stdout
