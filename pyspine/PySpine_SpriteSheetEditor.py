import pygame
import sys
import math
from typing import Dict
from dataclasses import asdict
import os

from configuration import *
from data_classes import ResizeHandle, SpriteRect
from viewport_common import ViewportManager
from drawing_common import draw_panel_background, draw_text_lines
from file_common import save_json_project, load_json_project
from event_common import BaseEventHandler

# Import undo/redo system
from undo_redo_common import UndoRedoMixin, UndoRedoCommand
from sprite_commands import (
    CreateSpriteCommand, DeleteSpriteCommand, MoveSpriteCommand,
    ResizeSpriteCommand, ChangeOriginCommand
)

# Initialize Pygame
pygame.init()

SPRITE_EDITOR_NAME_VERSION = "Sprite Sheet Editor v0.1"


class LoadSpriteSheetCommand(UndoRedoCommand):
    """Command for loading a sprite sheet (with full state backup)"""

    def __init__(self, editor, new_path: str, description: str = ""):
        super().__init__(description or f"Load sprite sheet {os.path.basename(new_path)}")
        self.editor = editor
        self.new_path = new_path

        # Store old state
        self.old_sprite_sheet = editor.sprite_sheet
        self.old_sprite_sheet_path = editor.sprite_sheet_path
        self.old_sprites = editor.sprites.copy()
        self.old_selected_sprite = editor.selected_sprite

        # Try loading the new sprite sheet to store new state
        try:
            self.new_sprite_sheet = pygame.image.load(new_path)
            self.load_success = True
        except pygame.error:
            self.new_sprite_sheet = None
            self.load_success = False

    def execute(self) -> None:
        if self.load_success:
            self.editor.sprite_sheet = self.new_sprite_sheet
            self.editor.sprite_sheet_path = self.new_path
            # Don't clear sprites automatically - let user decide
            self.editor.selected_sprite = None
            self.editor.viewport_manager.viewport_offset = [50, TOOLBAR_HEIGHT + 50]
            print(f"Loaded sprite sheet: {self.new_path}")
        else:
            print(f"Failed to load sprite sheet: {self.new_path}")

    def undo(self) -> None:
        self.editor.sprite_sheet = self.old_sprite_sheet
        self.editor.sprite_sheet_path = self.old_sprite_sheet_path
        self.editor.sprites = self.old_sprites.copy()
        self.editor.selected_sprite = self.old_selected_sprite
        print(f"Restored previous sprite sheet state")


class ClearSpritesCommand(UndoRedoCommand):
    """Command for clearing all sprites"""

    def __init__(self, editor, description: str = "Clear all sprites"):
        super().__init__(description)
        self.editor = editor
        self.old_sprites = editor.sprites.copy()
        self.old_selected_sprite = editor.selected_sprite

    def execute(self) -> None:
        self.editor.sprites.clear()
        self.editor.selected_sprite = None
        print("Cleared all sprites")

    def undo(self) -> None:
        self.editor.sprites = self.old_sprites.copy()
        self.editor.selected_sprite = self.old_selected_sprite
        print(f"Restored {len(self.old_sprites)} sprites")


class SpriteSheetEditor(BaseEventHandler, UndoRedoMixin):
    def __init__(self):
        super().__init__()
        BaseEventHandler.__init__(self)
        UndoRedoMixin.__init__(self)

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(f"{SPRITE_EDITOR_NAME_VERSION}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        # Initialize viewport manager
        self.viewport_manager = ViewportManager([50, TOOLBAR_HEIGHT + 50])

        # State
        self.sprite_sheet = None
        self.sprite_sheet_path = ""
        self.sprites: Dict[str, SpriteRect] = {}

        self.selected_sprite = None
        self.creating_sprite = False
        self.sprite_start_pos = None

        # Enhanced sprite editing
        self.resize_handle = ResizeHandle.NONE
        self.dragging_sprite = False
        self.resizing_sprite = False
        self.dragging_origin = False
        self.drag_offset = (0, 0)

        # Undo/redo specific state tracking
        self.operation_in_progress = False
        self.drag_start_bounds = None
        self.drag_start_origin = None
        self.drag_start_position = None

        # UI state
        self.sprite_panel_scroll = 0

        # Setup undo/redo key handlers
        self.setup_undo_redo_keys()

        # Setup additional key handlers specific to sprite sheet editor
        self.key_handlers.update({
            (pygame.K_o, pygame.K_LCTRL): self._open_sprite_sheet,
            (pygame.K_n, pygame.K_LCTRL): self._create_new_sprite,
            (pygame.K_x, pygame.K_LCTRL): self._clear_all_sprites,
        })

    def load_sprite_sheet(self, path: str, use_command: bool = True):
        """Load a sprite sheet image with optional undo support"""
        if use_command:
            load_command = LoadSpriteSheetCommand(self, path)
            self.execute_command(load_command)
            return load_command.load_success
        else:
            try:
                self.sprite_sheet = pygame.image.load(path)
                self.sprite_sheet_path = path
                print(f"Loaded sprite sheet: {path}")
                self.viewport_manager.viewport_offset = [50, TOOLBAR_HEIGHT + 50]
                return True
            except pygame.error as e:
                print(f"Failed to load sprite sheet: {e}")
                return False

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.KEYDOWN:
                # Try base event handler first
                if not self.handle_keydown(event):
                    # Handle sprite editor specific keys that weren't handled by base
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
        elif event.button == 3:  # Right click
            self._handle_right_click(event.pos)

    def _handle_mouse_up(self, event):
        if event.button == 1:
            # Complete any undo-enabled operations BEFORE clearing states
            self._complete_current_operation()

            # Handle sprite creation completion
            if self.creating_sprite and hasattr(self, 'temp_sprite_rect'):
                # Create sprite when mouse is released
                x, y, w, h = self.temp_sprite_rect
                if w > 5 and h > 5:  # Minimum size
                    self._create_sprite_at_bounds(x, y, w, h)

                # Clean up
                if hasattr(self, 'temp_sprite_rect'):
                    delattr(self, 'temp_sprite_rect')

            # Clear all interaction states
            self.creating_sprite = False
            self.dragging_origin = False
            self.dragging_sprite = False
            self.resizing_sprite = False
            self.resize_handle = ResizeHandle.NONE

        elif event.button == 2:
            self.viewport_manager.dragging_viewport = False

    def _complete_current_operation(self):
        """Complete any operation that's in progress and create undo command"""
        if not self.operation_in_progress or not self.selected_sprite:
            return

        sprite = self.sprites[self.selected_sprite]

        if self.resizing_sprite and self.drag_start_bounds:
            # Complete resize operation
            old_bounds = self.drag_start_bounds
            new_bounds = (sprite.x, sprite.y, sprite.width, sprite.height)

            if old_bounds != new_bounds:
                resize_command = ResizeSpriteCommand(
                    sprite, old_bounds, new_bounds,
                    f"Resize {sprite.name}"
                )
                # Add command to history without executing (already performed during drag)
                self.undo_manager.undo_stack.append(resize_command)
                self.undo_manager.redo_stack.clear()  # Clear redo stack after new action
                print(f"Recorded resize command: {resize_command}")

        elif self.dragging_sprite and self.drag_start_position:
            # Complete move operation
            old_pos = self.drag_start_position
            new_pos = (sprite.x, sprite.y)

            if old_pos != new_pos:
                move_command = MoveSpriteCommand(
                    sprite, old_pos, new_pos,
                    f"Move {sprite.name}"
                )
                # Add command to history without executing (already performed during drag)
                self.undo_manager.undo_stack.append(move_command)
                self.undo_manager.redo_stack.clear()  # Clear redo stack after new action
                print(f"Recorded move command: {move_command}")

        elif self.dragging_origin and self.drag_start_origin:
            # Complete origin change operation
            old_origin = self.drag_start_origin
            new_origin = (sprite.origin_x, sprite.origin_y)

            if old_origin != new_origin:
                origin_command = ChangeOriginCommand(
                    sprite, old_origin, new_origin,
                    f"Change {sprite.name} origin"
                )
                # Add command to history without executing (already performed during drag)
                self.undo_manager.undo_stack.append(origin_command)
                self.undo_manager.redo_stack.clear()  # Clear redo stack after new action
                print(f"Recorded origin change command: {origin_command}")

        # Clear operation state
        self.operation_in_progress = False
        self.drag_start_bounds = None
        self.drag_start_position = None
        self.drag_start_origin = None

    def _handle_mouse_motion(self, event):
        # Handle viewport dragging
        self.viewport_manager.handle_drag(event.pos)

        if self.creating_sprite and self.sprite_start_pos:
            self._update_sprite_creation(event.pos)

        elif self.dragging_origin and self.selected_sprite:
            self._update_origin_drag(event.pos)

        elif self.resizing_sprite and self.selected_sprite:
            self._update_sprite_resize(event.pos)

        elif self.dragging_sprite and self.selected_sprite:
            self._update_sprite_drag(event.pos)

        self.viewport_manager.last_mouse_pos = event.pos

    def _handle_mouse_wheel(self, event):
        mouse_x, mouse_y = pygame.mouse.get_pos()
        if self._is_in_main_viewport(mouse_x, mouse_y):
            # Use viewport manager for zooming
            self.viewport_manager.handle_zoom(event, (mouse_x, mouse_y))
        elif mouse_x > SCREEN_WIDTH - SPRITE_PANEL_WIDTH:
            # Scroll sprite panel
            self.sprite_panel_scroll -= event.y * 30
            self.sprite_panel_scroll = max(0, self.sprite_panel_scroll)

    def _handle_left_click(self, pos):
        x, y = pos

        # Check UI panels first
        if x > SCREEN_WIDTH - SPRITE_PANEL_WIDTH:  # Sprite panel
            self._handle_sprite_panel_click(pos)
        elif y < TOOLBAR_HEIGHT:  # Toolbar
            self._handle_toolbar_click(pos)
        else:  # Main viewport
            self._handle_viewport_click(pos)

    def _handle_right_click(self, pos):
        """Right click to create new sprite using command system"""
        if self._is_in_main_viewport(pos[0], pos[1]):
            viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)
            self._create_sprite_at_position(viewport_pos)

    def _handle_viewport_click(self, pos):
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

        if not self.creating_sprite:
            # Check if clicking on selected sprite's resize handles first
            if self.selected_sprite:
                handle = self._get_resize_handle_at_position(viewport_pos)
                if handle != ResizeHandle.NONE:
                    self.resize_handle = handle
                    self.resizing_sprite = True
                    self.operation_in_progress = True

                    # Store initial bounds for undo
                    sprite = self.sprites[self.selected_sprite]
                    self.drag_start_bounds = (sprite.x, sprite.y, sprite.width, sprite.height)
                    return

            # Check if clicking on origin (more generous hit area)
            clicked_sprite = self._get_sprite_at_position(viewport_pos)
            if clicked_sprite and self._is_clicking_origin(viewport_pos, clicked_sprite):
                self.selected_sprite = clicked_sprite
                self.dragging_origin = True
                self.operation_in_progress = True

                # Store initial origin for undo
                sprite = self.sprites[clicked_sprite]
                self.drag_start_origin = (sprite.origin_x, sprite.origin_y)
                return

            # Check if clicking on sprite body
            if clicked_sprite:
                self.selected_sprite = clicked_sprite
                sprite = self.sprites[clicked_sprite]
                self.drag_offset = (viewport_pos[0] - sprite.x, viewport_pos[1] - sprite.y)
                self.dragging_sprite = True
                self.operation_in_progress = True

                # Store initial position for undo
                self.drag_start_position = (sprite.x, sprite.y)
            else:
                # Start creating new sprite
                self.creating_sprite = True
                self.sprite_start_pos = viewport_pos
                self.selected_sprite = None

    def _handle_sprite_panel_click(self, pos):
        """Handle clicks in the sprite panel"""
        x, y = pos
        adjusted_y = y - TOOLBAR_HEIGHT - 40 + self.sprite_panel_scroll
        sprite_index = adjusted_y // SPRITE_WIDTH

        sprite_names = list(self.sprites.keys())
        if 0 <= sprite_index < len(sprite_names):
            sprite_name = sprite_names[sprite_index]
            self.selected_sprite = sprite_name
            print(f"Selected sprite: {sprite_name}")

    def _handle_toolbar_click(self, pos):
        """Handle toolbar button clicks"""
        pass

    def _get_resize_handle_at_position(self, pos):
        """Check if position is over a resize handle of the selected sprite"""
        if not self.selected_sprite or self.selected_sprite not in self.sprites:
            return ResizeHandle.NONE

        sprite = self.sprites[self.selected_sprite]
        handle_size = max(2, int(3 / self.viewport_manager.viewport_zoom))

        # Check corners first (they have priority)
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

    def _update_sprite_creation(self, pos):
        if self.sprite_start_pos and self.sprite_sheet:
            viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

            # Calculate sprite rectangle
            x1, y1 = self.sprite_start_pos
            x2, y2 = viewport_pos

            # Ensure positive dimensions
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

            # Store the current dimensions but don't create sprite yet
            self.temp_sprite_rect = (int(x), int(y), int(w), int(h))

    def _update_sprite_resize(self, pos):
        """Update sprite dimensions while resizing - direct manipulation for responsiveness"""
        if not self.selected_sprite or self.selected_sprite not in self.sprites:
            return

        if not self.drag_start_bounds:
            return

        sprite = self.sprites[self.selected_sprite]
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

        # Use the bounds from when resize started
        original_left, original_top, original_width, original_height = self.drag_start_bounds
        original_right = original_left + original_width
        original_bottom = original_top + original_height

        # Start with original bounds
        new_left = original_left
        new_top = original_top
        new_right = original_right
        new_bottom = original_bottom

        # Apply changes based on handle type
        if self.resize_handle == ResizeHandle.TOP_LEFT:
            new_left = viewport_pos[0]
            new_top = viewport_pos[1]

        elif self.resize_handle == ResizeHandle.TOP_RIGHT:
            new_right = viewport_pos[0]
            new_top = viewport_pos[1]

        elif self.resize_handle == ResizeHandle.BOTTOM_LEFT:
            new_left = viewport_pos[0]
            new_bottom = viewport_pos[1]

        elif self.resize_handle == ResizeHandle.BOTTOM_RIGHT:
            new_right = viewport_pos[0]
            new_bottom = viewport_pos[1]

        elif self.resize_handle == ResizeHandle.TOP:
            new_top = viewport_pos[1]

        elif self.resize_handle == ResizeHandle.BOTTOM:
            new_bottom = viewport_pos[1]

        elif self.resize_handle == ResizeHandle.LEFT:
            new_left = viewport_pos[0]

        elif self.resize_handle == ResizeHandle.RIGHT:
            new_right = viewport_pos[0]

        # Ensure minimum size (5 pixels)
        if new_right - new_left < 5:
            if self.resize_handle in [ResizeHandle.LEFT, ResizeHandle.TOP_LEFT, ResizeHandle.BOTTOM_LEFT]:
                new_left = new_right - 5
            else:
                new_right = new_left + 5

        if new_bottom - new_top < 5:
            if self.resize_handle in [ResizeHandle.TOP, ResizeHandle.TOP_LEFT, ResizeHandle.TOP_RIGHT]:
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

        # Apply the new bounds directly (command will be created on mouse up)
        sprite.x = int(new_left)
        sprite.y = int(new_top)
        sprite.width = int(new_right - new_left)
        sprite.height = int(new_bottom - new_top)

    def _update_sprite_drag(self, pos):
        """Update sprite position while dragging - direct manipulation for responsiveness"""
        if not self.selected_sprite or self.selected_sprite not in self.sprites:
            return

        sprite = self.sprites[self.selected_sprite]
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

        new_x = viewport_pos[0] - self.drag_offset[0]
        new_y = viewport_pos[1] - self.drag_offset[1]

        # Clamp to sprite sheet bounds
        if self.sprite_sheet:
            sheet_w, sheet_h = self.sprite_sheet.get_size()
            new_x = max(0, min(new_x, sheet_w - sprite.width))
            new_y = max(0, min(new_y, sheet_h - sprite.height))

        # Apply directly (command will be created on mouse up)
        sprite.x = int(new_x)
        sprite.y = int(new_y)

    def _update_origin_drag(self, pos):
        """Update sprite origin while dragging - direct manipulation for responsiveness"""
        if self.selected_sprite and self.selected_sprite in self.sprites:
            sprite = self.sprites[self.selected_sprite]
            viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

            # Calculate relative position within sprite
            rel_x = (viewport_pos[0] - sprite.x) / sprite.width if sprite.width > 0 else 0.5
            rel_y = (viewport_pos[1] - sprite.y) / sprite.height if sprite.height > 0 else 0.5

            # Clamp to 0-1 range and apply directly (command will be created on mouse up)
            sprite.origin_x = max(0, min(1, rel_x))
            sprite.origin_y = max(0, min(1, rel_y))

    def _create_sprite_at_bounds(self, x, y, w, h):
        """Create sprite with given bounds using command system"""
        sprite_name = self._get_next_sprite_name()
        new_sprite = SpriteRect(sprite_name, int(x), int(y), int(w), int(h))

        create_command = CreateSpriteCommand(self.sprites, new_sprite)
        self.execute_command(create_command)

        self.selected_sprite = sprite_name
        print(f"Created sprite: {sprite_name}")

    def _create_sprite_at_position(self, pos):
        """Create a new sprite at the given position using command system"""
        x, y = pos
        default_size = 50

        # Clamp to sprite sheet bounds if loaded
        if self.sprite_sheet:
            sheet_w, sheet_h = self.sprite_sheet.get_size()
            x = max(0, min(x, sheet_w - default_size))
            y = max(0, min(y, sheet_h - default_size))
            w = min(default_size, sheet_w - x)
            h = min(default_size, sheet_h - y)
        else:
            w = h = default_size

        self._create_sprite_at_bounds(x, y, w, h)

    def _create_new_sprite(self):
        """Create a new sprite at the center of the viewport using command system"""
        center_screen = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        center_viewport = self.viewport_manager.screen_to_viewport(center_screen, TOOLBAR_HEIGHT)
        self._create_sprite_at_position(center_viewport)

    def _clear_all_sprites(self):
        """Clear all sprites using command system"""
        if self.sprites:
            clear_command = ClearSpritesCommand(self)
            self.execute_command(clear_command)

    @staticmethod
    def _is_in_main_viewport(x, y):
        return (0 < x < SCREEN_WIDTH - SPRITE_PANEL_WIDTH and
                TOOLBAR_HEIGHT < y < SCREEN_HEIGHT)

    def _get_sprite_at_position(self, pos):
        """Find sprite at given viewport position"""
        x, y = pos
        # Check in reverse order so top sprites are selected first
        for name in reversed(list(self.sprites.keys())):
            sprite = self.sprites[name]
            if (sprite.x <= x <= sprite.x + sprite.width and
                    sprite.y <= y <= sprite.y + sprite.height):
                return name
        return None

    def _is_clicking_origin(self, pos, sprite_name):
        """Check if clicking on sprite origin point"""
        if sprite_name not in self.sprites:
            return False

        sprite = self.sprites[sprite_name]
        origin_x = sprite.x + sprite.width * sprite.origin_x
        origin_y = sprite.y + sprite.height * sprite.origin_y

        distance = math.sqrt((pos[0] - origin_x) ** 2 + (pos[1] - origin_y) ** 2)
        hit_radius = max(5, int(6 / self.viewport_manager.viewport_zoom))
        return distance < hit_radius

    def _open_sprite_sheet(self):
        """Open file dialog to load sprite sheet"""
        # For demo, try to load some common filenames
        common_files = ["GIJoe_FigurineParts.png", "spritesheet.png", "texture.png"]
        for filename in common_files:
            if os.path.exists(filename):
                self.load_sprite_sheet(filename)
                break
        else:
            print("No sprite sheet found. Place a PNG file in the directory and use Ctrl+O")

    def _get_next_sprite_name(self):
        """Find the next available sprite name"""
        base_name = "sprite_"
        existing_numbers = []

        for name in self.sprites.keys():
            if name.startswith(base_name):
                try:
                    number_part = name[len(base_name):]
                    number = int(number_part)
                    existing_numbers.append(number)
                except ValueError:
                    continue

        if not existing_numbers:
            return f"{base_name}1"

        existing_numbers.sort()
        next_number = 1

        for num in existing_numbers:
            if num == next_number:
                next_number += 1
            elif num > next_number:
                break

        return f"{base_name}{next_number}"

    # Override base class methods
    def save_project(self):
        """Save the current project"""
        project_data = {
            "sprite_sheet_path": self.sprite_sheet_path,
            "sprites": {name: asdict(sprite) for name, sprite in self.sprites.items()}
        }
        save_json_project("sprite_project.json", project_data, "Sprite project saved successfully!")

    def load_project(self):
        """Load a project"""
        project_data = load_json_project("sprite_project.json", "Sprite project loaded successfully!")
        if project_data:
            # Disable undo tracking during load
            self.undo_manager.disable()

            # Load sprite sheet
            if project_data.get("sprite_sheet_path"):
                self.load_sprite_sheet(project_data["sprite_sheet_path"], use_command=False)

            # Load sprites
            self.sprites = {}
            for name, sprite_data in project_data.get("sprites", {}).items():
                self.sprites[name] = SpriteRect(**sprite_data)

            # Re-enable undo tracking and clear history
            self.undo_manager.enable()
            self.clear_history()

    def delete_selected(self):
        """Delete selected sprite using command system"""
        if self.selected_sprite:
            delete_command = DeleteSpriteCommand(self.sprites, self.selected_sprite)
            self.execute_command(delete_command)
            self.selected_sprite = None

    def reset_viewport(self):
        """Reset viewport to default position and zoom"""
        self.viewport_manager.reset_viewport([50, TOOLBAR_HEIGHT + 50])

    def draw(self):
        self.screen.fill(DARK_GRAY)

        self._draw_main_viewport()
        self._draw_sprite_panel()
        self._draw_toolbar()
        self._draw_ui_info()

        pygame.display.flip()

    def _draw_main_viewport(self):
        """Draw main viewport"""
        viewport_rect = pygame.Rect(0, TOOLBAR_HEIGHT,
                                    SCREEN_WIDTH - SPRITE_PANEL_WIDTH,
                                    SCREEN_HEIGHT - TOOLBAR_HEIGHT)
        pygame.draw.rect(self.screen, BLACK, viewport_rect)
        self.screen.set_clip(viewport_rect)

        # Draw sprite sheet if loaded
        if self.sprite_sheet:
            sheet_pos = self.viewport_manager.viewport_to_screen((0, 0), TOOLBAR_HEIGHT)
            sheet_size = (
                self.sprite_sheet.get_width() * self.viewport_manager.viewport_zoom,
                self.sprite_sheet.get_height() * self.viewport_manager.viewport_zoom
            )

            scaled_sheet = pygame.transform.scale(self.sprite_sheet,
                                                  (int(sheet_size[0]), int(sheet_size[1])))
            self.screen.blit(scaled_sheet, sheet_pos)

        # Draw sprites
        self._draw_sprites()

        # Draw creation guides
        self._draw_creation_guides()

        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, WHITE, viewport_rect, 2)

    def _draw_sprites(self):
        """Draw sprite rectangles, origins, and resize handles"""
        for name, sprite in self.sprites.items():
            # Convert to screen coordinates
            screen_pos = self.viewport_manager.viewport_to_screen((sprite.x, sprite.y), TOOLBAR_HEIGHT)
            screen_size = (sprite.width * self.viewport_manager.viewport_zoom,
                           sprite.height * self.viewport_manager.viewport_zoom)

            # Draw sprite rectangle
            is_selected = name == self.selected_sprite
            color = YELLOW if is_selected else WHITE
            thickness = 3 if is_selected else 2

            sprite_rect = pygame.Rect(screen_pos[0], screen_pos[1], screen_size[0], screen_size[1])
            pygame.draw.rect(self.screen, color, sprite_rect, thickness)

            # Draw origin point
            origin_screen = self.viewport_manager.viewport_to_screen((
                sprite.x + sprite.width * sprite.origin_x,
                sprite.y + sprite.height * sprite.origin_y
            ), TOOLBAR_HEIGHT)

            # Draw larger, more visible origin point
            origin_size = max(2, int(2 * self.viewport_manager.viewport_zoom))
            pygame.draw.circle(self.screen, RED, (int(origin_screen[0]), int(origin_screen[1])), origin_size)
            pygame.draw.circle(self.screen, WHITE, (int(origin_screen[0]), int(origin_screen[1])), origin_size, 2)

            # Draw sprite name
            if self.viewport_manager.viewport_zoom > 0.3:
                text_color = YELLOW if is_selected else WHITE
                text = self.small_font.render(name, True, text_color)
                self.screen.blit(text, (screen_pos[0], screen_pos[1] - 20))

            # Draw resize handles for selected sprite
            if is_selected:
                self._draw_resize_handles(sprite)

    def _draw_resize_handles(self, sprite):
        """Draw resize handles for the selected sprite"""
        handle_size = max(2, int(3 * self.viewport_manager.viewport_zoom))

        # Corner handles
        corners = [
            (sprite.x, sprite.y),
            (sprite.x + sprite.width, sprite.y),
            (sprite.x, sprite.y + sprite.height),
            (sprite.x + sprite.width, sprite.y + sprite.height)
        ]

        for corner_x, corner_y in corners:
            screen_pos = self.viewport_manager.viewport_to_screen((corner_x, corner_y), TOOLBAR_HEIGHT)
            pygame.draw.rect(self.screen, CYAN,
                             (screen_pos[0] - handle_size // 2, screen_pos[1] - handle_size // 2,
                              handle_size, handle_size))

        # Edge handles
        edges = [
            (sprite.x + sprite.width / 2, sprite.y),
            (sprite.x + sprite.width / 2, sprite.y + sprite.height),
            (sprite.x, sprite.y + sprite.height / 2),
            (sprite.x + sprite.width, sprite.y + sprite.height / 2)
        ]

        for edge_x, edge_y in edges:
            screen_pos = self.viewport_manager.viewport_to_screen((edge_x, edge_y), TOOLBAR_HEIGHT)
            pygame.draw.rect(self.screen, CYAN,
                             (screen_pos[0] - handle_size // 2, screen_pos[1] - handle_size // 2,
                              handle_size, handle_size))

    def _draw_creation_guides(self):
        """Draw guides for sprite creation"""
        if self.creating_sprite and self.sprite_start_pos:
            mouse_pos = pygame.mouse.get_pos()
            if self._is_in_main_viewport(mouse_pos[0], mouse_pos[1]):
                start_screen = self.viewport_manager.viewport_to_screen(self.sprite_start_pos, TOOLBAR_HEIGHT)

                # If we have temp_sprite_rect, use it for more accurate preview
                if hasattr(self, 'temp_sprite_rect'):
                    x, y, w, h = self.temp_sprite_rect
                    rect_screen_pos = self.viewport_manager.viewport_to_screen((x, y), TOOLBAR_HEIGHT)
                    rect_screen_size = (w * self.viewport_manager.viewport_zoom,
                                        h * self.viewport_manager.viewport_zoom)
                    pygame.draw.rect(self.screen, YELLOW,
                                     (rect_screen_pos[0], rect_screen_pos[1],
                                      rect_screen_size[0], rect_screen_size[1]), 2)
                else:
                    # Fallback to simple line
                    pygame.draw.line(self.screen, GREEN, start_screen, mouse_pos, 3)

    def _draw_sprite_panel(self):
        """Draw sprite list panel with undo/redo status"""
        panel_rect = pygame.Rect(SCREEN_WIDTH - SPRITE_PANEL_WIDTH, TOOLBAR_HEIGHT,
                                 SPRITE_PANEL_WIDTH, SCREEN_HEIGHT - TOOLBAR_HEIGHT)
        draw_panel_background(self.screen, panel_rect)

        # Title
        title = self.font.render("Sprites", True, BLACK)
        self.screen.blit(title, (panel_rect.x + 10, TOOLBAR_HEIGHT + 10))

        # Enhanced undo/redo status
        y_offset = TOOLBAR_HEIGHT + 40
        y_offset = self._draw_undo_redo_status(panel_rect, y_offset)

        # Draw sprite list
        y_offset = y_offset - self.sprite_panel_scroll
        for name, sprite in self.sprites.items():
            if TOOLBAR_HEIGHT < y_offset < SCREEN_HEIGHT:
                # Highlight selected sprite
                if name == self.selected_sprite:
                    highlight_rect = pygame.Rect(panel_rect.x, y_offset - 2,
                                                 SPRITE_PANEL_WIDTH, 55)
                    pygame.draw.rect(self.screen, YELLOW, highlight_rect)
                    pygame.draw.rect(self.screen, BLACK, highlight_rect, 2)

                color = BLACK if name == self.selected_sprite else BLUE
                text = self.font.render(name, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))

                # Show sprite info
                info_lines = [
                    f"  {sprite.width}x{sprite.height} at ({sprite.x},{sprite.y})",
                    f"  Origin: ({sprite.origin_x:.2f}, {sprite.origin_y:.2f})"
                ]

                for i, info_line in enumerate(info_lines):
                    info = self.small_font.render(info_line, True, GRAY)
                    self.screen.blit(info, (panel_rect.x + 10, y_offset + 20 + i * 15))

            y_offset += 60

    def _draw_undo_redo_status(self, panel_rect, y_offset):
        """Draw undo/redo status information with more detail"""
        # Undo status
        if self.can_undo():
            undo_color = BLACK
            last_action = str(self.undo_manager.undo_stack[-1])
            if len(last_action) > 25:
                last_action = last_action[:22] + "..."
            undo_text = f"Undo: {last_action}"
        else:
            undo_color = GRAY
            undo_text = "Undo: No actions"

        # Redo status
        if self.can_redo():
            redo_color = BLACK
            next_action = str(self.undo_manager.redo_stack[-1])
            if len(next_action) > 25:
                next_action = next_action[:22] + "..."
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

    def _draw_toolbar(self):
        """Draw toolbar with shortcuts"""
        toolbar_rect = pygame.Rect(0, 0, SCREEN_WIDTH, TOOLBAR_HEIGHT)
        draw_panel_background(self.screen, toolbar_rect, GRAY, WHITE)

        # Enhanced toolbar with complete undo/redo info
        toolbar_lines = [
            "COMPLETE UNDO/REDO: Ctrl+O: Open | Ctrl+S: Save | Ctrl+L: Load | Ctrl+N: New | DEL: Delete | Ctrl+X: Clear",
            "ALL UNDOABLE: Right Click: Create | Drag Red Dot: Origin | Drag Cyan: Resize | Drag Sprite: Move | Ctrl+Z: Undo | Ctrl+Y: Redo"
        ]

        draw_text_lines(self.screen, self.small_font, toolbar_lines, (10, 10), WHITE, 20)

    def _draw_ui_info(self):
        """Draw UI information with complete undo/redo status"""
        info_lines = [
            f"{SPRITE_EDITOR_NAME_VERSION}",
            f"Zoom: {self.viewport_manager.viewport_zoom:.1f}x",
            f"Sprites: {len(self.sprites)}",
            f"Selected: {self.selected_sprite or 'None'}",
            ""
        ]

        # undo/redo status
        if self.can_undo():
            last_action = str(self.undo_manager.undo_stack[-1])
            if len(last_action) > 40:
                last_action = last_action[:37] + "..."
            info_lines.extend([
                f"Last Action: {last_action}",
                f"Undo Stack: {len(self.undo_manager.undo_stack)} | Redo Stack: {len(self.undo_manager.redo_stack)}"
            ])
        else:
            info_lines.extend([
                "No actions to undo",
                f"History: {len(self.undo_manager.undo_stack)} actions (max: {self.undo_manager.history_limit})"
            ])

        # Add operation status
        if self.operation_in_progress:
            if self.resizing_sprite:
                info_lines.append("RESIZING - Release to record in history")
            elif self.dragging_sprite:
                info_lines.append("MOVING - Release to record in history")
            elif self.dragging_origin:
                info_lines.append("CHANGING ORIGIN - Release to record in history")

        # Color-code lines
        for i, line in enumerate(info_lines):
            if line.startswith("SPRITE SHEET EDITOR"):
                color = GREEN
            elif line.startswith("Last Action") and self.can_undo():
                color = CYAN
            elif line.startswith(("RESIZING", "MOVING", "CHANGING")):
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
            self.screen.blit(text, (10, SCREEN_HEIGHT - 200 + i * 14))

    def run(self):
        running = True
        while running:
            running = self.handle_events()
            self.draw()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    editor = SpriteSheetEditor()

    # Try to load a sprite sheet if it exists
    if os.path.exists("GIJoe_FigurineParts.png"):
        editor.load_sprite_sheet("GIJoe_FigurineParts.png", use_command=False)  # Don't use command for initial load

    editor.run()