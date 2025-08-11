import pygame
import pygame_gui
from pygame_gui.core import UIElement, ObjectID
from pygame_gui.core.interfaces import IContainerLikeInterface
from typing import List, Optional, Dict, Any, Union, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import os
import json
import colorsys
import math

try:
    from pygame_gui.core.interfaces.gui_font_interface import IGUIFontInterface
except ImportError:
    IGUIFontInterface = None

PROPERTY_DEBUG = True

# Constants
PROPERTY_ROW_HEIGHT = 28
SECTION_HEADER_HEIGHT = 24
INDENT_SIZE = 16
CONTROL_SPACING = 4
MIN_LABEL_WIDTH = 80
COLOR_PICKER_SIZE = 16

# Define custom pygame-gui events
UI_PROPERTY_CHANGED = pygame.USEREVENT + 50
UI_PROPERTY_EDITING_STARTED = pygame.USEREVENT + 51
UI_PROPERTY_EDITING_FINISHED = pygame.USEREVENT + 52
UI_PROPERTY_VALIDATION_FAILED = pygame.USEREVENT + 53
UI_PROPERTY_SECTION_TOGGLED = pygame.USEREVENT + 54
UI_PROPERTY_RESET_REQUESTED = pygame.USEREVENT + 55


class PropertyType(Enum):
    """Supported property types"""
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DROPDOWN = "dropdown"
    COLOR = "color"
    VECTOR2 = "vector2"
    VECTOR3 = "vector3"
    SLIDER = "slider"
    FILE_PATH = "file_path"
    MULTILINE_TEXT = "multiline_text"
    RANGE = "range"  # Min/max number pair
    BUTTON = "button"  # Action button


class PropertyFlags(Enum):
    """Property behavior flags"""
    READONLY = "readonly"
    HIDDEN = "hidden"
    ADVANCED = "advanced"
    REQUIRED = "required"


@dataclass
class PropertySchema:
    """Schema defining a property for the inspector"""
    id: str
    label: str
    property_type: PropertyType
    value: Any = None
    default_value: Any = None

    # Type-specific options
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    precision: int = 2

    # Dropdown/enum options
    options: Optional[List[str]] = None
    option_values: Optional[List[Any]] = None

    # Text options
    max_length: Optional[int] = None
    placeholder: Optional[str] = None
    multiline_rows: int = 3

    # File path options
    file_types: Optional[List[str]] = None  # [".png", ".jpg"]
    directory_only: bool = False

    # Vector options
    component_labels: Optional[List[str]] = None  # ["X", "Y", "Z"]

    # Validation
    validator: Optional[Callable[[Any], bool]] = None
    validator_message: str = "Invalid value"

    # Behavior flags
    flags: List[PropertyFlags] = field(default_factory=list)

    # UI options
    tooltip: Optional[str] = None
    section: Optional[str] = None
    order: int = 0

    # Custom data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_readonly(self) -> bool:
        return PropertyFlags.READONLY in self.flags

    def is_hidden(self) -> bool:
        return PropertyFlags.HIDDEN in self.flags

    def is_advanced(self) -> bool:
        return PropertyFlags.ADVANCED in self.flags

    def is_required(self) -> bool:
        return PropertyFlags.REQUIRED in self.flags

    def validate(self, value: Any) -> Tuple[bool, str]:
        """Validate a value against this property's constraints"""
        try:
            # Type-specific validation
            if self.property_type == PropertyType.NUMBER:
                if not isinstance(value, (int, float)):
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        return False, f"'{value}' is not a valid number"

                if self.min_value is not None and value < self.min_value:
                    return False, f"Value must be >= {self.min_value}"
                if self.max_value is not None and value > self.max_value:
                    return False, f"Value must be <= {self.max_value}"

            elif self.property_type == PropertyType.TEXT:
                if not isinstance(value, str):
                    value = str(value)
                if self.max_length and len(value) > self.max_length:
                    return False, f"Text too long (max {self.max_length} characters)"

            elif self.property_type == PropertyType.COLOR:
                if isinstance(value, pygame.Color):
                    pass  # Already valid
                elif isinstance(value, (list, tuple)) and len(value) >= 3:
                    pass  # RGB(A) tuple
                elif isinstance(value, str):
                    try:
                        pygame.Color(value)
                    except ValueError:
                        return False, "Invalid color format"
                else:
                    return False, "Invalid color format"

            # Custom validator
            if self.validator and not self.validator(value):
                return False, self.validator_message

            return True, ""

        except Exception as e:
            return False, str(e)


@dataclass
class PropertySection:
    """A collapsible section of properties"""
    id: str
    label: str
    expanded: bool = True
    order: int = 0
    properties: List[PropertySchema] = field(default_factory=list)


@dataclass
class PropertyConfig:
    """Configuration for the property inspector"""
    # Layout
    row_height: int = PROPERTY_ROW_HEIGHT
    section_header_height: int = SECTION_HEADER_HEIGHT
    indent_size: int = INDENT_SIZE
    label_width_ratio: float = 0.4  # Ratio of row width for labels
    min_label_width: int = MIN_LABEL_WIDTH
    control_spacing: int = CONTROL_SPACING

    # Behavior
    live_editing: bool = True  # Update values while typing
    show_tooltips: bool = True
    show_reset_buttons: bool = True
    show_advanced_properties: bool = False
    auto_scroll_to_changed: bool = False

    # Validation
    validate_on_change: bool = True
    highlight_invalid: bool = True

    # Keyboard navigation
    tab_navigation: bool = True
    enter_confirms_edit: bool = True


class PropertyRenderer:
    """Base class for property renderers"""

    def __init__(self, property_schema: PropertySchema, config: PropertyConfig):
        self.property = property_schema
        self.config = config
        self.is_editing = False
        self.is_focused = False
        self.is_hovered = False
        self.validation_error: Optional[str] = None
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.label_rect = pygame.Rect(0, 0, 0, 0)
        self.control_rect = pygame.Rect(0, 0, 0, 0)

    # TODO: use get_local_rect?
    # adjusted = self.get_local_rect(comp_rect)
    def get_local_rect(self, abs_rect: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(abs_rect.move(-self.rect.x, -self.rect.y))

    def set_geometry(self, rect: pygame.Rect, label_width: int):
        """Set the geometry for this property renderer"""
        self.rect = rect
        self.label_rect = pygame.Rect(rect.x, rect.y, label_width, rect.height)
        self.control_rect = pygame.Rect(
            rect.x + label_width + self.config.control_spacing,
            rect.y,
            rect.width - label_width - self.config.control_spacing,
            rect.height
        )

    def draw(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        """Draw the property renderer"""
        self._draw_background(surface, colors)
        self._draw_label(surface, font, colors)
        self._draw_control(surface, font, colors)
        self._draw_validation_error(surface, font, colors)

    def _draw_background(self, surface: pygame.Surface, colors: Dict[str, pygame.Color]):
        """Draw background highlighting"""
        if self.validation_error and self.config.highlight_invalid:
            pygame.draw.rect(surface, colors.get('error_bg', pygame.Color(60, 20, 20)), self.rect)
        elif self.is_focused:
            pygame.draw.rect(surface, colors.get('focused_bg', pygame.Color(50, 80, 120)), self.rect)
        elif self.is_hovered:
            pygame.draw.rect(surface, colors.get('hovered_bg', pygame.Color(45, 45, 45)), self.rect)

    def _draw_label(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        """Draw the property label"""
        text_color = colors.get('normal_text', pygame.Color(255, 255, 255))
        if self.property.is_readonly():
            text_color = colors.get('readonly_text', pygame.Color(150, 150, 150))

        try:
            if hasattr(font, 'render_premul'):
                text_surface = font.render_premul(self.property.label, text_color)
            else:
                text_surface = font.render(self.property.label, True, text_color)

            # Center vertically in label rect
            y_offset = (self.label_rect.height - text_surface.get_height()) // 2
            surface.blit(text_surface, (self.label_rect.x + 4, self.label_rect.y + y_offset))

        except Exception as e:
            if PROPERTY_DEBUG:
                print(f"Error rendering label for {self.property.id}: {e}")

    def _draw_control(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        """Draw the property control - override in subclasses"""
        pass

    def _draw_validation_error(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        """Draw validation error indicator"""
        if self.validation_error:
            # Draw error icon or indicator
            error_color = colors.get('error_text', pygame.Color(255, 100, 100))
            pygame.draw.circle(surface, error_color,
                               (self.rect.right - 10, self.rect.centery), 3)

    def handle_event(self, event: pygame.event.Event, relative_pos: Tuple[int, int]) -> bool:
        """Handle input events - return True if consumed"""
        return False

    def start_editing(self):
        """Start editing this property"""
        if not self.property.is_readonly():
            self.is_editing = True

    def stop_editing(self, save: bool = True):
        """Stop editing this property"""
        self.is_editing = False

    def get_value(self) -> Any:
        """Get the current value from the control"""
        return self.property.value

    def set_value(self, value: Any, validate: bool = True):
        """Set the value in the control"""
        if validate:
            is_valid, error_msg = self.property.validate(value)
            if not is_valid:
                self.validation_error = error_msg
                return False
            self.validation_error = None

        self.property.value = value
        return True


class TextPropertyRenderer(PropertyRenderer):
    """Renderer for text properties"""

    def __init__(self, property_schema: PropertySchema, config: PropertyConfig):
        super().__init__(property_schema, config)
        self.text_input = ""
        self.cursor_pos = 0
        self.selection_start = 0
        self.selection_end = 0
        self.blink_timer = 0
        self.show_cursor = True

    def start_editing(self):
        super().start_editing()
        if self.is_editing:
            self.text_input = str(self.property.value or "")
            self.cursor_pos = len(self.text_input)
            self.selection_start = 0
            self.selection_end = len(self.text_input)

    def stop_editing(self, save: bool = True):
        if self.is_editing and save:
            self.set_value(self.text_input)
        super().stop_editing(save)

    def _draw_control(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        # Draw text input box
        box_color = colors.get('control_bg', pygame.Color(60, 60, 60))
        border_color = colors.get('control_border', pygame.Color(100, 100, 100))

        if self.is_editing:
            border_color = colors.get('focused_border', pygame.Color(120, 160, 255))

        pygame.draw.rect(surface, box_color, self.control_rect)
        pygame.draw.rect(surface, border_color, self.control_rect, 1)

        # Draw text
        display_text = self.text_input if self.is_editing else str(self.property.value or "")
        text_color = colors.get('control_text', pygame.Color(255, 255, 255))

        if self.property.is_readonly():
            text_color = colors.get('readonly_text', pygame.Color(150, 150, 150))

        try:
            if hasattr(font, 'render_premul'):
                text_surface = font.render_premul(display_text, text_color)
            else:
                text_surface = font.render(display_text, True, text_color)

            # Clip text to control rect
            text_rect = text_surface.get_rect()
            text_rect.centery = self.control_rect.centery
            text_rect.x = self.control_rect.x + 4

            # Create clipping rect
            clip_rect = self.control_rect.copy()
            clip_rect.width -= 8  # Padding

            surface.set_clip(clip_rect)
            surface.blit(text_surface, text_rect)
            surface.set_clip(None)

            # Draw cursor when editing
            if self.is_editing and self.show_cursor:
                cursor_x = text_rect.x + font.size(display_text[:self.cursor_pos])[0]
                if self.control_rect.contains(cursor_x, self.control_rect.y, 1, self.control_rect.height):
                    pygame.draw.line(surface, text_color,
                                     (cursor_x, self.control_rect.y + 4),
                                     (cursor_x, self.control_rect.bottom - 4))

        except Exception as e:
            if PROPERTY_DEBUG:
                print(f"Error rendering text control: {e}")

    def handle_event(self, event: pygame.event.Event, relative_pos: Tuple[int, int]) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.control_rect.collidepoint(relative_pos):
                if not self.is_editing:
                    self.start_editing()
                else:
                    # Position cursor
                    # This is a simplified cursor positioning
                    self.cursor_pos = len(self.text_input)
                return True

        elif event.type == pygame.KEYDOWN and self.is_editing:
            if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                self.stop_editing(True)
                return True
            elif event.key == pygame.K_ESCAPE:
                self.stop_editing(False)
                return True
            elif event.key == pygame.K_BACKSPACE:
                if self.cursor_pos > 0:
                    self.text_input = self.text_input[:self.cursor_pos - 1] + self.text_input[self.cursor_pos:]
                    self.cursor_pos -= 1
                return True
            elif event.key == pygame.K_DELETE:
                if self.cursor_pos < len(self.text_input):
                    self.text_input = self.text_input[:self.cursor_pos] + self.text_input[self.cursor_pos + 1:]
                return True
            elif event.key == pygame.K_LEFT:
                self.cursor_pos = max(0, self.cursor_pos - 1)
                return True
            elif event.key == pygame.K_RIGHT:
                self.cursor_pos = min(len(self.text_input), self.cursor_pos + 1)
                return True
            elif event.key == pygame.K_HOME:
                self.cursor_pos = 0
                return True
            elif event.key == pygame.K_END:
                self.cursor_pos = len(self.text_input)
                return True

        elif event.type == pygame.TEXTINPUT and self.is_editing:
            self.text_input = self.text_input[:self.cursor_pos] + event.text + self.text_input[self.cursor_pos:]
            self.cursor_pos += len(event.text)
            return True

        return False


class NumberPropertyRenderer(PropertyRenderer):
    """Renderer for numeric properties"""

    def __init__(self, property_schema: PropertySchema, config: PropertyConfig):
        super().__init__(property_schema, config)
        self.text_input = ""
        self.cursor_pos = 0
        self.is_float = property_schema.step is None or property_schema.step != int(property_schema.step or 1)

    def start_editing(self):
        super().start_editing()
        if self.is_editing:
            value = self.property.value or 0
            if self.is_float:
                self.text_input = f"{value:.{self.property.precision}f}"
            else:
                self.text_input = str(int(value))
            self.cursor_pos = len(self.text_input)

    def stop_editing(self, save: bool = True):
        if self.is_editing and save:
            try:
                if self.is_float:
                    value = float(self.text_input)
                else:
                    value = int(float(self.text_input))
                self.set_value(value)
            except ValueError:
                pass  # Keep old value
        super().stop_editing(save)

    def _draw_control(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        # Similar to text renderer but with number-specific formatting
        box_color = colors.get('control_bg', pygame.Color(60, 60, 60))
        border_color = colors.get('control_border', pygame.Color(100, 100, 100))

        if self.is_editing:
            border_color = colors.get('focused_border', pygame.Color(120, 160, 255))

        pygame.draw.rect(surface, box_color, self.control_rect)
        pygame.draw.rect(surface, border_color, self.control_rect, 1)

        # Draw number
        if self.is_editing:
            display_text = self.text_input
        else:
            value = self.property.value or 0
            if self.is_float:
                display_text = f"{value:.{self.property.precision}f}"
            else:
                display_text = str(int(value))

        text_color = colors.get('control_text', pygame.Color(255, 255, 255))
        if self.property.is_readonly():
            text_color = colors.get('readonly_text', pygame.Color(150, 150, 150))

        try:
            if hasattr(font, 'render_premul'):
                text_surface = font.render_premul(display_text, text_color)
            else:
                text_surface = font.render(display_text, True, text_color)

            text_rect = text_surface.get_rect()
            text_rect.centery = self.control_rect.centery
            text_rect.x = self.control_rect.x + 4

            surface.blit(text_surface, text_rect)

            # Draw cursor when editing
            if self.is_editing:
                cursor_x = text_rect.x + font.size(display_text[:self.cursor_pos])[0]
                pygame.draw.line(surface, text_color,
                                 (cursor_x, self.control_rect.y + 4),
                                 (cursor_x, self.control_rect.bottom - 4))

        except Exception as e:
            if PROPERTY_DEBUG:
                print(f"Error rendering number control: {e}")

    def handle_event(self, event: pygame.event.Event, relative_pos: Tuple[int, int]) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.control_rect.collidepoint(relative_pos):
                if not self.is_editing:
                    self.start_editing()
                return True

        elif event.type == pygame.KEYDOWN and self.is_editing:
            if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                self.stop_editing(True)
                return True
            elif event.key == pygame.K_ESCAPE:
                self.stop_editing(False)
                return True
            elif event.key == pygame.K_BACKSPACE:
                if self.cursor_pos > 0:
                    self.text_input = self.text_input[:self.cursor_pos - 1] + self.text_input[self.cursor_pos:]
                    self.cursor_pos -= 1
                return True
            elif event.key == pygame.K_DELETE:
                if self.cursor_pos < len(self.text_input):
                    self.text_input = self.text_input[:self.cursor_pos] + self.text_input[self.cursor_pos + 1:]
                return True
            elif event.key == pygame.K_LEFT:
                self.cursor_pos = max(0, self.cursor_pos - 1)
                return True
            elif event.key == pygame.K_RIGHT:
                self.cursor_pos = min(len(self.text_input), self.cursor_pos + 1)
                return True

        elif event.type == pygame.TEXTINPUT and self.is_editing:
            # Only allow numeric input
            allowed_chars = "0123456789"
            if self.is_float:
                allowed_chars += ".-"

            if event.text in allowed_chars:
                self.text_input = self.text_input[:self.cursor_pos] + event.text + self.text_input[self.cursor_pos:]
                self.cursor_pos += len(event.text)
            return True

        return False


class BooleanPropertyRenderer(PropertyRenderer):
    """Renderer for boolean properties"""

    def _draw_control(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        checkbox_size = min(16, self.control_rect.height - 4)
        checkbox_rect = pygame.Rect(
            self.control_rect.x + 4,
            self.control_rect.centery - checkbox_size // 2,
            checkbox_size,
            checkbox_size
        )

        # Draw checkbox
        box_color = colors.get('control_bg', pygame.Color(60, 60, 60))
        border_color = colors.get('control_border', pygame.Color(100, 100, 100))

        if self.is_focused:
            border_color = colors.get('focused_border', pygame.Color(120, 160, 255))

        pygame.draw.rect(surface, box_color, checkbox_rect)
        pygame.draw.rect(surface, border_color, checkbox_rect, 1)

        # Draw checkmark if true
        if self.property.value:
            check_color = colors.get('accent', pygame.Color(100, 200, 100))
            # Draw checkmark
            points = [
                (checkbox_rect.x + 3, checkbox_rect.centery),
                (checkbox_rect.centerx - 1, checkbox_rect.bottom - 4),
                (checkbox_rect.right - 3, checkbox_rect.y + 3)
            ]
            if len(points) >= 2:
                pygame.draw.lines(surface, check_color, False, points, 2)

    def handle_event(self, event: pygame.event.Event, relative_pos: Tuple[int, int]) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.control_rect.collidepoint(relative_pos):
                if not self.property.is_readonly():
                    self.set_value(not self.property.value)
                return True

        elif event.type == pygame.KEYDOWN and self.is_focused:
            if event.key == pygame.K_SPACE or event.key == pygame.K_RETURN:
                if not self.property.is_readonly():
                    self.set_value(not self.property.value)
                return True

        return False


class DropdownPropertyRenderer(PropertyRenderer):
    """Renderer for dropdown/enum properties"""

    def __init__(self, property_schema: PropertySchema, config: PropertyConfig):
        super().__init__(property_schema, config)
        self.dropdown_open = False
        self.hovered_option = -1

    def _draw_control(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        # Draw dropdown box
        box_color = colors.get('control_bg', pygame.Color(60, 60, 60))
        border_color = colors.get('control_border', pygame.Color(100, 100, 100))

        if self.is_focused or self.dropdown_open:
            border_color = colors.get('focused_border', pygame.Color(120, 160, 255))

        pygame.draw.rect(surface, box_color, self.control_rect)
        pygame.draw.rect(surface, border_color, self.control_rect, 1)

        # Draw current value
        current_text = str(self.property.value or "")
        if self.property.options and self.property.value in self.property.options:
            current_text = self.property.value

        text_color = colors.get('control_text', pygame.Color(255, 255, 255))
        if self.property.is_readonly():
            text_color = colors.get('readonly_text', pygame.Color(150, 150, 150))

        try:
            if hasattr(font, 'render_premul'):
                text_surface = font.render_premul(current_text, text_color)
            else:
                text_surface = font.render(current_text, True, text_color)

            text_rect = text_surface.get_rect()
            text_rect.centery = self.control_rect.centery
            text_rect.x = self.control_rect.x + 4

            surface.blit(text_surface, text_rect)
        except Exception:
            pass

        # Draw dropdown arrow
        arrow_color = colors.get('control_text', pygame.Color(255, 255, 255))
        arrow_center_x = self.control_rect.right - 12
        arrow_center_y = self.control_rect.centery

        if self.dropdown_open:
            # Up arrow
            points = [
                (arrow_center_x - 4, arrow_center_y + 2),
                (arrow_center_x, arrow_center_y - 2),
                (arrow_center_x + 4, arrow_center_y + 2)
            ]
        else:
            # Down arrow
            points = [
                (arrow_center_x - 4, arrow_center_y - 2),
                (arrow_center_x, arrow_center_y + 2),
                (arrow_center_x + 4, arrow_center_y - 2)
            ]

        pygame.draw.polygon(surface, arrow_color, points)

    def handle_event(self, event: pygame.event.Event, relative_pos: Tuple[int, int]) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.control_rect.collidepoint(relative_pos):
                if not self.property.is_readonly():
                    self.dropdown_open = not self.dropdown_open
                return True
            elif self.dropdown_open:
                # Check if clicking on dropdown options
                list_height = len(self.property.options or []) * self.config.row_height
                list_rect = pygame.Rect(
                    self.control_rect.x,
                    self.control_rect.bottom,
                    self.control_rect.width,
                    min(list_height, 200)
                )

                if list_rect.collidepoint(relative_pos):
                    # Calculate which option was clicked
                    option_index = (relative_pos[1] - list_rect.y) // self.config.row_height
                    if 0 <= option_index < len(self.property.options):
                        selected_option = self.property.options[option_index]
                        if self.property.option_values:
                            value = self.property.option_values[option_index]
                        else:
                            value = selected_option
                        self.set_value(value)
                    self.dropdown_open = False
                    return True
                else:
                    self.dropdown_open = False

        elif event.type == pygame.MOUSEMOTION and self.dropdown_open:
            # Update hovered option
            list_height = len(self.property.options or []) * self.config.row_height
            list_rect = pygame.Rect(
                self.control_rect.x,
                self.control_rect.bottom,
                self.control_rect.width,
                min(list_height, 200)
            )

            if list_rect.collidepoint(relative_pos):
                self.hovered_option = (relative_pos[1] - list_rect.y) // self.config.row_height
            else:
                self.hovered_option = -1

        elif event.type == pygame.KEYDOWN and self.is_focused:
            if event.key == pygame.K_SPACE or event.key == pygame.K_RETURN:
                if not self.property.is_readonly():
                    self.dropdown_open = not self.dropdown_open
                return True
            elif event.key == pygame.K_ESCAPE and self.dropdown_open:
                self.dropdown_open = False
                return True

        return False


class ColorPropertyRenderer(PropertyRenderer):
    """Improved renderer for color properties"""

    def __init__(self, property_schema: PropertySchema, config: PropertyConfig):
        super().__init__(property_schema, config)
        self.color_picker_open = False
        self.dragging_hue = False
        self.dragging_sv = False
        self.hsv = [0, 1, 1]  # Hue, Saturation, Value
        self.alpha = 255

        # Pre-create color picker surfaces for better performance
        self.hue_surface = None
        self.sv_surface = None
        self.picker_rect = None

    def _get_color(self) -> pygame.Color:
        """Get the current color as pygame.Color"""
        if isinstance(self.property.value, pygame.Color):
            return self.property.value
        elif isinstance(self.property.value, (list, tuple)) and len(self.property.value) >= 3:
            if len(self.property.value) >= 4:
                return pygame.Color(self.property.value[0], self.property.value[1],
                                    self.property.value[2], self.property.value[3])
            else:
                return pygame.Color(self.property.value[0], self.property.value[1],
                                    self.property.value[2])
        elif isinstance(self.property.value, str):
            try:
                return pygame.Color(self.property.value)
            except ValueError:
                return pygame.Color(255, 255, 255)
        else:
            return pygame.Color(255, 255, 255)

    def _color_to_hsv(self, color: pygame.Color):
        """Convert color to HSV using pygame's built-in conversion"""
        # Use pygame's built-in HSV conversion which is faster
        h, s, v, a = color.hsva
        self.hsv = [h, s / 100.0, v / 100.0]  # Normalize S,V to 0-1
        self.alpha = a * 255 // 100  # Convert percentage to 0-255

    def _hsv_to_color(self) -> pygame.Color:
        """Convert HSV to color using pygame's built-in conversion"""
        color = pygame.Color(0)
        color.hsva = (self.hsv[0], self.hsv[1] * 100, self.hsv[2] * 100, self.alpha * 100 // 255)
        return color

    def _create_hue_surface(self, width: int, height: int) -> pygame.Surface:
        """Create hue bar surface efficiently"""
        if self.hue_surface and self.hue_surface.get_size() == (width, height):
            return self.hue_surface

        self.hue_surface = pygame.Surface((width, height))

        # Create hue gradient more efficiently
        for y in range(height):
            hue = (y / height) * 360
            color = pygame.Color(0)
            color.hsva = (hue, 100, 100, 100)
            pygame.draw.line(self.hue_surface, color, (0, y), (width, y))

        return self.hue_surface

    def _create_sv_surface(self, width: int, height: int, hue: float) -> pygame.Surface:
        """Create saturation/value surface efficiently with caching"""
        cache_key = (width, height, int(hue))

        # Simple cache to avoid recreating identical surfaces
        if not hasattr(self, '_sv_cache'):
            self._sv_cache = {}

        if cache_key in self._sv_cache:
            return self._sv_cache[cache_key]

        surface = pygame.Surface((width, height))

        # Use larger chunks for better performance
        chunk_size = max(2, min(8, width // 20))  # Adaptive chunk size

        for x in range(0, width, chunk_size):
            for y in range(0, height, chunk_size):
                s = x / width
                v = 1.0 - (y / height)

                color = pygame.Color(0)
                color.hsva = (hue, s * 100, v * 100, 100)

                # Draw chunk
                chunk_width = min(chunk_size, width - x)
                chunk_height = min(chunk_size, height - y)
                rect = pygame.Rect(x, y, chunk_width, chunk_height)
                pygame.draw.rect(surface, color, rect)

        # Cache the surface (limit cache size)
        if len(self._sv_cache) > 10:  # Simple cache size limit
            # Remove oldest entry
            oldest_key = next(iter(self._sv_cache))
            del self._sv_cache[oldest_key]

        self._sv_cache[cache_key] = surface
        return surface

    def _get_picker_position(self) -> pygame.Rect:
        """Calculate color picker position, handling screen boundaries"""
        picker_width = 220
        picker_height = 200

        # Default position below the control
        x = self.control_rect.x
        y = self.control_rect.bottom + 2

        # Check if we need to position above instead
        screen_height = pygame.display.get_surface().get_height() if pygame.display.get_surface() else 600
        if y + picker_height > screen_height:
            y = self.control_rect.y - picker_height - 2

        # Check horizontal bounds
        screen_width = pygame.display.get_surface().get_width() if pygame.display.get_surface() else 800
        if x + picker_width > screen_width:
            x = screen_width - picker_width - 10

        return pygame.Rect(x, y, picker_width, picker_height)

    def _draw_control(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        current_color = self._get_color()

        # Draw color swatch
        swatch_size = self.control_rect.height - 4
        swatch_rect = pygame.Rect(
            self.control_rect.x + 2,
            self.control_rect.y + 2,
            swatch_size,
            swatch_size
        )

        # Draw checkerboard background for transparency
        self._draw_transparency_background(surface, swatch_rect)

        # Draw color
        pygame.draw.rect(surface, current_color, swatch_rect)

        # Draw border
        border_color = colors.get('control_border', pygame.Color(100, 100, 100))
        if self.is_focused:
            border_color = colors.get('focused_border', pygame.Color(120, 160, 255))
        pygame.draw.rect(surface, border_color, swatch_rect, 1)

        # Draw color text
        text_x = swatch_rect.right + 4
        color_text = f"#{current_color.r:02x}{current_color.g:02x}{current_color.b:02x}"
        if current_color.a < 255:
            color_text += f"{current_color.a:02x}"

        text_color = colors.get('control_text', pygame.Color(255, 255, 255))
        try:
            if hasattr(font, 'render_premul'):
                text_surface = font.render_premul(color_text, text_color)
            else:
                text_surface = font.render(color_text, True, text_color)

            text_rect = text_surface.get_rect()
            text_rect.centery = self.control_rect.centery
            text_rect.x = text_x

            # Clip text if it would overflow
            available_width = self.control_rect.right - text_x
            if text_surface.get_width() > available_width:
                # Create a subsurface to clip the text
                clipped_width = max(0, available_width)
                if clipped_width > 0:
                    clipped_surface = text_surface.subsurface((0, 0, clipped_width, text_surface.get_height()))
                    surface.blit(clipped_surface, text_rect)
            else:
                surface.blit(text_surface, text_rect)
        except Exception:
            pass

        # Draw color picker if open
        if self.color_picker_open:
            self._draw_color_picker(surface, colors)

    def _draw_transparency_background(self, surface: pygame.Surface, rect: pygame.Rect):
        """Draw checkerboard pattern for transparency visualization"""
        checker_size = 4
        for x in range(0, rect.width, checker_size):
            for y in range(0, rect.height, checker_size):
                checker_color = pygame.Color(200, 200, 200) if (
                                                                           x // checker_size + y // checker_size) % 2 == 0 else pygame.Color(
                    150, 150, 150)
                checker_rect = pygame.Rect(
                    rect.x + x,
                    rect.y + y,
                    min(checker_size, rect.width - x),
                    min(checker_size, rect.height - y)
                )
                pygame.draw.rect(surface, checker_color, checker_rect)

    def _draw_color_picker(self, surface: pygame.Surface, colors: Dict[str, pygame.Color]):
        """Draw the color picker popup with improved positioning"""
        self.picker_rect = self._get_picker_position()

        # Background
        bg_color = colors.get('control_bg', pygame.Color(60, 60, 60))
        border_color = colors.get('control_border', pygame.Color(100, 100, 100))
        pygame.draw.rect(surface, bg_color, self.picker_rect)
        pygame.draw.rect(surface, border_color, self.picker_rect, 1)

        # Color square (saturation/value)
        sv_rect = pygame.Rect(self.picker_rect.x + 10, self.picker_rect.y + 10, 160, 160)
        sv_surface = self._create_sv_surface(sv_rect.width, sv_rect.height, self.hsv[0])
        surface.blit(sv_surface, sv_rect)

        # Draw SV cursor
        cursor_x = sv_rect.x + int(self.hsv[1] * sv_rect.width)
        cursor_y = sv_rect.y + int((1.0 - self.hsv[2]) * sv_rect.height)
        pygame.draw.circle(surface, pygame.Color(255, 255, 255), (cursor_x, cursor_y), 6, 2)
        pygame.draw.circle(surface, pygame.Color(0, 0, 0), (cursor_x, cursor_y), 6, 1)

        # Hue bar
        hue_rect = pygame.Rect(sv_rect.right + 10, sv_rect.y, 20, sv_rect.height)
        hue_surface = self._create_hue_surface(hue_rect.width, hue_rect.height)
        surface.blit(hue_surface, hue_rect)

        # Draw hue cursor
        cursor_y = hue_rect.y + int((self.hsv[0] / 360.0) * hue_rect.height)
        pygame.draw.line(surface, pygame.Color(255, 255, 255),
                         (hue_rect.x - 2, cursor_y), (hue_rect.right + 2, cursor_y), 3)
        pygame.draw.line(surface, pygame.Color(0, 0, 0),
                         (hue_rect.x - 2, cursor_y), (hue_rect.right + 2, cursor_y), 1)

    def handle_event(self, event: pygame.event.Event, relative_pos: Tuple[int, int]) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # CHANGE: Make entire control area clickable, not just the swatch
            if self.control_rect.collidepoint(relative_pos):
                if not self.property.is_readonly():
                    self.color_picker_open = not self.color_picker_open
                    if self.color_picker_open:
                        self._color_to_hsv(self._get_color())
                return True

            elif self.color_picker_open and self.picker_rect:
                if self.picker_rect.collidepoint(relative_pos):
                    # Check SV square
                    sv_rect = pygame.Rect(self.picker_rect.x + 10, self.picker_rect.y + 10, 160, 160)
                    if sv_rect.collidepoint(relative_pos):
                        rel_x = (relative_pos[0] - sv_rect.x) / sv_rect.width
                        rel_y = (relative_pos[1] - sv_rect.y) / sv_rect.height
                        self.hsv[1] = max(0, min(1, rel_x))
                        self.hsv[2] = max(0, min(1, 1 - rel_y))
                        self.set_value(self._hsv_to_color())
                        self.dragging_sv = True
                        return True

                    # Check hue bar
                    hue_rect = pygame.Rect(sv_rect.right + 10, sv_rect.y, 20, sv_rect.height)
                    if hue_rect.collidepoint(relative_pos):
                        rel_y = (relative_pos[1] - hue_rect.y) / hue_rect.height
                        self.hsv[0] = max(0, min(360, rel_y * 360))
                        self.set_value(self._hsv_to_color())
                        self.dragging_hue = True
                        return True
                else:
                    self.color_picker_open = False

        elif event.type == pygame.MOUSEBUTTONUP:
            self.dragging_hue = False
            self.dragging_sv = False

        elif event.type == pygame.MOUSEMOTION and (self.dragging_hue or self.dragging_sv):
            if self.picker_rect:
                if self.dragging_sv:
                    sv_rect = pygame.Rect(self.picker_rect.x + 10, self.picker_rect.y + 10, 160, 160)
                    rel_x = (relative_pos[0] - sv_rect.x) / sv_rect.width
                    rel_y = (relative_pos[1] - sv_rect.y) / sv_rect.height
                    self.hsv[1] = max(0, min(1, rel_x))
                    self.hsv[2] = max(0, min(1, 1 - rel_y))
                    self.set_value(self._hsv_to_color())
                    return True
                elif self.dragging_hue:
                    sv_rect = pygame.Rect(self.picker_rect.x + 10, self.picker_rect.y + 10, 160, 160)
                    hue_rect = pygame.Rect(sv_rect.right + 10, sv_rect.y, 20, sv_rect.height)
                    rel_y = (relative_pos[1] - hue_rect.y) / hue_rect.height
                    self.hsv[0] = max(0, min(360, rel_y * 360))
                    self.set_value(self._hsv_to_color())
                    return True

        return False


class VectorPropertyRenderer(PropertyRenderer):
    """Renderer for vector2/vector3 properties - Simple text version"""

    def __init__(self, property_schema: PropertySchema, config: PropertyConfig):
        super().__init__(property_schema, config)
        self.component_count = 3 if property_schema.property_type == PropertyType.VECTOR3 else 2
        self.editing_component = -1
        self.text_input = ""
        self.cursor_pos = 0
        self.blink_timer = 0
        self.show_cursor = True

        # Ensure the property value is properly formatted as floats from the start
        if self.property.value:
            vector_value = self._get_vector_value()
            self.property.value = vector_value

    def _get_vector_value(self) -> List[float]:
        """Get vector as list of floats"""
        value = self.property.value
        if isinstance(value, (list, tuple)) and len(value) >= self.component_count:
            return [float(value[i]) for i in range(self.component_count)]
        elif hasattr(value, 'x') and hasattr(value, 'y'):
            result = [float(value.x), float(value.y)]
            if self.component_count > 2 and hasattr(value, 'z'):
                result.append(float(value.z))
            return result
        return [0.0] * self.component_count

    def _format_vector_text(self, vector_value: List[float]) -> str:
        """Format vector as readable text"""
        if self.component_count == 2:
            return f"[{vector_value[0]:.{self.property.precision}f}, {vector_value[1]:.{self.property.precision}f}]"
        else:
            return f"[{vector_value[0]:.{self.property.precision}f}, {vector_value[1]:.{self.property.precision}f}, {vector_value[2]:.{self.property.precision}f}]"

    def _parse_vector_text(self, text: str) -> List[float]:
        """Parse text back to vector"""
        try:
            # Remove brackets and split by comma
            clean_text = text.strip('[]')
            parts = [part.strip() for part in clean_text.split(',')]
            return [float(part) for part in parts[:self.component_count]]
        except:
            return self._get_vector_value()  # Return current value on error

    def start_editing(self):
        """Start editing this property"""
        super().start_editing()
        if self.is_editing:
            vector_value = self._get_vector_value()
            self.text_input = self._format_vector_text(vector_value)
            self.cursor_pos = len(self.text_input)

    def stop_editing(self, save: bool = True):
        """Stop editing this property"""
        if self.is_editing and save:
            vector_value = self._parse_vector_text(self.text_input)
            self.set_value(vector_value)
        super().stop_editing(save)

    def _draw_control(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        """Draw the vector control - exactly like TextPropertyRenderer"""
        # Draw text input box
        box_color = colors.get('control_bg', pygame.Color(60, 60, 60))
        border_color = colors.get('control_border', pygame.Color(100, 100, 100))

        if self.is_editing:
            border_color = colors.get('focused_border', pygame.Color(120, 160, 255))

        pygame.draw.rect(surface, box_color, self.control_rect)
        pygame.draw.rect(surface, border_color, self.control_rect, 1)

        # Draw text
        if self.is_editing:
            display_text = self.text_input
        else:
            vector_value = self._get_vector_value()
            display_text = self._format_vector_text(vector_value)

        text_color = colors.get('control_text', pygame.Color(255, 255, 255))
        if self.property.is_readonly():
            text_color = colors.get('readonly_text', pygame.Color(150, 150, 150))

        try:
            if hasattr(font, 'render_premul'):
                text_surface = font.render_premul(display_text, text_color)
            else:
                text_surface = font.render(display_text, True, text_color)

            # Position text exactly like TextPropertyRenderer
            text_rect = text_surface.get_rect()
            text_rect.centery = self.control_rect.centery
            text_rect.x = self.control_rect.x + 4

            # Create clipping rect exactly like TextPropertyRenderer
            clip_rect = self.control_rect.copy()
            clip_rect.width -= 8  # Padding

            surface.set_clip(clip_rect)
            surface.blit(text_surface, text_rect)
            surface.set_clip(None)

            # Draw cursor when editing - exactly like TextPropertyRenderer
            if self.is_editing and self.show_cursor:
                cursor_x = text_rect.x + font.size(display_text[:self.cursor_pos])[0]
                if self.control_rect.contains(cursor_x, self.control_rect.y, 1, self.control_rect.height):
                    pygame.draw.line(surface, text_color,
                                   (cursor_x, self.control_rect.y + 4),
                                   (cursor_x, self.control_rect.bottom - 4))

        except Exception as e:
            if PROPERTY_DEBUG:
                print(f"Error rendering vector control: {e}")

    def handle_event(self, event: pygame.event.Event, relative_pos: Tuple[int, int]) -> bool:
        """Handle events - exactly like TextPropertyRenderer"""
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.control_rect.collidepoint(relative_pos):
                if not self.is_editing:
                    self.start_editing()
                else:
                    # Position cursor
                    self.cursor_pos = len(self.text_input)
                return True

        elif event.type == pygame.KEYDOWN and self.is_editing:
            if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                self.stop_editing(True)
                return True
            elif event.key == pygame.K_ESCAPE:
                self.stop_editing(False)
                return True
            elif event.key == pygame.K_BACKSPACE:
                if self.cursor_pos > 0:
                    self.text_input = self.text_input[:self.cursor_pos - 1] + self.text_input[self.cursor_pos:]
                    self.cursor_pos -= 1
                return True
            elif event.key == pygame.K_DELETE:
                if self.cursor_pos < len(self.text_input):
                    self.text_input = self.text_input[:self.cursor_pos] + self.text_input[self.cursor_pos + 1:]
                return True
            elif event.key == pygame.K_LEFT:
                self.cursor_pos = max(0, self.cursor_pos - 1)
                return True
            elif event.key == pygame.K_RIGHT:
                self.cursor_pos = min(len(self.text_input), self.cursor_pos + 1)
                return True
            elif event.key == pygame.K_HOME:
                self.cursor_pos = 0
                return True
            elif event.key == pygame.K_END:
                self.cursor_pos = len(self.text_input)
                return True

        elif event.type == pygame.TEXTINPUT and self.is_editing:
            # Allow vector-appropriate characters
            if event.text in "0123456789.,-[] ":
                self.text_input = self.text_input[:self.cursor_pos] + event.text + self.text_input[self.cursor_pos:]
                self.cursor_pos += len(event.text)
            return True

        return False


class PropertyPanel(UIElement):
    """Main property inspector panel widget"""

    def __init__(self, relative_rect: pygame.Rect,
                 manager: pygame_gui.UIManager,
                 config: PropertyConfig = None,
                 container: IContainerLikeInterface = None,
                 object_id: Union[ObjectID, str, None] = None,
                 anchors: Dict[str, str] = None):

        # Handle object_id properly
        if isinstance(object_id, ObjectID):
            self._object_id = object_id
        elif isinstance(object_id, str):
            self._object_id = ObjectID(object_id=object_id, class_id=None)
        else:
            self._object_id = ObjectID(object_id='#property_inspector', class_id=None)

        super().__init__(relative_rect, manager, container,
                         starting_height=1, layer_thickness=1,
                         anchors=anchors, object_id=self._object_id)

        self.config = config or PropertyConfig()

        # Property data
        self.properties: Dict[str, PropertySchema] = {}
        self.sections: Dict[str, PropertySection] = {}
        self._original_properties: List[PropertySchema] = []
        self.target_object: Any = None
        self.change_callback: Optional[Callable[[str, Any, Any], None]] = None

        # UI state
        self.renderers: Dict[str, PropertyRenderer] = {}
        self.section_rects: Dict[str, pygame.Rect] = {}
        self.visible_properties: List[str] = []
        self.focused_property: Optional[str] = None
        self.is_panel_focused = False

        # Scrolling
        self.scroll_y = 0
        self.max_scroll = 0
        self.content_height = 0

        # Theme data
        self._update_theme_data()

        # Create the image surface
        self.image = pygame.Surface(self.rect.size).convert()

        # Initialize
        self.rebuild_ui()
        self._rebuild_image()

    def _needs_rebuild(self) -> bool:
        """Check if UI actually needs rebuilding"""
        if not hasattr(self, '_last_rebuild_state'):
            self._last_rebuild_state = None
            return True

        # Create current state signature
        current_state = {
            'scroll_y': self.scroll_y,
            'rect_size': (self.rect.width, self.rect.height),
            'section_states': {s.id: s.expanded for s in self.sections.values()},
            'focused_property': self.focused_property,
            'property_count': len(self.properties)
        }

        if current_state != self._last_rebuild_state:
            self._last_rebuild_state = current_state
            return True

        return False

    def _update_theme_data(self):
        """Update theme-dependent data"""
        try:
            self.themed_colors = {}

            color_mappings = {
                'dark_bg': pygame.Color(45, 45, 45),
                'normal_text': pygame.Color(255, 255, 255),
                'secondary_text': pygame.Color(180, 180, 180),
                'readonly_text': pygame.Color(150, 150, 150),
                'section_bg': pygame.Color(35, 35, 35),
                'section_text': pygame.Color(200, 200, 200),
                'control_bg': pygame.Color(60, 60, 60),
                'control_text': pygame.Color(255, 255, 255),
                'control_border': pygame.Color(100, 100, 100),
                'focused_bg': pygame.Color(50, 80, 120),
                'focused_border': pygame.Color(120, 160, 255),
                'hovered_bg': pygame.Color(50, 50, 50),
                'selected_bg': pygame.Color(70, 130, 180),
                'error_bg': pygame.Color(60, 20, 20),
                'error_text': pygame.Color(255, 100, 100),
                'accent': pygame.Color(100, 200, 100),
                'normal_border': pygame.Color(80, 80, 80),
            }

            theme = self.ui_manager.get_theme()

            for color_id, default_color in color_mappings.items():
                try:
                    if hasattr(theme, 'get_colour_or_gradient'):
                        color = theme.get_colour_or_gradient(color_id, ['property_inspector'])
                        self.themed_colors[color_id] = color if color else default_color
                    else:
                        self.themed_colors[color_id] = default_color
                except Exception:
                    self.themed_colors[color_id] = default_color

            # Get themed font
            try:
                if hasattr(theme, 'get_font'):
                    self.themed_font = theme.get_font(['property_inspector'])
                else:
                    raise Exception("No font method")
            except Exception:
                try:
                    self.themed_font = pygame.font.SysFont('Arial', 12)
                except:
                    self.themed_font = pygame.font.Font(None, 12)

        except Exception as e:
            if PROPERTY_DEBUG:
                print(f"Error getting theme data: {e}")
            # Complete fallback
            self.themed_colors = {
                'dark_bg': pygame.Color(45, 45, 45),
                'normal_text': pygame.Color(255, 255, 255),
                'secondary_text': pygame.Color(180, 180, 180),
                'readonly_text': pygame.Color(150, 150, 150),
                'section_bg': pygame.Color(35, 35, 35),
                'section_text': pygame.Color(200, 200, 200),
                'control_bg': pygame.Color(60, 60, 60),
                'control_text': pygame.Color(255, 255, 255),
                'control_border': pygame.Color(100, 100, 100),
                'focused_bg': pygame.Color(50, 80, 120),
                'focused_border': pygame.Color(120, 160, 255),
                'hovered_bg': pygame.Color(50, 50, 50),
                'selected_bg': pygame.Color(70, 130, 180),
                'error_bg': pygame.Color(60, 20, 20),
                'error_text': pygame.Color(255, 100, 100),
                'accent': pygame.Color(100, 200, 100),
                'normal_border': pygame.Color(80, 80, 80),
            }
            try:
                self.themed_font = pygame.font.SysFont('Arial', 12)
            except:
                self.themed_font = pygame.font.Font(None, 12)

    def rebuild_from_changed_theme_data(self):
        """Called when theme data changes"""
        self._update_theme_data()
        self.rebuild_ui()
        self._rebuild_image()

    def set_properties(self, properties: List[PropertySchema], target_object: Any = None):
        """Set the properties to display"""
        self.target_object = target_object
        self.properties.clear()
        self.sections.clear()
        self.renderers.clear()

        # Store the original, unfiltered properties list
        self._original_properties = properties.copy()

        # Organize properties by section
        for prop in properties:
            if prop.is_hidden():
                continue
            if prop.is_advanced() and not self.config.show_advanced_properties:
                continue

            self.properties[prop.id] = prop

            section_name = prop.section or "General"
            if section_name not in self.sections:
                self.sections[section_name] = PropertySection(
                    section_name, section_name, True,
                    order=len(self.sections)
                )

            self.sections[section_name].properties.append(prop)

        # Sort sections and properties
        for section in self.sections.values():
            section.properties.sort(key=lambda p: p.order)

        # Create renderers
        self._create_renderers()

        # Rebuild UI
        self.rebuild_ui()
        self._rebuild_image()

    def _create_renderers(self):
        """Create property renderers based on property types"""
        self.renderers.clear()

        for prop in self.properties.values():
            if prop.property_type == PropertyType.TEXT or prop.property_type == PropertyType.MULTILINE_TEXT:
                renderer = TextPropertyRenderer(prop, self.config)
            elif prop.property_type == PropertyType.NUMBER or prop.property_type == PropertyType.SLIDER:
                renderer = NumberPropertyRenderer(prop, self.config)
            elif prop.property_type == PropertyType.BOOLEAN:
                renderer = BooleanPropertyRenderer(prop, self.config)
            elif prop.property_type == PropertyType.DROPDOWN:
                renderer = DropdownPropertyRenderer(prop, self.config)
            elif prop.property_type == PropertyType.COLOR:
                renderer = ColorPropertyRenderer(prop, self.config)
            elif prop.property_type == PropertyType.VECTOR2 or prop.property_type == PropertyType.VECTOR3:
                renderer = VectorPropertyRenderer(prop, self.config)
            else:
                # Default to text renderer
                renderer = TextPropertyRenderer(prop, self.config)

            self.renderers[prop.id] = renderer

    def rebuild_ui(self):
        """Rebuild the UI layout"""
        if not self._needs_rebuild():
            return  # Skip rebuild if nothing changed

        if PROPERTY_DEBUG:
            print("Rebuilding property inspector UI...")

        self.visible_properties.clear()
        self.section_rects.clear()

        current_y = 0
        label_width = max(self.config.min_label_width,
                          int(self.rect.width * self.config.label_width_ratio))

        # Sort sections by order
        sorted_sections = sorted(self.sections.values(), key=lambda s: s.order)

        for section in sorted_sections:
            if not section.properties:
                continue

            # Section header
            section_rect = pygame.Rect(
                0, current_y - self.scroll_y,
                self.rect.width, self.config.section_header_height
            )
            self.section_rects[section.id] = section_rect
            current_y += self.config.section_header_height

            # Section properties (if expanded)
            if section.expanded:
                for prop in section.properties:
                    # Store absolute Y position for layout
                    absolute_y = current_y - self.scroll_y
                    prop_rect = pygame.Rect(
                        0, absolute_y,
                        self.rect.width, self.config.row_height
                    )

                    if prop.id in self.renderers:
                        renderer = self.renderers[prop.id]
                        renderer.set_geometry(prop_rect, label_width)

                        # Update focus state
                        renderer.is_focused = (prop.id == self.focused_property)

                    self.visible_properties.append(prop.id)
                    current_y += self.config.row_height

        # Update content height and max scroll
        self.content_height = current_y
        self.max_scroll = max(0, self.content_height - self.rect.height)

        if PROPERTY_DEBUG:
            print(f"UI rebuilt: {len(self.visible_properties)} visible properties, "
                  f"content_height: {self.content_height}, max_scroll: {self.max_scroll}")

    def _rebuild_image(self):
        """Rebuild the image surface"""
        # Fill background
        bg_color = self.themed_colors.get('dark_bg', pygame.Color(45, 45, 45))
        if hasattr(bg_color, 'apply_gradient_to_surface'):
            bg_color.apply_gradient_to_surface(self.image)
        else:
            self.image.fill(bg_color)

        # Draw sections and properties
        for section_id, section in self.sections.items():
            if section_id in self.section_rects:
                section_rect = self.section_rects[section_id]
                if 0 <= section_rect.y < self.rect.height and section_rect.bottom > 0:
                    self._draw_section_header(section, section_rect)

        # Draw properties
        open_dropdowns = []  # Track dropdown renderers for later drawing
        open_color_pickers = []  # Track color pickers

        for prop_id in self.visible_properties:
            if prop_id in self.renderers:
                renderer = self.renderers[prop_id]
                # Check if property is visible
                # if (renderer.rect.y >= -self.config.row_height and renderer.rect.y < self.rect.height):
                if -self.config.row_height <= renderer.rect.y < self.rect.height:

                    # Calculate surface rect (clamped to image bounds)
                    surface_y = max(0, renderer.rect.y)
                    surface_height = min(self.config.row_height,
                                         self.rect.height - surface_y)

                    if surface_height > 0:
                        try:
                            # Create subsurface at the correct position
                            surface_rect = pygame.Rect(0, surface_y, self.rect.width, surface_height)
                            prop_surface = self.image.subsurface(surface_rect)

                            # Adjust renderer drawing if partially clipped
                            draw_offset_y = surface_y - renderer.rect.y

                            # Create a temporary rect for drawing
                            draw_rect = pygame.Rect(0, draw_offset_y, self.rect.width, self.config.row_height)

                            # Temporarily adjust renderer geometry for drawing
                            old_rect = renderer.rect
                            old_label_rect = renderer.label_rect
                            old_control_rect = renderer.control_rect

                            renderer.rect = draw_rect
                            renderer.label_rect = pygame.Rect(
                                draw_rect.x, draw_rect.y,
                                old_label_rect.width, draw_rect.height
                            )
                            renderer.control_rect = pygame.Rect(
                                draw_rect.x + old_label_rect.width + self.config.control_spacing,
                                draw_rect.y,
                                old_control_rect.width, draw_rect.height
                            )

                            # Special handling for dropdown renderers
                            if isinstance(renderer, DropdownPropertyRenderer):
                                # Draw property without dropdown list on subsurface
                                self._draw_property_without_dropdown(renderer, prop_surface)
                                # Store for later drawing on main surface
                                if renderer.dropdown_open:
                                    open_dropdowns.append((renderer, old_rect, old_label_rect, old_control_rect))
                            # Special handling for color picker renderers
                            elif isinstance(renderer, ColorPropertyRenderer):
                                # Draw property without color picker on subsurface
                                self._draw_property_without_color_picker(renderer, prop_surface)
                                # Store for later drawing on main surface
                                if renderer.color_picker_open:
                                    open_color_pickers.append((renderer, old_rect, old_label_rect, old_control_rect))
                            else:
                                # Draw the property normally
                                renderer.draw(prop_surface, self.themed_font, self.themed_colors)

                            # Restore original geometry
                            renderer.rect = old_rect
                            renderer.label_rect = old_label_rect
                            renderer.control_rect = old_control_rect

                        except (ValueError, pygame.error) as e:
                            if PROPERTY_DEBUG:
                                print(f"Error creating subsurface for {prop_id}: {e}")

        # Draw open dropdown lists on the main surface (after all properties)
        for renderer, orig_rect, orig_label_rect, orig_control_rect in open_dropdowns:
            if renderer.dropdown_open and renderer.property.options:
                self._draw_dropdown_list(renderer, orig_rect, orig_label_rect, orig_control_rect)

        # Draw open color pickers on the main surface (after all properties)
        for renderer, orig_rect, orig_label_rect, orig_control_rect in open_color_pickers:
            if renderer.color_picker_open:
                self._draw_color_picker_popup(renderer, orig_rect, orig_label_rect, orig_control_rect)

        # Draw border
        border_color = self.themed_colors.get('normal_border', pygame.Color(80, 80, 80))
        pygame.draw.rect(self.image, border_color, self.image.get_rect(), 1)

        # Draw focus indicator if panel is focused
        if self.is_panel_focused:
            focus_color = self.themed_colors.get('focused_border', pygame.Color(120, 160, 255))
            pygame.draw.rect(self.image, focus_color, self.image.get_rect(), 2)

    def _draw_property_without_dropdown(self, renderer: DropdownPropertyRenderer, surface: pygame.Surface):
        """Draw dropdown property without the dropdown list"""
        # Temporarily disable dropdown for drawing
        dropdown_open = renderer.dropdown_open
        renderer.dropdown_open = False

        # Draw the property
        renderer.draw(surface, self.themed_font, self.themed_colors)

        # Restore dropdown state
        renderer.dropdown_open = dropdown_open

    def _draw_dropdown_list(self, renderer: DropdownPropertyRenderer, orig_rect: pygame.Rect,
                            orig_label_rect: pygame.Rect, orig_control_rect: pygame.Rect):
        """Draw dropdown list on the main surface"""
        if not renderer.property.options:
            return

        # Calculate dropdown list position using original control rect
        list_height = len(renderer.property.options) * self.config.row_height
        list_rect = pygame.Rect(
            orig_control_rect.x,
            orig_control_rect.bottom,
            orig_control_rect.width,
            min(list_height, 200)  # Max height
        )

        # Clip list rect to panel bounds
        panel_rect = pygame.Rect(0, 0, self.rect.width, self.rect.height)
        clipped_list_rect = list_rect.clip(panel_rect)

        if clipped_list_rect.width <= 0 or clipped_list_rect.height <= 0:
            return  # Nothing to draw

        # Background and border
        box_color = self.themed_colors.get('control_bg', pygame.Color(60, 60, 60))
        border_color = self.themed_colors.get('control_border', pygame.Color(100, 100, 100))

        pygame.draw.rect(self.image, box_color, clipped_list_rect)
        pygame.draw.rect(self.image, border_color, clipped_list_rect, 1)

        # Draw options
        text_color = self.themed_colors.get('control_text', pygame.Color(255, 255, 255))

        for i, option in enumerate(renderer.property.options):
            option_rect = pygame.Rect(
                list_rect.x,
                list_rect.y + i * self.config.row_height,
                list_rect.width,
                self.config.row_height
            )

            # Clip option rect to visible area
            visible_option_rect = option_rect.clip(clipped_list_rect)
            if visible_option_rect.width <= 0 or visible_option_rect.height <= 0:
                continue

            # Draw hover background
            if i == renderer.hovered_option:
                pygame.draw.rect(self.image, self.themed_colors.get('hovered_bg', pygame.Color(80, 80, 80)),
                                 visible_option_rect)

            # Draw selection background
            if option == renderer.property.value:
                pygame.draw.rect(self.image, self.themed_colors.get('selected_bg', pygame.Color(70, 130, 180)),
                                 visible_option_rect)

            # Draw option text
            try:
                if hasattr(self.themed_font, 'render_premul'):
                    option_surface = self.themed_font.render_premul(str(option), text_color)
                else:
                    option_surface = self.themed_font.render(str(option), True, text_color)

                option_text_rect = option_surface.get_rect()
                option_text_rect.centery = option_rect.centery
                option_text_rect.x = option_rect.x + 4

                # Only draw if text is within visible area
                if option_text_rect.colliderect(clipped_list_rect):
                    # Clip text to visible area if needed
                    clip_rect = option_text_rect.clip(clipped_list_rect)
                    if clip_rect.width > 0 and clip_rect.height > 0:
                        self.image.blit(option_surface, option_text_rect,
                                        (clip_rect.x - option_text_rect.x,
                                         clip_rect.y - option_text_rect.y,
                                         clip_rect.width, clip_rect.height))
            except Exception as e:
                if PROPERTY_DEBUG:
                    print(f"Error rendering dropdown option: {e}")

    def _draw_property_without_color_picker(self, renderer: ColorPropertyRenderer, surface: pygame.Surface):
        """Draw color property without the color picker"""
        # Temporarily disable color picker for drawing
        color_picker_open = renderer.color_picker_open
        renderer.color_picker_open = False

        # Draw the property
        renderer.draw(surface, self.themed_font, self.themed_colors)

        # Restore color picker state
        renderer.color_picker_open = color_picker_open

    def _draw_color_picker_popup(self, renderer: ColorPropertyRenderer, orig_rect: pygame.Rect,
                                 orig_label_rect: pygame.Rect, orig_control_rect: pygame.Rect):
        """Draw color picker popup on the main surface"""
        if not renderer.color_picker_open:
            return

        # Temporarily restore original geometry
        old_rect = renderer.rect
        old_label_rect = renderer.label_rect
        old_control_rect = renderer.control_rect

        renderer.rect = orig_rect
        renderer.label_rect = orig_label_rect
        renderer.control_rect = orig_control_rect

        # Draw color picker directly on main surface
        renderer._draw_color_picker(self.image, self.themed_colors)

        # Restore current geometry
        renderer.rect = old_rect
        renderer.label_rect = old_label_rect
        renderer.control_rect = old_control_rect

    def _draw_section_header(self, section: PropertySection, rect: pygame.Rect):
        """Draw a section header"""
        if rect.bottom < 0 or rect.y >= self.rect.height:
            return  # Outside visible area

        # Calculate visible portion
        visible_rect = rect.clip(pygame.Rect(0, 0, self.rect.width, self.rect.height))
        if visible_rect.width <= 0 or visible_rect.height <= 0:
            return

        # Background
        section_bg = self.themed_colors.get('section_bg', pygame.Color(35, 35, 35))
        try:
            section_surface = self.image.subsurface(visible_rect)
            section_surface.fill(section_bg)
        except (ValueError, pygame.error):
            return

        # Only draw text/icons if the header is mostly visible
        if rect.y >= 0 and rect.bottom <= self.rect.height:
            # Expand/collapse triangle
            triangle_x = 8
            triangle_y = rect.centery
            triangle_color = self.themed_colors.get('section_text', pygame.Color(200, 200, 200))

            if section.expanded:
                # Down triangle
                points = [
                    (triangle_x, triangle_y - 4),
                    (triangle_x + 8, triangle_y - 4),
                    (triangle_x + 4, triangle_y + 2)
                ]
            else:
                # Right triangle
                points = [
                    (triangle_x, triangle_y - 4),
                    (triangle_x, triangle_y + 4),
                    (triangle_x + 6, triangle_y)
                ]

            pygame.draw.polygon(self.image, triangle_color, points)

            # Section label
            text_x = triangle_x + 12
            text_color = self.themed_colors.get('section_text', pygame.Color(200, 200, 200))

            try:
                if hasattr(self.themed_font, 'render_premul'):
                    text_surface = self.themed_font.render_premul(section.label, text_color)
                else:
                    text_surface = self.themed_font.render(section.label, True, text_color)

                text_rect = text_surface.get_rect()
                text_rect.centery = rect.centery
                text_rect.x = text_x

                self.image.blit(text_surface, text_rect)

            except Exception as e:
                if PROPERTY_DEBUG:
                    print(f"Error rendering section header: {e}")

    def process_event(self, event: pygame.event.Event) -> bool:
        """Process pygame events"""
        consumed = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.is_panel_focused = True
                relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)

                if event.button == 1:  # Left click
                    consumed = self._handle_left_click(relative_pos)
                elif event.button == 3:  # Right click
                    consumed = self._handle_right_click(relative_pos)
            else:
                self.is_panel_focused = False
                self._stop_all_editing()

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)
                consumed = self._handle_mouse_up(relative_pos)

        elif event.type == pygame.MOUSEMOTION:
            relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)
            consumed = self._handle_mouse_motion(relative_pos)

        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                consumed = self._handle_scroll(event.y)

        elif event.type == pygame.KEYDOWN and self.is_panel_focused:
            consumed = self._handle_key_event(event)

        elif event.type == pygame.TEXTINPUT and self.is_panel_focused:
            consumed = self._handle_text_input(event)

        # Forward to focused property renderer
        if not consumed and self.focused_property and self.focused_property in self.renderers:
            relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y) if hasattr(event, 'pos') else (0, 0)
            consumed = self.renderers[self.focused_property].handle_event(event, relative_pos)
            if consumed:
                self._rebuild_image()

        return consumed

    def _handle_left_click(self, pos: Tuple[int, int]) -> bool:
        """Handle left mouse click"""

        # Check if ANY dropdown is open - if so, handle ALL clicks here
        for prop_id in self.visible_properties:
            if prop_id in self.renderers:
                renderer = self.renderers[prop_id]
                if isinstance(renderer, DropdownPropertyRenderer) and renderer.dropdown_open:
                    # Check if clicking on dropdown options
                    if renderer.property.options:
                        list_height = len(renderer.property.options) * self.config.row_height
                        list_rect = pygame.Rect(
                            renderer.control_rect.x,
                            renderer.control_rect.bottom,
                            renderer.control_rect.width,
                            min(list_height, 200)
                        )

                        if list_rect.collidepoint(pos):
                            # Calculate which option was clicked
                            option_index = (pos[1] - list_rect.y) // self.config.row_height
                            if 0 <= option_index < len(renderer.property.options):
                                selected_option = renderer.property.options[option_index]
                                if renderer.property.option_values:
                                    value = renderer.property.option_values[option_index]
                                else:
                                    value = selected_option
                                renderer.set_value(value)
                                self._check_property_changed(prop_id)
                            renderer.dropdown_open = False
                            self._rebuild_image()
                            return True
                        else:
                            # Click outside dropdown - close it AND CONSUME THE CLICK
                            renderer.dropdown_open = False
                            self._rebuild_image()
                            return True  # CHANGE: Return True to consume the click

        # Check if ANY color picker is open - if so, handle ALL clicks here
        for prop_id in self.visible_properties:
            if prop_id in self.renderers:
                renderer = self.renderers[prop_id]
                if isinstance(renderer, ColorPropertyRenderer) and renderer.color_picker_open:
                    if renderer.picker_rect and renderer.picker_rect.collidepoint(pos):
                        # Forward click to color picker renderer
                        consumed = renderer.handle_event(
                            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {'button': 1, 'pos': pos}),
                            pos
                        )
                        if consumed:
                            self._check_property_changed(prop_id)
                            self._rebuild_image()
                        return True
                    else:
                        # Click outside color picker - close it AND CONSUME THE CLICK
                        renderer.color_picker_open = False
                        self._rebuild_image()
                        return True  # CHANGE: Return True to consume the click

        # Only check section headers if NO popups are open
        for section_id, rect in self.section_rects.items():
            if rect.collidepoint(pos):
                section = self.sections[section_id]
                section.expanded = not section.expanded

                event_data = {
                    'section': section,
                    'ui_element': self,
                    'expanded': section.expanded
                }
                pygame.event.post(pygame.event.Event(UI_PROPERTY_SECTION_TOGGLED, event_data))

                self.rebuild_ui()
                self._rebuild_image()
                return True

        # Finally check property renderers normally
        for prop_id in self.visible_properties:
            if prop_id in self.renderers:
                renderer = self.renderers[prop_id]
                if renderer.rect.collidepoint(pos):
                    # Focus this property
                    if self.focused_property != prop_id:
                        self._stop_all_editing()
                        self.focused_property = prop_id
                        self.rebuild_ui()
                        self._rebuild_image()

                    # Forward to renderer
                    consumed = renderer.handle_event(
                        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {'button': 1, 'pos': pos}),
                        pos
                    )
                    if consumed:
                        self._rebuild_image()
                    return True

        return False

    def _handle_right_click(self, pos: Tuple[int, int]) -> bool:
        """Handle right mouse click"""
        # Find clicked property
        for prop_id in self.visible_properties:
            if prop_id in self.renderers:
                renderer = self.renderers[prop_id]
                if renderer.rect.collidepoint(pos):
                    # Fire context menu event
                    event_data = {
                        'property': renderer.property,
                        'ui_element': self,
                        'mouse_pos': pos
                    }
                    pygame.event.post(pygame.event.Event(UI_PROPERTY_RESET_REQUESTED, event_data))
                    return True

        return False

    def _handle_mouse_up(self, pos: Tuple[int, int]) -> bool:
        """Handle mouse up"""
        # Check open color pickers first
        for prop_id in self.visible_properties:
            if prop_id in self.renderers:
                renderer = self.renderers[prop_id]
                if isinstance(renderer, ColorPropertyRenderer) and renderer.color_picker_open:
                    if renderer.picker_rect and renderer.picker_rect.collidepoint(pos):
                        consumed = renderer.handle_event(
                            pygame.event.Event(pygame.MOUSEBUTTONUP, {'button': 1}), pos
                        )
                        if consumed:
                            self._rebuild_image()
                            return True

        # Original logic for other renderers
        consumed = False
        for renderer in self.renderers.values():
            if renderer.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, {'button': 1}), pos):
                consumed = True
                self._rebuild_image()
                break
        return consumed

    def _handle_mouse_motion(self, pos: Tuple[int, int]) -> bool:
        """Handle mouse motion"""
        hover_changed = False
        mouse_over_dropdown = False
        mouse_over_color_picker = False

        # Check dropdown lists first for hover states
        for prop_id in self.visible_properties:
            if prop_id in self.renderers:
                renderer = self.renderers[prop_id]
                if isinstance(renderer, DropdownPropertyRenderer) and renderer.dropdown_open:
                    if renderer.property.options:
                        list_height = len(renderer.property.options) * self.config.row_height
                        list_rect = pygame.Rect(
                            renderer.control_rect.x,
                            renderer.control_rect.bottom,
                            renderer.control_rect.width,
                            min(list_height, 200)
                        )

                        if list_rect.collidepoint(pos):
                            mouse_over_dropdown = True
                            new_hovered_option = (pos[1] - list_rect.y) // self.config.row_height
                            if 0 <= new_hovered_option < len(renderer.property.options):
                                if new_hovered_option != renderer.hovered_option:
                                    renderer.hovered_option = new_hovered_option
                                    hover_changed = True
                            else:
                                if renderer.hovered_option != -1:
                                    renderer.hovered_option = -1
                                    hover_changed = True
                        else:
                            if renderer.hovered_option != -1:
                                renderer.hovered_option = -1
                                hover_changed = True

        # Check color pickers for hover states
        if not mouse_over_dropdown:  # Only if not over dropdown
            for prop_id in self.visible_properties:
                if prop_id in self.renderers:
                    renderer = self.renderers[prop_id]
                    if isinstance(renderer, ColorPropertyRenderer) and renderer.color_picker_open:
                        if renderer.picker_rect and renderer.picker_rect.collidepoint(pos):
                            mouse_over_color_picker = True
                            # Forward motion to color picker
                            if renderer.handle_event(
                                pygame.event.Event(pygame.MOUSEMOTION, {'pos': pos}), pos
                            ):
                                hover_changed = True
                            break

        # Only update property hover states if mouse is NOT over a dropdown OR color picker
        if not mouse_over_dropdown and not mouse_over_color_picker:
            for prop_id in self.visible_properties:
                if prop_id in self.renderers:
                    renderer = self.renderers[prop_id]
                    new_hovered = renderer.rect.collidepoint(pos)
                    if new_hovered != renderer.is_hovered:
                        renderer.is_hovered = new_hovered
                        hover_changed = True
        else:
            # Clear hover states for all properties when mouse is over dropdown/color picker
            for prop_id in self.visible_properties:
                if prop_id in self.renderers:
                    renderer = self.renderers[prop_id]
                    if renderer.is_hovered:
                        renderer.is_hovered = False
                        hover_changed = True

        # Forward to focused renderer (only if not over dropdown)
        renderer_consumed = False
        if not mouse_over_dropdown and self.focused_property and self.focused_property in self.renderers:
            if self.renderers[self.focused_property].handle_event(
                    pygame.event.Event(pygame.MOUSEMOTION, {'pos': pos}), pos
            ):
                renderer_consumed = True

        # Only rebuild if something actually changed
        if hover_changed or renderer_consumed:
            self._rebuild_image()

        return hover_changed or renderer_consumed

    def _handle_scroll(self, delta: int) -> bool:
        """Handle scroll wheel"""
        scroll_speed = self.config.row_height * 3
        old_scroll = self.scroll_y
        self.scroll_y = max(0, min(self.max_scroll, self.scroll_y - delta * scroll_speed))

        if old_scroll != self.scroll_y:
            self.rebuild_ui()
            self._rebuild_image()
            return True

        return False

    def _handle_key_event(self, event: pygame.event.Event) -> bool:
        """Handle keyboard events"""
        if event.key == pygame.K_TAB:
            # Tab to next property
            if self.visible_properties:
                if self.focused_property:
                    try:
                        current_index = self.visible_properties.index(self.focused_property)
                        if pygame.key.get_pressed()[pygame.K_LSHIFT] or pygame.key.get_pressed()[pygame.K_RSHIFT]:
                            # Shift+Tab = previous
                            next_index = (current_index - 1) % len(self.visible_properties)
                        else:
                            # Tab = next
                            next_index = (current_index + 1) % len(self.visible_properties)
                        self.focused_property = self.visible_properties[next_index]
                    except ValueError:
                        self.focused_property = self.visible_properties[0]
                else:
                    self.focused_property = self.visible_properties[0]

                self._stop_all_editing()
                self.rebuild_ui()
                self._rebuild_image()
                return True

        elif event.key == pygame.K_UP:
            # Move to previous property
            if self.visible_properties and self.focused_property:
                try:
                    current_index = self.visible_properties.index(self.focused_property)
                    if current_index > 0:
                        self.focused_property = self.visible_properties[current_index - 1]
                        self._stop_all_editing()
                        self.rebuild_ui()
                        self._rebuild_image()
                        return True
                except ValueError:
                    pass

        elif event.key == pygame.K_DOWN:
            # Move to next property
            if self.visible_properties and self.focused_property:
                try:
                    current_index = self.visible_properties.index(self.focused_property)
                    if current_index < len(self.visible_properties) - 1:
                        self.focused_property = self.visible_properties[current_index + 1]
                        self._stop_all_editing()
                        self.rebuild_ui()
                        self._rebuild_image()
                        return True
                except ValueError:
                    pass

        # Forward to focused renderer if not handled
        if self.focused_property and self.focused_property in self.renderers:
            renderer = self.renderers[self.focused_property]
            if renderer.handle_event(event, (0, 0)):
                self._check_property_changed(self.focused_property)
                self._rebuild_image()
                return True

        return False

    def _handle_text_input(self, event: pygame.event.Event) -> bool:
        """Handle text input"""
        if self.focused_property and self.focused_property in self.renderers:
            renderer = self.renderers[self.focused_property]
            if renderer.handle_event(event, (0, 0)):
                self._check_property_changed(self.focused_property)
                self._rebuild_image()
                return True
        return False

    def _stop_all_editing(self):
        """Stop editing on all renderers"""
        for renderer in self.renderers.values():
            if renderer.is_editing:
                renderer.stop_editing(True)
                self._check_property_changed(renderer.property.id)

    def _check_property_changed(self, prop_id: str):
        """Check if a property value changed and fire event"""
        if prop_id in self.renderers:
            renderer = self.renderers[prop_id]
            old_value = getattr(self.target_object, prop_id, None) if self.target_object else None
            new_value = renderer.get_value()

            if old_value != new_value:
                # Update target object if available
                if self.target_object and hasattr(self.target_object, prop_id):
                    setattr(self.target_object, prop_id, new_value)

                # Fire change event
                event_data = {
                    'property': renderer.property,
                    'old_value': old_value,
                    'new_value': new_value,
                    'target_object': self.target_object,
                    'ui_element': self
                }
                pygame.event.post(pygame.event.Event(UI_PROPERTY_CHANGED, event_data))

                # Call change callback
                if self.change_callback:
                    self.change_callback(prop_id, old_value, new_value)

    def update(self, time_delta: float):
        """Update the panel"""
        super().update(time_delta)

        # Update cursor blink for text renderers
        for renderer in self.renderers.values():
            if isinstance(renderer, TextPropertyRenderer) and renderer.is_editing:
                renderer.blink_timer += time_delta
                if renderer.blink_timer > 0.5:
                    renderer.show_cursor = not renderer.show_cursor
                    renderer.blink_timer = 0
                    # Only rebuild if cursor visibility changed
                    self._rebuild_image()

    # Public API methods
    def set_property_value(self, prop_id: str, value: Any):
        """Programmatically set a property value"""
        if prop_id in self.properties:
            self.properties[prop_id].value = value
            if prop_id in self.renderers:
                self.renderers[prop_id].set_value(value)
            self._rebuild_image()

    def get_property_value(self, prop_id: str) -> Any:
        """Get a property value"""
        if prop_id in self.properties:
            return self.properties[prop_id].value
        return None

    def reset_property(self, prop_id: str):
        """Reset a property to its default value"""
        if prop_id in self.properties:
            prop = self.properties[prop_id]
            if prop.default_value is not None:
                self.set_property_value(prop_id, prop.default_value)

    def validate_all_properties(self) -> Dict[str, str]:
        """Validate all properties and return errors"""
        errors = {}
        for prop_id, prop in self.properties.items():
            is_valid, error_msg = prop.validate(prop.value)
            if not is_valid:
                errors[prop_id] = error_msg
        return errors

    def set_change_callback(self, callback: Callable[[str, Any, Any], None]):
        """Set callback for property changes"""
        self.change_callback = callback

    def expand_section(self, section_id: str):
        """Expand a section"""
        if section_id in self.sections:
            self.sections[section_id].expanded = True
            self.rebuild_ui()
            self._rebuild_image()

    def collapse_section(self, section_id: str):
        """Collapse a section"""
        if section_id in self.sections:
            self.sections[section_id].expanded = False
            self.rebuild_ui()
            self._rebuild_image()

    def show_advanced_properties(self, show: bool):
        """Show or hide advanced properties"""
        if self.config.show_advanced_properties != show:
            self.config.show_advanced_properties = show
            # Need to rebuild everything since visibility changed
            # properties = list(self.properties.values())
            properties = self._original_properties
            target = self.target_object
            self.set_properties(properties, target)

    def refresh(self):
        """Refresh the inspector display"""
        self.rebuild_ui()
        self._rebuild_image()


# Example theme for property inspector
PROPERTY_INSPECTOR_THEME = {
    "property_inspector": {
        "colours": {
            "dark_bg": "#2d2d2d",
            "normal_text": "#ffffff",
            "secondary_text": "#b4b4b4",
            "readonly_text": "#969696",
            "section_bg": "#232323",
            "section_text": "#c8c8c8",
            "control_bg": "#3c3c3c",
            "control_text": "#ffffff",
            "control_border": "#646464",
            "focused_bg": "#325078",
            "focused_border": "#78a0ff",
            "hovered_bg": "#323232",
            "selected_bg": "#4682b4",
            "error_bg": "#3c1414",
            "error_text": "#ff6464",
            "accent": "#64c864",
            "normal_border": "#505050"
        },
        "font": {
            "name": "arial",
            "size": "12",
            "bold": "0",
            "italic": "0"
        }
    }
}


def create_sample_properties() -> List[PropertySchema]:
    """Create sample properties for testing"""
    properties = [
        # Transform section
        PropertySchema(
            id="name",
            label="Name",
            property_type=PropertyType.TEXT,
            value="Sample Object",
            section="General",
            order=0,
            tooltip="The name of this object"
        ),

        PropertySchema(
            id="enabled",
            label="Enabled",
            property_type=PropertyType.BOOLEAN,
            value=True,
            section="General",
            order=1,
            tooltip="Whether this object is active"
        ),

        PropertySchema(
            id="position",
            label="Position",
            property_type=PropertyType.VECTOR3,
            value=[0.00, 0.00, 0.00],
            section="Transform",
            order=0,
            component_labels=["X", "Y", "Z"],
            tooltip="World position coordinates"
        ),

        PropertySchema(
            id="rotation",
            label="Rotation",
            property_type=PropertyType.VECTOR3,
            value=[0.00, 0.00, 0.00],
            section="Transform",
            order=1,
            component_labels=["X", "Y", "Z"],
            tooltip="Euler rotation angles in degrees"
        ),

        PropertySchema(
            id="scale",
            label="Scale",
            property_type=PropertyType.VECTOR3,
            value=[1.00, 1.00, 1.00],
            section="Transform",
            order=2,
            component_labels=["X", "Y", "Z"],
            default_value=[1, 1, 1],
            tooltip="Scale multipliers"
        ),

        # Rendering section
        PropertySchema(
            id="color",
            label="Color",
            property_type=PropertyType.COLOR,
            value=pygame.Color(255, 255, 255),
            section="Rendering",
            order=0,
            tooltip="Primary color"
        ),

        PropertySchema(
            id="opacity",
            label="Opacity",
            property_type=PropertyType.SLIDER,
            value=1.0,
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            precision=2,
            section="Rendering",
            order=1,
            tooltip="Transparency level"
        ),

        PropertySchema(
            id="material",
            label="Material",
            property_type=PropertyType.DROPDOWN,
            value="Default",
            options=["Default", "Metal", "Plastic", "Glass", "Wood"],
            section="Rendering",
            order=2,
            tooltip="Surface material type"
        ),

        # Physics section
        PropertySchema(
            id="mass",
            label="Mass",
            property_type=PropertyType.NUMBER,
            value=1.0,
            min_value=0.1,
            max_value=1000.0,
            precision=2,
            section="Physics",
            order=0,
            tooltip="Object mass in kilograms"
        ),

        PropertySchema(
            id="friction",
            label="Friction",
            property_type=PropertyType.SLIDER,
            value=0.5,
            min_value=0.0,
            max_value=2.0,
            step=0.1,
            precision=1,
            section="Physics",
            order=1,
            tooltip="Surface friction coefficient"
        ),

        PropertySchema(
            id="physics_enabled",
            label="Enable Physics",
            property_type=PropertyType.BOOLEAN,
            value=False,
            section="Physics",
            order=2,
            tooltip="Enable physics simulation"
        ),

        # Advanced section
        PropertySchema(
            id="debug_mode",
            label="Debug Mode",
            property_type=PropertyType.BOOLEAN,
            value=False,
            section="Advanced",
            flags=[PropertyFlags.ADVANCED],
            order=0,
            tooltip="Enable debug visualization"
        ),

        PropertySchema(
            id="notes",
            label="Notes",
            property_type=PropertyType.MULTILINE_TEXT,
            value="Enter notes here...",
            section="Advanced",
            flags=[PropertyFlags.ADVANCED],
            order=1,
            max_length=500,
            tooltip="Development notes"
        ),

        PropertySchema(
            id="readonly_id",
            label="Object ID",
            property_type=PropertyType.TEXT,
            value="obj_12345",
            section="Advanced",
            flags=[PropertyFlags.READONLY, PropertyFlags.ADVANCED],
            order=2,
            tooltip="Unique object identifier"
        ),
    ]

    return properties


class SampleObject:
    """Sample object for property editing"""

    def __init__(self):
        self.name = "Sample Object"
        self.enabled = True
        self.position = [0.00, 0.00, 0.00]
        self.rotation = [0.00, 0.00, 0.00]
        self.scale = [1.00, 1.00, 1.00]
        self.color = pygame.Color(255, 255, 255)
        self.opacity = 1.0
        self.material = "Default"
        self.mass = 1.0
        self.friction = 0.5
        self.physics_enabled = False
        self.debug_mode = False
        self.notes = "Enter notes here..."
        self.readonly_id = "obj_12345"


def main():
    """Example demonstration of the Property Inspector Panel"""
    pygame.init()
    screen = pygame.display.set_mode((1000, 700))
    pygame.display.set_caption("Property Inspector Panel Demo")
    clock = pygame.time.Clock()

    # Create manager with theme
    manager = pygame_gui.UIManager((1000, 700), PROPERTY_INSPECTOR_THEME)

    # Create sample object and properties
    sample_object = SampleObject()
    properties = create_sample_properties()

    # Configure property inspector
    config = PropertyConfig()
    config.show_advanced_properties = False  # Start with basic properties
    config.live_editing = True
    config.show_tooltips = True

    # Create property inspector
    property_inspector = PropertyPanel(
        pygame.Rect(50, 50, 400, 600),
        manager,
        config,
        object_id=ObjectID(object_id='#main_inspector', class_id='@property_panel')
    )

    # Set properties
    property_inspector.set_properties(properties, sample_object)

    # Set up change callback
    def on_property_changed(prop_id: str, old_value: Any, new_value: Any):
        if PROPERTY_DEBUG:
            print(f"Property changed: {prop_id} = {old_value} -> {new_value}")

    property_inspector.set_change_callback(on_property_changed)

    # Instructions
    print("\nProperty Inspector Panel Demo")
    print("\nFeatures:")
    print("- Multiple property types (text, number, boolean, dropdown, color, vector)")
    print("- Collapsible sections")
    print("- Live editing with validation")
    print("- Keyboard navigation (Tab, Arrow keys)")
    print("- Theme support")
    print("- Advanced property hiding/showing")

    print("\nControls:")
    print("- Click properties to edit")
    print("- Tab/Shift+Tab to navigate")
    print("- Arrow keys to move between properties")
    print("- Escape to cancel edits")
    print("- Right-click for context actions")
    print("- Mouse wheel to scroll")

    print("\nPress A to toggle advanced properties")
    print("Press R to reset all properties")
    print("Press S to save current values")
    print("Press L to load sample values\n")

    # State variables
    show_advanced = False

    running = True
    while running:
        time_delta = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_a:
                    # Toggle advanced properties
                    show_advanced = not show_advanced
                    property_inspector.show_advanced_properties(show_advanced)
                    print(f"Advanced properties: {'shown' if show_advanced else 'hidden'}")

                elif event.key == pygame.K_r:
                    # Reset all properties to defaults
                    for prop in properties:
                        if prop.default_value is not None:
                            property_inspector.reset_property(prop.id)
                    print("Reset all properties to defaults")

                elif event.key == pygame.K_s:
                    # Save current values (demonstrate getting values)
                    print("Current property values:")
                    for prop in properties:
                        value = property_inspector.get_property_value(prop.id)
                        print(f"  {prop.label}: {value}")

                elif event.key == pygame.K_l:
                    # Load sample values
                    property_inspector.set_property_value("name", "Loaded Object")
                    property_inspector.set_property_value("position", [10, 5, -3])
                    property_inspector.set_property_value("color", pygame.Color(255, 100, 50))
                    property_inspector.set_property_value("material", "Metal")
                    property_inspector.set_property_value("mass", 2.5)
                    print("Loaded sample values")

            # Handle property inspector events
            elif event.type == UI_PROPERTY_CHANGED:
                if PROPERTY_DEBUG:
                    print(f"Property changed event: {event.property.label} = {event.new_value}")

            elif event.type == UI_PROPERTY_SECTION_TOGGLED:
                if PROPERTY_DEBUG:
                    print(f"Section {'expanded' if event.expanded else 'collapsed'}: {event.section.label}")

            elif event.type == UI_PROPERTY_RESET_REQUESTED:
                # Handle right-click context action
                prop = event.property
                if prop.default_value is not None:
                    property_inspector.reset_property(prop.id)
                    print(f"Reset {prop.label} to default value")
                else:
                    print(f"No default value for {prop.label}")

            elif event.type == UI_PROPERTY_VALIDATION_FAILED:
                print(f"Validation failed for {event.property.label}: {event.error_message}")

            # Forward events to manager
            manager.process_events(event)

        # Update
        manager.update(time_delta)

        # Draw
        screen.fill((25, 25, 25))

        # Draw some info text
        font = pygame.font.Font(None, 24)
        info_text = font.render("Property Inspector Demo", True, pygame.Color(255, 255, 255))
        screen.blit(info_text, (500, 50))

        # Draw current object state
        y_offset = 100
        info_font = pygame.font.Font(None, 18)

        # Show ALL properties instead of just key ones
        all_properties = property_inspector.properties
        for prop_id, prop_schema in all_properties.items():
            value = property_inspector.get_property_value(prop_id)
            if value is not None:
                # Format the value for display
                if isinstance(value, list):
                    if all(isinstance(v, (int, float)) for v in value):
                        value_str = f"[{', '.join(f'{v:.2f}' if isinstance(v, float) else str(v) for v in value)}]"
                    else:
                        value_str = f"[{', '.join(str(v) for v in value)}]"
                elif isinstance(value, float):
                    value_str = f"{value:.3f}"
                elif isinstance(value, pygame.Color):
                    if value.a < 255:
                        value_str = f"RGBA({value.r}, {value.g}, {value.b}, {value.a})"
                    else:
                        value_str = f"RGB({value.r}, {value.g}, {value.b})"
                elif isinstance(value, bool):
                    value_str = "True" if value else "False"
                else:
                    value_str = str(value)

                # Show property label and value
                display_text = f"{prop_schema.label}: {value_str}"

                # Add section info for better organization
                section_name = prop_schema.section or "General"
                if prop_schema.is_advanced():
                    display_text += " (Advanced)"
                if prop_schema.is_readonly():
                    display_text += " (Read-only)"

                # Color code by section
                text_color = pygame.Color(200, 200, 200)  # Default
                if section_name == "Transform":
                    text_color = pygame.Color(150, 255, 150)  # Green
                elif section_name == "Rendering":
                    text_color = pygame.Color(255, 200, 150)  # Orange
                elif section_name == "Physics":
                    text_color = pygame.Color(150, 200, 255)  # Blue
                elif section_name == "Advanced":
                    text_color = pygame.Color(255, 150, 255)  # Magenta

                # Dim readonly properties
                if prop_schema.is_readonly():
                    text_color = pygame.Color(text_color.r // 2, text_color.g // 2, text_color.b // 2)

                text = info_font.render(display_text, True, text_color)
                screen.blit(text, (500, y_offset))
                y_offset += 22

        # Add section headers for better organization
        section_offsets = {}
        current_y = 100
        sections_order = ["General", "Transform", "Rendering", "Physics", "Advanced"]

        # Draw section-organized view on the right side
        section_x = 750
        section_y = 100
        section_font = pygame.font.Font(None, 20)
        property_font = pygame.font.Font(None, 16)

        for section_name in sections_order:
            # Check if we have properties in this section
            section_props = [prop for prop in all_properties.values() if (prop.section or "General") == section_name]
            if not section_props:
                continue

            # Draw section header
            section_color = pygame.Color(255, 255, 255)
            section_text = section_font.render(f"=== {section_name} ===", True, section_color)
            screen.blit(section_text, (section_x, section_y))
            section_y += 25

            # Draw properties in this section
            for prop in sorted(section_props, key=lambda p: p.order):
                if prop.is_hidden() or (prop.is_advanced() and not show_advanced):
                    continue

                value = property_inspector.get_property_value(prop.id)
                if value is not None:
                    # Format value
                    if isinstance(value, list):
                        if all(isinstance(v, (int, float)) for v in value):
                            value_str = f"[{', '.join(f'{v:.2f}' if isinstance(v, float) else str(v) for v in value)}]"
                        else:
                            value_str = f"[{', '.join(str(v) for v in value)}]"
                    elif isinstance(value, float):
                        value_str = f"{value:.3f}"
                    elif isinstance(value, pygame.Color):
                        value_str = f"#{value.r:02x}{value.g:02x}{value.b:02x}"
                        if value.a < 255:
                            value_str += f"{value.a:02x}"
                    elif isinstance(value, bool):
                        value_str = "Yes" if value else "No"
                    else:
                        value_str = str(value)[:30]  # Truncate long strings

                    display_text = f"  {prop.label}: {value_str}"

                    # Color based on property state
                    prop_color = pygame.Color(180, 180, 180)
                    if prop.is_readonly():
                        prop_color = pygame.Color(120, 120, 120)
                    elif prop.is_advanced():
                        prop_color = pygame.Color(200, 150, 200)

                    prop_text = property_font.render(display_text, True, prop_color)
                    screen.blit(prop_text, (section_x, section_y))
                    section_y += 18

            section_y += 10  # Extra space between sections

        # Draw validation status
        errors = property_inspector.validate_all_properties()
        if errors:
            error_text = info_font.render(f"Validation errors: {len(errors)}", True, pygame.Color(255, 100, 100))
            screen.blit(error_text, (500, y_offset + 20))
            for prop_id, error in errors.items():
                error_detail = info_font.render(f"  {prop_id}: {error}", True, pygame.Color(255, 150, 150))
                screen.blit(error_detail, (500, y_offset + 45))
                y_offset += 25
        else:
            valid_text = info_font.render("All properties valid", True, pygame.Color(100, 255, 100))
            screen.blit(valid_text, (500, y_offset + 20))

        manager.draw_ui(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()