from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .geometry import Vec2, rotate
from .model import Instance, Project, Sprite
from .validation import validate_project


@dataclass(frozen=True, slots=True)
class Pose:
    instance: str
    sprite: str
    anchor: Vec2
    top_left: Vec2
    rotation: float
    z: int
    visible: bool
    scale_x: float = 1.0
    scale_y: float = 1.0
    points: dict[str, Vec2] = None  # type: ignore[assignment]

    def scaled_local(self, v: Vec2) -> Vec2:
        return Vec2(v.x * self.scale_x, v.y * self.scale_y)

    def local_to_world(self, v: Vec2) -> Vec2:
        return self.top_left + rotate(self.scaled_local(v), self.rotation)

    def point(self, name: str) -> Vec2:
        return self.points[name]


OverrideMap = Mapping[str, Mapping[str, object]]


def solve_pose(project: Project, overrides: OverrideMap | None = None, *, strict: bool = True) -> dict[str, Pose]:
    """Compute world-space pose for every instance.

    The solver is deterministic and iterative. Each instance is solved after its parent.
    Root instance x/y are the world coordinates of its own self_point/pivot.
    Child instance pivot is constrained to its parent's named attachment point.
    """

    validate_project(project, strict=strict)
    order = _topological_order(project)
    poses: dict[str, Pose] = {}
    overrides = overrides or {}

    for name in order:
        inst = project.rig.instances[name]
        ov = overrides.get(name, {})
        requested_sprite_name = str(ov.get("sprite", inst.sprite))
        sprite_name = _compatible_sprite_name(project, inst, requested_sprite_name)
        sprite = project.sheet.sprites[sprite_name]
        visible = bool(ov.get("visible", inst.visible))

        scale_x = float(ov.get("scale_x", inst.scale_x))
        scale_y = float(ov.get("scale_y", inst.scale_y))

        if inst.parent is None:
            anchor = Vec2(float(ov.get("x", inst.x)), float(ov.get("y", inst.y)))
            world_rot = float(ov.get("rotation", inst.rotation)) + float(ov.get("local_rotation", inst.local_rotation))
        else:
            parent_pose = poses[inst.parent]
            assert inst.parent_point is not None
            # Normal attached children are hard-constrained to the parent point.
            # Child x/y are ignored unless the specific attachment point has been
            # marked breakable in project metadata AND this frame keys
            # break_attach=true.  This preserves the whole point of attachment
            # rigs while still allowing deliberate animated breaks later.
            anchor = parent_pose.point(inst.parent_point)
            if _attachment_break_enabled(project, inst, ov):
                local_offset = Vec2(float(ov.get("x", inst.x)), float(ov.get("y", inst.y)))
                anchor = anchor + rotate(local_offset, parent_pose.rotation)
            world_rot = parent_pose.rotation + float(ov.get("local_rotation", inst.local_rotation))

        self_local = _scale(sprite.point(inst.self_point).local_position(sprite), scale_x, scale_y)
        top_left = anchor - rotate(self_local, world_rot)
        points = _world_points(sprite, top_left, world_rot, scale_x, scale_y)
        poses[name] = Pose(
            instance=name,
            sprite=sprite_name,
            anchor=anchor,
            top_left=top_left,
            rotation=world_rot,
            z=inst.z,
            visible=visible,
            scale_x=scale_x,
            scale_y=scale_y,
            points=points,
        )

    return poses



def sprite_swap_problem(project: Project, instance_name: str, sprite_name: str) -> str | None:
    """Return a user-facing incompatibility reason for a per-frame sprite swap.

    Sprite swaps are safe only when the replacement sprite provides the selected
    instance's own attachment point and every point that existing children use
    to attach to this instance.  Otherwise the swap would detach the rig graph.
    The solver falls back to the rig-pose sprite for unsafe swaps; editor code
    should call this helper and show the reason before writing the keyframe.
    """

    if instance_name not in project.rig.instances:
        return f"missing instance {instance_name!r}"
    inst = project.rig.instances[instance_name]
    if sprite_name not in project.sheet.sprites:
        return f"missing sprite {sprite_name!r}"
    sprite = project.sheet.sprites[sprite_name]
    if inst.self_point not in sprite.points:
        return f"{sprite_name!r} is missing self attachment point {inst.self_point!r}"
    missing_child_points = sorted(
        child.parent_point
        for child in project.rig.instances.values()
        if child.parent == instance_name and child.parent_point and child.parent_point not in sprite.points
    )
    if missing_child_points:
        points = ", ".join(repr(p) for p in missing_child_points)
        return f"{sprite_name!r} is missing child attachment point(s): {points}"
    return None


def _compatible_sprite_name(project: Project, inst: Instance, requested_sprite_name: str) -> str:
    if requested_sprite_name == inst.sprite:
        return inst.sprite
    if sprite_swap_problem(project, inst.name, requested_sprite_name) is None:
        return requested_sprite_name
    # Runtime/export fallback: bad sprite-swap keyframes should not crash or
    # destroy attachments.  Keep the rig-pose sprite for this frame.
    return inst.sprite

def _attachment_break_enabled(project: Project, inst: Instance, ov: Mapping[str, object]) -> bool:
    if inst.parent is None:
        return False
    try:
        if not bool(ov.get("break_attach", False)):
            return False
        breakable = project.metadata.get("breakable_points", {})
        if not isinstance(breakable, dict):
            return False
        sprite_flags = breakable.get(inst.sprite, {})
        if not isinstance(sprite_flags, dict):
            return False
        return bool(sprite_flags.get(inst.self_point, False))
    except Exception:
        return False


def world_point(project: Project, instance_name: str, point_name: str, overrides: OverrideMap | None = None) -> Vec2:
    return solve_pose(project, overrides)[instance_name].point(point_name)


def _scale(v: Vec2, sx: float, sy: float) -> Vec2:
    return Vec2(v.x * sx, v.y * sy)


def _world_points(sprite: Sprite, top_left: Vec2, rotation: float, sx: float = 1.0, sy: float = 1.0) -> dict[str, Vec2]:
    return {name: top_left + rotate(_scale(point.local_position(sprite), sx, sy), rotation) for name, point in sprite.points.items()}


def _topological_order(project: Project) -> list[str]:
    children: dict[str, list[str]] = {name: [] for name in project.rig.instances}
    roots: list[str] = []
    for name, inst in project.rig.instances.items():
        if inst.parent is None:
            roots.append(name)
        else:
            children[inst.parent].append(name)

    for bucket in children.values():
        bucket.sort(key=lambda n: (project.rig.instances[n].z, n))
    roots.sort(key=lambda n: (project.rig.instances[n].z, n))

    order: list[str] = []
    stack = list(reversed(roots))
    while stack:
        name = stack.pop()
        order.append(name)
        for child in reversed(children[name]):
            stack.append(child)
    return order
