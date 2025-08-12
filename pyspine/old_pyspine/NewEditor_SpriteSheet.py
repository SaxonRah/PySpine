import pygame
import pygame_gui
import sys
import math
import os
from typing import Dict, Any, Optional, Tuple
from dataclasses import asdict

# Import configuration and core classes
from configuration import *
from data_classes import ResizeHandle, SpriteRect
from viewport_common import ViewportManager
from drawing_common import draw_grid
from file_common import save_json_project

# Import undo/redo system
from undo_redo_common import UndoRedoMixin, UndoRedoCommand
from sprite_commands import (
    CreateSpriteCommand, DeleteSpriteCommand, MoveSpriteCommand,
    ResizeSpriteCommand, ChangeOriginCommand
)

# Import new panel system
from pyspine.old_pyspine.pygame_gui_extensions.hierarchy_panel import (
    HierarchyPanel, HierarchyNode, HierarchyNodeType, HierarchyConfig,
    UI_HIERARCHY_NODE_SELECTED
)
from pyspine.old_pyspine.pygame_gui_extensions.property_panel import (
    PropertyPanel, PropertySchema, PropertyType, PropertyConfig, UI_PROPERTY_CHANGED
)
from pyspine.old_pyspine.pygame_gui_extensions.wip.navigator_panel import (
    NavigatorPanel, NavigatorConfig, NavigatorViewport, NavigatorMode,
    UI_NAVIGATOR_VIEWPORT_CHANGED
)

# Initialize Pygame and pygame_gui
pygame.init()

SPRITE_EDITOR_NAME_VERSION = "SpriteSheet Editor v3.0 (Panel System)"


class LoadSpriteSheetCommand(UndoRedoCommand):
    """Command for loading a sprite sheet"""

    def __init__(self, editor, new_path: str, description: str = ""):
        super().__init__(description or f"Load sprite sheet {os.path.basename(new_path)}")
        self.editor = editor
        self.new_path = new_path

        # Store old state
        self.old_sprite_sheet = editor.sprite_sheet
        self.old_sprite_sheet_path = editor.sprite_sheet_path
        self.old_sprites = editor.sprites.copy()
        self.old_selected_sprite = editor.selected_sprite

        # Try loading the new sprite sheet
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
            self.editor.selected_sprite = None
            self.editor.viewport_manager.viewport_offset = [50, TOOLBAR_HEIGHT + 50]
            self.editor.update_navigator()
            print(f"Loaded sprite sheet: {self.new_path}")
        else:
            print(f"Failed to load sprite sheet: {self.new_path}")

    def undo(self) -> None:
        self.editor.sprite_sheet = self.old_sprite_sheet
        self.editor.sprite_sheet_path = self.old_sprite_sheet_path
        self.editor.sprites = self.old_sprites.copy()
        self.editor.selected_sprite = self.old_selected_sprite
        self.editor.update_hierarchy()
        self.editor.update_navigator()
        print("Restored previous sprite sheet state")


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
        self.editor.update_hierarchy()

    def undo(self) -> None:
        self.editor.sprites = self.old_sprites.copy()
        self.editor.selected_sprite = self.old_selected_sprite
        self.editor.update_hierarchy()


class SpriteSheetContentProvider:
    """Content provider for the navigator panel"""

    def __init__(self, editor):
        self.editor = editor

    def get_content_size(self) -> Tuple[float, float]:
        """Get size of all content"""
        if not self.editor.sprite_sheet:
            return 800.0, 600.0
        return float(self.editor.sprite_sheet.get_width()), float(self.editor.sprite_sheet.get_height())

    def render_thumbnail(self, surface: pygame.Surface, thumbnail_rect: pygame.Rect,
                         viewport: NavigatorViewport) -> None:
        """Render content thumbnail for the navigator"""
        if not self.editor.sprite_sheet:
            # Draw placeholder
            pygame.draw.rect(surface, pygame.Color(100, 100, 100), thumbnail_rect)
            return

        # Scale and draw the sprite sheet
        sheet_w, sheet_h = self.editor.sprite_sheet.get_size()

        # Calculate scale to fit thumbnail
        scale_x = thumbnail_rect.width / sheet_w
        scale_y = thumbnail_rect.height / sheet_h
        scale = min(scale_x, scale_y)

        if scale > 0:
            scaled_w = int(sheet_w * scale)
            scaled_h = int(sheet_h * scale)

            if scaled_w > 0 and scaled_h > 0:
                scaled_sheet = pygame.transform.scale(self.editor.sprite_sheet, (scaled_w, scaled_h))

                # Center the scaled image
                draw_x = thumbnail_rect.x + (thumbnail_rect.width - scaled_w) // 2
                draw_y = thumbnail_rect.y + (thumbnail_rect.height - scaled_h) // 2
                surface.blit(scaled_sheet, (draw_x, draw_y))

                # Draw sprite rectangles
                for sprite in self.editor.sprites.values():
                    sprite_rect = pygame.Rect(
                        int(draw_x + sprite.x * scale),
                        int(draw_y + sprite.y * scale),
                        max(1, int(sprite.width * scale)),
                        max(1, int(sprite.height * scale))
                    )

                    # Highlight selected sprite
                    color = pygame.Color(255, 255, 0) if sprite.name == self.editor.selected_sprite else pygame.Color(0,
                                                                                                                      255,
                                                                                                                      255)
                    pygame.draw.rect(surface, color, sprite_rect, 1)

    def get_selection_bounds(self) -> Optional[pygame.Rect]:
        """Get bounds of selected content"""
        if self.editor.selected_sprite and self.editor.selected_sprite in self.editor.sprites:
            sprite = self.editor.sprites[self.editor.selected_sprite]
            return pygame.Rect(sprite.x, sprite.y, sprite.width, sprite.height)
        return None


class ModernSpriteSheetEditor(UndoRedoMixin):
    """Modern SpriteSheet Editor using the new panel system"""

    def __init__(self):
        super().__init__()

        # Initialize display
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(SPRITE_EDITOR_NAME_VERSION)
        self.clock = pygame.time.Clock()

        # Initialize UI manager
        self.ui_manager = pygame_gui.UIManager((SCREEN_WIDTH, SCREEN_HEIGHT))

        # Core editor state
        self.sprite_sheet = None
        self.sprite_sheet_path = ""
        self.sprites: Dict[str, SpriteRect] = {}
        self.selected_sprite = None

        # Viewport management
        self.viewport_manager = ViewportManager([50, TOOLBAR_HEIGHT + 50])

        # UI interaction state
        self.creating_sprite = False
        self.sprite_start_pos = None
        self.dragging_sprite = False
        self.dragging_origin = False
        self.resizing_sprite = False
        self.resize_handle = ResizeHandle.NONE
        self.drag_start_pos = None
        self.drag_offset = (0, 0)

        # Create fonts
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        # Initialize panels
        self._setup_panels()

        # Auto-load if available
        self._auto_load_sprite_sheet()

    def _setup_panels(self):
        """Set up all UI panels"""
        # Create hierarchy panel
        hierarchy_config = HierarchyConfig()
        hierarchy_config.show_root = False
        hierarchy_config.allow_drag = True
        hierarchy_config.allow_drop = True
        hierarchy_config.icon_size = (16, 16)

        self.hierarchy_root = HierarchyNode("root", "Sprites", HierarchyNodeType.ROOT)
        self.hierarchy_panel = HierarchyPanel(
            pygame.Rect(0, TOOLBAR_HEIGHT, HIERARCHY_PANEL_WIDTH, SCREEN_HEIGHT - TOOLBAR_HEIGHT),
            self.ui_manager,
            self.hierarchy_root,
            hierarchy_config
        )

        # Create property panel
        property_config = PropertyConfig()
        property_config.show_advanced_properties = False
        property_config.show_tooltips = True
        property_config.live_editing = True

        self.property_panel = PropertyPanel(
            pygame.Rect(SCREEN_WIDTH - PROPERTY_PANEL_WIDTH, TOOLBAR_HEIGHT,
                        PROPERTY_PANEL_WIDTH, SCREEN_HEIGHT - TOOLBAR_HEIGHT - 200),
            self.ui_manager,
            property_config
        )

        # Create navigator panel
        navigator_config = NavigatorConfig()
        navigator_config.show_zoom_controls = True
        navigator_config.show_coordinates = True
        navigator_config.click_to_navigate = True
        navigator_config.drag_to_pan = True
        navigator_config.mode = NavigatorMode.THUMBNAIL

        self.content_provider = SpriteSheetContentProvider(self)
        content_w, content_h = self.content_provider.get_content_size()

        # Initialize viewport info
        main_area = self._get_main_viewport_rect()
        initial_viewport = NavigatorViewport(
            content_x=0, content_y=0,
            content_width=main_area.width / self.viewport_manager.viewport_zoom,
            content_height=main_area.height / self.viewport_manager.viewport_zoom,
            zoom=self.viewport_manager.viewport_zoom,
            total_content_width=content_w,
            total_content_height=content_h
        )

        self.navigator_panel = NavigatorPanel(
            pygame.Rect(SCREEN_WIDTH - PROPERTY_PANEL_WIDTH, SCREEN_HEIGHT - 200,
                        PROPERTY_PANEL_WIDTH, 200),
            self.ui_manager,
            self.content_provider,
            initial_viewport,
            navigator_config
        )

        # Update navigator with current viewport
        self.update_navigator()

    def _auto_load_sprite_sheet(self):
        """Try to load a common sprite sheet file"""
        common_files = ["PySpineGuy.png", "spritesheet.png", "texture.png"]
        for filename in common_files:
            if os.path.exists(filename):
                self.load_sprite_sheet(filename)
                break

    def load_sprite_sheet(self, filename: str):
        """Load a sprite sheet using command system"""
        command = LoadSpriteSheetCommand(self, filename)
        self.execute_command(command)

    def update_hierarchy(self):
        """Update the hierarchy panel with current sprites"""
        # Clear existing children
        self.hierarchy_root.children.clear()

        # Add sprites as hierarchy nodes
        for sprite_name, sprite in self.sprites.items():
            sprite_node = HierarchyNode(
                sprite_name, sprite_name, HierarchyNodeType.ITEM,
                icon_name="sprite"
            )
            self.hierarchy_root.add_child(sprite_node)

        # Rebuild the hierarchy UI
        self.hierarchy_panel.rebuild_ui()

    def update_navigator(self):
        """Update the navigator panel with current viewport"""
        if hasattr(self, 'navigator_panel'):
            # Create viewport info from current state
            main_area = self._get_main_viewport_rect()
            content_w, content_h = self.content_provider.get_content_size()

            viewport = NavigatorViewport(
                content_x=-self.viewport_manager.viewport_offset[0],
                content_y=-self.viewport_manager.viewport_offset[1],
                content_width=main_area.width / self.viewport_manager.viewport_zoom,
                content_height=main_area.height / self.viewport_manager.viewport_zoom,
                zoom=self.viewport_manager.viewport_zoom,
                total_content_width=content_w,
                total_content_height=content_h
            )

            self.navigator_panel.set_viewport(viewport)

    def update_property_panel(self):
        """Update property panel with selected sprite properties"""
        if not self.selected_sprite or self.selected_sprite not in self.sprites:
            self.property_panel.set_properties([], None)
            return

        sprite = self.sprites[self.selected_sprite]

        # Create property schemas for the sprite
        properties = [
            PropertySchema(
                id="name",
                label="Name",
                property_type=PropertyType.TEXT,
                value=sprite.name,
                section="General",
                order=0,
                tooltip="The name of this sprite"
            ),
            PropertySchema(
                id="x",
                label="X Position",
                property_type=PropertyType.NUMBER,
                value=sprite.x,
                section="Transform",
                order=1,
                min_value=0,
                tooltip="X position in the sprite sheet"
            ),
            PropertySchema(
                id="y",
                label="Y Position",
                property_type=PropertyType.NUMBER,
                value=sprite.y,
                section="Transform",
                order=2,
                min_value=0,
                tooltip="Y position in the sprite sheet"
            ),
            PropertySchema(
                id="width",
                label="Width",
                property_type=PropertyType.NUMBER,
                value=sprite.width,
                section="Transform",
                order=3,
                min_value=1,
                tooltip="Width of the sprite rectangle"
            ),
            PropertySchema(
                id="height",
                label="Height",
                property_type=PropertyType.NUMBER,
                value=sprite.height,
                section="Transform",
                order=4,
                min_value=1,
                tooltip="Height of the sprite rectangle"
            ),
            PropertySchema(
                id="origin_x",
                label="Origin X",
                property_type=PropertyType.SLIDER,
                value=sprite.origin_x,
                section="Origin",
                order=5,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                precision=2,
                tooltip="Horizontal origin point (0.0 = left, 1.0 = right)"
            ),
            PropertySchema(
                id="origin_y",
                label="Origin Y",
                property_type=PropertyType.SLIDER,
                value=sprite.origin_y,
                section="Origin",
                order=6,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                precision=2,
                tooltip="Vertical origin point (0.0 = top, 1.0 = bottom)"
            )
        ]

        self.property_panel.set_properties(properties, sprite)

    def _get_main_viewport_rect(self):
        """Get the main viewport rectangle"""
        return pygame.Rect(
            HIERARCHY_PANEL_WIDTH, TOOLBAR_HEIGHT,
            SCREEN_WIDTH - HIERARCHY_PANEL_WIDTH - PROPERTY_PANEL_WIDTH,
            SCREEN_HEIGHT - TOOLBAR_HEIGHT - 200
        )

    def handle_event(self, event):
        """Handle input events"""
        # Let UI manager handle events first
        if self.ui_manager.process_events(event):
            return True

        # Handle custom events from panels
        if event.type == UI_HIERARCHY_NODE_SELECTED:
            if hasattr(event, 'node'):
                node_id = event.node.id
                if node_id in self.sprites:
                    self.selected_sprite = node_id
                    self.update_property_panel()
                else:
                    self.selected_sprite = None
                    self.property_panel.set_properties([], None)
                return True

        elif event.type == UI_PROPERTY_CHANGED:
            if hasattr(event, 'property') and hasattr(event, 'new_value'):
                self._handle_property_change(event.property.id, event.new_value)
                return True

        elif event.type == UI_NAVIGATOR_VIEWPORT_CHANGED:
            if hasattr(event, 'viewport'):
                viewport = event.viewport
                self.viewport_manager.viewport_offset[0] = -viewport.content_x
                self.viewport_manager.viewport_offset[1] = -viewport.content_y
                self.viewport_manager.viewport_zoom = viewport.zoom
                return True

        # Handle keyboard shortcuts
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_o and pygame.key.get_pressed()[pygame.K_LCTRL]:
                self._open_sprite_sheet()
                return True
            elif event.key == pygame.K_s and pygame.key.get_pressed()[pygame.K_LCTRL]:
                self._save_project()
                return True
            elif event.key == pygame.K_z and pygame.key.get_pressed()[pygame.K_LCTRL]:
                if pygame.key.get_pressed()[pygame.K_LSHIFT]:
                    self.redo()
                else:
                    self.undo()
                return True
            elif event.key == pygame.K_DELETE and self.selected_sprite:
                self._delete_selected_sprite()
                return True
            elif event.key == pygame.K_n and pygame.key.get_pressed()[pygame.K_LCTRL]:
                self._create_new_sprite()
                return True

        # Handle mouse events in main viewport
        main_viewport = self._get_main_viewport_rect()

        if event.type == pygame.MOUSEBUTTONDOWN:
            if main_viewport.collidepoint(event.pos):
                return self._handle_mouse_down(event)
        elif event.type == pygame.MOUSEBUTTONUP:
            return self._handle_mouse_up(event)
        elif event.type == pygame.MOUSEMOTION:
            if main_viewport.collidepoint(event.pos):
                return self._handle_mouse_motion(event)
        elif event.type == pygame.MOUSEWHEEL:
            if main_viewport.collidepoint(pygame.mouse.get_pos()):
                return self._handle_mouse_wheel(event)

        return False

    def _handle_property_change(self, property_id: str, new_value: Any):
        """Handle property changes from the property panel"""
        if not self.selected_sprite or self.selected_sprite not in self.sprites:
            return

        sprite = self.sprites[self.selected_sprite]

        # Create appropriate command based on property
        if property_id == "name":
            # Handle name change
            if new_value != sprite.name and new_value not in self.sprites:
                # Remove old sprite and add with new name
                old_sprite = self.sprites.pop(self.selected_sprite)
                old_sprite.name = new_value
                self.sprites[new_value] = old_sprite
                self.selected_sprite = new_value
                self.update_hierarchy()

        elif property_id in ["x", "y"]:
            old_pos = (sprite.x, sprite.y)
            if property_id == "x":
                new_pos = (int(new_value), sprite.y)
            else:
                new_pos = (sprite.x, int(new_value))

            command = MoveSpriteCommand(sprite, old_pos, new_pos)
            self.execute_command(command)

        elif property_id in ["width", "height"]:
            old_size = (sprite.width, sprite.height)
            if property_id == "width":
                new_size = (int(new_value), sprite.height)
            else:
                new_size = (sprite.width, int(new_value))

            command = ResizeSpriteCommand(sprite, old_size, new_size)
            self.execute_command(command)

        elif property_id in ["origin_x", "origin_y"]:
            old_origin = (sprite.origin_x, sprite.origin_y)
            if property_id == "origin_x":
                new_origin = (float(new_value), sprite.origin_y)
            else:
                new_origin = (sprite.origin_x, float(new_value))

            command = ChangeOriginCommand(sprite, old_origin, new_origin)
            self.execute_command(command)

        # Update navigator after property changes
        self.update_navigator()

    def _handle_mouse_down(self, event):
        """Handle mouse down in main viewport"""
        if event.button == 1:  # Left click
            viewport_pos = self.viewport_manager.screen_to_viewport(event.pos, TOOLBAR_HEIGHT)

            # Check if clicking on a sprite
            clicked_sprite = self._get_sprite_at_position(viewport_pos)

            if clicked_sprite:
                self.selected_sprite = clicked_sprite
                self.hierarchy_panel.set_selected_node(clicked_sprite)
                self.update_property_panel()

                # Check if clicking on origin point
                if self._is_clicking_origin(viewport_pos, clicked_sprite):
                    self.dragging_origin = True
                else:
                    # Check for resize handles
                    self.resize_handle = self._get_resize_handle(viewport_pos, clicked_sprite)
                    if self.resize_handle != ResizeHandle.NONE:
                        self.resizing_sprite = True
                    else:
                        self.dragging_sprite = True
                        sprite = self.sprites[clicked_sprite]
                        self.drag_offset = (viewport_pos[0] - sprite.x, viewport_pos[1] - sprite.y)

                self.drag_start_pos = viewport_pos
            else:
                # Start creating new sprite
                self.creating_sprite = True
                self.sprite_start_pos = viewport_pos

        elif event.button == 2:  # Middle click for panning
            self.viewport_manager.dragging_viewport = True
            self.viewport_manager.last_mouse_pos = event.pos

        return True

    def _handle_mouse_up(self, event):
        """Handle mouse up"""
        if event.button == 1:  # Left click
            if self.creating_sprite and self.sprite_start_pos:
                self._finish_sprite_creation(event.pos)
            elif self.dragging_sprite:
                self._finish_sprite_drag()
            elif self.resizing_sprite:
                self._finish_sprite_resize()
            elif self.dragging_origin:
                self._finish_origin_drag()

            # Reset all drag states
            self.creating_sprite = False
            self.dragging_sprite = False
            self.resizing_sprite = False
            self.dragging_origin = False
            self.sprite_start_pos = None
            self.drag_start_pos = None
            self.resize_handle = ResizeHandle.NONE

        elif event.button == 2:  # Middle click
            self.viewport_manager.dragging_viewport = False

        return True

    def _handle_mouse_motion(self, event):
        """Handle mouse motion in main viewport"""
        if self.viewport_manager.dragging_viewport:
            self.viewport_manager.handle_drag(event.pos)
            self.update_navigator()
            return True

        viewport_pos = self.viewport_manager.screen_to_viewport(event.pos, TOOLBAR_HEIGHT)

        if self.creating_sprite and self.sprite_start_pos:
            # Update sprite creation preview
            pass
        elif self.dragging_sprite and self.selected_sprite:
            # Move sprite
            sprite = self.sprites[self.selected_sprite]
            new_x = viewport_pos[0] - self.drag_offset[0]
            new_y = viewport_pos[1] - self.drag_offset[1]
            sprite.x = max(0, int(new_x))
            sprite.y = max(0, int(new_y))
            self.update_property_panel()
        elif self.resizing_sprite and self.selected_sprite:
            # Resize sprite
            self._update_sprite_resize(viewport_pos)
        elif self.dragging_origin and self.selected_sprite:
            # Move origin point
            self._update_origin_drag(viewport_pos)

        return True

    def _handle_mouse_wheel(self, event):
        """Handle mouse wheel for zooming"""
        mouse_pos = pygame.mouse.get_pos()
        # Convert toolbar-relative position for zoom
        zoom_pos = (mouse_pos[0], mouse_pos[1] - TOOLBAR_HEIGHT)
        self.viewport_manager.handle_zoom(event, zoom_pos)
        self.update_navigator()
        return True

    def _get_sprite_at_position(self, pos):
        """Find sprite at given viewport position"""
        x, y = pos
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

    def _get_resize_handle(self, pos, sprite_name):
        """Get resize handle at position"""
        if sprite_name not in self.sprites:
            return ResizeHandle.NONE

        sprite = self.sprites[sprite_name]
        handle_size = max(8, int(10 / self.viewport_manager.viewport_zoom))

        # Check corner handles
        corners = [
            (sprite.x, sprite.y, ResizeHandle.TOP_LEFT),
            (sprite.x + sprite.width, sprite.y, ResizeHandle.TOP_RIGHT),
            (sprite.x, sprite.y + sprite.height, ResizeHandle.BOTTOM_LEFT),
            (sprite.x + sprite.width, sprite.y + sprite.height, ResizeHandle.BOTTOM_RIGHT)
        ]

        for corner_x, corner_y, handle in corners:
            if abs(pos[0] - corner_x) <= handle_size and abs(pos[1] - corner_y) <= handle_size:
                return handle

        # Check edge handles
        edges = [
            (sprite.x + sprite.width / 2, sprite.y, ResizeHandle.TOP),
            (sprite.x + sprite.width / 2, sprite.y + sprite.height, ResizeHandle.BOTTOM),
            (sprite.x, sprite.y + sprite.height / 2, ResizeHandle.LEFT),
            (sprite.x + sprite.width, sprite.y + sprite.height / 2, ResizeHandle.RIGHT)
        ]

        for edge_x, edge_y, handle in edges:
            if abs(pos[0] - edge_x) <= handle_size and abs(pos[1] - edge_y) <= handle_size:
                return handle

        return ResizeHandle.NONE

    def _finish_sprite_creation(self, mouse_pos):
        """Finish creating a new sprite"""
        if not self.sprite_start_pos:
            return

        viewport_end = self.viewport_manager.screen_to_viewport(mouse_pos, TOOLBAR_HEIGHT)

        # Calculate sprite bounds
        x1, y1 = self.sprite_start_pos
        x2, y2 = viewport_end

        x = min(x1, x2)
        y = min(y1, y2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)

        # Minimum size
        if width < 5 or height < 5:
            width = max(width, 32)
            height = max(height, 32)

        # Clamp to sprite sheet bounds if available
        if self.sprite_sheet:
            sheet_w, sheet_h = self.sprite_sheet.get_size()
            x = max(0, min(x, sheet_w - width))
            y = max(0, min(y, sheet_h - height))
            width = min(width, sheet_w - x)
            height = min(height, sheet_h - y)

        # Create new sprite
        sprite_name = self._generate_sprite_name()
        new_sprite = SpriteRect(
            name=sprite_name,
            x=int(x), y=int(y),
            width=int(width), height=int(height)
        )

        # Execute creation command
        command = CreateSpriteCommand(self.sprites, new_sprite)
        self.execute_command(command)

        # Select the new sprite
        self.selected_sprite = sprite_name
        self.hierarchy_panel.set_selected_node(sprite_name)
        self.update_hierarchy()
        self.update_property_panel()

    def _finish_sprite_drag(self):
        """Finish dragging a sprite"""
        if self.selected_sprite and self.drag_start_pos:
            sprite = self.sprites[self.selected_sprite]
            current_pos = (sprite.x, sprite.y)

            # Only create command if position actually changed
            if current_pos != (self.drag_start_pos[0] - self.drag_offset[0],
                               self.drag_start_pos[1] - self.drag_offset[1]):
                old_pos = (int(self.drag_start_pos[0] - self.drag_offset[0]),
                           int(self.drag_start_pos[1] - self.drag_offset[1]))
                command = MoveSpriteCommand(sprite, old_pos, current_pos)
                self.execute_command(command)

    def _finish_sprite_resize(self):
        """Finish resizing a sprite"""
        # Implementation depends on how resize is tracked
        pass

    def _finish_origin_drag(self):
        """Finish dragging origin point"""
        # Implementation for origin dragging
        pass

    def _update_sprite_resize(self, viewport_pos):
        """Update sprite resize based on handle"""
        # Implementation for sprite resizing
        pass

    def _update_origin_drag(self, viewport_pos):
        """Update origin point dragging"""
        if not self.selected_sprite:
            return

        sprite = self.sprites[self.selected_sprite]

        # Calculate relative position within sprite
        rel_x = (viewport_pos[0] - sprite.x) / sprite.width
        rel_y = (viewport_pos[1] - sprite.y) / sprite.height

        # Clamp to 0-1 range
        sprite.origin_x = max(0.0, min(1.0, rel_x))
        sprite.origin_y = max(0.0, min(1.0, rel_y))

        self.update_property_panel()

    def _generate_sprite_name(self):
        """Generate a unique sprite name"""
        base_name = "sprite"
        counter = 1
        while f"{base_name}_{counter}" in self.sprites:
            counter += 1
        return f"{base_name}_{counter}"

    def _create_new_sprite(self):
        """Create a new sprite at center of viewport"""
        main_viewport = self._get_main_viewport_rect()
        center_screen = (main_viewport.centerx, main_viewport.centery)
        center_viewport = self.viewport_manager.screen_to_viewport(center_screen, TOOLBAR_HEIGHT)

        # Create sprite at center
        sprite_name = self._generate_sprite_name()
        new_sprite = SpriteRect(
            name=sprite_name,
            x=int(center_viewport[0] - 16),
            y=int(center_viewport[1] - 16),
            width=32, height=32
        )

        command = CreateSpriteCommand(self.sprites, new_sprite)
        self.execute_command(command)

        self.selected_sprite = sprite_name
        self.hierarchy_panel.set_selected_node(sprite_name)
        self.update_hierarchy()
        self.update_property_panel()

    def _delete_selected_sprite(self):
        """Delete the currently selected sprite"""
        if self.selected_sprite and self.selected_sprite in self.sprites:
            command = DeleteSpriteCommand(self.sprites, self.selected_sprite)
            self.execute_command(command)

            self.selected_sprite = None
            self.update_hierarchy()
            self.property_panel.set_properties([], None)

    def _open_sprite_sheet(self):
        """Open sprite sheet file dialog"""
        # For demo, try common files
        common_files = ["GIJoe_FigurineParts.png", "spritesheet.png", "texture.png"]
        for filename in common_files:
            if os.path.exists(filename):
                self.load_sprite_sheet(filename)
                break
        else:
            print("No sprite sheet found. Place a file named 'spritesheet.png' to load it.")

    def _save_project(self):
        """Save current project"""
        project_data = {
            "sprite_sheet_path": self.sprite_sheet_path,
            "sprites": {name: asdict(sprite) for name, sprite in self.sprites.items()}
        }

        save_result = save_json_project("spritesheet_project.json", project_data)
        if save_result:
            print("Project saved to spritesheet_project.json")
        else:
            print("Failed to save Project!")

    def render(self):
        """Render the editor"""
        # Clear screen
        self.screen.fill(DARK_GRAY)

        # Draw main viewport
        self._draw_main_viewport()

        # Draw toolbar
        self._draw_toolbar()

        # Update and draw UI panels
        time_delta = self.clock.get_time() / 1000.0
        self.ui_manager.update(time_delta)
        self.ui_manager.draw_ui(self.screen)

        # Draw additional overlays
        self._draw_creation_guides()

        pygame.display.flip()

    def _draw_toolbar(self):
        """Draw the toolbar"""
        toolbar_rect = pygame.Rect(0, 0, SCREEN_WIDTH, TOOLBAR_HEIGHT)
        pygame.draw.rect(self.screen, GRAY, toolbar_rect)
        pygame.draw.line(self.screen, BLACK, (0, TOOLBAR_HEIGHT), (SCREEN_WIDTH, TOOLBAR_HEIGHT))

        # Title
        title = self.font.render(SPRITE_EDITOR_NAME_VERSION, True, BLACK)
        self.screen.blit(title, (10, 15))

        # File info
        if self.sprite_sheet_path:
            file_info = f"File: {os.path.basename(self.sprite_sheet_path)}"
            if self.sprite_sheet:
                w, h = self.sprite_sheet.get_size()
                file_info += f" ({w}x{h})"

            info_text = self.small_font.render(file_info, True, BLACK)
            self.screen.blit(info_text, (300, 20))

        # Sprite count
        count_text = self.small_font.render(f"Sprites: {len(self.sprites)}", True, BLACK)
        self.screen.blit(count_text, (600, 20))

        # Undo/Redo info
        if self.can_undo():
            undo_text = self.small_font.render("Can Undo", True, BLUE)
            self.screen.blit(undo_text, (750, 10))

        if self.can_redo():
            redo_text = self.small_font.render("Can Redo", True, BLUE)
            self.screen.blit(redo_text, (750, 25))

    def _draw_main_viewport(self):
        """Draw the main editing viewport"""
        main_viewport = self._get_main_viewport_rect()

        # Clear viewport area
        pygame.draw.rect(self.screen, WHITE, main_viewport)

        # Create a clip rect for the viewport
        self.screen.set_clip(main_viewport)

        # Draw sprite sheet if loaded
        if self.sprite_sheet:
            sheet_pos = self.viewport_manager.viewport_to_screen((0, 0), TOOLBAR_HEIGHT)
            sheet_size = self.sprite_sheet.get_size()
            scaled_size = (
                int(sheet_size[0] * self.viewport_manager.viewport_zoom),
                int(sheet_size[1] * self.viewport_manager.viewport_zoom)
            )

            if scaled_size[0] > 0 and scaled_size[1] > 0:
                scaled_sheet = pygame.transform.scale(self.sprite_sheet, scaled_size)
                self.screen.blit(scaled_sheet, sheet_pos)

        # Draw grid
        draw_grid(self.screen, self.viewport_manager, main_viewport, TOOLBAR_HEIGHT)

        # Draw sprites
        self._draw_sprites()

        # Remove clip
        self.screen.set_clip(None)

        # Draw viewport border
        pygame.draw.rect(self.screen, BLACK, main_viewport, 2)

    def _draw_sprites(self):
        """Draw sprite rectangles and selection"""
        for sprite_name, sprite in self.sprites.items():
            # Convert to screen coordinates
            screen_pos = self.viewport_manager.viewport_to_screen((sprite.x, sprite.y), TOOLBAR_HEIGHT)
            screen_size = (
                int(sprite.width * self.viewport_manager.viewport_zoom),
                int(sprite.height * self.viewport_manager.viewport_zoom)
            )

            if screen_size[0] <= 0 or screen_size[1] <= 0:
                continue

            sprite_rect = pygame.Rect(screen_pos[0], screen_pos[1], screen_size[0], screen_size[1])

            # Draw sprite rectangle
            color = YELLOW if sprite_name == self.selected_sprite else BLUE
            pygame.draw.rect(self.screen, color, sprite_rect, 2)

            # Draw origin point
            origin_screen_x = screen_pos[0] + screen_size[0] * sprite.origin_x
            origin_screen_y = screen_pos[1] + screen_size[1] * sprite.origin_y
            pygame.draw.circle(self.screen, RED,
                               (int(origin_screen_x), int(origin_screen_y)), 4)

            # Draw sprite name
            if self.viewport_manager.viewport_zoom > 0.5:
                name_text = self.small_font.render(sprite_name, True, color)
                self.screen.blit(name_text, (screen_pos[0], screen_pos[1] - 20))

        # Draw selection handles for selected sprite
        if self.selected_sprite and self.selected_sprite in self.sprites:
            self._draw_selection_handles()

    def _draw_selection_handles(self):
        """Draw resize handles for selected sprite"""
        if not self.selected_sprite:
            return

        sprite = self.sprites[self.selected_sprite]
        handle_size = max(6, int(8 / self.viewport_manager.viewport_zoom))

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
        """Draw guides during sprite creation"""
        if self.creating_sprite and self.sprite_start_pos:
            mouse_pos = pygame.mouse.get_pos()
            main_viewport = self._get_main_viewport_rect()

            if main_viewport.collidepoint(mouse_pos):
                start_screen = self.viewport_manager.viewport_to_screen(self.sprite_start_pos, TOOLBAR_HEIGHT)

                # Draw creation rectangle
                width = abs(mouse_pos[0] - start_screen[0])
                height = abs(mouse_pos[1] - start_screen[1])
                x = min(start_screen[0], mouse_pos[0])
                y = min(start_screen[1], mouse_pos[1])

                pygame.draw.rect(self.screen, YELLOW, (x, y, width, height), 2)

    def run(self):
        """Main game loop"""
        running = True

        print(f"\n{SPRITE_EDITOR_NAME_VERSION}")
        print("\nControls:")
        print("- Left click and drag: Create new sprite rectangle")
        print("- Left click sprite: Select sprite")
        print("- Left click origin (red dot): Move origin point")
        print("- Left click handles (cyan squares): Resize sprite")
        print("- Middle mouse: Pan viewport")
        print("- Mouse wheel: Zoom in/out")
        print("- Ctrl+N: Create new sprite at center")
        print("- Ctrl+O: Open sprite sheet")
        print("- Ctrl+S: Save project")
        print("- Ctrl+Z: Undo")
        print("- Ctrl+Shift+Z: Redo")
        print("- Delete: Delete selected sprite")
        print("\nUse the Hierarchy Panel to select sprites")
        print("Use the Property Inspector to edit sprite properties")
        print("Use the Navigator to overview and navigate the sprite sheet")

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                else:
                    self.handle_event(event)

            self.render()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()


def main():
    """Entry point for the modern sprite sheet editor"""
    editor = ModernSpriteSheetEditor()
    editor.run()


if __name__ == "__main__":
    main()