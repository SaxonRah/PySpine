from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pyspine.io.jsonio import load_project
from pyspine.core.model import Project


@dataclass(slots=True)
class RuntimeBundle:
    project: Project
    root: Path
    manifest: dict
    _tempdir: tempfile.TemporaryDirectory[str] | None = None

    def close(self) -> None:
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None

    def __enter__(self) -> "RuntimeBundle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def load_runtime_bundle(path: str | Path) -> RuntimeBundle:
    path = Path(path)
    temp: tempfile.TemporaryDirectory[str] | None = None
    root = path
    if path.is_file() and path.suffix.lower() == ".zip":
        temp = tempfile.TemporaryDirectory(prefix="pyspine_bundle_")
        root = Path(temp.name)
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(root)

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"bundle manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    project_ref = manifest.get("project", "project.runtime.json")
    project = load_project(root / project_ref)
    return RuntimeBundle(project=project, root=root, manifest=manifest, _tempdir=temp)
