from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot

from pyspine.core.commands import (
    AddInstance,
    AddSprite,
    DeleteInstance,
    DeleteKeyframe,
    DeleteSprite,
    MoveKeyframe,
    MoveRoot,
    Reparent,
    RenameAttachmentPoint,
    RenameSprite,
    SetAttachmentPoint,
    SetInterpolation,
    SetKeyframe,
    SetManyKeyframes,
    SetNamedPose,
    SetRotation,
    SetZ,
    SetInstanceFields,
)
from pyspine.core.geometry import Rect, Vec2, clamp, rotate
from pyspine.core.model import AttachmentPoint, Clip, Instance, Sprite, Track
from pyspine.core.animation import sample_clip, solve_clip_pose
from pyspine.core.solver import Pose, solve_pose
from pyspine.editor.state import EditorState, TextPrompt
from pyspine.editor.hierarchy import matching_attachment_candidates, would_cycle
from pyspine.editor.timeline import frame_keys_at


@dataclass(slots=True)
class Drag:
    kind: str
    target: str | None
    start_mouse_world: Vec2
    start_value: object
    # A click on a visible sprite should only select it.  The editor creates a
    # candidate drag on mouse-down, but the drag is not considered real until
    # the cursor moves more than a small screen-space threshold.  This prevents
    # Animation mode from immediately IK-keying a limb just because the clicked
    # world point differs from the instance anchor/pivot.
    active: bool = False


class EditorTool:
    def __init__(self) -> None:
        self.drag: Drag | None = None

    def click(self, state: EditorState, world: Vec2, *, modifiers: int = 0) -> None:
        if state.mode == "sprite":
            self._sprite_click(state, world)
        elif state.mode == "rig":
            self._rig_click(state, world, modifiers=modifiers)
        else:
            self._rig_click(state, world, modifiers=modifiers)

    def drag_to(self, state: EditorState, world: Vec2) -> None:
        if self.drag is None:
            return
        if not self._activate_drag_if_threshold_met(state, world):
            return
        if self.drag.kind == "slice_rect":
            start = self.drag.start_mouse_world
            x0, x1 = sorted((start.x, world.x))
            y0, y1 = sorted((start.y, world.y))
            state.pending_rect = Rect(round(x0), round(y0), round(max(1.0, x1 - x0)), round(max(1.0, y1 - y0)))
        elif self.drag.kind == "point" and state.selected_sprite and self.drag.target:
            sprite = state.project.sheet.sprites[state.selected_sprite]
            px = clamp((world.x - sprite.rect.x) / sprite.rect.w, 0.0, 1.0)
            py = clamp((world.y - sprite.rect.y) / sprite.rect.h, 0.0, 1.0)
            point = sprite.points[self.drag.target]
            point.x = px
            point.y = py
            state.dirty = True
            state.message = f"moving point {state.selected_sprite}.{point.name} ({px:.3f}, {py:.3f})"
        elif self.drag.kind == "move" and self.drag.target:
            inst = state.project.rig.instances[self.drag.target]
            sx, sy = self.drag.start_value  # type: ignore[misc]
            if inst.parent is not None:
                # Attached children are not translated in Rig mode.  The rig pose
                # is the constraint graph; dragging a child would silently encode
                # an offset and defeat the attachment point system.  Use Animation
                # mode IK for posing, or explicitly key break_attach on a
                # breakable point if you want a deliberate detached frame.
                inst.x = float(sx); inst.y = float(sy)
                state.hover_snap_parent = None
                state.hover_snap_point = None
                state.message = f"{inst.name} is attached; rotate it or animate/IK it instead"
                return
            dx = world.x - self.drag.start_mouse_world.x
            dy = world.y - self.drag.start_mouse_world.y
            inst.x = float(sx) + dx
            inst.y = float(sy) + dy
            state.dirty = True
            parent, point = self._snap_target_under_mouse(state, world, self.drag.target)
            state.hover_snap_parent = parent
            state.hover_snap_point = point
            if parent and point:
                state.message = f"release to attach {self.drag.target}.{point} -> {parent}.{point}"
            else:
                state.message = f"moving root {self.drag.target} ({inst.x:.1f},{inst.y:.1f})"
        elif self.drag.kind == "anim_move" and self.drag.target:
            if not state.current_clip:
                return
            inst = state.project.rig.instances[self.drag.target]
            if inst.parent is not None:
                # Child translation in Animation mode means IK-pose the connected
                # chain to the mouse, not write child x/y offsets.  The real IK
                # keyframes are committed on release so undo stays clean.
                state.last_mouse_world = world
                state.message = f"release to IK {self.drag.target} to mouse"
                return
            sx, sy, bx, by = self.drag.start_value  # type: ignore[misc]
            dx = world.x - self.drag.start_mouse_world.x
            dy = world.y - self.drag.start_mouse_world.y
            clip = state.project.clips.setdefault(state.current_clip, Clip(state.current_clip, length=max(24.0, state.frame), fps=24.0, loop=True))
            track = clip.tracks.setdefault(self.drag.target, Track(self.drag.target, {}))
            track.channels.setdefault("x", {})[float(state.frame)] = float(sx) + dx
            track.channels.setdefault("y", {})[float(state.frame)] = float(sy) + dy
            state.dirty = True
            state.message = f"key-moving root {self.drag.target}"
        elif self.drag.kind == "anim_ik" and self.drag.target:
            state.last_mouse_world = world
            state.message = f"release to full-chain IK {self.drag.target}"
        elif self.drag.kind == "scale" and self.drag.target:
            inst = state.project.rig.instances[self.drag.target]
            poses = self._poses_for_current_view(state)
            pose = poses[self.drag.target]
            start_sx, start_sy, start_dist = self.drag.start_value  # type: ignore[misc]
            dist = max(1.0e-6, hypot(world.x - pose.anchor.x, world.y - pose.anchor.y))
            factor = max(0.05, dist / max(1.0e-6, float(start_dist)))
            inst.scale_x = max(0.05, float(start_sx) * factor)
            inst.scale_y = max(0.05, float(start_sy) * factor)
            state.dirty = True
        elif self.drag.kind == "rotate" and self.drag.target:
            inst = state.project.rig.instances[self.drag.target]
            poses = self._poses_for_current_view(state)
            pivot = poses[self.drag.target].anchor
            angle = degrees(atan2(world.y - pivot.y, world.x - pivot.x))
            base_mouse_angle, base_rotation = self.drag.start_value  # type: ignore[misc]
            delta = angle - float(base_mouse_angle)
            if inst.parent is None:
                inst.rotation = float(base_rotation) + delta
            else:
                inst.local_rotation = float(base_rotation) + delta
            state.dirty = True
        elif self.drag.kind == "anim_rotate" and self.drag.target:
            # In Animation mode the visible pose comes from the sampled clip, so
            # editing the rest rig makes the handle look dead.  Write a live
            # temporary key at the current frame, then convert it to an undoable
            # SetKeyframe on release.
            poses = self._poses_for_current_view(state)
            if self.drag.target not in poses or not state.current_clip:
                return
            pivot = poses[self.drag.target].anchor
            angle = degrees(atan2(world.y - pivot.y, world.x - pivot.x))
            base_mouse_angle, base_value, channel, _before_key = self.drag.start_value  # type: ignore[misc]
            value = float(base_value) + (angle - float(base_mouse_angle))
            clip = state.project.clips.setdefault(state.current_clip, Clip(state.current_clip, length=max(24.0, state.frame), fps=24.0, loop=True))
            track = clip.tracks.setdefault(self.drag.target, Track(self.drag.target, {}))
            track.channels.setdefault(str(channel), {})[float(state.frame)] = float(value)
            state.dirty = True

    def release(self, state: EditorState) -> None:
        if self.drag is None:
            return
        drag = self.drag
        self.drag = None
        if not drag.active:
            # It was a selection click, not a real drag.  Do not commit move,
            # rotate, IK, point-edit, or slice commands.
            state.hover_snap_parent = None
            state.hover_snap_point = None
            if drag.kind in {"anim_ik", "anim_move"}:
                state.message = f"selected {drag.target}" if drag.target else "selected"
            return
        if drag.kind == "slice_rect" and state.pending_rect:
            rect = state.pending_rect
            state.pending_rect = None
            if rect.w >= 2 and rect.h >= 2:
                name = state.unique_sprite_name("part")
                sprite = Sprite(
                    name=name,
                    rect=rect,
                    points={"origin": AttachmentPoint("origin", 0.5, 0.5)},
                )
                if state.run_command(AddSprite(sprite)):
                    state.selected_sprite = name
                    state.selected_point = "origin"
                    state.text_prompt = TextPrompt("rename_sprite", name, {"old": name})
                    state.message = "created slice; type a better name and press Enter"
        elif drag.kind == "point" and state.selected_sprite and drag.target:
            sprite = state.project.sheet.sprites[state.selected_sprite]
            before = drag.start_value
            after = sprite.points[drag.target]
            if isinstance(before, AttachmentPoint) and (before.x != after.x or before.y != after.y):
                # Restore before, then apply via command so undo/redo remains clean.
                sprite.points[drag.target] = before
                state.run_command(SetAttachmentPoint(state.selected_sprite, drag.target, before, after))
                state.selected_point = drag.target
        elif drag.kind == "move" and drag.target:
            inst = state.project.rig.instances[drag.target]
            before = drag.start_value
            after = (inst.x, inst.y)
            snap_parent = state.hover_snap_parent
            snap_point = state.hover_snap_point
            state.hover_snap_parent = None
            state.hover_snap_point = None
            if snap_parent and snap_point and inst.parent is None:
                # Restore the starting root state, then commit the snap through a
                # Reparent command so undo cleanly returns to the pre-drag root pose.
                inst.x, inst.y = before  # type: ignore[misc]
                state.run_command(Reparent(
                    inst.name,
                    None,
                    None,
                    inst.self_point,
                    snap_parent,
                    snap_point,
                    snap_point if snap_point in state.project.sheet.sprites[inst.sprite].points else inst.self_point,
                    before,
                    None,
                    label="Snap attach instance",
                ))
            elif before != after:
                inst.x, inst.y = before  # type: ignore[misc]
                # MoveRoot is kept for compatibility, but SetInstanceFields works
                # for both roots and attached children.
                state.run_command(SetInstanceFields(inst.name, {"x": before[0], "y": before[1]}, {"x": after[0], "y": after[1]}, label="Move instance"))  # type: ignore[index]
        elif drag.kind == "anim_move" and drag.target:
            clip_name = state.current_clip
            if not clip_name or clip_name not in state.project.clips:
                return
            inst = state.project.rig.instances[drag.target]
            if inst.parent is not None:
                # Safety: attached children should not commit x/y offset keys from
                # Animation-mode dragging.  That operation is handled by anim_ik.
                state.message = f"{drag.target} remains attached; use IK drag for pose"
                return
            sx, sy, before_x, before_y = drag.start_value  # type: ignore[misc]
            clip = state.project.clips[clip_name]
            track = clip.tracks.setdefault(drag.target, Track(drag.target, {}))
            frame = float(state.frame)
            x_keys = track.channels.setdefault("x", {})
            y_keys = track.channels.setdefault("y", {})
            after_x = x_keys.get(frame, sx)
            after_y = y_keys.get(frame, sy)
            if before_x is None:
                x_keys.pop(frame, None)
            else:
                x_keys[frame] = before_x
            if before_y is None:
                y_keys.pop(frame, None)
            else:
                y_keys[frame] = before_y
            changes = []
            if before_x != after_x:
                changes.append((drag.target, "x", frame, before_x, after_x))
            if before_y != after_y:
                changes.append((drag.target, "y", frame, before_y, after_y))
            if changes:
                state.run_command(SetManyKeyframes(clip_name, changes, label="Animate root move"))
        elif drag.kind == "anim_ik" and drag.target:
            clip_name = state.current_clip
            if not clip_name:
                return
            try:
                from pyspine.editor.animation_quality import choose_end_effector_point, whole_chain_ik_keyframes
                end_point = choose_end_effector_point(state.project, drag.target)
                cmd = whole_chain_ik_keyframes(
                    state.project, clip_name, drag.target, state.last_mouse_world, state.frame,
                    end_point=end_point, iterations=18, tolerance=0.75,
                )
                state.run_command(cmd)
                state.message = f"IK keyframed {drag.target}.{end_point}"
            except Exception as exc:
                state.message = f"IK drag failed: {exc}"
        elif drag.kind == "scale" and drag.target:
            inst = state.project.rig.instances[drag.target]
            before_sx, before_sy, _start_dist = drag.start_value  # type: ignore[misc]
            after = {"scale_x": inst.scale_x, "scale_y": inst.scale_y}
            before = {"scale_x": float(before_sx), "scale_y": float(before_sy)}
            if before != after:
                inst.scale_x = float(before_sx); inst.scale_y = float(before_sy)
                state.run_command(SetInstanceFields(inst.name, before, after, label="Scale instance"))
        elif drag.kind == "anim_rotate" and drag.target:
            _base_mouse_angle, _base_value, channel, before_key = drag.start_value  # type: ignore[misc]
            clip_name = state.current_clip
            if not clip_name or clip_name not in state.project.clips:
                return
            clip = state.project.clips[clip_name]
            track = clip.tracks.setdefault(drag.target, Track(drag.target, {}))
            keys = track.channels.setdefault(str(channel), {})
            frame = float(state.frame)
            after = float(keys.get(frame, _base_value))
            # Restore original key state, then apply through the command stack.
            if before_key is None:
                keys.pop(frame, None)
                if not keys:
                    track.channels.pop(str(channel), None)
            else:
                keys[frame] = float(before_key)
            if before_key != after:
                state.run_command(SetKeyframe(clip_name, drag.target, str(channel), frame, before_key, after, label="Animate rotate"))
        elif drag.kind == "rotate" and drag.target:
            inst = state.project.rig.instances[drag.target]
            _, before_rot = drag.start_value  # type: ignore[misc]
            after_rot = inst.rotation if inst.parent is None else inst.local_rotation
            if before_rot != after_rot:
                if inst.parent is None:
                    inst.rotation = float(before_rot)
                    state.run_command(SetRotation(inst.name, float(before_rot), after_rot, local=False))
                else:
                    inst.local_rotation = float(before_rot)
                    state.run_command(SetRotation(inst.name, float(before_rot), after_rot, local=True))


    def _activate_drag_if_threshold_met(self, state: EditorState, world: Vec2) -> bool:
        if self.drag is None:
            return False
        if self.drag.active:
            return True
        # Threshold is in screen pixels converted to world units, so it feels
        # the same at every zoom level.  Six pixels is large enough to absorb
        # normal click jitter but small enough that intentional drags feel
        # immediate.
        threshold = 6.0 / max(0.001, float(state.viewport.zoom))
        dx = world.x - self.drag.start_mouse_world.x
        dy = world.y - self.drag.start_mouse_world.y
        if hypot(dx, dy) < threshold:
            return False
        self.drag.active = True
        return True

    def rotate_selected(self, state: EditorState, degrees_delta: float) -> None:
        if not state.selected:
            return
        inst = state.project.rig.instances[state.selected]
        if state.mode == "animation":
            clip_name = state.current_clip or "anim"
            channel = "rotation" if inst.parent is None else "local_rotation"
            # Start from the sampled visible value so bracket rotation works after
            # IK/keyframed poses, not from the hidden rest rig.
            sampled = sample_clip(state.project, clip_name, state.frame) if clip_name in state.project.clips else {}
            rest = inst.rotation if channel == "rotation" else inst.local_rotation
            before_visible = float(sampled.get(inst.name, {}).get(channel, rest))
            before_key = None
            if clip_name in state.project.clips and inst.name in state.project.clips[clip_name].tracks:
                before_key = state.project.clips[clip_name].tracks[inst.name].channels.get(channel, {}).get(float(state.frame))
            cmd = SetKeyframe(clip_name, inst.name, channel, float(state.frame), before_key, before_visible + degrees_delta, label="Animate rotate")
            state.run_command(cmd)
            state.current_clip = clip_name
            return
        if inst.parent is None:
            cmd = SetRotation(inst.name, inst.rotation, inst.rotation + degrees_delta, local=False)
        else:
            cmd = SetRotation(inst.name, inst.local_rotation, inst.local_rotation + degrees_delta, local=True)
        state.run_command(cmd)

    def adjust_z(self, state: EditorState, delta: int) -> None:
        if not state.selected:
            return
        inst = state.project.rig.instances[state.selected]
        state.run_command(SetZ(inst.name, inst.z, inst.z + delta))

    def add_instance(self, state: EditorState, at: Vec2 | None = None) -> None:
        if not state.selected_sprite:
            state.message = "select a sprite in Sprite mode first"
            return
        name = state.unique_instance_name(state.selected_sprite)
        loc = at or state.last_mouse_world
        z = max((i.z for i in state.project.rig.instances.values()), default=-1) + 1
        inst = Instance(name=name, sprite=state.selected_sprite, x=loc.x, y=loc.y, z=z)
        parent, point = self._auto_attach_target(state, state.selected_sprite)
        if parent and point:
            inst.parent = parent
            inst.parent_point = point
            inst.self_point = point
            inst.x = 0.0
            inst.y = 0.0
        if state.run_command(AddInstance(inst)):
            state.selected = name
            state.mode = "rig"
            if parent and point:
                state.message = f"added {name}; auto-attached {point} to {parent}.{point}"
            else:
                state.message = f"added {name} as root"

    def delete_selected(self, state: EditorState) -> None:
        if state.mode == "sprite" and state.selected_sprite:
            sprite = state.project.sheet.sprites[state.selected_sprite]
            if state.selected_point and state.selected_point != "origin":
                before = sprite.points.get(state.selected_point)
                state.run_command(SetAttachmentPoint(state.selected_sprite, state.selected_point, before, None))
                state.selected_point = "origin"
            else:
                if state.run_command(DeleteSprite(sprite)):
                    state.selected_sprite = next(iter(state.project.sheet.sprites), None)
                    state.selected_point = "origin" if state.selected_sprite else None
        elif state.selected:
            inst = state.project.rig.instances[state.selected]
            if state.run_command(DeleteInstance(inst)):
                state.selected = None

    def prompt_rename(self, state: EditorState) -> None:
        if state.mode == "sprite" and state.selected_sprite and state.selected_point:
            state.text_prompt = TextPrompt(
                "rename_point",
                state.selected_point,
                {"old": state.selected_point, "sprite": state.selected_sprite},
            )
        elif state.mode == "sprite" and state.selected_sprite:
            state.text_prompt = TextPrompt("rename_sprite", state.selected_sprite, {"old": state.selected_sprite})
        elif state.selected:
            state.message = "instance rename not implemented yet"

    def add_point_at_mouse(self, state: EditorState) -> None:
        if not state.selected_sprite:
            return
        sprite = state.project.sheet.sprites[state.selected_sprite]
        world = state.last_mouse_world
        px = clamp((world.x - sprite.rect.x) / sprite.rect.w, 0.0, 1.0)
        py = clamp((world.y - sprite.rect.y) / sprite.rect.h, 0.0, 1.0)
        name = state.unique_point_name("point")
        state.text_prompt = TextPrompt("add_point", name, {"sprite": state.selected_sprite, "x": px, "y": py})
        state.message = "type attachment point name and press Enter"

    def reparent_selected_to_hover(self, state: EditorState, parent: str | None) -> None:
        child = state.selected
        if not child or child == parent:
            return
        inst = state.project.rig.instances[child]
        before_root = (inst.x, inst.y) if inst.parent is None else None
        if parent is None:
            poses = solve_pose(state.project)
            anchor = poses[child].anchor
            after_root = (anchor.x, anchor.y)
            cmd = Reparent(
                child,
                inst.parent,
                inst.parent_point,
                inst.self_point,
                None,
                None,
                inst.self_point,
                before_root,
                after_root,
            )
        else:
            point = self._best_common_point(state, inst.sprite, state.project.rig.instances[parent].sprite)
            if point is None:
                point = "origin"
            cmd = Reparent(
                child,
                inst.parent,
                inst.parent_point,
                inst.self_point,
                parent,
                point,
                point if point in state.project.sheet.sprites[inst.sprite].points else inst.self_point,
                before_root,
                None,
            )
        state.run_command(cmd)


    def set_attachment_pair(self, state: EditorState, parent_point: str, self_point: str) -> None:
        if not state.selected or state.selected not in state.project.rig.instances:
            return
        inst = state.project.rig.instances[state.selected]
        if inst.parent is None:
            state.message = "selected instance has no parent"
            return
        parent = state.project.rig.instances[inst.parent]
        child_sprite = state.project.sheet.sprites[inst.sprite]
        parent_sprite = state.project.sheet.sprites[parent.sprite]
        if self_point not in child_sprite.points:
            state.message = f"child sprite has no point {self_point}"
            return
        if parent_point not in parent_sprite.points:
            state.message = f"parent sprite has no point {parent_point}"
            return
        cmd = Reparent(
            inst.name,
            inst.parent,
            inst.parent_point,
            inst.self_point,
            inst.parent,
            parent_point,
            self_point,
            None,
            None,
            label="Set attachment pair",
        )
        if state.run_command(cmd):
            state.message = f"attached {inst.name}.{self_point} -> {inst.parent}.{parent_point}"

    def cycle_attachment_pair(self, state: EditorState, direction: int = 1) -> None:
        if not state.selected or state.selected not in state.project.rig.instances:
            return
        inst = state.project.rig.instances[state.selected]
        if inst.parent is None:
            state.message = "selected instance has no parent"
            return
        candidates = matching_attachment_candidates(state.project, inst.name, inst.parent)
        if not candidates:
            state.message = "no matching attachment points with parent"
            return
        current = (inst.parent_point, inst.self_point)
        idx = 0
        for i, c in enumerate(candidates):
            if (c.parent_point, c.self_point) == current:
                idx = i
                break
        chosen = candidates[(idx + direction) % len(candidates)]
        self.set_attachment_pair(state, chosen.parent_point, chosen.self_point)

    def set_keyframe(self, state: EditorState) -> None:
        if not state.selected:
            return
        clip_name = state.current_clip or "anim"
        inst = state.project.rig.instances[state.selected]
        channel = "rotation" if inst.parent is None else "local_rotation"
        value = inst.rotation if inst.parent is None else inst.local_rotation
        before = None
        clip = state.project.clips.get(clip_name)
        if clip and state.selected in clip.tracks:
            before = clip.tracks[state.selected].channels.get(channel, {}).get(state.frame)
        state.run_command(SetKeyframe(clip_name, state.selected, channel, state.frame, before, value))
        state.current_clip = clip_name

    def set_pose_keyframes(self, state: EditorState, *, selected_only: bool = False) -> None:
        clip_name = state.current_clip or "anim"
        names = [state.selected] if selected_only and state.selected else list(state.project.rig.instances)
        changes: list[tuple[str, str, float, float | None, float]] = []
        clip = state.project.clips.get(clip_name)
        for name in names:
            if name is None:
                continue
            inst = state.project.rig.instances[name]
            channels: list[tuple[str, float]] = []
            channels.extend([("x", inst.x), ("y", inst.y)])
            if inst.parent is None:
                channels.append(("rotation", inst.rotation))
            else:
                channels.append(("local_rotation", inst.local_rotation))
            channels.extend([("scale_x", inst.scale_x), ("scale_y", inst.scale_y), ("visible", 1.0 if inst.visible else 0.0)])
            for channel, value in channels:
                before = None
                if clip and name in clip.tracks:
                    before = clip.tracks[name].channels.get(channel, {}).get(state.frame)
                changes.append((name, channel, state.frame, before, value))
        if changes and state.run_command(SetManyKeyframes(clip_name, changes)):
            state.current_clip = clip_name

    def delete_keyframe(self, state: EditorState) -> None:
        if not state.selected or not state.current_clip:
            return
        inst = state.project.rig.instances[state.selected]
        channel = "rotation" if inst.parent is None else "local_rotation"
        clip = state.project.clips.get(state.current_clip)
        before = None
        if clip and state.selected in clip.tracks:
            before = clip.tracks[state.selected].channels.get(channel, {}).get(state.frame)
        if before is None:
            state.message = "no selected keyframe at this frame"
            return
        state.run_command(DeleteKeyframe(state.current_clip, state.selected, channel, state.frame, before))

    def toggle_interpolation(self, state: EditorState) -> None:
        if not state.selected:
            return
        clip_name = state.current_clip or "anim"
        inst = state.project.rig.instances[state.selected]
        channel = "rotation" if inst.parent is None else "local_rotation"
        clip = state.project.clips.get(clip_name)
        before = "linear"
        if clip and state.selected in clip.tracks:
            before = clip.tracks[state.selected].interpolation.get(channel, "linear")
        after = "step" if before == "linear" else "linear"
        if state.run_command(SetInterpolation(clip_name, state.selected, channel, before, after)):
            state.current_clip = clip_name
            state.message = f"{state.selected}.{channel} interpolation = {after}"

    def copy_pose(self, state: EditorState, *, selected_only: bool = False) -> None:
        names = [state.selected] if selected_only and state.selected else list(state.project.rig.instances)
        data: dict[str, dict[str, float | bool]] = {}
        for name in names:
            if name is None:
                continue
            inst = state.project.rig.instances[name]
            data[name] = {
                "x": inst.x,
                "y": inst.y,
                "rotation": inst.rotation,
                "local_rotation": inst.local_rotation,
                "scale_x": inst.scale_x,
                "scale_y": inst.scale_y,
                "visible": inst.visible,
                "sprite": inst.sprite,
            }
        state.pose_clipboard = data
        state.message = f"copied {len(data)} pose part(s)"

    def paste_pose(self, state: EditorState) -> None:
        if not state.pose_clipboard:
            state.message = "pose clipboard empty"
            return
        clip_name = state.current_clip or "anim"
        changes: list[tuple[str, str, float, float | None, float]] = []
        clip = state.project.clips.get(clip_name)
        for name, channels in state.pose_clipboard.items():
            if name not in state.project.rig.instances:
                continue
            inst = state.project.rig.instances[name]
            wanted = ["x", "y", "rotation" if inst.parent is None else "local_rotation", "scale_x", "scale_y", "visible", "sprite"]
            for channel in wanted:
                if channel in channels:
                    before = None
                    if clip and name in clip.tracks:
                        before = clip.tracks[name].channels.get(channel, {}).get(state.frame)
                    val = channels[channel]
                    if channel == "sprite":
                        changes.append((name, channel, state.frame, before, str(val)))
                    else:
                        changes.append((name, channel, state.frame, before, float(val)))
        if changes and state.run_command(SetManyKeyframes(clip_name, changes, label="Paste pose as keyframes")):
            state.current_clip = clip_name

    def _poses_for_current_view(self, state: EditorState) -> dict[str, Pose]:
        """Return the pose that is actually visible in the editor.

        This matters in Animation mode: the user is looking at the sampled
        keyframed pose, not the raw rest rig.  Picking against the rest rig
        makes selection feel offset as soon as a root x/y or rotation channel
        has animation data.
        """
        if state.mode == "animation" and state.current_clip and state.current_clip in state.project.clips:
            return solve_clip_pose(state.project, state.current_clip, state.frame)
        return solve_pose(state.project)

    def _sprite_click(self, state: EditorState, world: Vec2) -> None:
        state.last_mouse_world = world
        picked_point = pick_point(state, world)
        if picked_point:
            state.selected_sprite, state.selected_point = picked_point
            point = state.project.sheet.sprites[state.selected_sprite].points[state.selected_point]
            self.drag = Drag("point", state.selected_point, world, AttachmentPoint(point.name, point.x, point.y))
            return
        sprite_name = pick_sprite_rect(state, world)
        if sprite_name:
            state.selected_sprite = sprite_name
            state.selected_point = None
            return
        self.drag = Drag("slice_rect", None, world, None)
        state.pending_rect = Rect(world.x, world.y, 1, 1)

    def _rig_click(self, state: EditorState, world: Vec2, *, modifiers: int = 0) -> None:
        state.last_mouse_world = world
        poses = self._poses_for_current_view(state)
        scale_handle = pick_scale_handle(state, poses, world)
        if scale_handle:
            inst = state.project.rig.instances[scale_handle]
            if getattr(inst, "locked", False):
                state.message = f"{scale_handle} is locked"
                return
            pose = poses[scale_handle]
            dist = max(1.0e-6, hypot(world.x - pose.anchor.x, world.y - pose.anchor.y))
            self.drag = Drag("scale", scale_handle, world, (inst.scale_x, inst.scale_y, dist))
            state.selected = scale_handle
            state.message = f"scaling {scale_handle}"
            return
        handle = pick_rotate_handle(state, poses, world)
        if handle:
            inst = state.project.rig.instances[handle]
            if getattr(inst, "locked", False):
                state.message = f"{handle} is locked"
                return
            pose = poses[handle]
            angle = degrees(atan2(world.y - pose.anchor.y, world.x - pose.anchor.x))
            if state.mode == "animation" and state.current_clip:
                channel = "rotation" if inst.parent is None else "local_rotation"
                sampled = sample_clip(state.project, state.current_clip, state.frame) if state.current_clip in state.project.clips else {}
                rest = inst.rotation if channel == "rotation" else inst.local_rotation
                base = float(sampled.get(handle, {}).get(channel, rest))
                before_key = None
                clip = state.project.clips.get(state.current_clip)
                if clip and handle in clip.tracks:
                    before_key = clip.tracks[handle].channels.get(channel, {}).get(float(state.frame))
                self.drag = Drag("anim_rotate", handle, world, (angle, base, channel, before_key))
                state.message = f"key-rotating {handle}.{channel}"
            else:
                base = inst.rotation if inst.parent is None else inst.local_rotation
                self.drag = Drag("rotate", handle, world, (angle, base))
                state.message = f"rotating {handle}"
            state.selected = handle
            return
        picked = pick_instance(state, poses, world)
        if picked:
            if modifiers & 0x0003 and state.selected and state.selected != picked:
                self.reparent_selected_to_hover(state, picked)
                return
            state.selected = picked
            inst = state.project.rig.instances[picked]
            if getattr(inst, "locked", False):
                state.message = f"{picked} is locked"
                return
            if modifiers & 0x0100:
                pose = poses[picked]
                angle = degrees(atan2(world.y - pose.anchor.y, world.x - pose.anchor.x))
                base = inst.rotation if inst.parent is None else inst.local_rotation
                self.drag = Drag("rotate", picked, world, (angle, base))
            else:
                if state.mode == "animation" and state.current_clip:
                    if inst.parent is not None:
                        self.drag = Drag("anim_ik", picked, world, None)
                        state.last_mouse_world = world
                        state.message = f"drag to IK-pose {picked}; release to key"
                    else:
                        sampled = sample_clip(state.project, state.current_clip, state.frame) if state.current_clip in state.project.clips else {}
                        sx = float(sampled.get(picked, {}).get("x", inst.x))
                        sy = float(sampled.get(picked, {}).get("y", inst.y))
                        before_x = before_y = None
                        clip = state.project.clips.get(state.current_clip)
                        if clip and picked in clip.tracks:
                            before_x = clip.tracks[picked].channels.get("x", {}).get(float(state.frame))
                            before_y = clip.tracks[picked].channels.get("y", {}).get(float(state.frame))
                        self.drag = Drag("anim_move", picked, world, (sx, sy, before_x, before_y))
                        state.message = f"key-moving root {picked}"
                else:
                    self.drag = Drag("move", picked, world, (inst.x, inst.y))
                    state.hover_snap_parent = None
                    state.hover_snap_point = None
            return
        state.selected = None
        state.hover_snap_parent = None
        state.hover_snap_point = None

    def _auto_attach_target(self, state: EditorState, new_sprite_name: str) -> tuple[str | None, str | None]:
        if not state.selected or state.selected not in state.project.rig.instances:
            return None, None
        parent = state.project.rig.instances[state.selected]
        point = self._best_common_point(state, new_sprite_name, parent.sprite)
        return (state.selected, point) if point else (None, None)

    def _best_common_point(self, state: EditorState, child_sprite_name: str, parent_sprite_name: str) -> str | None:
        child = state.project.sheet.sprites[child_sprite_name]
        parent = state.project.sheet.sprites[parent_sprite_name]
        common = set(child.points) & set(parent.points)
        if not common:
            return None
        if state.selected_point in common:
            return state.selected_point
        non_origin = sorted(p for p in common if p != "origin")
        if non_origin:
            return non_origin[0]
        return "origin" if "origin" in common else None

    def _snap_target_under_mouse(self, state: EditorState, world: Vec2, child_name: str) -> tuple[str | None, str | None]:
        if not state.rig_snap_enabled or child_name not in state.project.rig.instances:
            return None, None
        child = state.project.rig.instances[child_name]
        if child.parent is not None:
            return None, None
        poses = self._poses_for_current_view(state)
        parent_name = pick_instance(state, poses, world, exclude=child_name)
        if parent_name is None or parent_name == child_name:
            return None, None
        if would_cycle(state.project, child_name, parent_name):
            return None, None
        parent = state.project.rig.instances[parent_name]
        point = self._best_common_point(state, child.sprite, parent.sprite)
        if point is None or point == "origin":
            return None, None
        return parent_name, point


# Backwards compatible name used by v2 app.
RigTool = EditorTool


def pick_sprite_rect(state: EditorState, world: Vec2) -> str | None:
    best: str | None = None
    best_area = float("inf")
    for sprite in state.project.sheet.sprites.values():
        r = sprite.rect
        if r.x <= world.x <= r.x + r.w and r.y <= world.y <= r.y + r.h:
            area = r.w * r.h
            if area < best_area:
                best = sprite.name
                best_area = area
    return best


def pick_point(state: EditorState, world: Vec2, radius: float | None = None) -> tuple[str, str] | None:
    # Pick radius is expressed in screen pixels, then converted to world units.
    # This keeps handles accurate after zooming instead of making the clickable
    # region balloon/shrink in screen space.
    if radius is None:
        radius = max(1.5, 8.0 / max(0.001, state.viewport.zoom))
    selected_first = []
    if state.selected_sprite and state.selected_sprite in state.project.sheet.sprites:
        selected_first.append(state.project.sheet.sprites[state.selected_sprite])
    rest = [s for s in state.project.sheet.sprites.values() if s.name != state.selected_sprite]
    for sprite in selected_first + rest:
        # Prefer selected point/origin last? Iterate selected point first for easier re-grab.
        ordered = list(sprite.points.values())
        if state.selected_point in sprite.points:
            sel = sprite.points[state.selected_point]
            ordered = [sel] + [p for p in ordered if p.name != sel.name]
        for point in ordered:
            pos = Vec2(sprite.rect.x + point.x * sprite.rect.w, sprite.rect.y + point.y * sprite.rect.h)
            if abs(pos.x - world.x) <= radius and abs(pos.y - world.y) <= radius:
                return (sprite.name, point.name)
    return None


def pick_instance(state: EditorState, poses: dict[str, Pose], world: Vec2, *, exclude: str | None = None) -> str | None:
    best: str | None = None
    for pose in sorted(poses.values(), key=lambda p: (p.z, p.instance), reverse=True):
        if pose.instance == exclude or not pose.visible:
            continue
        sprite = state.project.sheet.sprites[pose.sprite]
        local = rotate(world - pose.top_left, -pose.rotation)
        sx = pose.scale_x if abs(pose.scale_x) > 1.0e-6 else 1.0
        sy = pose.scale_y if abs(pose.scale_y) > 1.0e-6 else 1.0
        local = Vec2(local.x / sx, local.y / sy)
        # The outline is drawn in screen pixels, so hit padding should be screen-aware too.
        pad = max(1.0, 4.0 / max(0.001, state.viewport.zoom))
        if -pad <= local.x <= sprite.rect.w + pad and -pad <= local.y <= sprite.rect.h + pad:
            best = pose.instance
            break
    return best


def rotate_handle_position(state: EditorState, poses: dict[str, Pose], instance: str) -> Vec2 | None:
    pose = poses.get(instance)
    if pose is None:
        return None
    sprite = state.project.sheet.sprites[pose.sprite]
    # Keep the handle visually separated in screen space even when zoomed in/out.
    world_radius = max(sprite.rect.w, sprite.rect.h) * 0.75 + 24.0 / max(0.001, state.viewport.zoom)
    return pose.anchor + rotate(Vec2(0.0, -world_radius), pose.rotation)


def pick_rotate_handle(state: EditorState, poses: dict[str, Pose], world: Vec2) -> str | None:
    if not state.selected or state.selected not in poses:
        return None
    handle = rotate_handle_position(state, poses, state.selected)
    if handle is None:
        return None
    radius = 11.0 / max(0.001, state.viewport.zoom)
    if hypot(handle.x - world.x, handle.y - world.y) <= radius:
        return state.selected
    return None


def scale_handle_position(state: EditorState, poses: dict[str, Pose], instance: str) -> Vec2 | None:
    pose = poses.get(instance)
    if pose is None:
        return None
    sprite = state.project.sheet.sprites[pose.sprite]
    return pose.local_to_world(Vec2(sprite.rect.w, sprite.rect.h))


def pick_scale_handle(state: EditorState, poses: dict[str, Pose], world: Vec2) -> str | None:
    if not state.selected or state.selected not in poses:
        return None
    handle = scale_handle_position(state, poses, state.selected)
    if handle is None:
        return None
    radius = 11.0 / max(0.001, state.viewport.zoom)
    if hypot(handle.x - world.x, handle.y - world.y) <= radius:
        return state.selected
    return None


def _tool_toggle_locked(self: EditorTool, state: EditorState) -> None:
    if not state.selected or state.selected not in state.project.rig.instances:
        return
    inst = state.project.rig.instances[state.selected]
    state.run_command(SetInstanceFields(inst.name, {"locked": inst.locked}, {"locked": not inst.locked}, label="Toggle lock"))


def _tool_toggle_visible(self: EditorTool, state: EditorState) -> None:
    if not state.selected or state.selected not in state.project.rig.instances:
        return
    inst = state.project.rig.instances[state.selected]
    state.run_command(SetInstanceFields(inst.name, {"visible": inst.visible}, {"visible": not inst.visible}, label="Toggle visibility"))


def _tool_set_instance_fields(self: EditorTool, state: EditorState, instance: str, **fields: object) -> None:
    if instance not in state.project.rig.instances:
        return
    inst = state.project.rig.instances[instance]
    before = {k: getattr(inst, k) for k in fields}
    state.run_command(SetInstanceFields(instance, before, fields, label="Set instance properties"))


def _would_cycle(state: EditorState, child_name: str, new_parent_name: str) -> bool:
    cur: str | None = new_parent_name
    while cur is not None:
        if cur == child_name:
            return True
        cur = state.project.rig.instances[cur].parent
    return False


def _mirror_name_token(name: str) -> str | None:
    swaps = [
        ("left_", "right_"), ("right_", "left_"),
        ("_left", "_right"), ("_right", "_left"),
        ("left", "right"), ("right", "left"),
    ]
    for a, b in swaps:
        if a in name:
            return name.replace(a, b, 1)
    return None


def _current_keyable_values(state: EditorState, names: list[str]) -> dict[str, dict[str, float | bool]]:
    overrides: dict[str, dict[str, float | bool]] = {}
    if state.current_clip and state.current_clip in state.project.clips:
        overrides = sample_clip(state.project, state.current_clip, state.frame)
    data: dict[str, dict[str, float | bool]] = {}
    for name in names:
        if name not in state.project.rig.instances:
            continue
        inst = state.project.rig.instances[name]
        ov = overrides.get(name, {})
        data[name] = {
            "x": float(ov.get("x", inst.x)),
            "y": float(ov.get("y", inst.y)),
            "rotation": float(ov.get("rotation", inst.rotation)),
            "local_rotation": float(ov.get("local_rotation", inst.local_rotation)),
            "scale_x": float(ov.get("scale_x", inst.scale_x)),
            "scale_y": float(ov.get("scale_y", inst.scale_y)),
            "visible": bool(ov.get("visible", inst.visible)),
            "sprite": str(ov.get("sprite", inst.sprite)),
        }
    return data


def _instance_mirror_map(state: EditorState) -> dict[str, str]:
    # Prefer sprite-name matching because instance names may be user edited.
    by_sprite: dict[str, list[str]] = {}
    for name, inst in state.project.rig.instances.items():
        by_sprite.setdefault(inst.sprite, []).append(name)
    mapping: dict[str, str] = {}
    for name, inst in state.project.rig.instances.items():
        candidates: list[str] = []
        mirror_sprite = _mirror_name_token(inst.sprite)
        if mirror_sprite and mirror_sprite in by_sprite:
            candidates.extend(by_sprite[mirror_sprite])
        mirror_inst = _mirror_name_token(name)
        if mirror_inst and mirror_inst in state.project.rig.instances:
            candidates.append(mirror_inst)
        for cand in candidates:
            if cand != name:
                mapping[name] = cand
                break
    return mapping


def _pose_to_keyframe_changes(state: EditorState, pose: dict[str, dict[str, float | bool]]) -> list[tuple[str, str, float, float | None, float]]:
    clip_name = state.current_clip or "anim"
    clip = state.project.clips.get(clip_name)
    changes: list[tuple[str, str, float, float | None, float]] = []
    for name, channels in pose.items():
        if name not in state.project.rig.instances:
            continue
        inst = state.project.rig.instances[name]
        wanted = ["x", "y", "rotation" if inst.parent is None else "local_rotation", "scale_x", "scale_y", "visible", "sprite"]
        for channel in wanted:
            if channel not in channels:
                continue
            before = None
            if clip and name in clip.tracks:
                before = clip.tracks[name].channels.get(channel, {}).get(state.frame)
            if channel == "sprite":
                changes.append((name, channel, state.frame, before, str(channels[channel])))
            else:
                changes.append((name, channel, state.frame, before, float(channels[channel])))
    return changes


# Attach v8 methods without disturbing the earlier class body too much.  The
# methods are assigned at module import time, so tests and the editor see them
# as normal EditorTool methods.
def _tool_move_selected_keyframe(self: EditorTool, state: EditorState, new_frame: float) -> None:
    if not state.current_clip or not state.selected_key_instance or not state.selected_key_channel or state.selected_key_frame is None:
        state.message = "no selected keyframe"
        return
    clip = state.project.clips.get(state.current_clip)
    if not clip:
        return
    track = clip.tracks.get(state.selected_key_instance)
    if not track:
        return
    keys = track.channels.get(state.selected_key_channel, {})
    old_frame = float(state.selected_key_frame)
    if old_frame not in keys:
        state.message = "selected keyframe no longer exists"
        return
    new_frame = round(max(0.0, min(clip.length, new_frame)))
    overwritten = keys.get(new_frame) if new_frame != old_frame else None
    value = keys[old_frame]
    if state.run_command(MoveKeyframe(state.current_clip, state.selected_key_instance, state.selected_key_channel, old_frame, new_frame, value, overwritten)):
        state.selected_key_frame = new_frame
        state.frame = new_frame


def _tool_delete_keyframe_v8(self: EditorTool, state: EditorState) -> None:
    if state.current_clip and state.selected_key_instance and state.selected_key_channel and state.selected_key_frame is not None:
        clip = state.project.clips.get(state.current_clip)
        before = None
        if clip and state.selected_key_instance in clip.tracks:
            before = clip.tracks[state.selected_key_instance].channels.get(state.selected_key_channel, {}).get(state.selected_key_frame)
        if before is not None:
            if state.run_command(DeleteKeyframe(state.current_clip, state.selected_key_instance, state.selected_key_channel, state.selected_key_frame, before)):
                state.selected_key_instance = state.selected_key_channel = None
                state.selected_key_frame = None
            return
    # Fall back to the old selected-instance behavior.
    EditorTool._delete_keyframe_old(self, state)  # type: ignore[attr-defined]


def _tool_copy_pose_v8(self: EditorTool, state: EditorState, *, selected_only: bool = False) -> None:
    names = [state.selected] if selected_only and state.selected else list(state.project.rig.instances)
    names = [n for n in names if n]
    state.pose_clipboard = _current_keyable_values(state, names)  # type: ignore[arg-type]
    state.message = f"copied {len(state.pose_clipboard or {})} sampled pose part(s)"


def _tool_copy_frame_keyframes(self: EditorTool, state: EditorState, *, selected_only: bool = False) -> None:
    if not state.current_clip or state.current_clip not in state.project.clips:
        state.message = "no clip selected"
        return
    items = frame_keys_at(state.project.clips[state.current_clip], state.frame)
    if selected_only and state.selected:
        items = [item for item in items if item[0] == state.selected]
    state.frame_clipboard = items
    state.message = f"copied {len(items)} key(s) from frame {state.frame:.0f}"


def _tool_paste_frame_keyframes(self: EditorTool, state: EditorState) -> None:
    if not state.frame_clipboard:
        state.message = "frame clipboard empty"
        return
    clip_name = state.current_clip or "anim"
    clip = state.project.clips.get(clip_name)
    changes: list[tuple[str, str, float, float | None, float]] = []
    for inst_name, channel, value in state.frame_clipboard:
        if inst_name not in state.project.rig.instances:
            continue
        before = None
        if clip and inst_name in clip.tracks:
            before = clip.tracks[inst_name].channels.get(channel, {}).get(state.frame)
        changes.append((inst_name, channel, state.frame, before, str(value) if channel == "sprite" else float(value)))
    if changes and state.run_command(SetManyKeyframes(clip_name, changes, label="Paste frame keyframes")):
        state.current_clip = clip_name
        state.message = f"pasted {len(changes)} key(s) at frame {state.frame:.0f}"


def _tool_mirror_pose_keyframes(self: EditorTool, state: EditorState) -> None:
    mapping = _instance_mirror_map(state)
    if not mapping:
        state.message = "no left/right instance pairs found"
        return
    values = _current_keyable_values(state, list(state.project.rig.instances))
    mirrored: dict[str, dict[str, float | bool]] = {}
    visited: set[str] = set()
    for left, right in mapping.items():
        if left in visited or right in visited:
            continue
        visited.add(left); visited.add(right)
        lv = values.get(left, {})
        rv = values.get(right, {})
        if right in state.project.rig.instances:
            mirrored[left] = dict(rv)
            if "rotation" in mirrored[left]:
                mirrored[left]["rotation"] = -float(mirrored[left]["rotation"])
            if "local_rotation" in mirrored[left]:
                mirrored[left]["local_rotation"] = -float(mirrored[left]["local_rotation"])
        if left in state.project.rig.instances:
            mirrored[right] = dict(lv)
            if "rotation" in mirrored[right]:
                mirrored[right]["rotation"] = -float(mirrored[right]["rotation"])
            if "local_rotation" in mirrored[right]:
                mirrored[right]["local_rotation"] = -float(mirrored[right]["local_rotation"])
    changes = _pose_to_keyframe_changes(state, mirrored)
    if changes and state.run_command(SetManyKeyframes(state.current_clip or "anim", changes, label="Mirror pose keyframes")):
        state.current_clip = state.current_clip or "anim"
        state.message = f"mirrored {len(changes)} channel(s) at frame {state.frame:.0f}"


def _tool_reset_pose_keyframes(self: EditorTool, state: EditorState, *, selected_only: bool = False) -> None:
    names = [state.selected] if selected_only and state.selected else list(state.project.rig.instances)
    pose: dict[str, dict[str, float | bool]] = {}
    for name in names:
        if not name or name not in state.project.rig.instances:
            continue
        inst = state.project.rig.instances[name]
        pose[name] = {
            "x": inst.x,
            "y": inst.y,
            "rotation": inst.rotation,
            "local_rotation": inst.local_rotation,
            "scale_x": inst.scale_x,
            "scale_y": inst.scale_y,
            "visible": inst.visible,
            "sprite": inst.sprite,
        }
    changes = _pose_to_keyframe_changes(state, pose)
    if changes and state.run_command(SetManyKeyframes(state.current_clip or "anim", changes, label="Reset pose keyframes")):
        state.current_clip = state.current_clip or "anim"
        state.message = f"reset {len(changes)} channel(s) at frame {state.frame:.0f}"


def _tool_save_named_pose(self: EditorTool, state: EditorState, name: str, *, selected_only: bool = False) -> None:
    names = [state.selected] if selected_only and state.selected else list(state.project.rig.instances)
    names = [n for n in names if n]
    pose = _current_keyable_values(state, names)  # type: ignore[arg-type]
    before = dict(state.project.metadata.get("named_poses", {})).get(name)
    if state.run_command(SetNamedPose(name, before, pose, label="Save named pose")):
        state.message = f"saved pose {name!r} with {len(pose)} part(s)"


def _tool_apply_named_pose(self: EditorTool, state: EditorState, name: str) -> None:
    pose = dict(state.project.metadata.get("named_poses", {})).get(name)
    if not isinstance(pose, dict):
        state.message = f"pose {name!r} missing"
        return
    # pyright/mypy do not know this is the expected nested dictionary, but the
    # JSON format keeps it as plain metadata deliberately.
    changes = _pose_to_keyframe_changes(state, pose)  # type: ignore[arg-type]
    if changes and state.run_command(SetManyKeyframes(state.current_clip or "anim", changes, label="Apply named pose")):
        state.current_clip = state.current_clip or "anim"
        state.message = f"applied pose {name!r} at frame {state.frame:.0f}"


def _tool_reparent_instance_to_parent(self: EditorTool, state: EditorState, child: str, parent: str | None) -> None:
    old_selected = state.selected
    state.selected = child
    try:
        self.reparent_selected_to_hover(state, parent)
    finally:
        state.selected = child if child in state.project.rig.instances else old_selected


# Preserve old methods for fallbacks, then patch in v8 behavior.
if not hasattr(EditorTool, "_delete_keyframe_old"):
    EditorTool._delete_keyframe_old = EditorTool.delete_keyframe  # type: ignore[attr-defined]
EditorTool.move_selected_keyframe = _tool_move_selected_keyframe  # type: ignore[attr-defined]
EditorTool.delete_keyframe = _tool_delete_keyframe_v8  # type: ignore[method-assign]
EditorTool.copy_pose = _tool_copy_pose_v8  # type: ignore[method-assign]
EditorTool.copy_frame_keyframes = _tool_copy_frame_keyframes  # type: ignore[attr-defined]
EditorTool.paste_frame_keyframes = _tool_paste_frame_keyframes  # type: ignore[attr-defined]
EditorTool.mirror_pose_keyframes = _tool_mirror_pose_keyframes  # type: ignore[attr-defined]
EditorTool.reset_pose_keyframes = _tool_reset_pose_keyframes  # type: ignore[attr-defined]
EditorTool.save_named_pose = _tool_save_named_pose  # type: ignore[attr-defined]
EditorTool.apply_named_pose = _tool_apply_named_pose  # type: ignore[attr-defined]
EditorTool.reparent_instance_to_parent = _tool_reparent_instance_to_parent  # type: ignore[attr-defined]


# v12 transform/selection extensions
EditorTool.toggle_locked = _tool_toggle_locked  # type: ignore[attr-defined]
EditorTool.toggle_visible = _tool_toggle_visible  # type: ignore[attr-defined]
EditorTool.set_instance_fields = _tool_set_instance_fields  # type: ignore[attr-defined]
