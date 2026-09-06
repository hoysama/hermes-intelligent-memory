from __future__ import annotations

from pathlib import Path

from doctor import run_doctor
from installer import install_plugin

HERMES_SOURCE = Path("C:/Users/HoySa/AppData/Local/hermes/hermes-agent")


def test_doctor_detects_installed_plugin_and_database(tmp_path) -> None:
    project = Path(__file__).resolve().parents[1]
    install_plugin(project / "plugin" / "intelligent_memory", tmp_path)

    result = run_doctor(tmp_path, hermes_source=HERMES_SOURCE)

    assert result.healthy is HERMES_SOURCE.exists()
    assert result.integrity is True
    assert result.database is True


def test_doctor_detects_deleted_plugin_after_update(tmp_path) -> None:
    result = run_doctor(tmp_path, hermes_source=HERMES_SOURCE)

    assert result.healthy is False
    assert result.integrity is False
    assert any("integrity" in detail for detail in result.details)


def test_doctor_fix_rebuilds_projections_and_indices(tmp_path) -> None:
    from intelligent_memory.core.models import FactInput
    from intelligent_memory.core.store import MemoryStore

    project = Path(__file__).resolve().parents[1]
    install_plugin(project / "plugin" / "intelligent_memory", tmp_path)

    db_path = tmp_path / "intelligent_memory" / "memory.db"
    store = MemoryStore(db_path, profile="default")
    store.remember(FactInput(content="Test fact for doctor recovery", source="user"))
    store.close()

    # Verify MEMORY.md does not exist yet
    memory_md = tmp_path / "memories" / "MEMORY.md"
    assert not memory_md.exists()

    # Run doctor with fix=True
    result = run_doctor(tmp_path, hermes_source=HERMES_SOURCE, fix=True)
    assert memory_md.exists()
    assert "Test fact for doctor recovery" in memory_md.read_text(encoding="utf-8")
    assert any("Rebuilt projections" in fix for fix in result.fixes)
    assert any("facts_fts" in fix for fix in result.fixes)


def test_doctor_fix_restores_plugin_when_source_provided(tmp_path) -> None:
    project = Path(__file__).resolve().parents[1]
    plugin_source = project / "plugin" / "intelligent_memory"

    # Initially not installed
    result = run_doctor(
        tmp_path,
        hermes_source=HERMES_SOURCE,
        fix=True,
        plugin_source=plugin_source,
    )
    assert result.integrity is True
    assert any("Restored plugin files" in fix for fix in result.fixes)
