from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .geometry import Rect, Vec2


@dataclass(slots=True)
class AttachmentPoint:
    name: str
    x: float
    y: float

    def local_position(self, sprite: "Sprite") -> Vec2:
        return Vec2(self.x * sprite.rect.w, self.y * sprite.rect.h)


@dataclass(slots=True)
class Sprite:
    name: str
    rect: Rect
    points: dict[str, AttachmentPoint] = field(default_factory=dict)

    def point(self, name: str) -> AttachmentPoint:
        return self.points[name]

    def with_default_origin(self) -> "Sprite":
        if "origin" in self.points:
            return self
        clone = replace(self, points=dict(self.points))
        clone.points["origin"] = AttachmentPoint("origin", 0.5, 0.5)
        return clone


@dataclass(slots=True)
class SpriteSheet:
    image: str | None = None
    sprites: dict[str, Sprite] = field(default_factory=dict)


@dataclass(slots=True)
class Instance:
    name: str
    sprite: str
    parent: str | None = None
    parent_point: str | None = None
    self_point: str = "origin"
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    local_rotation: float = 0.0
    z: int = 0
    visible: bool = True
    locked: bool = False
    scale_x: float = 1.0
    scale_y: float = 1.0

    def is_root(self) -> bool:
        return self.parent is None


@dataclass(slots=True)
class Rig:
    instances: dict[str, Instance] = field(default_factory=dict)


ChannelKeyframes = dict[float, Any]


@dataclass(slots=True)
class Track:
    instance: str
    channels: dict[str, ChannelKeyframes] = field(default_factory=dict)
    # Per-channel interpolation. Missing means linear. Numeric channels support easing; sprite/visible are sampled as step.
    interpolation: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Clip:
    name: str
    length: float
    fps: float = 24.0
    loop: bool = True
    tracks: dict[str, Track] = field(default_factory=dict)


@dataclass(slots=True)
class Project:
    sheet: SpriteSheet = field(default_factory=SpriteSheet)
    rig: Rig = field(default_factory=Rig)
    clips: dict[str, Clip] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def sprite(self, name: str) -> Sprite:
        return self.sheet.sprites[name]

    def instance(self, name: str) -> Instance:
        return self.rig.instances[name]

    def clone_with_instance(self, instance: Instance) -> "Project":
        new = Project(self.sheet, Rig(dict(self.rig.instances)), dict(self.clips), dict(self.metadata))
        new.rig.instances[instance.name] = instance
        return new
