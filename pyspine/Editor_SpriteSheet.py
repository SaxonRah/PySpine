import pygame
import pygame_gui
import sys
import math
from typing import Dict
from dataclasses import asdict
import os

from configuration import *
from data_classes import ResizeHandle, SpriteRect
from viewport_common import ViewportManager
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

SPRITE_EDITOR_NAME_VERSION = "Sprite Sheet Editor GUI v0.1"


class LoadSpriteSheetCommand(UndoRedoCommand):
    """Command for loading a sprite sheet (with full state backup)"""

    def __init__(self, given_editor, new_path: str, description: str = ""):
        super().__init__(description or f"Load sprite sheet {os.path.basename(new_path)}")
        self.editor = given_editor
        self.new_path = new_path

        # Store old state
        self.old_sprite_sheet = given_editor.sprite_sheet
        self.old_sprite_sheet_path = given_editor.sprite_sheet_path
        self.old_sprites = given_editor.sprites.copy()
        self.old_selected_sprite = given_editor.selected_sprite

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
            self.editor.viewport_manager.viewport_offset = [50, 50]
            self.editor._update_ui_elements()
            print(f"Loaded sprite sheet: {self.new_path}")
        else:
            print(f"Failed to load sprite sheet: {self.new_path}")

    def undo(self) -> None:
        self.editor.sprite_sheet = self.old_sprite_sheet
        self.editor.sprite_sheet_path = self.old_sprite_sheet_path
        self.editor.sprites = self.old_sprites.copy()
        self.editor.selected_sprite = self.old_selected_sprite
        self.editor._update_ui_elements()
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
        self.editor._update_ui_elements()
        print("Cleared all sprites")

    def undo(self) -> None:
        self.editor.sprites = self.old_sprites.copy()
        self.editor.selected_sprite = self.old_selected_sprite
        self.editor._update_ui_elements()
        print(f"Restored {len(self.old_sprites)} sprites")


class SpriteSheetEditorGUI(BaseEventHandler, UndoRedoMixin):
    def __init__(self):
        super().__init__()
        BaseEventHandler.__init__(self)
        UndoRedoMixin.__init__(self)

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(f"{SPRITE_EDITOR_NAME_VERSION}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        # Initialize pygame-gui with theme to reduce font warnings
        self.ui_manager = pygame_gui.UIManager((SCREEN_WIDTH, SCREEN_HEIGHT))

        # Define layout dimensions
        self.sprite_panel_width = 300
        self.toolbar_height = 80
        self.main_viewport_width = SCREEN_WIDTH - self.sprite_panel_width
        self.main_viewport_height = SCREEN_HEIGHT - self.toolbar_height

        # Initialize viewport manager for the main canvas area
        self.viewport_manager = ViewportManager([50, 50])

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

        # Create UI elements
        self._create_ui_elements()

        # Setup undo/redo key handlers
        self.setup_undo_redo_keys()

        # Setup additional key handlers specific to sprite sheet editor
        self.key_handlers.update({
            (pygame.K_o, pygame.K_LCTRL): self._open_sprite_sheet,
            (pygame.K_n, pygame.K_LCTRL): self._create_new_sprite,
            (pygame.K_x, pygame.K_LCTRL): self._clear_all_sprites,
        })

    def _create_ui_elements(self):
        """Create pygame-gui UI elements"""

        # Main toolbar panel
        self.toolbar_panel = pygame_gui.elements.UIPanel(
            relative_rect=pygame.Rect(0, 0, SCREEN_WIDTH, self.toolbar_height),
            manager=self.ui_manager
        )

        # Toolbar buttons
        button_width = 120
        button_height = 30
        button_spacing = 10
        x_offset = 10
        y_offset = 10

        self.open_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Open Sheet',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.save_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Save Project',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.load_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Load Project',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.new_sprite_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='New Sprite',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.clear_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Clear All',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )

        # Undo/Redo buttons
        x_offset += button_width + button_spacing * 2
        self.undo_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, 80, button_height),
            text='Undo',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += 80 + button_spacing

        self.redo_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, 80, button_height),
            text='Redo',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )

        # Status label in toolbar
        self.status_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 45, 800, 25),
            text='Ready - Right click on canvas to create sprite, drag to edit',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )

        # Right side panel for sprite list and properties
        self.sprite_panel = pygame_gui.elements.UIPanel(
            relative_rect=pygame.Rect(self.main_viewport_width, self.toolbar_height,
                                      self.sprite_panel_width, self.main_viewport_height),
            manager=self.ui_manager
        )

        # Sprite list
        self.sprite_list_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 10, 200, 25),
            text='Sprites:',
            manager=self.ui_manager,
            container=self.sprite_panel
        )

        self.sprite_selection_list = pygame_gui.elements.UISelectionList(
            relative_rect=pygame.Rect(10, 40, self.sprite_panel_width - 20, 200),
            item_list=[],
            manager=self.ui_manager,
            container=self.sprite_panel
        )

        # Delete sprite button
        self.delete_sprite_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(10, 250, 100, 30),
            text='Delete',
            manager=self.ui_manager,
            container=self.sprite_panel
        )

        # Properties section
        self.properties_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 300, 200, 25),
            text='Properties:',
            manager=self.ui_manager,
            container=self.sprite_panel
        )

        # Properties display (will be updated dynamically)
        self.properties_text = pygame_gui.elements.UITextBox(
            relative_rect=pygame.Rect(10, 330, self.sprite_panel_width - 20, 200),
            html_text='<font color="#000000">No sprite selected</font>',
            manager=self.ui_manager,
            container=self.sprite_panel
        )

        # Undo/Redo history display
        self.history_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 540, 200, 25),
            text='History:',
            manager=self.ui_manager,
            container=self.sprite_panel
        )

        self.history_text = pygame_gui.elements.UITextBox(
            relative_rect=pygame.Rect(10, 570, self.sprite_panel_width - 20, 100),
            html_text='<font color="#000000">No history</font>',
            manager=self.ui_manager,
            container=self.sprite_panel
        )

        # Initial UI update - delay this to avoid the error during initialization
        pygame.time.set_timer(pygame.USEREVENT + 1, 100)  # Update UI after 100ms

    def _update_ui_elements(self):
        """Update UI elements to reflect current state"""
        # Update sprite list
        sprite_names = list(self.sprites.keys())
        self.sprite_selection_list.set_item_list(sprite_names)

        # Update selection in list
        if self.selected_sprite and self.selected_sprite in sprite_names:
            try:
                self.sprite_selection_list.set_single_selection(self.selected_sprite)
            except:
                pass  # Ignore selection errors

        # Update properties display
        if self.selected_sprite and self.selected_sprite in self.sprites:
            sprite = self.sprites[self.selected_sprite]
            properties_html = f'''<font color="#000000">
<b>Sprite: {sprite.name}</b><br>
Position: ({sprite.x}, {sprite.y})<br>
Size: {sprite.width} x {sprite.height}<br>
Origin: ({sprite.origin_x:.3f}, {sprite.origin_y:.3f})<br><br>

<b>Controls:</b><br>
- Drag sprite to move<br>
- Drag cyan handles to resize<br>
- Drag red dot to change origin<br>
- Right click to create new sprite<br>
</font>'''
        else:
            properties_html = '''<font color="#000000">
<b>No sprite selected</b><br><br>

<b>Usage:</b><br>
1. Open a sprite sheet image<br>
2. Right click to create sprites<br>
3. Drag to move/resize<br>
4. Red dot = origin point<br>
5. Save project when done<br>
</font>'''

        self.properties_text.set_text(properties_html)

        # Update history display
        undo_list = self.undo_manager.get_undo_list()
        redo_list = self.undo_manager.get_redo_list()

        history_html = f'<font color="#000000">'
        if undo_list:
            history_html += f'<b>Can Undo ({len(undo_list)}):</b><br>'
            for i, action in enumerate(undo_list[:3]):  # Show last 3
                history_html += f'{i + 1}. {action}<br>'
            if len(undo_list) > 3:
                history_html += f'... and {len(undo_list) - 3} more<br>'
        else:
            history_html += '<b>No undo history</b><br>'

        if redo_list:
            history_html += f'<br><b>Can Redo ({len(redo_list)}):</b><br>'
            for i, action in enumerate(redo_list[:2]):  # Show next 2
                history_html += f'{i + 1}. {action}<br>'

        history_html += '</font>'
        self.history_text.set_text(history_html)

        # Update button states - FIXED: Use enable()/disable() instead of set_enabled()
        if self.can_undo():
            self.undo_button.enable()
        else:
            self.undo_button.disable()

        if self.can_redo():
            self.redo_button.enable()
        else:
            self.redo_button.disable()

        if self.selected_sprite is not None:
            self.delete_sprite_button.enable()
        else:
            self.delete_sprite_button.disable()

        # Update status
        if self.sprite_sheet:
            sheet_name = os.path.basename(self.sprite_sheet_path) if self.sprite_sheet_path else "Unknown"
            status_text = f'Sheet: {sheet_name} | Sprites: {len(self.sprites)} | Zoom: {self.viewport_manager.viewport_zoom:.1f}x'
            if self.selected_sprite:
                status_text += f' | Selected: {self.selected_sprite}'
        else:
            status_text = 'No sprite sheet loaded - Click "Open Sheet" to begin'

        self.status_label.set_text(status_text)

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
                self.viewport_manager.viewport_offset = [50, 50]
                self._update_ui_elements()
                return True
            except pygame.error as e:
                print(f"Failed to load sprite sheet: {e}")
                return False

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            # Let pygame-gui process the event first - with error handling
            ui_consumed = False
            try:
                ui_consumed = self.ui_manager.process_events(event)
            except AttributeError as e:
                # Handle pygame-gui bug with ui_element attribute
                if "'pygame.event.Event' object has no attribute 'ui_element'" in str(e):
                    ui_consumed = False  # Continue processing
                else:
                    raise  # Re-raise if it's a different error

            # Handle delayed UI initialization
            if event.type == pygame.USEREVENT + 1:
                pygame.time.set_timer(pygame.USEREVENT + 1, 0)  # Cancel the timer
                self._update_ui_elements()  # Now safe to update UI
                continue

            # Handle pygame-gui events - check both possible event types
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                self._handle_ui_event(event)
            elif event.type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION:
                self._handle_ui_event(event)
            elif event.type == pygame.USEREVENT:
                # Check if this is a pygame-gui event
                if hasattr(event, 'user_type'):
                    if (event.user_type == pygame_gui.UI_BUTTON_PRESSED or
                            event.user_type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION):
                        self._handle_ui_event(event)

            # Handle non-UI events only if they weren't consumed by UI and are in main viewport
            if not ui_consumed:
                if event.type == pygame.KEYDOWN:
                    if not self.handle_keydown(event):
                        pass

            # Handle mouse events in main viewport regardless of UI consumption
            # (since we need to handle viewport interactions)
            if event.type == pygame.MOUSEBUTTONDOWN:
                if self._is_in_main_viewport(event.pos[0], event.pos[1]):
                    self._handle_mouse_down(event)

            elif event.type == pygame.MOUSEBUTTONUP:
                if self._is_in_main_viewport(event.pos[0], event.pos[1]):
                    self._handle_mouse_up(event)

            elif event.type == pygame.MOUSEMOTION:
                if self._is_in_main_viewport(event.pos[0], event.pos[1]):
                    self._handle_mouse_motion(event)

            elif event.type == pygame.MOUSEWHEEL:
                if self._is_in_main_viewport(pygame.mouse.get_pos()[0], pygame.mouse.get_pos()[1]):
                    self._handle_mouse_wheel(event)

        return True

    def _handle_ui_event(self, event):
        """Handle pygame-gui UI events"""
        # Handle both direct pygame-gui events and USEREVENT wrapped events
        event_type = None
        ui_element = None

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            event_type = pygame_gui.UI_BUTTON_PRESSED
            ui_element = event.ui_element
        elif event.type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION:
            event_type = pygame_gui.UI_SELECTION_LIST_NEW_SELECTION
            ui_element = event.ui_element
        elif event.type == pygame.USEREVENT and hasattr(event, 'user_type'):
            event_type = event.user_type
            ui_element = getattr(event, 'ui_element', None)

        if event_type == pygame_gui.UI_BUTTON_PRESSED:
            if ui_element == self.open_button:
                self._open_sprite_sheet()
            elif ui_element == self.save_button:
                self.save_project()
            elif ui_element == self.load_button:
                self.load_project()
            elif ui_element == self.new_sprite_button:
                self._create_new_sprite()
            elif ui_element == self.clear_button:
                self._clear_all_sprites()
            elif ui_element == self.undo_button:
                self.undo()
            elif ui_element == self.redo_button:
                self.redo()
            elif ui_element == self.delete_sprite_button:
                self.delete_selected()

        elif event_type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION:
            if ui_element == self.sprite_selection_list:
                selected_sprite = event.text
                if selected_sprite in self.sprites:
                    self.selected_sprite = selected_sprite
                    self._update_ui_elements()

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
                self.undo_manager.redo_stack.clear()
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
                self.undo_manager.redo_stack.clear()
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
                self.undo_manager.redo_stack.clear()
                print(f"Recorded origin change command: {origin_command}")

        # Clear operation state
        self.operation_in_progress = False
        self.drag_start_bounds = None
        self.drag_start_position = None
        self.drag_start_origin = None

        # Update UI after operation
        self._update_ui_elements()

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
        mouse_pos = pygame.mouse.get_pos()
        self.viewport_manager.handle_zoom(event, mouse_pos)

    def _handle_left_click(self, pos):
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

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

            # Update UI when selection changes
            self._update_ui_elements()

    def _handle_right_click(self, pos):
        """Right click to create new sprite using command system"""
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)
        self._create_sprite_at_position(viewport_pos)

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
            viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

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
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

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
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

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
            viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

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
        self._update_ui_elements()
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
        center_screen = (self.main_viewport_width // 2, self.main_viewport_height // 2 + self.toolbar_height)
        center_viewport = self.viewport_manager.screen_to_viewport(center_screen, self.toolbar_height)
        self._create_sprite_at_position(center_viewport)

    def _clear_all_sprites(self):
        """Clear all sprites using command system"""
        if self.sprites:
            clear_command = ClearSpritesCommand(self)
            self.execute_command(clear_command)

    def _is_in_main_viewport(self, x, y):
        return (0 < x < self.main_viewport_width and
                self.toolbar_height < y < SCREEN_HEIGHT)

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
        common_files = ["PySpineGuy.png", "GIJoe_FigurineParts.png", "spritesheet.png", "texture.png"]
        for filename in common_files:
            if os.path.exists(filename):
                self.load_sprite_sheet(filename)
                break
        else:
            print("No sprite sheet found. Place a PNG file in the directory")

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
        self._update_ui_elements()

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
            self._update_ui_elements()

    def delete_selected(self):
        """Delete selected sprite using command system"""
        if self.selected_sprite:
            delete_command = DeleteSpriteCommand(self.sprites, self.selected_sprite)
            self.execute_command(delete_command)
            self.selected_sprite = None
            self._update_ui_elements()

    def reset_viewport(self):
        """Reset viewport to default position and zoom"""
        self.viewport_manager.reset_viewport([50, 50])

    # Override undo/redo to update UI
    def undo(self, count: int = 1) -> bool:
        result = super().undo(count)
        if result:
            self._update_ui_elements()
        return result

    def redo(self, count: int = 1) -> bool:
        result = super().redo(count)
        if result:
            self._update_ui_elements()
        return result

    def update(self, dt):
        """Update the editor"""
        self.ui_manager.update(dt)

    def draw(self):
        self.screen.fill(DARK_GRAY)

        self._draw_main_viewport()

        # Draw pygame-gui elements
        self.ui_manager.draw_ui(self.screen)

        pygame.display.flip()

    def _draw_main_viewport(self):
        """Draw main viewport with sprite sheet and sprites"""
        viewport_rect = pygame.Rect(0, self.toolbar_height,
                                    self.main_viewport_width,
                                    self.main_viewport_height)
        pygame.draw.rect(self.screen, BLACK, viewport_rect)
        self.screen.set_clip(viewport_rect)

        # Draw sprite sheet if loaded
        if self.sprite_sheet:
            sheet_pos = self.viewport_manager.viewport_to_screen((0, 0), self.toolbar_height)
            sheet_size = (
                self.sprite_sheet.get_width() * self.viewport_manager.viewport_zoom,
                self.sprite_sheet.get_height() * self.viewport_manager.viewport_zoom
            )

            if sheet_size[0] > 0 and sheet_size[1] > 0:
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
            screen_pos = self.viewport_manager.viewport_to_screen((sprite.x, sprite.y), self.toolbar_height)
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
            ), self.toolbar_height)

            # Draw larger, more visible origin point
            origin_size = max(2, int(3 * self.viewport_manager.viewport_zoom))
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
        handle_size = max(3, int(4 * self.viewport_manager.viewport_zoom))

        # Corner handles
        corners = [
            (sprite.x, sprite.y),
            (sprite.x + sprite.width, sprite.y),
            (sprite.x, sprite.y + sprite.height),
            (sprite.x + sprite.width, sprite.y + sprite.height)
        ]

        for corner_x, corner_y in corners:
            screen_pos = self.viewport_manager.viewport_to_screen((corner_x, corner_y), self.toolbar_height)
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
            screen_pos = self.viewport_manager.viewport_to_screen((edge_x, edge_y), self.toolbar_height)
            pygame.draw.rect(self.screen, CYAN,
                             (screen_pos[0] - handle_size // 2, screen_pos[1] - handle_size // 2,
                              handle_size, handle_size))

    def _draw_creation_guides(self):
        """Draw guides for sprite creation"""
        if self.creating_sprite and self.sprite_start_pos:
            mouse_pos = pygame.mouse.get_pos()
            if self._is_in_main_viewport(mouse_pos[0], mouse_pos[1]):
                start_screen = self.viewport_manager.viewport_to_screen(self.sprite_start_pos, self.toolbar_height)

                # If we have temp_sprite_rect, use it for more accurate preview
                if hasattr(self, 'temp_sprite_rect'):
                    x, y, w, h = self.temp_sprite_rect
                    rect_screen_pos = self.viewport_manager.viewport_to_screen((x, y), self.toolbar_height)
                    rect_screen_size = (w * self.viewport_manager.viewport_zoom,
                                        h * self.viewport_manager.viewport_zoom)
                    pygame.draw.rect(self.screen, YELLOW,
                                     (rect_screen_pos[0], rect_screen_pos[1],
                                      rect_screen_size[0], rect_screen_size[1]), 2)
                else:
                    # Fallback to simple line
                    pygame.draw.line(self.screen, GREEN, start_screen, mouse_pos, 3)

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0  # Delta time in seconds

            running = self.handle_events()
            self.update(dt)
            self.draw()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    editor = SpriteSheetEditorGUI()

    # Try to load a sprite sheet if it exists
    if os.path.exists("PySpineGuy.png"):
        editor.load_sprite_sheet("PySpineGuy.png", use_command=False)  # Don't use command for initial load

    editor.run()