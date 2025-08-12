# attachment_editor_improved.py - Sprite attachment editor with viewport overlay
import pygame
import math
import os
import json
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from core_base import UniversalEditor, Command


# Data structures from the original editors
@dataclass
class SpriteRect:
    name: str
    x: int
    y: int
    width: int
    height: int
    origin_x: float = 0.5
    origin_y: float = 0.5
    endpoint_x: float = 0.5
    endpoint_y: float = 0.5


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
    auto_adjust_bone: bool = True

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


class BoneLayer(Enum):
    BEHIND = "behind"
    MIDDLE = "middle"
    FRONT = "front"


class AttachmentPoint(Enum):
    START = "start"
    END = "end"


class SpriteAttachmentEditor(UniversalEditor):
    """Sprite attachment editor with viewport overlay for sprite palette"""

    def __init__(self):
        super().__init__()

        # Asset loading
        self.sprite_sheet = None
        self.sprite_sheet_path = ""

        # Selection and interaction
        self.selected_sprite_type = None

        # Interaction state
        self.dragging_sprite_instance = False
        self.rotating_sprite = False
        self.rotation_start_angle = 0.0
        self.rotation_center = (0, 0)
        self.drag_offset = (0, 0)

        # Sprite palette overlay state
        self.show_sprite_palette = True
        self.palette_scroll = 0
        self.palette_rect = None  # Will be set in draw_sprite_palette_overlay

        # Debug mode
        self.debug_mode = False

        # Try to autoload projects
        self.try_auto_load()

    def setup_data_structures(self):
        """Setup attachment editor data structures"""
        self.data_objects = {
            'sprites': {},
            'bones': {},
            'sprite_instances': {}
        }

    def setup_key_bindings(self):
        """Setup attachment editor key bindings"""
        pass

    def get_editor_name(self) -> str:
        return "Sprite Attachment Editor v1.0"

    def try_auto_load(self):
        """Try to autoload existing projects"""
        self.load_both_projects()
        if os.path.exists("sprite_attachment_editor_project.json"):
            self.load_project()

    # ========================================================================
    # HIERARCHY SYSTEM (UNCHANGED)
    # ========================================================================

    def build_hierarchy(self):
        """Build hierarchy from current data objects"""
        self.hierarchy_nodes.clear()
        root_bones = [name for name, bone in self.data_objects['bones'].items() if bone.parent is None]
        for bone_name in root_bones:
            self.add_bone_hierarchy_node(bone_name)

    def add_bone_hierarchy_node(self, bone_name: str, parent_id: Optional[str] = None):
        """Add bone and its children to hierarchy"""
        if bone_name not in self.data_objects['bones']:
            return

        bone = self.data_objects['bones'][bone_name]
        layer_char = bone.layer.value[0].upper()
        attachment_char = bone.parent_attachment_point.value[0].upper() if bone.parent else ""
        layer_suffix = f"[{layer_char}{bone.layer_order}"
        if attachment_char:
            layer_suffix += f"->{attachment_char}"
        layer_suffix += "]"
        display_name = f"{bone_name} {layer_suffix}"

        self.add_hierarchy_node(
            bone_name,
            display_name,
            'bones',
            parent_id,
            metadata={'object': bone, 'bone_name': bone_name}
        )

        # Add attached sprite instances
        attached_sprites = [instance for instance in self.data_objects['sprite_instances'].values()
                            if instance.bone_name == bone_name]

        for sprite_instance in attached_sprites:
            attachment_char = "E" if sprite_instance.bone_attachment_point == AttachmentPoint.END else "S"
            auto_adjust_indicator = "~" if sprite_instance.auto_adjust_bone else ""
            sprite_display = f"{sprite_instance.sprite_name}->{attachment_char}{auto_adjust_indicator}"

            self.add_hierarchy_node(
                sprite_instance.id,
                sprite_display,
                'sprite_instances',
                bone_name,
                metadata={'object': sprite_instance, 'sprite_instance': sprite_instance}
            )

        # Add children bones
        for child_name in bone.children:
            self.add_bone_hierarchy_node(child_name, bone_name)

    # ========================================================================
    # SELECTION SYSTEM (IMPROVED)
    # ========================================================================

    def get_objects_at_position(self, pos: Tuple[float, float]) -> List[Tuple[str, str, Any]]:
        """Get all objects at position for selection cycling"""
        objects_at_pos = []
        x, y = pos

        # Check for sprite instances first
        sprite_at_pos = self.get_sprite_instance_at_position(pos)
        if sprite_at_pos:
            objects_at_pos.append(("sprite_instances", sprite_at_pos, "body"))

        # Check for bones (with attachment points)
        bone_attachment = self.get_attachment_point_at_position(pos)
        if bone_attachment[0]:
            bone_name, attachment_point = bone_attachment
            objects_at_pos.append(("bones", bone_name, attachment_point.value))
        else:
            # Check for bone body
            bone_at_pos = self.get_bone_at_position(pos)
            if bone_at_pos:
                objects_at_pos.append(("bones", bone_at_pos, "body"))

        return objects_at_pos

    # ========================================================================
    # EVENT HANDLING (IMPROVED)
    # ========================================================================

    def handle_keydown(self, event) -> bool:
        """Handle attachment editor specific keys"""
        if super().handle_keydown(event):
            return True

        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]
        shift_pressed = pygame.key.get_pressed()[pygame.K_LSHIFT]

        # File operations
        if ctrl_pressed and event.key == pygame.K_r:
            self.load_both_projects()
            return True

        # Toggle sprite palette
        elif event.key == pygame.K_p:
            self.show_sprite_palette = not self.show_sprite_palette
            print(f"Sprite palette: {'ON' if self.show_sprite_palette else 'OFF'}")
            return True

        # Sprite operations
        elif event.key == pygame.K_i:
            self.create_sprite_instance()
            return True
        elif event.key == pygame.K_t:
            self.create_test_sprite_instance()
            return True

        # Rotation shortcuts
        elif event.key == pygame.K_r and not shift_pressed and not ctrl_pressed:
            self.rotate_selected_sprite(15)
            return True
        elif event.key == pygame.K_r and shift_pressed:
            self.rotate_selected_sprite(-15)
            return True

        # Selection and attachment
        elif event.key == pygame.K_a:
            self.toggle_sprite_attachment_point()
            return True
        elif event.key == pygame.K_b:
            self.toggle_auto_adjust_bone()
            return True

        return False

    def handle_viewport_click(self, pos: Tuple[int, int]):
        """Handle clicks in main viewport - now includes sprite palette overlay"""
        viewport_pos = self.screen_to_viewport(pos)

        # Check if clicking on sprite palette overlay first
        if self.show_sprite_palette and self.palette_rect and self.palette_rect.collidepoint(pos):
            self.handle_sprite_palette_click(pos)
            return

        # Use base class selection cycling for main viewport
        self.handle_selection_at_position(viewport_pos, pos)

        # Get selected object for interaction setup
        selected_sprites = self.get_selected_objects('sprite_instances')
        if selected_sprites:
            self.start_sprite_instance_drag(selected_sprites[0], viewport_pos)
        elif not selected_sprites and self.selected_sprite_type:
            # Create sprite instance if sprite type selected
            self.create_sprite_instance_at_position(viewport_pos)

    def handle_sprite_palette_click(self, pos):
        """Handle clicks on sprite palette overlay - FIXED"""
        if not self.palette_rect or not self.sprite_sheet:
            return

        # Calculate relative position within the palette
        relative_x = pos[0] - self.palette_rect.x
        relative_y = pos[1] - self.palette_rect.y + self.palette_scroll

        # Account for header height - match exactly with drawing
        header_height = 90  # FIXED: Match the y_start calculation in draw_sprite_palette_overlay
        if relative_y < header_height:
            return

        # Calculate sprite grid position - FIXED to match drawing exactly
        sprite_size = 40
        spacing = 5
        sprites_per_row = (self.palette_rect.width - 20) // (sprite_size + spacing)

        adjusted_x = relative_x - 10  # Account for margin
        adjusted_y = relative_y - header_height

        if adjusted_x < 0:
            return

        # FIXED: Use exact same calculation as drawing
        row = max(0, int(adjusted_y // (sprite_size + spacing)))
        col = max(0, int(adjusted_x // (sprite_size + spacing)))

        sprite_index = row * sprites_per_row + col
        sprite_names = list(self.data_objects['sprites'].keys())

        if 0 <= sprite_index < len(sprite_names):
            self.selected_sprite_type = sprite_names[sprite_index]
            print(f"Selected sprite: {self.selected_sprite_type}")
        else:
            self.selected_sprite_type = None

    def handle_mouse_wheel(self, event):
        """Handle mouse wheel for zoom, rotation, and palette scroll"""
        mouse_x, mouse_y = pygame.mouse.get_pos()

        # Check if over sprite palette first
        if (self.show_sprite_palette and self.palette_rect and
                self.palette_rect.collidepoint((mouse_x, mouse_y))):
            self.palette_scroll -= event.y * 30
            self.palette_scroll = max(0, self.palette_scroll)
            return

        # Default zoom/scroll behavior
        super().handle_mouse_wheel(event)

    def handle_mouse_drag(self, pos):
        """Handle mouse dragging"""
        viewport_rect = self.get_main_viewport_rect()
        if not viewport_rect.collidepoint(pos):
            return

        if self.dragging_sprite_instance:
            self.update_sprite_instance_drag(pos)
        elif self.rotating_sprite:
            self.update_sprite_rotation(pos)

    def handle_left_click_release(self, pos):
        """Handle left click release"""
        self.dragging_sprite_instance = False

    # ========================================================================
    # SPRITE INSTANCE OPERATIONS (CORE FUNCTIONALITY)
    # ========================================================================

    def start_sprite_instance_drag(self, instance_id, pos):
        """Start dragging a sprite instance"""
        sprite_instance = self.data_objects['sprite_instances'][instance_id]
        sprite_pos = self.get_sprite_world_position(instance_id)

        if sprite_pos:
            self.drag_offset = (pos[0] - sprite_pos[0], pos[1] - sprite_pos[1])
            self.dragging_sprite_instance = True
            self.operation_in_progress = True
            self.drag_start_data = {
                'type': 'move_sprite',
                'instance_id': instance_id,
                'old_offset': (sprite_instance.offset_x, sprite_instance.offset_y)
            }

    def update_sprite_instance_drag(self, pos):
        """Update sprite instance position while dragging"""
        selected = self.get_first_selected('sprite_instances')
        if not selected:
            return

        sprite_instance = self.data_objects['sprite_instances'][selected]
        if not sprite_instance.bone_name or sprite_instance.bone_name not in self.data_objects['bones']:
            return

        viewport_pos = self.screen_to_viewport(pos)
        bone = self.data_objects['bones'][sprite_instance.bone_name]

        # Calculate attachment position
        if sprite_instance.bone_attachment_point == AttachmentPoint.END:
            attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
        else:  # START
            attach_x = bone.x
            attach_y = bone.y

        # Update offset from attachment point
        new_sprite_x = viewport_pos[0] - self.drag_offset[0]
        new_sprite_y = viewport_pos[1] - self.drag_offset[1]
        sprite_instance.offset_x = new_sprite_x - attach_x
        sprite_instance.offset_y = new_sprite_y - attach_y

        # Auto-adjust bone length if enabled
        if sprite_instance.auto_adjust_bone:
            self.auto_adjust_bone_for_sprite(selected)

    def create_sprite_instance_at_position(self, pos):
        """Create sprite instance at specific position"""
        if not self.selected_sprite_type:
            return

        # Check for attachment points with improved tolerance
        bone_name, attachment_point = self.get_attachment_point_at_position(pos, tolerance=25)

        if not bone_name:
            bone_name = self.get_bone_at_position(pos, tolerance=15)
            attachment_point = AttachmentPoint.START

        if bone_name:
            instance_id = self.get_next_sprite_instance_id(self.selected_sprite_type)

            # Calculate offset from attachment point
            bone = self.data_objects['bones'][bone_name]
            if attachment_point == AttachmentPoint.END:
                attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
            else:
                attach_x = bone.x
                attach_y = bone.y

            # ALWAYS attach at sprite origin (pos is where we clicked)
            offset_x = pos[0] - attach_x
            offset_y = pos[1] - attach_y

            new_instance = SpriteInstance(
                id=instance_id,
                sprite_name=self.selected_sprite_type,
                bone_name=bone_name,
                offset_x=offset_x,
                offset_y=offset_y,
                bone_attachment_point=attachment_point or AttachmentPoint.START,
                auto_adjust_bone=True
            )

            command = Command(
                action="create",
                object_type="sprite_instances",
                object_id=instance_id,
                old_data=None,
                new_data=new_instance,
                description=f"Create sprite instance {instance_id}"
            )

            self.execute_command(command)
            self.select_object('sprite_instances', instance_id)

            # Auto-adjust bone to match sprite span
            if new_instance.auto_adjust_bone:
                self.auto_adjust_bone_for_sprite(instance_id)

            attachment_desc = attachment_point.value if attachment_point else "START"
            print(f"Created sprite instance {instance_id} on bone {bone_name} {attachment_desc}")

    # ========================================================================
    # HELPER METHODS (CORE UTILITIES)
    # ========================================================================

    def get_sprite_instance_at_position(self, pos):
        """Find sprite instance at position"""
        x, y = pos

        for instance_id, sprite_instance in self.data_objects['sprite_instances'].items():
            if (sprite_instance.bone_name and
                    sprite_instance.bone_name in self.data_objects['bones'] and
                    sprite_instance.sprite_name in self.data_objects['sprites']):

                sprite_pos = self.get_sprite_world_position(instance_id)
                if not sprite_pos:
                    continue

                sprite = self.data_objects['sprites'][sprite_instance.sprite_name]
                sprite_origin_x, sprite_origin_y = sprite_pos

                # Work in world coordinates
                sprite_width = sprite.width * sprite_instance.scale
                sprite_height = sprite.height * sprite_instance.scale
                origin_offset_x = sprite_width * sprite.origin_x
                origin_offset_y = sprite_height * sprite.origin_y

                left = sprite_origin_x - origin_offset_x
                top = sprite_origin_y - origin_offset_y
                right = left + sprite_width
                bottom = top + sprite_height

                if left <= x <= right and top <= y <= bottom:
                    return instance_id

        return None

    def get_bone_at_position(self, pos, tolerance=8):
        """Find bone at position"""
        x, y = pos
        adjusted_tolerance = max(4, int(tolerance / max(0.1, self.viewport.zoom)))

        for bone_name, bone in self.data_objects['bones'].items():
            end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

            dist = self.point_to_line_distance((x, y), (bone.x, bone.y), (end_x, end_y))
            if dist < adjusted_tolerance:
                return bone_name

        return None

    def get_attachment_point_at_position(self, pos, tolerance=15):
        """Find attachment point at position"""
        x, y = pos
        adjusted_tolerance = max(8, int(tolerance / max(0.1, self.viewport.zoom)))

        for bone_name, bone in self.data_objects['bones'].items():
            end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

            # Check end point
            end_dist = math.sqrt((x - end_x) ** 2 + (y - end_y) ** 2)
            if end_dist < adjusted_tolerance:
                return bone_name, AttachmentPoint.END

            # Check start point
            start_dist = math.sqrt((x - bone.x) ** 2 + (y - bone.y) ** 2)
            if start_dist < adjusted_tolerance:
                return bone_name, AttachmentPoint.START

        return None, None

    @staticmethod
    def point_to_line_distance(point, line_start, line_end):
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

    def get_sprite_endpoint_world_position(self, instance_id):
        """Get sprite's endpoint position in world coordinates - CORRECTED"""
        if instance_id not in self.data_objects['sprite_instances']:
            return None

        sprite_instance = self.data_objects['sprite_instances'][instance_id]
        if sprite_instance.sprite_name not in self.data_objects['sprites']:
            return None

        sprite = self.data_objects['sprites'][sprite_instance.sprite_name]
        sprite_origin_pos = self.get_sprite_world_position(instance_id)  # This is the origin position
        if not sprite_origin_pos:
            return None

        sprite_origin_x, sprite_origin_y = sprite_origin_pos

        # Calculate endpoint position relative to origin position
        scaled_width = sprite.width * sprite_instance.scale
        scaled_height = sprite.height * sprite_instance.scale

        # Calculate the offset from origin to endpoint
        endpoint_offset_x = (sprite.endpoint_x - sprite.origin_x) * scaled_width
        endpoint_offset_y = (sprite.endpoint_y - sprite.origin_y) * scaled_height

        actual_endpoint_x = sprite_origin_x + endpoint_offset_x
        actual_endpoint_y = sprite_origin_y + endpoint_offset_y

        return actual_endpoint_x, actual_endpoint_y

    def get_next_sprite_instance_id(self, sprite_name):
        """Generate next sprite instance ID"""
        existing_count = len([i for i in self.data_objects['sprite_instances'].values()
                              if i.sprite_name == sprite_name])
        return f"{sprite_name}_{existing_count + 1}"

    # ========================================================================
    # AUTO-ADJUSTMENT AND DUAL ATTACHMENT FEATURES
    # ========================================================================

    def auto_adjust_bone_for_sprite(self, instance_id):
        """Automatically adjust bone length and angle to match sprite's dual attachment points - CORRECTED"""
        if instance_id not in self.data_objects['sprite_instances']:
            return

        sprite_instance = self.data_objects['sprite_instances'][instance_id]
        if not sprite_instance.bone_name or sprite_instance.bone_name not in self.data_objects['bones']:
            return

        if not sprite_instance.sprite_name or sprite_instance.sprite_name not in self.data_objects['sprites']:
            return

        sprite = self.data_objects['sprites'][sprite_instance.sprite_name]
        bone = self.data_objects['bones'][sprite_instance.bone_name]

        # Get sprite's origin and endpoint positions in world coordinates
        sprite_origin_world = self.get_sprite_origin_world_position(instance_id)
        sprite_endpoint_world = self.get_sprite_endpoint_world_position(instance_id)

        if not sprite_origin_world or not sprite_endpoint_world:
            return

        # Calculate the bone direction based on attachment point
        if sprite_instance.bone_attachment_point == AttachmentPoint.START:
            # Sprite is attached to bone START (red dot)
            # Bone should go FROM origin TO endpoint
            start_pos = sprite_origin_world
            end_pos = sprite_endpoint_world
        else:
            # Sprite is attached to bone END (red dot)
            # Bone should go FROM endpoint TO origin
            start_pos = sprite_endpoint_world
            end_pos = sprite_origin_world

        # Calculate distance and angle
        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        sprite_span_length = math.sqrt(dx * dx + dy * dy)
        sprite_span_angle = math.degrees(math.atan2(dy, dx))

        # Adjust bone to match sprite span
        if sprite_span_length > 5:  # Minimum meaningful length
            # Always update length and angle
            bone.length = sprite_span_length
            bone.angle = sprite_span_angle

            # Only adjust bone position if it's a ROOT bone (has no parent)
            if bone.parent is None:
                # For root bones, we can freely position them
                # The bone start should always be at start_pos
                bone.x = start_pos[0]
                bone.y = start_pos[1]
            else:
                # For child bones, DON'T move the bone - instead adjust the sprite offset
                # to match where the bone actually is after length/angle changes

                # Calculate where the bone attachment point actually is
                if sprite_instance.bone_attachment_point == AttachmentPoint.END:
                    actual_attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                    actual_attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
                    # The sprite origin should align with this end point
                    target_origin_pos = (actual_attach_x, actual_attach_y)
                else:  # START
                    actual_attach_x = bone.x
                    actual_attach_y = bone.y
                    # The sprite origin should align with this start point
                    target_origin_pos = (actual_attach_x, actual_attach_y)

                # Adjust sprite offset so the origin aligns with the bone attachment point
                sprite_instance.offset_x = target_origin_pos[0] - actual_attach_x
                sprite_instance.offset_y = target_origin_pos[1] - actual_attach_y

            # Update child positions only if this bone has children
            if bone.children:
                self.update_child_bone_positions(bone.name)

            print(f"Auto-adjusted bone {bone.name}: length={bone.length:.1f}, angle={bone.angle:.1f}Degrees")

    def update_child_bone_positions(self, bone_name):
        """Update child bone positions recursively"""
        if bone_name not in self.data_objects['bones']:
            return

        bone = self.data_objects['bones'][bone_name]

        for child_name in bone.children:
            if child_name in self.data_objects['bones']:
                child_bone = self.data_objects['bones'][child_name]

                # Calculate attachment position
                if child_bone.parent_attachment_point == AttachmentPoint.END:
                    # Child attaches to parent's end
                    attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                    attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
                else:
                    # Child attaches to parent's start
                    attach_x = bone.x
                    attach_y = bone.y

                child_bone.x = attach_x
                child_bone.y = attach_y

                # Recursively update grandchildren
                self.update_child_bone_positions(child_name)

    def get_sprite_world_position(self, instance_id):
        """Get world position where sprite's origin should be placed"""
        if instance_id not in self.data_objects['sprite_instances']:
            return None

        sprite_instance = self.data_objects['sprite_instances'][instance_id]
        if not sprite_instance.bone_name or sprite_instance.bone_name not in self.data_objects['bones']:
            return None

        bone = self.data_objects['bones'][sprite_instance.bone_name]

        # Determine bone attachment position
        if sprite_instance.bone_attachment_point == AttachmentPoint.END:
            attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
        else:  # START
            attach_x = bone.x
            attach_y = bone.y

        # Apply sprite offset
        sprite_origin_x = attach_x + sprite_instance.offset_x
        sprite_origin_y = attach_y + sprite_instance.offset_y

        return sprite_origin_x, sprite_origin_y

    def get_sprite_origin_world_position(self, instance_id):
        """Get sprite's origin point in world coordinates - CORRECTED"""
        # The sprite_pos from get_sprite_world_position IS the origin position!
        return self.get_sprite_world_position(instance_id)

    def get_sprite_endpoint_world_position(self, instance_id):
        """Get sprite's endpoint position in world coordinates - CORRECTED"""
        if instance_id not in self.data_objects['sprite_instances']:
            return None

        sprite_instance = self.data_objects['sprite_instances'][instance_id]
        if sprite_instance.sprite_name not in self.data_objects['sprites']:
            return None

        sprite = self.data_objects['sprites'][sprite_instance.sprite_name]

        # Get the origin position in world coordinates
        origin_world_pos = self.get_sprite_world_position(instance_id)
        if not origin_world_pos:
            return None

        origin_world_x, origin_world_y = origin_world_pos

        # Calculate sprite rectangle dimensions
        scaled_width = sprite.width * sprite_instance.scale
        scaled_height = sprite.height * sprite_instance.scale

        # Calculate sprite rectangle top-left corner from origin position
        origin_offset_x = sprite.origin_x * scaled_width
        origin_offset_y = sprite.origin_y * scaled_height

        sprite_rect_x = origin_world_x - origin_offset_x
        sprite_rect_y = origin_world_y - origin_offset_y

        # Calculate endpoint position relative to sprite rectangle
        endpoint_world_x = sprite_rect_x + sprite.endpoint_x * scaled_width
        endpoint_world_y = sprite_rect_y + sprite.endpoint_y * scaled_height

        return endpoint_world_x, endpoint_world_y

    # ========================================================================
    # SPRITE OPERATIONS
    # ========================================================================

    def create_sprite_instance(self):
        """Create a sprite instance"""
        if not self.selected_sprite_type:
            print("No sprite type selected. Click a sprite in the palette first.")
            return

        instance_id = self.get_next_sprite_instance_id(self.selected_sprite_type)
        new_instance = SpriteInstance(
            id=instance_id,
            sprite_name=self.selected_sprite_type,
            auto_adjust_bone=True
        )

        command = Command(
            action="create",
            object_type="sprite_instances",
            object_id=instance_id,
            old_data=None,
            new_data=new_instance,
            description=f"Create sprite instance {instance_id}"
        )

        self.execute_command(command)
        self.select_object('sprite_instances', instance_id)
        print(f"Created sprite instance: {instance_id} (not attached to any bone)")

    def create_test_sprite_instance(self):
        """Create sprite instance on first bone"""
        if not self.selected_sprite_type:
            print("Need sprite type selected. Click a sprite in the palette first.")
            return

        if not self.data_objects['bones']:
            print("No bones available. Create bones first.")
            return

        instance_id = self.get_next_sprite_instance_id(self.selected_sprite_type)
        bone_name = list(self.data_objects['bones'].keys())[0]

        new_instance = SpriteInstance(
            id=instance_id,
            sprite_name=self.selected_sprite_type,
            bone_name=bone_name,
            bone_attachment_point=AttachmentPoint.START,
            auto_adjust_bone=True
        )

        command = Command(
            action="create",
            object_type="sprite_instances",
            object_id=instance_id,
            old_data=None,
            new_data=new_instance,
            description=f"Create test sprite instance {instance_id}"
        )

        self.execute_command(command)
        self.select_object('sprite_instances', instance_id)

        # Automatically adjust bone to match sprite span
        self.auto_adjust_bone_for_sprite(instance_id)

        print(f"Created test sprite instance: {instance_id} with bone auto-adjustment")

    def toggle_sprite_attachment_point(self):
        """Toggle attachment point of selected sprite"""
        selected = self.get_first_selected('sprite_instances')
        if not selected:
            return

        sprite_instance = self.data_objects['sprite_instances'][selected]
        if not sprite_instance.bone_name:
            print("Sprite not attached to any bone")
            return

        old_instance = self.copy_sprite_instance(sprite_instance)
        old_attachment = sprite_instance.bone_attachment_point
        new_attachment = AttachmentPoint.START if old_attachment == AttachmentPoint.END else AttachmentPoint.END

        sprite_instance.bone_attachment_point = new_attachment

        command = Command(
            action="modify",
            object_type="sprite_instances",
            object_id=selected,
            old_data=old_instance,
            new_data=sprite_instance,
            description=f"Toggle {selected} attachment point"
        )

        self.execute_command(command)

        # Re-adjust bone if auto-adjust is enabled
        if sprite_instance.auto_adjust_bone:
            self.auto_adjust_bone_for_sprite(selected)

        print(f"Toggled {selected} attachment to {new_attachment.value.upper()}")

    def toggle_auto_adjust_bone(self):
        """Toggle auto-adjust bone feature for selected sprite"""
        selected = self.get_first_selected('sprite_instances')
        if not selected:
            return

        sprite_instance = self.data_objects['sprite_instances'][selected]
        old_instance = self.copy_sprite_instance(sprite_instance)

        sprite_instance.auto_adjust_bone = not sprite_instance.auto_adjust_bone

        command = Command(
            action="modify",
            object_type="sprite_instances",
            object_id=selected,
            old_data=old_instance,
            new_data=sprite_instance,
            description=f"Toggle auto-adjust for {selected}"
        )

        self.execute_command(command)

        status = "enabled" if sprite_instance.auto_adjust_bone else "disabled"
        print(f"Auto-adjust bone {status} for {selected}")

        # If enabled, immediately adjust the bone
        if sprite_instance.auto_adjust_bone:
            self.auto_adjust_bone_for_sprite(selected)

    def rotate_selected_sprite(self, degrees):
        """Rotate selected sprite by given degrees"""
        selected = self.get_first_selected('sprite_instances')
        if not selected:
            return

        sprite_instance = self.data_objects['sprite_instances'][selected]
        old_rotation = sprite_instance.offset_rotation
        new_rotation = (old_rotation + degrees) % 360

        command = Command(
            action="modify",
            object_type="sprite_instances",
            object_id=selected,
            old_data=self.copy_sprite_instance(sprite_instance, old_rotation),
            new_data=sprite_instance,
            description=f"Rotate {selected} by {degrees} degrees"
        )

        sprite_instance.offset_rotation = new_rotation
        self.execute_command(command)

    def copy_sprite_instance(self, instance, rotation=None):
        """Create a copy of a sprite instance"""
        return SpriteInstance(
            id=instance.id,
            sprite_name=instance.sprite_name,
            bone_name=instance.bone_name,
            offset_x=instance.offset_x,
            offset_y=instance.offset_y,
            offset_rotation=rotation if rotation is not None else instance.offset_rotation,
            scale=instance.scale,
            bone_attachment_point=instance.bone_attachment_point,
            auto_adjust_bone=instance.auto_adjust_bone
        )

    # ========================================================================
    # FILE OPERATIONS
    # ========================================================================

    def load_both_projects(self):
        """Load both sprite and bone projects"""
        sprite_loaded = False
        bone_loaded = False

        # Load sprite project
        sprite_filename = "../sprite_sheet_editor_v1.0_project.json"
        if os.path.exists(sprite_filename):
            sprite_loaded = self.load_sprite_project(sprite_filename)
            if sprite_loaded:
                print(f"Loaded sprite project: {len(self.data_objects['sprites'])} sprites")

        # Load bone project
        bone_filename = "bone_editor_v1.0_project.json"
        if os.path.exists(bone_filename):
            bone_loaded = self.load_bone_project(bone_filename)
            if bone_loaded:
                print(f"Loaded bone project: {len(self.data_objects['bones'])} bones")

        if sprite_loaded and bone_loaded:
            print("Ready for sprite attachment! Select sprites from palette and click on bones to attach.")
        elif sprite_loaded:
            print("Sprites loaded. Create bones in the Bone Editor to attach sprites to.")
        elif bone_loaded:
            print("Bones loaded. Create sprites in the Sprite Editor to attach to bones.")
        else:
            print("No projects loaded. Create sprites and bones first in their respective editors.")

        return sprite_loaded and bone_loaded

    def load_sprite_project(self, filename):
        """Load sprite project data with dual attachment point support"""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)

            project_data = data.get('data', data)

            # Load sprite sheet
            if project_data.get('sprite_sheet_path'):
                self.sprite_sheet_path = project_data['sprite_sheet_path']
                if os.path.exists(self.sprite_sheet_path):
                    self.sprite_sheet = pygame.image.load(self.sprite_sheet_path)

            # Load sprites with backward compatibility for dual attachment points
            self.data_objects['sprites'] = {}
            for name, sprite_data in project_data.get('sprites', {}).items():
                # Handle backward compatibility - add default endpoint if missing
                if 'endpoint_x' not in sprite_data:
                    sprite_data['endpoint_x'] = 1.0  # Default to right side
                if 'endpoint_y' not in sprite_data:
                    sprite_data['endpoint_y'] = 0.5  # Default to middle

                self.data_objects['sprites'][name] = SpriteRect(**sprite_data)

            print(f"Loaded {len(self.data_objects['sprites'])} sprites from {filename}")
            return True
        except Exception as e:
            print(f"Failed to load sprite project: {e}")
            return False

    def load_bone_project(self, filename):
        """Load bone project data"""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)

            project_data = data.get('data', data)

            # Load bones
            self.data_objects['bones'] = {}
            for name, bone_data in project_data.get('bones', {}).items():
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

            print(f"Loaded {len(self.data_objects['bones'])} bones from {filename}")
            return True
        except Exception as e:
            print(f"Failed to load bone project: {e}")
            return False

    def serialize_data_objects(self):
        """Serialize data objects for saving"""
        sprites_data = {}
        for name, sprite in self.data_objects['sprites'].items():
            sprites_data[name] = {
                'name': sprite.name,
                'x': sprite.x,
                'y': sprite.y,
                'width': sprite.width,
                'height': sprite.height,
                'origin_x': sprite.origin_x,
                'origin_y': sprite.origin_y,
                'endpoint_x': sprite.endpoint_x,
                'endpoint_y': sprite.endpoint_y
            }

        bones_data = {}
        for name, bone in self.data_objects['bones'].items():
            bones_data[name] = {
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
            }

        sprite_instances_data = {}
        for instance_id, instance in self.data_objects['sprite_instances'].items():
            sprite_instances_data[instance_id] = {
                'id': instance.id,
                'sprite_name': instance.sprite_name,
                'bone_name': instance.bone_name,
                'offset_x': instance.offset_x,
                'offset_y': instance.offset_y,
                'offset_rotation': instance.offset_rotation,
                'scale': instance.scale,
                'bone_attachment_point': instance.bone_attachment_point.value,
                'auto_adjust_bone': instance.auto_adjust_bone
            }

        return {
            'sprite_sheet_path': self.sprite_sheet_path,
            'sprites': sprites_data,
            'bones': bones_data,
            'sprite_instances': sprite_instances_data
        }

    def deserialize_data_objects(self, data):
        """Deserialize data objects from loading"""
        result = {'sprites': {}, 'bones': {}, 'sprite_instances': {}}

        # Load sprite sheet path
        if 'sprite_sheet_path' in data:
            self.sprite_sheet_path = data['sprite_sheet_path']
            if os.path.exists(self.sprite_sheet_path):
                self.sprite_sheet = pygame.image.load(self.sprite_sheet_path)

        # Load sprites with dual attachment point support
        for name, sprite_data in data.get('sprites', {}).items():
            # Handle backward compatibility
            if 'endpoint_x' not in sprite_data:
                sprite_data['endpoint_x'] = 1.0
            if 'endpoint_y' not in sprite_data:
                sprite_data['endpoint_y'] = 0.5

            result['sprites'][name] = SpriteRect(**sprite_data)

        # Load bones
        for name, bone_data in data.get('bones', {}).items():
            bone_data['layer'] = BoneLayer(bone_data.get('layer', 'middle'))
            bone_data['parent_attachment_point'] = AttachmentPoint(bone_data.get('parent_attachment_point', 'end'))
            result['bones'][name] = Bone(**bone_data)

        # Load sprite instances
        for instance_id, instance_data in data.get('sprite_instances', {}).items():
            instance_data['bone_attachment_point'] = AttachmentPoint(
                instance_data.get('bone_attachment_point', 'start'))

            # Handle backward compatibility for auto_adjust_bone
            if 'auto_adjust_bone' not in instance_data:
                instance_data['auto_adjust_bone'] = False

            result['sprite_instances'][instance_id] = SpriteInstance(**instance_data)

        return result

    def delete_selected(self):
        """Delete selected sprite instance"""
        selected = self.get_first_selected('sprite_instances')
        if selected:
            sprite_instance = self.data_objects['sprite_instances'][selected]
            command = Command(
                action="delete",
                object_type="sprite_instances",
                object_id=selected,
                old_data=sprite_instance,
                new_data=None,
                description=f"Delete sprite instance {selected}"
            )
            self.execute_command(command)
            self.clear_selection()

    def create_operation_command(self):
        """Create undo command for completed operation"""
        if not self.drag_start_data:
            return

        data = self.drag_start_data

        if data['type'] == 'move_sprite':
            instance_id = data['instance_id']
            current_instance = self.data_objects['sprite_instances'][instance_id]
            old_instance = self.copy_sprite_instance(current_instance)
            old_instance.offset_x = data['old_offset'][0]
            old_instance.offset_y = data['old_offset'][1]

            command = Command(
                action="modify",
                object_type="sprite_instances",
                object_id=instance_id,
                old_data=old_instance,
                new_data=current_instance,
                description=f"Move {instance_id}"
            )

            # Add to history manually
            self.command_history.append(command)
            self.redo_stack.clear()
            if len(self.command_history) > self.max_history:
                self.command_history.pop(0)

    # ========================================================================
    # DRAWING SYSTEM (IMPROVED WITH VIEWPORT OVERLAY)
    # ========================================================================

    def draw_objects(self):
        """Draw bones and sprite instances with proper layering"""
        self.draw_bones()
        self.draw_sprite_instances_by_layer()

    def draw_bones(self):
        """Draw bone hierarchy connections and bones"""
        # Draw hierarchy connections
        for bone_name, bone in self.data_objects['bones'].items():
            if bone.parent and bone.parent in self.data_objects['bones']:
                parent_bone = self.data_objects['bones'][bone.parent]

                # Calculate attachment position
                if bone.parent_attachment_point == AttachmentPoint.END:
                    parent_attach_x = parent_bone.x + parent_bone.length * math.cos(math.radians(parent_bone.angle))
                    parent_attach_y = parent_bone.y + parent_bone.length * math.sin(math.radians(parent_bone.angle))
                    connection_color = (100, 100, 100)
                else:
                    parent_attach_x = parent_bone.x
                    parent_attach_y = parent_bone.y
                    connection_color = (150, 100, 150)

                parent_attach_screen = self.viewport_to_screen((parent_attach_x, parent_attach_y))
                child_start_screen = self.viewport_to_screen((bone.x, bone.y))

                pygame.draw.line(self.screen, connection_color, parent_attach_screen, child_start_screen, 2)

        # Draw individual bones
        selected_bones = self.get_selected_objects('bones')
        for bone_name, bone in self.data_objects['bones'].items():
            selected = bone_name in selected_bones
            self.draw_bone(bone, selected)

    def draw_bone(self, bone, selected):
        """Draw a single bone"""
        colors = self.get_bone_layer_colors(bone.layer, selected)

        # Calculate positions
        start_screen = self.viewport_to_screen((bone.x, bone.y))
        end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
        end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
        end_screen = self.viewport_to_screen((end_x, end_y))

        # Draw bone line
        width = max(1, int(2 * self.viewport.zoom))
        pygame.draw.line(self.screen, colors['line'], start_screen, end_screen, width)

        # Draw joint points
        start_radius = max(2, int(4 * self.viewport.zoom))
        end_radius = max(2, int(4 * self.viewport.zoom))

        pygame.draw.circle(self.screen, colors['start'],
                           (int(start_screen[0]), int(start_screen[1])), start_radius)
        pygame.draw.circle(self.screen, colors['end'],
                           (int(end_screen[0]), int(end_screen[1])), end_radius)

        # Draw bone name if zoomed in
        if self.viewport.zoom > 0.4:
            mid_x = (start_screen[0] + end_screen[0]) / 2
            mid_y = (start_screen[1] + end_screen[1]) / 2

            # Show layer and sprite count
            sprite_count = len([i for i in self.data_objects['sprite_instances'].values()
                                if i.bone_name == bone.name])
            auto_adjust_count = len([i for i in self.data_objects['sprite_instances'].values()
                                     if i.bone_name == bone.name and i.auto_adjust_bone])

            display_name = f"{bone.name}[{bone.layer.value[0].upper()}{bone.layer_order}]"
            if sprite_count > 0:
                display_name += f"({sprite_count}"
                if auto_adjust_count > 0:
                    display_name += f"~{auto_adjust_count}"
                display_name += ")"

            text_color = colors['line']
            text = self.small_font.render(display_name, True, text_color)
            self.screen.blit(text, (mid_x, mid_y - 15))

    @staticmethod
    def get_bone_layer_colors(bone_layer, selected):
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

    def draw_sprite_instances_by_layer(self):
        """Draw sprite instances grouped by bone layer"""
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
        selected_sprites = self.get_selected_objects('sprite_instances')
        for layer in [BoneLayer.BEHIND, BoneLayer.MIDDLE, BoneLayer.FRONT]:
            for layer_order, instance_id, sprite_instance in layered_sprites[layer]:
                selected = instance_id in selected_sprites
                self.draw_sprite_instance(instance_id, sprite_instance, selected)

    def draw_sprite_instance(self, instance_id, sprite_instance, selected):
        """Draw a single sprite instance with dual attachment point visualization"""
        sprite = self.data_objects['sprites'][sprite_instance.sprite_name]
        bone = self.data_objects['bones'][sprite_instance.bone_name]

        try:
            # Get sprite world position
            sprite_pos = self.get_sprite_world_position(instance_id)
            if not sprite_pos:
                return

            sprite_world_x, sprite_world_y = sprite_pos

            # Extract sprite from sheet
            sprite_surface = self.sprite_sheet.subsurface((sprite.x, sprite.y, sprite.width, sprite.height))

            # Calculate final size after scaling
            final_width = max(1, int(sprite.width * sprite_instance.scale * self.viewport.zoom))
            final_height = max(1, int(sprite.height * sprite_instance.scale * self.viewport.zoom))

            # Scale the sprite
            scaled_sprite = pygame.transform.scale(sprite_surface, (final_width, final_height))

            # Calculate origin position in scaled sprite
            origin_x_pixels = final_width * sprite.origin_x
            origin_y_pixels = final_height * sprite.origin_y

            # Convert world position to screen coordinates
            origin_screen_pos = self.viewport_to_screen((sprite_world_x, sprite_world_y))

            # Handle rotation
            if abs(sprite_instance.offset_rotation) > 0.01:
                # Rotate around origin
                max_dim = max(final_width, final_height) * 2
                rotation_surface = pygame.Surface((max_dim, max_dim), pygame.SRCALPHA)

                sprite_pos_in_rotation = (
                    max_dim // 2 - origin_x_pixels,
                    max_dim // 2 - origin_y_pixels
                )
                rotation_surface.blit(scaled_sprite, sprite_pos_in_rotation)

                rotated_surface = pygame.transform.rotate(rotation_surface, -sprite_instance.offset_rotation)
                rotated_rect = rotated_surface.get_rect()

                final_pos = (
                    origin_screen_pos[0] - rotated_rect.width // 2,
                    origin_screen_pos[1] - rotated_rect.height // 2
                )

                self.screen.blit(rotated_surface, final_pos)

                # Selection highlight for rotated sprites
                if selected:
                    pygame.draw.circle(self.screen, (0, 255, 255),
                                       (int(origin_screen_pos[0]), int(origin_screen_pos[1])),
                                       max(final_width, final_height) // 2, 3)
            else:
                # No rotation - simple positioning
                final_pos = (
                    origin_screen_pos[0] - origin_x_pixels,
                    origin_screen_pos[1] - origin_y_pixels
                )

                self.screen.blit(scaled_sprite, final_pos)

                # Selection highlight
                if selected:
                    highlight_rect = pygame.Rect(final_pos[0], final_pos[1], final_width, final_height)
                    pygame.draw.rect(self.screen, (0, 255, 255), highlight_rect, 3)

            # Draw dual attachment point visualization
            sprite_origin_world = self.get_sprite_origin_world_position(instance_id)
            sprite_endpoint_world = self.get_sprite_endpoint_world_position(instance_id)

            if sprite_origin_world and sprite_endpoint_world:
                origin_screen = self.viewport_to_screen(sprite_origin_world)
                endpoint_screen = self.viewport_to_screen(sprite_endpoint_world)

                # Draw connection line between origin and endpoint
                if sprite_instance.auto_adjust_bone:
                    line_color = (255, 255, 0)  # Yellow for auto-adjust enabled
                    line_width = 3
                else:
                    line_color = (255, 165, 0)  # Orange for normal
                    line_width = 2

                pygame.draw.line(self.screen, line_color, origin_screen, endpoint_screen, line_width)

                # Draw origin point (red)
                pygame.draw.circle(self.screen, (255, 0, 0),
                                   (int(origin_screen[0]), int(origin_screen[1])), 4)
                pygame.draw.circle(self.screen, (255, 255, 255),
                                   (int(origin_screen[0]), int(origin_screen[1])), 4, 1)

                # Draw endpoint (blue)
                pygame.draw.circle(self.screen, (0, 0, 255),
                                   (int(endpoint_screen[0]), int(endpoint_screen[1])), 4)
                pygame.draw.circle(self.screen, (255, 255, 255),
                                   (int(endpoint_screen[0]), int(endpoint_screen[1])), 4, 1)

            # Draw attachment point indicators
            if sprite_instance.bone_attachment_point == AttachmentPoint.END:
                attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
                attachment_color = (255, 0, 0)  # Red for END
            else:  # START
                attach_x = bone.x
                attach_y = bone.y
                attachment_color = (0, 0, 255)  # Blue for START

            attachment_screen = self.viewport_to_screen((attach_x, attach_y))

            # Draw attachment point and connection
            pygame.draw.circle(self.screen, attachment_color,
                               (int(attachment_screen[0]), int(attachment_screen[1])), 4)
            pygame.draw.line(self.screen, attachment_color, attachment_screen, origin_screen_pos, 2)

        except pygame.error:
            pass  # Skip if sprite extraction fails

    # ========================================================================
    # VIEWPORT OVERLAY (NEW - MAIN IMPROVEMENT)
    # ========================================================================

    def draw_overlays(self):
        """Draw overlays including the sprite palette"""
        # Draw rotation controls for selected sprite
        selected_sprite = self.get_first_selected('sprite_instances')
        if selected_sprite:
            self.draw_sprite_rotation_overlay(selected_sprite)

        # Draw sprite palette overlay (main improvement)
        if self.show_sprite_palette:
            self.draw_sprite_palette_overlay()

        # Draw viewport info overlay (similar to bone editor)
        self.draw_viewport_info_overlay()

    def draw_sprite_rotation_overlay(self, sprite_instance_id):
        """Draw rotation controls for selected sprite"""
        sprite_pos = self.get_sprite_world_position(sprite_instance_id)
        if sprite_pos:
            sprite_instance = self.data_objects['sprite_instances'][sprite_instance_id]
            sprite_screen_pos = self.viewport_to_screen(sprite_pos)

            # Rotation circle
            radius = max(30, int(40 / self.viewport.zoom))
            pygame.draw.circle(self.screen, (255, 165, 0),
                               (int(sprite_screen_pos[0]), int(sprite_screen_pos[1])),
                               radius, 2)

            # Rotation indicator
            angle_rad = math.radians(sprite_instance.offset_rotation)
            line_end_x = sprite_screen_pos[0] + radius * math.cos(angle_rad)
            line_end_y = sprite_screen_pos[1] + radius * math.sin(angle_rad)

            pygame.draw.line(self.screen, (255, 165, 0),
                             sprite_screen_pos, (int(line_end_x), int(line_end_y)), 3)

            # Auto-adjust indicator
            if sprite_instance.auto_adjust_bone:
                auto_text = self.small_font.render("AUTO~", True, (255, 255, 0))
                self.screen.blit(auto_text, (sprite_screen_pos[0] + radius + 10, sprite_screen_pos[1] + 20))

            # Rotation value
            if abs(sprite_instance.offset_rotation) > 0.1:
                rot_text = self.small_font.render(f"{sprite_instance.offset_rotation:.1f}Degrees", True, (255, 165, 0))
                self.screen.blit(rot_text, (sprite_screen_pos[0] + radius + 10, sprite_screen_pos[1] - 10))

    def draw_sprite_palette_overlay(self):
        """Draw sprite palette overlay in viewport - FIXED click detection"""
        if not self.sprite_sheet:
            return

        viewport_rect = self.get_main_viewport_rect()

        # Position palette in top-left of viewport
        palette_width = 300
        palette_height = 400
        palette_x = viewport_rect.x + 10
        palette_y = viewport_rect.y + 10

        # Store palette rect for click detection
        self.palette_rect = pygame.Rect(palette_x, palette_y, palette_width, palette_height)

        # Draw semi-transparent background
        palette_surface = pygame.Surface((palette_width, palette_height), pygame.SRCALPHA)
        pygame.draw.rect(palette_surface, (0, 0, 0, 200), palette_surface.get_rect())
        pygame.draw.rect(palette_surface, (255, 255, 255), palette_surface.get_rect(), 2)
        self.screen.blit(palette_surface, (palette_x, palette_y))

        # Draw title
        title_text = self.font.render("Sprite Palette", True, (255, 255, 255))
        self.screen.blit(title_text, (palette_x + 10, palette_y + 10))

        # Draw instructions
        instructions = [
            "Click to select sprite",
            "P: Toggle this palette",
            "T: Test on first bone",
            "I: Create unattached"
        ]

        y_offset = palette_y + 35
        for instruction in instructions:
            inst_text = self.small_font.render(instruction, True, (200, 200, 200))
            self.screen.blit(inst_text, (palette_x + 10, y_offset))
            y_offset += 15

        # FIXED: Consistent y_start calculation for click detection
        y_start = palette_y + 90  # This should match header_height in click detection

        # Draw sprite grid
        sprite_size = 40
        spacing = 5
        sprites_per_row = (palette_width - 20) // (sprite_size + spacing)

        for i, (sprite_name, sprite) in enumerate(self.data_objects['sprites'].items()):
            row = i // sprites_per_row
            col = i % sprites_per_row

            # FIXED: Use exact same calculation for positioning
            sprite_x = palette_x + 10 + col * (sprite_size + spacing)
            sprite_y = y_start + row * (sprite_size + spacing) - self.palette_scroll

            # Only draw if visible
            if palette_y < sprite_y < palette_y + palette_height - sprite_size:
                try:
                    sprite_surface = self.sprite_sheet.subsurface((sprite.x, sprite.y, sprite.width, sprite.height))
                    scaled_sprite = pygame.transform.scale(sprite_surface, (sprite_size, sprite_size))

                    sprite_rect = pygame.Rect(sprite_x, sprite_y, sprite_size, sprite_size)

                    # Highlight if selected
                    if sprite_name == self.selected_sprite_type:
                        pygame.draw.rect(self.screen, (255, 255, 0), sprite_rect.inflate(4, 4))

                    self.screen.blit(scaled_sprite, sprite_rect)
                    pygame.draw.rect(self.screen, (255, 255, 255), sprite_rect, 1)

                    # Draw dual attachment points preview
                    origin_x = sprite_x + sprite_size * sprite.origin_x
                    origin_y = sprite_y + sprite_size * sprite.origin_y
                    endpoint_x = sprite_x + sprite_size * sprite.endpoint_x
                    endpoint_y = sprite_y + sprite_size * sprite.endpoint_y

                    # Draw connection line
                    pygame.draw.line(self.screen, (255, 165, 0), (origin_x, origin_y), (endpoint_x, endpoint_y), 1)

                    # Draw origin point (red)
                    pygame.draw.circle(self.screen, (255, 0, 0), (int(origin_x), int(origin_y)), 2)
                    # Draw endpoint (blue)
                    pygame.draw.circle(self.screen, (0, 0, 255), (int(endpoint_x), int(endpoint_y)), 2)

                except pygame.error:
                    pass

    def debug_attachment_points(self, instance_id):
        """Debug method to print attachment point calculations - CORRECTED"""
        if instance_id not in self.data_objects['sprite_instances']:
            return

        sprite_instance = self.data_objects['sprite_instances'][instance_id]
        sprite = self.data_objects['sprites'][sprite_instance.sprite_name]

        sprite_center = self.get_sprite_world_position(instance_id)  # This is actually origin, not center
        origin_world = self.get_sprite_origin_world_position(instance_id)
        endpoint_world = self.get_sprite_endpoint_world_position(instance_id)

        print(f"DEBUG {instance_id}:")
        print(f"  Sprite origin world pos: {sprite_center}")  # Renamed for clarity
        print(f"  Origin (red): {origin_world}")
        print(f"  Endpoint (blue): {endpoint_world}")
        print(f"  Sprite origin_x/y: {sprite.origin_x}, {sprite.origin_y}")
        print(f"  Sprite endpoint_x/y: {sprite.endpoint_x}, {sprite.endpoint_y}")
        print(f"  Scale: {sprite_instance.scale}")

    def draw_viewport_info_overlay(self):
        """Draw info overlay in bottom-right of viewport (like bone editor)"""
        viewport_rect = self.get_main_viewport_rect()

        # Collect overlay content
        overlay_lines = []

        # Current sprite type
        if self.selected_sprite_type:
            overlay_lines.append((f"Selected: {self.selected_sprite_type}", (255, 255, 0)))
            overlay_lines.append(("Click bones to attach", (0, 255, 0)))
        else:
            overlay_lines.append(("No sprite selected", (255, 100, 100)))
            overlay_lines.append(("Click palette to select", (200, 200, 200)))

        # Selected bone info
        selected_bones = self.get_selected_objects('bones')
        if selected_bones:
            bone_name = selected_bones[0]
            if bone_name in self.data_objects['bones']:  # Safety check
                bone = self.data_objects['bones'][bone_name]
                attached_sprites = [i for i in self.data_objects['sprite_instances'].values()
                                    if i.bone_name == bone_name]

                overlay_lines.append((f"Bone: {bone_name}", (100, 255, 100)))
                overlay_lines.append((f"  Sprites: {len(attached_sprites)}", (200, 200, 200)))

        # Selected sprite instance info
        selected_sprites = self.get_selected_objects('sprite_instances')
        if selected_sprites:
            sprite_instance_id = selected_sprites[0]
            # Safety check - ensure the sprite instance still exists
            if sprite_instance_id in self.data_objects['sprite_instances']:
                sprite_instance = self.data_objects['sprite_instances'][sprite_instance_id]

                overlay_lines.append((f"Instance: {sprite_instance_id}", (100, 100, 255)))
                overlay_lines.append((f"  Bone: {sprite_instance.bone_name or 'None'}", (200, 200, 200)))

                attachment_color = (255, 0, 0) if sprite_instance.bone_attachment_point == AttachmentPoint.END else (0,
                                                                                                                     0,
                                                                                                                     255)
                overlay_lines.append(
                    (f"  Attach: {sprite_instance.bone_attachment_point.value.upper()}", attachment_color))

                if sprite_instance.auto_adjust_bone:
                    overlay_lines.append(("  Auto-Adjust: ON", (255, 255, 0)))
            else:
                # Object was deleted but still selected - clear the selection
                self.deselect_object('sprite_instances', sprite_instance_id)

        # Project stats
        total_instances = len(self.data_objects['sprite_instances'])
        attached_instances = len([i for i in self.data_objects['sprite_instances'].values() if i.bone_name])

        overlay_lines.append((f"Instances: {attached_instances}/{total_instances}", (160, 160, 160)))
        overlay_lines.append((f"Sprites: {len(self.data_objects['sprites'])}", (160, 160, 160)))
        overlay_lines.append((f"Bones: {len(self.data_objects['bones'])}", (160, 160, 160)))

        # Calculate overlay size
        line_height = 16
        overlay_height = len(overlay_lines) * line_height + 20
        overlay_width = 280

        # Position in bottom-right of viewport
        overlay_x = viewport_rect.right - overlay_width - 10
        overlay_y = viewport_rect.bottom - overlay_height - 10

        # Draw background
        overlay_surface = pygame.Surface((overlay_width, overlay_height), pygame.SRCALPHA)
        pygame.draw.rect(overlay_surface, (0, 0, 0, 180), overlay_surface.get_rect())
        pygame.draw.rect(overlay_surface, (100, 100, 100), overlay_surface.get_rect(), 1)
        self.screen.blit(overlay_surface, (overlay_x, overlay_y))

        # Draw text lines
        y_pos = overlay_y + 10
        for text, color in overlay_lines:
            text_surface = self.small_font.render(text, True, color)
            self.screen.blit(text_surface, (overlay_x + 10, y_pos))
            y_pos += line_height

    # ========================================================================
    # SIMPLIFIED PROPERTIES PANEL
    # ========================================================================

    def draw_properties_content(self, panel_rect, y_offset):
        """Draw simplified properties panel content"""
        # Just show basic help and shortcuts
        instructions = [
            "SPRITE ATTACHMENT:",
            "",
            "CONTROLS:",
            "P: Toggle sprite palette",
            "T: Test sprite on first bone",
            "I: Create unattached sprite",
            "A: Toggle attachment point",
            "B: Toggle auto-adjust bone",
            "R: Rotate sprite 15Degrees",
            "Shift+R: Rotate sprite -15Degrees",
            "",
            "USAGE:",
            "1. Press P to show palette",
            "2. Click sprite to select",
            "3. Click bone to attach",
            "4. Drag to reposition",
            "5. Use A to change attachment",
            "6. Use B for auto bone adjust",
            "",
            "AUTO-ADJUST:",
            "When enabled (~), bones will",
            "automatically resize to match",
            "sprite's dual attachment points",
            "",
            "DUAL ATTACHMENT:",
            "Red = Origin point",
            "Blue = Endpoint",
            "Yellow line = Auto-adjust ON",
            "Orange line = Normal",
            "",
            "FILES:",
            "Ctrl+R: Reload both projects",
            "Ctrl+S: Save attachments"
        ]

        for instruction in instructions:
            if instruction:
                if instruction.endswith(":"):
                    color = (255, 0, 0)
                elif instruction.startswith("Red =") or instruction.startswith("Blue ="):
                    color = (255, 0, 0) if "Red" in instruction else (0, 0, 255)
                elif instruction.startswith("Yellow") or instruction.startswith("Orange"):
                    color = (255, 255, 0) if "Yellow" in instruction else (255, 165, 0)
                else:
                    color = (0, 0, 0)
                text = self.small_font.render(instruction, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 16

    def get_object_type_color(self, object_type: str) -> Tuple[int, int, int]:
        """Get color for object type icon"""
        colors = {
            'sprites': (255, 100, 100),
            'bones': (100, 255, 100),
            'sprite_instances': (100, 100, 255)
        }
        return colors.get(object_type, (128, 128, 128))


# Run the improved attachment editor
if __name__ == "__main__":
    editor = SpriteAttachmentEditor()
    editor.run()