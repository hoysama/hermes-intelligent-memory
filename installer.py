from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

EXCLUDED_NAMES = {"__pycache__", ".pytest_cache"}


@dataclass(frozen=True)
class InstallResult:
    destination: Path
    file_count: int
    manifest_sha256: str


def install_plugin(source: str | Path, hermes_home: str | Path) -> InstallResult:
    """Install the plugin atomically without touching its external data store."""
    source_path = Path(source).resolve()
    home = Path(hermes_home).resolve()
    destination = home / "plugins" / "intelligent_memory"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not (source_path / "plugin.yaml").is_file() or not (source_path / "__init__.py").is_file():
        raise ValueError(f"invalid plugin source: {source_path}")

    manifest = build_integrity_manifest(source_path)
    staging = Path(tempfile.mkdtemp(prefix=".intelligent_memory.", dir=destination.parent))
    previous = destination.with_name(destination.name + ".previous")
    try:
        _copy_tree(source_path, staging)
        (staging / "integrity.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        verify_integrity(staging, manifest)
        if previous.exists():
            shutil.rmtree(previous)
        if destination.exists():
            os.replace(destination, previous)
        os.replace(staging, destination)
        if previous.exists():
            shutil.rmtree(previous)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if previous.exists() and not destination.exists():
            os.replace(previous, destination)
        raise

    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    installed_files = manifest.get("files")
    if not isinstance(installed_files, dict):
        raise ValueError("invalid generated integrity manifest")
    return InstallResult(destination, len(installed_files), digest)


def build_integrity_manifest(source: str | Path) -> dict[str, object]:
    root = Path(source)
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in EXCLUDED_NAMES for part in path.parts):
            continue
        if path.name == "integrity.json":
            continue
        relative = path.relative_to(root).as_posix()
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"version": 1, "files": files}


def verify_integrity(root: str | Path, manifest: dict[str, object] | None = None) -> None:
    root_path = Path(root)
    if manifest is None:
        manifest = json.loads((root_path / "integrity.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("invalid integrity manifest")
    for relative, expected in files.items():
        path = root_path / str(relative)
        if not path.is_file():
            raise ValueError(f"missing plugin file: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"plugin integrity mismatch: {relative}")


def _copy_tree(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if any(part in EXCLUDED_NAMES for part in path.parts):
            continue
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
