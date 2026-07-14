from __future__ import annotations

from pathlib import Path

import pytest

from installer import build_integrity_manifest, install_plugin, verify_integrity


def test_installer_is_atomic_and_data_is_outside_plugin_directory(tmp_path) -> None:
    project = Path(__file__).resolve().parents[1]
    source = project / "plugin" / "intelligent_memory"
    data_dir = tmp_path / "intelligent_memory"
    data_dir.mkdir()
    data_file = data_dir / "memory.db"
    data_file.write_bytes(b"persistent-data")

    result = install_plugin(source, tmp_path)
    second = install_plugin(source, tmp_path)

    assert result.destination == tmp_path / "plugins" / "intelligent_memory"
    assert second.destination == result.destination
    verify_integrity(result.destination)
    assert data_file.read_bytes() == b"persistent-data"
    assert not (result.destination / "memory.db").exists()


def test_integrity_verification_detects_update_or_corruption(tmp_path) -> None:
    project = Path(__file__).resolve().parents[1]
    source = project / "plugin" / "intelligent_memory"
    result = install_plugin(source, tmp_path)
    manifest = build_integrity_manifest(source)
    target = result.destination / "cloud.py"
    target.write_text("corrupted", encoding="utf-8")

    with pytest.raises(ValueError, match="integrity mismatch"):
        verify_integrity(result.destination, manifest)
