from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from pyspine.io.jsonio import load_project, project_to_dict

RUNTIME_FORMAT = "pyspine.runtime"
RUNTIME_VERSION = 1
BUNDLE_FORMAT = "pyspine.bundle"
BUNDLE_VERSION = 1


def export_runtime_json(project_path: str | Path, output_json: str | Path, *, asset_prefix: str = "assets") -> Path:
    """Write a normalized runtime JSON file.

    Runtime JSON is deliberately close to the authoring format, but it records the
    image under metadata.runtime.image so simple game runtimes can find assets
    without understanding editor-only path layout decisions.
    """

    project_path = Path(project_path)
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    project = load_project(project_path)
    data = project_to_dict(project)
    metadata: dict[str, Any] = dict(data.get("metadata", {}))
    image_name = Path(project.sheet.image).name if project.sheet.image else None
    metadata["runtime"] = {
        "format": RUNTIME_FORMAT,
        "version": RUNTIME_VERSION,
        "image": f"{asset_prefix}/{image_name}" if image_name else None,
        "coordinate_system": "y_down_degrees_clockwise",
        "channels": ["x", "y", "rotation", "local_rotation", "visible"],
    }
    data["metadata"] = metadata
    output_json.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")
    return output_json


def export_packed_bundle(project_path: str | Path, output: str | Path, *, as_zip: bool | None = None) -> Path:
    """Export a standalone runtime bundle.

    If output ends in .zip, a zip bundle is written. Otherwise output is treated as
    a directory. The bundle contains:
      manifest.json
      project.runtime.json
      assets/<sprite-sheet-file>
    """

    project_path = Path(project_path)
    output = Path(output)
    if as_zip is None:
        as_zip = output.suffix.lower() == ".zip"

    if as_zip:
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = output.parent / (output.stem + "_bundle_tmp")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        try:
            _write_bundle_dir(project_path, temp_dir)
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(temp_dir.rglob("*")):
                    if path.is_file():
                        zf.write(path, path.relative_to(temp_dir).as_posix())
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        return output

    _write_bundle_dir(project_path, output)
    return output


def _write_bundle_dir(project_path: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    project = load_project(project_path)

    image_ref = project.sheet.image
    copied_image: str | None = None
    if image_ref:
        source_image = Path(image_ref)
        if not source_image.is_absolute():
            source_image = project_path.parent / source_image
        if not source_image.exists():
            raise FileNotFoundError(f"sprite sheet image not found: {source_image}")
        copied_image = f"assets/{source_image.name}"
        shutil.copy2(source_image, output_dir / copied_image)
        project.sheet.image = copied_image

    runtime_json = output_dir / "project.runtime.json"
    runtime_json.write_text(json.dumps(project_to_dict(project), indent=2, sort_keys=False), encoding="utf-8")
    manifest = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "project": "project.runtime.json",
        "image": copied_image,
        "clips": sorted(project.clips.keys()),
        "sprites": len(project.sheet.sprites),
        "instances": len(project.rig.instances),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=False), encoding="utf-8")
