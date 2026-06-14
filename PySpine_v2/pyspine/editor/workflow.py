from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pyspine.core.commands import KeyframeBatchEdit, SetInstanceFields, SetManyKeyframes
from pyspine.core.model import Instance, Project
from pyspine.core.validation import validate_project
from pyspine.io.jsonio import save_project
from pyspine.editor.timeline import keyable_channels


@dataclass(frozen=True, slots=True)
class KeyRef:
    instance: str
    channel: str
    frame: float


def children_of(project: Project, instance: str) -> list[str]:
    return sorted((i.name for i in project.rig.instances.values() if i.parent == instance), key=lambda n: (project.rig.instances[n].z, n))


def descendant_chain(project: Project, root: str) -> list[str]:
    out: list[str] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.append(cur)
        stack.extend(reversed(children_of(project, cur)))
    return out


def select_parent(project: Project, instance: str | None) -> str | None:
    if not instance or instance not in project.rig.instances:
        return None
    return project.rig.instances[instance].parent


def select_child(project: Project, instance: str | None, *, index: int = 0) -> str | None:
    if not instance:
        roots = sorted((i.name for i in project.rig.instances.values() if i.parent is None), key=lambda n: (project.rig.instances[n].z, n))
        return roots[index % len(roots)] if roots else None
    kids = children_of(project, instance)
    return kids[index % len(kids)] if kids else None


def set_instance_fields(project: Project, instance: str, **fields: object) -> SetInstanceFields:
    if instance not in project.rig.instances:
        raise KeyError(instance)
    inst = project.rig.instances[instance]
    before = {k: getattr(inst, k) for k in fields}
    after = dict(fields)
    return SetInstanceFields(instance, before, after)


def toggle_locked(project: Project, instance: str) -> SetInstanceFields:
    inst = project.rig.instances[instance]
    return set_instance_fields(project, instance, locked=not inst.locked)


def toggle_visible(project: Project, instance: str) -> SetInstanceFields:
    inst = project.rig.instances[instance]
    return set_instance_fields(project, instance, visible=not inst.visible)


def valid_sprite_options(project: Project) -> list[str]:
    return sorted(project.sheet.sprites)


def valid_parent_point_options(project: Project, instance: str) -> list[str]:
    inst = project.rig.instances[instance]
    if not inst.parent:
        return []
    parent = project.rig.instances[inst.parent]
    return sorted(project.sheet.sprites[parent.sprite].points)


def valid_self_point_options(project: Project, instance: str) -> list[str]:
    inst = project.rig.instances[instance]
    return sorted(project.sheet.sprites[inst.sprite].points)


def all_key_refs(project: Project, clip_name: str) -> list[KeyRef]:
    clip = project.clips[clip_name]
    refs: list[KeyRef] = []
    for inst, track in clip.tracks.items():
        for channel, keys in track.channels.items():
            refs.extend(KeyRef(inst, channel, float(frame)) for frame in keys)
    return sorted(refs, key=lambda r: (r.frame, r.instance, r.channel))


def key_refs_in_box(project: Project, clip_name: str, rows: Iterable[tuple[str, str]], frame_min: float, frame_max: float) -> list[KeyRef]:
    wanted = set(rows)
    lo, hi = sorted((float(frame_min), float(frame_max)))
    return [r for r in all_key_refs(project, clip_name) if (r.instance, r.channel) in wanted and lo <= r.frame <= hi]


def _keys_before(project: Project, clip_name: str, keys: Iterable[tuple[str, str, float]]) -> dict[tuple[str, str, float], float]:
    clip = project.clips.get(clip_name)
    out: dict[tuple[str, str, float], float] = {}
    if not clip:
        return out
    for inst, channel, frame in keys:
        track = clip.tracks.get(inst)
        value = None if not track else track.channels.get(channel, {}).get(float(frame))
        if value is not None:
            out[(inst, channel, float(frame))] = float(value)
    return out


def duplicate_keys(project: Project, clip_name: str, refs: Iterable[KeyRef], offset: float = 1.0) -> KeyframeBatchEdit:
    clip = project.clips[clip_name]
    after: dict[tuple[str, str, float], float | None] = {}
    touched: list[tuple[str, str, float]] = []
    for r in refs:
        track = clip.tracks.get(r.instance)
        if not track:
            continue
        keys = track.channels.get(r.channel, {})
        if r.frame not in keys:
            continue
        dst = float(r.frame + offset)
        after[(r.instance, r.channel, dst)] = float(keys[r.frame])
        touched.append((r.instance, r.channel, dst))
    return KeyframeBatchEdit(clip_name, _keys_before(project, clip_name, touched), after, label="Duplicate keyframes")


def move_keys(project: Project, clip_name: str, refs: Iterable[KeyRef], delta: float) -> KeyframeBatchEdit:
    clip = project.clips[clip_name]
    after: dict[tuple[str, str, float], float | None] = {}
    touched: set[tuple[str, str, float]] = set()
    for r in refs:
        track = clip.tracks.get(r.instance)
        if not track:
            continue
        keys = track.channels.get(r.channel, {})
        if r.frame not in keys:
            continue
        src = (r.instance, r.channel, float(r.frame))
        dst = (r.instance, r.channel, max(0.0, float(r.frame + delta)))
        after[src] = None
        after[dst] = float(keys[r.frame])
        touched.add(src); touched.add(dst)
    return KeyframeBatchEdit(clip_name, _keys_before(project, clip_name, touched), after, label="Move keyframes")


def scale_key_timing(project: Project, clip_name: str, refs: Iterable[KeyRef], origin: float, factor: float) -> KeyframeBatchEdit:
    clip = project.clips[clip_name]
    after: dict[tuple[str, str, float], float | None] = {}
    touched: set[tuple[str, str, float]] = set()
    for r in refs:
        track = clip.tracks.get(r.instance)
        if not track:
            continue
        keys = track.channels.get(r.channel, {})
        if r.frame not in keys:
            continue
        new_frame = max(0.0, float(origin + (r.frame - origin) * factor))
        src = (r.instance, r.channel, float(r.frame))
        dst = (r.instance, r.channel, new_frame)
        after[src] = None
        after[dst] = float(keys[r.frame])
        touched.add(src); touched.add(dst)
    return KeyframeBatchEdit(clip_name, _keys_before(project, clip_name, touched), after, label="Scale key timing")


def insert_frame_range(project: Project, clip_name: str, at_frame: float, length: float) -> KeyframeBatchEdit:
    refs = [r for r in all_key_refs(project, clip_name) if r.frame >= at_frame]
    return move_keys(project, clip_name, refs, length)


def delete_frame_range(project: Project, clip_name: str, start: float, end: float) -> KeyframeBatchEdit:
    lo, hi = sorted((start, end))
    clip = project.clips[clip_name]
    after: dict[tuple[str, str, float], float | None] = {}
    touched: set[tuple[str, str, float]] = set()
    for r in all_key_refs(project, clip_name):
        track = clip.tracks.get(r.instance)
        if not track:
            continue
        value = track.channels.get(r.channel, {}).get(r.frame)
        if value is None:
            continue
        src = (r.instance, r.channel, r.frame)
        if lo <= r.frame < hi:
            after[src] = None
            touched.add(src)
        elif r.frame >= hi:
            dst = (r.instance, r.channel, max(lo, r.frame - (hi - lo)))
            after[src] = None
            after[dst] = float(value)
            touched.add(src); touched.add(dst)
    return KeyframeBatchEdit(clip_name, _keys_before(project, clip_name, touched), after, label="Delete frame range")


def clear_channel(project: Project, clip_name: str, instance: str, channel: str) -> KeyframeBatchEdit:
    clip = project.clips[clip_name]
    track = clip.tracks.get(instance)
    refs = [KeyRef(instance, channel, f) for f in (track.channels.get(channel, {}) if track else {})]
    after = {(r.instance, r.channel, r.frame): None for r in refs}
    return KeyframeBatchEdit(clip_name, _keys_before(project, clip_name, after), after, label="Clear channel")


def clear_pose_at_frame(project: Project, clip_name: str, frame: float, *, instance: str | None = None) -> KeyframeBatchEdit:
    refs = [r for r in all_key_refs(project, clip_name) if abs(r.frame - frame) <= 1.0e-6 and (instance is None or r.instance == instance)]
    after = {(r.instance, r.channel, r.frame): None for r in refs}
    return KeyframeBatchEdit(clip_name, _keys_before(project, clip_name, after), after, label="Clear pose keys")


def clear_instance_keys(project: Project, clip_name: str, instance: str) -> KeyframeBatchEdit:
    refs = [r for r in all_key_refs(project, clip_name) if r.instance == instance]
    after = {(r.instance, r.channel, r.frame): None for r in refs}
    return KeyframeBatchEdit(clip_name, _keys_before(project, clip_name, after), after, label="Clear selected part keys")


def capture_pose(project: Project, names: Iterable[str] | None = None) -> dict[str, dict[str, float | bool]]:
    if names is None:
        names = project.rig.instances.keys()
    out: dict[str, dict[str, float | bool]] = {}
    for name in names:
        if name not in project.rig.instances:
            continue
        i = project.rig.instances[name]
        out[name] = {
            "x": i.x, "y": i.y, "rotation": i.rotation, "local_rotation": i.local_rotation,
            "scale_x": i.scale_x, "scale_y": i.scale_y, "visible": i.visible,
        }
    return out


def mirror_pose(project: Project, pose: dict[str, dict[str, float | bool]]) -> dict[str, dict[str, float | bool]]:
    def mirror_name(name: str) -> str | None:
        for a, b in (("left_", "right_"), ("right_", "left_"), ("_left", "_right"), ("_right", "_left")):
            if a in name:
                return name.replace(a, b, 1)
        return None
    by_sprite: dict[str, list[str]] = {}
    for n, inst in project.rig.instances.items():
        by_sprite.setdefault(inst.sprite, []).append(n)
    out: dict[str, dict[str, float | bool]] = {}
    for name, vals in pose.items():
        if name not in project.rig.instances:
            continue
        inst = project.rig.instances[name]
        target = mirror_name(name)
        if not target or target not in project.rig.instances:
            ms = mirror_name(inst.sprite)
            target = by_sprite.get(ms or "", [None])[0]
        if target:
            d = dict(vals)
            for ch in ("rotation", "local_rotation"):
                if ch in d:
                    d[ch] = -float(d[ch])
            out[target] = d
    return out


def blend_pose(a: dict[str, dict[str, float | bool]], b: dict[str, dict[str, float | bool]], t: float) -> dict[str, dict[str, float | bool]]:
    t = max(0.0, min(1.0, float(t)))
    out: dict[str, dict[str, float | bool]] = {}
    for name in sorted(set(a) | set(b)):
        av = a.get(name, {})
        bv = b.get(name, {})
        vals: dict[str, float | bool] = {}
        for k in sorted(set(av) | set(bv)):
            if k == "visible":
                vals[k] = bool(bv.get(k, av.get(k, True))) if t >= 0.5 else bool(av.get(k, bv.get(k, True)))
            else:
                aa = float(av.get(k, bv.get(k, 0.0)))
                bb = float(bv.get(k, av.get(k, 0.0)))
                vals[k] = aa + (bb - aa) * t
        out[name] = vals
    return out


def pose_to_keyframes(project: Project, clip_name: str, pose: dict[str, dict[str, float | bool]], frame: float) -> SetManyKeyframes:
    clip = project.clips.get(clip_name)
    changes: list[tuple[str, str, float, float | None, float]] = []
    for name, vals in pose.items():
        if name not in project.rig.instances:
            continue
        inst = project.rig.instances[name]
        allowed = ("x", "y", "rotation", "scale_x", "scale_y") if inst.parent is None else ("local_rotation", "scale_x", "scale_y")
        for ch in allowed:
            if ch not in vals:
                continue
            before = None
            if clip and name in clip.tracks:
                before = clip.tracks[name].channels.get(ch, {}).get(frame)
            changes.append((name, ch, frame, before, float(vals[ch])))
    return SetManyKeyframes(clip_name, changes, label="Apply pose")


def backup_path(path: str | Path, *, now: float | None = None) -> Path:
    path = Path(path)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now or time.time()))
    return path.with_name(path.stem + f".bak_{stamp}" + path.suffix)


def autosave_path(path: str | Path) -> Path:
    path = Path(path)
    return path.with_name(path.stem + ".autosave" + path.suffix)


def save_with_backup(project: Project, path: str | Path) -> Path | None:
    path = Path(path)
    made: Path | None = None
    if path.exists():
        made = backup_path(path)
        shutil.copy2(path, made)
    save_project(project, path)
    return made


def autosave(project: Project, path: str | Path) -> Path:
    out = autosave_path(path)
    save_project(project, out)
    return out


def recent_files_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "recent_files.json"


def add_recent_file(config_dir: str | Path, path: str | Path, *, limit: int = 10) -> list[str]:
    file = recent_files_path(config_dir)
    file.parent.mkdir(parents=True, exist_ok=True)
    items: list[str] = []
    if file.exists():
        try:
            items = [str(x) for x in json.loads(file.read_text(encoding="utf-8"))]
        except Exception:
            items = []
    p = str(Path(path))
    items = [p] + [x for x in items if x != p]
    items = items[:limit]
    file.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return items


def missing_images(project: Project, project_path: str | Path | None = None) -> list[Path]:
    if not project.sheet.image:
        return []
    path = Path(project.sheet.image)
    if not path.is_absolute() and project_path is not None:
        path = Path(project_path).parent / path
    return [] if path.exists() else [path]


def validate_before_export(project: Project, project_path: str | Path | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        warnings.extend(validate_project(project))
    except Exception as exc:
        errors.extend(str(exc).splitlines())
    for path in missing_images(project, project_path):
        errors.append(f"missing image: {path}")
    if not project.rig.instances:
        warnings.append("project has no rig instances")
    if not project.clips:
        warnings.append("project has no animation clips")
    return errors, warnings
