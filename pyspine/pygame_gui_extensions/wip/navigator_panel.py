import pygame
import pygame_gui
from pygame_gui.core import UIElement, ObjectID
from pygame_gui.core.interfaces import IContainerLikeInterface
from typing import List, Optional, Dict, Any, Union, Callable, Tuple, Protocol
from dataclasses import dataclass, field
from enum import Enum

try:
    from pygame_gui.core.interfaces.gui_font_interface import IGUIFontInterface
except ImportError:
    IGUIFontInterface = None

NAVIGATOR_DEBUG = False

# Constants
DEFAULT_ZOOM_LEVELS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 5.0]
MIN_VIEWPORT_SIZE = 5
ZOOM_WHEEL_FACTOR = 1.1
PAN_SENSITIVITY = 1.0

# Define custom pygame-gui events
UI_NAVIGATOR_VIEWPORT_CHANGED = pygame.USEREVENT + 100
UI_NAVIGATOR_ZOOM_CHANGED = pygame.USEREVENT + 101
UI_NAVIGATOR_NAVIGATION_CLICKED = pygame.USEREVENT + 102
UI_NAVIGATOR_FIT_REQUESTED = pygame.USEREVENT + 103
UI_NAVIGATOR_ZOOM_TO_SELECTION = pygame.USEREVENT + 104


class NavigatorMode(Enum):
    """Display modes for the navigator"""
    THUMBNAIL = "thumbnail"  # Show scaled-down content
    WIREFRAME = "wireframe"  # Show outline/structure only
    CUSTOM = "custom"  # Use custom drawing function


class ZoomMode(Enum):
    """Zoom behavior modes"""
    FIT_WIDTH = "fit_width"
    FIT_HEIGHT = "fit_height"
    FIT_ALL = "fit_all"
    ACTUAL_SIZE = "actual_size"
    CUSTOM = "custom"


class NavigatorViewport:
    """Information about the current viewport"""
    # Content coordinates (what part of the content is visible)

    def __init__(self,
                 content_x: float = 0.0, content_y: float = 0.0,
                 content_width: float = 100.0, content_height: float = 100.0,
                 zoom: float = 1.0,
                 total_content_width: float = 100.0, total_content_height: float = 100.0,
                 display_mode: NavigatorMode = NavigatorMode.THUMBNAIL):

        self.content_x: float = content_x
        self.content_y: float = content_y
        self.content_width: float = content_width
        self.content_height: float = content_height

        # Zoom level (1.0 = 100%)
        self.zoom: float = zoom

        # Total content size
        self.total_content_width: float = total_content_width
        self.total_content_height: float = total_content_height

        # Display mode
        self.display_mode: NavigatorMode = display_mode

    def get_center(self) -> Tuple[float, float]:
        """Get viewport center in content coordinates"""
        return (
            self.content_x + self.content_width / 2,
            self.content_y + self.content_height / 2
        )

    def set_center(self, x: float, y: float):
        """Set viewport center in content coordinates"""
        self.content_x = x - self.content_width / 2
        self.content_y = y - self.content_height / 2
        self.clamp_to_content()

    def clamp_to_content(self):
        """Ensure viewport stays within content bounds"""
        # Handle case where viewport is larger than content
        if self.content_width >= self.total_content_width:
            self.content_x = -(self.content_width - self.total_content_width) / 2
        else:
            self.content_x = max(0, int(min(self.content_x, self.total_content_width - self.content_width)))

        if self.content_height >= self.total_content_height:
            self.content_y = -(self.content_height - self.total_content_height) / 2
        else:
            self.content_y = max(0, int(min(self.content_y, self.total_content_height - self.content_height)))

    def contains_point(self, x: float, y: float) -> bool:
        """Check if a point is within the viewport"""
        return (self.content_x <= x <= self.content_x + self.content_width and
                self.content_y <= y <= self.content_y + self.content_height)


class ContentProvider(Protocol):
    """Protocol for content providers - implement this to provide content to the navigator"""

    def get_content_size(self) -> Tuple[float, float]:
        """Return the total size of the content"""
        ...

    def render_thumbnail(self, surface: pygame.Surface, thumbnail_rect: pygame.Rect,
                         viewport: NavigatorViewport) -> None:
        """Render content thumbnail to the given surface and rect"""
        ...

    def get_selection_bounds(self) -> Optional[pygame.Rect]:
        """Return bounds of current selection, if any"""
        ...


@dataclass
class NavigatorConfig:
    """Configuration for the navigator panel"""
    # Display settings
    mode: NavigatorMode = NavigatorMode.THUMBNAIL
    show_viewport_outline: bool = True
    show_zoom_controls: bool = True
    show_coordinates: bool = False

    # Viewport appearance
    viewport_color: pygame.Color = field(default_factory=lambda: pygame.Color(255, 255, 255, 180))
    viewport_border_color: pygame.Color = field(default_factory=lambda: pygame.Color(255, 255, 255))
    viewport_border_width: int = 2
    selection_color: pygame.Color = field(default_factory=lambda: pygame.Color(255, 255, 0, 100))

    # Zoom settings
    zoom_levels: List[float] = field(default_factory=lambda: DEFAULT_ZOOM_LEVELS.copy())
    min_zoom: float = 0.1
    max_zoom: float = 10.0
    zoom_wheel_enabled: bool = True

    # Navigation settings
    click_to_navigate: bool = True
    drag_to_pan: bool = True
    pan_sensitivity: float = PAN_SENSITIVITY

    # Layout
    zoom_control_height: int = 30
    padding: int = 4

    # Performance
    update_on_viewport_change: bool = True
    thumbnail_cache_enabled: bool = True
    max_thumbnail_size: Tuple[int, int] = (512, 512)

    # Custom drawing
    custom_draw_function: Optional[Callable[[pygame.Surface, pygame.Rect, NavigatorViewport], None]] = None


class ImageContentProvider:
    """Content provider for pygame surfaces/images"""

    def __init__(self, image: pygame.Surface):
        self.image = image
        self.selection_rect: Optional[pygame.Rect] = None

    def get_content_size(self) -> Tuple[float, float]:
        return float(self.image.get_width()), float(self.image.get_height())

    # def render_thumbnail(self, surface: pygame.Surface, thumbnail_rect: pygame.Rect, viewport: ViewportInfo) -> None:
    def render_thumbnail(self, surface: pygame.Surface, thumbnail_rect: pygame.Rect) -> None:
        # Scale image to fit thumbnail rect while maintaining aspect ratio
        img_w, img_h = self.image.get_size()
        scale_x = thumbnail_rect.width / img_w
        scale_y = thumbnail_rect.height / img_h
        scale = min(scale_x, scale_y)

        scaled_w = int(img_w * scale)
        scaled_h = int(img_h * scale)

        if scaled_w > 0 and scaled_h > 0:
            scaled_image = pygame.transform.scale(self.image, (scaled_w, scaled_h))

            # Center the scaled image in the thumbnail rect
            x = thumbnail_rect.x + (thumbnail_rect.width - scaled_w) // 2
            y = thumbnail_rect.y + (thumbnail_rect.height - scaled_h) // 2

            surface.blit(scaled_image, (x, y))

    def get_selection_bounds(self) -> Optional[pygame.Rect]:
        return self.selection_rect

    def set_selection(self, rect: Optional[pygame.Rect]):
        self.selection_rect = rect


class NodeGraphContentProvider:
    """Content provider for node graphs or diagrams"""

    def __init__(self, content_size: Tuple[float, float]):
        self.content_size = content_size
        self.nodes: List[Dict[str, Any]] = []
        self.connections: List[Tuple[int, int]] = []
        self.selection: List[int] = []

    def get_content_size(self) -> Tuple[float, float]:
        return self.content_size

    def add_node(self, x: float, y: float, width: float = 100, height: float = 50,
                 label: str = "", color: pygame.Color = pygame.Color(100, 150, 200)):
        """Add a node to the graph"""
        node = {
            'x': x, 'y': y, 'width': width, 'height': height,
            'label': label, 'color': color
        }
        self.nodes.append(node)
        return len(self.nodes) - 1

    def add_connection(self, from_node: int, to_node: int):
        """Add a connection between nodes"""
        if 0 <= from_node < len(self.nodes) and 0 <= to_node < len(self.nodes):
            self.connections.append((from_node, to_node))

    def render_thumbnail(self, surface: pygame.Surface, thumbnail_rect: pygame.Rect,
                         viewport: NavigatorViewport) -> None:
        if not self.nodes:
            return

        # Calculate scale to fit content in thumbnail - SAME AS _content_to_thumbnail_rect
        content_w, content_h = self.content_size
        scale_x = thumbnail_rect.width / content_w
        scale_y = thumbnail_rect.height / content_h
        scale = min(scale_x, scale_y)

        # Calculate scaled content size and offset for centering - SAME AS _content_to_thumbnail_rect
        scaled_content_w = content_w * scale
        scaled_content_h = content_h * scale
        offset_x = (thumbnail_rect.width - scaled_content_w) / 2
        offset_y = (thumbnail_rect.height - scaled_content_h) / 2

        # Check if we're in wireframe mode
        wireframe_mode = hasattr(viewport, 'display_mode') and viewport.display_mode == NavigatorMode.WIREFRAME

        # Draw connections first (so they appear behind nodes)
        for from_idx, to_idx in self.connections:
            if from_idx < len(self.nodes) and to_idx < len(self.nodes):
                from_node = self.nodes[from_idx]
                to_node = self.nodes[to_idx]

                # Calculate scaled positions. Use same coordinate transformation
                from_x = thumbnail_rect.x + offset_x + (from_node['x'] + from_node['width'] / 2) * scale
                from_y = thumbnail_rect.y + offset_y + (from_node['y'] + from_node['height'] / 2) * scale
                to_x = thumbnail_rect.x + offset_x + (to_node['x'] + to_node['width'] / 2) * scale
                to_y = thumbnail_rect.y + offset_y + (to_node['y'] + to_node['height'] / 2) * scale

                line_color = pygame.Color(120, 120, 120) if not wireframe_mode else pygame.Color(100, 100, 100)
                pygame.draw.line(surface, line_color,
                                 (int(from_x), int(from_y)), (int(to_x), int(to_y)), 1)

        # Draw nodes
        for i, node in enumerate(self.nodes):
            # Calculate scaled position and size. Use same coordinate transformation
            x = thumbnail_rect.x + offset_x + node['x'] * scale
            y = thumbnail_rect.y + offset_y + node['y'] * scale
            w = max(2, node['width'] * scale)
            h = max(2, node['height'] * scale)

            node_rect = pygame.Rect(int(x), int(y), int(w), int(h))

            if wireframe_mode:
                # Wireframe mode: just draw outlines
                border_color = pygame.Color(150, 150, 150)
                if i in self.selection:
                    border_color = pygame.Color(255, 255, 100)  # Yellow for selected
                pygame.draw.rect(surface, border_color, node_rect, 1)
            else:
                # Normal mode: draw filled rectangles
                color = node['color']
                if i in self.selection:
                    color = pygame.Color(255, 255, 100)  # Yellow for selected

                pygame.draw.rect(surface, color, node_rect)
                pygame.draw.rect(surface, pygame.Color(80, 80, 80), node_rect, 1)

    def get_selection_bounds(self) -> Optional[pygame.Rect]:
        if not self.selection:
            return None

        # Calculate bounding box of selected nodes
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')

        for node_idx in self.selection:
            if 0 <= node_idx < len(self.nodes):
                node = self.nodes[node_idx]
                min_x = min(min_x, node['x'])
                min_y = min(min_y, node['y'])
                max_x = max(max_x, node['x'] + node['width'])
                max_y = max(max_y, node['y'] + node['height'])

        if min_x != float('inf'):
            return pygame.Rect(int(min_x), int(min_y),
                               int(max_x - min_x), int(max_y - min_y))
        return None

    def set_selection(self, node_indices: List[int]):
        self.selection = [i for i in node_indices if 0 <= i < len(self.nodes)]


class FunctionContentProvider:
    """Content provider using custom drawing function"""

    def __init__(self, content_size: Tuple[float, float],
                 draw_function: Callable[[pygame.Surface, pygame.Rect, NavigatorViewport], None]):
        self.content_size = content_size
        self.draw_function = draw_function
        self.selection_bounds: Optional[pygame.Rect] = None

    def get_content_size(self) -> Tuple[float, float]:
        return self.content_size

    def render_thumbnail(self, surface: pygame.Surface, thumbnail_rect: pygame.Rect,
                         viewport: NavigatorViewport) -> None:
        self.draw_function(surface, thumbnail_rect, viewport)

    def get_selection_bounds(self) -> Optional[pygame.Rect]:
        return self.selection_bounds

    def set_selection_bounds(self, rect: Optional[pygame.Rect]):
        self.selection_bounds = rect


class ZoomControl:
    """Zoom control overlay for the navigator"""

    def __init__(self, rect: pygame.Rect, config: NavigatorConfig):
        self.rect = rect
        self.config = config

        # Button layout
        button_width = 25
        button_spacing = 2
        total_button_width = button_width * 4 + button_spacing * 3

        start_x = rect.x + (rect.width - total_button_width) // 2
        y = rect.y + (rect.height - button_width) // 2

        self.zoom_in_rect = pygame.Rect(start_x, y, button_width, button_width)
        self.zoom_out_rect = pygame.Rect(start_x + button_width + button_spacing, y, button_width, button_width)
        self.fit_rect = pygame.Rect(start_x + (button_width + button_spacing) * 2, y, button_width, button_width)
        self.actual_size_rect = pygame.Rect(start_x + (button_width + button_spacing) * 3, y, button_width,
                                            button_width)

        # Hover states
        self.hovered_button = None

    def draw(self, surface: pygame.Surface, current_zoom: float, colors: Dict[str, pygame.Color]):
        """Draw zoom controls"""
        # Background
        bg_color = colors.get('control_bg', pygame.Color(60, 60, 60, 200))
        if hasattr(bg_color, 'apply_gradient_to_surface'):
            # Create subsurface and apply gradient
            try:
                zoom_surface = surface.subsurface(self.rect)
                bg_color.apply_gradient_to_surface(zoom_surface)
            except (ValueError, pygame.error):
                pygame.draw.rect(surface, bg_color, self.rect)
        else:
            pygame.draw.rect(surface, bg_color, self.rect)

        # Border
        border_color = colors.get('control_border', pygame.Color(100, 100, 100))
        pygame.draw.rect(surface, border_color, self.rect, 1)

        # Buttons
        buttons = [
            (self.zoom_in_rect, "+", "zoom_in"),
            (self.zoom_out_rect, "-", "zoom_out"),
            (self.fit_rect, "F", "fit"),
            (self.actual_size_rect, "1", "actual")
        ]

        text_color = colors.get('control_text', pygame.Color(255, 255, 255))
        hover_color = colors.get('hovered_bg', pygame.Color(80, 80, 80))

        for button_rect, text, button_id in buttons:
            # Button background
            if self.hovered_button == button_id:
                pygame.draw.rect(surface, hover_color, button_rect)

            # Button border
            pygame.draw.rect(surface, border_color, button_rect, 1)

            # Button text
            font = pygame.font.Font(None, 16)
            try:
                text_surface = font.render(text, True, text_color)
                text_rect = text_surface.get_rect(center=button_rect.center)
                surface.blit(text_surface, text_rect)
            except Exception:
                pass

        # Zoom level display
        zoom_text = f"{current_zoom * 100:.0f}%"
        try:
            font = pygame.font.Font(None, 14)
            zoom_surface = font.render(zoom_text, True, text_color)
            zoom_rect = zoom_surface.get_rect()
            zoom_rect.centerx = self.rect.centerx
            zoom_rect.bottom = self.rect.bottom - 2
            surface.blit(zoom_surface, zoom_rect)
        except Exception:
            pass

    def handle_click(self, pos: Tuple[int, int]) -> Optional[str]:
        """Handle click on zoom controls, return action"""
        if self.zoom_in_rect.collidepoint(pos):
            return "zoom_in"
        elif self.zoom_out_rect.collidepoint(pos):
            return "zoom_out"
        elif self.fit_rect.collidepoint(pos):
            return "fit"
        elif self.actual_size_rect.collidepoint(pos):
            return "actual_size"
        return None

    def handle_hover(self, pos: Tuple[int, int]) -> bool:
        """Handle hover over zoom controls, return True if hover state changed"""
        old_hovered = self.hovered_button

        if self.zoom_in_rect.collidepoint(pos):
            self.hovered_button = "zoom_in"
        elif self.zoom_out_rect.collidepoint(pos):
            self.hovered_button = "zoom_out"
        elif self.fit_rect.collidepoint(pos):
            self.hovered_button = "fit"
        elif self.actual_size_rect.collidepoint(pos):
            self.hovered_button = "actual"
        else:
            self.hovered_button = None

        return old_hovered != self.hovered_button


class NavigatorPanel(UIElement):
    """Main navigator panel widget"""

    def __init__(self, relative_rect: pygame.Rect,
                 manager: pygame_gui.UIManager,
                 content_provider: ContentProvider,
                 viewport: NavigatorViewport = None,
                 config: NavigatorConfig = None,
                 container: IContainerLikeInterface = None,
                 object_id: Union[ObjectID, str, None] = None,
                 anchors: Dict[str, str] = None):

        # Handle object_id properly
        if isinstance(object_id, ObjectID):
            self._object_id = object_id
        elif isinstance(object_id, str):
            self._object_id = ObjectID(object_id=object_id, class_id=None)
        else:
            self._object_id = ObjectID(object_id='#navigator_panel', class_id=None)

        super().__init__(relative_rect, manager, container,
                         starting_height=1, layer_thickness=1,
                         anchors=anchors, object_id=self._object_id)

        self.content_provider = content_provider
        self.viewport = viewport or NavigatorViewport()
        self.config = config or NavigatorConfig()

        # Initialize viewport size based on content
        content_w, content_h = self.content_provider.get_content_size()
        self.viewport.total_content_width = content_w
        self.viewport.total_content_height = content_h

        # UI state
        self.is_dragging = False
        self.drag_start_pos = (0, 0)
        self.drag_start_viewport = None
        self.is_focused = False
        self.thumbnail_cache: Optional[pygame.Surface] = None
        self.cache_invalid = True

        # Calculate layout
        self._calculate_layout()

        # Zoom control
        if self.config.show_zoom_controls:
            zoom_rect = pygame.Rect(0, self.thumbnail_rect.bottom + 2,
                                    self.rect.width, self.config.zoom_control_height)
            self.zoom_control = ZoomControl(zoom_rect, self.config)
        else:
            self.zoom_control = None

        # Theme data
        self._update_theme_data()

        # Create image surface
        self.image = pygame.Surface(self.rect.size).convert()

        # Initial render
        self._rebuild_image()

    def _calculate_layout(self):
        """Calculate layout rectangles"""
        padding = self.config.padding

        # Thumbnail area
        available_height = self.rect.height - 2 * padding
        if self.config.show_zoom_controls:
            available_height -= self.config.zoom_control_height + 2

        self.thumbnail_rect = pygame.Rect(
            padding, padding,
            self.rect.width - 2 * padding,
            available_height
        )

    def _update_theme_data(self):
        """Update theme-dependent data"""
        try:
            self.themed_colors = {}

            color_mappings = {
                'dark_bg': pygame.Color(30, 30, 30),
                'thumbnail_bg': pygame.Color(45, 45, 45),
                'normal_border': pygame.Color(100, 100, 100),
                'focused_border': pygame.Color(120, 160, 255),
                'control_bg': pygame.Color(60, 60, 60),
                'control_border': pygame.Color(80, 80, 80),
                'control_text': pygame.Color(255, 255, 255),
                'hovered_bg': pygame.Color(80, 80, 80),
                'viewport_outline': self.config.viewport_border_color,
                'viewport_fill': self.config.viewport_color,
                'selection_highlight': self.config.selection_color,
            }

            theme = self.ui_manager.get_theme()

            for color_id, default_color in color_mappings.items():
                try:
                    if hasattr(theme, 'get_colour_or_gradient'):
                        color = theme.get_colour_or_gradient(color_id, ['navigator_panel'])
                        self.themed_colors[color_id] = color if color else default_color
                    else:
                        self.themed_colors[color_id] = default_color
                except Exception:
                    self.themed_colors[color_id] = default_color

            # Get themed font
            try:
                if hasattr(theme, 'get_font'):
                    self.themed_font = theme.get_font(['navigator_panel'])
                else:
                    raise Exception("No font method")
            except Exception:
                try:
                    self.themed_font = pygame.font.SysFont('Arial', 10)
                except:
                    self.themed_font = pygame.font.Font(None, 10)

        except Exception as e:
            if NAVIGATOR_DEBUG:
                print(f"Error getting theme data: {e}")
            # Complete fallback
            self.themed_colors = {
                'dark_bg': pygame.Color(30, 30, 30),
                'thumbnail_bg': pygame.Color(45, 45, 45),
                'normal_border': pygame.Color(100, 100, 100),
                'focused_border': pygame.Color(120, 160, 255),
                'control_bg': pygame.Color(60, 60, 60),
                'control_border': pygame.Color(80, 80, 80),
                'control_text': pygame.Color(255, 255, 255),
                'hovered_bg': pygame.Color(80, 80, 80),
                'viewport_outline': self.config.viewport_border_color,
                'viewport_fill': self.config.viewport_color,
                'selection_highlight': self.config.selection_color,
            }
            try:
                self.themed_font = pygame.font.SysFont('Arial', 10)
            except:
                self.themed_font = pygame.font.Font(None, 10)

    def rebuild_from_changed_theme_data(self):
        """Called when theme data changes"""
        self._update_theme_data()
        self.cache_invalid = True
        self._rebuild_image()

    def _rebuild_image(self):
        """Rebuild the image surface"""
        # Fill background
        bg_color = self.themed_colors.get('dark_bg', pygame.Color(30, 30, 30))
        if hasattr(bg_color, 'apply_gradient_to_surface'):
            bg_color.apply_gradient_to_surface(self.image)
        else:
            self.image.fill(bg_color)

        # Draw thumbnail
        self._draw_thumbnail()

        # Draw viewport indicator
        if self.config.show_viewport_outline:
            self._draw_viewport_indicator()

        # Draw selection highlight
        self._draw_selection_highlight()

        # Draw zoom controls
        if self.zoom_control:
            self.zoom_control.draw(self.image, self.viewport.zoom, self.themed_colors)

        # Draw coordinates if enabled
        if self.config.show_coordinates:
            self._draw_coordinates()

        # Draw border
        border_color = self.themed_colors.get('focused_border' if self.is_focused else 'normal_border',
                                              pygame.Color(100, 100, 100))
        pygame.draw.rect(self.image, border_color, self.image.get_rect(), 2)

    def _draw_thumbnail(self):
        """Draw the content thumbnail"""
        # Fill thumbnail background
        thumbnail_bg = self.themed_colors.get('thumbnail_bg', pygame.Color(45, 45, 45))
        pygame.draw.rect(self.image, thumbnail_bg, self.thumbnail_rect)

        # Draw content using provider
        try:
            if self.config.mode == NavigatorMode.CUSTOM and self.config.custom_draw_function:
                self.config.custom_draw_function(self.image, self.thumbnail_rect, self.viewport)
            else:
                # Create a copy of viewport with mode information
                temp_viewport = NavigatorViewport(
                    self.viewport.content_x, self.viewport.content_y,
                    self.viewport.content_width, self.viewport.content_height,
                    self.viewport.zoom,
                    self.viewport.total_content_width, self.viewport.total_content_height
                )
                # Add mode information as an attribute
                temp_viewport.display_mode = self.config.mode

                self.content_provider.render_thumbnail(self.image, self.thumbnail_rect, temp_viewport)
        except Exception as e:
            if NAVIGATOR_DEBUG:
                print(f"Error drawing thumbnail: {e}")
            # Draw error indicator
            error_color = pygame.Color(100, 50, 50)
            pygame.draw.rect(self.image, error_color, self.thumbnail_rect)

            # Draw error text
            try:
                error_text = self.themed_font.render_premul("Error", pygame.Color(255, 255, 255))
                text_rect = error_text.get_rect(center=self.thumbnail_rect.center)
                self.image.blit(error_text, text_rect)
            except:
                pass

        # Draw thumbnail border
        border_color = self.themed_colors.get('control_border', pygame.Color(80, 80, 80))
        pygame.draw.rect(self.image, border_color, self.thumbnail_rect, 1)

    def _draw_viewport_indicator(self):
        """Draw the viewport rectangle overlay"""
        viewport_rect = self._content_to_thumbnail_rect(
            self.viewport.content_x, self.viewport.content_y,
            self.viewport.content_width, self.viewport.content_height
        )

        if viewport_rect.width >= 1 and viewport_rect.height >= 1:
            # Clip to thumbnail area
            clipped_rect = viewport_rect.clip(self.thumbnail_rect)

            if clipped_rect.width > 0 and clipped_rect.height > 0:
                # Draw semi-transparent fill
                if self.config.viewport_color.a > 0:
                    temp_surface = pygame.Surface((clipped_rect.width, clipped_rect.height), pygame.SRCALPHA)
                    temp_surface.fill(self.config.viewport_color)
                    self.image.blit(temp_surface, clipped_rect)

                # Draw border
                if self.config.viewport_border_width > 0:
                    pygame.draw.rect(self.image, self.config.viewport_border_color,
                                     clipped_rect, self.config.viewport_border_width)

    def _draw_selection_highlight(self):
        """Draw selection highlight if any"""
        selection_bounds = self.content_provider.get_selection_bounds()
        if selection_bounds:
            selection_rect = self._content_to_thumbnail_rect(
                selection_bounds.x, selection_bounds.y,
                selection_bounds.width, selection_bounds.height
            )

            # Clip to thumbnail area
            clipped_rect = selection_rect.clip(self.thumbnail_rect)

            if clipped_rect.width > 0 and clipped_rect.height > 0:
                # Draw selection highlight
                if self.config.selection_color.a > 0:
                    temp_surface = pygame.Surface((clipped_rect.width, clipped_rect.height), pygame.SRCALPHA)
                    temp_surface.fill(self.config.selection_color)
                    self.image.blit(temp_surface, clipped_rect)

                # Draw selection border
                pygame.draw.rect(self.image, pygame.Color(255, 255, 0), clipped_rect, 2)

    def _draw_coordinates(self):
        """Draw coordinate information"""
        try:
            coord_text = f"({self.viewport.content_x:.0f}, {self.viewport.content_y:.0f}) " \
                         f"{self.viewport.zoom * 100:.0f}%"

            text_surface = self.themed_font.render_premul(coord_text, self.themed_colors.get('control_text', pygame.Color(255, 255, 255)))

            # Position at bottom-left of thumbnail
            text_rect = text_surface.get_rect()
            text_rect.bottomleft = (self.thumbnail_rect.x + 4, self.thumbnail_rect.bottom - 4)

            # Draw background
            bg_rect = text_rect.copy()
            bg_rect.inflate(4, 2)
            pygame.draw.rect(self.image, pygame.Color(0, 0, 0, 180), bg_rect)

            self.image.blit(text_surface, text_rect)
        except Exception:
            pass

    def _content_to_thumbnail_rect(self, content_x: float, content_y: float,
                                   content_width: float, content_height: float) -> pygame.Rect:
        """Convert content coordinates to thumbnail rect"""
        # Calculate scale
        content_w, content_h = self.content_provider.get_content_size()
        if content_w <= 0 or content_h <= 0:
            return pygame.Rect(0, 0, 0, 0)

        scale_x = self.thumbnail_rect.width / content_w
        scale_y = self.thumbnail_rect.height / content_h

        # Use uniform scale to maintain aspect ratio
        scale = min(scale_x, scale_y)

        # Calculate scaled content size and offset for centering
        scaled_content_w = content_w * scale
        scaled_content_h = content_h * scale

        offset_x = (self.thumbnail_rect.width - scaled_content_w) / 2
        offset_y = (self.thumbnail_rect.height - scaled_content_h) / 2

        # Convert coordinates - Apply scale before adding offset
        thumb_x = self.thumbnail_rect.x + offset_x + (content_x * scale)
        thumb_y = self.thumbnail_rect.y + offset_y + (content_y * scale)
        thumb_w = content_width * scale
        thumb_h = content_height * scale

        return pygame.Rect(int(thumb_x), int(thumb_y), int(thumb_w), int(thumb_h))

    def _thumbnail_to_content_point(self, thumb_x: int, thumb_y: int) -> Tuple[float, float]:
        """Convert thumbnail coordinates to content coordinates"""
        content_w, content_h = self.content_provider.get_content_size()
        if content_w <= 0 or content_h <= 0:
            return 0.0, 0.0

        # Calculate scale and offset (same as in _content_to_thumbnail_rect)
        scale_x = self.thumbnail_rect.width / content_w
        scale_y = self.thumbnail_rect.height / content_h
        scale = min(scale_x, scale_y)

        scaled_content_w = content_w * scale
        scaled_content_h = content_h * scale

        offset_x = (self.thumbnail_rect.width - scaled_content_w) / 2
        offset_y = (self.thumbnail_rect.height - scaled_content_h) / 2

        # Convert back to content coordinates - Remove offset before dividing by scale
        relative_x = thumb_x - self.thumbnail_rect.x - offset_x
        relative_y = thumb_y - self.thumbnail_rect.y - offset_y

        content_x = relative_x / scale
        content_y = relative_y / scale

        return content_x, content_y

    def process_event(self, event: pygame.event.Event) -> bool:
        """Process pygame events"""
        consumed = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.is_focused = True
                relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)

                if event.button == 1:  # Left click
                    consumed = self._handle_left_click(relative_pos)
                elif event.button == 3:  # Right click
                    consumed = self._handle_right_click(relative_pos)
            else:
                self.is_focused = False

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self.is_dragging:
                self._handle_drag_end()
                consumed = True

        elif event.type == pygame.MOUSEMOTION:
            relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)
            consumed = self._handle_mouse_motion(relative_pos)

        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                consumed = self._handle_scroll(event.y)

        elif event.type == pygame.KEYDOWN and self.is_focused:
            consumed = self._handle_key_event(event)

        return consumed

    def _handle_left_click(self, pos: Tuple[int, int]) -> bool:
        """Handle left mouse click"""
        # Check zoom controls first
        if self.zoom_control and self.zoom_control.rect.collidepoint(pos):
            action = self.zoom_control.handle_click(pos)
            if action:
                self._handle_zoom_action(action)
                return True

        # Check thumbnail area
        if self.thumbnail_rect.collidepoint(pos):
            if self.config.click_to_navigate:
                # Convert click position to content coordinates
                content_x, content_y = self._thumbnail_to_content_point(pos[0], pos[1])

                # Center viewport on clicked position
                self.viewport.set_center(content_x, content_y)
                self._fire_viewport_changed_event()
                self._rebuild_image()

                # Start dragging if enabled
                if self.config.drag_to_pan:
                    self.is_dragging = True
                    self.drag_start_pos = pos
                    self.drag_start_viewport = NavigatorViewport(
                        self.viewport.content_x, self.viewport.content_y,
                        self.viewport.content_width, self.viewport.content_height,
                        self.viewport.zoom,
                        self.viewport.total_content_width, self.viewport.total_content_height
                    )

                return True

        return False

    def _handle_right_click(self, pos: Tuple[int, int]) -> bool:
        """Handle right mouse click"""
        if self.thumbnail_rect.collidepoint(pos):
            # Fire navigation clicked event
            content_x, content_y = self._thumbnail_to_content_point(pos[0], pos[1])

            event_data = {
                'content_position': (content_x, content_y),
                'thumbnail_position': pos,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_NAVIGATOR_NAVIGATION_CLICKED, event_data))
            return True

        return False

    def _handle_mouse_motion(self, pos: Tuple[int, int]) -> bool:
        """Handle mouse motion"""
        hover_changed = False

        # Update zoom control hover
        if self.zoom_control:
            if self.zoom_control.handle_hover(pos):
                hover_changed = True

        # Handle dragging
        if self.is_dragging and self.drag_start_viewport:
            dx = pos[0] - self.drag_start_pos[0]
            dy = pos[1] - self.drag_start_pos[1]

            # Convert pixel movement to content movement
            content_w, content_h = self.content_provider.get_content_size()
            scale_x = self.thumbnail_rect.width / content_w
            scale_y = self.thumbnail_rect.height / content_h
            scale = min(scale_x, scale_y)

            if scale > 0:
                content_dx = dx / scale * self.config.pan_sensitivity
                content_dy = dy / scale * self.config.pan_sensitivity

                self.viewport.content_x = self.drag_start_viewport.content_x + content_dx
                self.viewport.content_y = self.drag_start_viewport.content_y + content_dy
                self.viewport.clamp_to_content()

                self._fire_viewport_changed_event()
                hover_changed = True

        if hover_changed:
            self._rebuild_image()

        return hover_changed

    def _handle_drag_end(self):
        """Handle end of drag operation"""
        self.is_dragging = False
        self.drag_start_viewport = None

    def _handle_scroll(self, delta: int) -> bool:
        """Handle mouse wheel scroll"""
        if self.config.zoom_wheel_enabled:
            if delta > 0:
                self._zoom_in()
            else:
                self._zoom_out()
            return True
        return False

    def _handle_key_event(self, event: pygame.event.Event) -> bool:
        """Handle keyboard events"""
        if event.key == pygame.K_f:
            self._fit_content()
            return True
        elif event.key == pygame.K_1:
            self._actual_size()
            return True
        elif event.key == pygame.K_PLUS or event.key == pygame.K_EQUALS:
            self._zoom_in()
            return True
        elif event.key == pygame.K_MINUS:
            self._zoom_out()
            return True
        elif event.key == pygame.K_LEFT:
            self._pan(-10, 0)
            return True
        elif event.key == pygame.K_RIGHT:
            self._pan(10, 0)
            return True
        elif event.key == pygame.K_UP:
            self._pan(0, -10)
            return True
        elif event.key == pygame.K_DOWN:
            self._pan(0, 10)
            return True

        return False

    def _handle_zoom_action(self, action: str):
        """Handle zoom control actions"""
        if action == "zoom_in":
            self._zoom_in()
        elif action == "zoom_out":
            self._zoom_out()
        elif action == "fit":
            self._fit_content()
        elif action == "actual_size":
            self._actual_size()

    def _zoom_in(self):
        """Zoom in to next level"""
        current_zoom = self.viewport.zoom
        for zoom_level in self.config.zoom_levels:
            if zoom_level > current_zoom:
                self.set_zoom(zoom_level)
                break
        else:
            # No higher zoom level found, use max zoom
            max_zoom = min(self.config.max_zoom, max(self.config.zoom_levels))
            if current_zoom < max_zoom:
                self.set_zoom(min(current_zoom * ZOOM_WHEEL_FACTOR, max_zoom))

    def _zoom_out(self):
        """Zoom out to previous level"""
        current_zoom = self.viewport.zoom
        for zoom_level in reversed(self.config.zoom_levels):
            if zoom_level < current_zoom:
                self.set_zoom(zoom_level)
                break
        else:
            # No lower zoom level found, use min zoom
            min_zoom = max(self.config.min_zoom, min(self.config.zoom_levels))
            if current_zoom > min_zoom:
                self.set_zoom(max(current_zoom / ZOOM_WHEEL_FACTOR, min_zoom))

    def _fit_content(self):
        """Fit all content in view"""
        content_w, content_h = self.content_provider.get_content_size()
        if content_w <= 0 or content_h <= 0:
            return

        # Calculate zoom to fit content
        zoom_x = self.viewport.content_width / content_w
        zoom_y = self.viewport.content_height / content_h
        zoom = min(zoom_x, zoom_y)

        self.set_zoom(zoom)

        # Center content
        self.viewport.set_center(content_w / 2, content_h / 2)
        self._fire_viewport_changed_event()

        # Fire fit event
        event_data = {'ui_element': self}
        pygame.event.post(pygame.event.Event(UI_NAVIGATOR_FIT_REQUESTED, event_data))

    def _actual_size(self):
        """Set zoom to 100% (actual size)"""
        self.set_zoom(1.0)

    def _pan(self, dx: float, dy: float):
        """Pan the viewport by pixel amounts"""
        # Convert pixels to content units
        content_dx = dx / self.viewport.zoom
        content_dy = dy / self.viewport.zoom

        self.viewport.content_x += content_dx
        self.viewport.content_y += content_dy
        self.viewport.clamp_to_content()

        self._fire_viewport_changed_event()
        self._rebuild_image()

    def _fire_viewport_changed_event(self):
        """Fire viewport changed event"""
        event_data = {
            'viewport': self.viewport,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_NAVIGATOR_VIEWPORT_CHANGED, event_data))

    def _fire_zoom_changed_event(self):
        """Fire zoom changed event"""
        event_data = {
            'zoom': self.viewport.zoom,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_NAVIGATOR_ZOOM_CHANGED, event_data))

    def update(self, time_delta: float):
        """Update the panel"""
        super().update(time_delta)

        # Check if we need to update content
        if self.config.update_on_viewport_change or self.cache_invalid:
            self.cache_invalid = False

    # Public API methods
    def set_content_provider(self, provider: ContentProvider):
        """Set a new content provider"""
        self.content_provider = provider

        # Update viewport size
        content_w, content_h = provider.get_content_size()
        self.viewport.total_content_width = content_w
        self.viewport.total_content_height = content_h

        self.cache_invalid = True
        self._rebuild_image()

    def set_viewport(self, viewport: NavigatorViewport):
        """Set viewport information"""
        self.viewport = viewport
        self._fire_viewport_changed_event()
        self._rebuild_image()

    def get_viewport(self) -> NavigatorViewport:
        """Get current viewport information"""
        return self.viewport

    def set_zoom(self, zoom: float):
        """Set zoom level"""
        old_zoom = self.viewport.zoom
        self.viewport.zoom = max(self.config.min_zoom, min(self.config.max_zoom, zoom))

        if old_zoom != self.viewport.zoom:
            # Keep the viewport center the same
            center_x, center_y = self.viewport.get_center()

            # Calculate new viewport size based on zoom
            # The viewport should represent a fixed screen area scaled by zoom
            # content_w, content_h = self.content_provider.get_content_size()

            # Base the viewport size on a reasonable screen area in content units
            # This should match what your main content area represents
            base_screen_width = 450  # Main content rect width
            base_screen_height = 350  # Main content rect height

            # Convert screen area to content units at current zoom
            self.viewport.content_width = base_screen_width / self.viewport.zoom
            self.viewport.content_height = base_screen_height / self.viewport.zoom

            # Restore center position
            self.viewport.set_center(center_x, center_y)

            self._fire_zoom_changed_event()
            self._rebuild_image()

    def fit_to_selection(self):
        """Fit viewport to current selection"""
        selection_bounds = self.content_provider.get_selection_bounds()
        if selection_bounds:
            # Calculate zoom to fit selection
            zoom_x = self.viewport.content_width / selection_bounds.width
            zoom_y = self.viewport.content_height / selection_bounds.height
            zoom = min(zoom_x, zoom_y) * 0.9  # Leave some margin

            self.set_zoom(zoom)

            # Center on selection
            center_x = selection_bounds.centerx
            center_y = selection_bounds.centery
            self.viewport.set_center(center_x, center_y)

            self._fire_viewport_changed_event()

            # Fire zoom to selection event
            event_data = {
                'selection_bounds': selection_bounds,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_NAVIGATOR_ZOOM_TO_SELECTION, event_data))

    def refresh(self):
        """Force refresh of the navigator"""
        self.cache_invalid = True
        self._rebuild_image()


# Example theme for navigator panel
NAVIGATOR_THEME = {
    "navigator_panel": {
        "colours": {
            "dark_bg": "#1e1e1e",
            "thumbnail_bg": "#2d2d2d",
            "normal_border": "#646464",
            "focused_border": "#78a0ff",
            "control_bg": "#3c3c3c",
            "control_border": "#505050",
            "control_text": "#ffffff",
            "hovered_bg": "#505050",
            "viewport_outline": "#ffffff",
            "viewport_fill": "#ffffff80",
            "selection_highlight": "#ffff0040"
        },
        "font": {
            "name": "arial",
            "size": "10",
            "bold": "0",
            "italic": "0"
        }
    }
}


def create_sample_image_content() -> ImageContentProvider:
    """Create sample image content"""
    # Create a sample image with some patterns
    image = pygame.Surface((800, 600))

    # Fill with gradient
    for y in range(600):
        color_value = int(255 * y / 600)
        color = pygame.Color(color_value // 3, color_value // 2, color_value)
        pygame.draw.line(image, color, (0, y), (800, y))

    # Add some shapes
    for i in range(20):
        x = (i % 5) * 160 + 80
        y = (i // 5) * 120 + 60
        color = pygame.Color(255, 255 - i * 10, i * 10)
        pygame.draw.circle(image, color, (x, y), 30)
        pygame.draw.rect(image, pygame.Color(255, 255, 255),
                         pygame.Rect(x - 40, y - 40, 80, 80), 2)

    provider = ImageContentProvider(image)

    # Set a sample selection
    provider.set_selection(pygame.Rect(200, 150, 200, 150))

    return provider


def create_sample_node_graph() -> NodeGraphContentProvider:
    """Create sample node graph content"""
    provider = NodeGraphContentProvider((1200, 800))

    # Add nodes in a hierarchical layout
    root = provider.add_node(100, 100, 120, 60, "Root", pygame.Color(100, 150, 255))

    # Level 1 nodes
    node1 = provider.add_node(50, 250, 100, 50, "Node 1", pygame.Color(150, 200, 100))
    node2 = provider.add_node(200, 250, 100, 50, "Node 2", pygame.Color(150, 200, 100))
    node3 = provider.add_node(350, 250, 100, 50, "Node 3", pygame.Color(150, 200, 100))

    # Level 2 nodes
    node4 = provider.add_node(25, 400, 80, 40, "Child 1", pygame.Color(255, 200, 100))
    node5 = provider.add_node(125, 400, 80, 40, "Child 2", pygame.Color(255, 200, 100))
    node6 = provider.add_node(275, 400, 80, 40, "Child 3", pygame.Color(255, 200, 100))
    node7 = provider.add_node(375, 400, 80, 40, "Child 4", pygame.Color(255, 200, 100))

    # Some distant nodes
    node8 = provider.add_node(600, 200, 100, 50, "Remote", pygame.Color(200, 100, 255))
    node9 = provider.add_node(800, 350, 90, 45, "Isolated", pygame.Color(255, 150, 150))

    # Add connections
    provider.add_connection(root, node1)
    provider.add_connection(root, node2)
    provider.add_connection(root, node3)
    provider.add_connection(node1, node4)
    provider.add_connection(node1, node5)
    provider.add_connection(node2, node6)
    provider.add_connection(node3, node7)
    provider.add_connection(node2, node8)
    provider.add_connection(node8, node9)

    # Set selection
    provider.set_selection([node1, node4, node5])

    return provider


def main():
    """Example demonstration of the Navigator Panel"""
    pygame.init()
    screen = pygame.display.set_mode((1200, 800))
    pygame.display.set_caption("Navigator Panel Demo")
    clock = pygame.time.Clock()

    # Create manager with theme
    manager = pygame_gui.UIManager((1200, 800), NAVIGATOR_THEME)

    # Create content providers
    image_provider = create_sample_image_content()
    node_provider = create_sample_node_graph()
    current_provider = node_provider

    # Create viewport with proper initial size for node content
    content_w, content_h = current_provider.get_content_size()
    main_content_width = 450  # Width of main content area
    main_content_height = 350  # Height of main content area
    initial_zoom = 1.0

    viewport = NavigatorViewport(
        content_x=100, content_y=100,
        content_width=main_content_width / initial_zoom,
        content_height=main_content_height / initial_zoom,
        zoom=initial_zoom,
        total_content_width=content_w, total_content_height=content_h
    )

    # Configure navigator
    config = NavigatorConfig()
    config.show_zoom_controls = True
    config.show_coordinates = True
    config.click_to_navigate = True
    config.drag_to_pan = True

    # Create navigator panel
    navigator = NavigatorPanel(
        pygame.Rect(50, 50, 300, 400),
        manager,
        current_provider,
        viewport,
        config,
        object_id=ObjectID(object_id='#main_navigator', class_id='@navigator')
    )

    # Create a second navigator for comparison with proper viewport
    viewport2 = NavigatorViewport(
        content_x=0, content_y=0,
        content_width=content_w * 0.5, content_height=content_h * 0.5,  # Show 50% of content
        zoom=1.0,
        total_content_width=content_w, total_content_height=content_h
    )

    config2 = NavigatorConfig()
    config2.show_zoom_controls = False
    config2.show_coordinates = False
    config2.mode = NavigatorMode.WIREFRAME

    navigator2 = NavigatorPanel(
        pygame.Rect(400, 50, 250, 300),
        manager,
        node_provider,
        viewport2,
        config2,
        object_id=ObjectID(object_id='#secondary_navigator', class_id='@navigator_two')
    )

    # Instructions
    print("\nNavigator Panel Demo")
    print("\nFeatures:")
    print("- Image and node graph content providers")
    print("- Viewport visualization and navigation")
    print("- Zoom controls with multiple levels")
    print("- Selection highlighting")
    print("- Click and drag navigation")
    print("- Keyboard shortcuts")

    print("\nControls:")
    print("- Click in navigator to center viewport")
    print("- Drag to pan viewport")
    print("- Mouse wheel to zoom")
    print("- Zoom buttons: +, -, F(it), 1(00%)")
    print("- Arrow keys to pan (when focused)")
    print("- F to fit content, 1 for actual size")
    print("- S to zoom to selection")

    print("\nPress T to toggle content type")
    print("Press R to reset viewport")
    print("Press I to show info")
    print("Press M to change navigator mode\n")

    # State variables
    using_node_content = True # Start with node content showing
    info_visible = True

    running = True
    while running:
        time_delta = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_t:
                    # Toggle content type
                    using_node_content = not using_node_content
                    new_provider = node_provider if using_node_content else image_provider
                    navigator.set_content_provider(new_provider)
                    print(f"Switched to {'node graph' if using_node_content else 'image'} content")

                elif event.key == pygame.K_r:
                    # Reset viewport
                    if using_node_content:
                        new_viewport = NavigatorViewport(0, 0, 600, 400, 1.0, 1200, 800)
                    else:
                        new_viewport = NavigatorViewport(100, 100, 400, 300, 1.0, 800, 600)
                    navigator.set_viewport(new_viewport)
                    print("Reset viewport")

                elif event.key == pygame.K_i:
                    # Toggle info display
                    info_visible = not info_visible
                    print(f"Info display: {'on' if info_visible else 'off'}")

                elif event.key == pygame.K_m:
                    # Cycle navigator mode
                    modes = list(NavigatorMode)
                    current_mode_index = modes.index(navigator.config.mode)
                    next_mode_index = (current_mode_index + 1) % len(modes)
                    navigator.config.mode = modes[next_mode_index]
                    navigator.refresh()
                    print(f"Navigator mode: {navigator.config.mode.value}")

                elif event.key == pygame.K_s:
                    # Zoom to selection
                    navigator.fit_to_selection()
                    print("Zoomed to selection")

            # Handle navigator events
            elif event.type == UI_NAVIGATOR_VIEWPORT_CHANGED:
                if NAVIGATOR_DEBUG:
                    vp = event.viewport
                    print(f"Viewport changed: ({vp.content_x:.1f}, {vp.content_y:.1f}) "
                          f"{vp.content_width:.1f}x{vp.content_height:.1f} @ {vp.zoom:.2f}x")

            elif event.type == UI_NAVIGATOR_ZOOM_CHANGED:
                if NAVIGATOR_DEBUG:
                    print(f"Zoom changed: {event.zoom:.2f}x")

            elif event.type == UI_NAVIGATOR_NAVIGATION_CLICKED:
                if NAVIGATOR_DEBUG:
                    pos = event.content_position
                    print(f"Navigation clicked at content position: ({pos[0]:.1f}, {pos[1]:.1f})")

            elif event.type == UI_NAVIGATOR_FIT_REQUESTED:
                if NAVIGATOR_DEBUG:
                    print("Fit to content requested")

            elif event.type == UI_NAVIGATOR_ZOOM_TO_SELECTION:
                if NAVIGATOR_DEBUG:
                    bounds = event.selection_bounds
                    print(f"Zoomed to selection: {bounds}")

            # Forward events to manager
            manager.process_events(event)

        # Update
        manager.update(time_delta)

        # Draw
        screen.fill((25, 25, 25))

        # Draw main content area simulation
        main_content_rect = pygame.Rect(700, 50, 450, 350)
        pygame.draw.rect(screen, pygame.Color(40, 40, 40), main_content_rect)
        pygame.draw.rect(screen, pygame.Color(100, 100, 100), main_content_rect, 2)

        # Simulate content in main area based on viewport
        vp = navigator.get_viewport()
        if using_node_content:
            # Calculate the scale factor to convert from content coordinates to screen coordinates
            content_to_screen_scale_x = main_content_rect.width / vp.content_width
            content_to_screen_scale_y = main_content_rect.height / vp.content_height

            # Draw nodes that are within the viewport
            for i, node in enumerate(node_provider.nodes):
                # Node bounds in content coordinates
                node_left = node['x']
                node_top = node['y']
                node_right = node['x'] + node['width']
                node_bottom = node['y'] + node['height']

                # Viewport bounds in content coordinates
                viewport_left = vp.content_x
                viewport_top = vp.content_y
                viewport_right = vp.content_x + vp.content_width
                viewport_bottom = vp.content_y + vp.content_height

                # Check if node intersects with viewport
                if (node_right > viewport_left and node_left < viewport_right and
                        node_bottom > viewport_top and node_top < viewport_bottom):

                    # Calculate the portion of the node that's visible in the viewport
                    visible_left = max(node_left, viewport_left)
                    visible_top = max(node_top, viewport_top)
                    visible_right = min(node_right, viewport_right)
                    visible_bottom = min(node_bottom, viewport_bottom)

                    # Convert to screen coordinates relative to main content rect
                    screen_left = main_content_rect.x + (visible_left - viewport_left) * content_to_screen_scale_x
                    screen_top = main_content_rect.y + (visible_top - viewport_top) * content_to_screen_scale_y
                    screen_right = main_content_rect.x + (visible_right - viewport_left) * content_to_screen_scale_x
                    screen_bottom = main_content_rect.y + (visible_bottom - viewport_top) * content_to_screen_scale_y

                    # Create screen rectangle
                    screen_rect = pygame.Rect(
                        int(screen_left),
                        int(screen_top),
                        max(1, int(screen_right - screen_left)),
                        max(1, int(screen_bottom - screen_top))
                    )

                    # Only draw if rectangle is valid and within main content area
                    if screen_rect.width > 0 and screen_rect.height > 0:
                        clipped_rect = screen_rect.clip(main_content_rect)
                        if clipped_rect.width > 0 and clipped_rect.height > 0:
                            color = node['color']
                            if i in node_provider.selection:
                                color = pygame.Color(255, 255, 100)

                            pygame.draw.rect(screen, color, clipped_rect)
                            pygame.draw.rect(screen, pygame.Color(200, 200, 200), clipped_rect, 1)
        else:
            # Draw portion of image content
            try:
                # Calculate which part of the image should be visible
                viewport_left = max(0, int(vp.content_x))
                viewport_top = max(0, int(vp.content_y))
                viewport_right = min(image_provider.image.get_width(), int(vp.content_x + vp.content_width))
                viewport_bottom = min(image_provider.image.get_height(), int(vp.content_y + vp.content_height))

                # Only proceed if there's a valid visible area
                if viewport_right > viewport_left and viewport_bottom > viewport_top:
                    # Extract the visible portion
                    visible_width = viewport_right - viewport_left
                    visible_height = viewport_bottom - viewport_top

                    if visible_width > 0 and visible_height > 0:
                        img_rect = pygame.Rect(int(viewport_left), int(viewport_top),
                                               int(visible_width), int(visible_height))

                        # Make sure the rectangle is within image bounds
                        img_rect = img_rect.clip(pygame.Rect(0, 0, image_provider.image.get_width(),
                                                             image_provider.image.get_height()))

                        if img_rect.width > 0 and img_rect.height > 0:
                            cropped = image_provider.image.subsurface(img_rect)

                            # Scale the cropped image to fill the main content area
                            scale_x = main_content_rect.width / visible_width
                            scale_y = main_content_rect.height / visible_height
                            scale = min(scale_x, scale_y)  # Maintain aspect ratio

                            scaled_width = int(visible_width * scale)
                            scaled_height = int(visible_height * scale)

                            if scaled_width > 0 and scaled_height > 0:
                                scaled_img = pygame.transform.scale(cropped, (scaled_width, scaled_height))

                                # Center the scaled image in the main content area
                                draw_x = main_content_rect.x + (main_content_rect.width - scaled_width) // 2
                                draw_y = main_content_rect.y + (main_content_rect.height - scaled_height) // 2

                                screen.blit(scaled_img, (draw_x, draw_y))

            except Exception as e:
                # Draw error indicator
                label_font = pygame.font.Font(None, 24)
                error_text = label_font.render(f"Image Error\n {e}", True, pygame.Color(255, 100, 100))
                error_rect = error_text.get_rect(center=main_content_rect.center)
                screen.blit(error_text, error_rect)

        # Draw info panel
        if info_visible:
            info_rect = pygame.Rect(700, 450, 450, 300)
            pygame.draw.rect(screen, pygame.Color(35, 35, 35), info_rect)
            pygame.draw.rect(screen, pygame.Color(80, 80, 80), info_rect, 1)

            font = pygame.font.Font(None, 20)
            small_font = pygame.font.Font(None, 16)

            y_offset = info_rect.y + 10

            # Title
            title = font.render("Navigator Demo Info", True, pygame.Color(255, 255, 255))
            screen.blit(title, (info_rect.x + 10, y_offset))
            y_offset += 30

            # Viewport info
            vp = navigator.get_viewport()
            info_lines = [
                f"Content Type: {'Node Graph' if using_node_content else 'Image'}",
                f"Viewport Position: ({vp.content_x:.1f}, {vp.content_y:.1f})",
                f"Viewport Size: {vp.content_width:.1f} x {vp.content_height:.1f}",
                f"Zoom Level: {vp.zoom:.2f}x ({vp.zoom * 100:.0f}%)",
                f"Total Content: {vp.total_content_width:.0f} x {vp.total_content_height:.0f}",
                "",
                "Navigator 1 (left): Full-featured with zoom controls",
                "Navigator 2 (right): Wireframe mode, no controls",
                "",
                "Both navigators show the same logical content",
                "but with different visualization modes.",
            ]

            for line in info_lines:
                if line:
                    text = small_font.render(line, True, pygame.Color(200, 200, 200))
                    screen.blit(text, (info_rect.x + 10, y_offset))
                y_offset += 18

            # Selection info
            if using_node_content and node_provider.selection:
                y_offset += 10
                selection_text = small_font.render(f"Selected Nodes: {len(node_provider.selection)}",
                                                   True, pygame.Color(255, 255, 100))
                screen.blit(selection_text, (info_rect.x + 10, y_offset))
            elif not using_node_content and image_provider.selection_rect:
                y_offset += 10
                sel_rect = image_provider.selection_rect
                selection_text = small_font.render(
                    f"Selection: {sel_rect.width}x{sel_rect.height} at ({sel_rect.x}, {sel_rect.y})",
                    True, pygame.Color(255, 255, 100))
                screen.blit(selection_text, (info_rect.x + 10, y_offset))

        # Draw labels
        label_font = pygame.font.Font(None, 18)
        nav1_label = label_font.render("Navigator 1 (Full)", True, pygame.Color(255, 255, 255))
        screen.blit(nav1_label, (50, 30))

        nav2_label = label_font.render("Navigator 2 (Wireframe)", True, pygame.Color(255, 255, 255))
        screen.blit(nav2_label, (400, 30))

        main_label = label_font.render("Main Content View", True, pygame.Color(255, 255, 255))
        screen.blit(main_label, (700, 30))

        manager.draw_ui(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()