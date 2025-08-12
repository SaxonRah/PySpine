# boneless_anim_editor.py - ENHANCED VERSION with Drag/Drop and Layers
# A standalone "boneless" animation editor where sprites ARE the bones
#
# Place this next to core_base.py and sprite_editor.py and run:
#   python boneless_anim_editor.py

import json
import os
import math
import copy
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple, Any
from enum import Enum

import pygame

from core_base import UniversalEditor, Command, PanelType
from sprite_editor import SpriteRect


class AttachmentPoint(Enum):
    ORIGIN = "origin"
    ENDPOINT = "endpoint"


class InterpolationType(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"


class InstanceLayer(Enum):
    BEHIND = "behind"
    MIDDLE = "middle"
    FRONT = "front"


@dataclass
class AnimInstance:
    """An instance of a palette sprite placed in the scene."""
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

    def get_transform_at_time(self, time: float) -> Tuple[float, float, float, float, float]:
        """Returns (x, y, rotation, scale_x, scale_y)"""
        if not self.keyframes:
            return 0.0, 0.0, 0.0, 1.0, 1.0

        if time <= self.keyframes[0].time:
            kf = self.keyframes[0]
            return kf.x, kf.y, kf.rotation, kf.scale_x, kf.scale_y

        if time >= self.keyframes[-1].time:
            kf = self.keyframes[-1]
            return kf.x, kf.y, kf.rotation, kf.scale_x, kf.scale_y

        # Find keyframes to interpolate between
        for i in range(len(self.keyframes) - 1):
            kf1 = self.keyframes[i]
            kf2 = self.keyframes[i + 1]

            if kf1.time <= time <= kf2.time:
                t = (time - kf1.time) / (kf2.time - kf1.time)

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

                return x, y, rotation, scale_x, scale_y

        return 0.0, 0.0, 0.0, 1.0, 1.0


class BonelessAnimEditor(UniversalEditor):
    def __init__(self, palette_project_file="sprite_sheet_editor_v1.0_project.json"):
        self.palette_file = palette_project_file
        super().__init__()

        # Data
        self.palette: Dict[str, SpriteRect] = {}
        self.instances: Dict[str, AnimInstance] = {}
        self.animation_tracks: Dict[str, AnimationTrack] = {}
        self.sprite_sheet = None
        self.sprite_sheet_path = ""

        # Editor state
        self.mode = "SETUP"  # or "ANIMATE"
        self.next_instance_index = 0

        # Animation state
        self.current_time = 0.0
        self.duration = 5.0
        self.fps = 30
        self.playing = False
        self.last_update_time = 0.0

        # Interaction state
        self.dragging_instance_id: Optional[str] = None
        self.rotating_instance = False
        self.scaling_instance = False
        self.drag_offset = (0, 0)
        self.drag_start_rotation = 0.0
        self.drag_start_scale = (1.0, 1.0)

        # Drag and drop state
        self.dragging_from_palette = False
        self.dragging_from_hierarchy = False
        self.palette_drag_sprite = None
        self.hierarchy_drag_instance = None
        self.drag_preview_pos = None
        self.snap_target = None
        self.snap_attachment = None

        # Visual settings
        self.connector_color = (255, 165, 0)
        self.connector_thickness = 3
        self.timeline_height = 200
        self.palette_scroll = 0

        # Transform gizmo settings
        self.gizmo_size = 10
        self.rotation_handle_distance = 30

        # Snapping settings
        self.snap_distance = 20
        self.snap_visual_radius = 10

        # Palette panel and timeline
        prop_rect = self.panel_configs[PanelType.PROPERTIES]['rect']
        palette_width = 250
        self.panel_configs[PanelType.PALETTE] = {
            'rect': pygame.Rect(prop_rect.x - palette_width, prop_rect.y, palette_width, prop_rect.height),
            'visible': True,
            'scrollable': True
        }

        # Adjust properties panel
        prop_rect.x -= palette_width

        self.setup_data_structures()
        self.setup_key_bindings()
        self.load_palette_from_sheet_project(self.palette_file)

        if os.path.exists("boneless_anim_project.json"):
            self.load_project()

    def setup_data_structures(self):
        self.data_objects = {
            'instances': {},
            'animation_tracks': {},
            'palette_ref': self.palette_file,
            'duration': 5.0,
            'fps': 30
        }

    def setup_key_bindings(self):
        pass

    def get_editor_name(self) -> str:
        return "Boneless Animation Editor"

    # ========================================================================
    # PALETTE & SPRITE SHEET LOADING
    # ========================================================================

    def load_palette_from_sheet_project(self, filename: str):
        if not os.path.exists(filename):
            print(f"Palette file not found: {filename}")
            return False

        try:
            with open(filename, 'r') as f:
                data = json.load(f)

            # Load sprite sheet path
            sprite_data = data.get('data', {})
            self.sprite_sheet_path = sprite_data.get('sprite_sheet_path', '')

            if self.sprite_sheet_path and os.path.exists(self.sprite_sheet_path):
                self.sprite_sheet = pygame.image.load(self.sprite_sheet_path)
                print(f"Loaded sprite sheet: {self.sprite_sheet_path}")

            # Load sprite definitions
            sprites = sprite_data.get('sprites', {})
            self.palette.clear()

            for k, v in sprites.items():
                if 'endpoint_x' not in v:
                    v['endpoint_x'] = 1.0
                if 'endpoint_y' not in v:
                    v['endpoint_y'] = 0.5
                self.palette[k] = SpriteRect(**v)

            print(f"Loaded palette ({len(self.palette)} sprites) from {filename}")
            return True

        except Exception as e:
            print("Failed to load palette:", e)
            return False

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

    def handle_hierarchy_click(self, pos: Tuple[int, int], hierarchy_rect: pygame.Rect):
        """Enhanced hierarchy click handling with drag and drop"""
        x, y = pos

        if self.editing_name:
            self.complete_name_edit()
            return

        # Calculate which item was clicked
        item_height = 25
        scroll_offset = self.ui_state.scroll_positions.get('hierarchy', 0)

        display_list = self.get_hierarchy_display_list()

        for i, (node_id, display_name, level, is_selected) in enumerate(display_list):
            item_y = hierarchy_rect.y + 30 + i * item_height - scroll_offset

            if item_y <= y <= item_y + item_height:
                node = self.hierarchy_nodes[node_id]

                # Check for double-click
                current_time = pygame.time.get_ticks()
                is_double_click = (
                        hasattr(self, 'last_click_time') and
                        current_time - self.last_click_time < self.double_click_timeout and
                        hasattr(self, 'last_clicked_object') and
                        self.last_clicked_object == node_id
                )

                if is_double_click:
                    self.start_name_edit(node_id, node.object_type)
                else:
                    self.select_object(node.object_type, node_id)
                    # Start hierarchy drag
                    self.dragging_from_hierarchy = True
                    self.hierarchy_drag_instance = node_id

                self.last_click_time = current_time
                self.last_clicked_object = node_id
                break

    # ========================================================================
    # LAYER MANAGEMENT
    # ========================================================================

    def set_selected_instance_layer(self, layer: InstanceLayer):
        """Set layer for selected instance"""
        selected = self.get_first_selected('instances')
        if not selected:
            return

        inst = self.instances[selected]
        if inst.layer != layer:
            old_inst = copy.deepcopy(inst)
            inst.layer = layer

            cmd = Command(
                action="modify",
                object_type="instances",
                object_id=selected,
                old_data=old_inst,
                new_data=copy.deepcopy(inst),
                description=f"Set {selected} to {layer.value.upper()} layer"
            )
            self.execute_command(cmd)
            print(f"Set {selected} to {layer.value.upper()} layer")

    def cycle_selected_instance_layer(self):
        """Cycle through layers for selected instance"""
        selected = self.get_first_selected('instances')
        if not selected:
            return

        inst = self.instances[selected]
        old_inst = copy.deepcopy(inst)

        if inst.layer == InstanceLayer.BEHIND:
            inst.layer = InstanceLayer.MIDDLE
        elif inst.layer == InstanceLayer.MIDDLE:
            inst.layer = InstanceLayer.FRONT
        else:
            inst.layer = InstanceLayer.BEHIND

        cmd = Command(
            action="modify",
            object_type="instances",
            object_id=selected,
            old_data=old_inst,
            new_data=copy.deepcopy(inst),
            description=f"Cycle {selected} to {inst.layer.value.upper()} layer"
        )
        self.execute_command(cmd)
        print(f"Cycled {selected} to {inst.layer.value.upper()} layer")

    def change_selected_instance_layer_order(self, delta: int):
        """Change layer order for selected instance"""
        selected = self.get_first_selected('instances')
        if not selected:
            return

        inst = self.instances[selected]
        old_inst = copy.deepcopy(inst)
        new_order = max(0, inst.layer_order + delta)

        if new_order != inst.layer_order:
            inst.layer_order = new_order
            cmd = Command(
                action="modify",
                object_type="instances",
                object_id=selected,
                old_data=old_inst,
                new_data=copy.deepcopy(inst),
                description=f"Change {selected} layer order to {new_order}"
            )
            self.execute_command(cmd)
            print(f"Changed {selected} layer order to {new_order}")

    # ========================================================================
    # DRAG AND DROP SYSTEM
    # ========================================================================

    def handle_palette_click(self, pos):
        """Enhanced palette click handling with drag and drop"""
        palette_rect = self.panel_configs[PanelType.PALETTE]['rect']

        # Calculate relative position within palette
        rel_x = pos[0] - palette_rect.x
        rel_y = pos[1] - palette_rect.y + self.palette_scroll

        # Account for header area
        header_height = 100
        if rel_y < header_height:
            return

        # Calculate which sprite was clicked
        adjusted_y = rel_y - header_height
        sprite_height = 70
        sprite_index = int(adjusted_y // sprite_height)

        sprite_names = list(self.palette.keys())
        if 0 <= sprite_index < len(sprite_names):
            sprite_name = sprite_names[sprite_index]

            # Start palette drag
            self.dragging_from_palette = True
            self.palette_drag_sprite = sprite_name
            print(f"Started dragging {sprite_name} from palette")

    def update_drag_and_drop(self, mouse_pos):
        """Update drag and drop state"""
        if self.dragging_from_palette:
            self.drag_preview_pos = mouse_pos
            viewport_rect = self.get_main_viewport_rect()

            if viewport_rect.collidepoint(mouse_pos):
                viewport_pos = self.screen_to_viewport(mouse_pos)

                # Check for snap targets
                self.snap_target = None
                self.snap_attachment = None

                snap_candidates = self.find_snap_candidates(viewport_pos)
                if snap_candidates:
                    closest = min(snap_candidates, key=lambda x: x[2])  # closest distance
                    if closest[2] < self.snap_distance / self.viewport.zoom:
                        self.snap_target = closest[0]
                        self.snap_attachment = closest[1]

        elif self.dragging_from_hierarchy:
            # Update hierarchy drag preview
            self.drag_preview_pos = mouse_pos

    def find_snap_candidates(self, pos):
        """Find nearby attachment points for snapping"""
        candidates = []

        for inst_id, inst in self.instances.items():
            if not inst.visible:
                continue

            # Get world transform
            time = self.current_time if self.mode == "ANIMATE" else None
            transform = self.get_instance_world_transform(inst_id, time)
            world_x, world_y, world_rot, world_sx, world_sy = transform

            # Check origin point (always at the instance's world position)
            distance = math.sqrt((pos[0] - world_x) ** 2 + (pos[1] - world_y) ** 2)
            candidates.append((inst_id, AttachmentPoint.ORIGIN, distance))

            # Check endpoint - calculate it properly
            if inst.sprite_name in self.palette:
                sprite = self.palette[inst.sprite_name]

                # Calculate endpoint position exactly like in draw_attachment_points
                sprite_width = sprite.width * world_sx
                sprite_height = sprite.height * world_sy

                # Calculate the offset from origin to endpoint
                endpoint_offset_x = (sprite.endpoint_x - sprite.origin_x) * sprite_width
                endpoint_offset_y = (sprite.endpoint_y - sprite.origin_y) * sprite_height

                # Rotate offset by instance rotation
                cos_r = math.cos(math.radians(world_rot))
                sin_r = math.sin(math.radians(world_rot))

                rotated_endpoint_x = endpoint_offset_x * cos_r - endpoint_offset_y * sin_r
                rotated_endpoint_y = endpoint_offset_x * sin_r + endpoint_offset_y * cos_r

                endpoint_world_x = world_x + rotated_endpoint_x
                endpoint_world_y = world_y + rotated_endpoint_y

                distance = math.sqrt((pos[0] - endpoint_world_x) ** 2 + (pos[1] - endpoint_world_y) ** 2)
                candidates.append((inst_id, AttachmentPoint.ENDPOINT, distance))

        return candidates

    def get_attachment_point_world_position(self, inst_id: str, attachment: AttachmentPoint) -> Tuple[float, float]:
        """Get the world position of a specific attachment point - NEW METHOD"""
        if inst_id not in self.instances:
            return (0, 0)

        inst = self.instances[inst_id]
        time = self.current_time if self.mode == "ANIMATE" else None
        transform = self.get_instance_world_transform(inst_id, time)
        world_x, world_y, world_rot, world_sx, world_sy = transform

        if attachment == AttachmentPoint.ORIGIN:
            return (world_x, world_y)
        else:  # ENDPOINT
            if inst.sprite_name not in self.palette:
                return (world_x, world_y)

            sprite = self.palette[inst.sprite_name]

            # Calculate endpoint position exactly like in draw_attachment_points
            sprite_width = sprite.width * world_sx
            sprite_height = sprite.height * world_sy

            # Calculate the offset from origin to endpoint
            endpoint_offset_x = (sprite.endpoint_x - sprite.origin_x) * sprite_width
            endpoint_offset_y = (sprite.endpoint_y - sprite.origin_y) * sprite_height

            # Rotate offset by instance rotation
            cos_r = math.cos(math.radians(world_rot))
            sin_r = math.sin(math.radians(world_rot))

            rotated_endpoint_x = endpoint_offset_x * cos_r - endpoint_offset_y * sin_r
            rotated_endpoint_y = endpoint_offset_x * sin_r + endpoint_offset_y * cos_r

            endpoint_world_x = world_x + rotated_endpoint_x
            endpoint_world_y = world_y + rotated_endpoint_y

            return (endpoint_world_x, endpoint_world_y)

    def complete_palette_drag(self, pos):
        """Complete drag from palette to viewport"""
        if not self.dragging_from_palette or not self.palette_drag_sprite:
            return

        viewport_rect = self.get_main_viewport_rect()
        if not viewport_rect.collidepoint(pos):
            return

        viewport_pos = self.screen_to_viewport(pos)

        # Create instance
        if self.snap_target and self.snap_attachment:
            # Get the exact world position of the attachment point
            attach_world_pos = self.get_attachment_point_world_position(self.snap_target, self.snap_attachment)

            # Create instance at attachment point (but this will be in world coordinates)
            inst_id = self.create_instance_from_palette(self.palette_drag_sprite, attach_world_pos)

            # Set parent relationship - this requires converting to local coordinates
            self.set_parent_at_attachment_point(inst_id, self.snap_target, self.snap_attachment)
            print(f"Created {self.palette_drag_sprite} attached to {self.snap_target} at {self.snap_attachment.value}")
        else:
            # Create at cursor position (default to origin point)
            inst_id = self.create_instance_from_palette(self.palette_drag_sprite, viewport_pos)
            print(f"Created {self.palette_drag_sprite} at cursor")

        self.select_object('instances', inst_id)

    def complete_hierarchy_drag(self, pos):
        """Complete drag from hierarchy for reparenting"""
        if not self.dragging_from_hierarchy or not self.hierarchy_drag_instance:
            return

        viewport_rect = self.get_main_viewport_rect()
        if viewport_rect.collidepoint(pos):
            viewport_pos = self.screen_to_viewport(pos)

            # Find target for reparenting
            snap_candidates = self.find_snap_candidates(viewport_pos)
            if snap_candidates:
                closest = min(snap_candidates, key=lambda x: x[2])
                if closest[2] < self.snap_distance / self.viewport.zoom:
                    target_id = closest[0]
                    attachment = closest[1]

                    if target_id != self.hierarchy_drag_instance:
                        # Check for circular dependency
                        if not self.would_create_cycle(self.hierarchy_drag_instance, target_id):
                            # Reparent and position at attachment point
                            self.reparent_to_attachment_point(self.hierarchy_drag_instance, target_id, attachment)
                            print(f"Reparented {self.hierarchy_drag_instance} to {target_id} at {attachment.value}")
                        else:
                            print("Cannot create circular parent-child relationship")
                else:
                    # No snap target - just reparent to world (unparent)
                    self.reparent_to_world(self.hierarchy_drag_instance, viewport_pos)
            else:
                # No candidates found - unparent to world
                self.reparent_to_world(self.hierarchy_drag_instance, viewport_pos)

    def reparent_to_attachment_point(self, child_id: str, new_parent_id: str, attachment: AttachmentPoint):
        """Reparent a child to a new parent at a specific attachment point"""
        if child_id not in self.instances or new_parent_id not in self.instances:
            return

        old_child = copy.deepcopy(self.instances[child_id])

        # Get where we want the child to appear (at the new parent's attachment point)
        target_world_pos = self.get_attachment_point_world_position(new_parent_id, attachment)

        # Remove from old parent
        if old_child.parent_id and old_child.parent_id in self.instances:
            try:
                self.instances[old_child.parent_id].children.remove(child_id)
            except ValueError:
                pass

        # Set new parent relationship
        child = self.instances[child_id]
        child.parent_id = new_parent_id
        child.parent_attachment = attachment

        # Add to new parent's children
        if child_id not in self.instances[new_parent_id].children:
            self.instances[new_parent_id].children.append(child_id)

        # Position the child at the attachment point
        self.position_child_at_world_point(child_id, target_world_pos)

        # Create undo command
        cmd = Command(
            action="modify",
            object_type="instances",
            object_id=child_id,
            old_data=old_child,
            new_data=copy.deepcopy(child),
            description=f"Reparent {child_id} to {new_parent_id} at {attachment.value}"
        )
        self.execute_command(cmd)

    def reparent_to_world(self, child_id: str, world_pos: Tuple[float, float]):
        """Reparent a child to world space (unparent) at a specific position"""
        if child_id not in self.instances:
            return

        old_child = copy.deepcopy(self.instances[child_id])

        # Remove from old parent
        if old_child.parent_id and old_child.parent_id in self.instances:
            try:
                self.instances[old_child.parent_id].children.remove(child_id)
            except ValueError:
                pass

        # Set to world space
        child = self.instances[child_id]
        child.parent_id = None
        child.parent_attachment = AttachmentPoint.ORIGIN
        child.x = world_pos[0]
        child.y = world_pos[1]

        # Create undo command
        cmd = Command(
            action="modify",
            object_type="instances",
            object_id=child_id,
            old_data=old_child,
            new_data=copy.deepcopy(child),
            description=f"Unparent {child_id} to world"
        )
        self.execute_command(cmd)

    def set_parent_at_attachment_point(self, child_id: str, parent_id: str, attachment: AttachmentPoint):
        """Set parent and position child at attachment point with correct local coordinates - IMPROVED"""
        if child_id not in self.instances or parent_id not in self.instances:
            return

        old_child = copy.deepcopy(self.instances[child_id])

        # Get the target world position (where we want the child to appear)
        target_world_pos = self.get_attachment_point_world_position(parent_id, attachment)

        # Remove from old parent first
        if old_child.parent_id and old_child.parent_id in self.instances:
            try:
                self.instances[old_child.parent_id].children.remove(child_id)
            except ValueError:
                pass

        # Set new parent relationship
        child = self.instances[child_id]
        child.parent_id = parent_id
        child.parent_attachment = attachment

        # Add to new parent's children
        if child_id not in self.instances[parent_id].children:
            self.instances[parent_id].children.append(child_id)

        # Position the child at the attachment point
        self.position_child_at_world_point(child_id, target_world_pos)

        # Create undo command
        cmd = Command(
            action="modify",
            object_type="instances",
            object_id=child_id,
            old_data=old_child,
            new_data=copy.deepcopy(child),
            description=f"Parent {child_id} to {parent_id} at {attachment.value}"
        )
        self.execute_command(cmd)

    def position_child_at_world_point(self, child_id: str, target_world_pos: Tuple[float, float]):
        """Position a child instance so it appears at a specific world position - IMPROVED"""
        if child_id not in self.instances:
            return

        child = self.instances[child_id]
        if not child.parent_id or child.parent_id not in self.instances:
            # No parent, just set world coordinates directly
            child.x = target_world_pos[0]
            child.y = target_world_pos[1]
            return

        # Get parent's world transform
        time = self.current_time if self.mode == "ANIMATE" else None
        parent_transform = self.get_instance_world_transform(child.parent_id, time)
        parent_x, parent_y, parent_rot, parent_sx, parent_sy = parent_transform

        # Calculate where the parent's attachment point is in world space
        parent_inst = self.instances[child.parent_id]
        if child.parent_attachment == AttachmentPoint.ENDPOINT and parent_inst.sprite_name in self.palette:
            sprite = self.palette[parent_inst.sprite_name]
            sprite_width = sprite.width * parent_sx
            sprite_height = sprite.height * parent_sy

            endpoint_offset_x = (sprite.endpoint_x - sprite.origin_x) * sprite_width
            endpoint_offset_y = (sprite.endpoint_y - sprite.origin_y) * sprite_height

            cos_r = math.cos(math.radians(parent_rot))
            sin_r = math.sin(math.radians(parent_rot))

            rotated_x = endpoint_offset_x * cos_r - endpoint_offset_y * sin_r
            rotated_y = endpoint_offset_x * sin_r + endpoint_offset_y * cos_r

            parent_attach_world_x = parent_x + rotated_x
            parent_attach_world_y = parent_y + rotated_y
        else:
            # Origin attachment
            parent_attach_world_x = parent_x
            parent_attach_world_y = parent_y

        # Calculate the offset from parent attachment point to target position
        offset_world_x = target_world_pos[0] - parent_attach_world_x
        offset_world_y = target_world_pos[1] - parent_attach_world_y

        # Convert this world offset to parent's local space
        # Apply inverse rotation
        cos_r = math.cos(math.radians(-parent_rot))
        sin_r = math.sin(math.radians(-parent_rot))

        # Rotate the offset vector by negative parent rotation
        rotated_offset_x = offset_world_x * cos_r - offset_world_y * sin_r
        rotated_offset_y = offset_world_x * sin_r + offset_world_y * cos_r

        # Scale by inverse of parent scale
        local_x = rotated_offset_x / parent_sx if parent_sx != 0 else 0
        local_y = rotated_offset_y / parent_sy if parent_sy != 0 else 0

        # Set the child's local position
        child.x = local_x
        child.y = local_y

    def would_create_cycle(self, child_id: str, potential_parent_id: str) -> bool:
        """Check if setting parent would create a cycle"""
        current = potential_parent_id
        while current:
            if current == child_id:
                return True
            current = self.instances[current].parent_id if current in self.instances else None
        return False

    # ========================================================================
    # INSTANCE MANAGEMENT
    # ========================================================================

    def create_instance_from_palette(self, sprite_name: str, world_pos: Tuple[float, float]):
        iid = f"inst_{self.next_instance_index}"
        self.next_instance_index += 1

        inst = AnimInstance(
            id=iid,
            sprite_name=sprite_name,
            x=world_pos[0],
            y=world_pos[1]
        )

        self.instances[iid] = inst
        self.animation_tracks[iid] = AnimationTrack(iid)

        cmd = Command(
            action="create",
            object_type="instances",
            object_id=iid,
            old_data=None,
            new_data=copy.deepcopy(inst),
            description=f"Create {sprite_name} instance"
        )
        self.execute_command(cmd)

        return iid

    def set_parent(self, child_id: str, parent_id: Optional[str], attachment: AttachmentPoint = AttachmentPoint.ORIGIN):
        """Set parent without changing position - UPDATED to use new method when positioning is needed"""
        if child_id not in self.instances:
            return

        old_inst = copy.deepcopy(self.instances[child_id])

        # Remove from old parent
        if old_inst.parent_id and old_inst.parent_id in self.instances:
            try:
                self.instances[old_inst.parent_id].children.remove(child_id)
            except ValueError:
                pass

        # Set new parent
        self.instances[child_id].parent_id = parent_id
        self.instances[child_id].parent_attachment = attachment

        if parent_id and parent_id in self.instances:
            if child_id not in self.instances[parent_id].children:
                self.instances[parent_id].children.append(child_id)

        cmd = Command(
            action="modify",
            object_type="instances",
            object_id=child_id,
            old_data=old_inst,
            new_data=copy.deepcopy(self.instances[child_id]),
            description=f"Parent {child_id} to {parent_id}"
        )
        self.execute_command(cmd)

    # ========================================================================
    # TRANSFORM CALCULATIONS (unchanged)
    # ========================================================================

    def get_instance_world_transform(self, inst_id: str, time: float = None) -> Tuple[
        float, float, float, float, float]:
        """Returns (x, y, rotation, scale_x, scale_y) in world space"""
        if inst_id not in self.instances:
            return (0, 0, 0, 1, 1)

        inst = self.instances[inst_id]

        # Get animated transform if in animate mode and time provided
        if self.mode == "ANIMATE" and time is not None and inst_id in self.animation_tracks:
            track = self.animation_tracks[inst_id]
            anim_transform = track.get_transform_at_time(time)
            local_transform = anim_transform
        else:
            # Use instance's setup transform
            local_transform = (inst.x, inst.y, inst.rotation, inst.scale_x, inst.scale_y)

        if inst.parent_id and inst.parent_id in self.instances:
            parent_transform = self.get_instance_world_transform(inst.parent_id, time)

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

    def combine_transforms(self, parent_t: Tuple[float, float, float, float, float],
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

        return (x, y, rotation, sx, sy)

    # ========================================================================
    # ANIMATION SYSTEM (unchanged)
    # ========================================================================

    def update(self):
        """Update animation playback"""
        if self.playing and self.mode == "ANIMATE":
            current_time = time.time()
            if self.last_update_time > 0:
                dt = current_time - self.last_update_time
                self.current_time += dt

                if self.current_time >= self.duration:
                    self.current_time = 0  # Loop

            self.last_update_time = current_time

    def toggle_playback(self):
        """Toggle animation playback"""
        self.playing = not self.playing
        if self.playing:
            self.last_update_time = time.time()
        print(f"Animation {'PLAYING' if self.playing else 'PAUSED'}")

    def add_keyframe_at_current_time(self, instance_id: str):
        """Add keyframe for instance at current time"""
        if instance_id not in self.instances or instance_id not in self.animation_tracks:
            return

        inst = self.instances[instance_id]
        track = self.animation_tracks[instance_id]

        keyframe = Keyframe(
            time=self.current_time,
            instance_id=instance_id,
            x=inst.x,
            y=inst.y,
            rotation=inst.rotation,
            scale_x=inst.scale_x,
            scale_y=inst.scale_y
        )

        track.add_keyframe(keyframe)
        print(f"Added keyframe for {instance_id} at {self.current_time:.2f}s")

    # ========================================================================
    # EVENT HANDLING
    # ========================================================================

    def handle_keydown(self, event) -> bool:
        if super().handle_keydown(event):
            return True

        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]
        shift_pressed = pygame.key.get_pressed()[pygame.K_LSHIFT]

        # Mode switching
        if event.key == pygame.K_TAB and not shift_pressed:
            self.mode = "ANIMATE" if self.mode == "SETUP" else "SETUP"
            print(f"Switched to {self.mode} mode")
            return True

        # Layer management
        elif event.key == pygame.K_4:
            self.set_selected_instance_layer(InstanceLayer.BEHIND)
            return True
        elif event.key == pygame.K_5:
            self.set_selected_instance_layer(InstanceLayer.MIDDLE)
            return True
        elif event.key == pygame.K_6:
            self.set_selected_instance_layer(InstanceLayer.FRONT)
            return True
        elif shift_pressed and event.key == pygame.K_TAB:
            self.cycle_selected_instance_layer()
            return True

        # Layer ordering
        elif event.key == pygame.K_PAGEUP or (shift_pressed and event.key == pygame.K_UP):
            self.change_selected_instance_layer_order(1)
            return True
        elif event.key == pygame.K_PAGEDOWN or (shift_pressed and event.key == pygame.K_DOWN):
            self.change_selected_instance_layer_order(-1)
            return True

        # Animation controls
        elif event.key == pygame.K_SPACE and self.mode == "ANIMATE":
            self.toggle_playback()
            return True

        elif event.key == pygame.K_LEFT and self.mode == "ANIMATE":
            self.current_time = max(0, self.current_time - 1.0 / self.fps)
            return True

        elif event.key == pygame.K_RIGHT and self.mode == "ANIMATE":
            self.current_time = min(self.duration, self.current_time + 1.0 / self.fps)
            return True

        elif event.key == pygame.K_HOME and self.mode == "ANIMATE":
            self.current_time = 0.0
            return True

        elif event.key == pygame.K_END and self.mode == "ANIMATE":
            self.current_time = self.duration
            return True

        # Keyframe operations
        elif event.key == pygame.K_k and self.mode == "ANIMATE":
            selected = self.get_first_selected('instances')
            if selected:
                self.add_keyframe_at_current_time(selected)
            return True

        # Parent/unparent operations
        elif event.key == pygame.K_p and ctrl_pressed:
            self.parent_selected_to_cursor()
            return True

        elif event.key == pygame.K_u and ctrl_pressed:
            self.unparent_selected()
            return True

        return False

    def handle_viewport_click(self, pos):
        """Handle clicks in main viewport"""
        # Check if clicking on timeline
        if pos[1] > self.screen.get_height() - self.timeline_height and self.mode == "ANIMATE":
            self.handle_timeline_click(pos)
            return

        # Check if clicking on palette
        palette_rect = self.panel_configs[PanelType.PALETTE]['rect']
        if palette_rect.collidepoint(pos):
            self.handle_palette_click(pos)
            return

        # Rest of viewport click handling
        viewport_pos = self.screen_to_viewport(pos)

        # FIRST: Check if clicking on gizmo of selected instance (BEFORE general hit detection)
        if self.mode == "SETUP":
            selected = self.get_first_selected('instances')
            if selected and selected in self.instances:
                gizmo_hit = self.check_gizmo_click(pos, selected)
                if gizmo_hit:
                    return  # Gizmo click handled, don't continue

        # SECOND: Check for instance interaction
        hit_instance = self.get_instance_at_point(viewport_pos)

        if hit_instance:
            self.select_object('instances', hit_instance)

            if self.mode == "SETUP":
                # Get the instance's current world transform
                inst = self.instances[hit_instance]
                world_transform = self.get_instance_world_transform(hit_instance)
                world_x, world_y = world_transform[0], world_transform[1]

                # Calculate drag offset using world coordinates
                self.drag_offset = (viewport_pos[0] - world_x, viewport_pos[1] - world_y)

                # IMPORTANT: Unparent the instance when starting to drag
                # This prevents the coordinate system mismatch
                if inst.parent_id:
                    print(f"Unparenting {hit_instance} from {inst.parent_id} for dragging")

                    # Store old instance state for undo
                    old_inst = copy.deepcopy(inst)

                    # Remove from parent's children list
                    if inst.parent_id in self.instances:
                        try:
                            self.instances[inst.parent_id].children.remove(hit_instance)
                        except ValueError:
                            pass

                    # Set instance to world space at its current world position
                    inst.parent_id = None
                    inst.parent_attachment = AttachmentPoint.ORIGIN
                    inst.x = world_x
                    inst.y = world_y

                    # Create undo command for the unparenting
                    cmd = Command(
                        action="modify",
                        object_type="instances",
                        object_id=hit_instance,
                        old_data=old_inst,
                        new_data=copy.deepcopy(inst),
                        description=f"Unparent {hit_instance} for dragging"
                    )
                    self.command_history.append(cmd)
                    self.redo_stack.clear()
                    if len(self.command_history) > self.max_history:
                        self.command_history.pop(0)

                # Now start dragging with corrected coordinates
                self.dragging_instance_id = hit_instance
                self.operation_in_progress = True
                self.drag_start_data = {
                    'type': 'transform',
                    'instance_id': hit_instance,
                    'old_transform': (inst.x, inst.y, inst.rotation, inst.scale_x, inst.scale_y)
                }

            elif self.mode == "ANIMATE":
                # Animate mode - update instance transform and create keyframe
                self.dragging_instance_id = hit_instance
                transform = self.get_instance_world_transform(hit_instance, self.current_time)
                self.drag_offset = (viewport_pos[0] - transform[0], viewport_pos[1] - transform[1])
                self.operation_in_progress = True

        else:
            self.clear_selection()

    def check_gizmo_click(self, screen_pos, instance_id):
        """Check if clicking on gizmo elements and handle the click"""
        transform = self.get_instance_world_transform(instance_id)
        world_x, world_y = transform[0], transform[1]
        gizmo_center = self.viewport_to_screen((world_x, world_y))

        dx = screen_pos[0] - gizmo_center[0]
        dy = screen_pos[1] - gizmo_center[1]
        distance = math.sqrt(dx * dx + dy * dy)

        # Match exactly what draw_transform_gizmo draws
        gizmo_size = max(4, int(self.gizmo_size * self.viewport.zoom))
        rotation_radius = max(15, int(self.rotation_handle_distance * self.viewport.zoom))

        inst = self.instances[instance_id]

        # Check scale handles (cyan squares) - exactly matching the draw positions
        for dx_dir, dy_dir in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
            handle_x = gizmo_center[0] + dx_dir * rotation_radius * 0.7
            handle_y = gizmo_center[1] + dy_dir * rotation_radius * 0.7

            # Check if click is within the 6x6 square (exactly as drawn)
            if (handle_x - 3 <= screen_pos[0] <= handle_x + 3 and
                    handle_y - 3 <= screen_pos[1] <= handle_y + 3):
                print("Scale handle clicked!")

                # UNPARENT LOGIC FOR SCALE
                if inst.parent_id:
                    print(f"Unparenting {instance_id} from {inst.parent_id} for scaling")
                    old_inst = copy.deepcopy(inst)

                    # Remove from parent's children list
                    if inst.parent_id in self.instances:
                        try:
                            self.instances[inst.parent_id].children.remove(instance_id)
                        except ValueError:
                            pass

                    # Set instance to world space at its current world position
                    inst.parent_id = None
                    inst.parent_attachment = AttachmentPoint.ORIGIN
                    inst.x = world_x
                    inst.y = world_y

                    # Create undo command for the unparenting
                    cmd = Command(
                        action="modify",
                        object_type="instances",
                        object_id=instance_id,
                        old_data=old_inst,
                        new_data=copy.deepcopy(inst),
                        description=f"Unparent {instance_id} for scaling"
                    )
                    self.command_history.append(cmd)
                    self.redo_stack.clear()
                    if len(self.command_history) > self.max_history:
                        self.command_history.pop(0)

                self.scaling_instance = True
                self.drag_start_scale = (inst.scale_x, inst.scale_y)
                self.operation_in_progress = True
                self.drag_start_data = {
                    'type': 'transform',
                    'instance_id': instance_id,
                    'old_transform': (inst.x, inst.y, inst.rotation, inst.scale_x, inst.scale_y)
                }
                return True

        # Check rotation ring (orange circle) - give some tolerance
        if rotation_radius - 8 <= distance <= rotation_radius + 8:
            print("Rotation ring clicked!")

            # UNPARENT LOGIC FOR ROTATION
            if inst.parent_id:
                print(f"Unparenting {instance_id} from {inst.parent_id} for rotation")
                old_inst = copy.deepcopy(inst)

                # Remove from parent's children list
                if inst.parent_id in self.instances:
                    try:
                        self.instances[inst.parent_id].children.remove(instance_id)
                    except ValueError:
                        pass

                # Set instance to world space at its current world position
                inst.parent_id = None
                inst.parent_attachment = AttachmentPoint.ORIGIN
                inst.x = world_x
                inst.y = world_y

                # Create undo command for the unparenting
                cmd = Command(
                    action="modify",
                    object_type="instances",
                    object_id=instance_id,
                    old_data=old_inst,
                    new_data=copy.deepcopy(inst),
                    description=f"Unparent {instance_id} for rotation"
                )
                self.command_history.append(cmd)
                self.redo_stack.clear()
                if len(self.command_history) > self.max_history:
                    self.command_history.pop(0)

            self.rotating_instance = True
            self.drag_start_rotation = inst.rotation
            self.operation_in_progress = True
            self.drag_start_data = {
                'type': 'transform',
                'instance_id': instance_id,
                'old_transform': (inst.x, inst.y, inst.rotation, inst.scale_x, inst.scale_y)
            }
            return True

        # Check center gizmo (yellow circle) for translation
        if distance <= gizmo_size:
            print("Center gizmo clicked!")

            # UNPARENT LOGIC FOR TRANSLATION
            if inst.parent_id:
                print(f"Unparenting {instance_id} from {inst.parent_id} for translation")
                old_inst = copy.deepcopy(inst)

                # Remove from parent's children list
                if inst.parent_id in self.instances:
                    try:
                        self.instances[inst.parent_id].children.remove(instance_id)
                    except ValueError:
                        pass

                # Set instance to world space at its current world position
                inst.parent_id = None
                inst.parent_attachment = AttachmentPoint.ORIGIN
                inst.x = world_x
                inst.y = world_y

                # Create undo command for the unparenting
                cmd = Command(
                    action="modify",
                    object_type="instances",
                    object_id=instance_id,
                    old_data=old_inst,
                    new_data=copy.deepcopy(inst),
                    description=f"Unparent {instance_id} for translation"
                )
                self.command_history.append(cmd)
                self.redo_stack.clear()
                if len(self.command_history) > self.max_history:
                    self.command_history.pop(0)

            # Now set up dragging with corrected coordinates
            viewport_pos = self.screen_to_viewport(screen_pos)
            self.dragging_instance_id = instance_id
            self.drag_offset = (viewport_pos[0] - inst.x, viewport_pos[1] - inst.y)  # Use local coords now
            self.operation_in_progress = True
            self.drag_start_data = {
                'type': 'transform',
                'instance_id': instance_id,
                'old_transform': (inst.x, inst.y, inst.rotation, inst.scale_x, inst.scale_y)
            }
            return True

        return False

    def handle_mouse_wheel(self, event):
        """Handle mouse wheel for zoom and palette scroll"""
        mouse_x, mouse_y = pygame.mouse.get_pos()

        # Check if over palette panel first
        palette_rect = self.panel_configs[PanelType.PALETTE]['rect']
        if palette_rect.collidepoint((mouse_x, mouse_y)):
            # Scroll palette
            self.palette_scroll -= event.y * 20
            self.palette_scroll = max(0, self.palette_scroll)

            # Calculate max scroll based on content
            sprite_count = len(self.palette)
            content_height = 100 + (sprite_count * 70)  # header + sprites
            max_scroll = max(0, content_height - palette_rect.height)
            self.palette_scroll = min(self.palette_scroll, max_scroll)
            return

        # Default viewport zoom behavior
        viewport_rect = self.get_main_viewport_rect()
        if viewport_rect.collidepoint((mouse_x, mouse_y)):
            zoom_factor = 1.1 if event.y > 0 else 0.9
            old_zoom = self.viewport.zoom
            self.viewport.zoom = max(0.1, min(5.0, self.viewport.zoom * zoom_factor))

            # Zoom towards mouse position
            zoom_ratio = self.viewport.zoom / old_zoom
            self.viewport.offset[0] = mouse_x - (mouse_x - self.viewport.offset[0]) * zoom_ratio
            self.viewport.offset[1] = mouse_y - (mouse_y - self.viewport.offset[1]) * zoom_ratio

    def handle_timeline_click(self, pos):
        """Handle clicks on animation timeline"""
        if self.mode != "ANIMATE":
            return

        x, y = pos
        timeline_y = self.screen.get_height() - self.timeline_height
        timeline_width = self.screen.get_width() - 100

        # Check if clicking on time scrubber
        relative_x = x - 50
        if 0 <= relative_x <= timeline_width:
            self.current_time = (relative_x / timeline_width) * self.duration
            self.current_time = max(0, min(self.duration, self.current_time))

    def handle_mouse_down(self, event):
        """Handle mouse down events"""
        super().handle_mouse_down(event)

    def handle_mouse_drag(self, pos):
        """Handle mouse dragging with drag and drop support"""
        # Update drag and drop for palette/hierarchy
        self.update_drag_and_drop(pos)

        if not self.operation_in_progress:
            return

        viewport_pos = self.screen_to_viewport(pos)

        if self.dragging_instance_id:
            inst = self.instances[self.dragging_instance_id]

            if self.mode == "SETUP":
                # Update instance position
                new_x = viewport_pos[0] - self.drag_offset[0]
                new_y = viewport_pos[1] - self.drag_offset[1]
                inst.x = new_x
                inst.y = new_y

                # ADD SNAPPING LOGIC FOR REGULAR INSTANCE DRAGGING
                # Check for snap targets during instance dragging
                self.snap_target = None
                self.snap_attachment = None

                # Calculate where the instance origin would be
                instance_pos = (new_x, new_y)
                snap_candidates = self.find_snap_candidates(instance_pos)

                if snap_candidates:
                    # Filter out invalid targets (self and descendants)
                    valid_candidates = []
                    for candidate_id, attachment, distance in snap_candidates:
                        # Skip self
                        if candidate_id == self.dragging_instance_id:
                            continue
                        # Skip if would create circular dependency
                        if self.would_create_cycle(self.dragging_instance_id, candidate_id):
                            continue
                        valid_candidates.append((candidate_id, attachment, distance))

                    if valid_candidates:
                        closest = min(valid_candidates, key=lambda x: x[2])  # closest distance
                        if closest[2] < self.snap_distance / self.viewport.zoom:
                            self.snap_target = closest[0]
                            self.snap_attachment = closest[1]
                            # Only print occasionally to avoid spam
                            if pygame.time.get_ticks() % 200 < 50:  # Print roughly every 200ms
                                print(f"Snap target: {self.snap_target} at {self.snap_attachment.value}")

            elif self.mode == "ANIMATE":
                # Update instance and create/update keyframe
                inst.x = viewport_pos[0] - self.drag_offset[0]
                inst.y = viewport_pos[1] - self.drag_offset[1]

        elif self.rotating_instance:
            selected = self.get_first_selected('instances')
            if selected:
                inst = self.instances[selected]
                transform = self.get_instance_world_transform(selected)
                center_x, center_y = transform[0], transform[1]

                angle = math.degrees(math.atan2(viewport_pos[1] - center_y, viewport_pos[0] - center_x))
                inst.rotation = angle

        elif self.scaling_instance:
            selected = self.get_first_selected('instances')
            if selected:
                inst = self.instances[selected]
                transform = self.get_instance_world_transform(selected)
                center_x, center_y = transform[0], transform[1]

                distance = math.sqrt((viewport_pos[0] - center_x) ** 2 + (viewport_pos[1] - center_y) ** 2)
                base_distance = 50
                scale_factor = max(0.1, distance / base_distance)

                inst.scale_x = scale_factor
                inst.scale_y = scale_factor

    def handle_left_click_release(self, pos):
        """Handle left click release with drag and drop completion"""
        # Complete drag and drop operations
        if self.dragging_from_palette:
            self.complete_palette_drag(pos)
            self.dragging_from_palette = False
            self.palette_drag_sprite = None
            self.snap_target = None
            self.snap_attachment = None

        elif self.dragging_from_hierarchy:
            self.complete_hierarchy_drag(pos)
            self.dragging_from_hierarchy = False
            self.hierarchy_drag_instance = None
            self.snap_target = None
            self.snap_attachment = None

        # NEW: Handle snapping for regular instance dragging
        elif self.dragging_instance_id and self.snap_target and self.snap_attachment:
            print(f"Completing snap: {self.dragging_instance_id} to {self.snap_target} at {self.snap_attachment.value}")
            self.complete_instance_snap(self.dragging_instance_id, self.snap_target, self.snap_attachment)

        # Handle regular operations
        if self.operation_in_progress:
            self.create_operation_command()

        self.dragging_instance_id = None
        self.rotating_instance = False
        self.scaling_instance = False
        self.operation_in_progress = False
        self.drag_start_data = None
        self.drag_preview_pos = None

        # Clear snap state
        self.snap_target = None
        self.snap_attachment = None

    def complete_instance_snap(self, instance_id: str, target_id: str, attachment: AttachmentPoint):
        """Complete snapping an instance to a target's attachment point"""
        if instance_id not in self.instances or target_id not in self.instances:
            return

        # CHECK FOR CIRCULAR DEPENDENCY FIRST
        if self.would_create_cycle(instance_id, target_id):
            print(f"Cannot attach {instance_id} to {target_id} - would create circular dependency!")
            return

        # Store the old state for undo
        old_inst = copy.deepcopy(self.instances[instance_id])

        # Get the target attachment point world position
        target_world_pos = self.get_attachment_point_world_position(target_id, attachment)

        # Remove from current parent if any
        inst = self.instances[instance_id]
        if inst.parent_id and inst.parent_id in self.instances:
            try:
                self.instances[inst.parent_id].children.remove(instance_id)
            except ValueError:
                pass

        # Set up the new parent relationship
        inst.parent_id = target_id
        inst.parent_attachment = attachment

        # Add to target's children
        if instance_id not in self.instances[target_id].children:
            self.instances[target_id].children.append(instance_id)

        # Position the instance at the attachment point
        self.position_child_at_world_point(instance_id, target_world_pos)

        # Create undo command for the attachment
        cmd = Command(
            action="modify",
            object_type="instances",
            object_id=instance_id,
            old_data=old_inst,
            new_data=copy.deepcopy(inst),
            description=f"Attach {instance_id} to {target_id} at {attachment.value}"
        )
        self.command_history.append(cmd)
        self.redo_stack.clear()
        if len(self.command_history) > self.max_history:
            self.command_history.pop(0)

        print(f"Attached {instance_id} to {target_id} at {attachment.value}")

    def get_instance_at_point(self, pos) -> Optional[str]:
        """Find instance at given world position"""
        for iid in reversed(list(self.instances.keys())):
            if not self.instances[iid].visible:
                continue

            time = self.current_time if self.mode == "ANIMATE" else None
            transform = self.get_instance_world_transform(iid, time)
            world_x, world_y = transform[0], transform[1]

            # Simple distance check to center
            distance = math.sqrt((pos[0] - world_x) ** 2 + (pos[1] - world_y) ** 2)
            hit_radius = 15 / self.viewport.zoom

            if distance <= hit_radius:
                return iid

        return None

    def parent_selected_to_cursor(self):
        """Parent selected instance to instance under cursor"""
        selected = self.get_first_selected('instances')
        if not selected:
            return

        mouse_pos = pygame.mouse.get_pos()
        viewport_pos = self.screen_to_viewport(mouse_pos)
        target = self.get_instance_at_point(viewport_pos)

        if target and target != selected:
            self.set_parent(selected, target, AttachmentPoint.ORIGIN)
            print(f"Parented {selected} to {target}")

    def unparent_selected(self):
        """Remove parent from selected instance"""
        selected = self.get_first_selected('instances')
        if selected and self.instances[selected].parent_id:
            self.set_parent(selected, None)
            print(f"Unparented {selected}")

    def create_operation_command(self):
        """Create undo command for completed operation"""
        if not self.drag_start_data or self.drag_start_data['type'] != 'transform':
            return

        instance_id = self.drag_start_data['instance_id']
        old_transform = self.drag_start_data['old_transform']
        current_inst = self.instances[instance_id]

        # Only create command if something actually changed
        current_transform = (current_inst.x, current_inst.y, current_inst.rotation, current_inst.scale_x,
                             current_inst.scale_y)

        if old_transform != current_transform:
            # Create a copy of the instance with old transform
            old_inst = copy.deepcopy(current_inst)
            old_inst.x, old_inst.y, old_inst.rotation, old_inst.scale_x, old_inst.scale_y = old_transform

            cmd = Command(
                action="modify",
                object_type="instances",
                object_id=instance_id,
                old_data=old_inst,
                new_data=copy.deepcopy(current_inst),
                description=f"Transform {instance_id}"
            )

            self.command_history.append(cmd)
            self.redo_stack.clear()
            if len(self.command_history) > self.max_history:
                self.command_history.pop(0)

    # ========================================================================
    # DRAWING SYSTEM
    # ========================================================================

    def draw(self):
        """Main drawing pipeline with animation update"""
        self.update()
        super().draw()

    def draw_objects(self):
        """Draw all instances with proper layering and connections"""
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

        # Draw connection lines first (behind everything)
        self.draw_connections()

        # Draw in layer order: BEHIND -> MIDDLE -> FRONT
        for layer in [InstanceLayer.BEHIND, InstanceLayer.MIDDLE, InstanceLayer.FRONT]:
            for layer_order, iid, inst in layered_instances[layer]:
                self.draw_instance(iid)

        # Draw transform gizmos for selected instance on top
        selected = self.get_first_selected('instances')
        if selected and self.mode == "SETUP":
            self.draw_transform_gizmo(selected)

        # Draw drag and drop overlays
        self.draw_drag_drop_overlays()

    def draw_drag_drop_overlays(self):
        """Draw drag and drop visual feedback"""
        # Draw drag preview
        if self.dragging_from_palette and self.drag_preview_pos and self.palette_drag_sprite:
            # Draw sprite preview following cursor
            preview_surface = self.small_font.render(f"Creating: {self.palette_drag_sprite}", True, (255, 255, 255))
            bg_rect = preview_surface.get_rect()
            bg_rect.topleft = (self.drag_preview_pos[0] + 10, self.drag_preview_pos[1] - 20)
            bg_rect = bg_rect.inflate(10, 5)

            pygame.draw.rect(self.screen, (0, 0, 0, 180), bg_rect)
            pygame.draw.rect(self.screen, (255, 255, 255), bg_rect, 1)
            self.screen.blit(preview_surface, (bg_rect.x + 5, bg_rect.y + 2))

        elif self.dragging_from_hierarchy and self.drag_preview_pos and self.hierarchy_drag_instance:
            # Draw reparent preview
            preview_text = f"Reparenting: {self.hierarchy_drag_instance}"
            preview_surface = self.small_font.render(preview_text, True, (255, 255, 0))
            bg_rect = preview_surface.get_rect()
            bg_rect.topleft = (self.drag_preview_pos[0] + 10, self.drag_preview_pos[1] - 20)
            bg_rect = bg_rect.inflate(10, 5)

            pygame.draw.rect(self.screen, (0, 0, 0, 180), bg_rect)
            pygame.draw.rect(self.screen, (255, 255, 0), bg_rect, 1)
            self.screen.blit(preview_surface, (bg_rect.x + 5, bg_rect.y + 2))

        # NEW: Draw instance dragging preview
        elif self.dragging_instance_id:
            mouse_pos = pygame.mouse.get_pos()
            preview_text = f"Dragging: {self.dragging_instance_id}"
            preview_surface = self.small_font.render(preview_text, True, (0, 255, 255))
            bg_rect = preview_surface.get_rect()
            bg_rect.topleft = (mouse_pos[0] + 10, mouse_pos[1] - 20)
            bg_rect = bg_rect.inflate(10, 5)

            pygame.draw.rect(self.screen, (0, 0, 0, 180), bg_rect)
            pygame.draw.rect(self.screen, (0, 255, 255), bg_rect, 1)
            self.screen.blit(preview_surface, (bg_rect.x + 5, bg_rect.y + 2))

        # Draw snap targets (works for all drag types now)
        if self.snap_target and self.snap_attachment:
            # Get the exact attachment point position
            snap_pos = self.get_attachment_point_world_position(self.snap_target, self.snap_attachment)

            # Check if this would be a valid attachment
            is_valid = True
            if self.dragging_instance_id:
                is_valid = not self.would_create_cycle(self.dragging_instance_id, self.snap_target)

            # Color based on validity and attachment type
            if not is_valid:
                snap_color = (255, 128, 0)  # Orange for invalid
            elif self.snap_attachment == AttachmentPoint.ORIGIN:
                snap_color = (255, 0, 0)  # Red for origin
            else:  # ENDPOINT
                snap_color = (0, 0, 255)  # Blue for endpoint

            # Draw snap indicator at the exact attachment point
            snap_screen = self.viewport_to_screen(snap_pos)
            snap_radius = max(12, int(self.snap_visual_radius * self.viewport.zoom))

            # Pulsing effect
            pulse = (math.sin(pygame.time.get_ticks() * 0.01) + 1) * 0.5
            alpha = int(180 + 75 * pulse)

            # Create surface with alpha
            snap_surf = pygame.Surface((snap_radius * 4, snap_radius * 4), pygame.SRCALPHA)
            pygame.draw.circle(snap_surf, (*snap_color, alpha), (snap_radius * 2, snap_radius * 2), snap_radius)

            # Different border for invalid targets
            border_color = (255, 255, 255, 255) if is_valid else (255, 0, 0, 255)
            border_width = 3 if is_valid else 5
            pygame.draw.circle(snap_surf, border_color, (snap_radius * 2, snap_radius * 2), snap_radius, border_width)

            self.screen.blit(snap_surf, (snap_screen[0] - snap_radius * 2, snap_screen[1] - snap_radius * 2))

            # Draw attachment type label
            if is_valid:
                attachment_text = "ORIGIN" if self.snap_attachment == AttachmentPoint.ORIGIN else "ENDPOINT"
            else:
                attachment_text = "INVALID (CYCLE)"

            label_surface = self.small_font.render(attachment_text, True, snap_color)
            label_rect = label_surface.get_rect()
            label_rect.center = (snap_screen[0], snap_screen[1] - snap_radius - 15)

            # Draw label background
            label_bg = label_rect.inflate(6, 4)
            pygame.draw.rect(self.screen, (0, 0, 0, 200), label_bg)
            pygame.draw.rect(self.screen, snap_color, label_bg, 1)
            self.screen.blit(label_surface, label_rect)

    def draw_instance(self, instance_id: str):
        """Draw a single instance"""
        inst = self.instances[instance_id]
        sprite = self.palette.get(inst.sprite_name)

        if not sprite:
            return

        # Get current transform (animated if in animate mode)
        time = self.current_time if self.mode == "ANIMATE" else None
        world_transform = self.get_instance_world_transform(instance_id, time)
        world_x, world_y, world_rot, world_sx, world_sy = world_transform

        # The world position represents the origin point, not the center
        origin_screen = self.viewport_to_screen((world_x, world_y))

        # Apply layer-based alpha
        layer_alpha = self.get_layer_alpha(inst.layer)

        # Draw sprite if sprite sheet is loaded
        if self.sprite_sheet:
            try:
                # Extract sprite from sheet
                sprite_surface = self.sprite_sheet.subsurface((sprite.x, sprite.y, sprite.width, sprite.height))

                # Calculate size
                final_width = max(1, int(sprite.width * world_sx * self.viewport.zoom))
                final_height = max(1, int(sprite.height * world_sy * self.viewport.zoom))

                # Scale sprite
                scaled_sprite = pygame.transform.scale(sprite_surface, (final_width, final_height))

                # Apply layer alpha
                if layer_alpha < 255:
                    scaled_sprite = scaled_sprite.copy()
                    scaled_sprite.set_alpha(layer_alpha)

                # Calculate where the top-left corner should be based on origin position
                origin_offset_x = sprite.origin_x * final_width
                origin_offset_y = sprite.origin_y * final_height

                # Handle rotation
                if abs(world_rot) > 0.01:
                    # For rotation, we need to rotate around the origin point
                    max_dim = max(final_width, final_height) * 2
                    rotation_surface = pygame.Surface((max_dim, max_dim), pygame.SRCALPHA)

                    # Place sprite so its origin is at the center of rotation surface
                    sprite_pos_in_rotation = (
                        max_dim // 2 - origin_offset_x,
                        max_dim // 2 - origin_offset_y
                    )
                    rotation_surface.blit(scaled_sprite, sprite_pos_in_rotation)

                    # Rotate the surface
                    rotated_surface = pygame.transform.rotate(rotation_surface, -world_rot)
                    rotated_rect = rotated_surface.get_rect()

                    # Position so the center of the rotated surface is at the origin screen position
                    final_pos = (
                        origin_screen[0] - rotated_rect.width // 2,
                        origin_screen[1] - rotated_rect.height // 2
                    )

                    self.screen.blit(rotated_surface, final_pos)

                else:
                    # No rotation - simple positioning
                    sprite_pos = (
                        origin_screen[0] - origin_offset_x,
                        origin_screen[1] - origin_offset_y
                    )
                    self.screen.blit(scaled_sprite, sprite_pos)

            except pygame.error:
                # Fallback to rectangle if sprite extraction fails
                self.draw_instance_placeholder(instance_id, origin_screen, sprite, world_sx, world_sy, layer_alpha)
        else:
            # Draw placeholder rectangle
            self.draw_instance_placeholder(instance_id, origin_screen, sprite, world_sx, world_sy, layer_alpha)

        # Draw attachment points
        self.draw_attachment_points(instance_id, sprite, world_transform)

        # Draw selection highlight - USE EXACT SAME PATTERN AS OTHER TRANSPARENT CIRCLES
        if self.is_object_selected('instances', instance_id):
            radius = max(3, int(6 * self.viewport.zoom))
            temp_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp_surf, (255, 255, 0, 80), (radius, radius), radius)
            self.screen.blit(temp_surf, (int(origin_screen[0] - radius), int(origin_screen[1] - radius)))

        # Draw instance label with layer info
        if self.viewport.zoom > 0.5:
            layer_char = inst.layer.value[0].upper()
            label = self.small_font.render(f"{inst.sprite_name}[{instance_id}][{layer_char}{inst.layer_order}]", True,
                                           (255, 255, 255))
            self.screen.blit(label, (origin_screen[0] + 10, origin_screen[1] - 20))

    def get_gizmo_handle_at_screen_position(self, screen_pos, instance_id):
        """Check which gizmo handle is at the given screen position"""
        if instance_id not in self.instances:
            return None

        transform = self.get_instance_world_transform(instance_id)
        world_x, world_y = transform[0], transform[1]
        gizmo_screen_pos = self.viewport_to_screen((world_x, world_y))

        dx = screen_pos[0] - gizmo_screen_pos[0]
        dy = screen_pos[1] - gizmo_screen_pos[1]
        distance_to_center = math.sqrt(dx * dx + dy * dy)

        # Gizmo sizes in screen space (matching draw_transform_gizmo exactly)
        gizmo_size = max(4, int(self.gizmo_size * self.viewport.zoom))
        rotation_radius = max(15, int(self.rotation_handle_distance * self.viewport.zoom))

        # Check scale handles first (cyan squares at corners)
        for dx_dir, dy_dir in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
            handle_x = gizmo_screen_pos[0] + dx_dir * rotation_radius * 0.7
            handle_y = gizmo_screen_pos[1] + dy_dir * rotation_radius * 0.7

            # Check if click is within the 6x6 square (matching draw code)
            if (handle_x - 3 <= screen_pos[0] <= handle_x + 3 and
                    handle_y - 3 <= screen_pos[1] <= handle_y + 3):
                return "scale"

        # Check rotation ring (orange circle) - allow some tolerance
        rotation_tolerance = 5
        if rotation_radius - rotation_tolerance <= distance_to_center <= rotation_radius + rotation_tolerance:
            return "rotation"

        # Check center gizmo for translation
        if distance_to_center <= gizmo_size:
            return "translate"

        return None

    def get_layer_alpha(self, layer: InstanceLayer) -> int:
        """Get alpha value based on layer"""
        if layer == InstanceLayer.BEHIND:
            return 160  # More transparent
        elif layer == InstanceLayer.FRONT:
            return 255  # Fully opaque
        else:  # MIDDLE
            return 200  # Slightly transparent

    def draw_instance_placeholder(self, instance_id: str, origin_screen: Tuple[int, int], sprite: SpriteRect,
                                  sx: float, sy: float, alpha: int = 255):
        """Draw placeholder rectangle for instance"""
        w = max(8, sprite.width * sx * self.viewport.zoom * 0.3)
        h = max(8, sprite.height * sy * self.viewport.zoom * 0.3)

        # Position rectangle so origin point is at the correct location
        origin_offset_x = sprite.origin_x * w
        origin_offset_y = sprite.origin_y * h

        rect = pygame.Rect(
            origin_screen[0] - origin_offset_x,
            origin_screen[1] - origin_offset_y,
            w, h
        )

        # Color based on selection and layer
        inst = self.instances[instance_id]
        if self.is_object_selected('instances', instance_id):
            color = (255, 255, 100)
        else:
            # Layer-based colors
            if inst.layer == InstanceLayer.BEHIND:
                color = (100, 100, 255)  # Blue
            elif inst.layer == InstanceLayer.FRONT:
                color = (255, 100, 100)  # Red
            else:  # MIDDLE
                color = (100, 255, 100)  # Green

        # Apply alpha
        if alpha < 255:
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(surf, (*color, alpha), surf.get_rect())
            pygame.draw.rect(surf, (255, 255, 255), surf.get_rect(), 1)
            self.screen.blit(surf, rect.topleft)
        else:
            pygame.draw.rect(self.screen, color, rect)
            pygame.draw.rect(self.screen, (255, 255, 255), rect, 1)

    def draw_attachment_points(self, instance_id: str, sprite: SpriteRect,
                               world_transform: Tuple[float, float, float, float, float]):
        """Draw origin and endpoint dots"""
        world_x, world_y, world_rot, world_sx, world_sy = world_transform

        # The world position represents where the ORIGIN should be
        origin_world_x = world_x
        origin_world_y = world_y
        origin_screen = self.viewport_to_screen((origin_world_x, origin_world_y))

        # Calculate endpoint position relative to origin
        sprite_width = sprite.width * world_sx
        sprite_height = sprite.height * world_sy

        # Calculate the offset from origin to endpoint
        endpoint_offset_x = (sprite.endpoint_x - sprite.origin_x) * sprite_width
        endpoint_offset_y = (sprite.endpoint_y - sprite.origin_y) * sprite_height

        # Rotate offset by instance rotation
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

                time = self.current_time if self.mode == "ANIMATE" else None

                # Get parent transform
                parent_transform = self.get_instance_world_transform(inst.parent_id, time)
                parent_x, parent_y = parent_transform[0], parent_transform[1]

                # Get child transform
                child_transform = self.get_instance_world_transform(iid, time)
                child_x, child_y = child_transform[0], child_transform[1]

                # Get attachment point
                if inst.parent_attachment == AttachmentPoint.ENDPOINT:
                    # Connect to parent's endpoint
                    parent_sprite = self.palette.get(parent_inst.sprite_name)
                    if parent_sprite:
                        # Calculate endpoint position
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
                    # Connect to parent's origin
                    attach_x, attach_y = parent_x, parent_y
                    connection_color = (255, 165, 0)  # Orange for origin attachment

                # Draw connection line
                parent_screen = self.viewport_to_screen((attach_x, attach_y))
                child_screen = self.viewport_to_screen((child_x, child_y))

                pygame.draw.line(self.screen, connection_color, parent_screen, child_screen, self.connector_thickness)

    def draw_transform_gizmo(self, instance_id: str):
        """Draw transform gizmo for selected instance"""
        transform = self.get_instance_world_transform(instance_id)
        world_x, world_y = transform[0], transform[1]
        screen_pos = self.viewport_to_screen((world_x, world_y))

        # Translation gizmo (center)
        gizmo_size = max(2, int(self.gizmo_size * self.viewport.zoom))
        temp_surf = pygame.Surface((gizmo_size * 2, gizmo_size * 2), pygame.SRCALPHA)
        pygame.draw.circle(temp_surf, (255, 255, 0, 100), (gizmo_size, gizmo_size), gizmo_size)
        pygame.draw.circle(temp_surf, (0, 0, 0, 255), (gizmo_size, gizmo_size), gizmo_size, 2)
        self.screen.blit(temp_surf, (int(screen_pos[0] - gizmo_size), int(screen_pos[1] - gizmo_size)))

        # Rotation gizmo (outer circle)
        rotation_radius = max(15, int(self.rotation_handle_distance * self.viewport.zoom))
        pygame.draw.circle(self.screen, (255, 165, 0), (int(screen_pos[0]), int(screen_pos[1])), rotation_radius, 2)

        # Scale gizmo (corner handles)
        for dx, dy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
            handle_x = screen_pos[0] + dx * rotation_radius * 0.7
            handle_y = screen_pos[1] + dy * rotation_radius * 0.7
            pygame.draw.rect(self.screen, (0, 255, 255),
                             (int(handle_x - 3), int(handle_y - 3), 6, 6))

    def draw_main_viewport(self):
        """Override to account for timeline in animate mode"""
        if self.mode == "ANIMATE":
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
        else:
            super().draw_main_viewport()

    def draw_timeline(self):
        """Draw animation timeline"""
        if self.mode != "ANIMATE":
            return

        timeline_y = self.screen.get_height() - self.timeline_height
        timeline_rect = pygame.Rect(0, timeline_y, self.screen.get_width(), self.timeline_height)

        # Background
        pygame.draw.rect(self.screen, (64, 64, 64), timeline_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), timeline_rect, 2)

        # Title
        title = self.font.render("Timeline", True, (255, 255, 255))
        self.screen.blit(title, (10, timeline_y + 10))

        # Playback controls
        controls_y = timeline_y + 40
        controls = ["|<<", "<<", ">||" if not self.playing else "||", ">>", ">>|"]
        for i, control in enumerate(controls):
            control_text = self.font.render(control, True, (255, 255, 255))
            self.screen.blit(control_text, (10 + i * 30, controls_y))

        # Time ruler
        ruler_y = timeline_y + 80
        ruler_width = self.screen.get_width() - 100

        # Draw time markers
        for i in range(int(self.duration) + 1):
            x = 50 + (i / self.duration) * ruler_width
            pygame.draw.line(self.screen, (255, 255, 255), (x, ruler_y), (x, ruler_y + 20))

            time_text = self.small_font.render(f"{i}s", True, (255, 255, 255))
            self.screen.blit(time_text, (x - 10, ruler_y + 25))

        # Current time indicator
        current_x = 50 + (self.current_time / self.duration) * ruler_width
        pygame.draw.line(self.screen, (255, 255, 0), (current_x, ruler_y), (current_x, ruler_y + 40), 3)

        # Instance tracks
        track_y = ruler_y + 50
        for i, (iid, track) in enumerate(self.animation_tracks.items()):
            inst = self.instances[iid]

            # Track name with layer info
            layer_char = inst.layer.value[0].upper()
            track_text = self.small_font.render(f"{inst.sprite_name}[{iid}][{layer_char}{inst.layer_order}]", True,
                                                (255, 255, 255))
            self.screen.blit(track_text, (10, track_y + i * 25))

            # Keyframes
            for keyframe in track.keyframes:
                kf_x = 50 + (keyframe.time / self.duration) * ruler_width

                # Color based on interpolation
                if keyframe.interpolation == InterpolationType.LINEAR:
                    kf_color = (255, 255, 255)
                elif keyframe.interpolation == InterpolationType.EASE_IN:
                    kf_color = (255, 0, 0)
                elif keyframe.interpolation == InterpolationType.EASE_OUT:
                    kf_color = (0, 0, 255)
                else:
                    kf_color = (255, 0, 255)

                pygame.draw.circle(self.screen, kf_color, (int(kf_x), int(track_y + i * 25)), 4)
                pygame.draw.circle(self.screen, (0, 0, 0), (int(kf_x), int(track_y + i * 25)), 4, 1)

    def draw_panels(self):
        """Draw all panels including palette"""
        super().draw_panels()

        # Draw palette panel
        if self.panel_configs[PanelType.PALETTE]['visible']:
            palette_rect = self.panel_configs[PanelType.PALETTE]['rect']
            self.draw_palette_panel(palette_rect)

    def draw_palette_panel(self, panel_rect):
        """Draw sprite palette panel with drag feedback"""
        # Background
        pygame.draw.rect(self.screen, (200, 200, 220), panel_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), panel_rect, 2)

        # Set clipping to panel area for scrolling
        self.screen.set_clip(panel_rect)

        # Calculate scroll offset
        scroll_y = -self.palette_scroll

        # Title (fixed position, not scrolled)
        title = self.font.render("Sprite Palette", True, (0, 0, 0))
        self.screen.blit(title, (panel_rect.x + 10, panel_rect.y + 10))

        # Instructions (fixed position, not scrolled)
        instructions = [
            "DRAG sprites to create instances",
            f"Mode: {self.mode}",
            "Tab: Switch modes"
        ]

        y_offset = panel_rect.y + 40
        for instruction in instructions:
            text = self.small_font.render(instruction, True, (64, 64, 64))
            self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 16

        # Scrollable content starts here
        content_y = panel_rect.y + 100 + scroll_y

        # Draw sprites (scrollable)
        for i, (sprite_name, sprite) in enumerate(self.palette.items()):
            sprite_y = content_y + (i * 70)

            # Only draw if visible in panel
            if sprite_y + 70 < panel_rect.y or sprite_y > panel_rect.bottom:
                continue

            # Highlight if being dragged
            is_dragging = self.dragging_from_palette and self.palette_drag_sprite == sprite_name
            if is_dragging:
                highlight_rect = pygame.Rect(panel_rect.x, sprite_y, panel_rect.width, 70)
                pygame.draw.rect(self.screen, (255, 255, 0, 64), highlight_rect)

            # Sprite thumbnail
            if self.sprite_sheet:
                try:
                    sprite_surface = self.sprite_sheet.subsurface((sprite.x, sprite.y, sprite.width, sprite.height))

                    # Scale to fit in palette
                    max_size = 40
                    scale = min(max_size / sprite.width, max_size / sprite.height)
                    thumb_width = int(sprite.width * scale)
                    thumb_height = int(sprite.height * scale)

                    if thumb_width > 0 and thumb_height > 0:
                        thumbnail = pygame.transform.scale(sprite_surface, (thumb_width, thumb_height))
                        thumb_rect = pygame.Rect(panel_rect.x + 10, sprite_y + 5, thumb_width, thumb_height)

                        # Dim if being dragged
                        if is_dragging:
                            thumbnail = thumbnail.copy()
                            thumbnail.set_alpha(128)

                        self.screen.blit(thumbnail, thumb_rect)
                        pygame.draw.rect(self.screen, (255, 255, 255), thumb_rect, 1)

                        # Draw origin and endpoint on thumbnail
                        origin_x = thumb_rect.x + sprite.origin_x * thumb_width
                        origin_y = thumb_rect.y + sprite.origin_y * thumb_height
                        endpoint_x = thumb_rect.x + sprite.endpoint_x * thumb_width
                        endpoint_y = thumb_rect.y + sprite.endpoint_y * thumb_height

                        pygame.draw.circle(self.screen, (255, 0, 0), (int(origin_x), int(origin_y)), 2)
                        pygame.draw.circle(self.screen, (0, 0, 255), (int(endpoint_x), int(endpoint_y)), 2)
                        pygame.draw.line(self.screen, (255, 165, 0),
                                         (int(origin_x), int(origin_y)), (int(endpoint_x), int(endpoint_y)), 1)

                except pygame.error:
                    # Fallback rectangle
                    thumb_rect = pygame.Rect(panel_rect.x + 10, sprite_y + 5, 40, 30)
                    thumb_color = (150, 150, 200) if is_dragging else (200, 200, 255)
                    pygame.draw.rect(self.screen, thumb_color, thumb_rect)
                    pygame.draw.rect(self.screen, (255, 255, 255), thumb_rect, 1)
            else:
                # No sprite sheet - draw placeholder
                thumb_rect = pygame.Rect(panel_rect.x + 10, sprite_y + 5, 40, 30)
                thumb_color = (150, 150, 200) if is_dragging else (200, 200, 255)
                pygame.draw.rect(self.screen, thumb_color, thumb_rect)
                pygame.draw.rect(self.screen, (255, 255, 255), thumb_rect, 1)

            # Sprite name
            name_color = (128, 128, 128) if is_dragging else (0, 0, 0)
            name_text = self.small_font.render(sprite_name, True, name_color)
            self.screen.blit(name_text, (panel_rect.x + 60, sprite_y + 10))

            # Sprite info
            info_text = self.small_font.render(f"{sprite.width}x{sprite.height}", True, (128, 128, 128))
            self.screen.blit(info_text, (panel_rect.x + 60, sprite_y + 30))

            # Attachment point info
            attach_text = self.small_font.render(
                f"O:({sprite.origin_x:.1f},{sprite.origin_y:.1f}) E:({sprite.endpoint_x:.1f},{sprite.endpoint_y:.1f})",
                True, (100, 100, 100))
            self.screen.blit(attach_text, (panel_rect.x + 60, sprite_y + 45))

        # Remove clipping
        self.screen.set_clip(None)

        # Draw scroll indicator if needed
        sprite_count = len(self.palette)
        content_height = 100 + (sprite_count * 70)
        if content_height > panel_rect.height:
            # Draw scrollbar
            scrollbar_height = max(20, int((panel_rect.height / content_height) * panel_rect.height))
            scrollbar_y = panel_rect.y + int((self.palette_scroll / content_height) * panel_rect.height)

            scrollbar_rect = pygame.Rect(panel_rect.right - 10, scrollbar_y, 8, scrollbar_height)
            pygame.draw.rect(self.screen, (100, 100, 100), scrollbar_rect)
            pygame.draw.rect(self.screen, (255, 255, 255), scrollbar_rect, 1)

    def draw_properties_content(self, panel_rect, y_offset):
        """Draw properties panel content"""
        # Mode indicator
        mode_text = self.font.render(f"Mode: {self.mode}", True, (255, 0, 0) if self.mode == "SETUP" else (0, 0, 255))
        self.screen.blit(mode_text, (panel_rect.x + 10, y_offset))
        y_offset += 30

        # Animation info
        if self.mode == "ANIMATE":
            anim_info = [
                f"Time: {self.current_time:.2f}s / {self.duration:.1f}s",
                f"FPS: {self.fps}",
                f"Playing: {'Yes' if self.playing else 'No'}"
            ]

            for info in anim_info:
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

            # Transform info
            info_lines = [
                f"Position: ({inst.x:.1f}, {inst.y:.1f})",
                f"Rotation: {inst.rotation:.1f}°",
                f"Scale: ({inst.scale_x:.2f}, {inst.scale_y:.2f})",
                f"Layer: {inst.layer.value.upper()} (Order: {inst.layer_order})",
                f"Parent: {inst.parent_id or 'None'}",
                f"Children: {len(inst.children)}",
                f"Attachment: {inst.parent_attachment.value if inst.parent_id else 'N/A'}"
            ]

            for line in info_lines:
                text = self.small_font.render(line, True, (0, 0, 0))
                self.screen.blit(text, (panel_rect.x + 20, y_offset))
                y_offset += 18

            # Animation track info
            if selected in self.animation_tracks:
                track = self.animation_tracks[selected]
                track_text = self.small_font.render(f"Keyframes: {len(track.keyframes)}", True, (0, 0, 0))
                self.screen.blit(track_text, (panel_rect.x + 20, y_offset))
                y_offset += 18

        y_offset += 20

        # Project stats
        stats = [
            f"Instances: {len(self.instances)}",
            f"Palette Sprites: {len(self.palette)}",
            f"Sprite Sheet: {os.path.basename(self.sprite_sheet_path) if self.sprite_sheet_path else 'None'}"
        ]

        # Layer distribution
        behind_count = sum(1 for inst in self.instances.values() if inst.layer == InstanceLayer.BEHIND)
        middle_count = sum(1 for inst in self.instances.values() if inst.layer == InstanceLayer.MIDDLE)
        front_count = sum(1 for inst in self.instances.values() if inst.layer == InstanceLayer.FRONT)

        stats.append(f"Layers - Behind: {behind_count} | Middle: {middle_count} | Front: {front_count}")

        for stat in stats:
            text = self.small_font.render(stat, True, (64, 64, 64))
            self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 18

        # Controls help
        y_offset += 20
        controls = [
            "DRAG & DROP:",
            "• Drag from palette: Create instances",
            "• Drag from hierarchy: Reparent",
            "• Snap to red/blue attachment points",
            "",
            "LAYERS:",
            "4=Behind | 5=Middle | 6=Front",
            "Shift+Tab=Cycle | PgUp/Dn=Order",
            "",
            "CONTROLS:",
            "Tab: Switch SETUP/ANIMATE",
            "",
            "SETUP MODE:",
            "• Drag center: Move",
            "• Drag outside: Rotate",
            "• Drag corners: Scale",
            "• Ctrl+P: Parent to cursor",
            "• Ctrl+U: Unparent",
            "",
            "ANIMATE MODE:",
            "• Space: Play/Pause",
            "• Left/Right: Step frames",
            "• Home/End: Go to start/end",
            "• K: Add keyframe",
            "• Drag instances: Animate",
            "",
            "UNIVERSAL:",
            "• Delete: Remove selected",
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
                            'interpolation': kf.interpolation.value
                        }
                        for kf in track.keyframes
                    ]
                }

        return {
            'palette_file': self.palette_file,
            'sprite_sheet_path': self.sprite_sheet_path,
            'instances': instances_data,
            'animation_tracks': tracks_data,
            'duration': self.duration,
            'fps': self.fps,
            'current_time': self.current_time
        }

    def deserialize_data_objects(self, data):
        """Deserialize from loading"""
        # Load palette
        self.palette_file = data.get('palette_file', self.palette_file)
        self.sprite_sheet_path = data.get('sprite_sheet_path', '')

        self.load_palette_from_sheet_project(self.palette_file)

        # Load animation settings
        self.duration = data.get('duration', 5.0)
        self.fps = data.get('fps', 30)
        self.current_time = data.get('current_time', 0.0)

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
                        interpolation=interpolation
                    )
                    track.add_keyframe(keyframe)

        # Update next instance index
        if self.instances:
            max_index = max(int(iid.split('_')[1]) for iid in self.instances.keys() if iid.startswith('inst_'))
            self.next_instance_index = max_index + 1

        return {
            'instances': data.get('instances', {}),
            'animation_tracks': data.get('animation_tracks', {}),
            'palette_ref': self.palette_file
        }

    def delete_selected(self):
        """Delete selected instance"""
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

        cmd = Command(
            action="delete",
            object_type="instances",
            object_id=selected,
            old_data=old_inst,
            new_data=None,
            description=f"Delete instance {selected}"
        )
        self.execute_command(cmd)

        self.clear_selection()
        print(f"Deleted instance {selected}")

    def load_project(self):
        """Load boneless animation project"""
        filename = "boneless_anim_project.json"
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

            print(f"Loaded project: {filename}")
            return True

        except Exception as e:
            print(f"Failed to load project: {e}")
            return False

    def save_project(self):
        """Save boneless animation project"""
        filename = "boneless_anim_project.json"
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

            print(f"Saved project: {filename}")

        except Exception as e:
            print(f"Failed to save project: {e}")


# Run the enhanced editor
if __name__ == "__main__":
    editor = BonelessAnimEditor()
    editor.run()