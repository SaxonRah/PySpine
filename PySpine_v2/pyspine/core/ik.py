from __future__ import annotations

from dataclasses import dataclass
from math import acos, atan2, cos, degrees, hypot, radians, sin

from .geometry import Vec2


@dataclass(frozen=True, slots=True)
class TwoBoneIKSolution:
    upper_world_angle: float
    lower_local_angle: float
    lower_world_angle: float
    elbow: Vec2
    target: Vec2
    reachable: bool


def distance(a: Vec2, b: Vec2) -> float:
    return hypot(b.x - a.x, b.y - a.y)


def angle_between(a: Vec2, b: Vec2) -> float:
    return degrees(atan2(b.y - a.y, b.x - a.x))


def normalize_degrees(angle: float) -> float:
    angle = (float(angle) + 180.0) % 360.0 - 180.0
    return 180.0 if angle == -180.0 else angle


def solve_two_bone_ik(root: Vec2, target: Vec2, upper_length: float, lower_length: float, *, bend: int = 1) -> TwoBoneIKSolution:
    """Solve a simple planar two-bone IK chain.

    Angles use PySpine's screen-space convention: +X right, +Y down, degrees.
    bend=+1 picks one elbow side; bend=-1 picks the mirrored side.
    """
    if upper_length <= 0 or lower_length <= 0:
        raise ValueError("bone lengths must be positive")
    sign = 1 if bend >= 0 else -1
    dx = target.x - root.x
    dy = target.y - root.y
    dist_raw = hypot(dx, dy)
    if dist_raw < 1.0e-9:
        # Avoid undefined base angle; place target just to the right.
        dx, dy = 1.0e-9, 0.0
        dist_raw = 1.0e-9
    max_reach = upper_length + lower_length
    min_reach = abs(upper_length - lower_length)
    reachable = min_reach <= dist_raw <= max_reach
    d = max(min_reach + 1.0e-9, min(max_reach - 1.0e-9, dist_raw))
    base = atan2(dy, dx)
    root_cos = (upper_length * upper_length + d * d - lower_length * lower_length) / (2.0 * upper_length * d)
    root_cos = max(-1.0, min(1.0, root_cos))
    root_offset = acos(root_cos)
    upper_angle = base - sign * root_offset
    internal_cos = (upper_length * upper_length + lower_length * lower_length - d * d) / (2.0 * upper_length * lower_length)
    internal_cos = max(-1.0, min(1.0, internal_cos))
    internal = acos(internal_cos)
    lower_local = sign * (3.141592653589793 - internal)
    lower_world = upper_angle + lower_local
    elbow = Vec2(root.x + cos(upper_angle) * upper_length, root.y + sin(upper_angle) * upper_length)
    clamped = Vec2(root.x + cos(base) * d, root.y + sin(base) * d)
    return TwoBoneIKSolution(
        upper_world_angle=normalize_degrees(degrees(upper_angle)),
        lower_local_angle=normalize_degrees(degrees(lower_local)),
        lower_world_angle=normalize_degrees(degrees(lower_world)),
        elbow=elbow,
        target=target if reachable else clamped,
        reachable=reachable,
    )
