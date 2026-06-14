from __future__ import annotations

from bisect import bisect_right

from .geometry import lerp
from .easing import apply_easing, normalize_easing
from .model import Clip, Project, Track
from .solver import solve_pose


def sample_clip(project: Project, clip: Clip | str, frame: float, *, loop: bool | None = None) -> dict[str, dict[str, object]]:
    if isinstance(clip, str):
        clip = project.clips[clip]
    use_loop = clip.loop if loop is None else loop
    frame = _normalize_frame(frame, clip.length, use_loop)

    overrides: dict[str, dict[str, object]] = {}
    for inst_name, track in clip.tracks.items():
        target: dict[str, object] = {}
        for channel, keys in track.channels.items():
            # Discrete channels are intentionally step-sampled.  This enables
            # sprite swaps such as open_hand -> closed_hand at exact frames.
            if channel == "sprite":
                target[channel] = _sample_discrete_channel(keys, frame)
            elif channel in {"visible", "break_attach"}:
                target[channel] = bool(round(float(_sample_channel(keys, frame, "step"))))
            else:
                mode = normalize_easing(track.interpolation.get(channel, "linear"))
                target[channel] = _sample_channel(keys, frame, mode)
        overrides[inst_name] = target
    return overrides


def solve_clip_pose(project: Project, clip: Clip | str, frame: float) -> dict:
    return solve_pose(project, sample_clip(project, clip, frame))


def _normalize_frame(frame: float, length: float, loop: bool) -> float:
    if length <= 0:
        return 0.0
    if loop:
        return frame % length
    return max(0.0, min(length, frame))


def _sample_channel(keys: dict[float, float], frame: float, mode: str = "linear") -> float:
    if not keys:
        raise ValueError("cannot sample empty keyframe channel")
    items = sorted((float(k), float(v)) for k, v in keys.items())
    frames = [k for k, _ in items]
    idx = bisect_right(frames, frame)
    if idx <= 0:
        return items[0][1]
    if idx >= len(items):
        return items[-1][1]
    left_frame, left_val = items[idx - 1]
    right_frame, right_val = items[idx]
    if mode == "step":
        return left_val
    if right_frame == left_frame:
        return right_val
    t = (frame - left_frame) / (right_frame - left_frame)
    return lerp(left_val, right_val, apply_easing(mode, t))


def make_track(instance: str, **channels: dict[float, float]) -> Track:
    return Track(instance=instance, channels={name: dict(values) for name, values in channels.items()})


def _sample_discrete_channel(keys: dict[float, object], frame: float) -> object:
    if not keys:
        raise ValueError("cannot sample empty keyframe channel")
    items = sorted((float(k), v) for k, v in keys.items())
    frames = [k for k, _ in items]
    idx = bisect_right(frames, frame)
    if idx <= 0:
        return items[0][1]
    return items[idx - 1][1]
