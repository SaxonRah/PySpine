import pygame
import sys
import math
from typing import Dict, List, Tuple, Optional
from dataclasses import asdict
import os
from enum import Enum

from configuration import *
from data_classes import (
    SpriteRect, SpriteInstance, Bone,
    BoneKeyframe, BoneTransform, BoneLayer, InterpolationType, AttachmentPoint)

# Import the new common modules
from viewport_common import ViewportManager
from drawing_common import draw_grid, draw_panel_background, draw_text_lines, is_in_rect
from bone_common import (
    draw_bone, draw_bone_hierarchy_connections, get_bone_at_position,
    get_bone_start_at_position, get_bone_end_at_position
)
from sprite_common import safe_sprite_extract, draw_sprite_with_origin
from file_common import save_json_project, load_json_project, serialize_dataclass_dict
from event_common import BaseEventHandler
from common import _point_to_line_distance

# Import undo/redo system
from undo_redo_common import UndoRedoMixin, UndoRedoCommand, StateSnapshotCommand
from animation_commands import (
    AddKeyframeCommand, DeleteKeyframeCommand, ModifyKeyframeCommand, MoveKeyframeCommand,
    SetInterpolationCommand, LoadAttachmentConfigurationCommand, LoadAnimationProjectCommand,
    ClearAnimationCommand, BoneManipulationCommand
)

ANIMATION_EDITOR_NAME_VERSION = "ANIMATION EDITOR v0.1"

# Initialize Pygame
pygame.init()


class BoneManipulationMode(Enum):
    TRANSLATION = "translation"
    ROTATION = "rotation"


class BoneAnimationTrack:
    def __init__(self, bone_name: str):
        self.bone_name = bone_name
        self.keyframes: List[BoneKeyframe] = []
        self.selected_keyframe: Optional[int] = None

    def add_keyframe(self, keyframe: BoneKeyframe):
        # Insert keyframe in chronological order
        inserted = False
        for i, kf in enumerate(self.keyframes):
            if kf.time > keyframe.time:
                self.keyframes.insert(i, keyframe)
                inserted = True
                break
        if not inserted:
            self.keyframes.append(keyframe)

    def get_transform_at_time(self, time: float) -> BoneTransform:
        if not self.keyframes:
            return BoneTransform()

        if time <= self.keyframes[0].time:
            return self.keyframes[0].transform

        if time >= self.keyframes[-1].time:
            return self.keyframes[-1].transform

        # Find keyframes to interpolate between
        for i in range(len(self.keyframes) - 1):
            kf1 = self.keyframes[i]
            kf2 = self.keyframes[i + 1]

            if kf1.time <= time <= kf2.time:
                t = (time - kf1.time) / (kf2.time - kf1.time)
                return self._interpolate_transforms(kf1, kf2, t)

        return BoneTransform()

    def get_sprite_at_time(self, time: float) -> Optional[str]:
        """Get the sprite instance ID that should be shown at this time"""
        if not self.keyframes:
            return None

        # Find the most recent keyframe at or before this time that has a sprite
        active_sprite = None
        for kf in self.keyframes:
            if kf.time <= time and kf.sprite_instance_id:
                active_sprite = kf.sprite_instance_id
            elif kf.time > time:
                break

        return active_sprite

    @staticmethod
    def _interpolate_transforms(kf1: BoneKeyframe, kf2: BoneKeyframe, t: float) -> BoneTransform:
        # Apply proper easing curves
        if kf1.interpolation == InterpolationType.EASE_IN:
            t = t * t * t  # Cubic ease in
        elif kf1.interpolation == InterpolationType.EASE_OUT:
            t = 1 - (1 - t) * (1 - t) * (1 - t)  # Cubic ease out
        elif kf1.interpolation == InterpolationType.EASE_IN_OUT:
            if t < 0.5:
                t = 4 * t * t * t
            else:
                t = 1 - pow(-2 * t + 2, 3) / 2
        elif kf1.interpolation == InterpolationType.BEZIER:
            # Simple bezier approximation
            t = t * t * (3.0 - 2.0 * t)

        # Interpolate transforms
        return BoneTransform(
            x=kf1.transform.x + (kf2.transform.x - kf1.transform.x) * t,
            y=kf1.transform.y + (kf2.transform.y - kf1.transform.y) * t,
            rotation=kf1.transform.rotation + (kf2.transform.rotation - kf1.transform.rotation) * t,
            scale=kf1.transform.scale + (kf2.transform.scale - kf1.transform.scale) * t
        )


class BoneAnimationProject:
    def __init__(self):
        self.sprite_sheet = None
        self.sprite_sheet_path = ""
        self.sprites: Dict[str, SpriteRect] = {}
        self.bones: Dict[str, Bone] = {}
        self.sprite_instances: Dict[str, SpriteInstance] = {}
        self.bone_tracks: Dict[str, BoneAnimationTrack] = {}

        # Store original bone positions for animation
        self.original_bone_positions: Dict[str, Tuple[float, float, float]] = {}

        self.current_time: float = 0.0
        self.duration: float = 5.0
        self.fps: int = 30
        self.playing: bool = False
        self.selected_bone: Optional[str] = None

    def load_attachment_configuration(self, filename: str) -> bool:
        """Load sprite attachment configuration from Sprite Attachment Editor with enum support"""
        data = load_json_project(filename)
        if not data:
            return False

        try:
            # Load sprite sheet
            if data.get("sprite_sheet_path"):
                self.sprite_sheet_path = data["sprite_sheet_path"]
                if os.path.exists(self.sprite_sheet_path):
                    self.sprite_sheet = pygame.image.load(self.sprite_sheet_path)

            # Load sprites
            self.sprites = {}
            for name, sprite_data in data.get("sprites", {}).items():
                self.sprites[name] = SpriteRect(**sprite_data)

            # Load bones with enum support
            from file_common import deserialize_bone_data
            self.bones = {}
            for name, bone_data in data.get("bones", {}).items():
                try:
                    self.bones[name] = deserialize_bone_data(bone_data)
                except Exception as e:
                    print(f"Error loading bone {name}: {e}")
                    continue

            # Store original bone positions for animation reference
            self.original_bone_positions = {}
            for name, bone in self.bones.items():
                self.original_bone_positions[name] = (bone.x, bone.y, bone.angle)

            # Load sprite instances with attachment point support
            self.sprite_instances = {}
            for instance_id, instance_data in data.get("sprite_instances", {}).items():
                # Handle attachment point field (new field)
                attachment_point_value = instance_data.get("bone_attachment_point", "start")
                try:
                    attachment_point = AttachmentPoint(attachment_point_value)
                except ValueError:
                    attachment_point = AttachmentPoint.START  # Default fallback

                sprite_instance = SpriteInstance(
                    id=instance_data["id"],
                    sprite_name=instance_data["sprite_name"],
                    bone_name=instance_data.get("bone_name"),
                    offset_x=instance_data.get("offset_x", 0.0),
                    offset_y=instance_data.get("offset_y", 0.0),
                    offset_rotation=instance_data.get("offset_rotation", 0.0),
                    scale=instance_data.get("scale", 1.0),
                    bone_attachment_point=attachment_point
                )

                # Ensure proper scale (fix zero or negative scales)
                if sprite_instance.scale <= 0:
                    sprite_instance.scale = 1.0

                self.sprite_instances[instance_id] = sprite_instance

            # Create animation tracks for each bone
            self.bone_tracks = {}
            for bone_name in self.bones.keys():
                self.bone_tracks[bone_name] = BoneAnimationTrack(bone_name)

            print(
                f"Loaded attachment configuration: {len(self.sprites)} sprites, {len(self.bones)} bones, {len(self.sprite_instances)} instances")
            return True
        except Exception as e:
            print(f"Error loading attachment configuration: {e}")
            return False

    def get_sprite_world_position(self, instance_id: str, time: float) -> Optional[Tuple[float, float]]:
        """Get the world position where the sprite's ORIGIN should be placed"""
        if instance_id not in self.sprite_instances:
            return None

        sprite_instance = self.sprite_instances[instance_id]
        if not sprite_instance.bone_name or sprite_instance.bone_name not in self.bones:
            return None

        # Get animated bone world transform
        bone_x, bone_y, bone_rot, bone_scale = self.get_bone_world_transform(sprite_instance.bone_name, time)
        bone = self.bones[sprite_instance.bone_name]

        # Determine bone attachment position
        if sprite_instance.bone_attachment_point == AttachmentPoint.END:
            attach_x = bone_x + bone.length * math.cos(math.radians(bone_rot))
            attach_y = bone_y + bone.length * math.sin(math.radians(bone_rot))
        else:  # START
            attach_x = bone_x
            attach_y = bone_y

        # Apply sprite's offset rotated by bone's rotation
        bone_rot_rad = math.radians(bone_rot)
        rotated_offset_x = (sprite_instance.offset_x * math.cos(bone_rot_rad) -
                            sprite_instance.offset_y * math.sin(bone_rot_rad))
        rotated_offset_y = (sprite_instance.offset_x * math.sin(bone_rot_rad) +
                            sprite_instance.offset_y * math.cos(bone_rot_rad))

        # This is where the sprite's ORIGIN should be positioned
        sprite_origin_x = attach_x + rotated_offset_x
        sprite_origin_y = attach_y + rotated_offset_y

        return sprite_origin_x, sprite_origin_y

    def get_bone_world_transform(self, bone_name: str, time: float) -> Tuple[float, float, float, float]:
        """Get bone's world transform maintaining hierarchy during animation"""
        if bone_name not in self.bones or bone_name not in self.original_bone_positions:
            return 0, 0, 0, 1

        bone = self.bones[bone_name]

        # Calculate hierarchical transform
        if bone.parent and bone.parent in self.bones:
            # Get parent's world transform first
            parent_x, parent_y, parent_rot, parent_scale = self.get_bone_world_transform(bone.parent, time)
            parent_bone = self.bones[bone.parent]

            # Calculate attachment position based on bone's attachment point
            attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)
            if attachment_point == AttachmentPoint.END:
                # Child attaches to parent's end
                parent_attach_x = parent_x + parent_bone.length * math.cos(math.radians(parent_rot))
                parent_attach_y = parent_y + parent_bone.length * math.sin(math.radians(parent_rot))
            else:  # START
                # Child attaches to parent's start
                parent_attach_x = parent_x
                parent_attach_y = parent_y

            # Get this bone's animation offset
            if bone_name in self.bone_tracks:
                anim_transform = self.bone_tracks[bone_name].get_transform_at_time(time)
            else:
                anim_transform = BoneTransform()

            # Rotate the child's offset by parent's rotation
            if anim_transform.x != 0 or anim_transform.y != 0:
                parent_angle_rad = math.radians(parent_rot)
                rotated_x = (anim_transform.x * math.cos(parent_angle_rad) -
                             anim_transform.y * math.sin(parent_angle_rad))
                rotated_y = (anim_transform.x * math.sin(parent_angle_rad) +
                             anim_transform.y * math.cos(parent_angle_rad))

                world_x = parent_attach_x + rotated_x
                world_y = parent_attach_y + rotated_y
            else:
                world_x = parent_attach_x
                world_y = parent_attach_y

            world_rotation = bone.angle + anim_transform.rotation
            world_scale = max(0.1, anim_transform.scale) if anim_transform.scale != 0 else 1.0

        else:
            # Root bone - use original position + animation
            orig_x, orig_y, orig_angle = self.original_bone_positions[bone_name]

            # Get animated transform
            if bone_name in self.bone_tracks:
                anim_transform = self.bone_tracks[bone_name].get_transform_at_time(time)
            else:
                anim_transform = BoneTransform()

            # Apply animation transform to original position
            world_x = orig_x + anim_transform.x
            world_y = orig_y + anim_transform.y
            world_rotation = orig_angle + anim_transform.rotation
            world_scale = max(0.1, anim_transform.scale) if anim_transform.scale != 0 else 1.0

        return world_x, world_y, world_rotation, world_scale


class BoneAnimationEditor(BaseEventHandler, UndoRedoMixin):
    def __init__(self):
        super().__init__()
        BaseEventHandler.__init__(self)
        UndoRedoMixin.__init__(self)

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(f"{ANIMATION_EDITOR_NAME_VERSION}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        self.project = BoneAnimationProject()

        # UI State with ViewportManager
        main_viewport_height = SCREEN_HEIGHT - TIMELINE_HEIGHT
        initial_offset = [SCREEN_WIDTH // 2, main_viewport_height // 2]
        self.viewport_manager = ViewportManager(initial_offset)
        self.timeline_scroll = 0

        # Bone manipulation mode
        self.bone_manipulation_mode = BoneManipulationMode.TRANSLATION

        # Interaction state
        self.dragging_timeline = False
        self.dragging_keyframe = False
        self.selected_track = None

        # Undo/redo specific state tracking
        self.operation_in_progress = False
        self.drag_start_transform = None
        self.drag_start_keyframe_time = None

        # Simplified bone manipulation states - only one drag state needed
        self.dragging_bone = False
        self.drag_start_pos = None  # Store the starting position for calculations
        self.drag_start_bone_state = None  # Store the bone's initial state when drag starts

        # Timeline interaction
        self.selected_keyframe = None

        # Setup undo/redo key handlers
        self.setup_undo_redo_keys()

        # Setup animation-specific key handlers
        self.setup_animation_keys()

    def setup_animation_keys(self):
        """Setup animation-specific keyboard shortcuts"""
        self.key_handlers.update({
            (pygame.K_SPACE, None): self._toggle_playback,
            (pygame.K_LEFT, None): self._step_backward,
            (pygame.K_RIGHT, None): self._step_forward,
            (pygame.K_HOME, None): self._go_to_start,
            (pygame.K_END, None): self._go_to_end,
            (pygame.K_k, None): self._add_keyframe_at_current_time,
            (pygame.K_1, None): lambda: self._set_keyframe_interpolation(InterpolationType.LINEAR),
            (pygame.K_2, None): lambda: self._set_keyframe_interpolation(InterpolationType.EASE_IN),
            (pygame.K_3, None): lambda: self._set_keyframe_interpolation(InterpolationType.EASE_OUT),
            (pygame.K_4, None): lambda: self._set_keyframe_interpolation(InterpolationType.EASE_IN_OUT),
            (pygame.K_5, None): lambda: self._set_keyframe_interpolation(InterpolationType.BEZIER),
            (pygame.K_a, pygame.K_LCTRL): self._load_attachment_configuration,
            (pygame.K_w, None): self._set_translation_mode,
            (pygame.K_e, None): self._set_rotation_mode,
            (pygame.K_t, None): self._toggle_manipulation_mode,
            (pygame.K_x, pygame.K_LCTRL): self._clear_all_animation,
        })

    def _complete_current_operation(self):
        """Complete any operation that's in progress and create undo command"""
        if not self.operation_in_progress:
            return

        if self.dragging_bone and self.project.selected_bone and self.drag_start_transform:
            # Complete bone manipulation operation
            bone_name = self.project.selected_bone
            track = self.project.bone_tracks.get(bone_name)

            if track:
                # Get current transform at current time
                current_transform = track.get_transform_at_time(self.project.current_time)

                # Check if transform actually changed
                old_transform = self.drag_start_transform
                if (abs(old_transform.x - current_transform.x) > 0.1 or
                        abs(old_transform.y - current_transform.y) > 0.1 or
                        abs(old_transform.rotation - current_transform.rotation) > 0.1 or
                        abs(old_transform.scale - current_transform.scale) > 0.1):
                    manipulation_command = BoneManipulationCommand(
                        track, bone_name, old_transform, current_transform, self.project.current_time,
                        f"{self.bone_manipulation_mode.value.title()} {bone_name}"
                    )
                    # Add command to history without executing (already performed during drag)
                    self.undo_manager.undo_stack.append(manipulation_command)
                    self.undo_manager.redo_stack.clear()
                    print(f"Recorded bone manipulation: {manipulation_command}")

        elif self.dragging_keyframe and self.selected_keyframe and self.drag_start_keyframe_time:
            # Complete keyframe drag operation
            if self.selected_track and self.selected_track in self.project.bone_tracks:
                track = self.project.bone_tracks[self.selected_track]
                if track.selected_keyframe is not None and 0 <= track.selected_keyframe < len(track.keyframes):
                    current_keyframe = track.keyframes[track.selected_keyframe]
                    old_time = self.drag_start_keyframe_time
                    new_time = current_keyframe.time

                    if abs(old_time - new_time) > 0.01:
                        move_command = MoveKeyframeCommand(
                            track, track.selected_keyframe, old_time, new_time,
                            f"Move keyframe to {new_time:.2f}s"
                        )
                        # Add command to history without executing (already performed during drag)
                        self.undo_manager.undo_stack.append(move_command)
                        self.undo_manager.redo_stack.clear()
                        print(f"Recorded keyframe move: {move_command}")

        # Clear operation state
        self.operation_in_progress = False
        self.drag_start_transform = None
        self.drag_start_keyframe_time = None

    # Mode switching methods
    def _set_translation_mode(self):
        self.bone_manipulation_mode = BoneManipulationMode.TRANSLATION
        print("Switched to TRANSLATION mode (Move bones)")

    def _set_rotation_mode(self):
        self.bone_manipulation_mode = BoneManipulationMode.ROTATION
        print("Switched to ROTATION mode (Rotate bones)")

    def _toggle_manipulation_mode(self):
        if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION:
            self._set_rotation_mode()
        else:
            self._set_translation_mode()

    def _clear_all_animation(self):
        """Clear all animation using command system"""
        if any(len(track.keyframes) > 0 for track in self.project.bone_tracks.values()):
            clear_command = ClearAnimationCommand(self.project)
            self.execute_command(clear_command)

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.KEYDOWN:
                if not self.handle_keydown(event):
                    pass

            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._handle_mouse_down(event)

            elif event.type == pygame.MOUSEBUTTONUP:
                self._handle_mouse_up(event)

            elif event.type == pygame.MOUSEMOTION:
                self._handle_mouse_motion(event)

            elif event.type == pygame.MOUSEWHEEL:
                self._handle_mouse_wheel(event)

        return True

    def _handle_mouse_down(self, event):
        if event.button == 1:  # Left click
            self._handle_left_click(event.pos)
        elif event.button == 2:  # Middle click
            self.viewport_manager.dragging_viewport = True
            self.viewport_manager.last_mouse_pos = event.pos

    def _handle_mouse_up(self, event):
        """Complete any undo-enabled operations BEFORE clearing states"""
        if event.button == 1:
            # Complete current operation first
            self._complete_current_operation()

            # Clear all dragging states
            self.dragging_bone = False
            self.drag_start_pos = None
            self.drag_start_bone_state = None

            if self.dragging_keyframe:
                print("COMPLETED: Keyframe drag")
            elif self.dragging_timeline:
                print("COMPLETED: Timeline drag")

            self.dragging_timeline = False
            self.dragging_keyframe = False

        elif event.button == 2:
            self.viewport_manager.dragging_viewport = False

    def _handle_mouse_motion(self, event):
        """Handle mouse motion with mode-based bone manipulation"""
        self.viewport_manager.handle_drag(event.pos)

        if self.dragging_timeline:
            self._handle_timeline_drag(event.pos)
        elif self.dragging_keyframe:
            self._handle_keyframe_drag(event.pos)
        elif self.dragging_bone and self.project.selected_bone:
            # Mode-based bone manipulation
            if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION:
                self._update_bone_translation(event.pos)
            else:  # ROTATION
                self._update_bone_rotation(event.pos)

        self.viewport_manager.last_mouse_pos = event.pos

    def _handle_mouse_wheel(self, event):
        mouse_x, mouse_y = pygame.mouse.get_pos()

        if self._is_in_main_viewport((mouse_x, mouse_y)):
            self.viewport_manager.handle_zoom(event, (mouse_x, mouse_y))

    def _handle_left_click(self, pos):
        x, y = pos

        if x > SCREEN_WIDTH - PROPERTY_PANEL_WIDTH:  # Property panel
            self._handle_property_panel_click(pos)
        elif y > SCREEN_HEIGHT - TIMELINE_HEIGHT:  # Timeline
            self._handle_timeline_click(pos)
        else:  # Main viewport
            self._handle_viewport_click(pos)

    def _handle_viewport_click(self, pos):
        """SIMPLIFIED: Handle clicks in main viewport - unified bone selection"""
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, toolbar_height=0)

        # Use animated bone positions for interaction
        animated_bones = {name: self._get_animated_bone_for_interaction(name) for name in self.project.bones.keys()}

        # Simple bone detection - any part of the bone
        clicked_bone = get_bone_at_position(animated_bones, viewport_pos, self.viewport_manager.viewport_zoom)

        if clicked_bone:
            self.project.selected_bone = clicked_bone
            self.selected_track = clicked_bone

            # Store drag start information for mode-based manipulation
            self.drag_start_pos = viewport_pos
            bone_x, bone_y, bone_rot, _ = self.project.get_bone_world_transform(clicked_bone, self.project.current_time)
            self.drag_start_bone_state = {
                'pos': (bone_x, bone_y),
                'rotation': bone_rot,
                'mouse_offset': (viewport_pos[0] - bone_x, viewport_pos[1] - bone_y)
            }

            # Store initial transform for undo
            track = self.project.bone_tracks.get(clicked_bone)
            if track:
                self.drag_start_transform = track.get_transform_at_time(self.project.current_time)
            else:
                self.drag_start_transform = BoneTransform()

            self.dragging_bone = True
            self.operation_in_progress = True

            mode_desc = "TRANSLATION" if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION else "ROTATION"
            print(f"SELECTED: {clicked_bone} for {mode_desc}")
        else:
            self.project.selected_bone = None
            self.selected_track = None
            self.dragging_bone = False

    def _get_animated_bone_for_interaction(self, bone_name):
        """Create a temporary bone with animated position for interaction detection"""
        if bone_name not in self.project.bones:
            return None

        original_bone = self.project.bones[bone_name]
        world_x, world_y, world_rot, _ = self.project.get_bone_world_transform(bone_name, self.project.current_time)

        # Create a temporary bone with animated transform for interaction
        animated_bone = Bone(
            name=bone_name,
            x=world_x,
            y=world_y,
            length=original_bone.length,
            angle=world_rot,
            parent=original_bone.parent,
            children=original_bone.children[:]
        )
        return animated_bone

    def _handle_timeline_click(self, pos):
        """Handle timeline clicks with bone and keyframe selection"""
        x, y = pos
        timeline_y = SCREEN_HEIGHT - TIMELINE_HEIGHT
        relative_x = x - 50
        timeline_width = SCREEN_WIDTH - PROPERTY_PANEL_WIDTH - 100

        # Check if clicking on bone track names
        if x < 50:
            track_y_offset = y - (timeline_y + 50)
            track_index = int(track_y_offset // 30)
            bone_names = list(self.project.bone_tracks.keys())
            if 0 <= track_index < len(bone_names):
                bone_name = bone_names[track_index]
                self.project.selected_bone = bone_name
                self.selected_track = bone_name
                print(f"Selected bone from timeline: {bone_name}")
                return

        # Check if clicking on keyframes
        for bone_name, track in self.project.bone_tracks.items():
            track_index = list(self.project.bone_tracks.keys()).index(bone_name)
            track_y = timeline_y + 50 + (track_index * 30)

            for i, keyframe in enumerate(track.keyframes):
                kf_x = 50 + (keyframe.time / self.project.duration) * timeline_width

                if abs(x - kf_x) < 10 and abs(y - track_y) < 10:
                    self.selected_track = bone_name
                    self.project.selected_bone = bone_name
                    track.selected_keyframe = i
                    self.selected_keyframe = keyframe
                    self.dragging_keyframe = True
                    self.operation_in_progress = True

                    # Store initial time for undo
                    self.drag_start_keyframe_time = keyframe.time

                    print(f"Selected keyframe {i} for bone {bone_name} at time {keyframe.time:.2f}")
                    return

        # Set current time
        if relative_x > 0:
            self.project.current_time = (relative_x / timeline_width) * self.project.duration
            self.project.current_time = max(0, int(min(self.project.duration, self.project.current_time)))
            self.dragging_timeline = True

    def _handle_timeline_drag(self, pos):
        """Handle timeline dragging"""
        x, y = pos
        relative_x = x - 50
        timeline_width = SCREEN_WIDTH - PROPERTY_PANEL_WIDTH - 100
        self.project.current_time = (relative_x / timeline_width) * self.project.duration
        self.project.current_time = max(0, int(min(self.project.duration, self.project.current_time)))

    def _handle_keyframe_drag(self, pos):
        """Handle keyframe dragging to change time - direct manipulation"""
        if self.selected_keyframe and self.selected_track and self.selected_track in self.project.bone_tracks:
            x, y = pos
            relative_x = x - 50
            timeline_width = SCREEN_WIDTH - PROPERTY_PANEL_WIDTH - 100
            new_time = (relative_x / timeline_width) * self.project.duration
            new_time = max(0, int(min(self.project.duration, new_time)))

            track = self.project.bone_tracks[self.selected_track]
            if track.selected_keyframe is not None and 0 <= track.selected_keyframe < len(track.keyframes):
                track.keyframes[track.selected_keyframe].time = new_time
                # Re-sort keyframes by time
                track.keyframes.sort(key=lambda kf: kf.time)

    def _handle_property_panel_click(self, pos):
        """Handle property panel clicks"""
        pass

    # Animation control methods
    def _toggle_playback(self):
        self.project.playing = not self.project.playing

    def _step_backward(self):
        self.project.current_time = max(0, int(self.project.current_time - 1 / self.project.fps))

    def _step_forward(self):
        self.project.current_time = min(self.project.duration, self.project.current_time + 1 / self.project.fps)

    def _go_to_start(self):
        self.project.current_time = 0

    def _go_to_end(self):
        self.project.current_time = self.project.duration

    # Interpolation methods
    def _set_keyframe_interpolation(self, interp_type: InterpolationType):
        """Set interpolation type for selected keyframe using command system"""
        if (self.selected_keyframe and self.selected_track and
                self.selected_track in self.project.bone_tracks):
            track = self.project.bone_tracks[self.selected_track]
            if track.selected_keyframe is not None and 0 <= track.selected_keyframe < len(track.keyframes):
                keyframe = track.keyframes[track.selected_keyframe]
                old_interpolation = keyframe.interpolation

                if old_interpolation != interp_type:
                    interp_command = SetInterpolationCommand(
                        keyframe, old_interpolation, interp_type,
                        f"Set keyframe interpolation to {interp_type.value}"
                    )
                    self.execute_command(interp_command)

    # Mode-based bone manipulation methods
    def _update_bone_translation(self, pos):
        """Update bone position using translation mode - direct manipulation"""
        if not self.project.selected_bone or not self.drag_start_bone_state:
            return

        viewport_pos = self.viewport_manager.screen_to_viewport(pos, toolbar_height=0)
        bone = self.project.bones[self.project.selected_bone]

        # Calculate the translation offset from the original position
        start_bone_pos = self.drag_start_bone_state['pos']
        mouse_offset = self.drag_start_bone_state['mouse_offset']

        # Calculate the new world position for the bone
        new_world_x = viewport_pos[0] - mouse_offset[0]
        new_world_y = viewport_pos[1] - mouse_offset[1]

        # Calculate the offset relative to the bone's parent or original position
        if bone.parent and bone.parent in self.project.bones:
            parent_x, parent_y, parent_rot, _ = self.project.get_bone_world_transform(bone.parent,
                                                                                      self.project.current_time)
            parent_bone = self.project.bones[bone.parent]

            # Handle different attachment points
            attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)
            if attachment_point == AttachmentPoint.END:
                parent_attach_x = parent_x + parent_bone.length * math.cos(math.radians(parent_rot))
                parent_attach_y = parent_y + parent_bone.length * math.sin(math.radians(parent_rot))
            else:  # START
                parent_attach_x = parent_x
                parent_attach_y = parent_y

            offset_x = new_world_x - parent_attach_x
            offset_y = new_world_y - parent_attach_y
        else:
            # Root bone - offset from original position
            if self.project.selected_bone in self.project.original_bone_positions:
                orig_x, orig_y, orig_angle = self.project.original_bone_positions[self.project.selected_bone]
                offset_x = new_world_x - orig_x
                offset_y = new_world_y - orig_y
            else:
                offset_x = offset_y = 0

        # Get current transform to preserve rotation and scale
        current_track = self.project.bone_tracks.get(self.project.selected_bone)
        if current_track:
            current_transform = current_track.get_transform_at_time(self.project.current_time)
            self._create_or_update_keyframe(self.project.selected_bone, offset_x, offset_y,
                                            current_transform.rotation, current_transform.scale)
        else:
            self._create_or_update_keyframe(self.project.selected_bone, offset_x, offset_y, 0, 0)

    def _update_bone_rotation(self, pos):
        """Update bone rotation using rotation mode - direct manipulation"""
        if not self.project.selected_bone or not self.drag_start_bone_state:
            return

        viewport_pos = self.viewport_manager.screen_to_viewport(pos, toolbar_height=0)
        bone = self.project.bones[self.project.selected_bone]

        # Get the current bone position (not the original)
        current_x, current_y, _, _ = self.project.get_bone_world_transform(self.project.selected_bone,
                                                                           self.project.current_time)

        # Calculate the angle from bone start to mouse position
        dx = viewport_pos[0] - current_x
        dy = viewport_pos[1] - current_y

        new_angle = math.degrees(math.atan2(dy, dx))
        orig_angle = bone.angle
        rotation_offset = new_angle - orig_angle

        # Get current transform to preserve position and scale
        current_track = self.project.bone_tracks.get(self.project.selected_bone)
        if current_track:
            current_transform = current_track.get_transform_at_time(self.project.current_time)
            self._create_or_update_keyframe(self.project.selected_bone,
                                            current_transform.x, current_transform.y,
                                            rotation_offset, current_transform.scale)
        else:
            self._create_or_update_keyframe(self.project.selected_bone, 0, 0, rotation_offset, 0)

        print(f"ROTATING: {self.project.selected_bone} -> {new_angle:.1f} (offset: {rotation_offset:+.1f})")

    def _create_or_update_keyframe(self, bone_name: str, x: float, y: float, rotation: float, scale: float):
        """Create or update keyframe for current time - direct manipulation"""
        if bone_name not in self.project.bone_tracks:
            return

        track = self.project.bone_tracks[bone_name]

        # Check if keyframe exists at current time
        existing_keyframe = None
        for i, kf in enumerate(track.keyframes):
            if abs(kf.time - self.project.current_time) < 0.01:  # Very close to current time
                existing_keyframe = i
                break

        transform = BoneTransform(x=x, y=y, rotation=rotation, scale=scale)

        if existing_keyframe is not None:
            # Update existing keyframe
            track.keyframes[existing_keyframe].transform = transform
        else:
            # Create new keyframe
            keyframe = BoneKeyframe(
                time=self.project.current_time,
                bone_name=bone_name,
                transform=transform
            )
            track.add_keyframe(keyframe)

    def _add_keyframe_at_current_time(self):
        """Add keyframe for selected bone at current time using command system"""
        if not self.project.selected_bone or self.project.selected_bone not in self.project.bone_tracks:
            print("No bone selected for keyframe")
            return

        track = self.project.bone_tracks[self.project.selected_bone]

        # Get current animated transform
        current_transform = track.get_transform_at_time(self.project.current_time)

        keyframe = BoneKeyframe(
            time=self.project.current_time,
            bone_name=self.project.selected_bone,
            transform=current_transform
        )

        add_command = AddKeyframeCommand(track, keyframe)
        self.execute_command(add_command)

    def _load_attachment_configuration(self):
        """Load attachment configuration using command system"""
        filename = "sprite_attachment_config.json"
        if os.path.exists(filename):
            load_command = LoadAttachmentConfigurationCommand(self.project, filename)
            self.execute_command(load_command)
        else:
            print("sprite_attachment_config.json not found. Please run Sprite Attachment Editor first.")

    @staticmethod
    def _is_in_main_viewport(pos):
        """Check if position is in main viewport"""
        x, y = pos
        main_viewport_height = SCREEN_HEIGHT - TIMELINE_HEIGHT
        return (0 < x < SCREEN_WIDTH - PROPERTY_PANEL_WIDTH and
                0 < y < main_viewport_height)

    # Override base class methods
    def delete_selected(self):
        """Delete selected item using command system"""
        if (self.selected_keyframe and self.selected_track and
                self.selected_track in self.project.bone_tracks):
            track = self.project.bone_tracks[self.selected_track]
            if track.selected_keyframe is not None and 0 <= track.selected_keyframe < len(track.keyframes):
                delete_command = DeleteKeyframeCommand(track, track.selected_keyframe)
                self.execute_command(delete_command)
                track.selected_keyframe = None
                self.selected_keyframe = None

    def reset_viewport(self):
        """Reset viewport to default position and zoom"""
        main_viewport_height = SCREEN_HEIGHT - TIMELINE_HEIGHT
        default_offset = [SCREEN_WIDTH // 2, main_viewport_height // 2]
        self.viewport_manager.reset_viewport(default_offset)

    def update(self):
        """Update animation"""
        if self.project.playing:
            dt = self.clock.get_time() / 1000.0
            self.project.current_time += dt

            if self.project.current_time >= self.project.duration:
                self.project.current_time = 0  # Loop

    def draw(self):
        """Main draw function"""
        self.screen.fill(DARK_GRAY)

        self._draw_main_viewport()
        self._draw_timeline()
        self._draw_property_panel()
        self._draw_ui_info()

        pygame.display.flip()

    def _draw_main_viewport(self):
        """Draw main animation viewport"""
        main_viewport_height = SCREEN_HEIGHT - TIMELINE_HEIGHT
        viewport_rect = pygame.Rect(0, 0,
                                    SCREEN_WIDTH - PROPERTY_PANEL_WIDTH,
                                    main_viewport_height)
        pygame.draw.rect(self.screen, BLACK, viewport_rect)
        self.screen.set_clip(viewport_rect)

        draw_grid(self.screen, self.viewport_manager, viewport_rect)
        self._draw_animated_sprites()
        self._draw_animated_skeleton()
        self._draw_mode_indicator()

        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, WHITE, viewport_rect, 2)

    def _draw_mode_indicator(self):
        """Draw mode indicator for current manipulation mode"""
        if self.project.selected_bone:
            bone_x, bone_y, _, _ = self.project.get_bone_world_transform(self.project.selected_bone,
                                                                         self.project.current_time)
            bone_screen = self.viewport_manager.viewport_to_screen((bone_x, bone_y), toolbar_height=0)

            if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION:
                # Draw four-way arrow for translation mode (like Adobe Animate)
                center_x, center_y = bone_screen
                arrow_size = 20
                arrow_color = CYAN

                # Draw plus symbol
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x - arrow_size, center_y),
                                 (center_x + arrow_size, center_y), 3)
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x, center_y - arrow_size),
                                 (center_x, center_y + arrow_size), 3)

                # Draw arrow heads
                head_size = 6
                # Right arrow
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x + arrow_size, center_y),
                                 (center_x + arrow_size - head_size, center_y - head_size), 3)
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x + arrow_size, center_y),
                                 (center_x + arrow_size - head_size, center_y + head_size), 3)
                # Left arrow
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x - arrow_size, center_y),
                                 (center_x - arrow_size + head_size, center_y - head_size), 3)
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x - arrow_size, center_y),
                                 (center_x - arrow_size + head_size, center_y + head_size), 3)
                # Up arrow
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x, center_y - arrow_size),
                                 (center_x - head_size, center_y - arrow_size + head_size), 3)
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x, center_y - arrow_size),
                                 (center_x + head_size, center_y - arrow_size + head_size), 3)
                # Down arrow
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x, center_y + arrow_size),
                                 (center_x - head_size, center_y + arrow_size - head_size), 3)
                pygame.draw.line(self.screen, arrow_color,
                                 (center_x, center_y + arrow_size),
                                 (center_x + head_size, center_y + arrow_size - head_size), 3)

            else:  # ROTATION mode
                # Draw circle for rotation mode (like Adobe Animate)
                center_x, center_y = bone_screen
                circle_radius = 25
                pygame.draw.circle(self.screen, YELLOW, (int(center_x), int(center_y)), circle_radius, 3)

                # Draw rotation arrow
                arc_start_angle = -math.pi / 4
                arc_end_angle = math.pi / 4
                arc_points = []
                for i in range(20):
                    angle = arc_start_angle + (arc_end_angle - arc_start_angle) * i / 19
                    x = center_x + circle_radius * math.cos(angle)
                    y = center_y + circle_radius * math.sin(angle)
                    arc_points.append((x, y))

                if len(arc_points) > 1:
                    pygame.draw.lines(self.screen, YELLOW, False, arc_points, 3)

    def _draw_animated_sprites(self):
        """Draw sprite instances with proper bone rotation inheritance"""
        if not self.project.sprite_sheet:
            return

        # Group sprites by bone layer and sort by layer_order
        layered_sprites = {
            BoneLayer.BEHIND: [],
            BoneLayer.MIDDLE: [],
            BoneLayer.FRONT: []
        }

        # Sort sprites into layers based on their bone's layer and layer_order
        for instance_id, sprite_instance in self.project.sprite_instances.items():
            if sprite_instance.bone_name and sprite_instance.bone_name in self.project.bones:
                if sprite_instance.sprite_name in self.project.sprites:
                    bone = self.project.bones[sprite_instance.bone_name]
                    bone_layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
                    bone_layer_order = getattr(bone, 'layer_order', 0)
                    layered_sprites[bone_layer].append((bone_layer_order, instance_id, sprite_instance))

        # Sort each layer by layer_order (lower numbers render first/behind)
        for layer in layered_sprites:
            layered_sprites[layer].sort(key=lambda x: x[0])

        # Draw sprites in layer order: BEHIND -> MIDDLE -> FRONT
        for layer in [BoneLayer.BEHIND, BoneLayer.MIDDLE, BoneLayer.FRONT]:
            for layer_order, instance_id, sprite_instance in layered_sprites[layer]:
                bone = self.project.bones[sprite_instance.bone_name]
                sprite = self.project.sprites[sprite_instance.sprite_name]

                try:
                    # Get sprite world position using attachment point support
                    sprite_pos = self.project.get_sprite_world_position(instance_id, self.project.current_time)
                    if not sprite_pos:
                        continue

                    sprite_world_x, sprite_world_y = sprite_pos

                    # Get animated bone transform for rotation and scale
                    bone_x, bone_y, bone_rot, bone_scale = self.project.get_bone_world_transform(
                        sprite_instance.bone_name, self.project.current_time)

                    # Calculate only the animation rotation delta
                    # Get the bone's original angle from when the sprite was attached
                    if sprite_instance.bone_name in self.project.original_bone_positions:
                        _, _, original_bone_angle = self.project.original_bone_positions[sprite_instance.bone_name]
                    else:
                        original_bone_angle = bone.angle

                    # Calculate the animation rotation delta (how much the bone has rotated from its original position)
                    animation_rotation_delta = bone_rot - original_bone_angle

                    # The sprite's offset_rotation is the baseline, add only the animation delta
                    total_rotation = sprite_instance.offset_rotation + animation_rotation_delta

                    # Use common sprite drawing function with FIXED rotation
                    draw_sprite_with_origin(
                        self.screen, self.viewport_manager, self.project.sprite_sheet, sprite,
                        (sprite_world_x, sprite_world_y),
                        rotation=total_rotation,  # Now uses sprite baseline + animation delta!
                        scale=bone_scale * sprite_instance.scale,
                        selected=False
                    )

                    # Draw attachment point indicators
                    if sprite_instance.bone_attachment_point == AttachmentPoint.END:
                        attach_x = bone_x + bone.length * math.cos(math.radians(bone_rot))
                        attach_y = bone_y + bone.length * math.sin(math.radians(bone_rot))
                        attachment_color = RED  # Red for END attachment
                    else:  # START
                        attach_x = bone_x
                        attach_y = bone_y
                        attachment_color = BLUE  # Blue for START attachment

                    # Draw connection line from attachment point to sprite
                    attachment_screen = self.viewport_manager.viewport_to_screen((attach_x, attach_y), toolbar_height=0)
                    sprite_screen_pos = self.viewport_manager.viewport_to_screen((sprite_world_x, sprite_world_y),
                                                                                 toolbar_height=0)

                    pygame.draw.circle(self.screen, attachment_color,
                                       (int(attachment_screen[0]), int(attachment_screen[1])), 3)
                    pygame.draw.line(self.screen, attachment_color, attachment_screen, sprite_screen_pos, 1)

                except pygame.error:
                    pass

    def _draw_animated_skeleton(self):
        """Draw animated skeleton with hierarchy connections maintained"""
        # Prepare animated transforms for drawing
        animated_transforms = {}
        for bone_name in self.project.bones.keys():
            animated_transforms[bone_name] = self.project.get_bone_world_transform(
                bone_name, self.project.current_time)

        # Draw hierarchy connections
        draw_bone_hierarchy_connections(self.screen, self.viewport_manager,
                                        self.project.bones, animated_transforms)

        # Draw individual bones
        for bone_name, bone in self.project.bones.items():
            world_x, world_y, world_rot, world_scale = animated_transforms[bone_name]

            # Create a temporary bone with animated transform for drawing
            animated_bone = Bone(
                name=bone_name,
                x=world_x,
                y=world_y,
                length=bone.length,
                angle=world_rot,
                parent=bone.parent,
                children=bone.children[:]
            )

            # Determine bone color based on state
            has_keyframes = bone_name in self.project.bone_tracks and len(
                self.project.bone_tracks[bone_name].keyframes) > 0

            if bone_name == self.project.selected_bone:
                color = ORANGE
            elif has_keyframes:
                color = CYAN  # Bones with keyframes are cyan
            else:
                color = GREEN  # Static bones are green

            draw_bone(self.screen, self.viewport_manager, animated_bone, color,
                      selected=(bone_name == self.project.selected_bone))

            # Draw bone name with attachment info
            if self.viewport_manager.viewport_zoom > 0.4:
                end_x = world_x + bone.length * math.cos(math.radians(world_rot))
                end_y = world_y + bone.length * math.sin(math.radians(world_rot))
                start_screen = self.viewport_manager.viewport_to_screen((world_x, world_y), toolbar_height=0)
                end_screen = self.viewport_manager.viewport_to_screen((end_x, end_y), toolbar_height=0)

                mid_x = (start_screen[0] + end_screen[0]) / 2
                mid_y = (start_screen[1] + end_screen[1]) / 2
                text_color = ORANGE if bone_name == self.project.selected_bone else color

                # Show attachment point info for child bones
                attachment_info = ""
                if bone.parent:
                    attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)
                    attachment_char = "E" if attachment_point == AttachmentPoint.END else "S"
                    attachment_info = f"->{attachment_char}"

                display_name = f"{bone_name}{attachment_info}"
                text = self.small_font.render(display_name, True, text_color)
                self.screen.blit(text, (mid_x, mid_y - 15))

    def _draw_timeline(self):
        """Draw animation timeline with better selection"""
        timeline_y = SCREEN_HEIGHT - TIMELINE_HEIGHT
        timeline_rect = pygame.Rect(0, timeline_y, SCREEN_WIDTH - PROPERTY_PANEL_WIDTH, TIMELINE_HEIGHT)
        pygame.draw.rect(self.screen, GRAY, timeline_rect)

        timeline_width = SCREEN_WIDTH - PROPERTY_PANEL_WIDTH - 100
        for i in range(int(self.project.duration) + 1):
            x = 50 + (i / self.project.duration) * timeline_width
            pygame.draw.line(self.screen, BLACK, (x, timeline_y), (x, timeline_y + 20))

            time_text = self.small_font.render(f"{i}s", True, BLACK)
            self.screen.blit(time_text, (x - 10, timeline_y + 25))

        # Current time indicator
        current_x = 50 + (self.project.current_time / self.project.duration) * timeline_width
        pygame.draw.line(self.screen, YELLOW, (current_x, timeline_y), (current_x, timeline_y + TIMELINE_HEIGHT))

        # Draw bone tracks
        y_offset = 50
        for bone_name, track in self.project.bone_tracks.items():
            track_y = timeline_y + y_offset

            # Highlight selected track
            is_selected = bone_name == self.selected_track
            color = YELLOW if is_selected else WHITE

            # Track name (clickable)
            track_text = self.small_font.render(bone_name, True, color)
            self.screen.blit(track_text, (5, track_y - 10))

            # Track background for selected
            if is_selected:
                track_bg = pygame.Rect(0, track_y - 15, 45, 25)
                pygame.draw.rect(self.screen, (64, 64, 0), track_bg)

            # Track line
            pygame.draw.line(self.screen, LIGHT_GRAY, (50, track_y),
                             (SCREEN_WIDTH - PROPERTY_PANEL_WIDTH - 50, track_y), 1)

            # Keyframes with interpolation colors
            for i, keyframe in enumerate(track.keyframes):
                kf_x = 50 + (keyframe.time / self.project.duration) * timeline_width

                # Color based on interpolation type
                if i == track.selected_keyframe:
                    kf_color = YELLOW
                elif keyframe.interpolation == InterpolationType.LINEAR:
                    kf_color = WHITE
                elif keyframe.interpolation == InterpolationType.EASE_IN:
                    kf_color = RED
                elif keyframe.interpolation == InterpolationType.EASE_OUT:
                    kf_color = BLUE
                elif keyframe.interpolation == InterpolationType.EASE_IN_OUT:
                    kf_color = PURPLE
                elif keyframe.interpolation == InterpolationType.BEZIER:
                    kf_color = GREEN
                else:
                    kf_color = WHITE

                # Draw circle for bone keyframes
                pygame.draw.circle(self.screen, kf_color, (int(kf_x), int(track_y)), 6)
                pygame.draw.circle(self.screen, BLACK, (int(kf_x), int(track_y)), 6, 2)

            y_offset += 30

    def _draw_property_panel(self):
        """Draw property panel with enhanced undo/redo and mode information"""
        panel_rect = pygame.Rect(SCREEN_WIDTH - PROPERTY_PANEL_WIDTH, 0,
                                 PROPERTY_PANEL_WIDTH, SCREEN_HEIGHT)
        draw_panel_background(self.screen, panel_rect)

        y_offset = 20

        title = self.font.render(f"{ANIMATION_EDITOR_NAME_VERSION}", True, BLACK)
        self.screen.blit(title, (panel_rect.x + 10, y_offset))
        y_offset += 40

        # Enhanced undo/redo status
        y_offset = self._draw_undo_redo_status(panel_rect, y_offset)

        # Mode indicator
        mode_text = f"Mode: {self.bone_manipulation_mode.value.upper()}"
        mode_color = CYAN if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION else YELLOW
        mode_surface = self.small_font.render(mode_text, True, mode_color)
        self.screen.blit(mode_surface, (panel_rect.x + 10, y_offset))
        y_offset += 25

        time_text = self.small_font.render(f"Time: {self.project.current_time:.2f}s", True, BLACK)
        self.screen.blit(time_text, (panel_rect.x + 10, y_offset))
        y_offset += 25

        # Selected keyframe info
        if self.selected_keyframe:
            kf_text = self.small_font.render("Selected Keyframe:", True, RED)
            self.screen.blit(kf_text, (panel_rect.x + 10, y_offset))
            y_offset += 20

            kf_info = [
                f"  Time: {self.selected_keyframe.time:.2f}s",
                f"  Bone: {self.selected_keyframe.bone_name}",
                f"  Interpolation: {self.selected_keyframe.interpolation.value}",
                f"  Transform: ({self.selected_keyframe.transform.x:.1f}, {self.selected_keyframe.transform.y:.1f})",
                f"  Rotation: {self.selected_keyframe.transform.rotation:.1f}"
            ]

            y_offset = draw_text_lines(self.screen, self.small_font, kf_info,
                                       (panel_rect.x + 10, y_offset), BLACK, 18)

        # Selected bone info
        if self.project.selected_bone:
            bone_text = self.small_font.render(f"Bone: {self.project.selected_bone}", True, BLACK)
            self.screen.blit(bone_text, (panel_rect.x + 10, y_offset))
            y_offset += 25

            bone = self.project.bones[self.project.selected_bone]
            # Show both original and animated positions
            orig_x, orig_y, orig_angle = self.project.original_bone_positions.get(self.project.selected_bone, (0, 0, 0))
            anim_x, anim_y, anim_rot, anim_scale = self.project.get_bone_world_transform(self.project.selected_bone,
                                                                                         self.project.current_time)

            # Show attachment point information
            attachment_info = ""
            if bone.parent:
                attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)
                attachment_info = f"Attachment: {attachment_point.value.upper()}"

            props = [
                f"Original: ({orig_x:.1f}, {orig_y:.1f}, {orig_angle:.1f})",
                f"Animated: ({anim_x:.1f}, {anim_y:.1f}, {anim_rot:.1f})",
                f"Length: {bone.length:.1f}",
                f"Parent: {bone.parent or 'None'}",
                attachment_info,
                f"Children: {len(bone.children)}",
                f"Keyframes: {len(self.project.bone_tracks.get(self.project.selected_bone, BoneAnimationTrack('')).keyframes)}"
            ]

            # Filter out empty strings
            props = [prop for prop in props if prop]

            y_offset = draw_text_lines(self.screen, self.small_font, props,
                                       (panel_rect.x + 10, y_offset), BLACK, 18)

        # Project stats
        y_offset += 20
        stats = [
            f"Sprites: {len(self.project.sprites)}",
            f"Instances: {len(self.project.sprite_instances)}",
            f"Bones: {len(self.project.bones)}",
            f"Total Keyframes: {sum(len(track.keyframes) for track in self.project.bone_tracks.values())}"
        ]

        y_offset = draw_text_lines(self.screen, self.small_font, stats,
                                   (panel_rect.x + 10, y_offset), BLACK, 18)

        # Instructions
        y_offset += 20
        instructions = [
            ANIMATION_EDITOR_NAME_VERSION,
            "",
            "UNDO/REDO:",
            "Ctrl+Z: Undo | Ctrl+Y: Redo",
            f"History: {len(self.undo_manager.undo_stack)} actions",
            "",
            "MODE SWITCHING:",
            "W: Translation Mode",
            "E: Rotation Mode",
            "T: Toggle Mode",
            "",
            "ANIMATION:",
            "SPACE: Play/Pause",
            "<-/->: Frame step",
            "HOME/END: Start/End",
            "K: Add keyframe",
            "",
            "TRANSLATION MODE:",
            "• Plus symbol indicator",
            "• Drag any part of bone",
            "• Moves bone position",
            "• Auto-creates keyframes",
            "",
            "ROTATION MODE:",
            "• Circle indicator",
            "• Drag any part of bone",
            "• Rotates around base",
            "• Auto-creates keyframes",
            "",
            "EASING (select keyframe):",
            "1: Linear  2: Ease In  3: Ease Out",
            "4: Ease In/Out  5: Bezier",
            "",
            "FILES:",
            "Ctrl+A: Load attachments",
            "Ctrl+S: Save animation",
            "Ctrl+L: Load animation",
            "",
            "WORKFLOW:",
            "1. Load attachment config",
            "2. Select bone",
            "3. Choose mode (W/E)",
            "4. Drag to animate",
            "5. Keyframes auto-created"
        ]

        for instruction in instructions:
            if instruction:
                if instruction.startswith(ANIMATION_EDITOR_NAME_VERSION):
                    color = GREEN
                elif instruction.startswith("COMPLETE UNDO/REDO SYSTEM"):
                    color = CYAN
                elif instruction.startswith(
                        ("ALL OPERATIONS", "UNDO/REDO", "MODE SWITCHING", "ANIMATION", "TRANSLATION MODE",
                         "ROTATION MODE", "EASING",
                         "FILES", "WORKFLOW")):
                    color = RED
                elif instruction.startswith(("✓", "•")):
                    color = GREEN if instruction.startswith("✓") else BLUE
                elif instruction.startswith(("Ctrl+Z", "Ctrl+Y", "History")):
                    color = CYAN
                else:
                    color = BLACK
                text = self.small_font.render(instruction, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 16

    def _draw_undo_redo_status(self, panel_rect, y_offset):
        """Draw undo/redo status information with more detail"""
        # Undo status
        if self.can_undo():
            undo_color = BLACK
            last_action = str(self.undo_manager.undo_stack[-1])
            if len(last_action) > 20:
                last_action = last_action[:17] + "..."
            undo_text = f"Undo: {last_action}"
        else:
            undo_color = GRAY
            undo_text = "Undo: No actions"

        # Redo status
        if self.can_redo():
            redo_color = BLACK
            next_action = str(self.undo_manager.redo_stack[-1])
            if len(next_action) > 20:
                next_action = next_action[:17] + "..."
            redo_text = f"Redo: {next_action}"
        else:
            redo_color = GRAY
            redo_text = "Redo: No actions"

        # History count
        history_text = f"History: {len(self.undo_manager.undo_stack)}/{self.undo_manager.history_limit}"

        undo_surface = self.small_font.render(undo_text, True, undo_color)
        redo_surface = self.small_font.render(redo_text, True, redo_color)
        history_surface = self.small_font.render(history_text, True, BLUE)

        self.screen.blit(undo_surface, (panel_rect.x + 10, y_offset))
        self.screen.blit(redo_surface, (panel_rect.x + 10, y_offset + 18))
        self.screen.blit(history_surface, (panel_rect.x + 10, y_offset + 36))

        return y_offset + 60

    def _draw_ui_info(self):
        """Draw UI information with complete undo/redo status"""
        play_text = "PAUSE" if self.project.playing else "PLAY"
        play_surface = self.font.render(play_text, True, WHITE)
        self.screen.blit(play_surface, (10, 10))

        # Mode status
        mode_desc = "TRANSLATE" if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION else "ROTATE"
        mode_color = CYAN if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION else YELLOW

        status_lines = [
            f"{ANIMATION_EDITOR_NAME_VERSION}",
            f"Mode: {mode_desc} (W/E to switch)"
        ]

        # Add enhanced undo/redo status
        if self.can_undo():
            last_action = str(self.undo_manager.undo_stack[-1])
            if len(last_action) > 40:
                last_action = last_action[:37] + "..."
            status_lines.extend([
                f"Last Action: {last_action}",
                f"Undo Stack: {len(self.undo_manager.undo_stack)} | Redo Stack: {len(self.undo_manager.redo_stack)}"
            ])
        else:
            status_lines.extend([
                "No actions to undo",
                f"History: {len(self.undo_manager.undo_stack)} actions (max: {self.undo_manager.history_limit})"
            ])

        # Add operation status
        if self.operation_in_progress:
            if self.dragging_bone:
                mode_desc = "TRANSLATING" if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION else "ROTATING"
                status_lines.append(f"{mode_desc} - Release to record in history")
            elif self.dragging_keyframe:
                status_lines.append("MOVING KEYFRAME - Release to record in history")

        for i, line in enumerate(status_lines):
            if line.startswith(ANIMATION_EDITOR_NAME_VERSION):
                color = GREEN
            elif line.startswith("Last Action") and self.can_undo():
                color = CYAN
            elif line.startswith(("TRANSLATING", "ROTATING", "MOVING KEYFRAME")):
                color = ORANGE
            elif line.startswith("ALL OPERATIONS"):
                color = YELLOW
            elif line.startswith("✓"):
                color = GREEN
            elif line == "":
                continue
            else:
                color = WHITE

            text = self.small_font.render(line, True, color)
            self.screen.blit(text, (10, 40 + i * 18))

    def save_project(self):
        """Save animation data with attachment point support"""
        animation_data = {
            "duration": self.project.duration,
            "fps": self.project.fps,
            "original_bone_positions": self.project.original_bone_positions,
            "sprite_instances": serialize_dataclass_dict(self.project.sprite_instances),
            "bone_tracks": {}
        }

        for bone_name, track in self.project.bone_tracks.items():
            if track.keyframes:
                track_data = {
                    "keyframes": []
                }

                for keyframe in track.keyframes:
                    kf_data = {
                        "time": keyframe.time,
                        "transform": asdict(keyframe.transform),
                        "interpolation": keyframe.interpolation.value,
                        "sprite_instance_id": keyframe.sprite_instance_id
                    }
                    track_data["keyframes"].append(kf_data)

                animation_data["bone_tracks"][bone_name] = track_data

        save_json_project("bone_animation.json", animation_data, "Bone animation saved successfully!")

    def load_project(self):
        """Load animation data using command system"""
        filename = "bone_animation.json"
        if os.path.exists(filename):
            load_command = LoadAnimationProjectCommand(self.project, filename)
            self.execute_command(load_command)
        else:
            print("bone_animation.json not found")

    def run(self):
        """Main run loop"""
        running = True
        while running:
            running = self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    editor = BoneAnimationEditor()

    # Autoload attachment configuration if it exists (disable undo tracking during autoload)
    if os.path.exists("sprite_attachment_config.json"):
        editor.undo_manager.disable()
        editor.project.load_attachment_configuration("sprite_attachment_config.json")
        editor.undo_manager.enable()
        editor.clear_history()

    editor.run()
