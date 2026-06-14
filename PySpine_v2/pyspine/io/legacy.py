from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pyspine.core.geometry import Rect
from pyspine.core.model import AttachmentPoint, Clip, Instance, Project, Rig, Sprite, SpriteSheet, Track
from pyspine.core.validation import validate_project


def load_legacy_bundle(
    sprite_path: str | Path,
    assembly_path: str | Path | None = None,
    animation_path: str | Path | None = None,
    *,
    image: str | None = None,
    angle_mode: str = "degrees",
) -> Project:
    """Best-effort importer for the old multi-file prototype format.

    This module intentionally does not preserve old editor UI state. It only maps the core concepts
    into the strict v2 model. `angle_mode` may be "degrees" or "radians".
    """

    if angle_mode not in {"degrees", "radians"}:
        raise ValueError("angle_mode must be 'degrees' or 'radians'")

    factor = 57.29577951308232 if angle_mode == "radians" else 1.0
    sprites = _read_legacy_sprites(Path(sprite_path), image=image)
    instances: dict[str, Instance] = {}
    clips: dict[str, Clip] = {}

    if assembly_path is not None:
        raw = json.loads(Path(assembly_path).read_text(encoding="utf-8"))
        for item in raw.get("instances", []):
            inst = Instance(
                name=str(item["name"]),
                sprite=str(item["sprite_name"]),
                parent=item.get("parent"),
                parent_point=item.get("parent_point"),
                self_point=str(item.get("self_point") or "origin"),
                x=float(item.get("root_x", 0.0)),
                y=float(item.get("root_y", 0.0)),
                rotation=float(item.get("rotation", 0.0)) * factor,
                local_rotation=float(item.get("local_rotation", 0.0)) * factor,
            )
            instances[inst.name] = inst

    if animation_path is not None:
        raw = json.loads(Path(animation_path).read_text(encoding="utf-8"))
        for clip_data in raw.get("animations", []):
            tracks: dict[str, Track] = {}
            for inst_name, channels in clip_data.get("tracks", {}).items():
                converted: dict[str, dict[float, float]] = {}
                for channel, keys in channels.items():
                    new_channel = {"root_x": "x", "root_y": "y"}.get(channel, channel)
                    scale = factor if new_channel in {"rotation", "local_rotation"} else 1.0
                    converted[new_channel] = {float(frame): float(value) * scale for frame, value in keys.items()}
                tracks[inst_name] = Track(instance=inst_name, channels=converted)
            clip = Clip(
                name=str(clip_data.get("name", "legacy_clip")),
                length=float(clip_data.get("length", 1.0)),
                fps=float(clip_data.get("fps", 24.0)),
                tracks=tracks,
            )
            clips[clip.name] = clip

    project = Project(sheet=sprites, rig=Rig(instances), clips=clips, metadata={"imported_from": "legacy"})
    validate_project(project, strict=False)
    return project


def _read_legacy_sprites(path: Path, *, image: str | None) -> SpriteSheet:
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw.get("data", raw)
    sprite_items: dict[str, Any] = data.get("sprites", {})
    sprites: dict[str, Sprite] = {}
    for key, item in sprite_items.items():
        name = str(item.get("name", key))
        points: dict[str, AttachmentPoint] = {}
        for point in item.get("attachment_points", []):
            p = AttachmentPoint(str(point["name"]), float(point["x"]), float(point["y"]))
            points[p.name] = p
        if "origin" not in points and "origin_x" in item and "origin_y" in item:
            points["origin"] = AttachmentPoint("origin", float(item["origin_x"]), float(item["origin_y"]))
        if "endpoint" not in points and "endpoint_x" in item and "endpoint_y" in item:
            points["endpoint"] = AttachmentPoint("endpoint", float(item["endpoint_x"]), float(item["endpoint_y"]))
        if "origin" not in points:
            points["origin"] = AttachmentPoint("origin", 0.5, 0.5)
        sprite = Sprite(
            name=name,
            rect=Rect(float(item["x"]), float(item["y"]), float(item["width"]), float(item["height"])),
            points=points,
        )
        sprites[name] = sprite
    return SpriteSheet(image=image, sprites=sprites)
