from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from .animation import solve_clip_pose
from .geometry import Vec2
from .model import Clip, Project


@dataclass(frozen=True, slots=True)
class MotionArcPoint:
    frame: float
    x: float
    y: float
    visible: bool = True

    @property
    def point(self) -> Vec2:
        return Vec2(self.x, self.y)


@dataclass(frozen=True, slots=True)
class PlantRange:
    start: float
    end: float
    max_speed: float


def frame_sequence(start: float, end: float, step: float = 1.0) -> list[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    lo, hi = sorted((float(start), float(end)))
    out: list[float] = []
    f = lo
    # Epsilon keeps exact integer endpoints stable.
    while f <= hi + 1.0e-9:
        out.append(round(f, 6))
        f += step
    return out


def motion_arc(
    project: Project,
    clip: Clip | str,
    instance: str,
    *,
    point: str = "origin",
    start: float | None = None,
    end: float | None = None,
    step: float = 1.0,
    include_invisible: bool = False,
) -> list[MotionArcPoint]:
    if isinstance(clip, str):
        clip = project.clips[clip]
    if start is None:
        start = 0.0
    if end is None:
        end = clip.length
    pts: list[MotionArcPoint] = []
    for f in frame_sequence(start, end, step):
        poses = solve_clip_pose(project, clip, f)
        if instance not in poses:
            raise KeyError(instance)
        pose = poses[instance]
        if point not in pose.points:
            raise KeyError(point)
        if include_invisible or pose.visible:
            p = pose.point(point)
            pts.append(MotionArcPoint(float(f), p.x, p.y, pose.visible))
    return pts


def point_speeds(arc: list[MotionArcPoint]) -> list[tuple[float, float]]:
    """Return per-segment speed as (ending_frame, units_per_frame)."""
    out: list[tuple[float, float]] = []
    for a, b in zip(arc, arc[1:]):
        df = max(1.0e-9, float(b.frame - a.frame))
        out.append((b.frame, hypot(b.x - a.x, b.y - a.y) / df))
    return out


def planted_ranges(
    project: Project,
    clip: Clip | str,
    instance: str,
    *,
    point: str = "origin",
    start: float | None = None,
    end: float | None = None,
    step: float = 1.0,
    speed_threshold: float = 0.25,
    min_frames: float = 2.0,
) -> list[PlantRange]:
    """Find approximate foot/hand planted ranges by low point velocity.

    This does not mutate animation. It is a detection helper for editor overlays and
    for foot-lock workflows.  Ranges are based on consecutive segments whose speed
    is <= speed_threshold.
    """
    arc = motion_arc(project, clip, instance, point=point, start=start, end=end, step=step, include_invisible=False)
    speeds = point_speeds(arc)
    if not speeds:
        return []
    ranges: list[PlantRange] = []
    current_start: float | None = None
    current_end: float | None = None
    current_max = 0.0
    prev_frame = arc[0].frame
    for (end_frame, speed), prev in zip(speeds, arc):
        if speed <= speed_threshold:
            if current_start is None:
                current_start = prev.frame
                current_max = speed
            current_end = end_frame
            current_max = max(current_max, speed)
        else:
            if current_start is not None and current_end is not None and current_end - current_start >= min_frames:
                ranges.append(PlantRange(current_start, current_end, current_max))
            current_start = current_end = None
            current_max = 0.0
        prev_frame = end_frame
    if current_start is not None and current_end is not None and current_end - current_start >= min_frames:
        ranges.append(PlantRange(current_start, current_end, current_max))
    return ranges
