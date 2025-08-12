import os
import math
import copy
import json
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple

import pygame

from boneless_core_base import UniversalEditor, Command
from boneless_sprite_editor import SpriteRect


class AttachmentPoint(Enum):
    ORIGIN = "origin"
    ENDPOINT = "endpoint"


class InterpolationType(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    CONSTANT = "constant"


class InstanceLayer(Enum):
    BEHIND = "behind"
    MIDDLE = "middle"
    FRONT = "front"


@dataclass
class AnimInstance:
    """An instance of a palette sprite placed in the scene (same as SceneInstance but for animation)"""
    id: str
    sprite_name: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    parent_id: Optional[str] = None
    parent_attachment: AttachmentPoint = AttachmentPoint.ORIGIN
    children: List[str] = field(default_factory=list)
    layer: InstanceLayer = InstanceLayer.MIDDLE
    layer_order: int = 0
    opacity: float = 1.0
    visible: bool = True


@dataclass
class Keyframe:
    """Animation keyframe for an instance"""
    time: float
    instance_id: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    opacity: float = 1.0
    interpolation: InterpolationType = InterpolationType.LINEAR


@dataclass
class AnimationTrack:
    """Animation track for a single instance"""
    instance_id: str
    keyframes: List[Keyframe] = field(default_factory=list)

    def add_keyframe(self, keyframe: Keyframe):
        # Insert in chronological order
        inserted = False
        for i, kf in enumerate(self.keyframes):
            if kf.time > keyframe.time:
                self.keyframes.insert(i, keyframe)
                inserted = True
                break
        if not inserted:
            self.keyframes.append(keyframe)

    def remove_keyframe_at_time(self, given_time: float, tolerance: float = 0.016):
        """Remove keyframe at specific time"""
        for i, kf in enumerate(self.keyframes):
            if abs(kf.time - given_time) < tolerance:
                self.keyframes.pop(i)
                return True
        return False

    def get_keyframe_at_time(self, given_time: float, tolerance: float = 0.016) -> Optional[Keyframe]:
        """Get keyframe at specific time"""
        for kf in self.keyframes:
            if abs(kf.time - given_time) < tolerance:
                return kf
        return None

    def get_transform_at_time(self, given_time: float) -> Tuple[float, float, float, float, float, float]:
        """Returns (x, y, rotation, scale_x, scale_y, opacity)"""
        if not self.keyframes:
            return 0.0, 0.0, 0.0, 1.0, 1.0, 1.0

        if given_time <= self.keyframes[0].time:
            kf = self.keyframes[0]
            return kf.x, kf.y, kf.rotation, kf.scale_x, kf.scale_y, kf.opacity

        if given_time >= self.keyframes[-1].time:
            kf = self.keyframes[-1]
            return kf.x, kf.y, kf.rotation, kf.scale_x, kf.scale_y, kf.opacity

        # Find keyframes to interpolate between
        for i in range(len(self.keyframes) - 1):
            kf1 = self.keyframes[i]
            kf2 = self.keyframes[i + 1]

            if kf1.time <= given_time <= kf2.time:
                # Handle constant interpolation
                if kf1.interpolation == InterpolationType.CONSTANT:
                    return kf1.x, kf1.y, kf1.rotation, kf1.scale_x, kf1.scale_y, kf1.opacity

                t = (given_time - kf1.time) / (kf2.time - kf1.time) if kf2.time != kf1.time else 0

                # Apply easing
                if kf1.interpolation == InterpolationType.EASE_IN:
                    t = t * t * t
                elif kf1.interpolation == InterpolationType.EASE_OUT:
                    t = 1 - (1 - t) * (1 - t) * (1 - t)
                elif kf1.interpolation == InterpolationType.EASE_IN_OUT:
                    if t < 0.5:
                        t = 4 * t * t * t
                    else:
                        t = 1 - pow(-2 * t + 2, 3) / 2

                # Interpolate
                x = kf1.x + (kf2.x - kf1.x) * t
                y = kf1.y + (kf2.y - kf1.y) * t
                rotation = kf1.rotation + (kf2.rotation - kf1.rotation) * t
                scale_x = kf1.scale_x + (kf2.scale_x - kf1.scale_x) * t
                scale_y = kf1.scale_y + (kf2.scale_y - kf1.scale_y) * t
                opacity = kf1.opacity + (kf2.opacity - kf1.opacity) * t

                return x, y, rotation, scale_x, scale_y, opacity

        return 0.0, 0.0, 0.0, 1.0, 1.0, 1.0


class AnimatorEditor(UniversalEditor):
    def __init__(self, scene_file="boneless_scene.json"):
        self.scene_file = scene_file
        super().__init__()

        # Data
        self.palette: Dict[str, SpriteRect] = {}
        self.instances: Dict[str, AnimInstance] = {}
        self.animation_tracks: Dict[str, AnimationTrack] = {}
        self.sprite_sheet = None
        self.sprite_sheet_path = ""

        # Animation state
        self.current_time = 0.0
        self.duration = 5.0
        self.fps = 30
        self.playing = False
        self.last_update_time = 0.0
        self.loop_animation = True

        # Timeline settings
        self.timeline_height = 200
        self.time_scale = 100  # pixels per second
        self.timeline_scroll = 0
        self.track_height = 25
        self.selected_keyframes: List[Tuple[str, float]] = []  # (instance_id, time) pairs

        # Interaction state
        self.dragging_time_scrubber = False
        self.dragging_keyframe = False
        self.dragging_keyframe_instance = None
        self.dragging_keyframe_time = None
        self.keyframe_drag_offset = 0

        # Onion skinning
        self.onion_skin_enabled = True
        self.onion_skin_frames = 3
        self.onion_skin_alpha = 64

        # Recording mode for automatic keyframe creation
        self.recording_mode = False

        self.setup_data_structures()
        self.setup_key_bindings()
        self.load_scene_from_file(self.scene_file)

        if os.path.exists("animation_project.json"):
            self.load_project()

    def setup_data_structures(self):
        self.data_objects = {
            'instances': {},
            'animation_tracks': {},
            'scene_file': self.scene_file,
            'duration': 5.0,
            'fps': 30
        }

    def setup_key_bindings(self):
        pass

    def get_editor_name(self) -> str:
        return "Animation Editor"

    # ========================================================================
    # SCENE LOADING
    # ========================================================================

    def load_scene_from_file(self, filename: str):
        """Load scene from boneless scene editor"""
        if not os.path.exists(filename):
            print(f"Scene file not found: {filename}")
            return False

        try:
            with open(filename, 'r') as f:
                data = json.load(f)

            scene_data = data.get('data', {})

            # Load palette file reference
            palette_file = scene_data.get('palette_file', 'sprite_sheet_editor_v1.0_project.json')
            self.load_palette_from_sheet_project(palette_file)

            # Convert scene instances to anim instances
            self.instances.clear()
            self.animation_tracks.clear()

            scene_instances = scene_data.get('instances', {})
            for iid, inst_data in scene_instances.items():
                attachment = AttachmentPoint(inst_data.get('parent_attachment', 'origin'))
                layer = InstanceLayer(inst_data.get('layer', 'middle'))

                # Create anim instance from scene instance
                anim_inst = AnimInstance(
                    id=inst_data['id'],
                    sprite_name=inst_data['sprite_name'],
                    x=inst_data.get('x', 0.0),
                    y=inst_data.get('y', 0.0),
                    rotation=inst_data.get('rotation', 0.0),
                    scale_x=inst_data.get('scale_x', 1.0),
                    scale_y=inst_data.get('scale_y', 1.0),
                    parent_id=inst_data.get('parent_id'),
                    parent_attachment=attachment,
                    children=inst_data.get('children', []),
                    layer=layer,
                    layer_order=inst_data.get('layer_order', 0),
                    opacity=inst_data.get('opacity', 1.0),
                    visible=inst_data.get('visible', True)
                )

                self.instances[iid] = anim_inst

                # Create initial animation track
                track = AnimationTrack(iid)

                # Create initial keyframe at time 0 with instance's setup values
                initial_keyframe = Keyframe(
                    time=0.0,
                    instance_id=iid,
                    x=anim_inst.x,
                    y=anim_inst.y,
                    rotation=anim_inst.rotation,
                    scale_x=anim_inst.scale_x,
                    scale_y=anim_inst.scale_y,
                    opacity=anim_inst.opacity
                )
                track.add_keyframe(initial_keyframe)

                self.animation_tracks[iid] = track

            print(f"Loaded scene with {len(self.instances)} instances from {filename}")
            return True

        except Exception as e:
            print(f"Failed to load scene: {e}")
            return False

    def load_palette_from_sheet_project(self, filename: str):
        """Load sprite palette from sprite sheet project"""
        if not os.path.exists(filename):
            print(f"Palette file not found: {filename}")
            return False

        try:
            with open(filename, 'r') as f:
                data = json.load(f)

            sprite_data = data.get('data', {})
            self.sprite_sheet_path = sprite_data.get('sprite_sheet_path', '')

            if self.sprite_sheet_path and os.path.exists(self.sprite_sheet_path):
                self.sprite_sheet = pygame.image.load(self.sprite_sheet_path)
                print(f"Loaded sprite sheet: {self.sprite_sheet_path}")

            sprites = sprite_data.get('sprites', {})
            self.palette.clear()

            for k, v in sprites.items():
                if 'endpoint_x' not in v:
                    v['endpoint_x'] = 1.0
                if 'endpoint_y' not in v:
                    v['endpoint_y'] = 0.5
                self.palette[k] = SpriteRect(**v)

            print(f"Loaded palette ({len(self.palette)} sprites)")
            return True

        except Exception as e:
            print("Failed to load palette:", e)
            return False

    # ========================================================================
    # ANIMATION SYSTEM
    # ========================================================================

    def update(self):
        """Update animation playback"""
        if self.playing:
            current_time = time.time()
            if self.last_update_time > 0:
                dt = current_time - self.last_update_time
                self.current_time += dt

                if self.current_time >= self.duration:
                    if self.loop_animation:
                        self.current_time = 0  # Loop
                    else:
                        self.current_time = self.duration
                        self.playing = False  # Stop at end

            self.last_update_time = current_time

    def toggle_playback(self):
        """Toggle animation playback"""
        self.playing = not self.playing
        if self.playing:
            self.last_update_time = time.time()
        print(f"Animation {'PLAYING' if self.playing else 'PAUSED'}")

    def step_frame(self, direction: int):
        """Step one frame forward or backward"""
        frame_time = 1.0 / self.fps
        new_time = self.current_time + (direction * frame_time)
        self.current_time = max(0, int(min(self.duration, new_time)))
        print(f"Stepped to frame {int(self.current_time * self.fps)}")

    def go_to_time(self, given_time: float):
        """Go to specific time"""
        self.current_time = max(0, int(min(self.duration, given_time)))

    def set_duration(self, new_duration: float):
        """Set animation duration"""
        if new_duration > 0:
            self.duration = new_duration
            self.current_time = min(self.current_time, self.duration)

    def add_keyframe_at_current_time(self, instance_id: str):
        """Add keyframe for instance at current time"""
        if instance_id not in self.instances or instance_id not in self.animation_tracks:
            return

        inst = self.instances[instance_id]
        track = self.animation_tracks[instance_id]

        # Check if keyframe already exists at this time
        existing_kf = track.get_keyframe_at_time(self.current_time)
        if existing_kf:
            # Update existing keyframe
            existing_kf.x = inst.x
            existing_kf.y = inst.y
            existing_kf.rotation = inst.rotation
            existing_kf.scale_x = inst.scale_x
            existing_kf.scale_y = inst.scale_y
            existing_kf.opacity = inst.opacity
            print(f"Updated keyframe for {instance_id} at {self.current_time:.2f}s")
        else:
            # Create new keyframe
            keyframe = Keyframe(
                time=self.current_time,
                instance_id=instance_id,
                x=inst.x,
                y=inst.y,
                rotation=inst.rotation,
                scale_x=inst.scale_x,
                scale_y=inst.scale_y,
                opacity=inst.opacity
            )

            track.add_keyframe(keyframe)
            print(f"Added keyframe for {instance_id} at {self.current_time:.2f}s")

    def delete_keyframe_at_current_time(self, instance_id: str):
        """Delete keyframe at current time"""
        if instance_id not in self.animation_tracks:
            return

        track = self.animation_tracks[instance_id]
        if track.remove_keyframe_at_time(self.current_time):
            print(f"Deleted keyframe for {instance_id} at {self.current_time:.2f}s")

    def set_keyframe_interpolation(self, instance_id: str, given_time: float, interpolation: InterpolationType):
        """Set interpolation mode for keyframe"""
        if instance_id not in self.animation_tracks:
            return

        track = self.animation_tracks[instance_id]
        keyframe = track.get_keyframe_at_time(given_time)
        if keyframe:
            keyframe.interpolation = interpolation
            print(f"Set {instance_id} keyframe at {given_time:.2f}s to {interpolation.value}")

    def apply_animation_at_time(self, given_time: float):
        """Apply animation transforms to all instances at given time"""
        for inst_id, track in self.animation_tracks.items():
            if inst_id in self.instances:
                inst = self.instances[inst_id]
                x, y, rotation, scale_x, scale_y, opacity = track.get_transform_at_time(given_time)

                inst.x = x
                inst.y = y
                inst.rotation = rotation
                inst.scale_x = scale_x
                inst.scale_y = scale_y
                inst.opacity = opacity

    # ========================================================================
    # HIERARCHY SYSTEM
    # ========================================================================

    def build_hierarchy(self):
        self.hierarchy_nodes.clear()

        # Add root instances first
        for iid, inst in self.instances.items():
            if inst.parent_id is None:
                self.add_hierarchy_node(
                    iid,
                    f"{inst.sprite_name}[{iid}]",
                    'instances',
                    metadata={'instance': inst}
                )
                self._add_instance_children(iid)

    def _add_instance_children(self, parent_id: str):
        parent_inst = self.instances[parent_id]

        for child_id in parent_inst.children:
            if child_id in self.instances:
                child_inst = self.instances[child_id]
                attachment_char = "E" if child_inst.parent_attachment == AttachmentPoint.ENDPOINT else "O"
                layer_char = child_inst.layer.value[0].upper()

                self.add_hierarchy_node(
                    child_id,
                    f"{child_inst.sprite_name}[{child_id}]->{attachment_char}[{layer_char}{child_inst.layer_order}]",
                    'instances',
                    parent_id=parent_id,
                    metadata={'instance': child_inst}
                )
                self._add_instance_children(child_id)

    # ========================================================================
    # TRANSFORM CALCULATIONS (same as boneless editor)
    # ========================================================================

    def get_instance_world_transform(self, inst_id: str) -> Tuple[float, float, float, float, float]:
        """Returns (x, y, rotation, scale_x, scale_y) in world space"""
        if inst_id not in self.instances:
            return 0, 0, 0, 1, 1

        inst = self.instances[inst_id]
        local_transform = (inst.x, inst.y, inst.rotation, inst.scale_x, inst.scale_y)

        if inst.parent_id and inst.parent_id in self.instances:
            parent_transform = self.get_instance_world_transform(inst.parent_id)

            # Get parent's attachment point
            parent_inst = self.instances[inst.parent_id]
            if inst.parent_attachment == AttachmentPoint.ENDPOINT and parent_inst.sprite_name in self.palette:
                sprite = self.palette[parent_inst.sprite_name]
                # Calculate endpoint position
                parent_x, parent_y, parent_rot, parent_sx, parent_sy = parent_transform

                # Get sprite dimensions
                sprite_width = sprite.width * parent_sx
                sprite_height = sprite.height * parent_sy

                # Calculate endpoint offset
                endpoint_offset_x = (sprite.endpoint_x - sprite.origin_x) * sprite_width
                endpoint_offset_y = (sprite.endpoint_y - sprite.origin_y) * sprite_height

                # Rotate offset by parent rotation
                cos_r = math.cos(math.radians(parent_rot))
                sin_r = math.sin(math.radians(parent_rot))

                rotated_x = endpoint_offset_x * cos_r - endpoint_offset_y * sin_r
                rotated_y = endpoint_offset_x * sin_r + endpoint_offset_y * cos_r

                # Adjust parent position to attachment point
                parent_transform = (
                    parent_x + rotated_x,
                    parent_y + rotated_y,
                    parent_rot,
                    parent_sx,
                    parent_sy
                )

            return self.combine_transforms(parent_transform, local_transform)
        else:
            return local_transform

    @staticmethod
    def combine_transforms(parent_t: Tuple[float, float, float, float, float],
                           local_t: Tuple[float, float, float, float, float]) -> Tuple[
        float, float, float, float, float]:
        """Combine parent and local transforms"""
        px, py, prot, psx, psy = parent_t
        lx, ly, lrot, lsx, lsy = local_t

        # Scale
        sx = psx * lsx
        sy = psy * lsy

        # Rotation
        rotation = prot + lrot

        # Translation
        cos_r = math.cos(math.radians(prot))
        sin_r = math.sin(math.radians(prot))

        # Rotate local position by parent rotation and scale
        rotated_x = (lx * psx) * cos_r - (ly * psy) * sin_r
        rotated_y = (lx * psx) * sin_r + (ly * psy) * cos_r

        x = px + rotated_x
        y = py + rotated_y

        return x, y, rotation, sx, sy

    # ========================================================================
    # EVENT HANDLING
    # ========================================================================

    def handle_keydown(self, event) -> bool:
        if super().handle_keydown(event):
            return True

        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]
        shift_pressed = pygame.key.get_pressed()[pygame.K_LSHIFT]

        # Animation controls
        if event.key == pygame.K_SPACE:
            self.toggle_playback()
            return True

        elif event.key == pygame.K_LEFT:
            if ctrl_pressed:
                self.go_to_time(0.0)  # Go to start
            else:
                self.step_frame(-1)
            return True

        elif event.key == pygame.K_RIGHT:
            if ctrl_pressed:
                self.go_to_time(self.duration)  # Go to end
            else:
                self.step_frame(1)
            return True

        elif event.key == pygame.K_HOME:
            self.go_to_time(0.0)
            return True

        elif event.key == pygame.K_END:
            self.go_to_time(self.duration)
            return True

        # Keyframe operations
        elif event.key == pygame.K_k:
            selected = self.get_first_selected('instances')
            if selected:
                self.add_keyframe_at_current_time(selected)
            return True

        elif event.key == pygame.K_x and shift_pressed:
            selected = self.get_first_selected('instances')
            if selected:
                self.delete_keyframe_at_current_time(selected)
            return True

        # Recording mode
        elif event.key == pygame.K_r and ctrl_pressed:
            self.recording_mode = not self.recording_mode
            print(f"Recording mode: {'ON' if self.recording_mode else 'OFF'}")
            return True

        # Onion skinning
        elif event.key == pygame.K_o and ctrl_pressed:
            self.onion_skin_enabled = not self.onion_skin_enabled
            print(f"Onion skinning: {'ON' if self.onion_skin_enabled else 'OFF'}")
            return True

        # Import scene
        elif event.key == pygame.K_e and ctrl_pressed:
            self.import_scene()
            return True

        # Interpolation shortcuts for selected keyframes
        elif event.key == pygame.K_1:
            self.set_selected_keyframes_interpolation(InterpolationType.LINEAR)
            return True
        elif event.key == pygame.K_2:
            self.set_selected_keyframes_interpolation(InterpolationType.EASE_IN)
            return True
        elif event.key == pygame.K_3:
            self.set_selected_keyframes_interpolation(InterpolationType.EASE_OUT)
            return True
        elif event.key == pygame.K_4:
            self.set_selected_keyframes_interpolation(InterpolationType.EASE_IN_OUT)
            return True
        elif event.key == pygame.K_5:
            self.set_selected_keyframes_interpolation(InterpolationType.CONSTANT)
            return True

        return False

    def set_selected_keyframes_interpolation(self, interpolation: InterpolationType):
        """Set interpolation for selected keyframes"""
        if not self.selected_keyframes:
            return

        for instance_id, temp_time in self.selected_keyframes:
            self.set_keyframe_interpolation(instance_id, temp_time, interpolation)

    def import_scene(self):
        """Import scene from boneless editor"""
        self.load_scene_from_file(self.scene_file)
        print("Scene imported! Previous animation data cleared.")

    def handle_viewport_click(self, pos):
        """Handle clicks in main viewport"""
        # Check if clicking on timeline
        if pos[1] > self.screen.get_height() - self.timeline_height:
            self.handle_timeline_click(pos)
            return

        # Standard viewport interaction - no dragging/gizmos in animation mode)
        viewport_pos = self.screen_to_viewport(pos)
        hit_instance = self.get_instance_at_point(viewport_pos)

        if hit_instance:
            self.select_object('instances', hit_instance)
        else:
            self.clear_selection()

    def handle_timeline_click(self, pos):
        """Handle clicks on animation timeline"""
        x, y = pos
        timeline_y = self.screen.get_height() - self.timeline_height
        timeline_rect = pygame.Rect(0, timeline_y, self.screen.get_width(), self.timeline_height)

        if not timeline_rect.collidepoint(pos):
            return

        # Calculate time from click position
        time_ruler_y = timeline_y + 60
        ruler_width = self.screen.get_width() - 100

        if time_ruler_y <= y <= time_ruler_y + 40:
            # Clicking on time ruler
            relative_x = x - 50
            if 0 <= relative_x <= ruler_width:
                clicked_time = (relative_x / ruler_width) * self.duration
                self.go_to_time(clicked_time)
                self.dragging_time_scrubber = True
                return

        # Check for keyframe clicks
        track_area_y = time_ruler_y + 50
        for i, (inst_id, track) in enumerate(self.animation_tracks.items()):
            track_y = track_area_y + i * self.track_height

            if track_y <= y <= track_y + self.track_height:
                # Check keyframes in this track
                for keyframe in track.keyframes:
                    kf_x = 50 + (keyframe.time / self.duration) * ruler_width

                    if abs(x - kf_x) <= 6:  # Hit tolerance
                        # Keyframe clicked
                        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]

                        if ctrl_pressed:
                            # Multi-select
                            kf_id = (inst_id, keyframe.time)
                            if kf_id in self.selected_keyframes:
                                self.selected_keyframes.remove(kf_id)
                            else:
                                self.selected_keyframes.append(kf_id)
                        else:
                            # Single select
                            self.selected_keyframes = [(inst_id, keyframe.time)]

                        # Start dragging keyframe
                        self.dragging_keyframe = True
                        self.dragging_keyframe_instance = inst_id
                        self.dragging_keyframe_time = keyframe.time
                        self.keyframe_drag_offset = x - kf_x

                        print(f"Selected keyframe: {inst_id} at {keyframe.time:.2f}s")
                        return

    def handle_mouse_drag(self, pos):
        """Handle mouse dragging"""
        if self.dragging_time_scrubber:
            # Update time scrubber position
            timeline_y = self.screen.get_height() - self.timeline_height
            ruler_width = self.screen.get_width() - 100
            relative_x = pos[0] - 50

            if 0 <= relative_x <= ruler_width:
                new_time = (relative_x / ruler_width) * self.duration
                self.go_to_time(new_time)

        elif self.dragging_keyframe and self.dragging_keyframe_instance and self.dragging_keyframe_time is not None:
            # Drag keyframe to new time
            timeline_y = self.screen.get_height() - self.timeline_height
            ruler_width = self.screen.get_width() - 100
            relative_x = pos[0] - 50 - self.keyframe_drag_offset

            if 0 <= relative_x <= ruler_width:
                new_time = (relative_x / ruler_width) * self.duration
                new_time = max(0, int(min(self.duration, new_time)))

                # Move keyframe to new time
                track = self.animation_tracks[self.dragging_keyframe_instance]
                keyframe = track.get_keyframe_at_time(self.dragging_keyframe_time)

                if keyframe:
                    # Remove from old time and add at new time
                    track.keyframes.remove(keyframe)
                    keyframe.time = new_time
                    track.add_keyframe(keyframe)

                    # Update selection
                    for i, (inst_id, temp_time) in enumerate(self.selected_keyframes):
                        if (inst_id == self.dragging_keyframe_instance and
                                abs(temp_time - self.dragging_keyframe_time) < 0.016):
                            self.selected_keyframes[i] = (inst_id, new_time)

                    self.dragging_keyframe_time = new_time

    def handle_left_click_release(self, pos):
        """Handle left click release"""
        self.dragging_time_scrubber = False
        self.dragging_keyframe = False
        self.dragging_keyframe_instance = None
        self.dragging_keyframe_time = None
        self.keyframe_drag_offset = 0

    def get_instance_at_point(self, pos) -> Optional[str]:
        """Find instance at given world position"""
        for iid in reversed(list(self.instances.keys())):
            if not self.instances[iid].visible:
                continue

            transform = self.get_instance_world_transform(iid)
            world_x, world_y = transform[0], transform[1]

            distance = math.sqrt((pos[0] - world_x) ** 2 + (pos[1] - world_y) ** 2)
            hit_radius = 15 / self.viewport.zoom

            if distance <= hit_radius:
                return iid

        return None

    # ========================================================================
    # DRAWING SYSTEM
    # ========================================================================

    def draw(self):
        """Main drawing pipeline with animation update"""
        self.update()

        # Apply current animation state
        self.apply_animation_at_time(self.current_time)

        super().draw()

    def draw_objects(self):
        """Draw all instances with animation applied"""
        # Draw onion skins first
        if self.onion_skin_enabled:
            self.draw_onion_skins()

        # Group instances by layer
        layered_instances = {
            InstanceLayer.BEHIND: [],
            InstanceLayer.MIDDLE: [],
            InstanceLayer.FRONT: []
        }

        for iid, inst in self.instances.items():
            if inst.visible:
                layered_instances[inst.layer].append((inst.layer_order, iid, inst))

        # Sort each layer by layer_order
        for layer in layered_instances:
            layered_instances[layer].sort(key=lambda x: x[0])

        # Draw connection lines first
        self.draw_connections()

        # Draw in layer order: BEHIND -> MIDDLE -> FRONT
        for layer in [InstanceLayer.BEHIND, InstanceLayer.MIDDLE, InstanceLayer.FRONT]:
            for layer_order, iid, inst in layered_instances[layer]:
                self.draw_instance(iid)

    def draw_onion_skins(self):
        """Draw onion skin frames"""
        frame_time = 1.0 / self.fps

        for i in range(1, self.onion_skin_frames + 1):
            # Past frames
            past_time = self.current_time - (i * frame_time)
            if past_time >= 0:
                self.draw_onion_skin_at_time(past_time, self.onion_skin_alpha, (0, 100, 255))  # Blue for past

            # Future frames
            future_time = self.current_time + (i * frame_time)
            if future_time <= self.duration:
                self.draw_onion_skin_at_time(future_time, self.onion_skin_alpha, (255, 100, 0))  # Orange for future

    def draw_onion_skin_at_time(self, given_time: float, alpha: int, tint_color: Tuple[int, int, int]):
        """Draw onion skin at specific time"""
        # Temporarily apply animation at the onion skin time
        temp_transforms = {}
        for inst_id in self.instances:
            inst = self.instances[inst_id]
            temp_transforms[inst_id] = (inst.x, inst.y, inst.rotation, inst.scale_x, inst.scale_y, inst.opacity)

        # Apply onion skin time animation
        for inst_id, track in self.animation_tracks.items():
            if inst_id in self.instances:
                inst = self.instances[inst_id]
                x, y, rotation, scale_x, scale_y, opacity = track.get_transform_at_time(given_time)
                inst.x = x
                inst.y = y
                inst.rotation = rotation
                inst.scale_x = scale_x
                inst.scale_y = scale_y
                inst.opacity = opacity

        # Draw instances as onion skins
        for iid, inst in self.instances.items():
            if inst.visible:
                self.draw_instance_onion_skin(iid, alpha, tint_color)

        # Restore original transforms
        for inst_id, (x, y, rot, sx, sy, op) in temp_transforms.items():
            inst = self.instances[inst_id]
            inst.x = x
            inst.y = y
            inst.rotation = rot
            inst.scale_x = sx
            inst.scale_y = sy
            inst.opacity = op

    def draw_instance_onion_skin(self, instance_id: str, alpha: int, tint_color: Tuple[int, int, int]):
        """Draw instance as onion skin"""
        inst = self.instances[instance_id]
        sprite = self.palette.get(inst.sprite_name)

        if not sprite:
            return

        world_transform = self.get_instance_world_transform(instance_id)
        world_x, world_y, world_rot, world_sx, world_sy = world_transform

        origin_screen = self.viewport_to_screen((world_x, world_y))

        # Draw simple onion skin shape
        radius = max(2, int(8 * self.viewport.zoom))
        temp_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(temp_surf, (*tint_color, alpha), (radius, radius), radius)
        self.screen.blit(temp_surf, (int(origin_screen[0] - radius), int(origin_screen[1] - radius)))

    def draw_instance(self, instance_id: str):
        """Draw a single instance with current animation state"""
        inst = self.instances[instance_id]
        sprite = self.palette.get(inst.sprite_name)

        if not sprite:
            return

        world_transform = self.get_instance_world_transform(instance_id)
        world_x, world_y, world_rot, world_sx, world_sy = world_transform

        origin_screen = self.viewport_to_screen((world_x, world_y))

        # Apply opacity
        alpha = int(inst.opacity * 255)

        # Draw sprite if sprite sheet is loaded
        if self.sprite_sheet:
            try:
                sprite_surface = self.sprite_sheet.subsurface((sprite.x, sprite.y, sprite.width, sprite.height))

                final_width = max(1, int(sprite.width * world_sx * self.viewport.zoom))
                final_height = max(1, int(sprite.height * world_sy * self.viewport.zoom))

                scaled_sprite = pygame.transform.scale(sprite_surface, (final_width, final_height))

                if alpha < 255:
                    scaled_sprite = scaled_sprite.copy()
                    scaled_sprite.set_alpha(alpha)

                origin_offset_x = sprite.origin_x * final_width
                origin_offset_y = sprite.origin_y * final_height

                if abs(world_rot) > 0.01:
                    max_dim = max(final_width, final_height) * 2
                    rotation_surface = pygame.Surface((max_dim, max_dim), pygame.SRCALPHA)

                    sprite_pos_in_rotation = (
                        max_dim // 2 - origin_offset_x,
                        max_dim // 2 - origin_offset_y
                    )
                    rotation_surface.blit(scaled_sprite, sprite_pos_in_rotation)

                    rotated_surface = pygame.transform.rotate(rotation_surface, -world_rot)
                    rotated_rect = rotated_surface.get_rect()

                    final_pos = (
                        origin_screen[0] - rotated_rect.width // 2,
                        origin_screen[1] - rotated_rect.height // 2
                    )

                    self.screen.blit(rotated_surface, final_pos)

                else:
                    sprite_pos = (
                        origin_screen[0] - origin_offset_x,
                        origin_screen[1] - origin_offset_y
                    )
                    self.screen.blit(scaled_sprite, sprite_pos)

            except pygame.error:
                self.draw_instance_placeholder(instance_id, origin_screen, sprite, world_sx, world_sy, alpha)
        else:
            self.draw_instance_placeholder(instance_id, origin_screen, sprite, world_sx, world_sy, alpha)

        # Draw attachment points
        self.draw_attachment_points(sprite, world_transform)

        # Draw selection highlight
        if self.is_object_selected('instances', instance_id):
            radius = max(3, int(6 * self.viewport.zoom))
            temp_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp_surf, (255, 255, 0, 80), (radius, radius), radius)
            self.screen.blit(temp_surf, (int(origin_screen[0] - radius), int(origin_screen[1] - radius)))

        # Draw instance label
        if self.viewport.zoom > 0.5:
            layer_char = inst.layer.value[0].upper()
            label = self.small_font.render(f"{inst.sprite_name}[{instance_id}][{layer_char}{inst.layer_order}]",
                                           True,
                                           (255, 255, 255))
            self.screen.blit(label, (origin_screen[0] + 10, origin_screen[1] - 20))

    def draw_instance_placeholder(self, instance_id: str, origin_screen: Tuple[int, int], sprite: SpriteRect,
                                  sx: float, sy: float, alpha: int = 255):
        """Draw placeholder rectangle for instance"""
        w = max(8, sprite.width * sx * self.viewport.zoom * 0.3)
        h = max(8, sprite.height * sy * self.viewport.zoom * 0.3)

        origin_offset_x = sprite.origin_x * w
        origin_offset_y = sprite.origin_y * h

        rect = pygame.Rect(
            origin_screen[0] - origin_offset_x,
            origin_screen[1] - origin_offset_y,
            w, h
        )

        inst = self.instances[instance_id]
        if self.is_object_selected('instances', instance_id):
            color = (255, 255, 100)
        else:
            if inst.layer == InstanceLayer.BEHIND:
                color = (100, 100, 255)  # Blue
            elif inst.layer == InstanceLayer.FRONT:
                color = (255, 100, 100)  # Red
            else:  # MIDDLE
                color = (100, 255, 100)  # Green

        if alpha < 255:
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(surf, (*color, alpha), surf.get_rect())
            pygame.draw.rect(surf, (255, 255, 255), surf.get_rect(), 1)
            self.screen.blit(surf, rect.topleft)
        else:
            pygame.draw.rect(self.screen, color, rect)
            pygame.draw.rect(self.screen, (255, 255, 255), rect, 1)

    def draw_attachment_points(self, sprite: SpriteRect,
                               world_transform: Tuple[float, float, float, float, float]):
        """Draw origin and endpoint dots"""
        world_x, world_y, world_rot, world_sx, world_sy = world_transform

        origin_world_x = world_x
        origin_world_y = world_y
        origin_screen = self.viewport_to_screen((origin_world_x, origin_world_y))

        sprite_width = sprite.width * world_sx
        sprite_height = sprite.height * world_sy

        endpoint_offset_x = (sprite.endpoint_x - sprite.origin_x) * sprite_width
        endpoint_offset_y = (sprite.endpoint_y - sprite.origin_y) * sprite_height

        cos_r = math.cos(math.radians(world_rot))
        sin_r = math.sin(math.radians(world_rot))

        rotated_endpoint_x = endpoint_offset_x * cos_r - endpoint_offset_y * sin_r
        rotated_endpoint_y = endpoint_offset_x * sin_r + endpoint_offset_y * cos_r

        endpoint_world_x = origin_world_x + rotated_endpoint_x
        endpoint_world_y = origin_world_y + rotated_endpoint_y
        endpoint_screen = self.viewport_to_screen((endpoint_world_x, endpoint_world_y))

        # Draw connection line
        pygame.draw.line(self.screen, (255, 165, 0), origin_screen, endpoint_screen, 2)

        # Draw origin dot (red)
        pygame.draw.circle(self.screen, (255, 0, 0), (int(origin_screen[0]), int(origin_screen[1])), 4)
        pygame.draw.circle(self.screen, (255, 255, 255), (int(origin_screen[0]), int(origin_screen[1])), 4, 1)

        # Draw endpoint dot (blue)
        pygame.draw.circle(self.screen, (0, 0, 255), (int(endpoint_screen[0]), int(endpoint_screen[1])), 4)
        pygame.draw.circle(self.screen, (255, 255, 255), (int(endpoint_screen[0]), int(endpoint_screen[1])), 4, 1)

    def draw_connections(self):
        """Draw parent-child connection lines"""
        for iid, inst in self.instances.items():
            if inst.parent_id and inst.parent_id in self.instances:
                parent_inst = self.instances[inst.parent_id]

                parent_transform = self.get_instance_world_transform(inst.parent_id)
                parent_x, parent_y = parent_transform[0], parent_transform[1]

                child_transform = self.get_instance_world_transform(iid)
                child_x, child_y = child_transform[0], child_transform[1]

                if inst.parent_attachment == AttachmentPoint.ENDPOINT:
                    parent_sprite = self.palette.get(parent_inst.sprite_name)
                    if parent_sprite:
                        sprite_width = parent_sprite.width * parent_transform[3]
                        sprite_height = parent_sprite.height * parent_transform[4]

                        endpoint_offset_x = (parent_sprite.endpoint_x - parent_sprite.origin_x) * sprite_width
                        endpoint_offset_y = (parent_sprite.endpoint_y - parent_sprite.origin_y) * sprite_height

                        cos_r = math.cos(math.radians(parent_transform[2]))
                        sin_r = math.sin(math.radians(parent_transform[2]))

                        rotated_x = endpoint_offset_x * cos_r - endpoint_offset_y * sin_r
                        rotated_y = endpoint_offset_x * sin_r + endpoint_offset_y * cos_r

                        attach_x = parent_x + rotated_x
                        attach_y = parent_y + rotated_y
                    else:
                        attach_x, attach_y = parent_x, parent_y

                    connection_color = (0, 255, 255)  # Cyan for endpoint attachment
                else:
                    attach_x, attach_y = parent_x, parent_y
                    connection_color = (255, 165, 0)  # Orange for origin attachment

                parent_screen = self.viewport_to_screen((attach_x, attach_y))
                child_screen = self.viewport_to_screen((child_x, child_y))

                pygame.draw.line(self.screen, connection_color, parent_screen, child_screen, 3)

    def draw_main_viewport(self):
        """Override to account for timeline"""
        # Reduce viewport height to account for timeline
        viewport_rect = self.get_main_viewport_rect()
        viewport_rect.height -= self.timeline_height

        pygame.draw.rect(self.screen, (0, 0, 0), viewport_rect)
        self.screen.set_clip(viewport_rect)

        self.draw_grid()
        self.draw_objects()

        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, (255, 255, 255), viewport_rect, 2)

        # Draw timeline
        self.draw_timeline()

    def draw_timeline(self):
        """Draw animation timeline"""
        timeline_y = self.screen.get_height() - self.timeline_height
        timeline_rect = pygame.Rect(0, timeline_y, self.screen.get_width(), self.timeline_height)

        # Background
        pygame.draw.rect(self.screen, (64, 64, 64), timeline_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), timeline_rect, 2)

        # Title and info
        title = self.font.render("Animation Timeline", True, (255, 255, 255))
        self.screen.blit(title, (10, timeline_y + 10))

        # Playback info
        info_text = f"Time: {self.current_time:.2f}s/{self.duration:.1f}s | Frame: {int(self.current_time * self.fps)}/{int(self.duration * self.fps)} | FPS: {self.fps}"
        if self.playing:
            info_text += " | PLAYING"
        if self.recording_mode:
            info_text += " | RECORDING"
        if self.onion_skin_enabled:
            info_text += " | ONION"

        info_surface = self.small_font.render(info_text, True, (255, 255, 255))
        self.screen.blit(info_surface, (10, timeline_y + 35))

        # Time ruler
        ruler_y = timeline_y + 60
        ruler_width = self.screen.get_width() - 100

        # Draw time markers
        seconds_per_mark = max(1, int(self.duration / 10))
        for i in range(0, int(self.duration) + 1, seconds_per_mark):
            x = 50 + (i / self.duration) * ruler_width
            pygame.draw.line(self.screen, (255, 255, 255), (x, ruler_y), (x, ruler_y + 20))

            time_text = self.small_font.render(f"{i}s", True, (255, 255, 255))
            self.screen.blit(time_text, (x - 10, ruler_y + 25))

        # Current time indicator
        current_x = 50 + (self.current_time / self.duration) * ruler_width
        pygame.draw.line(self.screen, (255, 255, 0), (current_x, ruler_y), (current_x, timeline_rect.bottom), 3)

        # Instance tracks
        track_y = ruler_y + 50
        for i, (inst_id, track) in enumerate(self.animation_tracks.items()):
            inst = self.instances[inst_id]
            track_rect = pygame.Rect(10, track_y + i * self.track_height, self.screen.get_width() - 20,
                                     self.track_height)

            # Alternate track background colors
            track_color = (80, 80, 80) if i % 2 == 0 else (70, 70, 70)
            pygame.draw.rect(self.screen, track_color, track_rect)

            # Track name with layer info
            layer_char = inst.layer.value[0].upper()
            track_text = self.small_font.render(f"{inst.sprite_name}[{inst_id}][{layer_char}{inst.layer_order}]",
                                                True,
                                                (255, 255, 255))
            self.screen.blit(track_text, (15, track_y + i * self.track_height + 5))

            kf_color = (0, 0, 0)

            # Keyframes
            for keyframe in track.keyframes:
                kf_x = 50 + (keyframe.time / self.duration) * ruler_width

                # Color based on interpolation
                if keyframe.interpolation == InterpolationType.LINEAR:
                    kf_color = (255, 255, 255)
                elif keyframe.interpolation == InterpolationType.EASE_IN:
                    kf_color = (255, 100, 100)
                elif keyframe.interpolation == InterpolationType.EASE_OUT:
                    kf_color = (100, 100, 255)
                elif keyframe.interpolation == InterpolationType.EASE_IN_OUT:
                    kf_color = (255, 100, 255)
                elif keyframe.interpolation == InterpolationType.CONSTANT:
                    kf_color = (100, 255, 100)

                # Check if keyframe is selected
                is_selected = (inst_id, keyframe.time) in self.selected_keyframes

                if is_selected:
                    # Draw selection highlight
                    pygame.draw.circle(self.screen, (255, 255, 0),
                                       (int(kf_x), int(track_y + i * self.track_height + 12)), 8)

                pygame.draw.circle(self.screen, kf_color, (int(kf_x), int(track_y + i * self.track_height + 12)), 6)
                pygame.draw.circle(self.screen, (0, 0, 0), (int(kf_x), int(track_y + i * self.track_height + 12)),
                                   6, 1)

        # Draw interpolation legend
        legend_y = timeline_rect.bottom - 50
        legend_items = [
            ("Linear", (255, 255, 255)),
            ("Ease In", (255, 100, 100)),
            ("Ease Out", (100, 100, 255)),
            ("Ease In/Out", (255, 100, 255)),
            ("Constant", (100, 255, 100))
        ]

        legend_x = self.screen.get_width() - 300
        for i, (name, color) in enumerate(legend_items):
            x = legend_x + (i * 60)
            pygame.draw.circle(self.screen, color, (x, legend_y), 4)
            text = self.small_font.render(name, True, (255, 255, 255))
            self.screen.blit(text, (x - 15, legend_y + 10))

    def draw_properties_content(self, panel_rect, y_offset):
        """Draw animator properties panel content"""
        # Animation info
        anim_text = self.font.render("ANIMATION MODE", True, (255, 0, 0))
        self.screen.blit(anim_text, (panel_rect.x + 10, y_offset))
        y_offset += 30

        # Current time and playback info
        time_info = [
            f"Time: {self.current_time:.2f}s / {self.duration:.1f}s",
            f"Frame: {int(self.current_time * self.fps)} / {int(self.duration * self.fps)}",
            f"FPS: {self.fps}",
            f"Playing: {'Yes' if self.playing else 'No'}",
            f"Loop: {'Yes' if self.loop_animation else 'No'}",
            f"Recording: {'ON' if self.recording_mode else 'OFF'}",
            f"Onion Skin: {'ON' if self.onion_skin_enabled else 'OFF'}"
        ]

        for info in time_info:
            text = self.small_font.render(info, True, (0, 0, 0))
            self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 18

        y_offset += 10

        # Selected instance info
        selected = self.get_first_selected('instances')
        if selected and selected in self.instances:
            inst = self.instances[selected]

            inst_text = self.font.render(f"Selected: {inst.sprite_name}[{selected}]", True, (0, 0, 0))
            self.screen.blit(inst_text, (panel_rect.x + 10, y_offset))
            y_offset += 25

            # Current animated values
            info_lines = [
                f"Position: ({inst.x:.1f}, {inst.y:.1f})",
                f"Rotation: {inst.rotation:.1f}°",
                f"Scale: ({inst.scale_x:.2f}, {inst.scale_y:.2f})",
                f"Opacity: {inst.opacity:.2f}",
                f"Layer: {inst.layer.value.upper()} (Order: {inst.layer_order})",
                f"Parent: {inst.parent_id or 'None'}",
                f"Children: {len(inst.children)}"
            ]

            for line in info_lines:
                text = self.small_font.render(line, True, (0, 0, 0))
                self.screen.blit(text, (panel_rect.x + 20, y_offset))
                y_offset += 18

            # Keyframe info
            if selected in self.animation_tracks:
                track = self.animation_tracks[selected]
                kf_at_current = track.get_keyframe_at_time(self.current_time)

                if kf_at_current:
                    kf_text = f"Keyframe at {self.current_time:.2f}s ({kf_at_current.interpolation.value})"
                    color = (0, 255, 0)
                else:
                    kf_text = f"No keyframe at {self.current_time:.2f}s"
                    color = (255, 0, 0)

                kf_surface = self.small_font.render(kf_text, True, color)
                self.screen.blit(kf_surface, (panel_rect.x + 20, y_offset))
                y_offset += 18

                total_kf_text = f"Total keyframes: {len(track.keyframes)}"
                total_kf_surface = self.small_font.render(total_kf_text, True, (0, 0, 0))
                self.screen.blit(total_kf_surface, (panel_rect.x + 20, y_offset))
                y_offset += 18

        y_offset += 20

        # Selected keyframes info
        if self.selected_keyframes:
            sel_kf_text = f"Selected keyframes: {len(self.selected_keyframes)}"
            sel_kf_surface = self.font.render(sel_kf_text, True, (0, 0, 255))
            self.screen.blit(sel_kf_surface, (panel_rect.x + 10, y_offset))
            y_offset += 25

            for inst_id, temp_time in self.selected_keyframes[:5]:  # Show max 5
                kf_info = f"• {inst_id} at {temp_time:.2f}s"
                kf_info_surface = self.small_font.render(kf_info, True, (0, 0, 0))
                self.screen.blit(kf_info_surface, (panel_rect.x + 20, y_offset))
                y_offset += 16

            if len(self.selected_keyframes) > 5:
                more_text = f"... and {len(self.selected_keyframes) - 5} more"
                more_surface = self.small_font.render(more_text, True, (128, 128, 128))
                self.screen.blit(more_surface, (panel_rect.x + 20, y_offset))
                y_offset += 16

        y_offset += 20

        # Project stats
        stats = [
            f"Instances: {len(self.instances)}",
            f"Animation Tracks: {len(self.animation_tracks)}",
            f"Total Keyframes: {sum(len(track.keyframes) for track in self.animation_tracks.values())}",
            f"Scene File: {os.path.basename(self.scene_file)}",
            f"Sprite Sheet: {os.path.basename(self.sprite_sheet_path) if self.sprite_sheet_path else 'None'}"
        ]

        for stat in stats:
            text = self.small_font.render(stat, True, (64, 64, 64))
            self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 18

        # Controls help
        y_offset += 20
        controls = [
            "ANIMATION CONTROLS:",
            "• Space: Play/Pause",
            "• Left/Right: Step frames",
            "• Ctrl+Left/Right: Go to start/end",
            "• Home/End: Go to start/end",
            "",
            "KEYFRAMES:",
            "• K: Add keyframe for selected",
            "• Shift+X: Delete keyframe at time",
            "• Click timeline: Set time",
            "• Click keyframe: Select keyframe",
            "• Ctrl+Click: Multi-select keyframes",
            "• Drag keyframe: Move in time",
            "",
            "INTERPOLATION (for selected keyframes):",
            "• 1: Linear",
            "• 2: Ease In",
            "• 3: Ease Out",
            "• 4: Ease In/Out",
            "• 5: Constant",
            "",
            "MODES:",
            "• Ctrl+R: Toggle recording mode",
            "• Ctrl+O: Toggle onion skinning",
            "• Ctrl+E: Import scene from editor",
            "",
            "UNIVERSAL:",
            "• Ctrl+S/L: Save/Load animation",
            "• Ctrl+Z/Y: Undo/Redo"
        ]

        for control in controls:
            if control:
                if control.endswith(":"):
                    color = (255, 0, 0)
                elif control.startswith("•"):
                    color = (0, 0, 255)
                else:
                    color = (0, 0, 0)
                text = self.small_font.render(control, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 14

    # ========================================================================
    # FILE OPERATIONS
    # ========================================================================

    def serialize_data_objects(self):
        """Serialize for saving"""
        instances_data = {}
        for iid, inst in self.instances.items():
            instances_data[iid] = {
                'id': inst.id,
                'sprite_name': inst.sprite_name,
                'x': inst.x,
                'y': inst.y,
                'rotation': inst.rotation,
                'scale_x': inst.scale_x,
                'scale_y': inst.scale_y,
                'parent_id': inst.parent_id,
                'parent_attachment': inst.parent_attachment.value,
                'children': inst.children,
                'layer': inst.layer.value,
                'layer_order': inst.layer_order,
                'opacity': inst.opacity,
                'visible': inst.visible
            }

        tracks_data = {}
        for iid, track in self.animation_tracks.items():
            if track.keyframes:
                tracks_data[iid] = {
                    'instance_id': track.instance_id,
                    'keyframes': [
                        {
                            'time': kf.time,
                            'instance_id': kf.instance_id,
                            'x': kf.x,
                            'y': kf.y,
                            'rotation': kf.rotation,
                            'scale_x': kf.scale_x,
                            'scale_y': kf.scale_y,
                            'opacity': kf.opacity,
                            'interpolation': kf.interpolation.value
                        }
                        for kf in track.keyframes
                    ]
                }

        return {
            'scene_file': self.scene_file,
            'sprite_sheet_path': self.sprite_sheet_path,
            'instances': instances_data,
            'animation_tracks': tracks_data,
            'duration': self.duration,
            'fps': self.fps,
            'current_time': self.current_time,
            'loop_animation': self.loop_animation
        }

    def deserialize_data_objects(self, data):
        """Deserialize from loading"""
        # Load scene file reference
        self.scene_file = data.get('scene_file', self.scene_file)
        self.sprite_sheet_path = data.get('sprite_sheet_path', '')

        # Load animation settings
        self.duration = data.get('duration', 5.0)
        self.fps = data.get('fps', 30)
        self.current_time = data.get('current_time', 0.0)
        self.loop_animation = data.get('loop_animation', True)

        # Load palette (try to load from existing scene file first)
        palette_loaded = False
        if os.path.exists(self.scene_file):
            try:
                with open(self.scene_file, 'r') as f:
                    scene_data = json.load(f)
                palette_file = scene_data.get('data', {}).get('palette_file',
                                                              'sprite_sheet_editor_v1.0_project.json')
                self.load_palette_from_sheet_project(palette_file)
                palette_loaded = True
            except:
                pass

        if not palette_loaded:
            # Fallback to default palette file
            self.load_palette_from_sheet_project('sprite_sheet_editor_v1.0_project.json')

        # Load instances
        self.instances.clear()
        for iid, inst_data in data.get('instances', {}).items():
            attachment = AttachmentPoint(inst_data.get('parent_attachment', 'origin'))
            layer = InstanceLayer(inst_data.get('layer', 'middle'))

            self.instances[iid] = AnimInstance(
                id=inst_data['id'],
                sprite_name=inst_data['sprite_name'],
                x=inst_data.get('x', 0.0),
                y=inst_data.get('y', 0.0),
                rotation=inst_data.get('rotation', 0.0),
                scale_x=inst_data.get('scale_x', 1.0),
                scale_y=inst_data.get('scale_y', 1.0),
                parent_id=inst_data.get('parent_id'),
                parent_attachment=attachment,
                children=inst_data.get('children', []),
                layer=layer,
                layer_order=inst_data.get('layer_order', 0),
                opacity=inst_data.get('opacity', 1.0),
                visible=inst_data.get('visible', True)
            )

        # Load animation tracks
        self.animation_tracks.clear()
        for iid in self.instances.keys():
            self.animation_tracks[iid] = AnimationTrack(iid)

        for iid, track_data in data.get('animation_tracks', {}).items():
            if iid in self.animation_tracks:
                track = self.animation_tracks[iid]

                for kf_data in track_data.get('keyframes', []):
                    interpolation = InterpolationType(kf_data.get('interpolation', 'linear'))

                    keyframe = Keyframe(
                        time=kf_data['time'],
                        instance_id=kf_data['instance_id'],
                        x=kf_data.get('x', 0.0),
                        y=kf_data.get('y', 0.0),
                        rotation=kf_data.get('rotation', 0.0),
                        scale_x=kf_data.get('scale_x', 1.0),
                        scale_y=kf_data.get('scale_y', 1.0),
                        opacity=kf_data.get('opacity', 1.0),
                        interpolation=interpolation
                    )
                    track.add_keyframe(keyframe)

        return data

    def save_project(self):
        """Save animation project"""
        filename = "animation_project.json"
        try:
            project_data = {
                'editor_type': self.get_editor_name(),
                'data': self.serialize_data_objects(),
                'ui_state': {
                    'viewport': {
                        'offset': self.viewport.offset,
                        'zoom': self.viewport.zoom
                    },
                    'selected': self.ui_state.selected_objects,
                    'scroll_positions': self.ui_state.scroll_positions
                }
            }

            with open(filename, 'w') as f:
                json.dump(project_data, f, indent=2, default=str)

            print(f"Saved animation: {filename}")

        except Exception as e:
            print(f"Failed to save animation: {e}")

    def load_project(self, given_filename: str = None):
        """Load animation project"""
        if given_filename is not None:
            filename = given_filename
        else:
            filename = "animation_project.json"

        try:
            with open(filename, 'r') as f:
                project_data = json.load(f)

            self.data_objects = self.deserialize_data_objects(project_data.get('data', {}))

            # Load UI state
            ui_state = project_data.get('ui_state', {})
            if 'viewport' in ui_state:
                self.viewport.offset = ui_state['viewport'].get('offset', [50, 50])
                self.viewport.zoom = ui_state['viewport'].get('zoom', 1.0)

            self.ui_state.selected_objects = ui_state.get('selected', {})
            self.ui_state.scroll_positions = ui_state.get('scroll_positions', {})

            # Clear undo history
            self.command_history.clear()
            self.redo_stack.clear()

            print(f"Loaded animation: {filename}")
            return True

        except Exception as e:
            print(f"Failed to load animation: {e}")
            return False

    def delete_selected(self):
        """Delete selected instance and its animation track"""
        selected = self.get_first_selected('instances')
        if not selected or selected not in self.instances:
            return

        inst = self.instances[selected]

        # Remove from parent's children list
        if inst.parent_id and inst.parent_id in self.instances:
            try:
                self.instances[inst.parent_id].children.remove(selected)
            except ValueError:
                pass

        # Unparent all children
        for child_id in inst.children[:]:
            if child_id in self.instances:
                self.instances[child_id].parent_id = None
                self.instances[child_id].parent_attachment = AttachmentPoint.ORIGIN

        # Remove instance and track
        old_inst = copy.deepcopy(inst)
        del self.instances[selected]

        if selected in self.animation_tracks:
            del self.animation_tracks[selected]

        # Remove from selected keyframes
        self.selected_keyframes = [(iid, temp_time) for iid, temp_time in self.selected_keyframes if iid != selected]

        cmd = Command(
            action="delete",
            object_type="instances",
            object_id=selected,
            old_data=old_inst,
            new_data=None,
            description=f"Delete animated instance {selected}"
        )
        self.execute_command(cmd)

        self.clear_selection()
        print(f"Deleted animated instance {selected}")


# Run the animation editor
if __name__ == "__main__":
    editor = AnimatorEditor()
    editor.run()
