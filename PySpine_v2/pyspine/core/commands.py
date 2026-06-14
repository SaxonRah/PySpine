from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .model import AttachmentPoint, Clip, Instance, Project, Sprite, Track
from .validation import validate_project


class Command(Protocol):
    label: str

    def apply(self, project: Project) -> None: ...

    def undo(self, project: Project) -> None: ...


def _validate(project: Project) -> None:
    validate_project(project)


@dataclass(slots=True)
class MoveRoot:
    instance: str
    before: tuple[float, float]
    after: tuple[float, float]
    label: str = "Move root"

    def apply(self, project: Project) -> None:
        inst = project.rig.instances[self.instance]
        inst.x, inst.y = self.after

    def undo(self, project: Project) -> None:
        inst = project.rig.instances[self.instance]
        inst.x, inst.y = self.before


@dataclass(slots=True)
class SetRotation:
    instance: str
    before: float
    after: float
    local: bool = True
    label: str = "Rotate instance"

    def apply(self, project: Project) -> None:
        inst = project.rig.instances[self.instance]
        if self.local:
            inst.local_rotation = self.after
        else:
            inst.rotation = self.after

    def undo(self, project: Project) -> None:
        inst = project.rig.instances[self.instance]
        if self.local:
            inst.local_rotation = self.before
        else:
            inst.rotation = self.before


@dataclass(slots=True)
class SetZ:
    instance: str
    before: int
    after: int
    label: str = "Set draw order"

    def apply(self, project: Project) -> None:
        project.rig.instances[self.instance].z = self.after

    def undo(self, project: Project) -> None:
        project.rig.instances[self.instance].z = self.before


@dataclass(slots=True)
class Reparent:
    instance: str
    before_parent: str | None
    before_parent_point: str | None
    before_self_point: str
    after_parent: str | None
    after_parent_point: str | None
    after_self_point: str
    before_root_pos: tuple[float, float] | None = None
    after_root_pos: tuple[float, float] | None = None
    label: str = "Reparent instance"

    def apply(self, project: Project) -> None:
        self._set(project, self.after_parent, self.after_parent_point, self.after_self_point, self.after_root_pos)
        _validate(project)

    def undo(self, project: Project) -> None:
        self._set(project, self.before_parent, self.before_parent_point, self.before_self_point, self.before_root_pos)
        _validate(project)

    def _set(
        self,
        project: Project,
        parent: str | None,
        parent_point: str | None,
        self_point: str,
        root_pos: tuple[float, float] | None,
    ) -> None:
        inst = project.rig.instances[self.instance]
        inst.parent = parent
        inst.parent_point = parent_point
        inst.self_point = self_point
        if parent is None and root_pos is not None:
            inst.x, inst.y = root_pos


@dataclass(slots=True)
class AddSprite:
    sprite: Sprite
    label: str = "Add sprite slice"

    def apply(self, project: Project) -> None:
        if self.sprite.name in project.sheet.sprites:
            raise ValueError(f"sprite {self.sprite.name!r} already exists")
        project.sheet.sprites[self.sprite.name] = self.sprite
        _validate(project)

    def undo(self, project: Project) -> None:
        project.sheet.sprites.pop(self.sprite.name, None)
        _validate(project)


@dataclass(slots=True)
class DeleteSprite:
    sprite: Sprite
    label: str = "Delete sprite slice"

    def apply(self, project: Project) -> None:
        users = [i.name for i in project.rig.instances.values() if i.sprite == self.sprite.name]
        if users:
            raise ValueError(f"cannot delete sprite used by instances: {', '.join(users)}")
        project.sheet.sprites.pop(self.sprite.name, None)
        _validate(project)

    def undo(self, project: Project) -> None:
        project.sheet.sprites[self.sprite.name] = self.sprite
        _validate(project)


@dataclass(slots=True)
class RenameSprite:
    before: str
    after: str
    label: str = "Rename sprite"

    def apply(self, project: Project) -> None:
        self._rename(project, self.before, self.after)
        _validate(project)

    def undo(self, project: Project) -> None:
        self._rename(project, self.after, self.before)
        _validate(project)

    def _rename(self, project: Project, src: str, dst: str) -> None:
        if src not in project.sheet.sprites:
            raise KeyError(src)
        if dst in project.sheet.sprites:
            raise ValueError(f"sprite {dst!r} already exists")
        sprite = project.sheet.sprites.pop(src)
        sprite.name = dst
        project.sheet.sprites[dst] = sprite
        for inst in project.rig.instances.values():
            if inst.sprite == src:
                inst.sprite = dst


@dataclass(slots=True)
class SetSpriteRect:
    sprite_name: str
    before: tuple[float, float, float, float]
    after: tuple[float, float, float, float]
    label: str = "Set sprite rectangle"

    def apply(self, project: Project) -> None:
        from .geometry import Rect

        project.sheet.sprites[self.sprite_name].rect = Rect(*self.after)
        _validate(project)

    def undo(self, project: Project) -> None:
        from .geometry import Rect

        project.sheet.sprites[self.sprite_name].rect = Rect(*self.before)
        _validate(project)


@dataclass(slots=True)
class SetAttachmentPoint:
    sprite_name: str
    point_name: str
    before: AttachmentPoint | None
    after: AttachmentPoint | None
    label: str = "Set attachment point"

    def apply(self, project: Project) -> None:
        self._set(project, self.after)
        _validate(project)

    def undo(self, project: Project) -> None:
        self._set(project, self.before)
        _validate(project)

    def _set(self, project: Project, point: AttachmentPoint | None) -> None:
        points = project.sheet.sprites[self.sprite_name].points
        if point is None:
            if self.point_name == "origin":
                raise ValueError("cannot delete required origin point")
            points.pop(self.point_name, None)
        else:
            points[self.point_name] = point


@dataclass(slots=True)
class RenameAttachmentPoint:
    sprite_name: str
    before: str
    after: str
    label: str = "Rename attachment point"

    def apply(self, project: Project) -> None:
        self._rename(project, self.before, self.after)
        _validate(project)

    def undo(self, project: Project) -> None:
        self._rename(project, self.after, self.before)
        _validate(project)

    def _rename(self, project: Project, src: str, dst: str) -> None:
        sprite = project.sheet.sprites[self.sprite_name]
        if src not in sprite.points:
            raise KeyError(src)
        if dst in sprite.points:
            raise ValueError(f"point {dst!r} already exists")
        point = sprite.points.pop(src)
        point.name = dst
        sprite.points[dst] = point
        for inst in project.rig.instances.values():
            if inst.sprite == self.sprite_name and inst.self_point == src:
                inst.self_point = dst
            if inst.parent is not None:
                parent = project.rig.instances.get(inst.parent)
                if parent and parent.sprite == self.sprite_name and inst.parent_point == src:
                    inst.parent_point = dst


@dataclass(slots=True)
class AddInstance:
    instance: Instance
    label: str = "Add instance"

    def apply(self, project: Project) -> None:
        if self.instance.name in project.rig.instances:
            raise ValueError(f"instance {self.instance.name!r} already exists")
        project.rig.instances[self.instance.name] = self.instance
        _validate(project)

    def undo(self, project: Project) -> None:
        project.rig.instances.pop(self.instance.name, None)
        for clip in project.clips.values():
            clip.tracks.pop(self.instance.name, None)
        _validate(project)


@dataclass(slots=True)
class DeleteInstance:
    instance: Instance
    label: str = "Delete instance"

    def apply(self, project: Project) -> None:
        children = [i.name for i in project.rig.instances.values() if i.parent == self.instance.name]
        if children:
            raise ValueError(f"cannot delete instance with children: {', '.join(children)}")
        project.rig.instances.pop(self.instance.name, None)
        for clip in project.clips.values():
            clip.tracks.pop(self.instance.name, None)
        _validate(project)

    def undo(self, project: Project) -> None:
        project.rig.instances[self.instance.name] = self.instance
        _validate(project)


@dataclass(slots=True)
class SetKeyframe:
    clip_name: str
    instance: str
    channel: str
    frame: float
    before: Any | None
    after: Any
    label: str = "Set keyframe"

    def apply(self, project: Project) -> None:
        track = _ensure_track(project, self.clip_name, self.instance)
        track.channels.setdefault(self.channel, {})[self.frame] = self.after
        _validate(project)

    def undo(self, project: Project) -> None:
        track = _ensure_track(project, self.clip_name, self.instance)
        channel = track.channels.setdefault(self.channel, {})
        if self.before is None:
            channel.pop(self.frame, None)
            if not channel:
                track.channels.pop(self.channel, None)
        else:
            channel[self.frame] = self.before
        _validate(project)


@dataclass(slots=True)
class SetInstanceFields:
    instance: str
    before: dict[str, object]
    after: dict[str, object]
    label: str = "Set instance properties"

    def apply(self, project: Project) -> None:
        self._set(project, self.after)
        _validate(project)

    def undo(self, project: Project) -> None:
        self._set(project, self.before)
        _validate(project)

    def _set(self, project: Project, values: dict[str, object]) -> None:
        inst = project.rig.instances[self.instance]
        for key, value in values.items():
            if not hasattr(inst, key):
                raise AttributeError(key)
            setattr(inst, key, value)


@dataclass(slots=True)
class KeyframeBatchEdit:
    clip_name: str
    before: dict[tuple[str, str, float], Any]
    after: dict[tuple[str, str, float], Any | None]
    label: str = "Edit keyframes"

    def apply(self, project: Project) -> None:
        self._apply(project, self.after)
        _validate(project)

    def undo(self, project: Project) -> None:
        undo_map: dict[tuple[str, str, float], float | None] = {k: v for k, v in self.before.items()}
        for k in self.after:
            if k not in undo_map:
                undo_map[k] = None
        self._apply(project, undo_map)
        _validate(project)

    def _apply(self, project: Project, changes: dict[tuple[str, str, float], Any | None]) -> None:
        clip = project.clips.get(self.clip_name)
        if clip is None:
            clip = Clip(self.clip_name, length=24.0, fps=24.0, loop=True)
            project.clips[self.clip_name] = clip
        for (inst_name, channel, frame), value in changes.items():
            track = clip.tracks.get(inst_name)
            if value is None:
                if not track:
                    continue
                keys = track.channels.get(channel)
                if not keys:
                    continue
                keys.pop(frame, None)
                if not keys:
                    track.channels.pop(channel, None)
                    track.interpolation.pop(channel, None)
                if not track.channels:
                    clip.tracks.pop(inst_name, None)
                continue
            track = _ensure_track(project, self.clip_name, inst_name)
            track.channels.setdefault(channel, {})[float(frame)] = value


def _ensure_track(project: Project, clip_name: str, instance: str) -> Track:
    if clip_name not in project.clips:
        project.clips[clip_name] = Clip(name=clip_name, length=24.0, fps=24.0, loop=True)
    clip = project.clips[clip_name]
    if instance not in clip.tracks:
        clip.tracks[instance] = Track(instance=instance, channels={})
    return clip.tracks[instance]


@dataclass(slots=True)
class DeleteKeyframe:
    clip_name: str
    instance: str
    channel: str
    frame: float
    before: Any | None
    label: str = "Delete keyframe"

    def apply(self, project: Project) -> None:
        clip = project.clips.get(self.clip_name)
        if clip is None:
            return
        track = clip.tracks.get(self.instance)
        if track is None:
            return
        keys = track.channels.get(self.channel)
        if keys is None:
            return
        keys.pop(self.frame, None)
        if not keys:
            track.channels.pop(self.channel, None)
            track.interpolation.pop(self.channel, None)
        if not track.channels:
            clip.tracks.pop(self.instance, None)
        _validate(project)

    def undo(self, project: Project) -> None:
        if self.before is None:
            return
        track = _ensure_track(project, self.clip_name, self.instance)
        track.channels.setdefault(self.channel, {})[self.frame] = self.before
        _validate(project)


@dataclass(slots=True)
class SetInterpolation:
    clip_name: str
    instance: str
    channel: str
    before: str
    after: str
    label: str = "Set interpolation"

    def apply(self, project: Project) -> None:
        track = _ensure_track(project, self.clip_name, self.instance)
        if self.after == "linear":
            track.interpolation.pop(self.channel, None)
        else:
            track.interpolation[self.channel] = self.after
        _validate(project)

    def undo(self, project: Project) -> None:
        track = _ensure_track(project, self.clip_name, self.instance)
        if self.before == "linear":
            track.interpolation.pop(self.channel, None)
        else:
            track.interpolation[self.channel] = self.before
        _validate(project)


@dataclass(slots=True)
class SetManyKeyframes:
    clip_name: str
    changes: list[tuple[str, str, float, Any | None, Any]]
    label: str = "Set pose keyframes"

    def apply(self, project: Project) -> None:
        for instance, channel, frame, _before, after in self.changes:
            track = _ensure_track(project, self.clip_name, instance)
            track.channels.setdefault(channel, {})[frame] = after
        _validate(project)

    def undo(self, project: Project) -> None:
        for instance, channel, frame, before, _after in reversed(self.changes):
            track = _ensure_track(project, self.clip_name, instance)
            keys = track.channels.setdefault(channel, {})
            if before is None:
                keys.pop(frame, None)
                if not keys:
                    track.channels.pop(channel, None)
                    track.interpolation.pop(channel, None)
            else:
                keys[frame] = before
            if not track.channels:
                project.clips[self.clip_name].tracks.pop(instance, None)
        _validate(project)


@dataclass(slots=True)
class MoveKeyframe:
    clip_name: str
    instance: str
    channel: str
    before_frame: float
    after_frame: float
    value: Any
    overwritten_after: Any | None = None
    label: str = "Move keyframe"

    def apply(self, project: Project) -> None:
        if self.before_frame == self.after_frame:
            return
        track = _ensure_track(project, self.clip_name, self.instance)
        keys = track.channels.setdefault(self.channel, {})
        keys.pop(self.before_frame, None)
        keys[self.after_frame] = self.value
        _validate(project)

    def undo(self, project: Project) -> None:
        if self.before_frame == self.after_frame:
            return
        track = _ensure_track(project, self.clip_name, self.instance)
        keys = track.channels.setdefault(self.channel, {})
        keys.pop(self.after_frame, None)
        keys[self.before_frame] = self.value
        if self.overwritten_after is not None:
            keys[self.after_frame] = self.overwritten_after
        _validate(project)


@dataclass(slots=True)
class SetNamedPose:
    name: str
    before: dict | None
    after: dict | None
    label: str = "Set named pose"

    def apply(self, project: Project) -> None:
        poses = project.metadata.setdefault("named_poses", {})
        if self.after is None:
            poses.pop(self.name, None)
        else:
            poses[self.name] = self.after
        _validate(project)

    def undo(self, project: Project) -> None:
        poses = project.metadata.setdefault("named_poses", {})
        if self.before is None:
            poses.pop(self.name, None)
        else:
            poses[self.name] = self.before
        _validate(project)
