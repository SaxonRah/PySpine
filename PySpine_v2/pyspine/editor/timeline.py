from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from pyspine.core.model import Clip, Project
from pyspine.editor.hierarchy import hierarchy_rows


@dataclass(frozen=True, slots=True)
class TimelineRow:
    instance: str
    channel: str
    depth: int

    @property
    def label(self) -> str:
        return f"{self.instance}.{self.channel}"


def keyable_channels(project: Project, instance_name: str) -> tuple[str, ...]:
    inst = project.rig.instances[instance_name]
    # x/y are meaningful for every sprite now.  For roots they are world-space
    # placement; for children they are local offsets from the attachment pair.
    if inst.parent is None:
        return ("x", "y", "rotation", "scale_x", "scale_y", "visible", "sprite")
    return ("x", "y", "local_rotation", "scale_x", "scale_y", "visible", "sprite")


def timeline_rows(project: Project, clip: Clip | None = None, *, include_empty: bool = True) -> list[TimelineRow]:
    rows: list[TimelineRow] = []
    for hrow in hierarchy_rows(project):
        channels = keyable_channels(project, hrow.instance)
        if not include_empty and clip is not None:
            track = clip.tracks.get(hrow.instance)
            channels = tuple(ch for ch in channels if track and ch in track.channels)
        for channel in channels:
            rows.append(TimelineRow(hrow.instance, channel, hrow.depth))
    return rows


def frames_with_keys(clip: Clip, *, eps: float = 1e-6) -> list[float]:
    out: set[float] = set()
    for track in clip.tracks.values():
        for keys in track.channels.values():
            out.update(float(f) for f in keys)
    return sorted(out)


def frame_keys_at(clip: Clip, frame: float, *, eps: float = 1e-6) -> list[tuple[str, str, object]]:
    out: list[tuple[str, str, object]] = []
    for inst_name, track in clip.tracks.items():
        for channel, keys in track.channels.items():
            for key_frame, value in keys.items():
                if isclose(float(key_frame), float(frame), abs_tol=eps):
                    out.append((inst_name, channel, value))
    return sorted(out)


def find_nearest_key(clip: Clip, instance: str, channel: str, frame: float, *, max_delta: float = 0.75) -> float | None:
    track = clip.tracks.get(instance)
    if not track:
        return None
    keys = track.channels.get(channel)
    if not keys:
        return None
    best = min((float(f) for f in keys), key=lambda f: abs(f - frame))
    return best if abs(best - frame) <= max_delta else None
