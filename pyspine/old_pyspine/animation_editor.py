# animation_editor.py - Complete animation editor built on the base system
import pygame
import math
import os
import time
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass
from enum import Enum
from core_base import UniversalEditor, Command


# Data structures from previous editors
@dataclass
class SpriteRect:
    name: str
    x: int
    y: int
    width: int
    height: int
    origin_x: float = 0.5
    origin_y: float = 0.5


@dataclass
class SpriteInstance:
    id: str
    sprite_name: str
    bone_name: Optional[str] = None
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_rotation: float = 0.0
    scale: float = 1.0
    bone_attachment_point: 'AttachmentPoint' = None

    def __post_init__(self):
        if self.bone_attachment_point is None:
            self.bone_attachment_point = AttachmentPoint.START


@dataclass
class Bone:
    name: str
    x: float
    y: float
    length: float
    angle: float = 0.0
    parent: Optional[str] = None
    parent_attachment_point: 'AttachmentPoint' = None
    children: List[str] = None
    layer: 'BoneLayer' = None
    layer_order: int = 0

    def __post_init__(self):
        if self.children is None:
            self.children = []
        if self.parent_attachment_point is None:
            self.parent_attachment_point = AttachmentPoint.END
        if self.layer is None:
            self.layer = BoneLayer.MIDDLE


@dataclass
class BoneTransform:
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale: float = 1.0


@dataclass
class BoneKeyframe:
    time: float
    bone_name: str
    transform: BoneTransform
    interpolation: 'InterpolationType' = None
    sprite_instance_id: Optional[str] = None

    def __post_init__(self):
        if self.interpolation is None:
            self.interpolation = InterpolationType.LINEAR


class BoneLayer(Enum):
    BEHIND = "behind"
    MIDDLE = "middle"
    FRONT = "front"


class AttachmentPoint(Enum):
    START = "start"
    END = "end"


class InterpolationType(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    BEZIER = "bezier"


class BoneManipulationMode(Enum):
    TRANSLATION = "translation"
    ROTATION = "rotation"


class BoneAnimationTrack:
    """Animation track for a single bone"""

    def __init__(self, bone_name: str):
        self.bone_name = bone_name
        self.keyframes: List[BoneKeyframe] = []
        self.selected_keyframe: Optional[int] = None

    def add_keyframe(self, keyframe: BoneKeyframe):
        """Add keyframe in chronological order"""
        inserted = False
        for i, kf in enumerate(self.keyframes):
            if kf.time > keyframe.time:
                self.keyframes.insert(i, keyframe)
                inserted = True
                break
        if not inserted:
            self.keyframes.append(keyframe)

    def get_transform_at_time(self, time: float) -> BoneTransform:
        """Get interpolated transform at given time"""
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

    def _interpolate_transforms(self, kf1: BoneKeyframe, kf2: BoneKeyframe, t: float) -> BoneTransform:
        """Interpolate between two keyframes with easing"""
        # Apply easing curve
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
            t = t * t * (3.0 - 2.0 * t)  # Smooth step

        # Linear interpolation between transforms
        return BoneTransform(
            x=kf1.transform.x + (kf2.transform.x - kf1.transform.x) * t,
            y=kf1.transform.y + (kf2.transform.y - kf1.transform.y) * t,
            rotation=kf1.transform.rotation + (kf2.transform.rotation - kf1.transform.rotation) * t,
            scale=kf1.transform.scale + (kf2.transform.scale - kf1.transform.scale) * t
        )


class AnimationEditor(UniversalEditor):
    """Complete animation editor implementation"""

    def __init__(self):
        super().__init__()

        # Asset loading
        self.sprite_sheet = None
        self.sprite_sheet_path = ""

        # Animation state
        self.current_time = 0.0
        self.duration = 5.0
        self.fps = 30
        self.playing = False
        self.last_update_time = 0.0

        # Original bone positions (for animation reference)
        self.original_bone_positions: Dict[str, Tuple[float, float, float]] = {}

        # Bone manipulation
        self.bone_manipulation_mode = BoneManipulationMode.TRANSLATION
        self.dragging_bone = False
        self.drag_start_bone_state = None
        self.drag_start_pos = None

        # Timeline interaction
        self.timeline_scroll = 0
        self.dragging_timeline = False
        self.dragging_keyframe = False
        self.selected_keyframe = None
        self.selected_track = None
        self.drag_start_keyframe_time = None

        # UI state
        self.timeline_height = 200

        # Try to auto-load attachment configuration
        self.try_auto_load()

    def setup_data_structures(self):
        """Setup animation editor data structures"""
        self.data_objects = {
            'sprites': {},  # SpriteRect definitions
            'bones': {},  # Bone definitions
            'sprite_instances': {},  # SpriteInstance objects
            'bone_tracks': {},  # BoneAnimationTrack objects
        }

    def setup_key_bindings(self):
        """Setup animation editor key bindings"""
        pass  # Use base class bindings

    def get_editor_name(self) -> str:
        return "Animation Editor v1.0"

    def build_hierarchy(self):
        """Build hierarchy from bones and tracks"""
        self.hierarchy_nodes.clear()

        # Add root bones and build tree
        for bone_name, bone in self.data_objects['bones'].items():
            if bone.parent is None:
                self.add_hierarchy_node(
                    bone_name,
                    f"BONE[{bone_name}]",
                    'bones',
                    metadata={'bone': bone}
                )
                self._add_bone_children(bone_name)

    def _add_bone_children(self, parent_bone_name):
        """Recursively add bone children to hierarchy"""
        parent_bone = self.data_objects['bones'][parent_bone_name]

        for child_name in parent_bone.children:
            if child_name in self.data_objects['bones']:
                child_bone = self.data_objects['bones'][child_name]
                attachment_char = "E" if child_bone.parent_attachment_point == AttachmentPoint.END else "S"

                self.add_hierarchy_node(
                    child_name,
                    f"BONE[{child_name}]->{attachment_char}",
                    'bones',
                    parent_id=parent_bone_name,
                    metadata={'bone': child_bone}
                )
                self._add_bone_children(child_name)

        # Add sprite instances attached to this bone
        for instance_id, sprite_instance in self.data_objects['sprite_instances'].items():
            if sprite_instance.bone_name == parent_bone_name:
                attachment_char = "E" if sprite_instance.bone_attachment_point == AttachmentPoint.END else "S"
                self.add_hierarchy_node(
                    instance_id,
                    f"SPRT[{sprite_instance.sprite_name}]->{attachment_char}",
                    'sprite_instances',
                    parent_id=parent_bone_name,
                    metadata={'sprite_instance': sprite_instance}
                )

    def get_object_type_color(self, object_type: str) -> Tuple[int, int, int]:
        """Get color for object type icon"""
        colors = {
            'sprites': (255, 100, 100),
            'bones': (100, 255, 100),
            'sprite_instances': (100, 100, 255),
            'bone_tracks': (255, 255, 100)
        }
        return colors.get(object_type, (128, 128, 128))

    def try_auto_load(self):
        """Try to auto-load attachment configuration"""
        if os.path.exists("sprite_attachment_editor_project.json"):
            self.load_attachment_configuration("sprite_attachment_editor_project.json")

        # Try to load existing animation
        if os.path.exists("animation_editor_project.json"):
            self.load_project()

    # ========================================================================
    # EVENT HANDLING OVERRIDES
    # ========================================================================

    def handle_keydown(self, event) -> bool:
        """Handle animation editor specific keys"""
        if super().handle_keydown(event):
            return True

        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]
        shift_pressed = pygame.key.get_pressed()[pygame.K_LSHIFT]

        # Animation playback controls
        if event.key == pygame.K_SPACE:
            self.toggle_playback()
            return True
        elif event.key == pygame.K_LEFT:
            self.step_backward()
            return True
        elif event.key == pygame.K_RIGHT:
            self.step_forward()
            return True
        elif event.key == pygame.K_HOME:
            self.go_to_start()
            return True
        elif event.key == pygame.K_END:
            self.go_to_end()
            return True

        # Keyframe operations
        elif event.key == pygame.K_k:
            self.add_keyframe_at_current_time()
            return True

        # Interpolation shortcuts
        elif event.key == pygame.K_1:
            self.set_keyframe_interpolation(InterpolationType.LINEAR)
            return True
        elif event.key == pygame.K_2:
            self.set_keyframe_interpolation(InterpolationType.EASE_IN)
            return True
        elif event.key == pygame.K_3:
            self.set_keyframe_interpolation(InterpolationType.EASE_OUT)
            return True
        elif event.key == pygame.K_4:
            self.set_keyframe_interpolation(InterpolationType.EASE_IN_OUT)
            return True
        elif event.key == pygame.K_5:
            self.set_keyframe_interpolation(InterpolationType.BEZIER)
            return True

        # Bone manipulation modes
        elif event.key == pygame.K_w:
            self.set_translation_mode()
            return True
        elif event.key == pygame.K_e:
            self.set_rotation_mode()
            return True
        elif event.key == pygame.K_t:
            self.toggle_manipulation_mode()
            return True

        # File operations
        elif ctrl_pressed and event.key == pygame.K_a:
            self.load_attachment_configuration_dialog()
            return True
        elif ctrl_pressed and event.key == pygame.K_x:
            self.clear_all_animation()
            return True

        return False

    def handle_viewport_click(self, pos):
        """Handle clicks in main viewport for bone manipulation"""
        viewport_pos = self.screen_to_viewport(pos)

        # Check for timeline clicks first
        if pos[1] > self.screen.get_height() - self.timeline_height:
            self.handle_timeline_click(pos)
            return

        # Use animated bone positions for interaction
        animated_bones = {name: self.get_animated_bone_for_interaction(name)
                          for name in self.data_objects['bones'].keys()}

        # Simple bone detection
        clicked_bone = self.get_bone_at_position(animated_bones, viewport_pos)

        if clicked_bone:
            self.select_object('bones', clicked_bone)
            self.selected_track = clicked_bone

            # Store drag start information for manipulation
            self.drag_start_pos = viewport_pos
            bone_x, bone_y, bone_rot, _ = self.get_bone_world_transform(clicked_bone, self.current_time)
            self.drag_start_bone_state = {
                'pos': (bone_x, bone_y),
                'rotation': bone_rot,
                'mouse_offset': (viewport_pos[0] - bone_x, viewport_pos[1] - bone_y)
            }

            # Store initial transform for undo
            track = self.data_objects['bone_tracks'].get(clicked_bone)
            if track:
                self.drag_start_data = {
                    'type': 'bone_manipulation',
                    'bone_name': clicked_bone,
                    'old_transform': track.get_transform_at_time(self.current_time)
                }
            else:
                self.drag_start_data = {
                    'type': 'bone_manipulation',
                    'bone_name': clicked_bone,
                    'old_transform': BoneTransform()
                }

            self.dragging_bone = True
            self.operation_in_progress = True

            mode_desc = "TRANSLATION" if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION else "ROTATION"
            print(f"SELECTED: {clicked_bone} for {mode_desc}")
        else:
            self.clear_selection()
            self.selected_track = None
            self.dragging_bone = False

    def handle_timeline_click(self, pos):
        """Handle timeline clicks for time scrubbing and keyframe selection"""
        x, y = pos
        timeline_y = self.screen.get_height() - self.timeline_height
        relative_x = x - 50
        timeline_width = self.screen.get_width() - 300 - 100

        # Check if clicking on bone track names
        if x < 50:
            track_y_offset = y - (timeline_y + 50)
            track_index = int(track_y_offset // 30)
            bone_names = list(self.data_objects['bone_tracks'].keys())
            if 0 <= track_index < len(bone_names):
                bone_name = bone_names[track_index]
                self.select_object('bones', bone_name)
                self.selected_track = bone_name
                print(f"Selected bone from timeline: {bone_name}")
                return

        # Check if clicking on keyframes
        for bone_name, track in self.data_objects['bone_tracks'].items():
            track_index = list(self.data_objects['bone_tracks'].keys()).index(bone_name)
            track_y = timeline_y + 50 + (track_index * 30)

            for i, keyframe in enumerate(track.keyframes):
                kf_x = 50 + (keyframe.time / self.duration) * timeline_width

                if abs(x - kf_x) < 10 and abs(y - track_y) < 10:
                    self.selected_track = bone_name
                    self.select_object('bones', bone_name)
                    track.selected_keyframe = i
                    self.selected_keyframe = keyframe
                    self.dragging_keyframe = True
                    self.operation_in_progress = True

                    # Store initial time for undo
                    self.drag_start_keyframe_time = keyframe.time

                    print(f"Selected keyframe {i} for bone {bone_name} at time {keyframe.time:.2f}")
                    return

        # Set current time by clicking on timeline
        if relative_x > 0:
            self.current_time = (relative_x / timeline_width) * self.duration
            self.current_time = max(0, min(self.duration, self.current_time))
            self.dragging_timeline = True

    def handle_left_click_release(self, pos):
        """Handle left click release"""
        # Clear interaction states
        self.dragging_bone = False
        self.drag_start_pos = None
        self.drag_start_bone_state = None

        self.dragging_timeline = False
        self.dragging_keyframe = False

    def handle_mouse_drag(self, pos):
        """Handle mouse dragging"""
        if self.dragging_timeline:
            self.handle_timeline_drag(pos)
        elif self.dragging_keyframe:
            self.handle_keyframe_drag(pos)
        elif self.dragging_bone and self.get_selected_bone():
            self.handle_bone_manipulation_drag(pos)

    def handle_timeline_drag(self, pos):
        """Handle timeline dragging for time scrubbing"""
        x, y = pos
        relative_x = x - 50
        timeline_width = self.screen.get_width() - 300 - 100
        self.current_time = (relative_x / timeline_width) * self.duration
        self.current_time = max(0, min(self.duration, self.current_time))

    def handle_keyframe_drag(self, pos):
        """Handle keyframe dragging to change time"""
        if self.selected_keyframe and self.selected_track:
            x, y = pos
            relative_x = x - 50
            timeline_width = self.screen.get_width() - 300 - 100
            new_time = (relative_x / timeline_width) * self.duration
            new_time = max(0, min(self.duration, new_time))

            track = self.data_objects['bone_tracks'][self.selected_track]
            if track.selected_keyframe is not None and 0 <= track.selected_keyframe < len(track.keyframes):
                track.keyframes[track.selected_keyframe].time = new_time
                # Re-sort keyframes by time
                track.keyframes.sort(key=lambda kf: kf.time)

    def handle_bone_manipulation_drag(self, pos):
        """Handle bone manipulation based on current mode"""
        if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION:
            self.update_bone_translation(pos)
        else:  # ROTATION
            self.update_bone_rotation(pos)

    def handle_mouse_wheel(self, event):
        """Handle mouse wheel for zoom and timeline scroll"""
        mouse_x, mouse_y = pygame.mouse.get_pos()

        viewport_rect = self.get_main_viewport_rect()
        if viewport_rect.collidepoint((mouse_x, mouse_y)):
            super().handle_mouse_wheel(event)
        elif mouse_y > self.screen.get_height() - self.timeline_height:  # Timeline area
            # Could add timeline zoom here
            pass

    # ========================================================================
    # ANIMATION PLAYBACK CONTROLS
    # ========================================================================

    def toggle_playback(self):
        """Toggle animation playback"""
        self.playing = not self.playing
        if self.playing:
            self.last_update_time = time.time()
        print(f"Animation {'PLAYING' if self.playing else 'PAUSED'}")

    def step_backward(self):
        """Step backward one frame"""
        self.current_time = max(0, self.current_time - 1.0 / self.fps)
        print(f"Step backward to {self.current_time:.2f}s")

    def step_forward(self):
        """Step forward one frame"""
        self.current_time = min(self.duration, self.current_time + 1.0 / self.fps)
        print(f"Step forward to {self.current_time:.2f}s")

    def go_to_start(self):
        """Go to animation start"""
        self.current_time = 0.0
        print("Go to start")

    def go_to_end(self):
        """Go to animation end"""
        self.current_time = self.duration
        print("Go to end")

    # ========================================================================
    # BONE MANIPULATION
    # ========================================================================

    def set_translation_mode(self):
        """Set bone manipulation to translation mode"""
        self.bone_manipulation_mode = BoneManipulationMode.TRANSLATION
        print("Switched to TRANSLATION mode")

    def set_rotation_mode(self):
        """Set bone manipulation to rotation mode"""
        self.bone_manipulation_mode = BoneManipulationMode.ROTATION
        print("Switched to ROTATION mode")

    def toggle_manipulation_mode(self):
        """Toggle between manipulation modes"""
        if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION:
            self.set_rotation_mode()
        else:
            self.set_translation_mode()

    def update_bone_translation(self, pos):
        """Update bone position using translation mode"""
        selected_bone = self.get_selected_bone()
        if not selected_bone or not self.drag_start_bone_state:
            return

        viewport_pos = self.screen_to_viewport(pos)
        bone = self.data_objects['bones'][selected_bone]

        # Calculate translation offset from original position
        start_bone_pos = self.drag_start_bone_state['pos']
        mouse_offset = self.drag_start_bone_state['mouse_offset']

        new_world_x = viewport_pos[0] - mouse_offset[0]
        new_world_y = viewport_pos[1] - mouse_offset[1]

        # Calculate offset relative to bone's parent or original position
        if bone.parent and bone.parent in self.data_objects['bones']:
            parent_x, parent_y, parent_rot, _ = self.get_bone_world_transform(bone.parent, self.current_time)
            parent_bone = self.data_objects['bones'][bone.parent]

            # Handle attachment points
            if bone.parent_attachment_point == AttachmentPoint.END:
                parent_attach_x = parent_x + parent_bone.length * math.cos(math.radians(parent_rot))
                parent_attach_y = parent_y + parent_bone.length * math.sin(math.radians(parent_rot))
            else:  # START
                parent_attach_x = parent_x
                parent_attach_y = parent_y

            offset_x = new_world_x - parent_attach_x
            offset_y = new_world_y - parent_attach_y
        else:
            # Root bone - offset from original position
            if selected_bone in self.original_bone_positions:
                orig_x, orig_y, orig_angle = self.original_bone_positions[selected_bone]
                offset_x = new_world_x - orig_x
                offset_y = new_world_y - orig_y
            else:
                offset_x = offset_y = 0

        # Get current transform to preserve rotation and scale
        current_track = self.data_objects['bone_tracks'].get(selected_bone)
        if current_track:
            current_transform = current_track.get_transform_at_time(self.current_time)
            self.create_or_update_keyframe(selected_bone, offset_x, offset_y,
                                           current_transform.rotation, current_transform.scale)
        else:
            self.create_or_update_keyframe(selected_bone, offset_x, offset_y, 0, 0)

    def update_bone_rotation(self, pos):
        """Update bone rotation using rotation mode"""
        selected_bone = self.get_selected_bone()
        if not selected_bone or not self.drag_start_bone_state:
            return

        viewport_pos = self.screen_to_viewport(pos)
        bone = self.data_objects['bones'][selected_bone]

        # Get current bone position
        current_x, current_y, _, _ = self.get_bone_world_transform(selected_bone, self.current_time)

        # Calculate angle from bone start to mouse position
        dx = viewport_pos[0] - current_x
        dy = viewport_pos[1] - current_y

        new_angle = math.degrees(math.atan2(dy, dx))
        orig_angle = bone.angle
        rotation_offset = new_angle - orig_angle

        # Get current transform to preserve position and scale
        current_track = self.data_objects['bone_tracks'].get(selected_bone)
        if current_track:
            current_transform = current_track.get_transform_at_time(self.current_time)
            self.create_or_update_keyframe(selected_bone,
                                           current_transform.x, current_transform.y,
                                           rotation_offset, current_transform.scale)
        else:
            self.create_or_update_keyframe(selected_bone, 0, 0, rotation_offset, 0)

    def create_or_update_keyframe(self, bone_name: str, x: float, y: float, rotation: float, scale: float):
        """Create or update keyframe at current time"""
        if bone_name not in self.data_objects['bone_tracks']:
            return

        track = self.data_objects['bone_tracks'][bone_name]

        # Check if keyframe exists at current time
        existing_keyframe = None
        for i, kf in enumerate(track.keyframes):
            if abs(kf.time - self.current_time) < 0.01:
                existing_keyframe = i
                break

        transform = BoneTransform(x=x, y=y, rotation=rotation, scale=scale)

        if existing_keyframe is not None:
            # Update existing keyframe
            track.keyframes[existing_keyframe].transform = transform
        else:
            # Create new keyframe
            keyframe = BoneKeyframe(
                time=self.current_time,
                bone_name=bone_name,
                transform=transform
            )
            track.add_keyframe(keyframe)

    def create_operation_command(self):
        """Create undo command for bone manipulation"""
        if not self.drag_start_data or self.drag_start_data['type'] != 'bone_manipulation':
            return

        bone_name = self.drag_start_data['bone_name']
        old_transform = self.drag_start_data['old_transform']

        track = self.data_objects['bone_tracks'].get(bone_name)
        if track:
            current_transform = track.get_transform_at_time(self.current_time)

            # Check if transform actually changed
            if (abs(old_transform.x - current_transform.x) > 0.1 or
                    abs(old_transform.y - current_transform.y) > 0.1 or
                    abs(old_transform.rotation - current_transform.rotation) > 0.1 or
                    abs(old_transform.scale - current_transform.scale) > 0.1):

                # This is complex because we're modifying keyframes, not the objects directly
                # For now, just record it as a bone manipulation
                mode_desc = self.bone_manipulation_mode.value.title()
                print(f"Recorded {mode_desc} for {bone_name}")

                # Add a simple record to history
                self.command_history.append(Command(
                    action="modify",
                    object_type="bone_animation",
                    object_id=bone_name,
                    old_data=old_transform,
                    new_data=current_transform,
                    description=f"{mode_desc} {bone_name}"
                ))

                if len(self.command_history) > self.max_history:
                    self.command_history.pop(0)

    # ========================================================================
    # KEYFRAME OPERATIONS
    # ========================================================================

    def add_keyframe_at_current_time(self):
        """Add keyframe for selected bone at current time"""
        selected_bone = self.get_selected_bone()
        if not selected_bone or selected_bone not in self.data_objects['bone_tracks']:
            print("No bone selected for keyframe")
            return

        track = self.data_objects['bone_tracks'][selected_bone]
        current_transform = track.get_transform_at_time(self.current_time)

        keyframe = BoneKeyframe(
            time=self.current_time,
            bone_name=selected_bone,
            transform=current_transform
        )

        track.add_keyframe(keyframe)
        print(f"Added keyframe for {selected_bone} at {self.current_time:.2f}s")

    def set_keyframe_interpolation(self, interp_type: InterpolationType):
        """Set interpolation type for selected keyframe"""
        if (self.selected_keyframe and self.selected_track and
                self.selected_track in self.data_objects['bone_tracks']):
            track = self.data_objects['bone_tracks'][self.selected_track]
            if track.selected_keyframe is not None and 0 <= track.selected_keyframe < len(track.keyframes):
                keyframe = track.keyframes[track.selected_keyframe]
                old_interpolation = keyframe.interpolation

                if old_interpolation != interp_type:
                    keyframe.interpolation = interp_type
                    print(f"Set keyframe interpolation to {interp_type.value}")

    def clear_all_animation(self):
        """Clear all animation data"""
        if any(len(track.keyframes) > 0 for track in self.data_objects['bone_tracks'].values()):
            for track in self.data_objects['bone_tracks'].values():
                track.keyframes.clear()
                track.selected_keyframe = None
            self.current_time = 0.0
            print("Cleared all animation data")

    def delete_selected(self):
        """Delete selected keyframe"""
        if (self.selected_keyframe and self.selected_track and
                self.selected_track in self.data_objects['bone_tracks']):
            track = self.data_objects['bone_tracks'][self.selected_track]
            if track.selected_keyframe is not None and 0 <= track.selected_keyframe < len(track.keyframes):
                deleted_kf = track.keyframes.pop(track.selected_keyframe)
                track.selected_keyframe = None
                self.selected_keyframe = None
                print(f"Deleted keyframe at {deleted_kf.time:.2f}s")

    # ========================================================================
    # ANIMATION SYSTEM
    # ========================================================================

    def update(self):
        """Update animation state"""
        if self.playing:
            current_time = time.time()
            if self.last_update_time > 0:
                dt = current_time - self.last_update_time
                self.current_time += dt

                if self.current_time >= self.duration:
                    self.current_time = 0  # Loop animation

            self.last_update_time = current_time

    def get_bone_world_transform(self, bone_name: str, time: float) -> Tuple[float, float, float, float]:
        """Get bone's world transform maintaining hierarchy during animation"""
        if bone_name not in self.data_objects['bones'] or bone_name not in self.original_bone_positions:
            return 0, 0, 0, 1

        bone = self.data_objects['bones'][bone_name]

        # Calculate hierarchical transform
        if bone.parent and bone.parent in self.data_objects['bones']:
            # Get parent's world transform first
            parent_x, parent_y, parent_rot, parent_scale = self.get_bone_world_transform(bone.parent, time)
            parent_bone = self.data_objects['bones'][bone.parent]

            # Calculate attachment position
            if bone.parent_attachment_point == AttachmentPoint.END:
                parent_attach_x = parent_x + parent_bone.length * math.cos(math.radians(parent_rot))
                parent_attach_y = parent_y + parent_bone.length * math.sin(math.radians(parent_rot))
            else:  # START
                parent_attach_x = parent_x
                parent_attach_y = parent_y

            # Get this bone's animation offset
            if bone_name in self.data_objects['bone_tracks']:
                anim_transform = self.data_objects['bone_tracks'][bone_name].get_transform_at_time(time)
            else:
                anim_transform = BoneTransform()

            # Rotate child's offset by parent's rotation
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
            if bone_name in self.data_objects['bone_tracks']:
                anim_transform = self.data_objects['bone_tracks'][bone_name].get_transform_at_time(time)
            else:
                anim_transform = BoneTransform()

            world_x = orig_x + anim_transform.x
            world_y = orig_y + anim_transform.y
            world_rotation = orig_angle + anim_transform.rotation
            world_scale = max(0.1, anim_transform.scale) if anim_transform.scale != 0 else 1.0

        return world_x, world_y, world_rotation, world_scale

    def get_sprite_world_position(self, instance_id: str, time: float) -> Optional[Tuple[float, float]]:
        """Get sprite world position at given time"""
        if instance_id not in self.data_objects['sprite_instances']:
            return None

        sprite_instance = self.data_objects['sprite_instances'][instance_id]
        if not sprite_instance.bone_name or sprite_instance.bone_name not in self.data_objects['bones']:
            return None

        # Get animated bone world transform
        bone_x, bone_y, bone_rot, bone_scale = self.get_bone_world_transform(sprite_instance.bone_name, time)
        bone = self.data_objects['bones'][sprite_instance.bone_name]

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

        sprite_origin_x = attach_x + rotated_offset_x
        sprite_origin_y = attach_y + rotated_offset_y

        return sprite_origin_x, sprite_origin_y

    def get_animated_bone_for_interaction(self, bone_name):
        """Create temporary bone with animated position for interaction"""
        if bone_name not in self.data_objects['bones']:
            return None

        original_bone = self.data_objects['bones'][bone_name]
        world_x, world_y, world_rot, _ = self.get_bone_world_transform(bone_name, self.current_time)

        # Create temporary bone with animated transform
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

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def get_bone_at_position(self, bones, pos, tolerance=8):
        """Find bone at position"""
        x, y = pos
        adjusted_tolerance = max(4, int(tolerance / self.viewport.zoom))

        for bone_name, bone in bones.items():
            if not bone:
                continue

            end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

            # Check line distance
            dist = self.point_to_line_distance((x, y), (bone.x, bone.y), (end_x, end_y))
            if dist < adjusted_tolerance:
                return bone_name

        return None

    def point_to_line_distance(self, point, line_start, line_end):
        """Calculate distance from point to line segment"""
        px, py = point
        x1, y1 = line_start
        x2, y2 = line_end

        dx = x2 - x1
        dy = y2 - y1

        if dx == 0 and dy == 0:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy

        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

    def get_selected_bone(self):
        """Get currently selected bone"""
        return self.get_first_selected('bones')

    # ========================================================================
    # FILE OPERATIONS
    # ========================================================================

    def load_attachment_configuration_dialog(self):
        """Load attachment configuration"""
        filename = "sprite_attachment_editor_project.json"
        if os.path.exists(filename):
            self.load_attachment_configuration(filename)
        else:
            print(f"{filename} not found. Please run Sprite Attachment Editor first.")

    def load_attachment_configuration(self, filename):
        """Load attachment configuration from sprite attachment editor"""
        try:
            import json
            with open(filename, 'r') as f:
                data = json.load(f)

            # Load sprite sheet
            if data.get('sprite_sheet_path'):
                self.sprite_sheet_path = data['sprite_sheet_path']
                if os.path.exists(self.sprite_sheet_path):
                    self.sprite_sheet = pygame.image.load(self.sprite_sheet_path)

            # Load sprites
            self.data_objects['sprites'] = {}
            for name, sprite_data in data.get('sprites', {}).items():
                self.data_objects['sprites'][name] = SpriteRect(**sprite_data)

            # Load bones with enum support
            self.data_objects['bones'] = {}
            for name, bone_data in data.get('bones', {}).items():
                # Handle enum fields
                if 'layer' in bone_data:
                    bone_data['layer'] = BoneLayer(bone_data['layer'])
                else:
                    bone_data['layer'] = BoneLayer.MIDDLE

                if 'parent_attachment_point' in bone_data:
                    bone_data['parent_attachment_point'] = AttachmentPoint(bone_data['parent_attachment_point'])
                else:
                    bone_data['parent_attachment_point'] = AttachmentPoint.END

                if 'children' not in bone_data:
                    bone_data['children'] = []

                self.data_objects['bones'][name] = Bone(**bone_data)

            # Store original bone positions
            self.original_bone_positions = {}
            for name, bone in self.data_objects['bones'].items():
                self.original_bone_positions[name] = (bone.x, bone.y, bone.angle)

            # Load sprite instances with attachment point support
            self.data_objects['sprite_instances'] = {}
            for instance_id, instance_data in data.get('sprite_instances', {}).items():
                # Handle attachment point
                attachment_point_value = instance_data.get('bone_attachment_point', 'start')
                try:
                    attachment_point = AttachmentPoint(attachment_point_value)
                except ValueError:
                    attachment_point = AttachmentPoint.START

                sprite_instance = SpriteInstance(
                    id=instance_data['id'],
                    sprite_name=instance_data['sprite_name'],
                    bone_name=instance_data.get('bone_name'),
                    offset_x=instance_data.get('offset_x', 0.0),
                    offset_y=instance_data.get('offset_y', 0.0),
                    offset_rotation=instance_data.get('offset_rotation', 0.0),
                    scale=instance_data.get('scale', 1.0),
                    bone_attachment_point=attachment_point
                )

                if sprite_instance.scale <= 0:
                    sprite_instance.scale = 1.0

                self.data_objects['sprite_instances'][instance_id] = sprite_instance

            # Create animation tracks for each bone
            self.data_objects['bone_tracks'] = {}
            for bone_name in self.data_objects['bones'].keys():
                self.data_objects['bone_tracks'][bone_name] = BoneAnimationTrack(bone_name)

            print(
                f"Loaded attachment configuration: {len(self.data_objects['sprites'])} sprites, {len(self.data_objects['bones'])} bones, {len(self.data_objects['sprite_instances'])} instances")
            return True
        except Exception as e:
            print(f"Error loading attachment configuration: {e}")
            return False

    def serialize_data_objects(self) -> Dict[str, any]:
        """Serialize data objects for saving"""
        import json

        serialized = {
            'duration': self.duration,
            'fps': self.fps,
            'current_time': self.current_time,
            'original_bone_positions': self.original_bone_positions,
            'sprite_sheet_path': self.sprite_sheet_path,
            'sprites': {name: {
                'name': sprite.name,
                'x': sprite.x,
                'y': sprite.y,
                'width': sprite.width,
                'height': sprite.height,
                'origin_x': sprite.origin_x,
                'origin_y': sprite.origin_y
            } for name, sprite in self.data_objects['sprites'].items()},
            'bones': {name: {
                'name': bone.name,
                'x': bone.x,
                'y': bone.y,
                'length': bone.length,
                'angle': bone.angle,
                'parent': bone.parent,
                'parent_attachment_point': bone.parent_attachment_point.value,
                'children': bone.children,
                'layer': bone.layer.value,
                'layer_order': bone.layer_order
            } for name, bone in self.data_objects['bones'].items()},
            'sprite_instances': {instance_id: {
                'id': instance.id,
                'sprite_name': instance.sprite_name,
                'bone_name': instance.bone_name,
                'offset_x': instance.offset_x,
                'offset_y': instance.offset_y,
                'offset_rotation': instance.offset_rotation,
                'scale': instance.scale,
                'bone_attachment_point': instance.bone_attachment_point.value
            } for instance_id, instance in self.data_objects['sprite_instances'].items()},
            'bone_tracks': {}
        }

        # Save animation tracks
        for bone_name, track in self.data_objects['bone_tracks'].items():
            if track.keyframes:
                track_data = {
                    'keyframes': []
                }

                for keyframe in track.keyframes:
                    kf_data = {
                        'time': keyframe.time,
                        'bone_name': keyframe.bone_name,
                        'transform': {
                            'x': keyframe.transform.x,
                            'y': keyframe.transform.y,
                            'rotation': keyframe.transform.rotation,
                            'scale': keyframe.transform.scale
                        },
                        'interpolation': keyframe.interpolation.value,
                        'sprite_instance_id': keyframe.sprite_instance_id
                    }
                    track_data['keyframes'].append(kf_data)

                serialized['bone_tracks'][bone_name] = track_data

        return serialized

    def deserialize_data_objects(self, data: Dict[str, any]) -> Dict[str, any]:
        """Deserialize data objects from loading"""
        # Load basic animation settings
        self.duration = data.get('duration', 5.0)
        self.fps = data.get('fps', 30)
        self.current_time = data.get('current_time', 0.0)
        self.original_bone_positions = data.get('original_bone_positions', {})
        self.sprite_sheet_path = data.get('sprite_sheet_path', '')

        # Load sprite sheet
        if self.sprite_sheet_path and os.path.exists(self.sprite_sheet_path):
            self.sprite_sheet = pygame.image.load(self.sprite_sheet_path)

        deserialized = {
            'sprites': {},
            'bones': {},
            'sprite_instances': {},
            'bone_tracks': {}
        }

        # Load sprites
        for name, sprite_data in data.get('sprites', {}).items():
            deserialized['sprites'][name] = SpriteRect(**sprite_data)

        # Load bones
        for name, bone_data in data.get('bones', {}).items():
            bone_data['layer'] = BoneLayer(bone_data.get('layer', 'middle'))
            bone_data['parent_attachment_point'] = AttachmentPoint(bone_data.get('parent_attachment_point', 'end'))
            deserialized['bones'][name] = Bone(**bone_data)

        # Load sprite instances
        for instance_id, instance_data in data.get('sprite_instances', {}).items():
            instance_data['bone_attachment_point'] = AttachmentPoint(
                instance_data.get('bone_attachment_point', 'start'))
            deserialized['sprite_instances'][instance_id] = SpriteInstance(**instance_data)

        # Load animation tracks
        for bone_name in deserialized['bones'].keys():
            deserialized['bone_tracks'][bone_name] = BoneAnimationTrack(bone_name)

        # Load keyframes
        for bone_name, track_data in data.get('bone_tracks', {}).items():
            if bone_name in deserialized['bone_tracks']:
                track = deserialized['bone_tracks'][bone_name]

                for kf_data in track_data.get('keyframes', []):
                    transform = BoneTransform(**kf_data['transform'])
                    interpolation = InterpolationType(kf_data.get('interpolation', 'linear'))

                    keyframe = BoneKeyframe(
                        time=kf_data['time'],
                        bone_name=kf_data['bone_name'],
                        transform=transform,
                        interpolation=interpolation,
                        sprite_instance_id=kf_data.get('sprite_instance_id')
                    )
                    track.add_keyframe(keyframe)

        return deserialized

    # ========================================================================
    # DRAWING OVERRIDES
    # ========================================================================

    def draw_objects(self):
        """Draw animated bones and sprites"""
        # Prepare animated transforms
        animated_transforms = {}
        for bone_name in self.data_objects['bones'].keys():
            animated_transforms[bone_name] = self.get_bone_world_transform(bone_name, self.current_time)

        # Draw hierarchy connections
        self.draw_bone_hierarchy_connections(animated_transforms)

        # Draw animated sprites first (by layer)
        self.draw_animated_sprites()

        # Draw animated skeleton
        self.draw_animated_skeleton(animated_transforms)

    def draw_bone_hierarchy_connections(self, animated_transforms):
        """Draw hierarchy connections with animated positions"""
        for bone_name, bone in self.data_objects['bones'].items():
            if bone.parent and bone.parent in self.data_objects['bones']:
                parent_bone = self.data_objects['bones'][bone.parent]

                parent_transform = animated_transforms.get(bone.parent)
                child_transform = animated_transforms.get(bone_name)

                if parent_transform and child_transform:
                    parent_x, parent_y, parent_rot, _ = parent_transform
                    child_x, child_y, _, _ = child_transform

                    # Choose attachment point
                    if bone.parent_attachment_point == AttachmentPoint.END:
                        parent_attach_x = parent_x + parent_bone.length * math.cos(math.radians(parent_rot))
                        parent_attach_y = parent_y + parent_bone.length * math.sin(math.radians(parent_rot))
                        connection_color = (100, 100, 100)
                    else:  # START
                        parent_attach_x = parent_x
                        parent_attach_y = parent_y
                        connection_color = (150, 100, 150)

                    parent_attach_screen = self.viewport_to_screen((parent_attach_x, parent_attach_y))
                    child_start_screen = self.viewport_to_screen((child_x, child_y))

                    pygame.draw.line(self.screen, connection_color, parent_attach_screen, child_start_screen, 2)

    def draw_animated_skeleton(self, animated_transforms):
        """Draw animated skeleton with layer ordering"""
        # Group bones by layer
        layered_bones = {
            BoneLayer.BEHIND: [],
            BoneLayer.MIDDLE: [],
            BoneLayer.FRONT: []
        }

        for bone_name, bone in self.data_objects['bones'].items():
            layer_order = bone.layer_order
            layered_bones[bone.layer].append((layer_order, bone_name, bone))

        # Sort each layer by layer_order
        for layer in layered_bones:
            layered_bones[layer].sort(key=lambda x: x[0])

        # Draw in layer order
        selected_bone = self.get_selected_bone()
        for layer in [BoneLayer.BEHIND, BoneLayer.MIDDLE, BoneLayer.FRONT]:
            for layer_order, bone_name, bone in layered_bones[layer]:
                selected = bone_name == selected_bone
                world_x, world_y, world_rot, world_scale = animated_transforms[bone_name]

                # Determine bone color
                has_keyframes = (bone_name in self.data_objects['bone_tracks'] and
                                 len(self.data_objects['bone_tracks'][bone_name].keyframes) > 0)

                if selected:
                    color = (255, 165, 0)  # Orange
                elif has_keyframes:
                    color = (0, 255, 255)  # Cyan - animated bones
                else:
                    color = self.get_bone_layer_colors(bone.layer, False)['line']  # Layer color

                self.draw_animated_bone(bone, world_x, world_y, world_rot, color, selected)

    def draw_animated_bone(self, bone, world_x, world_y, world_rot, color, selected):
        """Draw a single animated bone"""
        # Calculate positions
        start_screen = self.viewport_to_screen((world_x, world_y))
        end_x = world_x + bone.length * math.cos(math.radians(world_rot))
        end_y = world_y + bone.length * math.sin(math.radians(world_rot))
        end_screen = self.viewport_to_screen((end_x, end_y))

        # Draw bone line
        width = max(1, int(3 * self.viewport.zoom))
        pygame.draw.line(self.screen, color, start_screen, end_screen, width)

        # Draw joint points
        start_radius = max(3, int(5 * self.viewport.zoom))
        end_radius = max(3, int(5 * self.viewport.zoom))

        # Start point (blue)
        pygame.draw.circle(self.screen, (0, 0, 255),
                           (int(start_screen[0]), int(start_screen[1])), start_radius)
        pygame.draw.circle(self.screen, (255, 255, 255),
                           (int(start_screen[0]), int(start_screen[1])), start_radius, 1)

        # End point (red)
        pygame.draw.circle(self.screen, (255, 0, 0),
                           (int(end_screen[0]), int(end_screen[1])), end_radius)
        pygame.draw.circle(self.screen, (255, 255, 255),
                           (int(end_screen[0]), int(end_screen[1])), end_radius, 1)

        # Draw bone name
        if self.viewport.zoom > 0.4:
            mid_x = (start_screen[0] + end_screen[0]) / 2
            mid_y = (start_screen[1] + end_screen[1]) / 2

            # Show attachment info
            attachment_info = ""
            if bone.parent:
                attachment_char = "E" if bone.parent_attachment_point == AttachmentPoint.END else "S"
                attachment_info = f"->{attachment_char}"

            display_name = f"{bone.name}{attachment_info}"
            text = self.small_font.render(display_name, True, color)
            self.screen.blit(text, (mid_x, mid_y - 15))

    def draw_animated_sprites(self):
        """Draw sprite instances with animation"""
        if not self.sprite_sheet:
            return

        # Group sprites by bone layer
        layered_sprites = {
            BoneLayer.BEHIND: [],
            BoneLayer.MIDDLE: [],
            BoneLayer.FRONT: []
        }

        for instance_id, sprite_instance in self.data_objects['sprite_instances'].items():
            if (sprite_instance.bone_name and
                    sprite_instance.bone_name in self.data_objects['bones'] and
                    sprite_instance.sprite_name in self.data_objects['sprites']):
                bone = self.data_objects['bones'][sprite_instance.bone_name]
                bone_layer_order = bone.layer_order
                layered_sprites[bone.layer].append((bone_layer_order, instance_id, sprite_instance))

        # Sort each layer by layer_order
        for layer in layered_sprites:
            layered_sprites[layer].sort(key=lambda x: x[0])

        # Draw in layer order: BEHIND -> MIDDLE -> FRONT
        for layer in [BoneLayer.BEHIND, BoneLayer.MIDDLE, BoneLayer.FRONT]:
            for layer_order, instance_id, sprite_instance in layered_sprites[layer]:
                self.draw_animated_sprite_instance(instance_id, sprite_instance)

    def draw_animated_sprite_instance(self, instance_id, sprite_instance):
        """Draw a single animated sprite instance"""
        bone = self.data_objects['bones'][sprite_instance.bone_name]
        sprite = self.data_objects['sprites'][sprite_instance.sprite_name]

        try:
            # Get sprite world position
            sprite_pos = self.get_sprite_world_position(instance_id, self.current_time)
            if not sprite_pos:
                return

            sprite_world_x, sprite_world_y = sprite_pos

            # Get animated bone transform for rotation
            bone_x, bone_y, bone_rot, bone_scale = self.get_bone_world_transform(sprite_instance.bone_name,
                                                                                 self.current_time)

            # Calculate sprite rotation (baseline + animation delta)
            if sprite_instance.bone_name in self.original_bone_positions:
                _, _, original_bone_angle = self.original_bone_positions[sprite_instance.bone_name]
            else:
                original_bone_angle = bone.angle

            animation_rotation_delta = bone_rot - original_bone_angle
            total_rotation = sprite_instance.offset_rotation + animation_rotation_delta

            # Extract and scale sprite
            sprite_surface = self.sprite_sheet.subsurface((sprite.x, sprite.y, sprite.width, sprite.height))
            final_width = max(1, int(sprite.width * bone_scale * sprite_instance.scale * self.viewport.zoom))
            final_height = max(1, int(sprite.height * bone_scale * sprite_instance.scale * self.viewport.zoom))
            scaled_sprite = pygame.transform.scale(sprite_surface, (final_width, final_height))

            # Calculate origin position
            origin_x_pixels = final_width * sprite.origin_x
            origin_y_pixels = final_height * sprite.origin_y
            origin_screen_pos = self.viewport_to_screen((sprite_world_x, sprite_world_y))

            # Handle rotation
            if abs(total_rotation) > 0.01:
                max_dim = max(final_width, final_height) * 2
                rotation_surface = pygame.Surface((max_dim, max_dim), pygame.SRCALPHA)

                sprite_pos_in_rotation = (
                    max_dim // 2 - origin_x_pixels,
                    max_dim // 2 - origin_y_pixels
                )
                rotation_surface.blit(scaled_sprite, sprite_pos_in_rotation)

                rotated_surface = pygame.transform.rotate(rotation_surface, -total_rotation)
                rotated_rect = rotated_surface.get_rect()

                final_pos = (
                    origin_screen_pos[0] - rotated_rect.width // 2,
                    origin_screen_pos[1] - rotated_rect.height // 2
                )

                self.screen.blit(rotated_surface, final_pos)
            else:
                # No rotation
                final_pos = (
                    origin_screen_pos[0] - origin_x_pixels,
                    origin_screen_pos[1] - origin_y_pixels
                )

                self.screen.blit(scaled_sprite, final_pos)

            # Draw attachment indicators
            if sprite_instance.bone_attachment_point == AttachmentPoint.END:
                attach_x = bone_x + bone.length * math.cos(math.radians(bone_rot))
                attach_y = bone_y + bone.length * math.sin(math.radians(bone_rot))
                attachment_color = (255, 0, 0)  # Red for END
            else:  # START
                attach_x = bone_x
                attach_y = bone_y
                attachment_color = (0, 0, 255)  # Blue for START

            attachment_screen = self.viewport_to_screen((attach_x, attach_y))

            pygame.draw.circle(self.screen, attachment_color,
                               (int(attachment_screen[0]), int(attachment_screen[1])), 3)
            pygame.draw.line(self.screen, attachment_color, attachment_screen, origin_screen_pos, 1)

        except pygame.error:
            pass  # Skip if sprite extraction fails

    def get_bone_layer_colors(self, bone_layer, selected):
        """Get color scheme based on bone layer"""
        if bone_layer == BoneLayer.BEHIND:
            return {
                'line': (0, 150, 255) if selected else (0, 100, 200),
                'start': (0, 255, 255) if selected else (0, 150, 255),
                'end': (0, 100, 255) if selected else (0, 0, 200)
            }
        elif bone_layer == BoneLayer.FRONT:
            return {
                'line': (255, 165, 0) if selected else (255, 0, 0),
                'start': (255, 100, 100) if selected else (200, 0, 0),
                'end': (255, 165, 0) if selected else (255, 100, 0)
            }
        else:  # MIDDLE
            return {
                'line': (255, 165, 0) if selected else (0, 255, 0),
                'start': (0, 255, 255) if selected else (0, 0, 255),
                'end': (255, 165, 0) if selected else (255, 0, 0)
            }

    def draw_overlays(self):
        """Draw mode indicators and manipulation guides"""
        # Draw manipulation mode indicator for selected bone
        selected_bone = self.get_selected_bone()
        if selected_bone:
            bone_x, bone_y, _, _ = self.get_bone_world_transform(selected_bone, self.current_time)
            bone_screen = self.viewport_to_screen((bone_x, bone_y))

            if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION:
                # Draw four-way arrow for translation
                center_x, center_y = bone_screen
                arrow_size = 20
                arrow_color = (0, 255, 255)  # Cyan

                # Draw plus symbol with arrows
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
                # Draw circle for rotation
                center_x, center_y = bone_screen
                circle_radius = 25
                pygame.draw.circle(self.screen, (255, 255, 0), (int(center_x), int(center_y)), circle_radius, 3)

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
                    pygame.draw.lines(self.screen, (255, 255, 0), False, arc_points, 3)

    def draw_main_viewport(self):
        """Override to account for timeline"""
        viewport_rect = pygame.Rect(self.hierarchy_panel_width, 60,
                                    self.screen.get_width() - self.hierarchy_panel_width - 300,
                                    self.screen.get_height() - 60 - self.timeline_height)
        pygame.draw.rect(self.screen, (0, 0, 0), viewport_rect)
        self.screen.set_clip(viewport_rect)

        self.draw_grid()
        self.draw_objects()
        self.draw_overlays()

        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, (255, 255, 255), viewport_rect, 2)

        # Draw timeline
        timeline_rect = pygame.Rect(self.hierarchy_panel_width, self.screen.get_height() - self.timeline_height,
                                    self.screen.get_width() - self.hierarchy_panel_width - 300, self.timeline_height)
        pygame.draw.rect(self.screen, (128, 128, 128), timeline_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), timeline_rect, 2)

        self.draw_timeline(timeline_rect)

    def draw_timeline(self, timeline_rect):
        """Draw animation timeline with keyframes"""
        timeline_width = timeline_rect.width - 100

        # Draw time ruler
        for i in range(int(self.duration) + 1):
            x = timeline_rect.x + 50 + (i / self.duration) * timeline_width
            pygame.draw.line(self.screen, (0, 0, 0),
                             (x, timeline_rect.y),
                             (x, timeline_rect.y + 20))

            time_text = self.small_font.render(f"{i}s", True, (0, 0, 0))
            self.screen.blit(time_text, (x - 10, timeline_rect.y + 25))

        # Draw current time indicator
        current_x = timeline_rect.x + 50 + (self.current_time / self.duration) * timeline_width
        pygame.draw.line(self.screen, (255, 255, 0),
                         (current_x, timeline_rect.y),
                         (current_x, timeline_rect.bottom), 3)

        # Draw bone tracks
        y_offset = 50
        for bone_name, track in self.data_objects['bone_tracks'].items():
            track_y = timeline_rect.y + y_offset

            # Highlight selected track
            is_selected = bone_name == self.selected_track
            color = (255, 255, 0) if is_selected else (255, 255, 255)

            # Track name
            track_text = self.small_font.render(bone_name, True, color)
            self.screen.blit(track_text, (timeline_rect.x + 5, track_y - 10))

            # Track background
            if is_selected:
                track_bg = pygame.Rect(timeline_rect.x, track_y - 15, 45, 25)
                pygame.draw.rect(self.screen, (64, 64, 0), track_bg)

            # Track line
            pygame.draw.line(self.screen, (200, 200, 200),
                             (timeline_rect.x + 50, track_y),
                             (timeline_rect.right - 50, track_y), 1)

            # Draw keyframes with interpolation colors
            for i, keyframe in enumerate(track.keyframes):
                kf_x = timeline_rect.x + 50 + (keyframe.time / self.duration) * timeline_width

                # Color based on interpolation and selection
                if i == track.selected_keyframe:
                    kf_color = (255, 255, 0)  # Yellow for selected
                elif keyframe.interpolation == InterpolationType.LINEAR:
                    kf_color = (255, 255, 255)  # White
                elif keyframe.interpolation == InterpolationType.EASE_IN:
                    kf_color = (255, 0, 0)  # Red
                elif keyframe.interpolation == InterpolationType.EASE_OUT:
                    kf_color = (0, 0, 255)  # Blue
                elif keyframe.interpolation == InterpolationType.EASE_IN_OUT:
                    kf_color = (128, 0, 128)  # Purple
                elif keyframe.interpolation == InterpolationType.BEZIER:
                    kf_color = (0, 255, 0)  # Green
                else:
                    kf_color = (255, 255, 255)

                # Draw keyframe
                pygame.draw.circle(self.screen, kf_color, (int(kf_x), int(track_y)), 6)
                pygame.draw.circle(self.screen, (0, 0, 0), (int(kf_x), int(track_y)), 6, 2)

            y_offset += 30

    def draw_properties_content(self, panel_rect, y_offset):
        """Draw animation properties panel"""
        # Mode indicator
        mode_text = f"Mode: {self.bone_manipulation_mode.value.upper()}"
        mode_color = (0, 255, 255) if self.bone_manipulation_mode == BoneManipulationMode.TRANSLATION else (255, 255, 0)
        mode_surface = self.small_font.render(mode_text, True, mode_color)
        self.screen.blit(mode_surface, (panel_rect.x + 10, y_offset))
        y_offset += 25

        # Playback controls
        play_text = "PLAYING" if self.playing else "PAUSED"
        play_color = (0, 255, 0) if self.playing else (255, 0, 0)
        play_surface = self.small_font.render(play_text, True, play_color)
        self.screen.blit(play_surface, (panel_rect.x + 10, y_offset))
        y_offset += 20

        time_text = self.small_font.render(f"Time: {self.current_time:.2f}s / {self.duration:.2f}s", True, (0, 0, 0))
        self.screen.blit(time_text, (panel_rect.x + 10, y_offset))
        y_offset += 25

        # Selected keyframe info
        if self.selected_keyframe:
            kf_text = self.small_font.render("Selected Keyframe:", True, (255, 0, 0))
            self.screen.blit(kf_text, (panel_rect.x + 10, y_offset))
            y_offset += 20

            kf_info = [
                f"  Time: {self.selected_keyframe.time:.2f}s",
                f"  Bone: {self.selected_keyframe.bone_name}",
                f"  Interpolation: {self.selected_keyframe.interpolation.value}",
                f"  Transform: ({self.selected_keyframe.transform.x:.1f}, {self.selected_keyframe.transform.y:.1f})",
                f"  Rotation: {self.selected_keyframe.transform.rotation:.1f}"
            ]

            for line in kf_info:
                text = self.small_font.render(line, True, (0, 0, 0))
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
                y_offset += 18

        # Selected bone info
        selected_bone = self.get_selected_bone()
        if selected_bone:
            bone_text = self.small_font.render(f"Bone: {selected_bone}", True, (0, 0, 0))
            self.screen.blit(bone_text, (panel_rect.x + 10, y_offset))
            y_offset += 25

            bone = self.data_objects['bones'][selected_bone]
            # Show both original and animated positions
            orig_x, orig_y, orig_angle = self.original_bone_positions.get(selected_bone, (0, 0, 0))
            anim_x, anim_y, anim_rot, anim_scale = self.get_bone_world_transform(selected_bone, self.current_time)

            props = [
                f"Original: ({orig_x:.1f}, {orig_y:.1f}, {orig_angle:.1f})",
                f"Animated: ({anim_x:.1f}, {anim_y:.1f}, {anim_rot:.1f})",
                f"Length: {bone.length:.1f}",
                f"Parent: {bone.parent or 'None'}",
                f"Keyframes: {len(self.data_objects['bone_tracks'].get(selected_bone, BoneAnimationTrack('')).keyframes)}"
            ]

            for prop in props:
                text = self.small_font.render(prop, True, (0, 0, 0))
                self.screen.blit(text, (panel_rect.x + 20, y_offset))
                y_offset += 18

        # Project stats
        y_offset += 20
        total_keyframes = sum(len(track.keyframes) for track in self.data_objects['bone_tracks'].values())
        stats = [
            f"Sprites: {len(self.data_objects['sprites'])}",
            f"Instances: {len(self.data_objects['sprite_instances'])}",
            f"Bones: {len(self.data_objects['bones'])}",
            f"Total Keyframes: {total_keyframes}"
        ]

        for stat in stats:
            text = self.small_font.render(stat, True, (64, 64, 64))
            self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 18

        # Instructions
        y_offset += 20
        instructions = [
            "PLAYBACK:",
            "SPACE: Play/Pause",
            "Left/Right: Frame step",
            "HOME/END: Start/End",
            "",
            "ANIMATION:",
            "K: Add keyframe",
            "W: Translation mode",
            "E: Rotation mode",
            "T: Toggle mode",
            "",
            "INTERPOLATION:",
            "1: Linear  2: Ease In",
            "3: Ease Out  4: Ease In/Out",
            "5: Bezier",
            "",
            "TIMELINE:",
            "Click to scrub time",
            "Click keyframes to select",
            "Drag keyframes to move",
            "",
            "BONE MANIPULATION:",
            "Translation: Move bones",
            "Rotation: Rotate bones",
            "Auto-creates keyframes",
            "",
            "FILES:",
            "Ctrl+A: Load attachments",
            "Ctrl+S: Save animation",
            "Ctrl+X: Clear animation"
        ]

        for instruction in instructions:
            if instruction:
                if instruction.endswith(":"):
                    color = (255, 0, 0)
                elif instruction.startswith("Click") or instruction.startswith("Drag"):
                    color = (0, 0, 255)
                else:
                    color = (0, 0, 0)
                text = self.small_font.render(instruction, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 16


# Run the animation editor
if __name__ == "__main__":
    editor = AnimationEditor()
    editor.run()