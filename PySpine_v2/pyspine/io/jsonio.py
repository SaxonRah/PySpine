from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pyspine.core.geometry import Rect
from pyspine.core.model import AttachmentPoint, Clip, Instance, Project, Rig, Sprite, SpriteSheet, Track
from pyspine.core.validation import validate_project

FORMAT = "pyspine.project"
VERSION = 1


def load_project(path: str | Path, *, validate: bool = True) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    project = project_from_dict(data)
    if validate:
        validate_project(project)
    return project


def save_project(project: Project, path: str | Path, *, indent: int = 2) -> None:
    validate_project(project)
    Path(path).write_text(json.dumps(project_to_dict(project), indent=indent, sort_keys=False), encoding="utf-8")


def project_from_dict(data: dict[str, Any]) -> Project:
    if data.get("format") != FORMAT:
        raise ValueError(f"not a {FORMAT} file")
    if int(data.get("version", 0)) != VERSION:
        raise ValueError(f"unsupported project version {data.get('version')!r}")

    sheet_data = data.get("sheet", {})
    sprites: dict[str, Sprite] = {}
    for s in sheet_data.get("sprites", []):
        rect = Rect(*map(float, s["rect"]))
        points = {
            name: AttachmentPoint(str(name), float(pos[0]), float(pos[1]))
            for name, pos in s.get("points", {}).items()
        }
        sprite = Sprite(name=str(s["name"]), rect=rect, points=points)
        sprites[sprite.name] = sprite

    instances: dict[str, Instance] = {}
    for i in data.get("rig", {}).get("instances", []):
        inst = Instance(
            name=str(i["name"]),
            sprite=str(i["sprite"]),
            parent=i.get("parent"),
            parent_point=i.get("parent_point"),
            self_point=str(i.get("self_point", "origin")),
            x=float(i.get("x", 0.0)),
            y=float(i.get("y", 0.0)),
            rotation=float(i.get("rotation", 0.0)),
            local_rotation=float(i.get("local_rotation", 0.0)),
            z=int(i.get("z", 0)),
            visible=bool(i.get("visible", True)),
            locked=bool(i.get("locked", False)),
            scale_x=float(i.get("scale_x", 1.0)),
            scale_y=float(i.get("scale_y", 1.0)),
        )
        instances[inst.name] = inst

    clips: dict[str, Clip] = {}
    for c in data.get("clips", []):
        tracks: dict[str, Track] = {}
        interpolation_data = c.get("interpolation", {})
        for inst_name, channels in c.get("tracks", {}).items():
            normalized_channels: dict[str, dict[float, object]] = {}
            for channel, raw_keys in channels.items():
                if channel == "sprite":
                    normalized_channels[channel] = {float(frame): str(value) for frame, value in raw_keys.items()}
                else:
                    normalized_channels[channel] = {float(frame): float(value) for frame, value in raw_keys.items()}
            inst_interp = dict(interpolation_data.get(inst_name, {})) if isinstance(interpolation_data, dict) else {}
            tracks[inst_name] = Track(instance=inst_name, channels=normalized_channels, interpolation={str(k): str(v) for k, v in inst_interp.items()})
        clip = Clip(
            name=str(c["name"]),
            length=float(c["length"]),
            fps=float(c.get("fps", 24.0)),
            loop=bool(c.get("loop", True)),
            tracks=tracks,
        )
        clips[clip.name] = clip

    return Project(
        sheet=SpriteSheet(image=sheet_data.get("image"), sprites=sprites),
        rig=Rig(instances=instances),
        clips=clips,
        metadata=dict(data.get("metadata", {})),
    )


def project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": VERSION,
        "metadata": dict(project.metadata),
        "sheet": {
            "image": project.sheet.image,
            "sprites": [
                {
                    "name": sprite.name,
                    "rect": [sprite.rect.x, sprite.rect.y, sprite.rect.w, sprite.rect.h],
                    "points": {name: [point.x, point.y] for name, point in sprite.points.items()},
                }
                for sprite in sorted(project.sheet.sprites.values(), key=lambda s: s.name)
            ],
        },
        "rig": {
            "instances": [
                {
                    "name": inst.name,
                    "sprite": inst.sprite,
                    "parent": inst.parent,
                    "parent_point": inst.parent_point,
                    "self_point": inst.self_point,
                    "x": inst.x,
                    "y": inst.y,
                    "rotation": inst.rotation,
                    "local_rotation": inst.local_rotation,
                    "z": inst.z,
                    "visible": inst.visible,
                    "locked": inst.locked,
                    "scale_x": inst.scale_x,
                    "scale_y": inst.scale_y,
                }
                for inst in sorted(project.rig.instances.values(), key=lambda i: (i.z, i.name))
            ]
        },
        "clips": [
            {
                "name": clip.name,
                "length": clip.length,
                "fps": clip.fps,
                "loop": clip.loop,
                "tracks": {
                    inst_name: {
                        channel: {str(frame): value for frame, value in sorted(keys.items())}
                        for channel, keys in track.channels.items()
                    }
                    for inst_name, track in sorted(clip.tracks.items())
                },
                "interpolation": {
                    inst_name: dict(track.interpolation)
                    for inst_name, track in sorted(clip.tracks.items())
                    if track.interpolation
                },
            }
            for clip in sorted(project.clips.values(), key=lambda c: c.name)
        ],
    }
