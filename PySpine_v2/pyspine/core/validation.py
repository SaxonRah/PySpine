from __future__ import annotations

from math import isfinite

from .model import Project
from .easing import is_supported_easing, normalize_easing


class ValidationError(ValueError):
    """Raised when a project cannot be solved or serialized safely."""


def validate_project(project: Project, *, strict: bool = True) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []

    for name, sprite in project.sheet.sprites.items():
        if name != sprite.name:
            errors.append(f"sprite key {name!r} does not match sprite.name {sprite.name!r}")
        if sprite.rect.w <= 0 or sprite.rect.h <= 0:
            errors.append(f"sprite {name!r} has non-positive dimensions")
        if not isfinite(sprite.rect.w) or not isfinite(sprite.rect.h):
            errors.append(f"sprite {name!r} has non-finite dimensions")
        if len(sprite.points) != len(set(sprite.points)):
            errors.append(f"sprite {name!r} has duplicate point names")
        if "origin" not in sprite.points:
            warnings.append(f"sprite {name!r} has no 'origin' point")
        for point_name, point in sprite.points.items():
            if point_name != point.name:
                errors.append(f"sprite {name!r} point key {point_name!r} does not match point.name {point.name!r}")
            if not isfinite(point.x) or not isfinite(point.y):
                errors.append(f"sprite {name!r} point {point_name!r} is non-finite")
            if strict and not (0.0 <= point.x <= 1.0 and 0.0 <= point.y <= 1.0):
                errors.append(f"sprite {name!r} point {point_name!r} is outside normalized bounds")

    for name, inst in project.rig.instances.items():
        if name != inst.name:
            errors.append(f"instance key {name!r} does not match instance.name {inst.name!r}")
        if inst.sprite not in project.sheet.sprites:
            errors.append(f"instance {name!r} references missing sprite {inst.sprite!r}")
            continue
        sprite = project.sheet.sprites[inst.sprite]
        if inst.self_point not in sprite.points:
            errors.append(f"instance {name!r} self_point {inst.self_point!r} missing on sprite {inst.sprite!r}")
        if inst.parent is not None:
            if inst.parent not in project.rig.instances:
                errors.append(f"instance {name!r} references missing parent {inst.parent!r}")
            elif inst.parent == name:
                errors.append(f"instance {name!r} cannot parent itself")
            if not inst.parent_point:
                errors.append(f"child instance {name!r} needs parent_point")
            elif inst.parent in project.rig.instances:
                parent = project.rig.instances[inst.parent]
                if parent.sprite in project.sheet.sprites:
                    parent_sprite = project.sheet.sprites[parent.sprite]
                    if inst.parent_point not in parent_sprite.points:
                        errors.append(
                            f"instance {name!r} parent_point {inst.parent_point!r} missing on parent sprite {parent.sprite!r}"
                        )
        if not isfinite(inst.rotation) or not isfinite(inst.local_rotation):
            errors.append(f"instance {name!r} has non-finite rotation")
        if not isfinite(inst.scale_x) or not isfinite(inst.scale_y):
            errors.append(f"instance {name!r} has non-finite scale")
        if abs(inst.scale_x) < 1.0e-6 or abs(inst.scale_y) < 1.0e-6:
            errors.append(f"instance {name!r} has near-zero scale")
        else:
            if inst.parent is None and (not isfinite(inst.x) or not isfinite(inst.y)):
                errors.append(f"root instance {name!r} has non-finite position")

    cycle = _find_cycle(project)
    if cycle:
        errors.append("cycle detected: " + " -> ".join(cycle))

    for clip_name, clip in project.clips.items():
        if clip_name != clip.name:
            errors.append(f"clip key {clip_name!r} does not match clip.name {clip.name!r}")
        if clip.length <= 0:
            errors.append(f"clip {clip_name!r} must have positive length")
        if clip.fps <= 0:
            errors.append(f"clip {clip_name!r} must have positive fps")
        for track_name, track in clip.tracks.items():
            if track_name != track.instance:
                errors.append(f"clip {clip_name!r} track key {track_name!r} does not match track.instance")
            if track.instance not in project.rig.instances:
                errors.append(f"clip {clip_name!r} references missing instance {track.instance!r}")
            for channel, keys in track.channels.items():
                if channel not in {"x", "y", "rotation", "local_rotation", "scale_x", "scale_y", "visible", "sprite", "break_attach"}:
                    errors.append(f"clip {clip_name!r} has unsupported channel {channel!r}")
                if not keys:
                    warnings.append(f"clip {clip_name!r} track {track.instance!r}.{channel} has no keys")
                mode = track.interpolation.get(channel, "linear")
                try:
                    # Sprite swaps and visibility are always step/discrete; ignore user easing.
                    if channel not in {"sprite", "visible", "break_attach"}:
                        normalize_easing(mode)
                except ValueError:
                    errors.append(f"clip {clip_name!r} track {track.instance!r}.{channel} has unsupported interpolation {mode!r}")
                for frame, value in keys.items():
                    if not isfinite(float(frame)):
                        errors.append(f"clip {clip_name!r} track {track.instance!r}.{channel} contains non-finite frame")
                    if channel == "sprite":
                        if not isinstance(value, str) or value not in project.sheet.sprites:
                            errors.append(f"clip {clip_name!r} track {track.instance!r}.sprite references missing sprite {value!r}")
                        else:
                            inst = project.rig.instances.get(track.instance)
                            replacement = project.sheet.sprites[value]
                            if inst is not None:
                                if inst.self_point not in replacement.points:
                                    warnings.append(
                                        f"clip {clip_name!r} track {track.instance!r}.sprite value {value!r} cannot attach: missing self point {inst.self_point!r}"
                                    )
                                missing_child_points = sorted(
                                    child.parent_point
                                    for child in project.rig.instances.values()
                                    if child.parent == track.instance and child.parent_point and child.parent_point not in replacement.points
                                )
                                if missing_child_points:
                                    warnings.append(
                                        f"clip {clip_name!r} track {track.instance!r}.sprite value {value!r} cannot attach child point(s): "
                                        + ", ".join(repr(p) for p in missing_child_points)
                                    )
                    else:
                        try:
                            numeric_value = float(value)
                        except (TypeError, ValueError):
                            errors.append(f"clip {clip_name!r} track {track.instance!r}.{channel} contains non-numeric key")
                            continue
                        if not isfinite(numeric_value):
                            errors.append(f"clip {clip_name!r} track {track.instance!r}.{channel} contains non-finite key")
            for channel, mode in track.interpolation.items():
                if channel not in track.channels:
                    warnings.append(f"clip {clip_name!r} track {track.instance!r}.{channel} interpolation has no matching channel")
                if channel in {"sprite", "visible", "break_attach"}:
                    continue
                try:
                    normalize_easing(mode)
                except ValueError:
                    errors.append(f"clip {clip_name!r} track {track.instance!r}.{channel} has unsupported interpolation {mode!r}")

    if errors:
        raise ValidationError("\n".join(errors))
    return warnings


def _find_cycle(project: Project) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(name: str) -> list[str] | None:
        if name in visiting:
            idx = stack.index(name) if name in stack else 0
            return stack[idx:] + [name]
        if name in visited:
            return None
        visiting.add(name)
        stack.append(name)
        parent = project.rig.instances[name].parent
        if parent in project.rig.instances:
            found = dfs(parent)
            if found:
                return found
        visiting.remove(name)
        visited.add(name)
        stack.pop()
        return None

    for name in project.rig.instances:
        found = dfs(name)
        if found:
            return found
    return None
