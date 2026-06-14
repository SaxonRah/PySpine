from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from pathlib import Path
from typing import Iterable

from pyspine.core.animation import solve_clip_pose
from pyspine.core.geometry import Vec2, rotate
from pyspine.core.model import Project
from pyspine.core.solver import Pose, solve_pose


@dataclass(frozen=True, slots=True)
class Bounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return max(0.0, self.max_x - self.min_x)

    @property
    def height(self) -> float:
        return max(0.0, self.max_y - self.min_y)

    def union(self, other: "Bounds") -> "Bounds":
        return Bounds(
            min(self.min_x, other.min_x),
            min(self.min_y, other.min_y),
            max(self.max_x, other.max_x),
            max(self.max_y, other.max_y),
        )

    def expanded(self, margin: float) -> "Bounds":
        return Bounds(self.min_x - margin, self.min_y - margin, self.max_x + margin, self.max_y + margin)


def pose_bounds(project: Project, poses: dict[str, Pose]) -> Bounds:
    xs: list[float] = []
    ys: list[float] = []
    for pose in poses.values():
        if not pose.visible:
            continue
        sprite = project.sheet.sprites[pose.sprite]
        for corner in sprite.rect.corners():
            p = pose.local_to_world(corner)
            xs.append(p.x)
            ys.append(p.y)
    if not xs:
        return Bounds(0.0, 0.0, 1.0, 1.0)
    return Bounds(min(xs), min(ys), max(xs), max(ys))


def clip_bounds(project: Project, clip: str, frames: Iterable[float]) -> Bounds:
    bounds: Bounds | None = None
    for frame in frames:
        current = pose_bounds(project, solve_clip_pose(project, clip, frame))
        bounds = current if bounds is None else bounds.union(current)
    if bounds is None:
        return pose_bounds(project, solve_pose(project))
    return bounds


class PillowRenderer:
    """Pillow-based offline renderer for exports.

    This keeps export/rendering independent from pygame and the editor. It uses the
    same solved Pose data as the live runtime so exported PNG/GIF frames match the
    animation system.
    """

    def __init__(self, project: Project, project_path: str | Path | None = None):
        try:
            from PIL import Image  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised only when Pillow is missing
            raise RuntimeError("Pillow is required for image export: pip install Pillow") from exc

        self.Image = Image
        self.project = project
        self.project_path = Path(project_path) if project_path is not None else None
        self.sheet_image = self._load_sheet_image()
        self._sprite_cache: dict[str, object] = {}

    def render_rest(self, *, margin: int = 8, bounds: Bounds | None = None, background=(0, 0, 0, 0)):
        return self.render_poses(solve_pose(self.project), margin=margin, bounds=bounds, background=background)

    def render_clip_frame(self, clip: str, frame: float, *, margin: int = 8, bounds: Bounds | None = None, background=(0, 0, 0, 0)):
        return self.render_poses(solve_clip_pose(self.project, clip, frame), margin=margin, bounds=bounds, background=background)

    def render_poses(self, poses: dict[str, Pose], *, margin: int = 8, bounds: Bounds | None = None, background=(0, 0, 0, 0)):
        if bounds is None:
            bounds = pose_bounds(self.project, poses).expanded(margin)
            offset = Vec2(-bounds.min_x, -bounds.min_y)
        else:
            bounds = bounds.expanded(margin)
            offset = Vec2(-bounds.min_x, -bounds.min_y)

        width = max(1, int(ceil(bounds.width)))
        height = max(1, int(ceil(bounds.height)))
        target = self.Image.new("RGBA", (width, height), background)

        for pose in sorted(poses.values(), key=lambda p: (p.z, p.instance)):
            if not pose.visible:
                continue
            self._paste_pose(target, pose, offset)
        return target

    def _paste_pose(self, target, pose: Pose, offset: Vec2) -> None:
        sprite = self.project.sheet.sprites[pose.sprite]
        crop = self._sprite_image(pose.sprite)
        if crop is None:
            return
        # The geometry system treats positive degrees as clockwise on a y-down
        # screen. PIL uses the conventional image rotate direction, so negate the
        # angle to match the live pygame renderer.
        if abs(pose.scale_x - 1.0) > 1.0e-6 or abs(pose.scale_y - 1.0) > 1.0e-6:
            crop = crop.resize((max(1, int(round(crop.size[0] * abs(pose.scale_x)))), max(1, int(round(crop.size[1] * abs(pose.scale_y))))), self.Image.Resampling.BICUBIC)
        rotated = crop.rotate(-pose.rotation, expand=True, resample=self.Image.Resampling.BICUBIC)
        corners = [pose.local_to_world(c) for c in sprite.rect.corners()]
        center = Vec2(sum(c.x for c in corners) / 4.0, sum(c.y for c in corners) / 4.0) + offset
        left = int(round(center.x - rotated.size[0] / 2.0))
        top = int(round(center.y - rotated.size[1] / 2.0))
        target.alpha_composite(rotated, (left, top))

    def _sprite_image(self, sprite_name: str):
        if self.sheet_image is None:
            return None
        cached = self._sprite_cache.get(sprite_name)
        if cached is not None:
            return cached
        sprite = self.project.sheet.sprites[sprite_name]
        box = (
            int(floor(sprite.rect.x)),
            int(floor(sprite.rect.y)),
            int(ceil(sprite.rect.x + sprite.rect.w)),
            int(ceil(sprite.rect.y + sprite.rect.h)),
        )
        crop = self.sheet_image.crop(box).convert("RGBA")
        self._sprite_cache[sprite_name] = crop
        return crop

    def _load_sheet_image(self):
        image_ref = self.project.sheet.image
        if not image_ref:
            return None
        path = Path(image_ref)
        if not path.is_absolute() and self.project_path is not None:
            path = self.project_path.parent / path
        if not path.exists():
            raise FileNotFoundError(f"sprite sheet image not found: {path}")
        return self.Image.open(path).convert("RGBA")
