import os
import math
from enum import Enum
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

import pygame

from boneless_core_base import UniversalEditor, Command


@dataclass
class SpriteRect:
    name: str
    x: int
    y: int
    width: int
    height: int
    origin_x: float = 0.5
    origin_y: float = 0.5
    endpoint_x: float = 0.5  # New endpoint for bone attachment
    endpoint_y: float = 0.5  # New endpoint for bone attachment


class ResizeHandle(Enum):
    NONE = 0
    TOP_LEFT = 1
    TOP_RIGHT = 2
    BOTTOM_LEFT = 3
    BOTTOM_RIGHT = 4
    TOP = 5
    BOTTOM = 6
    LEFT = 7
    RIGHT = 8


class SpriteSheetEditor(UniversalEditor):
    """Complete sprite sheet editor implementation with dual attachment points"""

    def __init__(self):
        super().__init__()

        # Sprite-specific state
        self.sprite_sheet = None
        self.sprite_sheet_path = ""

        # Interaction state
        self.creating_sprite = False
        self.sprite_start_pos = None
        self.temp_sprite_rect = None

        self.dragging_sprite = False
        self.dragging_origin = False
        self.dragging_endpoint = False  # New state for endpoint dragging
        self.resizing_sprite = False
        self.resize_handle = ResizeHandle.NONE
        self.drag_offset = (0, 0)

        # Try to load default sprite sheet
        self.try_load_default_sprite_sheet()
        # Try to load existing project
        self.try_auto_load()

    def setup_data_structures(self):
        """Setup sprite editor data structures"""
        self.data_objects = {
            'sprites': {}
        }

    def setup_key_bindings(self):
        """Setup sprite editor key bindings"""
        pass  # Use base class key bindings

    def get_editor_name(self) -> str:
        return "Sprite Sheet Editor v1.0"

    def try_load_default_sprite_sheet(self):
        """Try to load a default sprite sheet if available"""
        default_files = ["spritesheet.png", "texture.png", "sprites.png"]
        for filename in default_files:
            if os.path.exists(filename):
                self.load_sprite_sheet(filename)
                break

    def load_sprite_sheet(self, path: str):
        """Load a sprite sheet image"""
        try:
            self.sprite_sheet = pygame.image.load(path)
            self.sprite_sheet_path = path
            self.reset_viewport()
            print(f"Loaded sprite sheet: {path}")
            return True
        except pygame.error as e:
            print(f"Failed to load sprite sheet: {e}")
            return False

    # ========================================================================
    # HIERARCHY SYSTEM OVERRIDES
    # ========================================================================

    def build_hierarchy(self):
        """Build hierarchy from sprites"""
        self.hierarchy_nodes.clear()

        for sprite_name, sprite in self.data_objects['sprites'].items():
            self.add_hierarchy_node(
                sprite_name,
                sprite_name,
                'sprites',
                metadata={'sprite': sprite}
            )

    def get_object_type_color(self, object_type: str) -> Tuple[int, int, int]:
        """Get color for object type icon"""
        if object_type == 'sprites':
            return 255, 100, 100
        return 128, 128, 128

    def rename_object(self, object_type: str, old_name: str, new_name: str) -> bool:
        """Rename a sprite"""
        if object_type != 'sprites' or old_name not in self.data_objects['sprites']:
            return False

        sprite = self.data_objects['sprites'][old_name]
        del self.data_objects['sprites'][old_name]

        # Update sprite's name property
        sprite.name = new_name
        self.data_objects['sprites'][new_name] = sprite

        # Update selection
        selected = self.ui_state.selected_objects.get('sprites', [])
        if old_name in selected:
            selected[selected.index(old_name)] = new_name

        return True

    def get_objects_at_position(self, pos: Tuple[float, float]):
        """Get sprites at position for selection cycling"""
        objects = []
        x, y = pos

        # Check sprites in reverse order for proper layering
        for name in reversed(list(self.data_objects['sprites'].keys())):
            sprite = self.data_objects['sprites'][name]
            if (sprite.x <= x <= sprite.x + sprite.width and
                    sprite.y <= y <= sprite.y + sprite.height):
                objects.append(('sprites', name, {'type': 'body'}))

        return objects

    # ========================================================================
    # EVENT HANDLING OVERRIDES
    # ========================================================================

    def handle_keydown(self, event) -> bool:
        """Handle sprite editor specific keys"""
        if super().handle_keydown(event):
            return True

        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]

        if ctrl_pressed and event.key == pygame.K_o:
            self.open_sprite_sheet()
            return True
        elif ctrl_pressed and event.key == pygame.K_n:
            self.create_sprite_at_center()
            return True

        return False

    def handle_viewport_click(self, pos: Tuple[int, int]):
        """Handle clicks in main viewport"""
        viewport_pos = self.screen_to_viewport(pos)

        if not self.creating_sprite:
            # Check for resize handle first
            selected = self.get_first_selected('sprites')
            if selected:
                handle = self.get_resize_handle_at_position(viewport_pos)
                if handle != ResizeHandle.NONE:
                    self.start_resize_operation(handle)
                    return

            # Check for endpoint point
            clicked_sprite = self.get_sprite_at_position(viewport_pos)
            if clicked_sprite and self.is_clicking_endpoint(viewport_pos, clicked_sprite):
                self.start_endpoint_drag(clicked_sprite)
                return

            # Check for origin point
            if clicked_sprite and self.is_clicking_origin(viewport_pos, clicked_sprite):
                self.start_origin_drag(clicked_sprite)
                return

            # Handle selection with cycling
            self.handle_selection_at_position(viewport_pos, pos)

            # If we selected a sprite, start dragging it
            selected = self.get_first_selected('sprites')
            if selected and clicked_sprite == selected:
                self.start_sprite_drag(selected, viewport_pos)
            elif not clicked_sprite:
                # Start creating new sprite
                self.start_sprite_creation(viewport_pos)

    def handle_left_click_release(self, pos):
        """Handle left click release"""
        if self.creating_sprite and self.temp_sprite_rect:
            self.complete_sprite_creation()

        # Clear interaction states
        self.creating_sprite = False
        self.dragging_sprite = False
        self.dragging_origin = False
        self.dragging_endpoint = False
        self.resizing_sprite = False
        self.resize_handle = ResizeHandle.NONE

    def handle_right_click(self, pos):
        """Right click to create sprite"""
        viewport_rect = self.get_main_viewport_rect()
        if viewport_rect.collidepoint(pos):
            viewport_pos = self.screen_to_viewport(pos)
            self.create_sprite_at_position(viewport_pos)

    def handle_mouse_drag(self, pos):
        """Handle mouse dragging"""
        viewport_rect = self.get_main_viewport_rect()
        if not viewport_rect.collidepoint(pos):
            return

        viewport_pos = self.screen_to_viewport(pos)

        if self.creating_sprite:
            self.update_sprite_creation(viewport_pos)
        elif self.dragging_sprite:
            self.update_sprite_drag(viewport_pos)
        elif self.dragging_origin:
            self.update_origin_drag(viewport_pos)
        elif self.dragging_endpoint:
            self.update_endpoint_drag(viewport_pos)
        elif self.resizing_sprite:
            self.update_sprite_resize(viewport_pos)

    # ========================================================================
    # SPRITE OPERATIONS
    # ========================================================================

    def start_sprite_creation(self, pos):
        """Start creating a new sprite"""
        self.creating_sprite = True
        self.sprite_start_pos = pos
        self.clear_selection()

    def update_sprite_creation(self, pos):
        """Update sprite creation preview"""
        if not self.sprite_start_pos or not self.sprite_sheet:
            return

        x1, y1 = self.sprite_start_pos
        x2, y2 = pos

        # Calculate bounds
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)

        # Clamp to sprite sheet bounds
        sheet_w, sheet_h = self.sprite_sheet.get_size()
        x = max(0, min(x, sheet_w))
        y = max(0, min(y, sheet_h))
        w = min(w, sheet_w - x)
        h = min(h, sheet_h - y)

        self.temp_sprite_rect = (int(x), int(y), int(w), int(h))

    def complete_sprite_creation(self):
        """Complete sprite creation"""
        if not self.temp_sprite_rect:
            return

        x, y, w, h = self.temp_sprite_rect
        if w > 5 and h > 5:  # Minimum size
            self.create_sprite_with_bounds(x, y, w, h)

        self.temp_sprite_rect = None
        self.sprite_start_pos = None

    def start_sprite_drag(self, sprite_name, pos):
        """Start dragging a sprite"""
        sprite = self.data_objects['sprites'][sprite_name]
        self.drag_offset = (pos[0] - sprite.x, pos[1] - sprite.y)
        self.dragging_sprite = True
        self.operation_in_progress = True
        self.drag_start_data = {
            'type': 'move',
            'sprite_name': sprite_name,
            'old_pos': (sprite.x, sprite.y)
        }

    def update_sprite_drag(self, pos):
        """Update sprite position while dragging"""
        selected = self.get_first_selected('sprites')
        if not selected:
            return

        sprite = self.data_objects['sprites'][selected]
        new_x = pos[0] - self.drag_offset[0]
        new_y = pos[1] - self.drag_offset[1]

        # Clamp to sprite sheet bounds
        if self.sprite_sheet:
            sheet_w, sheet_h = self.sprite_sheet.get_size()
            new_x = max(0, min(new_x, sheet_w - sprite.width))
            new_y = max(0, min(new_y, sheet_h - sprite.height))

        sprite.x = int(new_x)
        sprite.y = int(new_y)

    def start_origin_drag(self, sprite_name):
        """Start dragging sprite origin"""
        self.select_object('sprites', sprite_name)
        self.dragging_origin = True
        self.operation_in_progress = True
        sprite = self.data_objects['sprites'][sprite_name]
        self.drag_start_data = {
            'type': 'origin',
            'sprite_name': sprite_name,
            'old_origin': (sprite.origin_x, sprite.origin_y)
        }

    def update_origin_drag(self, pos):
        """Update sprite origin while dragging"""
        selected = self.get_first_selected('sprites')
        if not selected:
            return

        sprite = self.data_objects['sprites'][selected]
        rel_x = (pos[0] - sprite.x) / sprite.width if sprite.width > 0 else 0.5
        rel_y = (pos[1] - sprite.y) / sprite.height if sprite.height > 0 else 0.5

        sprite.origin_x = max(0, min(1, rel_x))
        sprite.origin_y = max(0, min(1, rel_y))

    def start_endpoint_drag(self, sprite_name):
        """Start dragging sprite endpoint"""
        self.select_object('sprites', sprite_name)
        self.dragging_endpoint = True
        self.operation_in_progress = True
        sprite = self.data_objects['sprites'][sprite_name]
        self.drag_start_data = {
            'type': 'endpoint',
            'sprite_name': sprite_name,
            'old_endpoint': (sprite.endpoint_x, sprite.endpoint_y)
        }

    def update_endpoint_drag(self, pos):
        """Update sprite endpoint while dragging"""
        selected = self.get_first_selected('sprites')
        if not selected:
            return

        sprite = self.data_objects['sprites'][selected]
        rel_x = (pos[0] - sprite.x) / sprite.width if sprite.width > 0 else 0.5
        rel_y = (pos[1] - sprite.y) / sprite.height if sprite.height > 0 else 0.5

        sprite.endpoint_x = max(0, min(1, rel_x))
        sprite.endpoint_y = max(0, min(1, rel_y))

    def start_resize_operation(self, handle):
        """Start resizing a sprite"""
        selected = self.get_first_selected('sprites')
        if not selected:
            return

        self.resize_handle = handle
        self.resizing_sprite = True
        self.operation_in_progress = True
        sprite = self.data_objects['sprites'][selected]
        self.drag_start_data = {
            'type': 'resize',
            'sprite_name': selected,
            'old_bounds': (sprite.x, sprite.y, sprite.width, sprite.height)
        }

    def update_sprite_resize(self, pos):
        """Update sprite size while resizing"""
        selected = self.get_first_selected('sprites')
        if not selected or not self.drag_start_data:
            return

        sprite = self.data_objects['sprites'][selected]
        old_x, old_y, old_w, old_h = self.drag_start_data['old_bounds']

        # Calculate new bounds based on handle
        new_left = old_x
        new_top = old_y
        new_right = old_x + old_w
        new_bottom = old_y + old_h

        if self.resize_handle in [ResizeHandle.TOP_LEFT, ResizeHandle.LEFT, ResizeHandle.BOTTOM_LEFT]:
            new_left = pos[0]
        if self.resize_handle in [ResizeHandle.TOP_RIGHT, ResizeHandle.RIGHT, ResizeHandle.BOTTOM_RIGHT]:
            new_right = pos[0]
        if self.resize_handle in [ResizeHandle.TOP_LEFT, ResizeHandle.TOP, ResizeHandle.TOP_RIGHT]:
            new_top = pos[1]
        if self.resize_handle in [ResizeHandle.BOTTOM_LEFT, ResizeHandle.BOTTOM, ResizeHandle.BOTTOM_RIGHT]:
            new_bottom = pos[1]

        # Ensure minimum size
        if new_right - new_left < 5:
            if new_left != old_x:
                new_left = new_right - 5
            else:
                new_right = new_left + 5

        if new_bottom - new_top < 5:
            if new_top != old_y:
                new_top = new_bottom - 5
            else:
                new_bottom = new_top + 5

        # Clamp to sprite sheet bounds
        if self.sprite_sheet:
            sheet_w, sheet_h = self.sprite_sheet.get_size()
            new_left = max(0, min(new_left, sheet_w))
            new_top = max(0, min(new_top, sheet_h))
            new_right = max(new_left + 5, min(new_right, sheet_w))
            new_bottom = max(new_top + 5, min(new_bottom, sheet_h))

        # Apply new bounds
        sprite.x = int(new_left)
        sprite.y = int(new_top)
        sprite.width = int(new_right - new_left)
        sprite.height = int(new_bottom - new_top)

    def create_sprite_at_position(self, pos):
        """Create a sprite at the given position"""
        x, y = pos
        default_size = 50

        if self.sprite_sheet:
            sheet_w, sheet_h = self.sprite_sheet.get_size()
            x = max(0, min(x, sheet_w - default_size))
            y = max(0, min(y, sheet_h - default_size))
            w = min(default_size, sheet_w - x)
            h = min(default_size, sheet_h - y)
        else:
            w = h = default_size

        self.create_sprite_with_bounds(x, y, w, h)

    def create_sprite_at_center(self):
        """Create a sprite at the center of the viewport"""
        viewport_rect = self.get_main_viewport_rect()
        center_screen = (viewport_rect.centerx, viewport_rect.centery)
        center_viewport = self.screen_to_viewport(center_screen)
        self.create_sprite_at_position(center_viewport)

    def create_sprite_with_bounds(self, x, y, w, h):
        """Create a sprite with specific bounds"""
        sprite_name = self.get_next_object_name('sprites', 'sprite_')
        # Initialize with origin at left side, endpoint at right side by default
        new_sprite = SpriteRect(
            name=sprite_name,
            x=int(x),
            y=int(y),
            width=int(w),
            height=int(h),
            origin_x=0.0,  # Left side for bone start
            origin_y=0.5,  # Middle height
            endpoint_x=1.0,  # Right side for bone end
            endpoint_y=0.5  # Middle height
        )

        command = Command(
            action="create",
            object_type="sprites",
            object_id=sprite_name,
            old_data=None,
            new_data=new_sprite,
            description=f"Create sprite {sprite_name}"
        )

        self.execute_command(command)
        self.select_object('sprites', sprite_name)

    def create_operation_command(self):
        """Create undo command for completed operation"""
        if not self.drag_start_data:
            return

        data = self.drag_start_data
        sprite_name = data['sprite_name']
        current_sprite = self.data_objects['sprites'][sprite_name]

        if data['type'] == 'move':
            old_sprite = SpriteRect(
                name=current_sprite.name,
                x=data['old_pos'][0],
                y=data['old_pos'][1],
                width=current_sprite.width,
                height=current_sprite.height,
                origin_x=current_sprite.origin_x,
                origin_y=current_sprite.origin_y,
                endpoint_x=current_sprite.endpoint_x,
                endpoint_y=current_sprite.endpoint_y
            )
            command = Command(
                action="modify",
                object_type="sprites",
                object_id=sprite_name,
                old_data=old_sprite,
                new_data=current_sprite,
                description=f"Move {sprite_name}"
            )
        elif data['type'] == 'origin':
            old_sprite = SpriteRect(
                name=current_sprite.name,
                x=current_sprite.x,
                y=current_sprite.y,
                width=current_sprite.width,
                height=current_sprite.height,
                origin_x=data['old_origin'][0],
                origin_y=data['old_origin'][1],
                endpoint_x=current_sprite.endpoint_x,
                endpoint_y=current_sprite.endpoint_y
            )
            command = Command(
                action="modify",
                object_type="sprites",
                object_id=sprite_name,
                old_data=old_sprite,
                new_data=current_sprite,
                description=f"Change {sprite_name} origin"
            )
        elif data['type'] == 'endpoint':
            old_sprite = SpriteRect(
                name=current_sprite.name,
                x=current_sprite.x,
                y=current_sprite.y,
                width=current_sprite.width,
                height=current_sprite.height,
                origin_x=current_sprite.origin_x,
                origin_y=current_sprite.origin_y,
                endpoint_x=data['old_endpoint'][0],
                endpoint_y=data['old_endpoint'][1]
            )
            command = Command(
                action="modify",
                object_type="sprites",
                object_id=sprite_name,
                old_data=old_sprite,
                new_data=current_sprite,
                description=f"Change {sprite_name} endpoint"
            )
        elif data['type'] == 'resize':
            old_x, old_y, old_w, old_h = data['old_bounds']
            old_sprite = SpriteRect(
                name=current_sprite.name,
                x=old_x,
                y=old_y,
                width=old_w,
                height=old_h,
                origin_x=current_sprite.origin_x,
                origin_y=current_sprite.origin_y,
                endpoint_x=current_sprite.endpoint_x,
                endpoint_y=current_sprite.endpoint_y
            )
            command = Command(
                action="modify",
                object_type="sprites",
                object_id=sprite_name,
                old_data=old_sprite,
                new_data=current_sprite,
                description=f"Resize {sprite_name}"
            )
        else:
            return

        # Add to history manually
        self.command_history.append(command)
        self.redo_stack.clear()
        if len(self.command_history) > self.max_history:
            self.command_history.pop(0)

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def try_auto_load(self):
        """Try to autoload existing sprite project"""
        if os.path.exists("sprite_sheet_editor_v1.0_project.json"):
            self.load_project()

    def get_sprite_at_position(self, pos) -> Optional[str]:
        """Find sprite at given position"""
        x, y = pos
        # Check in reverse order for proper layering
        for name in reversed(list(self.data_objects['sprites'].keys())):
            sprite = self.data_objects['sprites'][name]
            if (sprite.x <= x <= sprite.x + sprite.width and
                    sprite.y <= y <= sprite.y + sprite.height):
                return name
        return None

    def is_clicking_origin(self, pos, sprite_name) -> bool:
        """Check if clicking on sprite origin"""
        sprite = self.data_objects['sprites'][sprite_name]
        origin_x = sprite.x + sprite.width * sprite.origin_x
        origin_y = sprite.y + sprite.height * sprite.origin_y

        distance = math.sqrt((pos[0] - origin_x) ** 2 + (pos[1] - origin_y) ** 2)
        hit_radius = max(5, int(6 / self.viewport.zoom))
        return distance < hit_radius

    def is_clicking_endpoint(self, pos, sprite_name) -> bool:
        """Check if clicking on sprite endpoint"""
        sprite = self.data_objects['sprites'][sprite_name]
        endpoint_x = sprite.x + sprite.width * sprite.endpoint_x
        endpoint_y = sprite.y + sprite.height * sprite.endpoint_y

        distance = math.sqrt((pos[0] - endpoint_x) ** 2 + (pos[1] - endpoint_y) ** 2)
        hit_radius = max(5, int(6 / self.viewport.zoom))
        return distance < hit_radius

    def get_resize_handle_at_position(self, pos) -> ResizeHandle:
        """Get resize handle at position"""
        selected = self.get_first_selected('sprites')
        if not selected:
            return ResizeHandle.NONE

        sprite = self.data_objects['sprites'][selected]
        handle_size = max(3, int(5 / self.viewport.zoom))

        # Check corners first
        corners = [
            (sprite.x, sprite.y, ResizeHandle.TOP_LEFT),
            (sprite.x + sprite.width, sprite.y, ResizeHandle.TOP_RIGHT),
            (sprite.x, sprite.y + sprite.height, ResizeHandle.BOTTOM_LEFT),
            (sprite.x + sprite.width, sprite.y + sprite.height, ResizeHandle.BOTTOM_RIGHT)
        ]

        for corner_x, corner_y, handle in corners:
            if abs(pos[0] - corner_x) < handle_size and abs(pos[1] - corner_y) < handle_size:
                return handle

        # Check edges
        edges = [
            (sprite.x + sprite.width / 2, sprite.y, ResizeHandle.TOP),
            (sprite.x + sprite.width / 2, sprite.y + sprite.height, ResizeHandle.BOTTOM),
            (sprite.x, sprite.y + sprite.height / 2, ResizeHandle.LEFT),
            (sprite.x + sprite.width, sprite.y + sprite.height / 2, ResizeHandle.RIGHT)
        ]

        for edge_x, edge_y, handle in edges:
            if abs(pos[0] - edge_x) < handle_size and abs(pos[1] - edge_y) < handle_size:
                return handle

        return ResizeHandle.NONE

    def open_sprite_sheet(self):
        """Try to open a sprite sheet"""
        # For demo, try common filenames
        common_files = ["spritesheet.png", "texture.png", "sprites.png", "sheet.png", "PySpineGuy.png"]
        for filename in common_files:
            if os.path.exists(filename):
                self.load_sprite_sheet(filename)
                break
        else:
            print("No sprite sheet found. Place a PNG file in the directory.")

    def delete_selected(self):
        """Delete selected sprite"""
        selected = self.get_first_selected('sprites')
        if selected:
            sprite = self.data_objects['sprites'][selected]
            command = Command(
                action="delete",
                object_type="sprites",
                object_id=selected,
                old_data=sprite,
                new_data=None,
                description=f"Delete {selected}"
            )
            self.execute_command(command)
            self.clear_selection()

    # ========================================================================
    # FILE OPERATIONS
    # ========================================================================

    def serialize_data_objects(self) -> Dict:
        """Serialize sprites for saving"""
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
        return {
            'sprites': sprites_data,
            'sprite_sheet_path': self.sprite_sheet_path
        }

    def deserialize_data_objects(self, data: Dict) -> Dict:
        """Deserialize sprites from loading"""
        result = {'sprites': {}}

        # Load sprite sheet path if available
        if 'sprite_sheet_path' in data:
            self.sprite_sheet_path = data['sprite_sheet_path']
            if os.path.exists(self.sprite_sheet_path):
                self.sprite_sheet = pygame.image.load(self.sprite_sheet_path)

        # Reconstruct SpriteRect objects
        for sprite_name, sprite_data in data.get('sprites', {}).items():
            # Handle backward compatibility - add default endpoint if missing
            if 'endpoint_x' not in sprite_data:
                sprite_data['endpoint_x'] = 1.0  # Default to right side
            if 'endpoint_y' not in sprite_data:
                sprite_data['endpoint_y'] = 0.5  # Default to middle

            result['sprites'][sprite_name] = SpriteRect(**sprite_data)

        return result

    # ========================================================================
    # DRAWING OVERRIDES
    # ========================================================================

    def draw_objects(self):
        """Draw all sprites"""
        # Draw sprite sheet background
        if self.sprite_sheet:
            sheet_pos = self.viewport_to_screen((0, 0))
            sheet_size = (
                int(self.sprite_sheet.get_width() * self.viewport.zoom),
                int(self.sprite_sheet.get_height() * self.viewport.zoom)
            )

            if sheet_size[0] > 0 and sheet_size[1] > 0:
                scaled_sheet = pygame.transform.scale(self.sprite_sheet, sheet_size)
                self.screen.blit(scaled_sheet, sheet_pos)

        # Draw sprite rectangles
        selected_sprite = self.get_first_selected('sprites')
        for name, sprite in self.data_objects['sprites'].items():
            self.draw_sprite(sprite, name == selected_sprite)

        # Draw creation preview
        if self.creating_sprite and self.temp_sprite_rect:
            self.draw_creation_preview()

    def draw_sprite(self, sprite: SpriteRect, selected: bool):
        """Draw a single sprite rectangle with dual attachment points"""
        # Draw sprite bounds
        screen_pos = self.viewport_to_screen((sprite.x, sprite.y))
        screen_size = (
            int(sprite.width * self.viewport.zoom),
            int(sprite.height * self.viewport.zoom)
        )

        color = (255, 255, 0) if selected else (255, 255, 255)
        thickness = 3 if selected else 2

        if screen_size[0] > 0 and screen_size[1] > 0:
            sprite_rect = pygame.Rect(screen_pos[0], screen_pos[1], screen_size[0], screen_size[1])
            pygame.draw.rect(self.screen, color, sprite_rect, thickness)

        # Calculate world positions for both attachment points
        origin_world = (
            sprite.x + sprite.width * sprite.origin_x,
            sprite.y + sprite.height * sprite.origin_y
        )
        endpoint_world = (
            sprite.x + sprite.width * sprite.endpoint_x,
            sprite.y + sprite.height * sprite.endpoint_y
        )

        # Convert to screen coordinates
        origin_screen = self.viewport_to_screen(origin_world)
        endpoint_screen = self.viewport_to_screen(endpoint_world)

        # Draw line connecting the two attachment points
        if selected:
            pygame.draw.line(self.screen, (255, 165, 0), origin_screen, endpoint_screen, 3)

        # Draw origin point (red circle)
        origin_size = max(3, int(4 * self.viewport.zoom))
        temp_surf = pygame.Surface((origin_size * 2, origin_size * 2), pygame.SRCALPHA)
        pygame.draw.circle(temp_surf, (255, 0, 0, 180), (origin_size, origin_size), origin_size)
        pygame.draw.circle(temp_surf, (255, 0, 0, 255), (origin_size, origin_size), int(origin_size * 0.4))
        self.screen.blit(temp_surf, (int(origin_screen[0] - origin_size), int(origin_screen[1] - origin_size)))
        pygame.draw.circle(self.screen, (255, 255, 255),
                           (int(origin_screen[0]), int(origin_screen[1])), origin_size, 1)

        # Draw endpoint point (blue circle)
        endpoint_size = max(3, int(4 * self.viewport.zoom))
        temp_surf = pygame.Surface((endpoint_size * 2, endpoint_size * 2), pygame.SRCALPHA)
        pygame.draw.circle(temp_surf, (0, 0, 255, 180), (endpoint_size, endpoint_size), endpoint_size)
        pygame.draw.circle(temp_surf, (0, 0, 255, 255), (endpoint_size, endpoint_size), int(endpoint_size * 0.4))
        self.screen.blit(temp_surf, (int(endpoint_screen[0] - endpoint_size), int(endpoint_screen[1] - endpoint_size)))
        pygame.draw.circle(self.screen, (255, 255, 255),
                           (int(endpoint_screen[0]), int(endpoint_screen[1])), endpoint_size, 1)

        # Draw labels if zoomed in enough
        if self.viewport.zoom > 0.5 and selected:
            origin_text = self.small_font.render("O", True, (255, 0, 0))
            endpoint_text = self.small_font.render("E", True, (0, 0, 255))

            origin_rect = origin_text.get_rect()
            origin_rect.center = (int(origin_screen[0]), int(origin_screen[1]))
            self.screen.blit(origin_text, origin_rect)

            endpoint_rect = endpoint_text.get_rect()
            endpoint_rect.center = (int(endpoint_screen[0]), int(endpoint_screen[1]))
            self.screen.blit(endpoint_text, endpoint_rect)

        # Draw sprite name
        if self.viewport.zoom > 0.3:
            text_color = (255, 255, 0) if selected else (255, 255, 255)
            text = self.small_font.render(sprite.name, True, text_color)
            self.screen.blit(text, (screen_pos[0], screen_pos[1] - 20))

        # Draw resize handles for selected sprite
        if selected:
            self.draw_resize_handles(sprite)

    def draw_resize_handles(self, sprite: SpriteRect):
        """Draw resize handles for selected sprite"""
        handle_size = max(2, int(2 * self.viewport.zoom))

        # Corner handles
        corners = [
            (sprite.x, sprite.y),
            (sprite.x + sprite.width, sprite.y),
            (sprite.x, sprite.y + sprite.height),
            (sprite.x + sprite.width, sprite.y + sprite.height)
        ]

        for corner_x, corner_y in corners:
            screen_pos = self.viewport_to_screen((corner_x, corner_y))
            handle_rect = pygame.Rect(
                screen_pos[0] - handle_size,
                screen_pos[1] - handle_size,
                handle_size * 2,
                handle_size * 2
            )
            temp_surf = pygame.Surface((handle_size * 2, handle_size * 2), pygame.SRCALPHA)
            pygame.draw.rect(temp_surf, (0, 255, 255, 127), temp_surf.get_rect())
            self.screen.blit(temp_surf, handle_rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255), handle_rect, 1)

        # Edge handles
        edges = [
            (sprite.x + sprite.width / 2, sprite.y),
            (sprite.x + sprite.width / 2, sprite.y + sprite.height),
            (sprite.x, sprite.y + sprite.height / 2),
            (sprite.x + sprite.width, sprite.y + sprite.height / 2)
        ]

        for edge_x, edge_y in edges:
            screen_pos = self.viewport_to_screen((edge_x, edge_y))
            handle_rect = pygame.Rect(
                screen_pos[0] - handle_size,
                screen_pos[1] - handle_size,
                handle_size * 2,
                handle_size * 2
            )
            temp_surf = pygame.Surface((handle_size * 2, handle_size * 2), pygame.SRCALPHA)
            pygame.draw.rect(temp_surf, (0, 255, 255, 127), temp_surf.get_rect())
            self.screen.blit(temp_surf, handle_rect.topleft)
            pygame.draw.rect(self.screen, (255, 255, 255), handle_rect, 1)

    def draw_creation_preview(self):
        """Draw sprite creation preview"""
        if not self.temp_sprite_rect:
            return

        x, y, w, h = self.temp_sprite_rect
        screen_pos = self.viewport_to_screen((x, y))
        screen_size = (int(w * self.viewport.zoom), int(h * self.viewport.zoom))

        if screen_size[0] > 0 and screen_size[1] > 0:
            preview_rect = pygame.Rect(screen_pos[0], screen_pos[1], screen_size[0], screen_size[1])
            pygame.draw.rect(self.screen, (0, 255, 0), preview_rect, 2)

    def draw_properties_content(self, panel_rect: pygame.Rect, y_offset: int):
        """Draw sprite editor properties panel content"""
        # Selected sprite info
        selected = self.get_first_selected('sprites')
        if selected:
            sprite = self.data_objects['sprites'][selected]

            sprite_text = self.font.render(f"Selected: {selected}", True, (0, 0, 0))
            self.screen.blit(sprite_text, (panel_rect.x + 10, y_offset))
            y_offset += 30

            info_lines = [
                f"Position: ({sprite.x}, {sprite.y})",
                f"Size: {sprite.width} x {sprite.height}",
                f"Origin: ({sprite.origin_x:.2f}, {sprite.origin_y:.2f})",
                f"Endpoint: ({sprite.endpoint_x:.2f}, {sprite.endpoint_y:.2f})"
            ]

            for line in info_lines:
                text = self.small_font.render(line, True, (0, 0, 0))
                self.screen.blit(text, (panel_rect.x + 20, y_offset))
                y_offset += 20

        y_offset += 20

        # Project stats
        stats = [
            f"Total Sprites: {len(self.data_objects['sprites'])}",
            f"Sprite Sheet: {os.path.basename(self.sprite_sheet_path) if self.sprite_sheet_path else 'None'}"
        ]

        for stat in stats:
            text = self.small_font.render(stat, True, (64, 64, 64))
            self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 20

        # Instructions
        y_offset += 20
        instructions = [
            "DUAL ATTACHMENT POINTS:",
            "Red dot (O): Origin point",
            "Blue dot (E): Endpoint",
            "Orange line: Bone span",
            "",
            "CONTROLS:",
            "Left click: Select/Create",
            "Right click: Create sprite",
            "F2: Rename selected",
            "Drag red dot: Move origin",
            "Drag blue dot: Move endpoint",
            "Drag cyan: Resize",
            "C: Cycle selection",
            "",
            "SHORTCUTS:",
            "Ctrl+O: Open sprite sheet",
            "Ctrl+N: New sprite",
            "Del: Delete selected",
            "",
            "BONE SYSTEM:",
            "Bones will span between the",
            "origin and endpoint points."
        ]

        for instruction in instructions:
            if instruction:
                if instruction.endswith(":"):
                    color = (255, 0, 0)
                elif instruction.startswith("Red dot"):
                    color = (255, 0, 0)
                elif instruction.startswith("Blue dot"):
                    color = (0, 0, 255)
                elif instruction.startswith("Orange line"):
                    color = (255, 165, 0)
                else:
                    color = (0, 0, 0)
                text = self.small_font.render(instruction, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 16


# Run the sprite editor
if __name__ == "__main__":
    editor = SpriteSheetEditor()
    editor.run()
