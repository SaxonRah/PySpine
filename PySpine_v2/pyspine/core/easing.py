from __future__ import annotations

import re
from math import isfinite

EASING_MODES = {
    "linear",
    "step",
    "ease_in",
    "ease_out",
    "ease_in_out",
    "smoothstep",
    "smootherstep",
}

_CUBIC_BEZIER_RE = re.compile(r"^bezier\(([^,]+),([^,]+),([^,]+),([^\)]+)\)$")


def clamp01(t: float) -> float:
    return max(0.0, min(1.0, float(t)))


def is_supported_easing(mode: str) -> bool:
    mode = str(mode or "linear")
    return mode in EASING_MODES or _CUBIC_BEZIER_RE.match(mode.replace(" ", "")) is not None


def normalize_easing(mode: str | None) -> str:
    if not mode:
        return "linear"
    mode = str(mode).strip().lower().replace("-", "_")
    aliases = {
        "hold": "step",
        "constant": "step",
        "easein": "ease_in",
        "easeout": "ease_out",
        "easeinout": "ease_in_out",
        "ease_inout": "ease_in_out",
        "ease_out_in": "ease_in_out",
    }
    mode = aliases.get(mode, mode)
    # Preserve CSS-like cubic bezier but normalize spaces.
    if mode.startswith("bezier"):
        mode = mode.replace(" ", "")
    if not is_supported_easing(mode):
        raise ValueError(f"unsupported easing mode {mode!r}")
    return mode


def apply_easing(mode: str | None, t: float) -> float:
    """Map a 0..1 interpolation position through an easing curve.

    Supported strings: linear, step, ease_in, ease_out, ease_in_out,
    smoothstep, smootherstep, and bezier(x1,y1,x2,y2).  Bezier uses a
    small binary solve for x(t), good enough for editor/runtime sampling.
    """
    mode = normalize_easing(mode)
    t = clamp01(t)
    if mode == "linear":
        return t
    if mode == "step":
        return 0.0
    if mode == "ease_in":
        return t * t * t
    if mode == "ease_out":
        u = 1.0 - t
        return 1.0 - u * u * u
    if mode == "ease_in_out":
        return 4.0 * t * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0
    if mode == "smoothstep":
        return t * t * (3.0 - 2.0 * t)
    if mode == "smootherstep":
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
    m = _CUBIC_BEZIER_RE.match(mode)
    if m:
        x1, y1, x2, y2 = (float(v) for v in m.groups())
        if not all(isfinite(v) for v in (x1, y1, x2, y2)):
            raise ValueError(f"non-finite bezier easing {mode!r}")
        return _cubic_bezier_y_for_x(t, x1, y1, x2, y2)
    raise ValueError(f"unsupported easing mode {mode!r}")


def _cubic(a: float, b: float, c: float, d: float, t: float) -> float:
    u = 1.0 - t
    return u * u * u * a + 3.0 * u * u * t * b + 3.0 * u * t * t * c + t * t * t * d


def _cubic_bezier_y_for_x(x: float, x1: float, y1: float, x2: float, y2: float) -> float:
    # The standard endpoints are (0,0) and (1,1). Solve x(t)=x by bisection.
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) * 0.5
        bx = _cubic(0.0, x1, x2, 1.0, mid)
        if bx < x:
            lo = mid
        else:
            hi = mid
    t = (lo + hi) * 0.5
    return clamp01(_cubic(0.0, y1, y2, 1.0, t))
