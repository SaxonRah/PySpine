import pygame
import pygame_gui
from pygame_gui.core import UIElement, ObjectID
from pygame_gui.core.interfaces import IContainerLikeInterface
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import os

try:
    from pygame_gui.core.interfaces.gui_font_interface import IGUIFontInterface
except ImportError:
    # Fallback for older versions
    IGUIFontInterface = None

HIERARCHY_DEBUG = False

# Constants
DOUBLE_CLICK_TIME = 500  # milliseconds
DROP_ZONE_RATIO = 0.25   # for before/after drop detection (0 to 1)

# Define custom pygame-gui events
UI_HIERARCHY_NODE_SELECTED = pygame.USEREVENT + 1
UI_HIERARCHY_NODE_DOUBLE_CLICKED = pygame.USEREVENT + 2
UI_HIERARCHY_NODE_RIGHT_CLICKED = pygame.USEREVENT + 3
UI_HIERARCHY_NODE_EXPANDED = pygame.USEREVENT + 4
UI_HIERARCHY_NODE_COLLAPSED = pygame.USEREVENT + 5
UI_HIERARCHY_DRAG_STARTED = pygame.USEREVENT + 6
UI_HIERARCHY_DROP_COMPLETED = pygame.USEREVENT + 7


class HierarchyNodeType(Enum):
    FOLDER = "folder"
    ITEM = "item"
    ROOT = "root"


@dataclass
class HierarchyNode:
    """Generic hierarchy node that can represent any data structure"""
    id: str
    name: str
    node_type: HierarchyNodeType
    data: Dict[str, Any] = field(default_factory=dict)
    children: List['HierarchyNode'] = field(default_factory=list)
    parent: Optional['HierarchyNode'] = None
    expanded: bool = True
    icon_name: Optional[str] = None  # Custom icon name for theme lookup

    def add_child(self, child: 'HierarchyNode'):
        """Add a child node"""
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: 'HierarchyNode'):
        """Remove a child node"""
        if child in self.children:
            child.parent = None
            self.children.remove(child)

    def get_depth(self) -> int:
        """Get the depth level of this node"""
        depth = 0
        current = self.parent
        while current:
            depth += 1
            current = current.parent
        return depth

    def find_node(self, node_id: str) -> Optional['HierarchyNode']:
        """Find a node by ID recursively"""
        if self.id == node_id:
            return self
        for child in self.children:
            found = child.find_node(node_id)
            if found:
                return found
        return None


class IconManager:
    """Manages icons for the hierarchy panel"""

    def __init__(self, manager: pygame_gui.UIManager, icon_size: tuple = (16, 16)):
        self.manager = manager
        self.icon_size = icon_size
        self.icon_cache: Dict[str, pygame.Surface] = {}
        self.default_icons = {}
        self._create_default_icons()

    def _create_default_icons(self):
        """Create default icons for common node types"""
        icon_surface = pygame.Surface(self.icon_size, pygame.SRCALPHA)

        # Folder icon (yellow folder shape)
        folder_surface = icon_surface.copy()
        folder_color = pygame.Color(255, 215, 0)  # Gold
        pygame.draw.rect(folder_surface, folder_color,
                         pygame.Rect(1, 4, 12, 8))
        pygame.draw.rect(folder_surface, folder_color,
                         pygame.Rect(1, 2, 4, 2))
        self.default_icons[HierarchyNodeType.FOLDER] = folder_surface

        # Folder open icon (opened folder)
        folder_open_surface = icon_surface.copy()
        pygame.draw.rect(folder_open_surface, folder_color,
                         pygame.Rect(1, 6, 12, 6))
        pygame.draw.polygon(folder_open_surface, folder_color,
                            [(1, 4), (5, 4), (6, 6), (1, 6)])
        self.default_icons['folder_open'] = folder_open_surface

        # Item icon (document/file)
        item_surface = icon_surface.copy()
        item_color = pygame.Color(200, 200, 200)  # Light gray
        pygame.draw.rect(item_surface, item_color,
                         pygame.Rect(3, 2, 8, 11))
        pygame.draw.rect(item_surface, pygame.Color(100, 100, 100),
                         pygame.Rect(3, 2, 8, 11), 1)
        # Small lines to represent text
        pygame.draw.line(item_surface, pygame.Color(100, 100, 100),
                         (4, 5), (9, 5))
        pygame.draw.line(item_surface, pygame.Color(100, 100, 100),
                         (4, 7), (9, 7))
        pygame.draw.line(item_surface, pygame.Color(100, 100, 100),
                         (4, 9), (7, 9))
        self.default_icons[HierarchyNodeType.ITEM] = item_surface

    def get_icon(self, node: HierarchyNode, expanded: bool = False) -> pygame.Surface:
        """Get icon for a node"""
        cache_key = f"{node.node_type.value}_{node.icon_name}_{expanded}"

        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]

        icon_surface = None

        # Try to load custom icon from theme or file
        if node.icon_name:
            icon_surface = self._load_themed_icon(node.icon_name)

        # Fall back to default icons
        if icon_surface is None:
            if node.node_type == HierarchyNodeType.FOLDER:
                if expanded and 'folder_open' in self.default_icons:
                    icon_surface = self.default_icons['folder_open']
                else:
                    icon_surface = self.default_icons[HierarchyNodeType.FOLDER]
            else:
                icon_surface = self.default_icons.get(node.node_type)

        # Create a blank icon if nothing found
        if icon_surface is None:
            icon_surface = pygame.Surface(self.icon_size, pygame.SRCALPHA)
            pygame.draw.circle(icon_surface, pygame.Color(150, 150, 150),
                               (self.icon_size[0] // 2, self.icon_size[1] // 2), 4)

        self.icon_cache[cache_key] = icon_surface
        return icon_surface

    def _load_themed_icon(self, icon_name: str) -> Optional[pygame.Surface]:
        """Load icon from theme or file system"""
        try:
            # Try to load from theme resources first
            theme = self.manager.get_theme()
            # Check if theme has icon resources defined
            # This is a simplified approach - in practice you'd implement
            # proper theme resource loading similar to how pygame-gui does it

            # For now, try to load from file system
            icon_paths = [
                f"icons/{icon_name}.png",
                f"assets/icons/{icon_name}.png",
                f"data/icons/{icon_name}.png",
                f"{icon_name}.png"
            ]

            for path in icon_paths:
                if os.path.exists(path):
                    surface = pygame.image.load(path).convert_alpha()
                    return pygame.transform.scale(surface, self.icon_size)

        except Exception as e:
            if HIERARCHY_DEBUG:
                print(f"Failed to load icon {icon_name}: {e}")

        return None

    def clear_cache(self):
        """Clear the icon cache"""
        self.icon_cache.clear()


@dataclass
class HierarchyConfig:
    """Configuration for the hierarchy panel (theme-independent settings)"""
    # Layout settings
    indent_size: int = 20
    node_height: int = 25
    icon_size: tuple = (16, 16)

    # Behavior
    allow_drag: bool = True
    allow_drop: bool = True
    allow_reorder: bool = True
    show_root: bool = False
    folders_only_have_children: bool = False

    # Animation settings
    expand_animation_time: float = 0.0  # 0 = no animation


class HierarchyNodeUI:
    """UI representation of a hierarchy node"""

    def __init__(self, node: HierarchyNode, rect: pygame.Rect, config: HierarchyConfig):
        self.node = node
        self.rect = rect
        self.config = config
        self.is_hovered = False
        self.is_selected = False
        self.is_focused = False
        self.is_drop_target = False
        self.is_invalid_drop_target = False
        self.drop_position = None
        self.expand_button_rect = None

        # Calculate expand button position if node has children
        if self.node.children:
            button_size = 12
            indent = self.node.get_depth() * self.config.indent_size
            self.expand_button_rect = pygame.Rect(
                indent + 5,  # Relative to the node rect
                (rect.height - button_size) // 2,
                button_size,
                button_size
            )

    def draw(self, surface: pygame.Surface,
             font: Union[pygame.font.Font, 'IGUIFontInterface', Any],
             surface_rect: pygame.Rect,
             colors: Dict[str, pygame.Color],
             icon_manager: IconManager):
        """Draw the node UI onto the surface (relative coordinates)"""
        # Use relative coordinates within the surface
        draw_rect = pygame.Rect(0, 0, surface_rect.width, self.config.node_height)

        # Background
        if self.is_invalid_drop_target:
            drop_color = colors.get('invalid_drop', pygame.Color(150, 80, 80))
            if self.drop_position == 1:  # As child - highlight entire node
                pygame.draw.rect(surface, drop_color, draw_rect)
            else:  # Before/after - draw line
                line_y = draw_rect.top if self.drop_position == 0 else draw_rect.bottom - 1
                pygame.draw.line(surface, drop_color,
                                 (draw_rect.left, line_y), (draw_rect.right, line_y), 3)
        elif self.is_drop_target:
            drop_color = colors.get('valid_drop', pygame.Color(100, 150, 100))
            if self.drop_position == 1:  # As child - highlight entire node
                pygame.draw.rect(surface, drop_color, draw_rect)
            else:  # Before/after - draw line
                line_y = draw_rect.top if self.drop_position == 0 else draw_rect.bottom - 1
                pygame.draw.line(surface, drop_color,
                                 (draw_rect.left, line_y), (draw_rect.right, line_y), 3)
        elif self.is_focused:
            pygame.draw.rect(surface, colors.get('focused_bg', pygame.Color(100, 160, 220)), draw_rect)
            # Draw focus border
            pygame.draw.rect(surface, colors.get('focus_border', pygame.Color(255, 255, 255)), draw_rect, 2)
        elif self.is_selected:
            pygame.draw.rect(surface, colors.get('selected_bg', pygame.Color(70, 130, 180)), draw_rect)
        elif self.is_hovered:
            pygame.draw.rect(surface, colors.get('hovered_bg', pygame.Color(60, 60, 60)), draw_rect)

        indent = self.node.get_depth() * self.config.indent_size

        # Draw expand/collapse button
        if self.node.children and self.expand_button_rect:
            center_x = self.expand_button_rect.centerx
            center_y = self.expand_button_rect.centery
            text_color = colors.get('normal_text', pygame.Color(255, 255, 255))

            if self.node.expanded:
                # Draw collapse button (triangle pointing down)
                points = [
                    (center_x - 4, center_y - 2),
                    (center_x + 4, center_y - 2),
                    (center_x, center_y + 3)
                ]
            else:
                # Draw expand button (triangle pointing right)
                points = [
                    (center_x - 2, center_y - 4),
                    (center_x - 2, center_y + 4),
                    (center_x + 3, center_y)
                ]
            pygame.draw.polygon(surface, text_color, points)

        # Draw icon
        icon_x = indent + (20 if self.node.children else 5)
        icon_surface = icon_manager.get_icon(self.node, self.node.expanded)
        icon_y = (draw_rect.height - icon_surface.get_height()) // 2
        surface.blit(icon_surface, (icon_x, icon_y))

        # Draw text - Handle both pygame-gui fonts and regular pygame fonts
        text_x = icon_x + self.config.icon_size[0] + 5
        try:
            text_color = colors.get('normal_text', pygame.Color(255, 255, 255))

            # Check if it's a pygame-gui font (GUIFontPygame) or regular pygame font
            if hasattr(font, 'render_premul'):
                # It's a pygame-gui font - use render_premul
                text_surface = font.render_premul(self.node.name, text_color)
            elif hasattr(font, 'render'):
                # It's a regular pygame font - use render
                text_surface = font.render(self.node.name, True, text_color)
            else:
                # Fallback - create a simple text surface
                fallback_font = pygame.font.Font(None, 16)
                text_surface = fallback_font.render(self.node.name, True, text_color)

            text_y = (draw_rect.height - text_surface.get_height()) // 2
            surface.blit(text_surface, (text_x, text_y))

        except Exception as e:
            if HIERARCHY_DEBUG:
                print(f"Error rendering text for {self.node.name}: {e}")
            # Try fallback rendering
            try:
                fallback_font = pygame.font.Font(None, 16)
                text_surface = fallback_font.render(self.node.name, True, pygame.Color(255, 255, 255))
                text_y = (draw_rect.height - text_surface.get_height()) // 2
                surface.blit(text_surface, (text_x, text_y))
            except:
                pass  # Give up on this text

    def handle_click(self, pos: tuple, panel_rect: pygame.Rect) -> str:
        """Handle click events, return action type"""
        # Convert absolute position to relative position within this node
        relative_pos = (pos[0] - self.rect.x, pos[1] - self.rect.y)

        if self.expand_button_rect and self.expand_button_rect.collidepoint(relative_pos):
            return "expand_toggle"
        return "select"


class HierarchyPanel(UIElement):
    """Main hierarchy panel widget that inherits from UIElement"""

    def __init__(self, relative_rect: pygame.Rect,
                 manager: pygame_gui.UIManager,
                 root_node: HierarchyNode,
                 config: HierarchyConfig = None,
                 container: IContainerLikeInterface = None,
                 object_id: Union[ObjectID, str, None] = None,
                 anchors: Dict[str, str] = None):

        # Handle object_id properly - ObjectID only takes object_id and class_id parameters
        if isinstance(object_id, ObjectID):
            self._object_id = object_id
        elif isinstance(object_id, str):
            self._object_id = ObjectID(object_id=object_id, class_id=None)
        else:
            self._object_id = ObjectID(object_id='#hierarchy_panel', class_id=None)

        super().__init__(relative_rect, manager, container,
                         starting_height=1, layer_thickness=1,
                         anchors=anchors, object_id=self._object_id)

        self.root_node = root_node
        self.config = config or HierarchyConfig()

        # Icon manager
        self.icon_manager = IconManager(manager, self.config.icon_size)

        # UI state
        self.visible_nodes: List[HierarchyNode] = []
        self.node_uis: List[HierarchyNodeUI] = []
        self.selected_node: Optional[HierarchyNode] = None
        self.focused_node: Optional[HierarchyNode] = None
        self.hovered_node: Optional[HierarchyNode] = None
        self.dragging_node: Optional[HierarchyNode] = None
        self.drag_offset = (0, 0)
        self.drop_target: Optional[HierarchyNode] = None
        self.drop_position = 0
        self.is_valid_drop = False

        # Keyboard navigation state
        self.is_focused = False
        self.last_click_time = 0
        self.double_click_time = DOUBLE_CLICK_TIME

        # Scrolling
        self.scroll_y = 0
        self.max_scroll = 0

        # Theme data
        self._update_theme_data()

        # Create the image surface that pygame-gui will draw
        self.image = pygame.Surface(self.rect.size).convert()

        # Set up the initial state
        self.rebuild_ui()
        self._rebuild_image()

    def _update_theme_data(self):
        """Update theme-dependent data"""
        try:
            # Use UIElement's built-in theme access methods instead of calling theme directly
            # This handles the version differences automatically

            self.themed_colors = {}

            # Try to get each color, fall back to defaults if not found
            color_mappings = {
                'dark_bg': pygame.Color(40, 40, 40),
                'normal_text': pygame.Color(255, 255, 255),
                'selected_bg': pygame.Color(70, 130, 180),
                'hovered_bg': pygame.Color(60, 60, 60),
                'focused_bg': pygame.Color(100, 160, 220),
                'normal_border': pygame.Color(100, 100, 100),
                'focus_border': pygame.Color(255, 255, 255),
                'valid_drop': pygame.Color(100, 150, 100),
                'invalid_drop': pygame.Color(150, 80, 80),
            }

            # Try to get themed colors using the manager's theme
            theme = self.ui_manager.get_theme()

            for color_id, default_color in color_mappings.items():
                try:
                    # Try different ways to get the color based on pygame-gui version
                    if hasattr(theme, 'get_colour_or_gradient'):
                        # Build combined IDs manually by concatenating our IDs
                        combined_id_parts = []

                        # Add object IDs (most specific first)
                        if hasattr(self, 'object_ids') and self.object_ids:
                            for obj_id in self.object_ids:
                                if obj_id:
                                    combined_id_parts.append(obj_id)

                        # Add class IDs
                        if hasattr(self, 'class_ids') and self.class_ids:
                            for class_id in self.class_ids:
                                if class_id:
                                    combined_id_parts.append(class_id)

                        # Add element IDs (least specific)
                        if hasattr(self, 'element_ids') and self.element_ids:
                            for elem_id in self.element_ids:
                                if elem_id:
                                    combined_id_parts.append(elem_id)

                        # Try each combined ID from most to least specific
                        color = None
                        for combined_id in combined_id_parts:
                            try:
                                color = theme.get_colour_or_gradient(color_id, [combined_id])
                                break
                            except:
                                continue

                        if color is None:
                            # Try with just the element ID
                            color = theme.get_colour_or_gradient(color_id, ['hierarchy_panel'])

                        self.themed_colors[color_id] = color if color else default_color
                    else:
                        self.themed_colors[color_id] = default_color

                except Exception:
                    self.themed_colors[color_id] = default_color

            # Try to get themed font
            try:
                if hasattr(theme, 'get_font'):
                    self.themed_font = theme.get_font(['hierarchy_panel'])
                else:
                    raise Exception("No font method")
            except Exception:
                # Fallback font
                try:
                    self.themed_font = pygame.font.SysFont('Arial', 14)
                except:
                    self.themed_font = pygame.font.Font(None, 14)

        except Exception as e:
            if HIERARCHY_DEBUG:
                print(f"Error getting theme data: {e}")
            # Complete fallback
            self.themed_colors = {
                'dark_bg': pygame.Color(40, 40, 40),
                'normal_text': pygame.Color(255, 255, 255),
                'selected_bg': pygame.Color(70, 130, 180),
                'hovered_bg': pygame.Color(60, 60, 60),
                'focused_bg': pygame.Color(100, 160, 220),
                'normal_border': pygame.Color(100, 100, 100),
                'focus_border': pygame.Color(255, 255, 255),
                'valid_drop': pygame.Color(100, 150, 100),
                'invalid_drop': pygame.Color(150, 80, 80),
            }
            try:
                self.themed_font = pygame.font.SysFont('Arial', 14)
            except:
                self.themed_font = pygame.font.Font(None, 14)

    def rebuild_from_changed_theme_data(self):
        """Called when theme data changes"""
        self._update_theme_data()
        self.icon_manager.clear_cache()  # Clear cached icons as they may use themed colors
        self.rebuild_ui()
        self._rebuild_image()

    def _can_accept_children(self, node: HierarchyNode) -> bool:
        """Check if a node can accept children based on configuration"""
        if not self.config.folders_only_have_children:
            return True  # Any node can have children

        # Only folders (and root) can have children
        return node.node_type in [HierarchyNodeType.FOLDER, HierarchyNodeType.ROOT]

    def _is_valid_drop_target(self, target: HierarchyNode, position: int) -> bool:
        """Check if a drop operation would be valid"""
        if not target or not self.dragging_node:
            return False

        # Can't drop on self
        if target == self.dragging_node:
            return False

        # Can't drop on descendant
        if self._is_descendant(target, self.dragging_node):
            return False

        # If dropping as child (position 1), check if target can accept children
        if position == 1:
            return self._can_accept_children(target)

        # For before/after drops (position 0/2), we're adding to the target's parent
        # so check if the target's parent can accept children
        if target.parent:
            return self._can_accept_children(target.parent)

        return True

    def _collect_visible_nodes(self, node: HierarchyNode, nodes: List[HierarchyNode]):
        """Collect all visible nodes (accounting for expanded state)"""
        # Skip root if configured
        if node.node_type == HierarchyNodeType.ROOT and not self.config.show_root:
            pass  # Don't add root to visible nodes
        else:
            nodes.append(node)

        # Add children if expanded
        if node.expanded:
            for child in node.children:
                self._collect_visible_nodes(child, nodes)

    def rebuild_ui(self):
        """Rebuild the UI node list"""
        if HIERARCHY_DEBUG:
            print("Rebuilding UI...")

        # Collect visible nodes
        self.visible_nodes.clear()
        self._collect_visible_nodes(self.root_node, self.visible_nodes)

        # Create UI elements with updated positions
        self.node_uis.clear()
        for i, node in enumerate(self.visible_nodes):
            y_pos = i * self.config.node_height - self.scroll_y
            rect = pygame.Rect(
                self.rect.x,
                self.rect.y + y_pos,
                self.rect.width,
                self.config.node_height
            )
            node_ui = HierarchyNodeUI(node, rect, self.config)
            # Preserve selection and focus state
            if node == self.selected_node:
                node_ui.is_selected = True
            if node == self.focused_node:
                node_ui.is_focused = True
            self.node_uis.append(node_ui)

        # Update max scroll
        total_height = len(self.visible_nodes) * self.config.node_height
        self.max_scroll = max(0, total_height - self.rect.height)

        if HIERARCHY_DEBUG:
            print(f"UI rebuilt: {len(self.visible_nodes)} visible nodes, max_scroll: {self.max_scroll}")

    def _rebuild_image(self):
        """Rebuild the image surface that pygame-gui will draw"""
        # Fill background
        bg_color = self.themed_colors.get('dark_bg', pygame.Color(40, 40, 40))
        if hasattr(bg_color, 'apply_gradient_to_surface'):
            # It's a gradient
            bg_color.apply_gradient_to_surface(self.image)
        else:
            # It's a regular color
            self.image.fill(bg_color)

        # Draw nodes
        nodes_drawn = 0
        for i, node_ui in enumerate(self.node_uis):
            y_pos = i * self.config.node_height - self.scroll_y

            # Only draw nodes that are visible in the panel
            if 0 <= y_pos < self.rect.height and y_pos + self.config.node_height > 0:
                # Create a subsurface for this node at the correct Y position
                node_rect = pygame.Rect(0, y_pos, self.rect.width, self.config.node_height)
                node_surface = self.image.subsurface(node_rect)
                surface_rect = pygame.Rect(0, 0, self.rect.width, self.config.node_height)
                node_ui.draw(node_surface, self.themed_font, surface_rect,
                             self.themed_colors, self.icon_manager)
                nodes_drawn += 1

        # Draw border
        border_color = self.themed_colors.get('normal_border', pygame.Color(100, 100, 100))
        pygame.draw.rect(self.image, border_color, self.image.get_rect(), 2)

        # Draw focus indicator if focused
        if self.is_focused:
            focus_color = self.themed_colors.get('focus_border', pygame.Color(255, 255, 255))
            pygame.draw.rect(self.image, focus_color, self.image.get_rect(), 3)

        if HIERARCHY_DEBUG:
            print(f"Image rebuilt: Drew {nodes_drawn} nodes")

    def process_event(self, event: pygame.event.Event) -> bool:
        """Process pygame events - overrides UIElement method"""
        consumed = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.is_focused = True
                if event.button == 1:  # Left click
                    self._handle_left_click(event.pos)
                    consumed = True
                elif event.button == 3:  # Right click
                    self._handle_right_click(event.pos)
                    consumed = True
            else:
                self.is_focused = False

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self.dragging_node:
                self._handle_drop(event.pos)
                consumed = True

        elif event.type == pygame.MOUSEMOTION:
            self._handle_mouse_motion(event.pos)
            if self.dragging_node:
                self._handle_drag(event.pos)
                consumed = True

        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self._handle_scroll(event.y)
                consumed = True

        elif event.type == pygame.KEYDOWN and self.is_focused:
            consumed = self._handle_key_event(event)

        return consumed

    def _handle_key_event(self, event: pygame.event.Event) -> bool:
        """Handle keyboard navigation"""
        if not self.focused_node and self.visible_nodes:
            # No focused node, focus the first one
            self.focused_node = self.visible_nodes[0]
            self.rebuild_ui()
            self._rebuild_image()
            return True

        if not self.focused_node:
            return False

        current_index = -1
        try:
            current_index = self.visible_nodes.index(self.focused_node)
        except ValueError:
            # Focused node not in visible list, reset to first
            self.focused_node = self.visible_nodes[0] if self.visible_nodes else None
            self.rebuild_ui()
            self._rebuild_image()
            return True

        consumed = True
        if event.key == pygame.K_UP:
            # Move focus up
            if current_index > 0:
                self.focused_node = self.visible_nodes[current_index - 1]
                self._ensure_focused_visible()
        elif event.key == pygame.K_DOWN:
            # Move focus down
            if current_index < len(self.visible_nodes) - 1:
                self.focused_node = self.visible_nodes[current_index + 1]
                self._ensure_focused_visible()
        elif event.key == pygame.K_LEFT:
            # Collapse node or move to parent
            if self.focused_node.expanded and self.focused_node.children:
                self._toggle_node_expansion(self.focused_node)
            elif self.focused_node.parent and self.focused_node.parent != self.root_node:
                self.focused_node = self.focused_node.parent
                self._ensure_focused_visible()
        elif event.key == pygame.K_RIGHT:
            # Expand node or move to first child
            if not self.focused_node.expanded and self.focused_node.children:
                self._toggle_node_expansion(self.focused_node)
            elif self.focused_node.expanded and self.focused_node.children:
                self.focused_node = self.focused_node.children[0]
                self._ensure_focused_visible()
        elif event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
            # Select focused node or toggle expansion
            if event.key == pygame.K_SPACE and self.focused_node.children:
                self._toggle_node_expansion(self.focused_node)
            else:
                self._select_node(self.focused_node)
        elif event.key == pygame.K_HOME:
            # Move to first node
            if self.visible_nodes:
                self.focused_node = self.visible_nodes[0]
                self._ensure_focused_visible()
        elif event.key == pygame.K_END:
            # Move to last node
            if self.visible_nodes:
                self.focused_node = self.visible_nodes[-1]
                self._ensure_focused_visible()
        else:
            consumed = False

        if consumed:
            self.rebuild_ui()
            self._rebuild_image()

        return consumed

    def _ensure_focused_visible(self):
        """Ensure the focused node is visible in the viewport"""
        if not self.focused_node:
            return

        try:
            focused_index = self.visible_nodes.index(self.focused_node)
            focused_y = focused_index * self.config.node_height

            # Check if focused node is above viewport
            if focused_y < self.scroll_y:
                self.scroll_y = focused_y
            # Check if focused node is below viewport
            elif focused_y + self.config.node_height > self.scroll_y + self.rect.height:
                self.scroll_y = focused_y + self.config.node_height - self.rect.height

            # Clamp scroll
            self.scroll_y = max(0, min(self.max_scroll, self.scroll_y))
        except ValueError:
            pass

    def _toggle_node_expansion(self, node: HierarchyNode):
        """Toggle node expansion and fire appropriate event"""
        node.expanded = not node.expanded

        event_type = UI_HIERARCHY_NODE_EXPANDED if node.expanded else UI_HIERARCHY_NODE_COLLAPSED
        event_data = {
            'node': node,
            'ui_element': self,
            'expanded': node.expanded
        }
        pygame.event.post(pygame.event.Event(event_type, event_data))

        self.rebuild_ui()
        self._rebuild_image()

    def _select_node(self, node: HierarchyNode):
        """Select a node and fire selection event"""
        self.selected_node = node
        self.focused_node = node

        event_data = {
            'node': node,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_HIERARCHY_NODE_SELECTED, event_data))

        self._rebuild_image()

    def _handle_left_click(self, pos: tuple):
        """Handle left mouse click"""
        clicked_node = self._get_node_at_position(pos)
        if clicked_node:
            # Check for double click
            current_time = pygame.time.get_ticks()
            is_double_click = (current_time - self.last_click_time < self.double_click_time and
                               clicked_node == self.selected_node)
            self.last_click_time = current_time

            node_ui = next((ui for ui in self.node_uis if ui.node == clicked_node), None)
            if node_ui:
                action = node_ui.handle_click(pos, self.rect)
                if action == "expand_toggle":
                    self._toggle_node_expansion(clicked_node)
                elif action == "select":
                    self._select_node(clicked_node)
                    self.focused_node = clicked_node

                    # Fire double click event if applicable
                    if is_double_click:
                        event_data = {
                            'node': clicked_node,
                            'ui_element': self
                        }
                        pygame.event.post(pygame.event.Event(UI_HIERARCHY_NODE_DOUBLE_CLICKED, event_data))

                    # Start drag if enabled
                    if self.config.allow_drag:
                        self.dragging_node = clicked_node
                        self.drag_offset = (pos[0] - node_ui.rect.x, pos[1] - node_ui.rect.y)

                        event_data = {
                            'node': clicked_node,
                            'ui_element': self
                        }
                        pygame.event.post(pygame.event.Event(UI_HIERARCHY_DRAG_STARTED, event_data))

    def _handle_right_click(self, pos: tuple):
        """Handle right mouse click"""
        clicked_node = self._get_node_at_position(pos)
        if clicked_node:
            event_data = {
                'node': clicked_node,
                'ui_element': self,
                'mouse_pos': pos
            }
            pygame.event.post(pygame.event.Event(UI_HIERARCHY_NODE_RIGHT_CLICKED, event_data))

    def _handle_mouse_motion(self, pos: tuple):
        """Handle mouse movement"""
        if self.rect.collidepoint(pos):
            new_hovered = self._get_node_at_position(pos)
            if new_hovered != self.hovered_node:
                if self.hovered_node:
                    node_ui = next((ui for ui in self.node_uis if ui.node == self.hovered_node), None)
                    if node_ui:
                        node_ui.is_hovered = False

                self.hovered_node = new_hovered
                if self.hovered_node:
                    node_ui = next((ui for ui in self.node_uis if ui.node == self.hovered_node), None)
                    if node_ui:
                        node_ui.is_hovered = True

                self._rebuild_image()

    def _handle_drag(self, pos: tuple):
        """Handle drag operation"""
        if not self.dragging_node:
            return

        # Clear previous drop target
        self.drop_target = None
        self.is_valid_drop = False

        # Find potential drop target
        if self.rect.collidepoint(pos):
            target_node = self._get_node_at_position(pos)
            if target_node and target_node != self.dragging_node:
                # Determine drop position
                node_ui = next((ui for ui in self.node_uis if ui.node == target_node), None)
                if node_ui:
                    relative_y = pos[1] - node_ui.rect.y
                    if relative_y < node_ui.rect.height * DROP_ZONE_RATIO:
                        self.drop_position = 0  # Before
                    elif relative_y > node_ui.rect.height * (1 - DROP_ZONE_RATIO):
                        self.drop_position = 2  # After
                    else:
                        self.drop_position = 1  # As child

                    self.drop_target = target_node
                    self.is_valid_drop = self._is_valid_drop_target(target_node, self.drop_position)

        # Update drop target UI highlighting
        for node_ui in self.node_uis:
            if node_ui.node == self.drop_target:
                node_ui.is_drop_target = self.is_valid_drop
                node_ui.is_invalid_drop_target = not self.is_valid_drop
                node_ui.drop_position = self.drop_position
            else:
                node_ui.is_drop_target = False
                node_ui.is_invalid_drop_target = False
                node_ui.drop_position = None

        self._rebuild_image()

    def _handle_drop(self, pos: tuple):
        """Handle drop operation"""
        if self.dragging_node and self.drop_target and self.config.allow_drop and self.is_valid_drop:
            self._perform_drop()
        elif not self.is_valid_drop and self.drop_target:
            if HIERARCHY_DEBUG:
                print(f"Drop rejected: Invalid target for {self.dragging_node.name}")

        # Clean up drag state
        self.dragging_node = None
        self.drop_target = None
        self.is_valid_drop = False
        for node_ui in self.node_uis:
            node_ui.is_drop_target = False
            node_ui.is_invalid_drop_target = False
            node_ui.drop_position = None

        self._rebuild_image()

    def _perform_drop(self):
        """Perform the actual drop operation"""
        if not (self.dragging_node and self.drop_target):
            return

        if HIERARCHY_DEBUG:
            print(f"Performing drop: {self.dragging_node.name} -> {self.drop_target.name} (position: {self.drop_position})")

        # Store old parent for event
        old_parent = self.dragging_node.parent

        # Remove from current parent
        if self.dragging_node.parent:
            self.dragging_node.parent.remove_child(self.dragging_node)

        # Add to new location
        if self.drop_position == 1:  # As child
            self.drop_target.add_child(self.dragging_node)
            # Expand target to show the new child
            self.drop_target.expanded = True
        else:  # Before or after
            target_parent = self.drop_target.parent
            if target_parent:
                target_index = target_parent.children.index(self.drop_target)
                if self.drop_position == 2:  # After
                    target_index += 1

                target_parent.children.insert(target_index, self.dragging_node)
                self.dragging_node.parent = target_parent

        # Fire drop completed event
        event_data = {
            'dragged_node': self.dragging_node,
            'target_node': self.drop_target,
            'old_parent': old_parent,
            'new_parent': self.dragging_node.parent,
            'drop_position': self.drop_position,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_HIERARCHY_DROP_COMPLETED, event_data))

        # Rebuild UI to reflect changes
        self.rebuild_ui()
        self._rebuild_image()

        if HIERARCHY_DEBUG:
            print(f"Drop completed. New parent: {self.dragging_node.parent.name if self.dragging_node.parent else 'None'}")

    def _handle_scroll(self, delta: int):
        """Handle scroll wheel"""
        scroll_speed = self.config.node_height * 3
        old_scroll = self.scroll_y
        self.scroll_y = max(0, min(self.max_scroll, self.scroll_y - delta * scroll_speed))
        if old_scroll != self.scroll_y:
            self.rebuild_ui()
            self._rebuild_image()

    def _get_node_at_position(self, pos: tuple) -> Optional[HierarchyNode]:
        """Get the node at the given position"""
        for node_ui in self.node_uis:
            if node_ui.rect.collidepoint(pos):
                return node_ui.node
        return None

    @staticmethod
    def _is_descendant(potential_descendant: HierarchyNode, ancestor: HierarchyNode) -> bool:
        """Check if a node is a descendant of another"""
        current = potential_descendant.parent
        while current:
            if current == ancestor:
                return True
            current = current.parent
        return False

    def update(self, time_delta: float):
        """Update the panel - overrides UIElement method"""
        super().update(time_delta)

        # Update UI state
        for node_ui in self.node_uis:
            node_ui.is_selected = (node_ui.node == self.selected_node)
            node_ui.is_focused = (node_ui.node == self.focused_node)

    # Public API methods for external control
    def set_selected_node(self, node_id: str):
        """Programmatically select a node by ID"""
        node = self.root_node.find_node(node_id)
        if node:
            self._select_node(node)
            self.rebuild_ui()
            self._rebuild_image()

    def expand_node(self, node_id: str):
        """Programmatically expand a node by ID"""
        node = self.root_node.find_node(node_id)
        if node and not node.expanded:
            self._toggle_node_expansion(node)

    def collapse_node(self, node_id: str):
        """Programmatically collapse a node by ID"""
        node = self.root_node.find_node(node_id)
        if node and node.expanded:
            self._toggle_node_expansion(node)

    def get_selected_node(self) -> Optional[HierarchyNode]:
        """Get the currently selected node"""
        return self.selected_node

    def refresh(self):
        """Refresh the hierarchy display"""
        self.rebuild_ui()
        self._rebuild_image()

    def load_icons_from_directory(self, icon_directory: str):
        """Load custom icons from a directory"""
        if os.path.exists(icon_directory):
            self.icon_manager.icon_directory = icon_directory
            self.icon_manager.clear_cache()
        else:
            if HIERARCHY_DEBUG:
                print(f"Icon directory not found: {icon_directory}")


# Example theme file for the hierarchy panel
EXAMPLE_THEME = {
    "hierarchy_panel": {
        "colours": {
            "dark_bg": "#2b2b2b",
            "normal_text": "#ffffff",
            "selected_bg": "#4682b4",
            "hovered_bg": "#3c3c3c",
            "focused_bg": "#64a0dc",
            "normal_border": "#646464",
            "focus_border": "#ffffff",
            "valid_drop": "#649650",
            "invalid_drop": "#965050"
        },
        "font": {
            "name": "arial",
            "size": "14",
            "bold": "0",
            "italic": "0"
        },
        "misc": {
            "border_width": "2",
            "shadow_width": "0"
        }
    },
    "@file_hierarchy": {
        "colours": {
            "dark_bg": "#1e1e1e",
            "normal_text": "#d4d4d4"
        }
    },
    "#project_explorer": {
        "colours": {
            "selected_bg": "#37373d"
        }
    }
}


# Example usage with theme support
def create_sample_hierarchy() -> HierarchyNode:
    """Create a sample hierarchy for testing"""
    root = HierarchyNode("root", "Root", HierarchyNodeType.ROOT)

    # Add some folders and items with custom icons
    folder1 = HierarchyNode("folder1", "Documents", HierarchyNodeType.FOLDER, icon_name="documents")
    folder2 = HierarchyNode("folder2", "Images", HierarchyNodeType.FOLDER, icon_name="images")
    folder3 = HierarchyNode("folder3", "Code", HierarchyNodeType.FOLDER, icon_name="code")

    item1 = HierarchyNode("item1", "readme.txt", HierarchyNodeType.ITEM, icon_name="text")
    item2 = HierarchyNode("item2", "photo.jpg", HierarchyNodeType.ITEM, icon_name="image")
    item3 = HierarchyNode("item3", "main.py", HierarchyNodeType.ITEM, icon_name="python")
    item4 = HierarchyNode("item4", "config.json", HierarchyNodeType.ITEM, icon_name="json")

    root.add_child(folder1)
    root.add_child(folder2)
    root.add_child(folder3)

    folder1.add_child(item1)
    folder1.add_child(item4)
    folder2.add_child(item2)
    folder3.add_child(item3)

    # Add nested folder
    subfolder = HierarchyNode("subfolder1", "Python Scripts", HierarchyNodeType.FOLDER, icon_name="python_folder")
    nested_item = HierarchyNode("nested1", "utils.py", HierarchyNodeType.ITEM, icon_name="python")
    subfolder.add_child(nested_item)
    folder3.add_child(subfolder)

    return root


def main():
    """Example: demonstration of the Hierarchy Panel"""
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Hierarchy Panel")
    clock = pygame.time.Clock()

    # Create manager with theme
    manager = pygame_gui.UIManager((800, 600), EXAMPLE_THEME)

    # Create hierarchy
    root_node = create_sample_hierarchy()

    if HIERARCHY_DEBUG:
        print(f"Created hierarchy with root: {root_node.name}, children: {len(root_node.children)}")

    # Configure
    config = HierarchyConfig()
    config.folders_only_have_children = True  # Enable folders-only mode
    config.icon_size = (16, 16)

    # Create hierarchy panel with different theme IDs
    hierarchy_panel = HierarchyPanel(
        pygame.Rect(50, 50, 300, 400),
        manager,
        root_node,
        config,
        object_id=ObjectID(object_id='#project_explorer', class_id='@file_hierarchy')
    )

    # Load custom icons if available
    if os.path.exists("icons"):
        hierarchy_panel.load_icons_from_directory("icons")

    # Add instructions
    print("\nHierarchy Panel")
    print("\nFeatures:")
    print("- Theme support with custom colors and fonts")
    print("- Icon system with custom icon loading")
    print("- Object ID support for specific theming")

    print("\nMouse controls:")
    print("- Click to select")
    print("- Double-click for double-click events")
    print("- Right-click for context events")
    print("- Drag and drop to move nodes")
    print("- Scroll wheel to scroll")

    print("\nKeyboard controls (when focused):")
    print("- Arrow keys to navigate")
    print("- Enter/Space to select/toggle")
    print("- Home/End to jump to first/last")
    print("- Left/Right to collapse/expand")

    print("\nPress T to toggle theme, F to toggle folders-only mode\n")

    # Alternative theme
    alt_theme = {
        "hierarchy_panel": {
            "colours": {
                "dark_bg": "#1a1a1a",
                "normal_text": "#e0e0e0",
                "selected_bg": "#0078d4",
                "hovered_bg": "#2a2a2a",
                "focused_bg": "#005a9e",
                "normal_border": "#404040",
                "focus_border": "#ffffff",
                "valid_drop": "#508050",
                "invalid_drop": "#805050"
            },
            "font": {
                "name": "arial",
                "size": "16",
                "bold": "1"
            }
        },
        "@file_hierarchy": {
            "colours": {
                "dark_bg": "#0d1117",
                "normal_text": "#c9d1d9",
                "selected_bg": "#21262d"
            }
        }
    }

    running = True
    using_alt_theme = False

    while running:
        time_delta = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f:
                    # Toggle folders-only mode
                    config.folders_only_have_children = not config.folders_only_have_children
                    if HIERARCHY_DEBUG:
                        print(f"Toggled folders_only_have_children = {config.folders_only_have_children}")
                elif event.key == pygame.K_t:
                    # Toggle theme
                    using_alt_theme = not using_alt_theme
                    if using_alt_theme:
                        manager.get_theme().load_theme(alt_theme)
                    else:
                        manager.get_theme().load_theme(EXAMPLE_THEME)

                    # Manually trigger theme rebuild for our custom element
                    hierarchy_panel.rebuild_from_changed_theme_data()

                    if HIERARCHY_DEBUG:
                        print(f"Switched to {'alternative' if using_alt_theme else 'default'} theme")

            # Handle custom hierarchy events
            elif event.type == UI_HIERARCHY_NODE_SELECTED:
                if HIERARCHY_DEBUG:
                    print(f"Event: Node selected - {event.node.name}")
            elif event.type == UI_HIERARCHY_NODE_DOUBLE_CLICKED:
                if HIERARCHY_DEBUG:
                    print(f"Event: Node double-clicked - {event.node.name}")
            elif event.type == UI_HIERARCHY_NODE_RIGHT_CLICKED:
                if HIERARCHY_DEBUG:
                    print(f"Event: Node right-clicked - {event.node.name}")
            elif event.type == UI_HIERARCHY_NODE_EXPANDED:
                if HIERARCHY_DEBUG:
                    print(f"Event: Node expanded - {event.node.name}")
            elif event.type == UI_HIERARCHY_NODE_COLLAPSED:
                if HIERARCHY_DEBUG:
                    print(f"Event: Node collapsed - {event.node.name}")
            elif event.type == UI_HIERARCHY_DRAG_STARTED:
                if HIERARCHY_DEBUG:
                    print(f"Event: Drag started - {event.node.name}")
            elif event.type == UI_HIERARCHY_DROP_COMPLETED:
                if HIERARCHY_DEBUG:
                    print(f"Event: Drop completed - {event.dragged_node.name}"
                          f" -> {event.new_parent.name if event.new_parent else 'Root'}")

            manager.process_events(event)

        manager.update(time_delta)

        screen.fill((30, 30, 30))
        manager.draw_ui(screen)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
