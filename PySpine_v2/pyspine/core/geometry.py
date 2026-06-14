from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin


_EPS = 1.0e-9


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0

    def __add__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vec2":
        return Vec2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

    def almost_equal(self, other: "Vec2", eps: float = 1.0e-6) -> bool:
        return abs(self.x - other.x) <= eps and abs(self.y - other.y) <= eps


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def size(self) -> Vec2:
        return Vec2(self.w, self.h)

    def corners(self) -> tuple[Vec2, Vec2, Vec2, Vec2]:
        return (
            Vec2(0.0, 0.0),
            Vec2(self.w, 0.0),
            Vec2(self.w, self.h),
            Vec2(0.0, self.h),
        )


def rotate(v: Vec2, degrees: float) -> Vec2:
    if abs(degrees) < _EPS:
        return v
    r = radians(degrees)
    c = cos(r)
    s = sin(r)
    return Vec2(v.x * c - v.y * s, v.x * s + v.y * c)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
