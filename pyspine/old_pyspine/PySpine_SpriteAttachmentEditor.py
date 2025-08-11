import pygame
import sys
import math
from typing import Dict, Tuple, Optional, List
import os

# Import from the separated editors
from configuration import *
from data_classes import Bone, SpriteRect, SpriteInstance, BoneLayer, AttachmentPoint

# Import new common modules
from viewport_common import ViewportManager
from drawing_common import draw_grid, draw_panel_background, draw_text_lines
from bone_common import (
    draw_bone, draw_bone_hierarchy_connections, get_bone_at_position, get_attachment_point_at_position
)
from sprite_common import safe_sprite_extract, draw_sprite_with_origin
from file_common import save_json_project, load_json_project, auto_load_if_exists, serialize_dataclass_dict
from event_common import BaseEventHandler

# Import undo/redo system
from undo_redo_common import UndoRedoMixin
from sprite_commands import (
    CreateSpriteInstanceCommand, DeleteSpriteInstanceCommand, MoveSpriteInstanceCommand,
    RotateSpriteInstanceCommand, AttachSpriteInstanceCommand,
    LoadSpriteProjectCommand, LoadBoneProjectCommand, LoadAttachmentConfigCommand
)

# Initialize Pygame
pygame.init()

SPRITE_ATTACHMENT_EDITOR_NAME_VERSION = "Sprite Attachment Editor v0.1"


class EnhancedSpriteInstance(SpriteInstance):
    """Enhanced sprite instance with attachment point support"""

    def __init__(self, id: str, sprite_name: str, bone_name: Optional[str] = None,
                 offset_x: float = 0.0, offset_y: float = 0.0, offset_rotation: float = 0.0,
                 scale: float = 1.0, bone_attachment_point: AttachmentPoint = AttachmentPoint.START):
        super().__init__(id, sprite_name, bone_name, offset_x, offset_y, offset_rotation, scale)
        self.bone_attachment_point = bone_attachment_point


class SpriteAttachmentProject:
    def __init__(self):
        self.sprite_sheet = None
        self.sprite_sheet_path = ""
        self.sprites: Dict[str, SpriteRect] = {}
        self.bones: Dict[str, Bone] = {}
        self.sprite_instances: Dict[str, EnhancedSpriteInstance] = {}

    def create_sprite_instance(self, sprite_name: str) -> EnhancedSpriteInstance:
        """Create a new instance of a sprite"""
        instance_id = f"{sprite_name}_{len([i for i in self.sprite_instances.values() if i.sprite_name == sprite_name]) + 1}"
        instance = EnhancedSpriteInstance(id=instance_id, sprite_name=sprite_name)
        return instance  # Don't add to dict here - let command handle it

    def attach_sprite_instance_to_bone(self, instance_id: str, bone_name: str,
                                       attachment_point: AttachmentPoint = AttachmentPoint.START):
        """Attach a sprite instance to a bone's attachment point"""
        if instance_id in self.sprite_instances and bone_name in self.bones:
            sprite_instance = self.sprite_instances[instance_id]
            sprite_instance.bone_name = bone_name
            sprite_instance.bone_attachment_point = attachment_point

            # Reset offset to attach at bone attachment point
            sprite_instance.offset_x = 0
            sprite_instance.offset_y = 0

            attachment_desc = "START" if attachment_point == AttachmentPoint.START else "END"
            print(f"Attached sprite instance {instance_id} to bone {bone_name} {attachment_desc}")

    def get_sprite_instances_for_bone(self, bone_name: str) -> List[str]:
        """Get all sprite instances attached to a specific bone"""
        return [instance_id for instance_id, instance in self.sprite_instances.items()
                if instance.bone_name == bone_name]

    def get_sprite_world_position(self, instance_id: str) -> Optional[Tuple[float, float]]:
        """Get the world position where the sprite's ORIGIN should be placed"""
        if instance_id not in self.sprite_instances:
            return None

        sprite_instance = self.sprite_instances[instance_id]
        if not sprite_instance.bone_name or sprite_instance.bone_name not in self.bones:
            return None

        bone = self.bones[sprite_instance.bone_name]

        # Determine bone attachment position
        if sprite_instance.bone_attachment_point == AttachmentPoint.END:
            attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
        else:  # START
            attach_x = bone.x
            attach_y = bone.y

        # The offset represents where the sprite's ORIGIN should be relative to the bone attachment point
        sprite_origin_x = attach_x + sprite_instance.offset_x
        sprite_origin_y = attach_y + sprite_instance.offset_y

        return sprite_origin_x, sprite_origin_y

    def load_sprite_project(self, filename: str) -> bool:
        """Load sprite project created by sprite sheet editor"""
        data = load_json_project(filename, f"Loaded sprites from sprite project")
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

            print(f"Loaded {len(self.sprites)} sprites from sprite project")
            return True
        except Exception as e:
            print(f"Error processing sprite project: {e}")
            return False

    def load_bone_project(self, filename: str) -> bool:
        """Load bone project created by bone editor with enum support"""
        data = load_json_project(filename, f"Loaded bones from bone project")
        if not data:
            return False

        try:
            # Load bones with enum support
            from file_common import deserialize_bone_data
            self.bones = {}
            for name, bone_data in data.get("bones", {}).items():
                try:
                    self.bones[name] = deserialize_bone_data(bone_data)
                except Exception as e:
                    print(f"Error loading bone {name}: {e}")
                    continue

            print(f"Loaded {len(self.bones)} bones from bone project")
            return True
        except Exception as e:
            print(f"Error processing bone project: {e}")
            return False


class SpriteAttachmentEditor(BaseEventHandler, UndoRedoMixin):
    def __init__(self):
        super().__init__()
        BaseEventHandler.__init__(self)
        UndoRedoMixin.__init__(self)

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(f"{SPRITE_ATTACHMENT_EDITOR_NAME_VERSION}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)
        self.tiny_font = pygame.font.Font(None, 14)

        self.project = SpriteAttachmentProject()

        # UI State using common viewport manager
        main_viewport_height = SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT
        initial_offset = [HIERARCHY_PANEL_WIDTH + 50, main_viewport_height // 2]
        self.viewport_manager = ViewportManager(initial_offset)
        self.palette_scroll = 0
        self.hierarchy_scroll = 0

        # Selection and interaction
        self.selected_sprite_type = None
        self.selected_sprite_instance = None
        self.selected_bone = None

        # Undo/redo specific state tracking
        self.operation_in_progress = False
        self.drag_start_offset = None
        self.drag_start_rotation = None
        self.drag_start_attachment = None

        self.dragging_sprite_instance = False

        # Hierarchy drag and drop states
        self.dragging_hierarchy_sprite = False
        self.hierarchy_drag_sprite = None
        self.hierarchy_drag_offset = (0, 0)
        self.hierarchy_drop_target = None
        self.hierarchy_drop_attachment_point = AttachmentPoint.START

        # Selection cycling system
        self.elements_at_cursor = []
        self.selection_cycle_index = 0
        self.last_click_pos = None
        self.click_tolerance = 5
        self.selection_feedback_timer = 0

        # Rotation states
        self.rotating_sprite = False
        self.rotation_start_angle = 0.0
        self.rotation_center = (0, 0)
        self.drag_offset = (0, 0)

        # Hierarchy display
        self.hierarchy_display_items: List[Tuple[str, str, int, int, int]] = []

        # Setup undo/redo key handlers
        self.setup_undo_redo_keys()

        # Setup editor-specific key handlers
        self.setup_editor_keys()

    def setup_editor_keys(self):
        """Setup sprite attachment editor specific key handlers"""
        self.key_handlers.update({
            (pygame.K_i, None): self._create_sprite_instance,
            (pygame.K_t, None): self._create_test_sprite_instance,
            (pygame.K_r, None): self._rotate_selected_sprite_15,
            (pygame.K_r, pygame.K_LSHIFT): self._rotate_selected_sprite_minus_15,
            (pygame.K_q, None): self._rotate_selected_sprite_5,
            (pygame.K_q, pygame.K_LSHIFT): self._rotate_selected_sprite_minus_5,
            (pygame.K_e, None): self._reset_sprite_rotation,
            (pygame.K_ESCAPE, None): self._deselect_all,
            (pygame.K_o, pygame.K_LCTRL): self._load_sprite_project,
            (pygame.K_p, pygame.K_LCTRL): self._load_bone_project,
            (pygame.K_n, pygame.K_LCTRL): self._create_new_sprite_instance,
            # Selection cycling and attachment point toggling
            (pygame.K_TAB, pygame.K_LSHIFT): self._cycle_selection,
            (pygame.K_c, None): self._cycle_selection,
            (pygame.K_a, None): self._toggle_sprite_attachment_point,
        })

    def _complete_current_operation(self):
        """Complete any operation that's in progress and create undo command"""
        if not self.operation_in_progress or not self.selected_sprite_instance:
            return

        if self.selected_sprite_instance not in self.project.sprite_instances:
            return

        sprite_instance = self.project.sprite_instances[self.selected_sprite_instance]

        if self.dragging_sprite_instance and self.drag_start_offset:
            # Complete move operation
            old_offset = self.drag_start_offset
            new_offset = (sprite_instance.offset_x, sprite_instance.offset_y)

            if abs(old_offset[0] - new_offset[0]) > 0.1 or abs(old_offset[1] - new_offset[1]) > 0.1:
                move_command = MoveSpriteInstanceCommand(
                    sprite_instance, old_offset, new_offset,
                    f"Move {sprite_instance.id}"
                )
                # Add command to history without executing (already performed during drag)
                self.undo_manager.undo_stack.append(move_command)
                self.undo_manager.redo_stack.clear()
                print(f"Recorded move command: {move_command}")

        elif self.rotating_sprite and self.drag_start_rotation is not None:
            # Complete rotation operation
            old_rotation = self.drag_start_rotation
            new_rotation = sprite_instance.offset_rotation

            if abs(old_rotation - new_rotation) > 0.1:
                rotate_command = RotateSpriteInstanceCommand(
                    sprite_instance, old_rotation, new_rotation,
                    f"Rotate {sprite_instance.id}"
                )
                # Add command to history without executing (already performed during drag)
                self.undo_manager.undo_stack.append(rotate_command)
                self.undo_manager.redo_stack.clear()
                print(f"Recorded rotate command: {rotate_command}")

        # Clear operation state
        self.operation_in_progress = False
        self.drag_start_offset = None
        self.drag_start_rotation = None
        self.drag_start_attachment = None

    def _cycle_selection(self):
        """Cycle through elements at the current cursor position"""
        if self.elements_at_cursor and len(self.elements_at_cursor) > 1:
            self.selection_cycle_index = (self.selection_cycle_index + 1) % len(self.elements_at_cursor)
            element_type, element_id, interaction_type = self.elements_at_cursor[self.selection_cycle_index]

            if element_type == "sprite":
                self.selected_sprite_instance = element_id
                self.selected_bone = None
            elif element_type == "bone":
                self.selected_bone = element_id
                self.selected_sprite_instance = None

            self.selection_feedback_timer = 60
            print(
                f"CYCLED to: {element_type} {element_id} [{self.selection_cycle_index + 1}/{len(self.elements_at_cursor)}]")
        else:
            print("No overlapping elements to cycle through")

    def _toggle_sprite_attachment_point(self):
        """Toggle attachment point of selected sprite using command system"""
        if self.selected_sprite_instance and self.selected_sprite_instance in self.project.sprite_instances:
            sprite_instance = self.project.sprite_instances[self.selected_sprite_instance]
            if sprite_instance.bone_name:
                old_attachment = sprite_instance.bone_attachment_point
                new_attachment = AttachmentPoint.START if old_attachment == AttachmentPoint.END else AttachmentPoint.END

                attach_command = AttachSpriteInstanceCommand(
                    sprite_instance, sprite_instance.bone_name, sprite_instance.bone_name,
                    old_attachment, new_attachment,
                    f"Toggle {sprite_instance.id} attachment point"
                )
                self.execute_command(attach_command)
            else:
                print("Selected sprite is not attached to any bone")

    def _deselect_all(self):
        """Deselect all selections"""
        self.selected_sprite_type = None
        self.selected_sprite_instance = None
        self.selected_bone = None
        self.elements_at_cursor = []
        print("Deselected all")

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.KEYDOWN:
                if self.handle_keydown(event):
                    continue

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
        elif event.button == 3:  # Right click
            self._handle_right_click(event.pos)

    def _handle_mouse_up(self, event):
        if event.button == 1:
            # Complete current operation first
            self._complete_current_operation()

            self.dragging_sprite_instance = False

            # Complete hierarchy drag operation
            if self.dragging_hierarchy_sprite:
                self._complete_hierarchy_sprite_drag(event.pos)
            self.dragging_hierarchy_sprite = False
            self.hierarchy_drag_sprite = None
            self.hierarchy_drop_target = None

        elif event.button == 2:
            self.viewport_manager.dragging_viewport = False
        elif event.button == 3:
            # Complete rotation operation
            self._complete_current_operation()
            self.rotating_sprite = False

    def _handle_mouse_motion(self, event):
        self.viewport_manager.handle_drag(event.pos)

        if self.dragging_sprite_instance and self.selected_sprite_instance:
            self._update_sprite_instance_drag(event.pos)
        elif self.rotating_sprite and self.selected_sprite_instance:
            self._update_sprite_rotation(event.pos)
        elif self.dragging_hierarchy_sprite:
            self._update_hierarchy_sprite_drag(event.pos)

        self.viewport_manager.last_mouse_pos = event.pos

    def _handle_mouse_wheel(self, event):
        mouse_x, mouse_y = pygame.mouse.get_pos()

        # Rotate selected sprite with mouse wheel
        if self.selected_sprite_instance and self._is_in_main_viewport((mouse_x, mouse_y)):
            viewport_pos = self.viewport_manager.screen_to_viewport((mouse_x, mouse_y))
            sprite_pos = self.project.get_sprite_world_position(self.selected_sprite_instance)

            if sprite_pos:
                dist = math.sqrt((viewport_pos[0] - sprite_pos[0]) ** 2 + (viewport_pos[1] - sprite_pos[1]) ** 2)
                if dist < 50:
                    rotation_amount = 15 if event.y > 0 else -15
                    self._rotate_selected_sprite(rotation_amount)
                    return

        # Normal zoom/scroll behavior
        if self._is_in_main_viewport((mouse_x, mouse_y)):
            self.viewport_manager.handle_zoom(event, (mouse_x, mouse_y))
        elif self._is_in_sprite_palette(mouse_x, mouse_y):
            self.palette_scroll -= event.y * 30
            self.palette_scroll = max(0, self.palette_scroll)
        elif mouse_x < HIERARCHY_PANEL_WIDTH:
            self.hierarchy_scroll -= event.y * 30
            self.hierarchy_scroll = max(0, self.hierarchy_scroll)

    def _handle_left_click(self, pos):
        x, y = pos

        if x < HIERARCHY_PANEL_WIDTH:
            self._handle_hierarchy_panel_click(pos)
        elif x > SCREEN_WIDTH - PROPERTY_PANEL_WIDTH:
            self._handle_property_panel_click(pos)
        elif y > SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT:
            self._handle_sprite_palette_click(pos)
        else:  # Main viewport
            self._handle_viewport_click(pos)

    def _handle_hierarchy_panel_click(self, pos):
        """Handle clicks in the hierarchy panel with drag and drop support"""
        x, y = pos

        clicked_item = None
        for item_type, item_name, item_y, indent, level in self.hierarchy_display_items:
            if abs(y - item_y) < 12:
                clicked_item = (item_type, item_name)
                break

        if clicked_item:
            item_type, item_name = clicked_item

            if item_type == "bone":
                self.selected_bone = item_name
                self.selected_sprite_instance = None
                print(f"Selected bone from hierarchy: {item_name}")

            elif item_type == "sprite":
                self.selected_sprite_instance = item_name
                self.selected_bone = None
                print(f"Selected sprite from hierarchy: {item_name}")

                # Start dragging sprite if not already dragging
                if not self.dragging_hierarchy_sprite:
                    self.dragging_hierarchy_sprite = True
                    self.hierarchy_drag_sprite = item_name
                    self.hierarchy_drag_offset = (x - 10, y - 40)
                    print(f"Started dragging sprite: {item_name}")

    def _update_hierarchy_sprite_drag(self, pos):
        """Update hierarchy sprite drag state and determine drop target"""
        if not self.dragging_hierarchy_sprite or not self.hierarchy_drag_sprite:
            return

        x, y = pos
        self.hierarchy_drop_target = None
        self.hierarchy_drop_attachment_point = AttachmentPoint.START

        # Find what we're hovering over
        for item_type, item_name, item_y, indent, level in self.hierarchy_display_items:
            if abs(y - item_y) < 12:
                if item_type == "bone" and item_name != self.hierarchy_drag_sprite:
                    self.hierarchy_drop_target = item_name

                    # Determine attachment point based on mouse position within the bone row
                    relative_x = x - (10 + indent * 20)  # Adjust for indentation
                    bone_text_width = len(f"BONE[{item_name}]") * 8  # Approximate text width

                    if relative_x < bone_text_width / 2:
                        self.hierarchy_drop_attachment_point = AttachmentPoint.START
                    else:
                        self.hierarchy_drop_attachment_point = AttachmentPoint.END
                    break

    def _complete_hierarchy_sprite_drag(self, pos):
        """Complete hierarchy sprite drag operation using command system"""
        if not self.dragging_hierarchy_sprite or not self.hierarchy_drag_sprite:
            return

        if self.hierarchy_drop_target and self.hierarchy_drag_sprite in self.project.sprite_instances:
            sprite_instance = self.project.sprite_instances[self.hierarchy_drag_sprite]
            old_bone = sprite_instance.bone_name
            old_attachment = sprite_instance.bone_attachment_point

            if old_bone != self.hierarchy_drop_target or old_attachment != self.hierarchy_drop_attachment_point:
                attach_command = AttachSpriteInstanceCommand(
                    sprite_instance, old_bone, self.hierarchy_drop_target,
                    old_attachment, self.hierarchy_drop_attachment_point,
                    f"Move {sprite_instance.id} to {self.hierarchy_drop_target}"
                )
                self.execute_command(attach_command)

                # Reset offset to attach at bone attachment point
                sprite_instance.offset_x = 0
                sprite_instance.offset_y = 0

    def _handle_right_click(self, pos):
        """Handle right click for rotation"""
        if self._is_in_main_viewport(pos):
            viewport_pos = self.viewport_manager.screen_to_viewport(pos)

            clicked_sprite_instance = self._get_sprite_instance_at_position(viewport_pos)
            if clicked_sprite_instance:
                self.selected_sprite_instance = clicked_sprite_instance
                self.rotating_sprite = True
                self.operation_in_progress = True

                # Store initial rotation for undo
                sprite_instance = self.project.sprite_instances[clicked_sprite_instance]
                self.drag_start_rotation = sprite_instance.offset_rotation

                sprite_pos = self.project.get_sprite_world_position(clicked_sprite_instance)
                if sprite_pos:
                    self.rotation_center = sprite_pos

                    dx = viewport_pos[0] - sprite_pos[0]
                    dy = viewport_pos[1] - sprite_pos[1]
                    self.rotation_start_angle = math.degrees(math.atan2(dy, dx))

    def _handle_viewport_click(self, pos):
        """Handle clicks in main viewport with enhanced selection cycling"""
        viewport_pos = self.viewport_manager.screen_to_viewport(pos)

        # Check if this is a click in the same area as the last click
        same_area = False
        if self.last_click_pos:
            dx = pos[0] - self.last_click_pos[0]
            dy = pos[1] - self.last_click_pos[1]
            if math.sqrt(dx * dx + dy * dy) < self.click_tolerance:
                same_area = True

        # Find all elements at this position
        elements_at_pos = []

        # Check for sprite instances
        sprite_at_pos = self._get_sprite_instance_at_position(viewport_pos)
        if sprite_at_pos:
            elements_at_pos.append(("sprite", sprite_at_pos, "body"))

        # Check for bones (with attachment points)
        bone_attachment = get_attachment_point_at_position(self.project.bones, viewport_pos,
                                                           self.viewport_manager.viewport_zoom, tolerance=15)
        if bone_attachment[0]:  # bone_name, attachment_point
            bone_name, attachment_point = bone_attachment
            elements_at_pos.append(("bone", bone_name, attachment_point.value))
        else:
            # Check for bone body
            bone_at_pos = get_bone_at_position(self.project.bones, viewport_pos, self.viewport_manager.viewport_zoom)
            if bone_at_pos:
                elements_at_pos.append(("bone", bone_at_pos, "body"))

        if elements_at_pos:
            if same_area and self.elements_at_cursor == elements_at_pos:
                # Same area click - cycle through elements
                self.selection_cycle_index = (self.selection_cycle_index + 1) % len(elements_at_pos)
                print(f"CYCLING: {self.selection_cycle_index + 1}/{len(elements_at_pos)} overlapping elements")
            else:
                # New area click - start fresh
                self.elements_at_cursor = elements_at_pos
                self.selection_cycle_index = 0
                if len(elements_at_pos) > 1:
                    print(f"FOUND: {len(elements_at_pos)} overlapping elements. Click again to cycle.")

            # Select the element
            element_type, element_id, interaction_type = elements_at_pos[self.selection_cycle_index]

            if element_type == "sprite":
                clicked_sprite_instance = element_id
                self.selected_sprite_instance = clicked_sprite_instance
                self.selected_bone = None
                self.dragging_sprite_instance = True
                self.operation_in_progress = True

                # Store initial offset for undo
                sprite_instance = self.project.sprite_instances[clicked_sprite_instance]
                self.drag_start_offset = (sprite_instance.offset_x, sprite_instance.offset_y)

                sprite_pos = self.project.get_sprite_world_position(clicked_sprite_instance)
                if sprite_pos:
                    self.drag_offset = (viewport_pos[0] - sprite_pos[0], viewport_pos[1] - sprite_pos[1])

                print(f"SELECTED: Sprite {element_id} [{self.selection_cycle_index + 1}/{len(elements_at_pos)}]")

            elif element_type == "bone":
                self.selected_bone = element_id
                self.selected_sprite_instance = None
                print(
                    f"SELECTED: Bone {element_id} ({interaction_type}) [{self.selection_cycle_index + 1}/{len(elements_at_pos)}]")

            self.selection_feedback_timer = 60

        else:
            # No elements at position - create sprite or deselect
            if self.selected_sprite_type:
                self._create_sprite_instance_at_position(viewport_pos)
            else:
                self.selected_sprite_instance = None
                self.selected_bone = None
                self.elements_at_cursor = []
                self.selection_cycle_index = 0

        self.last_click_pos = pos

    def _handle_sprite_palette_click(self, pos):
        """Handle clicks in sprite palette"""
        x, y = pos
        palette_y = SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT
        relative_y = y - palette_y + self.palette_scroll

        if relative_y < 25:
            return

        sprite_size = 64
        spacing = 10
        start_x = HIERARCHY_PANEL_WIDTH + 10

        adjusted_y = relative_y - 25
        adjusted_x = x - start_x

        if adjusted_x < 0:
            return

        # Calculate sprite index
        sprites_per_row = (SCREEN_WIDTH - HIERARCHY_PANEL_WIDTH - PROPERTY_PANEL_WIDTH - start_x) // (
                sprite_size + spacing)
        row = adjusted_y // (sprite_size + 20)
        col = adjusted_x // (sprite_size + spacing)

        sprite_index = int(row * sprites_per_row + col)

        sprite_names = list(self.project.sprites.keys())
        if 0 <= sprite_index < len(sprite_names):
            self.selected_sprite_type = sprite_names[sprite_index]
            print(f"Selected sprite type: {self.selected_sprite_type}")
        else:
            self.selected_sprite_type = None
            print("Deselected sprite type")

    def _handle_property_panel_click(self, pos):
        """Handle property panel clicks"""
        pass

    def update(self):
        """Update editor state"""
        if self.selection_feedback_timer > 0:
            self.selection_feedback_timer -= 1

    # Sprite manipulation methods - all using command system now
    def _rotate_selected_sprite_15(self):
        self._rotate_selected_sprite(15)

    def _rotate_selected_sprite_minus_15(self):
        self._rotate_selected_sprite(-15)

    def _rotate_selected_sprite_5(self):
        self._rotate_selected_sprite(5)

    def _rotate_selected_sprite_minus_5(self):
        self._rotate_selected_sprite(-5)

    def _rotate_selected_sprite(self, degrees: float):
        """Rotate selected sprite by given degrees using command system"""
        if self.selected_sprite_instance and self.selected_sprite_instance in self.project.sprite_instances:
            sprite_instance = self.project.sprite_instances[self.selected_sprite_instance]
            old_rotation = sprite_instance.offset_rotation
            new_rotation = (old_rotation + degrees) % 360

            rotate_command = RotateSpriteInstanceCommand(
                sprite_instance, old_rotation, new_rotation,
                f"Rotate {sprite_instance.id} by {degrees}°"
            )
            self.execute_command(rotate_command)

    def _reset_sprite_rotation(self):
        """Reset selected sprite rotation to 0 using command system"""
        if self.selected_sprite_instance and self.selected_sprite_instance in self.project.sprite_instances:
            sprite_instance = self.project.sprite_instances[self.selected_sprite_instance]
            old_rotation = sprite_instance.offset_rotation

            if abs(old_rotation) > 0.1:
                rotate_command = RotateSpriteInstanceCommand(
                    sprite_instance, old_rotation, 0.0,
                    f"Reset {sprite_instance.id} rotation"
                )
                self.execute_command(rotate_command)

    def _update_sprite_rotation(self, pos):
        """Update sprite rotation based on mouse position - direct manipulation"""
        if self.selected_sprite_instance and self.selected_sprite_instance in self.project.sprite_instances:
            sprite_instance = self.project.sprite_instances[self.selected_sprite_instance]
            viewport_pos = self.viewport_manager.screen_to_viewport(pos)

            dx = viewport_pos[0] - self.rotation_center[0]
            dy = viewport_pos[1] - self.rotation_center[1]
            current_angle = math.degrees(math.atan2(dy, dx))

            angle_delta = current_angle - self.rotation_start_angle
            sprite_instance.offset_rotation = angle_delta % 360

    def _update_sprite_instance_drag(self, pos):
        """Update sprite instance position - direct manipulation"""
        if self.selected_sprite_instance and self.selected_sprite_instance in self.project.sprite_instances:
            sprite_instance = self.project.sprite_instances[self.selected_sprite_instance]
            viewport_pos = self.viewport_manager.screen_to_viewport(pos)

            if sprite_instance.bone_name:
                bone = self.project.bones[sprite_instance.bone_name]

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

    def _get_sprite_instance_at_position(self, pos):
        """Find sprite instance at viewport position"""
        x, y = pos

        for instance_id, sprite_instance in self.project.sprite_instances.items():
            if (sprite_instance.bone_name and
                    sprite_instance.bone_name in self.project.bones and
                    sprite_instance.sprite_name in self.project.sprites):

                sprite_pos = self.project.get_sprite_world_position(instance_id)
                if not sprite_pos:
                    continue

                sprite = self.project.sprites[sprite_instance.sprite_name]
                sprite_origin_x, sprite_origin_y = sprite_pos

                # Calculate the sprite's bounding box considering origin and rotation
                sprite_width = sprite.width * sprite_instance.scale
                sprite_height = sprite.height * sprite_instance.scale

                # Calculate corners relative to origin
                origin_offset_x = sprite_width * sprite.origin_x
                origin_offset_y = sprite_height * sprite.origin_y

                # Simple bounding box check (ignoring rotation for now)
                left = sprite_origin_x - origin_offset_x
                top = sprite_origin_y - origin_offset_y
                right = left + sprite_width
                bottom = top + sprite_height

                if left <= x <= right and top <= y <= bottom:
                    return instance_id

        return None

    def _create_sprite_instance(self):
        """Create a new sprite instance using command system"""
        if self.selected_sprite_type:
            instance = self.project.create_sprite_instance(self.selected_sprite_type)

            create_command = CreateSpriteInstanceCommand(
                self.project.sprite_instances, instance,
                f"Create sprite instance {instance.id}"
            )
            self.execute_command(create_command)

            self.selected_sprite_instance = instance.id
            print(f"Created sprite instance: {instance.id}")

    def _create_test_sprite_instance(self):
        """Create sprite instance on selected bone using command system"""
        if self.selected_sprite_type and self.project.bones:
            instance = self.project.create_sprite_instance(self.selected_sprite_type)

            create_command = CreateSpriteInstanceCommand(
                self.project.sprite_instances, instance,
                f"Create test sprite instance {instance.id}"
            )
            self.execute_command(create_command)

            first_bone = list(self.project.bones.keys())[0]
            attach_command = AttachSpriteInstanceCommand(
                instance, None, first_bone, AttachmentPoint.START, AttachmentPoint.START,
                f"Attach {instance.id} to {first_bone}"
            )
            self.execute_command(attach_command)

            self.selected_sprite_instance = instance.id
            print(f"TEST: Created sprite instance {instance.id} on bone {first_bone} START")

    def _create_new_sprite_instance(self):
        """Create a new sprite instance at the center using command system"""
        center_screen = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        center_viewport = self.viewport_manager.screen_to_viewport(center_screen)
        self._create_sprite_instance_at_position(center_viewport)

    def _create_sprite_instance_at_position(self, pos):
        """Create sprite instance at specific position using command system"""
        if self.selected_sprite_type:
            # Check for attachment points first (more precise)
            bone_name, attachment_point = get_attachment_point_at_position(
                self.project.bones, pos, self.viewport_manager.viewport_zoom, tolerance=20)

            if not bone_name:
                # Fall back to bone body
                bone_name = get_bone_at_position(self.project.bones, pos, self.viewport_manager.viewport_zoom)
                attachment_point = AttachmentPoint.START

            if bone_name:
                instance = self.project.create_sprite_instance(self.selected_sprite_type)

                create_command = CreateSpriteInstanceCommand(
                    self.project.sprite_instances, instance,
                    f"Create sprite instance {instance.id}"
                )
                self.execute_command(create_command)

                attach_command = AttachSpriteInstanceCommand(
                    instance, None, bone_name, AttachmentPoint.START, attachment_point or AttachmentPoint.START,
                    f"Attach {instance.id} to {bone_name}"
                )
                self.execute_command(attach_command)

                # Set offset from attachment point
                bone = self.project.bones[bone_name]
                if attachment_point == AttachmentPoint.END:
                    attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                    attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
                else:
                    attach_x = bone.x
                    attach_y = bone.y

                instance.offset_x = pos[0] - attach_x
                instance.offset_y = pos[1] - attach_y
                self.selected_sprite_instance = instance.id

                attachment_desc = attachment_point.value if attachment_point else "START"
                print(f"Created sprite instance {instance.id} at bone {bone_name} {attachment_desc}")

    def _load_sprite_project(self):
        """Load sprite project using command system"""
        filename = "sprite_project.json"
        if os.path.exists(filename):
            load_command = LoadSpriteProjectCommand(self.project, filename)
            self.execute_command(load_command)
        else:
            print("sprite_project.json not found")

    def _load_bone_project(self):
        """Load bone project using command system"""
        filename = "bone_project.json"
        if os.path.exists(filename):
            load_command = LoadBoneProjectCommand(self.project, filename)
            self.execute_command(load_command)
            if load_command.load_success:
                self.center_viewport_on_bones()
        else:
            print("bone_project.json not found")

    @staticmethod
    def _is_in_main_viewport(pos):
        """Check if position is in main viewport"""
        x, y = pos
        main_viewport_height = SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT
        return (HIERARCHY_PANEL_WIDTH < x < SCREEN_WIDTH - PROPERTY_PANEL_WIDTH and
                0 < y < main_viewport_height)

    @staticmethod
    def _is_in_sprite_palette(x, y):
        """Check if position is in sprite palette"""
        palette_y = SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT
        return (HIERARCHY_PANEL_WIDTH < x < SCREEN_WIDTH - PROPERTY_PANEL_WIDTH and
                palette_y < y < SCREEN_HEIGHT)

    # Override base class methods
    def save_project(self):
        """Save sprite attachment configuration"""
        self.save_attachment_configuration()

    def load_project(self):
        """Load sprite attachment configuration using command system"""
        filename = "sprite_attachment_config.json"
        if os.path.exists(filename):
            load_command = LoadAttachmentConfigCommand(self, filename)
            self.execute_command(load_command)
        else:
            print("sprite_attachment_config.json not found")

    def delete_selected(self):
        """Delete selected item using command system"""
        if self.selected_sprite_instance:
            delete_command = DeleteSpriteInstanceCommand(
                self.project.sprite_instances, self.selected_sprite_instance,
                f"Delete sprite instance {self.selected_sprite_instance}"
            )
            self.execute_command(delete_command)
            self.selected_sprite_instance = None

    def reset_viewport(self):
        """Reset viewport to default"""
        main_viewport_height = SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT
        initial_offset = [HIERARCHY_PANEL_WIDTH + 50, main_viewport_height // 2]
        self.viewport_manager.reset_viewport(initial_offset)

    def draw(self):
        """Main draw function"""
        self.screen.fill(DARK_GRAY)

        self._draw_hierarchy_panel()
        self._draw_main_viewport()
        self._draw_sprite_palette()
        self._draw_property_panel()
        self._draw_ui_info()

        pygame.display.flip()

    def _draw_hierarchy_panel(self):
        """Draw bone hierarchy panel with sprite attachments and enhanced undo/redo status"""
        panel_rect = pygame.Rect(0, 0, HIERARCHY_PANEL_WIDTH, SCREEN_HEIGHT)
        draw_panel_background(self.screen, panel_rect)

        title = self.font.render("Hierarchy", True, BLACK)
        self.screen.blit(title, (10, 10))

        # Enhanced undo/redo status
        y_offset = 40
        y_offset = self._draw_undo_redo_status(panel_rect, y_offset)

        self.hierarchy_display_items.clear()
        y_offset = y_offset - self.hierarchy_scroll

        # Get root bones (bones with no parent)
        root_bones = [name for name, bone in self.project.bones.items() if bone.parent is None]

        for root_name in root_bones:
            y_offset = self._draw_bone_hierarchy_node(root_name, 10, y_offset, 0)

        # Draw drag preview
        if self.dragging_hierarchy_sprite and self.hierarchy_drag_sprite:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            if mouse_x < HIERARCHY_PANEL_WIDTH:
                # Show what we're dragging
                preview_text = self.small_font.render(f"Dragging: {self.hierarchy_drag_sprite}", True, YELLOW)
                self.screen.blit(preview_text, (mouse_x + 10, mouse_y - 10))

                # Show drop target and attachment point
                if self.hierarchy_drop_target:
                    attachment_desc = self.hierarchy_drop_attachment_point.value.upper()
                    drop_text = f"Drop on {self.hierarchy_drop_target} ({attachment_desc})"
                    drop_surface = self.small_font.render(drop_text, True, GREEN)
                    self.screen.blit(drop_surface, (mouse_x + 10, mouse_y + 10))

        # Show selection cycling info
        if len(self.elements_at_cursor) > 1:
            cycle_text = f"Cycling: {self.selection_cycle_index + 1}/{len(self.elements_at_cursor)}"
            cycle_surface = self.small_font.render(cycle_text, True, YELLOW)
            self.screen.blit(cycle_surface, (10, SCREEN_HEIGHT - 40))

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

    def _draw_bone_hierarchy_node(self, bone_name, x, y, indent):
        """Recursively draw bone hierarchy tree with attached sprites and drop indicators"""
        if bone_name not in self.project.bones or y > SCREEN_HEIGHT:
            return y

        bone = self.project.bones[bone_name]

        if 0 < y < SCREEN_HEIGHT:
            self.hierarchy_display_items.append(("bone", bone_name, y, indent, len(self._get_bone_ancestry(bone_name))))

            # Highlight selected bone
            if bone_name == self.selected_bone:
                highlight_rect = pygame.Rect(0, y - 2, HIERARCHY_PANEL_WIDTH, 22)
                pygame.draw.rect(self.screen, YELLOW, highlight_rect)

            # Highlight drop target
            if (self.dragging_hierarchy_sprite and
                    self.hierarchy_drop_target == bone_name):
                drop_color = GREEN
                drop_rect = pygame.Rect(0, y - 2, HIERARCHY_PANEL_WIDTH, 22)
                pygame.draw.rect(self.screen, drop_color, drop_rect, 3)

                # Show attachment point indicator
                attachment_desc = self.hierarchy_drop_attachment_point.value[0].upper()
                attachment_indicator = self.small_font.render(f"->{attachment_desc}", True, GREEN)
                self.screen.blit(attachment_indicator, (HIERARCHY_PANEL_WIDTH - 30, y))

            # Bone info with layer and attachment
            layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            layer_order = getattr(bone, 'layer_order', 0)

            layer_char = layer.value[0].upper()
            layer_suffix = f"[{layer_char}{layer_order}]"

            bone_text = "  " * indent + f"BONE[{bone_name}]->{layer_suffix}"
            color = BLACK if bone_name == self.selected_bone else BLUE
            text = self.small_font.render(bone_text, True, color)
            self.screen.blit(text, (x, y))

        y += 20

        # Draw attached sprites with drag indicators
        attached_sprites = self.project.get_sprite_instances_for_bone(bone_name)
        for sprite_id in attached_sprites:
            if 0 < y < SCREEN_HEIGHT:
                sprite_instance = self.project.sprite_instances[sprite_id]
                attachment_char = "E" if sprite_instance.bone_attachment_point == AttachmentPoint.END else "S"

                self.hierarchy_display_items.append(("sprite", sprite_id, y, indent + 1, 0))

                # Highlight selected sprite
                if sprite_id == self.selected_sprite_instance:
                    highlight_rect = pygame.Rect(0, y - 2, HIERARCHY_PANEL_WIDTH, 18)
                    pygame.draw.rect(self.screen, CYAN, highlight_rect)

                # Highlight dragging sprite
                if self.dragging_hierarchy_sprite and sprite_id == self.hierarchy_drag_sprite:
                    drag_rect = pygame.Rect(0, y - 2, HIERARCHY_PANEL_WIDTH, 18)
                    pygame.draw.rect(self.screen, ORANGE, drag_rect, 2)

                sprite_text = "  " * (indent + 1) + f"SPRT[{sprite_instance.sprite_name}]->{attachment_char}"
                sprite_color = BLACK if sprite_id == self.selected_sprite_instance else PURPLE

                # Gray out if being dragged
                if self.dragging_hierarchy_sprite and sprite_id == self.hierarchy_drag_sprite:
                    sprite_color = GRAY

                sprite_surface = self.tiny_font.render(sprite_text, True, sprite_color)
                self.screen.blit(sprite_surface, (x, y))

            y += 18

        # Draw children
        for child_name in bone.children:
            y = self._draw_bone_hierarchy_node(child_name, x, y, indent + 1)

        return y

    def _get_bone_ancestry(self, bone_name):
        """Get list of ancestors for a bone"""
        ancestry = []
        current = bone_name
        while current and current in self.project.bones:
            bone = self.project.bones[current]
            if bone.parent:
                ancestry.append(bone.parent)
                current = bone.parent
            else:
                break
        return ancestry

    def _draw_main_viewport(self):
        """Draw main viewport with bones and sprite instances"""
        main_viewport_height = SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT
        viewport_rect = pygame.Rect(HIERARCHY_PANEL_WIDTH, 0,
                                    SCREEN_WIDTH - HIERARCHY_PANEL_WIDTH - PROPERTY_PANEL_WIDTH,
                                    main_viewport_height)
        pygame.draw.rect(self.screen, BLACK, viewport_rect)
        self.screen.set_clip(viewport_rect)

        draw_grid(self.screen, self.viewport_manager, viewport_rect)
        self._draw_static_skeleton()
        self._draw_sprite_instances()
        self._draw_rotation_controls()
        self._draw_selection_feedback()

        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, WHITE, viewport_rect, 2)

    def _draw_selection_feedback(self):
        """Draw selection feedback for cycling"""
        if len(self.elements_at_cursor) > 1 and self.selection_feedback_timer > 0:
            # Show which element is currently selected
            element_type, element_id, interaction_type = self.elements_at_cursor[self.selection_cycle_index]

            feedback_text = f"Selected: {element_type} {element_id} ({interaction_type}) [{self.selection_cycle_index + 1}/{len(self.elements_at_cursor)}]"
            feedback_surface = self.small_font.render(feedback_text, True, YELLOW)

            # Draw with background for visibility
            text_rect = feedback_surface.get_rect()
            text_rect.topleft = (HIERARCHY_PANEL_WIDTH + 10, 10)
            pygame.draw.rect(self.screen, BLACK, text_rect.inflate(10, 5))
            self.screen.blit(feedback_surface, text_rect)

    def _draw_sprite_palette(self):
        """Draw sprite palette with updated layout"""
        palette_y = SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT
        palette_rect = pygame.Rect(HIERARCHY_PANEL_WIDTH, palette_y,
                                   SCREEN_WIDTH - HIERARCHY_PANEL_WIDTH - PROPERTY_PANEL_WIDTH,
                                   SPRITE_PALETTE_HEIGHT)
        draw_panel_background(self.screen, palette_rect, GRAY)

        title = self.small_font.render("Sprite Palette (Click to select, ESC to deselect)", True, WHITE)
        self.screen.blit(title, (HIERARCHY_PANEL_WIDTH + 10, palette_y + 5))

        if self.project.sprite_sheet:
            sprite_size = 64
            spacing = 10
            x_offset = HIERARCHY_PANEL_WIDTH + 10
            y_offset = palette_y + 25 - self.palette_scroll

            sprites_per_row = (SCREEN_WIDTH - HIERARCHY_PANEL_WIDTH - PROPERTY_PANEL_WIDTH - 20) // (
                    sprite_size + spacing)

            for i, (sprite_name, sprite) in enumerate(self.project.sprites.items()):
                row = i // sprites_per_row
                col = i % sprites_per_row

                sprite_x = x_offset + col * (sprite_size + spacing)
                sprite_y = y_offset + row * (sprite_size + 20)

                if palette_y - sprite_size < sprite_y < SCREEN_HEIGHT:
                    sprite_surface = safe_sprite_extract(self.project.sprite_sheet, sprite)
                    if sprite_surface:
                        scaled_sprite = pygame.transform.scale(sprite_surface, (sprite_size, sprite_size))

                        sprite_rect = pygame.Rect(sprite_x, sprite_y, sprite_size, sprite_size)
                        self.screen.blit(scaled_sprite, sprite_rect)

                        if sprite_name == self.selected_sprite_type:
                            pygame.draw.rect(self.screen, YELLOW, sprite_rect, 3)
                        else:
                            pygame.draw.rect(self.screen, WHITE, sprite_rect, 1)

                        name_text = self.small_font.render(sprite_name, True, WHITE)
                        self.screen.blit(name_text, (sprite_x, sprite_y + sprite_size + 2))

    def _draw_static_skeleton(self):
        """Draw static skeleton for attachment reference"""
        # Draw hierarchy connections
        draw_bone_hierarchy_connections(self.screen, self.viewport_manager, self.project.bones)

        # Draw individual bones with enhanced selection indicators
        for bone_name, bone in self.project.bones.items():
            selected = (bone_name == self.selected_bone)
            draw_bone(self.screen, self.viewport_manager, bone,
                      color=ORANGE if selected else GREEN, selected=selected, font=self.tiny_font)

            # Draw bone name with attachment info
            if self.viewport_manager.viewport_zoom > 0.4:
                start_screen = self.viewport_manager.viewport_to_screen((bone.x, bone.y))
                end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
                end_screen = self.viewport_manager.viewport_to_screen((end_x, end_y))

                mid_x = (start_screen[0] + end_screen[0]) / 2
                mid_y = (start_screen[1] + end_screen[1]) / 2

                # Show layer and attached sprite count
                layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
                layer_order = getattr(bone, 'layer_order', 0)
                sprite_count = len(self.project.get_sprite_instances_for_bone(bone_name))

                display_name = f"{bone_name}[{layer.value[0].upper()}{layer_order}]"
                if sprite_count > 0:
                    display_name += f"({sprite_count})"

                text_color = ORANGE if selected else GREEN
                text = self.small_font.render(display_name, True, text_color)
                self.screen.blit(text, (mid_x, mid_y - 15))

    def _draw_sprite_instances(self):
        """Draw sprite instances with enhanced attachment point visualization"""
        if not self.project.sprite_sheet:
            return

        # Group sprites by bone layer and sort by layer_order
        layered_sprites = {
            BoneLayer.BEHIND: [],
            BoneLayer.MIDDLE: [],
            BoneLayer.FRONT: []
        }

        for instance_id, sprite_instance in self.project.sprite_instances.items():
            if sprite_instance.bone_name and sprite_instance.bone_name in self.project.bones:
                if sprite_instance.sprite_name in self.project.sprites:
                    bone = self.project.bones[sprite_instance.bone_name]
                    bone_layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
                    bone_layer_order = getattr(bone, 'layer_order', 0)
                    layered_sprites[bone_layer].append((bone_layer_order, instance_id, sprite_instance))

        for layer in layered_sprites:
            layered_sprites[layer].sort(key=lambda x: x[0])

        # Draw sprites in layer order: BEHIND -> MIDDLE -> FRONT
        for layer in [BoneLayer.BEHIND, BoneLayer.MIDDLE, BoneLayer.FRONT]:
            for layer_order, instance_id, sprite_instance in layered_sprites[layer]:
                bone = self.project.bones[sprite_instance.bone_name]
                sprite = self.project.sprites[sprite_instance.sprite_name]

                try:
                    # Get sprite world position based on attachment point
                    sprite_pos = self.project.get_sprite_world_position(instance_id)
                    if not sprite_pos:
                        continue

                    sprite_world_x, sprite_world_y = sprite_pos

                    # Draw sprite using common function
                    sprite_rect = draw_sprite_with_origin(
                        self.screen, self.viewport_manager, self.project.sprite_sheet, sprite,
                        (sprite_world_x, sprite_world_y),
                        rotation=sprite_instance.offset_rotation,
                        scale=sprite_instance.scale,
                        selected=(instance_id == self.selected_sprite_instance)
                    )

                    if sprite_rect:
                        # Show attachment to bone attachment point
                        if sprite_instance.bone_attachment_point == AttachmentPoint.END:
                            attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                            attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
                            attachment_color = RED  # Red for END attachment
                        else:  # START
                            attach_x = bone.x
                            attach_y = bone.y
                            attachment_color = BLUE  # Blue for START attachment

                        attachment_screen = self.viewport_manager.viewport_to_screen((attach_x, attach_y))
                        sprite_screen_pos = self.viewport_manager.viewport_to_screen((sprite_world_x, sprite_world_y))

                        # Draw attachment point and connection
                        pygame.draw.circle(self.screen, attachment_color,
                                           (int(attachment_screen[0]), int(attachment_screen[1])), 4)
                        pygame.draw.line(self.screen, attachment_color, attachment_screen, sprite_screen_pos, 2)

                except pygame.error:
                    pass

    def _draw_rotation_controls(self):
        """Draw rotation controls for selected sprite"""
        if self.selected_sprite_instance and self.selected_sprite_instance in self.project.sprite_instances:
            sprite_instance = self.project.sprite_instances[self.selected_sprite_instance]

            if sprite_instance.bone_name and sprite_instance.bone_name in self.project.bones:
                sprite_pos = self.project.get_sprite_world_position(self.selected_sprite_instance)
                if sprite_pos:
                    sprite_screen_pos = self.viewport_manager.viewport_to_screen(sprite_pos)

                    radius = max(30, int(40 / self.viewport_manager.viewport_zoom))
                    pygame.draw.circle(self.screen, ORANGE,
                                       (int(sprite_screen_pos[0]), int(sprite_screen_pos[1])),
                                       radius, 2)

                    angle_rad = math.radians(sprite_instance.offset_rotation)
                    line_end_x = sprite_screen_pos[0] + radius * math.cos(angle_rad)
                    line_end_y = sprite_screen_pos[1] + radius * math.sin(angle_rad)

                    pygame.draw.line(self.screen, ORANGE,
                                     sprite_screen_pos,
                                     (int(line_end_x), int(line_end_y)), 3)

                    if abs(sprite_instance.offset_rotation) > 0.1:
                        rot_text = self.small_font.render(f"{sprite_instance.offset_rotation:.1f}°", True, ORANGE)
                        self.screen.blit(rot_text, (sprite_screen_pos[0] + radius + 10, sprite_screen_pos[1] - 10))

    def _draw_property_panel(self):
        """Draw property panel with enhanced undo/redo and drag information"""
        panel_rect = pygame.Rect(SCREEN_WIDTH - PROPERTY_PANEL_WIDTH, 0,
                                 PROPERTY_PANEL_WIDTH, SCREEN_HEIGHT)
        draw_panel_background(self.screen, panel_rect)

        y_offset = 20

        title = self.font.render("Properties", True, BLACK)
        self.screen.blit(title, (panel_rect.x + 10, y_offset))
        y_offset += 40

        # Selected sprite type
        if self.selected_sprite_type:
            sprite_type_text = self.small_font.render(f"Sprite Type: {self.selected_sprite_type}", True, BLACK)
            self.screen.blit(sprite_type_text, (panel_rect.x + 10, y_offset))
            y_offset += 20

        # Selected bone info
        if self.selected_bone:
            bone_text = self.small_font.render(f"Selected Bone: {self.selected_bone}", True, BLACK)
            self.screen.blit(bone_text, (panel_rect.x + 10, y_offset))
            y_offset += 20

            bone = self.project.bones[self.selected_bone]
            attached_sprites = self.project.get_sprite_instances_for_bone(self.selected_bone)

            bone_info = [
                f"  Layer: {getattr(bone, 'layer', BoneLayer.MIDDLE).value.upper()}",
                f"  Layer Order: {getattr(bone, 'layer_order', 0)}",
                f"  Attached Sprites: {len(attached_sprites)}"
            ]

            y_offset = draw_text_lines(self.screen, self.small_font, bone_info,
                                       (panel_rect.x + 10, y_offset), BLACK, 18)
            y_offset += 10

        # Selected sprite instance
        if self.selected_sprite_instance:
            instance_text = self.small_font.render(f"Selected Sprite: {self.selected_sprite_instance}", True, BLACK)
            self.screen.blit(instance_text, (panel_rect.x + 10, y_offset))
            y_offset += 20

            sprite_instance = self.project.sprite_instances[self.selected_sprite_instance]

            # Enhanced bone attachment info
            bone_layer_info = ""
            if sprite_instance.bone_name and sprite_instance.bone_name in self.project.bones:
                bone = self.project.bones[sprite_instance.bone_name]
                layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
                layer_order = getattr(bone, 'layer_order', 0)
                bone_layer_info = f"  Bone Layer: {layer.value.upper()}({layer_order})"

            attachment_point_info = f"  Attachment: {sprite_instance.bone_attachment_point.value.upper()}"
            attachment_color = RED if sprite_instance.bone_attachment_point == AttachmentPoint.END else BLUE

            instance_info = [
                f"  Sprite: {sprite_instance.sprite_name}",
                f"  Bone: {sprite_instance.bone_name or 'None'}",
                bone_layer_info,
                f"  Offset: ({sprite_instance.offset_x:.1f}, {sprite_instance.offset_y:.1f})",
                f"  Rotation: {sprite_instance.offset_rotation:.1f}°",
                f"  Scale: {sprite_instance.scale:.2f}"
            ]

            y_offset = draw_text_lines(self.screen, self.small_font, instance_info,
                                       (panel_rect.x + 10, y_offset), BLACK, 18)

            # Draw attachment point info with color
            attach_text = self.small_font.render(attachment_point_info, True, attachment_color)
            self.screen.blit(attach_text, (panel_rect.x + 10, y_offset))
            y_offset += 20

        # Drag and drop status
        if self.dragging_hierarchy_sprite:
            drag_info = [
                "DRAGGING SPRITE:",
                f"  Sprite: {self.hierarchy_drag_sprite}",
                f"  Target: {self.hierarchy_drop_target or 'None'}",
                f"  Attachment: {self.hierarchy_drop_attachment_point.value.upper() if self.hierarchy_drop_target else 'N/A'}"
            ]

            y_offset += 10
            drag_title = self.small_font.render("DRAGGING SPRITE:", True, ORANGE)
            self.screen.blit(drag_title, (panel_rect.x + 10, y_offset))
            y_offset += 18

            for info in drag_info[1:]:
                info_text = self.small_font.render(info, True, ORANGE)
                self.screen.blit(info_text, (panel_rect.x + 10, y_offset))
                y_offset += 16

        # Project stats
        y_offset += 20
        stats = [
            f"Sprites: {len(self.project.sprites)}",
            f"Instances: {len(self.project.sprite_instances)}",
            f"Bones: {len(self.project.bones)}"
        ]

        y_offset = draw_text_lines(self.screen, self.small_font, stats,
                                   (panel_rect.x + 10, y_offset), BLACK, 18)

        # Instructions - UPDATED with undo/redo info
        y_offset += 20
        instructions = [
            SPRITE_ATTACHMENT_EDITOR_NAME_VERSION,
            "",
            "UNDO/REDO:",
            "Ctrl+Z: Undo | Ctrl+Y: Redo",
            f"History: {len(self.undo_manager.undo_stack)} actions",
            "",
            "HIERARCHY DRAG & DROP:",
            "• Drag sprites in hierarchy",
            "• Drop on bones for reattachment",
            "• Left/Right side = START/END",
            "• Visual drop indicators",
            "",
            "CONTROLS:",
            "I: Create sprite instance",
            "ESC: Deselect all",
            "A: Toggle attachment point",
            "Shift+Tab/C: Cycle selection",
            "Drag sprite: Move on bone",
            "Right click: Rotate sprite",
            "R/Q: Rotate selected sprite",
            "E: Reset rotation",
            "",
            "VISUAL CUES:",
            "Blue line/dot = START attachment",
            "Red line/dot = END attachment",
            "Yellow highlight = Selected",
            "Orange outline = Dragging",
            "",
            "FILES:",
            "Ctrl+O: Load sprites",
            "Ctrl+P: Load bones",
            "Ctrl+S: Save attachments",
            "Ctrl+L: Load attachments",
        ]

        for instruction in instructions:
            if instruction:
                if instruction.startswith(SPRITE_ATTACHMENT_EDITOR_NAME_VERSION):
                    color = GREEN
                elif instruction.startswith("COMPLETE UNDO/REDO SYSTEM"):
                    color = CYAN
                elif instruction.startswith(
                        ("ALL OPERATIONS", "UNDO/REDO", "HIERARCHY DRAG", "CONTROLS", "VISUAL CUES", "FILES")):
                    color = RED
                elif instruction.startswith(("*", "•")):
                    color = BLUE if instruction.startswith("•") else GREEN
                elif instruction.startswith(("Ctrl+Z", "Ctrl+Y", "History")):
                    color = CYAN
                else:
                    color = BLACK
                text = self.small_font.render(instruction, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 16

    def center_viewport_on_bones(self):
        """Center viewport on all bones with appropriate zoom"""
        if not self.project.bones:
            return

        # Calculate bounding box of all bones
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')

        for bone in self.project.bones.values():
            min_x = min(min_x, bone.x)
            max_x = max(max_x, bone.x)
            min_y = min(min_y, bone.y)
            max_y = max(max_y, bone.y)

            end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
            min_x = min(min_x, end_x)
            max_x = max(max_x, end_x)
            min_y = min(min_y, end_y)
            max_y = max(max_y, end_y)

        bones_width = max_x - min_x
        bones_height = max_y - min_y
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        # Calculate viewport dimensions (account for hierarchy panel)
        viewport_width = SCREEN_WIDTH - HIERARCHY_PANEL_WIDTH - PROPERTY_PANEL_WIDTH
        viewport_height = SCREEN_HEIGHT - SPRITE_PALETTE_HEIGHT

        if bones_width > 0 and bones_height > 0:
            padding = 1.2
            zoom_x = viewport_width / (bones_width * padding)
            zoom_y = viewport_height / (bones_height * padding)
            target_zoom = min(zoom_x, zoom_y, 2.0)
            target_zoom = max(target_zoom, 0.1)
        else:
            target_zoom = 1.0

        self.viewport_manager.viewport_zoom = target_zoom
        self.viewport_manager.viewport_offset[0] = HIERARCHY_PANEL_WIDTH + viewport_width / 2 - center_x * target_zoom
        self.viewport_manager.viewport_offset[1] = viewport_height / 2 - center_y * target_zoom

        print(f"Centered viewport on {len(self.project.bones)} bones (zoom: {target_zoom:.2f})")

    def _draw_ui_info(self):
        """Draw UI information with complete undo/redo status"""
        status_lines = [
            f"{SPRITE_ATTACHMENT_EDITOR_NAME_VERSION}",
            f"Hierarchy Drag & Drop",
            f"Enhanced sprite management",
            f"Drag sprites between bones",
            ""
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
            if self.dragging_sprite_instance:
                status_lines.append("MOVING SPRITE - Release to record in history")
            elif self.rotating_sprite:
                status_lines.append("ROTATING SPRITE - Release to record in history")

        for i, line in enumerate(status_lines):
            if line.startswith(SPRITE_ATTACHMENT_EDITOR_NAME_VERSION):
                color = GREEN
            elif line.startswith("Last Action") and self.can_undo():
                color = CYAN
            elif line.startswith(("MOVING", "ROTATING")):
                color = ORANGE
            elif line.startswith("ALL OPERATIONS"):
                color = YELLOW
            elif line.startswith("*"):
                color = GREEN
            elif line == "":
                continue
            else:
                color = WHITE

            text = self.small_font.render(line, True, color)
            self.screen.blit(text, (HIERARCHY_PANEL_WIDTH + 10, 10 + i * 18))

    def load_attachment_configuration_from_data(self, data):
        """Load attachment configuration from data dict (used by command)"""
        try:
            # Load sprite sheet
            if data.get("sprite_sheet_path"):
                self.project.sprite_sheet_path = data["sprite_sheet_path"]
                if os.path.exists(self.project.sprite_sheet_path):
                    self.project.sprite_sheet = pygame.image.load(self.project.sprite_sheet_path)

            # Load sprites
            self.project.sprites = {}
            for name, sprite_data in data.get("sprites", {}).items():
                self.project.sprites[name] = SpriteRect(**sprite_data)

            # Load bones
            from file_common import deserialize_bone_data
            self.project.bones = {}
            for name, bone_data in data.get("bones", {}).items():
                try:
                    self.project.bones[name] = deserialize_bone_data(bone_data)
                except Exception as e:
                    print(f"Error loading bone {name}: {e}")
                    continue

            # Load sprite instances with attachment points
            self.project.sprite_instances = {}
            for instance_id, instance_data in data.get("sprite_instances", {}).items():
                # Handle attachment point
                attachment_point_value = instance_data.get("bone_attachment_point", "start")
                try:
                    attachment_point = AttachmentPoint(attachment_point_value)
                except ValueError:
                    attachment_point = AttachmentPoint.START

                sprite_instance = EnhancedSpriteInstance(
                    id=instance_data["id"],
                    sprite_name=instance_data["sprite_name"],
                    bone_name=instance_data.get("bone_name"),
                    offset_x=instance_data.get("offset_x", 0.0),
                    offset_y=instance_data.get("offset_y", 0.0),
                    offset_rotation=instance_data.get("offset_rotation", 0.0),
                    scale=instance_data.get("scale", 1.0),
                    bone_attachment_point=attachment_point
                )
                self.project.sprite_instances[instance_id] = sprite_instance

        except Exception as e:
            print(f"Error processing attachment configuration: {e}")
            raise

    def save_attachment_configuration(self):
        """Save sprite attachment configuration with attachment points"""
        attachment_data = {
            "sprite_sheet_path": self.project.sprite_sheet_path,
            "sprites": serialize_dataclass_dict(self.project.sprites),
            "bones": serialize_dataclass_dict(self.project.bones),
            "sprite_instances": {}
        }

        # Serialize sprite instances with attachment points
        for instance_id, sprite_instance in self.project.sprite_instances.items():
            instance_data = {
                "id": sprite_instance.id,
                "sprite_name": sprite_instance.sprite_name,
                "bone_name": sprite_instance.bone_name,
                "offset_x": sprite_instance.offset_x,
                "offset_y": sprite_instance.offset_y,
                "offset_rotation": sprite_instance.offset_rotation,
                "scale": sprite_instance.scale,
                "bone_attachment_point": sprite_instance.bone_attachment_point.value
            }
            attachment_data["sprite_instances"][instance_id] = instance_data

        save_json_project("sprite_attachment_config.json", attachment_data,
                          "Enhanced sprite attachment configuration saved successfully!")

    def load_attachment_configuration(self):
        """Load sprite attachment configuration using command system"""
        filename = "sprite_attachment_config.json"
        if os.path.exists(filename):
            load_command = LoadAttachmentConfigCommand(self, filename)
            self.execute_command(load_command)
        else:
            print("sprite_attachment_config.json not found")

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
    editor = SpriteAttachmentEditor()

    # Autoload projects if they exist (disable undo tracking during autoload)
    editor.undo_manager.disable()

    sprite_loaded = auto_load_if_exists("sprite_project.json", editor.project.load_sprite_project)
    bone_loaded = auto_load_if_exists("bone_project.json", editor.project.load_bone_project)

    if bone_loaded:
        editor.center_viewport_on_bones()

    # Re-enable undo tracking and clear history
    editor.undo_manager.enable()
    editor.clear_history()

    editor.run()
