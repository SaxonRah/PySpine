import pygame
import pygame_gui
from pygame_gui.core import UIElement, ObjectID
from pygame_gui.core.interfaces import IContainerLikeInterface
from typing import List, Optional, Dict, Any, Union, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import math
import time as time_module

try:
    from pygame_gui.core.interfaces.gui_font_interface import IGUIFontInterface
except ImportError:
    IGUIFontInterface = None

TIMELINE_DEBUG = False

# Constants
FRAME_HEIGHT = 20
LAYER_HEIGHT = 40
SCRUBBER_HEIGHT = 30
CONTROLS_HEIGHT = 35
KEYFRAME_SIZE = 8
PLAYHEAD_WIDTH = 2
ZOOM_SENSITIVITY = 0.1
MIN_ZOOM = 0.1
MAX_ZOOM = 10.0
DEFAULT_FPS = 30
MIN_FPS = 1
MAX_FPS = 120

# Define custom pygame-gui events
UI_TIMELINE_FRAME_CHANGED = pygame.USEREVENT + 100
UI_TIMELINE_KEYFRAME_ADDED = pygame.USEREVENT + 101
UI_TIMELINE_KEYFRAME_REMOVED = pygame.USEREVENT + 102
UI_TIMELINE_KEYFRAME_MOVED = pygame.USEREVENT + 103
UI_TIMELINE_KEYFRAME_SELECTED = pygame.USEREVENT + 104
UI_TIMELINE_LAYER_VISIBILITY_CHANGED = pygame.USEREVENT + 105
UI_TIMELINE_LAYER_LOCK_CHANGED = pygame.USEREVENT + 106
UI_TIMELINE_PLAYBACK_STARTED = pygame.USEREVENT + 107
UI_TIMELINE_PLAYBACK_STOPPED = pygame.USEREVENT + 108
UI_TIMELINE_PLAYBACK_PAUSED = pygame.USEREVENT + 109
UI_TIMELINE_ZOOM_CHANGED = pygame.USEREVENT + 110
UI_TIMELINE_SELECTION_CHANGED = pygame.USEREVENT + 111


class InterpolationType(Enum):
    """Animation interpolation types"""
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    STEP = "step"
    BEZIER = "bezier"
    SMOOTH = "smooth"


class LayerType(Enum):
    """Animation layer types"""
    TRANSFORM = "transform"
    PROPERTY = "property"
    EVENT = "event"
    SOUND = "sound"
    CUSTOM = "custom"


class PlaybackState(Enum):
    """Timeline playback states"""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    SCRUBBING = "scrubbing"


class KeyframeFlags(Enum):
    """Keyframe behavior flags"""
    LOCKED = "locked"
    SELECTED = "selected"
    TANGENT_BROKEN = "tangent_broken"
    AUTO_TANGENT = "auto_tangent"


@dataclass
class Keyframe:
    """Individual keyframe in an animation"""
    frame: int
    value: Any
    interpolation: InterpolationType = InterpolationType.LINEAR
    flags: List[KeyframeFlags] = field(default_factory=list)

    # Bezier curve control points (relative to keyframe position)
    in_tangent: Tuple[float, float] = (0.0, 0.0)
    out_tangent: Tuple[float, float] = (0.0, 0.0)

    # Custom data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_locked(self) -> bool:
        return KeyframeFlags.LOCKED in self.flags

    def is_selected(self) -> bool:
        return KeyframeFlags.SELECTED in self.flags

    def set_selected(self, selected: bool):
        if selected and KeyframeFlags.SELECTED not in self.flags:
            self.flags.append(KeyframeFlags.SELECTED)
        elif not selected and KeyframeFlags.SELECTED in self.flags:
            self.flags.remove(KeyframeFlags.SELECTED)


@dataclass
class AnimationCurve:
    """Animation curve containing keyframes for a specific property"""
    property_name: str
    keyframes: List[Keyframe] = field(default_factory=list)
    default_value: Any = None
    enabled: bool = True

    def add_keyframe(self, keyframe: Keyframe):
        """Add keyframe maintaining frame order"""
        # Remove existing keyframe at same frame
        self.keyframes = [kf for kf in self.keyframes if kf.frame != keyframe.frame]

        # Insert in correct position
        inserted = False
        for i, kf in enumerate(self.keyframes):
            if kf.frame > keyframe.frame:
                self.keyframes.insert(i, keyframe)
                inserted = True
                break

        if not inserted:
            self.keyframes.append(keyframe)

    def remove_keyframe(self, frame: int) -> bool:
        """Remove keyframe at specified frame"""
        original_count = len(self.keyframes)
        self.keyframes = [kf for kf in self.keyframes if kf.frame != frame]
        return len(self.keyframes) < original_count

    def get_keyframe(self, frame: int) -> Optional[Keyframe]:
        """Get keyframe at specific frame"""
        for kf in self.keyframes:
            if kf.frame == frame:
                return kf
        return None

    def get_value_at_frame(self, frame: float) -> Any:
        """Interpolate value at given frame"""
        if not self.keyframes:
            return self.default_value

        # Find surrounding keyframes
        before_kf = None
        after_kf = None

        for kf in self.keyframes:
            if kf.frame <= frame:
                before_kf = kf
            elif kf.frame > frame and after_kf is None:
                after_kf = kf
                break

        # No keyframes or only one
        if before_kf is None:
            return after_kf.value if after_kf else self.default_value
        if after_kf is None:
            return before_kf.value

        # Same frame
        if before_kf.frame == after_kf.frame:
            return before_kf.value

        # Interpolate between keyframes
        return self._interpolate(before_kf, after_kf, frame)

    def _interpolate(self, kf1: Keyframe, kf2: Keyframe, frame: float) -> Any:
        """Interpolate between two keyframes"""
        if kf1.frame == kf2.frame:
            return kf1.value

        t = (frame - kf1.frame) / (kf2.frame - kf1.frame)
        t = max(0.0, min(1.0, t))

        # Handle different value types
        if isinstance(kf1.value, (int, float)) and isinstance(kf2.value, (int, float)):
            return self._interpolate_numeric(kf1, kf2, t)
        elif isinstance(kf1.value, (list, tuple)) and isinstance(kf2.value, (list, tuple)):
            return self._interpolate_vector(kf1, kf2, t)
        elif isinstance(kf1.value, pygame.Color) and isinstance(kf2.value, pygame.Color):
            return self._interpolate_color(kf1, kf2, t)
        else:
            # Default to step interpolation for unsupported types
            return kf1.value if t < 0.5 else kf2.value

    @staticmethod
    def _interpolate_numeric(kf1: Keyframe, kf2: Keyframe, t: float) -> float:
        """Interpolate numeric values"""
        if kf1.interpolation == InterpolationType.STEP:
            return kf1.value
        elif kf1.interpolation == InterpolationType.LINEAR:
            return kf1.value + (kf2.value - kf1.value) * t
        elif kf1.interpolation == InterpolationType.EASE_IN:
            t = t * t
            return kf1.value + (kf2.value - kf1.value) * t
        elif kf1.interpolation == InterpolationType.EASE_OUT:
            t = 1 - (1 - t) * (1 - t)
            return kf1.value + (kf2.value - kf1.value) * t
        elif kf1.interpolation == InterpolationType.EASE_IN_OUT:
            t = 0.5 * (1 - math.cos(math.pi * t))
            return kf1.value + (kf2.value - kf1.value) * t
        elif kf1.interpolation == InterpolationType.SMOOTH:
            t = t * t * (3 - 2 * t)  # Smoothstep
            return kf1.value + (kf2.value - kf1.value) * t
        else:
            return kf1.value + (kf2.value - kf1.value) * t

    def _interpolate_vector(self, kf1: Keyframe, kf2: Keyframe, t: float) -> List[float]:
        """Interpolate vector values"""
        if kf1.interpolation == InterpolationType.STEP:
            return list(kf1.value)

        result = []
        for i in range(min(len(kf1.value), len(kf2.value))):
            if isinstance(kf1.value[i], (int, float)) and isinstance(kf2.value[i], (int, float)):
                # Create temporary keyframes for numeric interpolation
                temp_kf1 = Keyframe(kf1.frame, kf1.value[i], kf1.interpolation)
                temp_kf2 = Keyframe(kf2.frame, kf2.value[i], kf1.interpolation)
                result.append(self._interpolate_numeric(temp_kf1, temp_kf2, t))
            else:
                result.append(kf1.value[i] if t < 0.5 else kf2.value[i])
        return result

    @staticmethod
    def _interpolate_color(kf1: Keyframe, kf2: Keyframe, t: float) -> pygame.Color:
        """Interpolate color values"""
        if kf1.interpolation == InterpolationType.STEP:
            return pygame.Color(kf1.value)

        r = int(kf1.value.r + (kf2.value.r - kf1.value.r) * t)
        g = int(kf1.value.g + (kf2.value.g - kf1.value.g) * t)
        b = int(kf1.value.b + (kf2.value.b - kf1.value.b) * t)
        a = int(kf1.value.a + (kf2.value.a - kf1.value.a) * t)

        return pygame.Color(max(0, min(255, r)), max(0, min(255, g)),
                            max(0, min(255, b)), max(0, min(255, a)))


@dataclass
class AnimationLayer:
    """Layer containing multiple animation curves"""
    id: str
    name: str
    layer_type: LayerType = LayerType.PROPERTY
    curves: List[AnimationCurve] = field(default_factory=list)

    # Layer properties
    visible: bool = True
    locked: bool = False
    muted: bool = False
    solo: bool = False

    # Visual properties
    color: pygame.Color = field(default_factory=lambda: pygame.Color(150, 150, 150))
    height: int = LAYER_HEIGHT

    # Target object reference (optional)
    target_object: Any = None
    target_property_path: Optional[str] = None

    # Custom data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_curve(self, curve: AnimationCurve):
        """Add animation curve to layer"""
        # Remove existing curve with same property name
        self.curves = [c for c in self.curves if c.property_name != curve.property_name]
        self.curves.append(curve)

    def remove_curve(self, property_name: str) -> bool:
        """Remove animation curve by property name"""
        original_count = len(self.curves)
        self.curves = [c for c in self.curves if c.property_name != property_name]
        return len(self.curves) < original_count

    def get_curve(self, property_name: str) -> Optional[AnimationCurve]:
        """Get animation curve by property name"""
        for curve in self.curves:
            if curve.property_name == property_name:
                return curve
        return None

    def get_all_keyframes(self) -> List[Tuple[AnimationCurve, Keyframe]]:
        """Get all keyframes from all curves"""
        keyframes = []
        for curve in self.curves:
            for kf in curve.keyframes:
                keyframes.append((curve, kf))
        return sorted(keyframes, key=lambda x: x[1].frame)

    def get_keyframes_at_frame(self, frame: int) -> List[Tuple[AnimationCurve, Keyframe]]:
        """Get all keyframes at specific frame"""
        keyframes = []
        for curve in self.curves:
            kf = curve.get_keyframe(frame)
            if kf:
                keyframes.append((curve, kf))
        return keyframes


@dataclass
class AnimationClip:
    """Animation clip containing layers and global settings"""
    name: str
    layers: List[AnimationLayer] = field(default_factory=list)

    # Timeline settings
    length: int = 300  # frames
    fps: float = DEFAULT_FPS
    start_frame: int = 0

    # Playback settings
    loop: bool = False
    ping_pong: bool = False

    # Custom data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_layer(self, layer: AnimationLayer):
        """Add animation layer"""
        self.layers.append(layer)

    def remove_layer(self, layer_id: str) -> bool:
        """Remove layer by ID"""
        original_count = len(self.layers)
        self.layers = [layer for layer in self.layers if layer.id != layer_id]
        return len(self.layers) < original_count

    def get_layer(self, layer_id: str) -> Optional[AnimationLayer]:
        """Get layer by ID"""
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        return None

    def get_duration_seconds(self) -> float:
        """Get clip duration in seconds"""
        return self.length / self.fps if self.fps > 0 else 0.0

    def frame_to_time(self, frame: float) -> float:
        """Convert frame to time in seconds"""
        return frame / self.fps if self.fps > 0 else 0.0

    def time_to_frame(self, time_seconds: float) -> float:
        """Convert time to frame"""
        return time_seconds * self.fps


@dataclass
class TimelineConfig:
    """Configuration for the timeline panel"""
    # Display settings
    frame_height: int = FRAME_HEIGHT
    layer_height: int = LAYER_HEIGHT
    scrubber_height: int = SCRUBBER_HEIGHT
    controls_height: int = CONTROLS_HEIGHT

    # Timeline settings
    show_frame_numbers: bool = True
    show_time_code: bool = True
    major_tick_interval: int = 10
    minor_tick_interval: int = 5

    # Keyframe settings
    keyframe_size: int = KEYFRAME_SIZE
    keyframe_shape: str = "diamond"  # diamond, circle, square
    show_interpolation_curves: bool = False

    # Behavior
    snap_to_frames: bool = True
    auto_scroll_on_playback: bool = True
    zoom_to_fit_on_clip_change: bool = True

    # Playback
    default_fps: float = DEFAULT_FPS
    loop_by_default: bool = False

    # Integration
    sync_with_property_panel: bool = True
    sync_with_hierarchy_panel: bool = True


class TimelineRenderer:
    """Handles rendering of timeline elements"""

    def __init__(self, config: TimelineConfig):
        self.config = config

    @staticmethod
    def draw_timeline_background(surface: pygame.Surface, rect: pygame.Rect,
                                 colors: Dict[str, pygame.Color]):
        """Draw timeline background with grid"""
        bg_color = colors.get('timeline_bg', pygame.Color(40, 40, 40))
        surface.fill(bg_color)

        # Draw frame grid (simplified for this implementation)
        grid_color = colors.get('grid_line', pygame.Color(60, 60, 60))

        # Vertical lines for frames (every 10 frames)
        for i in range(0, rect.width, 50):  # Simplified spacing
            pygame.draw.line(surface, grid_color, (i, 0), (i, rect.height))

    def draw_keyframe(self, surface: pygame.Surface, pos: Tuple[int, int],
                      keyframe: Keyframe, colors: Dict[str, pygame.Color]):
        """Draw a keyframe at specified position"""
        # Defaults
        size = self.config.keyframe_size
        x, y = pos
        points = []
        rect = pygame.Rect(x - size // 2, y - size // 2, size, size)

        # Choose color based on keyframe state
        if keyframe.is_selected():
            color = colors.get('keyframe_selected', pygame.Color(255, 255, 100))
        elif keyframe.is_locked():
            color = colors.get('keyframe_locked', pygame.Color(150, 150, 150))
        else:
            # Color by interpolation type
            color_map = {
                InterpolationType.LINEAR: colors.get('keyframe_linear', pygame.Color(100, 150, 255)),
                InterpolationType.EASE_IN: colors.get('keyframe_ease_in', pygame.Color(100, 255, 100)),
                InterpolationType.EASE_OUT: colors.get('keyframe_ease_out', pygame.Color(255, 100, 100)),
                InterpolationType.EASE_IN_OUT: colors.get('keyframe_ease_in_out', pygame.Color(255, 150, 100)),
                InterpolationType.STEP: colors.get('keyframe_step', pygame.Color(200, 200, 200)),
                InterpolationType.BEZIER: colors.get('keyframe_bezier', pygame.Color(255, 100, 255)),
                InterpolationType.SMOOTH: colors.get('keyframe_smooth', pygame.Color(100, 255, 255)),
            }
            color = color_map.get(keyframe.interpolation, pygame.Color(150, 150, 150))

        # Draw keyframe shape
        if self.config.keyframe_shape == "diamond":
            points = [
                (x, y - size // 2),
                (x + size // 2, y),
                (x, y + size // 2),
                (x - size // 2, y)
            ]
            pygame.draw.polygon(surface, color, points)
        elif self.config.keyframe_shape == "circle":
            pygame.draw.circle(surface, color, (x, y), size // 2)
        else:  # square
            rect = pygame.Rect(x - size // 2, y - size // 2, size, size)
            pygame.draw.rect(surface, color, rect)

        # Draw outline
        outline_color = colors.get('keyframe_outline', pygame.Color(0, 0, 0))
        if self.config.keyframe_shape == "diamond":
            pygame.draw.polygon(surface, outline_color, points, 1)
        elif self.config.keyframe_shape == "circle":
            pygame.draw.circle(surface, outline_color, (x, y), size // 2, 1)
        else:
            pygame.draw.rect(surface, outline_color, rect, 1)

    @staticmethod
    def draw_playhead(surface: pygame.Surface, x: int, rect: pygame.Rect,
                      colors: Dict[str, pygame.Color]):
        """Draw playhead at specified x position"""
        playhead_color = colors.get('playhead', pygame.Color(255, 0, 0))
        pygame.draw.line(surface, playhead_color, (x, rect.top), (x, rect.bottom), PLAYHEAD_WIDTH)

        # Draw playhead handle
        handle_size = 8
        handle_rect = pygame.Rect(x - handle_size // 2, rect.top, handle_size, handle_size)
        pygame.draw.rect(surface, playhead_color, handle_rect)


class TimelinePanel(UIElement):
    """Main timeline/animation panel widget"""

    def __init__(self, relative_rect: pygame.Rect,
                 manager: pygame_gui.UIManager,
                 config: TimelineConfig = None,
                 container: IContainerLikeInterface = None,
                 object_id: Union[ObjectID, str, None] = None,
                 anchors: Dict[str, str] = None):

        # Handle object_id properly
        if isinstance(object_id, ObjectID):
            self._object_id = object_id
        elif isinstance(object_id, str):
            self._object_id = ObjectID(object_id=object_id, class_id=None)
        else:
            self._object_id = ObjectID(object_id='#timeline_panel', class_id=None)

        super().__init__(relative_rect, manager, container,
                         starting_height=1, layer_thickness=1,
                         anchors=anchors, object_id=self._object_id)

        self.config = config or TimelineConfig()

        # Animation data
        self.clip: Optional[AnimationClip] = None
        self.current_frame: float = 0.0
        self.playback_state = PlaybackState.STOPPED
        self.selection: List[Tuple[str, str, int]] = []  # [(layer_id, curve_name, frame)]

        # Playback timing
        self.last_playback_time = 0.0
        self.playback_start_frame = 0.0

        # View settings
        self.zoom = 1.0
        self.scroll_x = 0.0
        self.scroll_y = 0.0

        # UI state
        self.is_scrubbing = False
        self.is_dragging_keyframe = False
        self.drag_start_pos = (0, 0)
        self.drag_start_frame = 0.0
        self.hovered_keyframe: Optional[Tuple[str, str, int]] = None
        self.focused_layer: Optional[str] = None

        # Layout rects
        self.controls_rect = pygame.Rect(0, 0, 0, 0)
        self.scrubber_rect = pygame.Rect(0, 0, 0, 0)
        self.timeline_rect = pygame.Rect(0, 0, 0, 0)
        self.layers_rect = pygame.Rect(0, 0, 0, 0)

        # Renderer
        self.renderer = TimelineRenderer(self.config)

        # Integration callbacks
        self.frame_change_callback: Optional[Callable[[float], None]] = None
        self.keyframe_change_callback: Optional[Callable[[str, str, int, Any], None]] = None

        # Theme data
        self._update_theme_data()

        # Create the image surface
        self.image = pygame.Surface(self.rect.size).convert()

        # Initialize
        self._setup_layout()
        self._rebuild_image()

    def _needs_rebuild(self) -> bool:
        """Check if UI needs rebuilding"""
        if not hasattr(self, '_last_rebuild_state'):
            self._last_rebuild_state = None
            return True

        current_state = {
            'current_frame': self.current_frame,
            'zoom': self.zoom,
            'scroll_x': self.scroll_x,
            'scroll_y': self.scroll_y,
            'playback_state': self.playback_state,
            'clip_id': id(self.clip) if self.clip else None,
            'selection_count': len(self.selection)
        }

        if current_state != self._last_rebuild_state:
            self._last_rebuild_state = current_state
            return True

        return False

    def _update_theme_data(self):
        """Update theme-dependent data"""
        self.themed_colors = {}

        color_mappings = {
            'timeline_bg': pygame.Color(40, 40, 40),
            'controls_bg': pygame.Color(35, 35, 35),
            'scrubber_bg': pygame.Color(45, 45, 45),
            'layer_bg': pygame.Color(50, 50, 50),
            'layer_bg_alt': pygame.Color(45, 45, 45),
            'normal_text': pygame.Color(255, 255, 255),
            'disabled_text': pygame.Color(150, 150, 150),
            'grid_line': pygame.Color(60, 60, 60),
            'major_tick': pygame.Color(200, 200, 200),
            'minor_tick': pygame.Color(150, 150, 150),
            'playhead': pygame.Color(255, 80, 80),
            'selection': pygame.Color(100, 150, 255),
            'keyframe_linear': pygame.Color(100, 150, 255),
            'keyframe_ease_in': pygame.Color(100, 255, 100),
            'keyframe_ease_out': pygame.Color(255, 100, 100),
            'keyframe_ease_in_out': pygame.Color(255, 150, 100),
            'keyframe_step': pygame.Color(200, 200, 200),
            'keyframe_bezier': pygame.Color(255, 100, 255),
            'keyframe_smooth': pygame.Color(100, 255, 255),
            'keyframe_selected': pygame.Color(255, 255, 100),
            'keyframe_locked': pygame.Color(120, 120, 120),
            'keyframe_outline': pygame.Color(20, 20, 20),
            'button_bg': pygame.Color(60, 60, 60),
            'button_hover': pygame.Color(80, 80, 80),
            'button_pressed': pygame.Color(40, 40, 40),
            'border': pygame.Color(100, 100, 100),
            'focus_border': pygame.Color(120, 160, 255),
        }

        try:
            theme = self.ui_manager.get_theme()

            for color_id, default_color in color_mappings.items():
                try:
                    if hasattr(theme, 'get_colour_or_gradient'):
                        color = theme.get_colour_or_gradient(color_id, ['timeline_panel'])
                        self.themed_colors[color_id] = color if color else default_color
                    else:
                        self.themed_colors[color_id] = default_color
                except Exception:
                    self.themed_colors[color_id] = default_color

            # Get themed font
            try:
                if hasattr(theme, 'get_font'):
                    self.themed_font = theme.get_font(['timeline_panel'])
                else:
                    raise Exception("No font method")
            except Exception:
                try:
                    self.themed_font = pygame.font.SysFont('Arial', 10)
                except:
                    self.themed_font = pygame.font.Font(None, 10)

        except Exception as e:
            if TIMELINE_DEBUG:
                print(f"Error getting theme data: {e}")
            # Complete fallback
            self.themed_colors = color_mappings
            try:
                self.themed_font = pygame.font.SysFont('Arial', 10)
            except:
                self.themed_font = pygame.font.Font(None, 10)

    def rebuild_from_changed_theme_data(self):
        """Called when theme data changes"""
        self._update_theme_data()
        self._rebuild_image()

    def _setup_layout(self):
        """Setup layout rectangles"""
        self.controls_rect = pygame.Rect(
            0, 0, self.rect.width, self.config.controls_height
        )

        self.scrubber_rect = pygame.Rect(
            0, self.config.controls_height,
            self.rect.width, self.config.scrubber_height
        )

        self.timeline_rect = pygame.Rect(
            0, self.config.controls_height + self.config.scrubber_height,
            self.rect.width,
               self.rect.height - self.config.controls_height - self.config.scrubber_height
        )

        # Layers area within timeline
        self.layers_rect = self.timeline_rect.copy()

    def _rebuild_image(self):
        """Rebuild the image surface"""
        if not self._needs_rebuild():
            return

        # Fill background
        bg_color = self.themed_colors.get('timeline_bg', pygame.Color(40, 40, 40))
        self.image.fill(bg_color)

        # Draw components
        self._draw_controls()
        self._draw_scrubber()
        self._draw_timeline()

        # Draw border
        border_color = self.themed_colors.get('border', pygame.Color(100, 100, 100))
        pygame.draw.rect(self.image, border_color, self.image.get_rect(), 1)

    def _draw_controls(self):
        """Draw playback controls"""
        if self.controls_rect.height <= 0:
            return

        try:
            controls_surface = self.image.subsurface(self.controls_rect)
        except (ValueError, pygame.error):
            return

        # Background
        bg_color = self.themed_colors.get('controls_bg', pygame.Color(35, 35, 35))
        controls_surface.fill(bg_color)

        # Draw playback buttons (simplified)
        button_size = min(24, self.controls_rect.height - 6)
        button_y = (self.controls_rect.height - button_size) // 2
        button_spacing = button_size + 4

        buttons = [
            ("<<", self._rewind_to_start),
            ("|<", self._step_backward),
            (">" if self.playback_state != PlaybackState.PLAYING else "||", self._toggle_playback),
            (">|", self._step_forward),
            (">>", self._fast_forward_to_end),
        ]

        button_x = 10
        for button_text, button_action in buttons:
            button_rect = pygame.Rect(button_x, button_y, button_size, button_size)

            # Button background
            button_color = self.themed_colors.get('button_bg', pygame.Color(60, 60, 60))
            pygame.draw.rect(controls_surface, button_color, button_rect)

            # Button border
            border_color = self.themed_colors.get('border', pygame.Color(100, 100, 100))
            pygame.draw.rect(controls_surface, border_color, button_rect, 1)

            # Button text
            try:
                text_color = self.themed_colors.get('normal_text', pygame.Color(255, 255, 255))
                if hasattr(self.themed_font, 'render_premul'):
                    text_surface = self.themed_font.render_premul(button_text, text_color)
                else:
                    text_surface = self.themed_font.render(button_text, True, text_color)

                text_rect = text_surface.get_rect(center=button_rect.center)
                controls_surface.blit(text_surface, text_rect)
            except Exception:
                pass

            button_x += button_spacing

        # Draw frame/time display
        display_x = button_x + 20
        frame_text = f"Frame: {int(self.current_frame)}"
        if self.clip:
            time_text = f"Time: {self.clip.frame_to_time(self.current_frame):.2f}s"
            fps_text = f"FPS: {self.clip.fps:.1f}"
        else:
            time_text = "Time: 0.00s"
            fps_text = f"FPS: {self.config.default_fps:.1f}"

        try:
            text_color = self.themed_colors.get('normal_text', pygame.Color(255, 255, 255))

            if hasattr(self.themed_font, 'render_premul'):
                frame_surface = self.themed_font.render_premul(frame_text, text_color)
                time_surface = self.themed_font.render_premul(time_text, text_color)
                fps_surface = self.themed_font.render_premul(fps_text, text_color)
            else:
                frame_surface = self.themed_font.render(frame_text, True, text_color)
                time_surface = self.themed_font.render(time_text, True, text_color)
                fps_surface = self.themed_font.render(fps_text, True, text_color)

            text_y = (self.controls_rect.height - frame_surface.get_height()) // 2
            controls_surface.blit(frame_surface, (display_x, text_y))
            controls_surface.blit(time_surface, (display_x + 100, text_y))
            controls_surface.blit(fps_surface, (display_x + 200, text_y))

        except Exception:
            pass

    def _draw_scrubber(self):
        """Draw timeline scrubber with frame markers"""
        if self.scrubber_rect.height <= 0:
            return

        try:
            scrubber_surface = self.image.subsurface(self.scrubber_rect)
        except (ValueError, pygame.error):
            return

        # Background
        bg_color = self.themed_colors.get('scrubber_bg', pygame.Color(45, 45, 45))
        scrubber_surface.fill(bg_color)

        if not self.clip:
            return

        # Calculate frame positions
        frames_per_pixel = 1.0 / self.zoom
        start_frame = self.scroll_x * frames_per_pixel
        end_frame = start_frame + self.scrubber_rect.width * frames_per_pixel

        # Draw frame markers
        major_color = self.themed_colors.get('major_tick', pygame.Color(200, 200, 200))
        minor_color = self.themed_colors.get('minor_tick', pygame.Color(150, 150, 150))

        for frame in range(int(start_frame), int(end_frame) + 1):
            if frame < 0 or frame > self.clip.length:
                continue

            x = int((frame - start_frame) / frames_per_pixel)
            if x < 0 or x >= self.scrubber_rect.width:
                continue

            # Major or minor tick
            if frame % self.config.major_tick_interval == 0:
                color = major_color
                height = self.scrubber_rect.height // 2
                # Draw frame number
                if self.config.show_frame_numbers:
                    try:
                        text_color = self.themed_colors.get('normal_text', pygame.Color(255, 255, 255))
                        if hasattr(self.themed_font, 'render_premul'):
                            text_surface = self.themed_font.render_premul(str(frame), text_color)
                        else:
                            text_surface = self.themed_font.render(str(frame), True, text_color)

                        text_rect = text_surface.get_rect()
                        text_rect.centerx = x
                        text_rect.bottom = self.scrubber_rect.height - 2

                        if text_rect.left >= 0 and text_rect.right < self.scrubber_rect.width:
                            scrubber_surface.blit(text_surface, text_rect)
                    except Exception:
                        pass
            elif frame % self.config.minor_tick_interval == 0:
                color = minor_color
                height = self.scrubber_rect.height // 3
            else:
                continue

            pygame.draw.line(scrubber_surface, color, (x, 0), (x, height))

        # Draw playhead in scrubber
        playhead_x = int((self.current_frame - start_frame) / frames_per_pixel)
        if 0 <= playhead_x < self.scrubber_rect.width:
            self.renderer.draw_playhead(scrubber_surface, playhead_x,
                                        pygame.Rect(0, 0, self.scrubber_rect.width, self.scrubber_rect.height),
                                        self.themed_colors)

    def _draw_timeline(self):
        """Draw timeline with layers and keyframes"""
        if self.timeline_rect.height <= 0 or not self.clip:
            return

        try:
            timeline_surface = self.image.subsurface(self.timeline_rect)
        except (ValueError, pygame.error):
            return

        # Draw timeline background with grid
        self.renderer.draw_timeline_background(timeline_surface, self.timeline_rect, self.themed_colors)

        # Calculate visible area
        frames_per_pixel = 1.0 / self.zoom
        start_frame = self.scroll_x * frames_per_pixel
        end_frame = start_frame + self.timeline_rect.width * frames_per_pixel

        # Draw layers
        layer_y = -self.scroll_y
        for i, layer in enumerate(self.clip.layers):
            if layer_y + layer.height < 0:
                layer_y += layer.height
                continue
            if layer_y > self.timeline_rect.height:
                break

            # Layer background
            layer_rect = pygame.Rect(0, int(layer_y), self.timeline_rect.width, layer.height)
            if layer_rect.bottom > 0 and layer_rect.top < self.timeline_rect.height:
                bg_color = self.themed_colors.get('layer_bg_alt' if i % 2 else 'layer_bg',
                                                  pygame.Color(50, 50, 50))
                clipped_rect = layer_rect.clip(pygame.Rect(0, 0, self.timeline_rect.width, self.timeline_rect.height))
                if clipped_rect.width > 0 and clipped_rect.height > 0:
                    try:
                        layer_surface = timeline_surface.subsurface(clipped_rect)
                        layer_surface.fill(bg_color)
                    except (ValueError, pygame.error):
                        pass

                # Layer name
                if layer_rect.height > 15:  # Only draw text if layer is tall enough
                    try:
                        text_color = self.themed_colors.get('disabled_text' if not layer.visible else 'normal_text',
                                                            pygame.Color(255, 255, 255))
                        if hasattr(self.themed_font, 'render_premul'):
                            text_surface = self.themed_font.render_premul(layer.name, text_color)
                        else:
                            text_surface = self.themed_font.render(layer.name, True, text_color)

                        text_rect = text_surface.get_rect()
                        text_rect.left = 5
                        text_rect.centery = layer_y + layer.height // 2

                        if text_rect.bottom <= self.timeline_rect.height and text_rect.top >= 0:
                            timeline_surface.blit(text_surface, text_rect)
                    except Exception:
                        pass

                # Draw keyframes for this layer
                self._draw_layer_keyframes(timeline_surface, layer, layer_y, start_frame, end_frame, frames_per_pixel)

            layer_y += layer.height

        # Draw playhead in timeline
        playhead_x = int((self.current_frame - start_frame) / frames_per_pixel)
        if 0 <= playhead_x < self.timeline_rect.width:
            self.renderer.draw_playhead(timeline_surface, playhead_x,
                                        pygame.Rect(0, 0, self.timeline_rect.width, self.timeline_rect.height),
                                        self.themed_colors)

    def _draw_layer_keyframes(self, surface: pygame.Surface, layer: AnimationLayer,
                              layer_y: float, start_frame: float, end_frame: float,
                              frames_per_pixel: float):
        """Draw keyframes for a specific layer"""
        if not layer.visible:
            return

        # Get all keyframes in visible range
        keyframes = []
        for curve in layer.curves:
            for kf in curve.keyframes:
                if start_frame <= kf.frame <= end_frame:
                    keyframes.append((curve, kf))

        # Draw keyframes
        for curve, kf in keyframes:
            x = int((kf.frame - start_frame) / frames_per_pixel)
            y = int(layer_y + layer.height // 2)

            if 0 <= x < self.timeline_rect.width and 0 <= y < self.timeline_rect.height:
                # Check if this keyframe is selected
                is_selected = (layer.id, curve.property_name, kf.frame) in self.selection
                if is_selected:
                    kf.set_selected(True)
                else:
                    kf.set_selected(False)

                self.renderer.draw_keyframe(surface, (x, y), kf, self.themed_colors)

    def process_event(self, event: pygame.event.Event) -> bool:
        """Process pygame events"""
        consumed = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)
                if event.button == 1:  # Left click
                    consumed = self._handle_left_click(relative_pos)
                elif event.button == 3:  # Right click
                    consumed = self._handle_right_click(relative_pos)

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self._handle_mouse_up()
                consumed = True

        elif event.type == pygame.MOUSEMOTION:
            relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)
            consumed = self._handle_mouse_motion(relative_pos)

        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                consumed = self._handle_scroll(event.x, event.y)

        elif event.type == pygame.KEYDOWN:
            consumed = self._handle_key_event(event)

        return consumed

    def _handle_left_click(self, pos: Tuple[int, int]) -> bool:
        """Handle left mouse click"""
        x, y = pos

        # Check controls area
        if self.controls_rect.collidepoint(pos):
            return self._handle_controls_click(pos)

        # Check scrubber area
        elif self.scrubber_rect.collidepoint(pos):
            # Start scrubbing
            self.is_scrubbing = True
            self._set_frame_from_scrubber_pos(x)
            return True

        # Check timeline area
        elif self.timeline_rect.collidepoint(pos):
            timeline_pos = (x, y - self.timeline_rect.y)
            return self._handle_timeline_click(timeline_pos)

        return False

    def _handle_controls_click(self, pos: Tuple[int, int]) -> bool:
        """Handle click in controls area"""
        # Simple button detection (would be more sophisticated in real implementation)
        button_size = min(24, self.controls_rect.height - 6)
        button_y = (self.controls_rect.height - button_size) // 2
        button_spacing = button_size + 4

        button_x = 10
        buttons = [
            self._rewind_to_start,
            self._step_backward,
            self._toggle_playback,
            self._step_forward,
            self._fast_forward_to_end,
        ]

        for button_action in buttons:
            button_rect = pygame.Rect(button_x, button_y, button_size, button_size)
            if button_rect.collidepoint(pos):
                button_action()
                return True
            button_x += button_spacing

        return False

    def _handle_timeline_click(self, pos: Tuple[int, int]) -> bool:
        """Handle click in timeline area"""
        if not self.clip:
            return False

        x, y = pos

        # Calculate frame from x position
        frames_per_pixel = 1.0 / self.zoom
        start_frame = self.scroll_x * frames_per_pixel
        clicked_frame = int(start_frame + x * frames_per_pixel)

        # Find clicked layer
        layer_y = -self.scroll_y
        clicked_layer = None

        for layer in self.clip.layers:
            if layer_y <= y < layer_y + layer.height:
                clicked_layer = layer
                break
            layer_y += layer.height

        if not clicked_layer:
            return False

        # Check for keyframe click
        keyframe_clicked = False
        for curve in clicked_layer.curves:
            for kf in curve.keyframes:
                kf_x = int((kf.frame - start_frame) / frames_per_pixel)
                kf_y = layer_y + clicked_layer.height // 2

                # Check if click is near keyframe
                if abs(x - kf_x) <= self.config.keyframe_size and abs(y - kf_y) <= self.config.keyframe_size:
                    self._select_keyframe(clicked_layer.id, curve.property_name, kf.frame)
                    keyframe_clicked = True
                    break

            if keyframe_clicked:
                break

        if not keyframe_clicked:
            # Clear selection and set current frame
            self.selection.clear()
            self.set_current_frame(clicked_frame)

        self._rebuild_image()
        return True

    @staticmethod
    def _handle_right_click(pos: Tuple[int, int]) -> bool:
        """Handle right mouse click"""
        # Context menu would be implemented here
        return False

    def _handle_mouse_up(self):
        """Handle mouse button release"""
        self.is_scrubbing = False
        self.is_dragging_keyframe = False

    def _handle_mouse_motion(self, pos: Tuple[int, int]) -> bool:
        """Handle mouse motion"""
        if self.is_scrubbing and self.scrubber_rect.collidepoint(pos):
            self._set_frame_from_scrubber_pos(pos[0])
            return True

        # Update hover state
        self._update_hover_state(pos)
        return False

    def _handle_scroll(self, x_delta: int, y_delta: int) -> bool:
        """Handle scroll wheel"""
        keys = pygame.key.get_pressed()

        if keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]:
            # Zoom
            zoom_factor = 1.0 + (y_delta * ZOOM_SENSITIVITY)
            old_zoom = self.zoom
            self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * zoom_factor))

            if self.zoom != old_zoom:
                # Adjust scroll to zoom around mouse position
                mouse_x = pygame.mouse.get_pos()[0] - self.rect.x
                if self.scrubber_rect.collidepoint((mouse_x, 0)):
                    frames_per_pixel = 1.0 / old_zoom
                    mouse_frame = self.scroll_x * frames_per_pixel + mouse_x * frames_per_pixel

                    new_frames_per_pixel = 1.0 / self.zoom
                    self.scroll_x = (mouse_frame - mouse_x * new_frames_per_pixel) / new_frames_per_pixel

                self._rebuild_image()

                event_data = {'zoom': self.zoom, 'ui_element': self}
                pygame.event.post(pygame.event.Event(UI_TIMELINE_ZOOM_CHANGED, event_data))
                return True
        else:
            # Scroll
            if abs(x_delta) > abs(y_delta):
                # Horizontal scroll
                self.scroll_x = max(0, int(self.scroll_x + x_delta * 10))
            else:
                # Vertical scroll
                self.scroll_y = max(0, int(self.scroll_y + y_delta * 10))

            self._rebuild_image()
            return True

        return False

    def _handle_key_event(self, event: pygame.event.Event) -> bool:
        """Handle keyboard events"""
        if event.key == pygame.K_SPACE:
            self._toggle_playback()
            return True
        elif event.key == pygame.K_LEFT:
            self._step_backward()
            return True
        elif event.key == pygame.K_RIGHT:
            self._step_forward()
            return True
        elif event.key == pygame.K_HOME:
            self._rewind_to_start()
            return True
        elif event.key == pygame.K_END:
            self._fast_forward_to_end()
            return True
        elif event.key == pygame.K_DELETE:
            self._delete_selected_keyframes()
            return True

        return False

    def _set_frame_from_scrubber_pos(self, x: int):
        """Set current frame from scrubber x position"""
        frames_per_pixel = 1.0 / self.zoom
        start_frame = self.scroll_x * frames_per_pixel
        frame = start_frame + x * frames_per_pixel

        if self.config.snap_to_frames:
            frame = round(frame)

        self.set_current_frame(frame)

    def _update_hover_state(self, pos: Tuple[int, int]):
        """Update hover state for UI elements"""
        # Update hovered keyframe
        old_hovered = self.hovered_keyframe
        self.hovered_keyframe = self._get_keyframe_at_pos(pos)

        if old_hovered != self.hovered_keyframe:
            self._rebuild_image()

    def _get_keyframe_at_pos(self, pos: Tuple[int, int]) -> Optional[Tuple[str, str, int]]:
        """Get keyframe at mouse position"""
        if not self.clip or not self.timeline_rect.collidepoint(pos):
            return None

        x, y = pos[0], pos[1] - self.timeline_rect.y

        # Calculate frame and layer
        frames_per_pixel = 1.0 / self.zoom
        start_frame = self.scroll_x * frames_per_pixel

        layer_y = -self.scroll_y
        for layer in self.clip.layers:
            if layer_y <= y < layer_y + layer.height:
                # Check keyframes in this layer
                for curve in layer.curves:
                    for kf in curve.keyframes:
                        kf_x = int((kf.frame - start_frame) / frames_per_pixel)
                        kf_y = layer_y + layer.height // 2

                        if (abs(x - kf_x) <= self.config.keyframe_size and
                                abs(y - kf_y) <= self.config.keyframe_size):
                            return layer.id, curve.property_name, kf.frame
                break
            layer_y += layer.height

        return None

    def _select_keyframe(self, layer_id: str, property_name: str, frame: int):
        """Select a keyframe"""
        keyframe_id = (layer_id, property_name, frame)

        # Toggle selection
        if keyframe_id in self.selection:
            self.selection.remove(keyframe_id)
        else:
            # Clear previous selection (single selection for now)
            self.selection.clear()
            self.selection.append(keyframe_id)

        event_data = {
            'selection': self.selection.copy(),
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_TIMELINE_SELECTION_CHANGED, event_data))

    def _delete_selected_keyframes(self):
        """Delete selected keyframes"""
        if not self.clip or not self.selection:
            return

        for layer_id, property_name, frame in self.selection:
            layer = self.clip.get_layer(layer_id)
            if layer:
                curve = layer.get_curve(property_name)
                if curve:
                    curve.remove_keyframe(frame)

                    event_data = {
                        'layer_id': layer_id,
                        'property_name': property_name,
                        'frame': frame,
                        'ui_element': self
                    }
                    pygame.event.post(pygame.event.Event(UI_TIMELINE_KEYFRAME_REMOVED, event_data))

        self.selection.clear()
        self._rebuild_image()

    # Playback control methods
    def _toggle_playback(self):
        """Toggle playback state"""
        if self.playback_state == PlaybackState.PLAYING:
            self.pause()
        elif self.playback_state == PlaybackState.PAUSED:
            self.play()
        else:
            self.play()

    def _step_backward(self):
        """Step one frame backward"""
        self.set_current_frame(self.current_frame - 1)

    def _step_forward(self):
        """Step one frame forward"""
        self.set_current_frame(self.current_frame + 1)

    def _rewind_to_start(self):
        """Rewind to start"""
        self.set_current_frame(0)

    def _fast_forward_to_end(self):
        """Fast forward to end"""
        if self.clip:
            self.set_current_frame(self.clip.length)
        else:
            self.set_current_frame(100)  # Default length

    def update(self, time_delta: float):
        """Update the panel"""
        super().update(time_delta)

        # Handle playback
        if self.playback_state == PlaybackState.PLAYING and self.clip:
            current_time = time_module.time()
            elapsed = current_time - self.last_playback_time
            frame_delta = elapsed * self.clip.fps

            new_frame = self.current_frame + frame_delta

            if new_frame >= self.clip.length:
                if self.clip.loop:
                    new_frame = self.clip.start_frame
                else:
                    new_frame = self.clip.length
                    self.stop()

            self.set_current_frame(new_frame)
            self.last_playback_time = current_time

            # Auto-scroll during playback
            if self.config.auto_scroll_on_playback:
                self._auto_scroll_to_frame(self.current_frame)

    def _auto_scroll_to_frame(self, frame: float):
        """Auto-scroll timeline to keep frame visible"""
        frames_per_pixel = 1.0 / self.zoom
        start_frame = self.scroll_x * frames_per_pixel
        end_frame = start_frame + self.scrubber_rect.width * frames_per_pixel

        margin = (end_frame - start_frame) * 0.1  # 10% margin

        if frame < start_frame + margin:
            self.scroll_x = max(0, int((frame - margin) / frames_per_pixel))
            self._rebuild_image()
        elif frame > end_frame - margin:
            self.scroll_x = max(0, int((frame - self.scrubber_rect.width * frames_per_pixel + margin) / frames_per_pixel))
            self._rebuild_image()

    # Public API methods
    def set_clip(self, clip: AnimationClip):
        """Set the animation clip to display"""
        self.clip = clip
        self.current_frame = 0.0
        self.selection.clear()

        if self.config.zoom_to_fit_on_clip_change and clip:
            self.zoom_to_fit()

        self._rebuild_image()

    def get_clip(self) -> Optional[AnimationClip]:
        """Get the current animation clip"""
        return self.clip

    def set_current_frame(self, frame: float):
        """Set the current frame"""
        if self.clip:
            frame = max(0, min(self.clip.length, int(frame)))
        else:
            frame = max(0, int(frame))

        old_frame = self.current_frame
        self.current_frame = frame

        if old_frame != frame:
            # Fire frame change event
            event_data = {
                'frame': frame,
                'old_frame': old_frame,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_TIMELINE_FRAME_CHANGED, event_data))

            # Call callback
            if self.frame_change_callback:
                self.frame_change_callback(frame)

            self._rebuild_image()

    def get_current_frame(self) -> float:
        """Get the current frame"""
        return self.current_frame

    def play(self):
        """Start playback"""
        if self.playback_state != PlaybackState.PLAYING:
            self.playback_state = PlaybackState.PLAYING
            self.last_playback_time = time_module.time()

            event_data = {'ui_element': self}
            pygame.event.post(pygame.event.Event(UI_TIMELINE_PLAYBACK_STARTED, event_data))

            self._rebuild_image()

    def pause(self):
        """Pause playback"""
        if self.playback_state == PlaybackState.PLAYING:
            self.playback_state = PlaybackState.PAUSED

            event_data = {'ui_element': self}
            pygame.event.post(pygame.event.Event(UI_TIMELINE_PLAYBACK_PAUSED, event_data))

            self._rebuild_image()

    def stop(self):
        """Stop playback"""
        self.playback_state = PlaybackState.STOPPED

        event_data = {'ui_element': self}
        pygame.event.post(pygame.event.Event(UI_TIMELINE_PLAYBACK_STOPPED, event_data))

        self._rebuild_image()

    def add_keyframe(self, layer_id: str, property_name: str, frame: int, value: Any,
                     interpolation: InterpolationType = InterpolationType.LINEAR):
        """Add a keyframe"""
        if not self.clip:
            return False

        layer = self.clip.get_layer(layer_id)
        if not layer:
            return False

        curve = layer.get_curve(property_name)
        if not curve:
            curve = AnimationCurve(property_name, default_value=value)
            layer.add_curve(curve)

        keyframe = Keyframe(frame, value, interpolation)
        curve.add_keyframe(keyframe)

        event_data = {
            'layer_id': layer_id,
            'property_name': property_name,
            'frame': frame,
            'value': value,
            'keyframe': keyframe,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_TIMELINE_KEYFRAME_ADDED, event_data))

        if self.keyframe_change_callback:
            self.keyframe_change_callback(layer_id, property_name, frame, value)

        self._rebuild_image()
        return True

    def remove_keyframe(self, layer_id: str, property_name: str, frame: int):
        """Remove a keyframe"""
        if not self.clip:
            return False

        layer = self.clip.get_layer(layer_id)
        if not layer:
            return False

        curve = layer.get_curve(property_name)
        if not curve:
            return False

        if curve.remove_keyframe(frame):
            event_data = {
                'layer_id': layer_id,
                'property_name': property_name,
                'frame': frame,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_TIMELINE_KEYFRAME_REMOVED, event_data))

            self._rebuild_image()
            return True

        return False

    def get_value_at_frame(self, layer_id: str, property_name: str, frame: float) -> Any:
        """Get interpolated value at specific frame"""
        if not self.clip:
            return None

        layer = self.clip.get_layer(layer_id)
        if not layer:
            return None

        curve = layer.get_curve(property_name)
        if not curve:
            return None

        return curve.get_value_at_frame(frame)

    def zoom_to_fit(self):
        """Zoom timeline to fit entire clip"""
        if not self.clip or self.clip.length <= 0:
            return

        available_width = self.scrubber_rect.width - 20  # Some margin
        self.zoom = available_width / self.clip.length
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom))
        self.scroll_x = 0

        self._rebuild_image()

    def set_zoom(self, zoom: float):
        """Set timeline zoom level"""
        old_zoom = self.zoom
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))

        if old_zoom != self.zoom:
            event_data = {'zoom': self.zoom, 'ui_element': self}
            pygame.event.post(pygame.event.Event(UI_TIMELINE_ZOOM_CHANGED, event_data))
            self._rebuild_image()

    def set_frame_change_callback(self, callback: Callable[[float], None]):
        """Set callback for frame changes"""
        self.frame_change_callback = callback

    def set_keyframe_change_callback(self, callback: Callable[[str, str, int, Any], None]):
        """Set callback for keyframe changes"""
        self.keyframe_change_callback = callback

    def get_selected_keyframes(self) -> List[Tuple[str, str, int]]:
        """Get currently selected keyframes"""
        return self.selection.copy()

    def clear_selection(self):
        """Clear keyframe selection"""
        self.selection.clear()
        self._rebuild_image()

    def refresh(self):
        """Refresh the timeline display"""
        self._rebuild_image()


# Example theme for timeline panel
TIMELINE_THEME = {
    "timeline_panel": {
        "colours": {
            "timeline_bg": "#282828",
            "controls_bg": "#232323",
            "scrubber_bg": "#2d2d2d",
            "layer_bg": "#323232",
            "layer_bg_alt": "#2d2d2d",
            "normal_text": "#ffffff",
            "disabled_text": "#969696",
            "grid_line": "#3c3c3c",
            "major_tick": "#c8c8c8",
            "minor_tick": "#969696",
            "playhead": "#ff5050",
            "selection": "#6496ff",
            "keyframe_linear": "#64a0ff",
            "keyframe_ease_in": "#64ff64",
            "keyframe_ease_out": "#ff6464",
            "keyframe_ease_in_out": "#ff9664",
            "keyframe_step": "#c8c8c8",
            "keyframe_bezier": "#ff64ff",
            "keyframe_smooth": "#64ffff",
            "keyframe_selected": "#ffff64",
            "keyframe_locked": "#787878",
            "keyframe_outline": "#141414",
            "button_bg": "#3c3c3c",
            "button_hover": "#505050",
            "button_pressed": "#282828",
            "border": "#646464",
            "focus_border": "#78a0ff"
        },
        "font": {
            "name": "arial",
            "size": "10",
            "bold": "0",
            "italic": "0"
        }
    }
}


def create_sample_animation_clip() -> AnimationClip:
    """Create a sample animation clip for testing"""
    clip = AnimationClip("Sample Animation", length=120, fps=30.0)

    # Transform layer
    transform_layer = AnimationLayer("transform", "Transform", LayerType.TRANSFORM)

    # Position X animation
    pos_x_curve = AnimationCurve("position_x", default_value=0.0)
    pos_x_curve.add_keyframe(Keyframe(0, 0.0, InterpolationType.LINEAR))
    pos_x_curve.add_keyframe(Keyframe(30, 100.0, InterpolationType.EASE_OUT))
    pos_x_curve.add_keyframe(Keyframe(60, 0.0, InterpolationType.EASE_IN_OUT))
    pos_x_curve.add_keyframe(Keyframe(90, -50.0, InterpolationType.EASE_IN))
    pos_x_curve.add_keyframe(Keyframe(120, 0.0, InterpolationType.LINEAR))
    transform_layer.add_curve(pos_x_curve)

    # Position Y animation
    pos_y_curve = AnimationCurve("position_y", default_value=0.0)
    pos_y_curve.add_keyframe(Keyframe(0, 0.0, InterpolationType.LINEAR))
    pos_y_curve.add_keyframe(Keyframe(15, -30.0, InterpolationType.EASE_OUT))
    pos_y_curve.add_keyframe(Keyframe(45, 50.0, InterpolationType.EASE_IN_OUT))
    pos_y_curve.add_keyframe(Keyframe(75, -20.0, InterpolationType.SMOOTH))
    pos_y_curve.add_keyframe(Keyframe(120, 0.0, InterpolationType.LINEAR))
    transform_layer.add_curve(pos_y_curve)

    # Rotation animation
    rotation_curve = AnimationCurve("rotation", default_value=0.0)
    rotation_curve.add_keyframe(Keyframe(0, 0.0, InterpolationType.LINEAR))
    rotation_curve.add_keyframe(Keyframe(60, 180.0, InterpolationType.EASE_IN_OUT))
    rotation_curve.add_keyframe(Keyframe(120, 360.0, InterpolationType.LINEAR))
    transform_layer.add_curve(rotation_curve)

    clip.add_layer(transform_layer)

    # Color layer
    color_layer = AnimationLayer("color", "Color", LayerType.PROPERTY)

    # Color animation
    color_curve = AnimationCurve("color", default_value=pygame.Color(255, 255, 255))
    color_curve.add_keyframe(Keyframe(0, pygame.Color(255, 0, 0), InterpolationType.LINEAR))
    color_curve.add_keyframe(Keyframe(30, pygame.Color(0, 255, 0), InterpolationType.LINEAR))
    color_curve.add_keyframe(Keyframe(60, pygame.Color(0, 0, 255), InterpolationType.LINEAR))
    color_curve.add_keyframe(Keyframe(90, pygame.Color(255, 255, 0), InterpolationType.LINEAR))
    color_curve.add_keyframe(Keyframe(120, pygame.Color(255, 0, 0), InterpolationType.LINEAR))
    color_layer.add_curve(color_curve)

    # Opacity animation
    opacity_curve = AnimationCurve("opacity", default_value=1.0)
    opacity_curve.add_keyframe(Keyframe(0, 1.0, InterpolationType.LINEAR))
    opacity_curve.add_keyframe(Keyframe(20, 0.2, InterpolationType.EASE_OUT))
    opacity_curve.add_keyframe(Keyframe(40, 1.0, InterpolationType.EASE_IN))
    opacity_curve.add_keyframe(Keyframe(80, 0.5, InterpolationType.STEP))
    opacity_curve.add_keyframe(Keyframe(120, 1.0, InterpolationType.LINEAR))
    color_layer.add_curve(opacity_curve)

    clip.add_layer(color_layer)

    # Scale layer
    scale_layer = AnimationLayer("scale", "Scale", LayerType.PROPERTY)

    # Scale animation
    scale_curve = AnimationCurve("scale", default_value=1.0)
    scale_curve.add_keyframe(Keyframe(0, 1.0, InterpolationType.LINEAR))
    scale_curve.add_keyframe(Keyframe(25, 1.5, InterpolationType.EASE_OUT))
    scale_curve.add_keyframe(Keyframe(50, 0.8, InterpolationType.EASE_IN_OUT))
    scale_curve.add_keyframe(Keyframe(75, 2.0, InterpolationType.BEZIER))
    scale_curve.add_keyframe(Keyframe(100, 0.5, InterpolationType.SMOOTH))
    scale_curve.add_keyframe(Keyframe(120, 1.0, InterpolationType.LINEAR))
    scale_layer.add_curve(scale_curve)

    clip.add_layer(scale_layer)

    return clip


class SampleAnimatedObject:
    """Sample object that can be animated"""

    def __init__(self):
        self.position_x = 0.0
        self.position_y = 0.0
        self.rotation = 0.0
        self.color = pygame.Color(255, 255, 255)
        self.opacity = 1.0
        self.scale = 1.0

    def apply_frame_values(self, clip: AnimationClip, frame: float):
        """Apply animation values from specified frame"""
        for layer in clip.layers:
            for curve in layer.curves:
                value = curve.get_value_at_frame(frame)
                if hasattr(self, curve.property_name):
                    setattr(self, curve.property_name, value)


def main():
    """Example demonstration of the Timeline Panel"""
    pygame.init()
    screen = pygame.display.set_mode((1200, 800))
    pygame.display.set_caption("Timeline Panel Demo")
    clock = pygame.time.Clock()

    # Create manager with theme
    manager = pygame_gui.UIManager((1200, 800), TIMELINE_THEME)

    # Create timeline panel
    config = TimelineConfig()
    config.show_frame_numbers = True
    config.show_time_code = True
    config.auto_scroll_on_playback = True

    timeline_panel = TimelinePanel(
        pygame.Rect(50, 50, 1100, 300),
        manager,
        config,
        object_id=ObjectID(object_id='#main_timeline', class_id='@timeline_panel')
    )

    # Create sample animation
    sample_clip = create_sample_animation_clip()
    timeline_panel.set_clip(sample_clip)

    # Create animated object for demonstration
    animated_object = SampleAnimatedObject()

    # Set up frame change callback to update object
    def on_frame_changed(given_frame: float):
        if TIMELINE_DEBUG:
            print(f"Frame changed to: {given_frame}")
        animated_object.apply_frame_values(sample_clip, given_frame)

    timeline_panel.set_frame_change_callback(on_frame_changed)

    # Instructions
    print("\nTimeline Panel Demo")
    print("\nFeatures:")
    print("- Frame-based timeline with scrubbing")
    print("- Multiple interpolation types (linear, ease, step, bezier, smooth)")
    print("- Layer management")
    print("- Keyframe editing (add, remove, select)")
    print("- Playback controls")
    print("- Zoom and scroll")
    print("- Integration with animated objects")

    print("\nControls:")
    print("- Click controls to play/pause/stop")
    print("- Click and drag in scrubber to scrub timeline")
    print("- Click keyframes to select them")
    print("- Space bar to toggle playback")
    print("- Left/Right arrows to step frames")
    print("- Home/End to go to start/end")
    print("- Ctrl+Mouse wheel to zoom")
    print("- Mouse wheel to scroll")
    print("- Delete to remove selected keyframes")

    print("\nPress K to add keyframe at current frame")
    print("Press Z to zoom to fit")
    print("Press F to go to specific frame")
    print("Press L to toggle loop")
    print("Press C to clear selection\n")

    running = True
    while running:
        time_delta = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_k:
                    # Add keyframe at current frame
                    frame = int(timeline_panel.get_current_frame())
                    timeline_panel.add_keyframe("transform", "position_x", frame,
                                                animated_object.position_x, InterpolationType.LINEAR)
                    print(f"Added keyframe at frame {frame}")

                elif event.key == pygame.K_z:
                    # Zoom to fit
                    timeline_panel.zoom_to_fit()
                    print("Zoomed to fit")

                elif event.key == pygame.K_f:
                    # Go to frame (simplified - just go to frame 60)
                    timeline_panel.set_current_frame(60)
                    print("Jumped to frame 60")

                elif event.key == pygame.K_l:
                    # Toggle loop
                    if sample_clip:
                        sample_clip.loop = not sample_clip.loop
                        print(f"Loop {'enabled' if sample_clip.loop else 'disabled'}")

                elif event.key == pygame.K_c:
                    # Clear selection
                    timeline_panel.clear_selection()
                    print("Cleared selection")

            # Handle timeline events
            elif event.type == UI_TIMELINE_FRAME_CHANGED:
                if TIMELINE_DEBUG:
                    print(f"Frame changed: {event.frame}")

            elif event.type == UI_TIMELINE_KEYFRAME_ADDED:
                if TIMELINE_DEBUG:
                    print(f"Keyframe added: {event.layer_id}.{event.property_name} @ {event.frame}")

            elif event.type == UI_TIMELINE_KEYFRAME_REMOVED:
                if TIMELINE_DEBUG:
                    print(f"Keyframe removed: {event.layer_id}.{event.property_name} @ {event.frame}")

            elif event.type == UI_TIMELINE_PLAYBACK_STARTED:
                if TIMELINE_DEBUG:
                    print("Playback started")

            elif event.type == UI_TIMELINE_PLAYBACK_STOPPED:
                if TIMELINE_DEBUG:
                    print("Playback stopped")

            elif event.type == UI_TIMELINE_PLAYBACK_PAUSED:
                if TIMELINE_DEBUG:
                    print("Playback paused")

            elif event.type == UI_TIMELINE_SELECTION_CHANGED:
                if TIMELINE_DEBUG:
                    print(f"Selection changed: {len(event.selection)} keyframes selected")

            elif event.type == UI_TIMELINE_ZOOM_CHANGED:
                if TIMELINE_DEBUG:
                    print(f"Zoom changed: {event.zoom:.2f}")

            # Forward to manager
            manager.process_events(event)

        # Update
        manager.update(time_delta)

        # Draw
        screen.fill((20, 20, 20))

        # Draw animated object visualization
        center_x = 600
        center_y = 500

        # Calculate position based on animation
        draw_x = center_x + animated_object.position_x
        draw_y = center_y + animated_object.position_y

        # Calculate size based on scale
        base_size = 30
        size = int(base_size * animated_object.scale)

        # Calculate color with opacity
        color = pygame.Color(animated_object.color)
        color.a = int(255 * animated_object.opacity)

        # Draw object (simple circle)
        if size > 0:
            pygame.draw.circle(screen, color, (int(draw_x), int(draw_y)), size)

            # Draw rotation indicator (line from center)
            import math
            line_length = size * 0.8
            angle_rad = math.radians(animated_object.rotation)
            end_x = draw_x + math.cos(angle_rad) * line_length
            end_y = draw_y + math.sin(angle_rad) * line_length
            pygame.draw.line(screen, pygame.Color(255, 255, 255),
                             (draw_x, draw_y), (end_x, end_y), 2)

        # Draw info text
        font = pygame.font.Font(None, 24)
        info_lines = [
            f"Timeline Demo - Frame: {timeline_panel.get_current_frame():.1f}",
            f"Position: ({animated_object.position_x:.1f}, {animated_object.position_y:.1f})",
            f"Rotation: {animated_object.rotation:.1f}",
            f"Scale: {animated_object.scale:.2f}",
            f"Opacity: {animated_object.opacity:.2f}",
            f"Playback: {timeline_panel.playback_state.value}"
        ]

        y_offset = 380
        for line in info_lines:
            text_surface = font.render(line, True, pygame.Color(255, 255, 255))
            screen.blit(text_surface, (50, y_offset))
            y_offset += 25

        # Draw keyframe info
        if timeline_panel.get_selected_keyframes():
            selection_text = f"Selected: {len(timeline_panel.get_selected_keyframes())} keyframes"
            text_surface = font.render(selection_text, True, pygame.Color(255, 255, 100))
            screen.blit(text_surface, (50, y_offset))

        manager.draw_ui(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()