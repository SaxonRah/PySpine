from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable

from pyspine.core.commands import KeyframeBatchEdit, SetManyKeyframes
from pyspine.core.geometry import Vec2
from pyspine.core.ik import angle_between, normalize_degrees, solve_two_bone_ik, distance
from pyspine.core.model import Clip, Project
from pyspine.core.motion import MotionArcPoint, motion_arc, planted_ranges
from pyspine.core.animation import sample_clip, solve_clip_pose
from pyspine.core.solver import solve_pose


@dataclass(frozen=True, slots=True)
class OnionFrame:
    frame: float
    offset: int
    alpha: float


@dataclass(frozen=True, slots=True)
class OnionSkinSettings:
    before: int = 2
    after: int = 2
    step: float = 2.0
    base_alpha: float = 0.45
    falloff: float = 0.65
    loop: bool = False

    @classmethod
    def from_metadata(cls, metadata: dict) -> "OnionSkinSettings":
        """Load onion-skin settings from project metadata.

        With ``slots=True`` dataclasses, field defaults are not reliably readable as
        ``cls.before``/``cls.after`` class attributes on every Python version.  They
        can be ``member_descriptor`` objects, which caused the editor to crash when
        an old project had no ``metadata["onion_skin"]`` block.  Build one default
        instance instead, then coerce user metadata on top of it.
        """
        raw = metadata.get("onion_skin", {}) if isinstance(metadata, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        default = cls()

        def read_int(name: str, fallback: int, *, minimum: int | None = None) -> int:
            try:
                value = int(raw.get(name, fallback))
            except (TypeError, ValueError):
                value = fallback
            if minimum is not None:
                value = max(minimum, value)
            return value

        def read_float(name: str, fallback: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
            try:
                value = float(raw.get(name, fallback))
            except (TypeError, ValueError):
                value = fallback
            if minimum is not None:
                value = max(minimum, value)
            if maximum is not None:
                value = min(maximum, value)
            return value

        return cls(
            before=read_int("before", default.before, minimum=0),
            after=read_int("after", default.after, minimum=0),
            step=read_float("step", default.step, minimum=0.001),
            base_alpha=read_float("base_alpha", default.base_alpha, minimum=0.0, maximum=1.0),
            falloff=read_float("falloff", default.falloff, minimum=0.0, maximum=1.0),
            loop=bool(raw.get("loop", default.loop)),
        )

    def to_metadata(self) -> dict[str, float | int | bool]:
        return {
            "before": self.before,
            "after": self.after,
            "step": self.step,
            "base_alpha": self.base_alpha,
            "falloff": self.falloff,
            "loop": self.loop,
        }

    def frames(self, current_frame: float, length: float) -> list[OnionFrame]:
        if self.step <= 0:
            raise ValueError("onion step must be positive")
        out: list[OnionFrame] = []
        for i in range(self.before, 0, -1):
            f = float(current_frame) - i * self.step
            if self.loop and length > 0:
                f %= length
            elif f < 0:
                continue
            out.append(OnionFrame(f, -i, self.base_alpha * (self.falloff ** (i - 1))))
        for i in range(1, self.after + 1):
            f = float(current_frame) + i * self.step
            if self.loop and length > 0:
                f %= length
            elif f > length:
                continue
            out.append(OnionFrame(f, i, self.base_alpha * (self.falloff ** (i - 1))))
        return out


def set_onion_metadata(project: Project, settings: OnionSkinSettings) -> None:
    project.metadata["onion_skin"] = settings.to_metadata()


def motion_arc_for_selection(project: Project, clip_name: str, instance: str | None, *, point: str = "origin", step: float = 1.0) -> list[MotionArcPoint]:
    if not instance:
        return []
    return motion_arc(project, clip_name, instance, point=point, step=step)


def two_bone_ik_keyframes(
    project: Project,
    clip_name: str,
    upper_instance: str,
    lower_instance: str,
    target: Vec2,
    frame: float,
    *,
    end_point: str,
    bend: int = 1,
) -> SetManyKeyframes:
    """Create rotation keyframes for a two-bone chain at one frame.

    The lower instance must be parented to the upper instance.  The upper bone is
    the vector from upper.self_point to lower.parent_point.  The lower bone is the
    vector from lower.self_point to end_point.
    """
    if lower_instance not in project.rig.instances or upper_instance not in project.rig.instances:
        raise KeyError("missing IK instance")
    upper = project.rig.instances[upper_instance]
    lower = project.rig.instances[lower_instance]
    if lower.parent != upper_instance:
        raise ValueError("lower instance must be parented to upper instance")
    if not lower.parent_point:
        raise ValueError("lower instance needs parent_point on upper")
    us = project.sheet.sprites[upper.sprite]
    ls = project.sheet.sprites[lower.sprite]
    if upper.self_point not in us.points or lower.parent_point not in us.points:
        raise KeyError("upper chain points missing")
    if lower.self_point not in ls.points or end_point not in ls.points:
        raise KeyError("lower chain points missing")

    poses = solve_clip_pose(project, clip_name, frame) if clip_name in project.clips else solve_pose(project)
    upper_pose = poses[upper_instance]
    root_world = upper_pose.point(upper.self_point)

    u0 = us.point(upper.self_point).local_position(us)
    u1 = us.point(lower.parent_point).local_position(us)
    l0 = ls.point(lower.self_point).local_position(ls)
    l1 = ls.point(end_point).local_position(ls)
    upper_len = hypot((u1.x - u0.x) * upper.scale_x, (u1.y - u0.y) * upper.scale_y)
    lower_len = hypot((l1.x - l0.x) * lower.scale_x, (l1.y - l0.y) * lower.scale_y)
    upper_rest_angle = angle_between(u0, u1)
    lower_rest_angle = angle_between(l0, l1)

    sol = solve_two_bone_ik(root_world, target, upper_len, lower_len, bend=bend)
    parent_world_rot = 0.0
    if upper.parent:
        parent_world_rot = poses[upper.parent].rotation
    desired_upper_sprite_rot = normalize_degrees(sol.upper_world_angle - upper_rest_angle)
    if upper.parent is None:
        upper_channel = "rotation"
        upper_value = normalize_degrees(desired_upper_sprite_rot - upper.local_rotation)
    else:
        upper_channel = "local_rotation"
        upper_value = normalize_degrees(desired_upper_sprite_rot - parent_world_rot)
    desired_lower_sprite_rot = normalize_degrees(sol.lower_world_angle - lower_rest_angle)
    lower_value = normalize_degrees(desired_lower_sprite_rot - desired_upper_sprite_rot)

    clip = project.clips.get(clip_name)
    changes: list[tuple[str, str, float, float | None, float]] = []
    for inst, ch, val in ((upper_instance, upper_channel, upper_value), (lower_instance, "local_rotation", lower_value)):
        before = None
        if clip and inst in clip.tracks:
            before = clip.tracks[inst].channels.get(ch, {}).get(float(frame))
        changes.append((inst, ch, float(frame), before, float(val)))
    return SetManyKeyframes(clip_name, changes, label="Two-bone IK")


def foot_lock_keyframes(
    project: Project,
    clip_name: str,
    root_instance: str,
    locked_instance: str,
    locked_point: str,
    start: float,
    end: float,
    *,
    step: float = 1.0,
    target: Vec2 | None = None,
) -> SetManyKeyframes:
    """Key root x/y so a selected foot/hand point stays planted over a frame range."""
    if root_instance not in project.rig.instances or locked_instance not in project.rig.instances:
        raise KeyError("missing foot-lock instance")
    if project.rig.instances[root_instance].parent is not None:
        raise ValueError("foot-lock root_instance must be a root instance")
    clip = project.clips[clip_name]
    if target is None:
        p0 = solve_clip_pose(project, clip, start)[locked_instance].point(locked_point)
        target = Vec2(p0.x, p0.y)
    changes: list[tuple[str, str, float, float | None, float]] = []
    for f in _frames(start, end, step):
        overrides = sample_clip(project, clip, f)
        poses = solve_clip_pose(project, clip, f)
        cur = poses[locked_instance].point(locked_point)
        delta = Vec2(target.x - cur.x, target.y - cur.y)
        sampled_root = overrides.get(root_instance, {})
        inst = project.rig.instances[root_instance]
        new_x = float(sampled_root.get("x", inst.x)) + delta.x
        new_y = float(sampled_root.get("y", inst.y)) + delta.y
        track = clip.tracks.get(root_instance)
        bx = track.channels.get("x", {}).get(f) if track else None
        by = track.channels.get("y", {}).get(f) if track else None
        changes.append((root_instance, "x", f, bx, new_x))
        changes.append((root_instance, "y", f, by, new_y))
    return SetManyKeyframes(clip_name, changes, label="Foot lock")


def detect_plant_ranges(project: Project, clip_name: str, instance: str, point: str, *, threshold: float = 0.25, min_frames: float = 2.0):
    return planted_ranges(project, clip_name, instance, point=point, speed_threshold=threshold, min_frames=min_frames)


def _frames(start: float, end: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    lo, hi = sorted((float(start), float(end)))
    out = []
    f = lo
    while f <= hi + 1.0e-9:
        out.append(round(f, 6))
        f += step
    return out

# ---- v13.4 whole-chain IK ----------------------------------------------------

def instance_ancestor_chain(project: Project, selected_instance: str) -> list[str]:
    """Return root->selected ancestry for a rig instance."""
    if selected_instance not in project.rig.instances:
        raise KeyError(selected_instance)
    chain: list[str] = []
    seen: set[str] = set()
    name: str | None = selected_instance
    while name is not None:
        if name in seen:
            raise ValueError("cycle in instance chain")
        seen.add(name)
        chain.append(name)
        name = project.rig.instances[name].parent
    chain.reverse()
    return chain


def choose_end_effector_point(project: Project, instance_name: str) -> str:
    """Pick a useful point to drag when the user selects a hand/foot/limb end.

    Prefer an explicit hand/foot/wrist/ankle endpoint if it is not the instance's
    own attachment point.  Otherwise fall back to origin, then any non-self point.
    """
    inst = project.rig.instances[instance_name]
    sprite = project.sheet.sprites[inst.sprite]
    pts = list(sprite.points)
    preferred = ("hand", "foot", "wrist", "ankle", "toe", "heel", "origin")
    candidates = [p for p in pts if p not in {inst.self_point, inst.parent_point}]
    for needle in preferred:
        for p in candidates:
            if p == needle or needle in p:
                return p
    if "origin" in sprite.points:
        return "origin"
    for p in pts:
        if p != inst.self_point:
            return p
    return inst.self_point


def whole_chain_ik_keyframes(
    project: Project,
    clip_name: str,
    selected_instance: str,
    target: Vec2,
    frame: float,
    *,
    end_point: str | None = None,
    max_chain: int | None = None,
    iterations: int = 12,
    tolerance: float = 0.75,
) -> SetManyKeyframes:
    """CCD-style full-chain IK from the selected end-effector toward the root.

    This is intentionally an animator helper, not a physics solver.  It keys the
    rotation/local_rotation channels along the selected instance's ancestor chain.
    For a hand this means shoulder -> upper arm -> forearm -> hand; for a foot it
    can include shoulders/waist/pelvis/thigh/knee/calf/foot, which is what makes
    it feel like "full body" instead of the old two-bone-only helper.
    """
    if selected_instance not in project.rig.instances:
        raise KeyError(selected_instance)
    if clip_name not in project.clips:
        project.clips[clip_name] = Clip(name=clip_name, length=24.0, fps=24.0, loop=True)
    clip = project.clips[clip_name]
    end_point = end_point or choose_end_effector_point(project, selected_instance)
    chain = instance_ancestor_chain(project, selected_instance)
    if max_chain is not None and max_chain > 0:
        chain = chain[-max_chain:]
    if not chain:
        raise ValueError("empty IK chain")

    base_overrides = sample_clip(project, clip, frame)
    overrides: dict[str, dict[str, object]] = {name: dict(vals) for name, vals in base_overrides.items()}

    def channel_for(inst_name: str) -> str:
        return "rotation" if project.rig.instances[inst_name].parent is None else "local_rotation"

    def current_value(inst_name: str, channel: str) -> float:
        inst = project.rig.instances[inst_name]
        fallback = inst.rotation if channel == "rotation" else inst.local_rotation
        return float(overrides.get(inst_name, {}).get(channel, fallback))

    if end_point not in project.sheet.sprites[project.rig.instances[selected_instance].sprite].points:
        raise KeyError(f"end point {end_point!r} missing on {selected_instance}")

    for _ in range(max(1, int(iterations))):
        poses = solve_pose(project, overrides)
        eff = poses[selected_instance].point(end_point)
        if distance(eff, target) <= tolerance:
            break
        # Rotate from the end back toward the root.  Include the selected part so
        # hands/feet can aim their own origin/endpoint too, but skip locked parts.
        for joint in reversed(chain):
            inst = project.rig.instances[joint]
            if getattr(inst, "locked", False):
                continue
            poses = solve_pose(project, overrides)
            if joint not in poses or selected_instance not in poses:
                continue
            pivot = poses[joint].point(inst.self_point)
            eff = poses[selected_instance].point(end_point)
            a = angle_between(pivot, eff)
            b = angle_between(pivot, target)
            delta = normalize_degrees(b - a)
            if abs(delta) < 0.001:
                continue
            ch = channel_for(joint)
            overrides.setdefault(joint, {})[ch] = normalize_degrees(current_value(joint, ch) + delta)

    # If the rotations cannot quite reach the target, translate the root by the
    # remaining residual.  This is what makes Y feel like a whole-body posing
    # tool in Animation mode: hands/feet can pull the torso/root instead of
    # stopping at a strict two-bone reach limit.
    poses = solve_pose(project, overrides)
    eff = poses[selected_instance].point(end_point)
    residual = Vec2(target.x - eff.x, target.y - eff.y)
    root_name = chain[0]
    root = project.rig.instances[root_name]
    if root.parent is None and not getattr(root, "locked", False) and distance(eff, target) > tolerance:
        overrides.setdefault(root_name, {})["x"] = float(overrides.get(root_name, {}).get("x", root.x)) + residual.x
        overrides.setdefault(root_name, {})["y"] = float(overrides.get(root_name, {}).get("y", root.y)) + residual.y

    changes: list[tuple[str, str, float, object | None, object]] = []
    for inst_name in chain:
        if getattr(project.rig.instances[inst_name], "locked", False):
            continue
        channels = [channel_for(inst_name)]
        if inst_name == root_name and project.rig.instances[inst_name].parent is None:
            channels.extend(["x", "y"])
        for ch in channels:
            if inst_name not in overrides or ch not in overrides[inst_name]:
                continue
            before = None
            track = clip.tracks.get(inst_name)
            if track:
                before = track.channels.get(ch, {}).get(float(frame))
            after = float(overrides[inst_name][ch])
            changes.append((inst_name, ch, float(frame), before, after))
    if not changes:
        raise ValueError("IK produced no keyframes; chain may be locked")
    return SetManyKeyframes(clip_name, changes, label="Whole-chain IK")
