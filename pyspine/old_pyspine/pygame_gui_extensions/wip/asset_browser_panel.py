import pygame
import pygame_gui
from pygame_gui.core import UIElement, ObjectID
from pygame_gui.core.interfaces import IContainerLikeInterface
from typing import List, Optional, Dict, Any, Union, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import time
import hashlib
from pathlib import Path
import threading
from queue import Queue

try:
    from pygame_gui.core.interfaces.gui_font_interface import IGUIFontInterface
except ImportError:
    IGUIFontInterface = None

# Optional PIL support for better thumbnail generation
try:
    from PIL import Image as PILImage

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

ASSET_DEBUG = False

# Constants
DEFAULT_THUMBNAIL_SIZE = (128, 128)
SMALL_THUMBNAIL_SIZE = (64, 64)
LARGE_THUMBNAIL_SIZE = (256, 256)
GRID_ITEM_PADDING = 8
LIST_ITEM_HEIGHT = 32
DETAIL_ITEM_HEIGHT = 80

# Define custom pygame-gui events
UI_ASSET_SELECTED = pygame.USEREVENT + 100
UI_ASSET_DOUBLE_CLICKED = pygame.USEREVENT + 101
UI_ASSET_RIGHT_CLICKED = pygame.USEREVENT + 102
UI_ASSET_DRAG_STARTED = pygame.USEREVENT + 103
UI_ASSET_DROP_COMPLETED = pygame.USEREVENT + 104
UI_ASSET_IMPORT_REQUESTED = pygame.USEREVENT + 105
UI_ASSET_EXPORT_REQUESTED = pygame.USEREVENT + 106
UI_ASSET_METADATA_CHANGED = pygame.USEREVENT + 107
UI_ASSET_COLLECTION_CHANGED = pygame.USEREVENT + 108
UI_ASSET_SEARCH_UPDATED = pygame.USEREVENT + 109


class AssetType(Enum):
    """Supported asset types"""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    MODEL = "model"
    TEXT = "text"
    SCRIPT = "script"
    FONT = "font"
    MATERIAL = "material"
    ANIMATION = "animation"
    PREFAB = "prefab"
    SCENE = "scene"
    OTHER = "other"

    def __lt__(self, other):
        """Enable sorting of AssetType enums"""
        if isinstance(other, AssetType):
            return self.value < other.value
        return NotImplemented

class AssetViewMode(Enum):
    """Asset browser view modes"""
    GRID = "grid"
    LIST = "list"
    DETAIL = "detail"


class AssetSortMode(Enum):
    """Asset sorting options"""
    NAME = "name"
    TYPE = "type"
    SIZE = "size"
    DATE_MODIFIED = "date_modified"
    DATE_CREATED = "date_created"


@dataclass
class AssetMetadata:
    """Metadata for an asset"""
    # File information
    file_size: int = 0
    date_created: float = 0.0
    date_modified: float = 0.0
    file_hash: Optional[str] = None

    # Asset-specific data
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    format: Optional[str] = None
    color_depth: Optional[int] = None
    compression: Optional[str] = None

    # User-defined metadata
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    copyright: Optional[str] = None
    tags: Set[str] = field(default_factory=set)
    rating: int = 0  # 0-5 stars
    favorite: bool = False

    # Custom properties
    custom_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for serialization"""
        data = {
            'file_size': self.file_size,
            'date_created': self.date_created,
            'date_modified': self.date_modified,
            'file_hash': self.file_hash,
            'width': self.width,
            'height': self.height,
            'duration': self.duration,
            'format': self.format,
            'color_depth': self.color_depth,
            'compression': self.compression,
            'title': self.title,
            'description': self.description,
            'author': self.author,
            'copyright': self.copyright,
            'tags': list(self.tags),
            'rating': self.rating,
            'favorite': self.favorite,
            'custom_data': self.custom_data
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AssetMetadata':
        """Create metadata from dictionary"""
        metadata = cls()
        for key, value in data.items():
            if key == 'tags':
                metadata.tags = set(value) if value else set()
            elif hasattr(metadata, key):
                setattr(metadata, key, value)
        return metadata


@dataclass
class AssetItem:
    """Represents a single asset"""
    id: str
    name: str
    file_path: Path
    asset_type: AssetType
    metadata: AssetMetadata = field(default_factory=AssetMetadata)
    thumbnail_path: Optional[Path] = None
    collection_id: Optional[str] = None

    # Runtime data
    thumbnail_surface: Optional[pygame.Surface] = None
    is_loading_thumbnail: bool = False
    last_access_time: float = field(default_factory=time.time)

    def get_file_extension(self) -> str:
        """Get file extension"""
        return self.file_path.suffix.lower()

    def get_display_name(self) -> str:
        """Get display name (title or filename)"""
        return self.metadata.title or self.name

    def get_file_size_str(self) -> str:
        """Get human-readable file size"""
        size = self.metadata.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"

    def matches_search(self, query: str) -> bool:
        """Check if asset matches search query"""
        query = query.lower()

        # Check name and title
        if query in self.name.lower():
            return True
        if self.metadata.title and query in self.metadata.title.lower():
            return True

        # Check description
        if self.metadata.description and query in self.metadata.description.lower():
            return True

        # Check tags
        for tag in self.metadata.tags:
            if query in tag.lower():
                return True

        # Check file extension
        if query in self.get_file_extension():
            return True

        # Check author
        if self.metadata.author and query in self.metadata.author.lower():
            return True

        return False

    def has_tag(self, tag: str) -> bool:
        """Check if asset has a specific tag"""
        return tag.lower() in [t.lower() for t in self.metadata.tags]


@dataclass
class AssetCollection:
    """Represents a collection/folder of assets"""
    id: str
    name: str
    description: str = ""
    asset_ids: Set[str] = field(default_factory=set)
    parent_id: Optional[str] = None
    children_ids: Set[str] = field(default_factory=set)
    color: Optional[pygame.Color] = None
    icon_name: Optional[str] = None
    expanded: bool = True
    order: int = 0

    # Metadata
    created_time: float = field(default_factory=time.time)
    modified_time: float = field(default_factory=time.time)

    def add_asset(self, asset_id: str):
        """Add asset to collection"""
        self.asset_ids.add(asset_id)
        self.modified_time = time.time()

    def remove_asset(self, asset_id: str):
        """Remove asset from collection"""
        self.asset_ids.discard(asset_id)
        self.modified_time = time.time()

    def add_child_collection(self, collection_id: str):
        """Add child collection"""
        self.children_ids.add(collection_id)
        self.modified_time = time.time()

    def remove_child_collection(self, collection_id: str):
        """Remove child collection"""
        self.children_ids.discard(collection_id)
        self.modified_time = time.time()


class AssetPreviewGenerator:
    """Generates thumbnails and previews for assets"""

    def __init__(self, cache_dir: Path = None, thumbnail_size: Tuple[int, int] = DEFAULT_THUMBNAIL_SIZE):
        self.cache_dir = cache_dir or Path("asset_cache")
        self.thumbnail_size = thumbnail_size
        self.cache_dir.mkdir(exist_ok=True)

        # Background thumbnail generation
        self.generation_queue = Queue()
        self.generation_thread = None
        self.stop_generation = False

        # Supported formats
        self.image_formats = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.gif', '.webp'}
        self.text_formats = {'.txt', '.py', '.json', '.xml', '.html', '.css', '.js', '.md'}

        self._start_generation_thread()

    def _start_generation_thread(self):
        """Start background thumbnail generation thread"""
        if self.generation_thread is None or not self.generation_thread.is_alive():
            self.stop_generation = False
            self.generation_thread = threading.Thread(target=self._generation_worker, daemon=True)
            self.generation_thread.start()

    def _generation_worker(self):
        """Background worker for thumbnail generation"""
        while not self.stop_generation:
            try:
                asset_item = self.generation_queue.get(timeout=1.0)
                if asset_item is None:  # Shutdown signal
                    break

                self._generate_thumbnail_sync(asset_item)
                asset_item.is_loading_thumbnail = False

            except:
                continue

    def stop(self):
        """Stop background generation"""
        self.stop_generation = True
        self.generation_queue.put(None)  # Signal shutdown
        if self.generation_thread and self.generation_thread.is_alive():
            self.generation_thread.join(timeout=1.0)

    def get_cache_path(self, asset_item: AssetItem) -> Path:
        """Get cache file path for asset thumbnail"""
        # Use file hash for cache key if available
        cache_key = asset_item.metadata.file_hash or asset_item.id
        return self.cache_dir / f"{cache_key}_{self.thumbnail_size[0]}x{self.thumbnail_size[1]}.png"

    def has_cached_thumbnail(self, asset_item: AssetItem) -> bool:
        """Check if cached thumbnail exists and is up to date"""
        cache_path = self.get_cache_path(asset_item)
        if not cache_path.exists():
            return False

        # Check if cache is newer than source file
        try:
            cache_time = cache_path.stat().st_mtime
            source_time = asset_item.file_path.stat().st_mtime
            return cache_time >= source_time
        except OSError:
            return False

    def get_thumbnail_async(self, asset_item: AssetItem) -> pygame.Surface:
        """Get thumbnail asynchronously (returns placeholder if not ready)"""
        # Return cached surface if available
        if asset_item.thumbnail_surface:
            return asset_item.thumbnail_surface

        # Check for cached file
        cache_path = self.get_cache_path(asset_item)
        if self.has_cached_thumbnail(asset_item):
            try:
                asset_item.thumbnail_surface = pygame.image.load(str(cache_path))
                return asset_item.thumbnail_surface
            except pygame.error:
                pass

        # Queue for background generation if not already loading
        if not asset_item.is_loading_thumbnail:
            asset_item.is_loading_thumbnail = True
            self.generation_queue.put(asset_item)

        # Return placeholder
        return self._create_placeholder_thumbnail(asset_item)

    def _generate_thumbnail_sync(self, asset_item: AssetItem):
        """Generate thumbnail synchronously"""
        try:
            surface = None

            if asset_item.asset_type == AssetType.IMAGE:
                surface = self._generate_image_thumbnail(asset_item)
            elif asset_item.asset_type == AssetType.TEXT:
                surface = self._generate_text_thumbnail(asset_item)
            else:
                surface = self._create_placeholder_thumbnail(asset_item)

            if surface:
                # Save to cache
                cache_path = self.get_cache_path(asset_item)
                pygame.image.save(surface, str(cache_path))

                # Store in asset
                asset_item.thumbnail_surface = surface

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error generating thumbnail for {asset_item.name}: {e}")

    def _generate_image_thumbnail(self, asset_item: AssetItem) -> pygame.Surface:
        """Generate thumbnail for image asset"""
        try:
            if PIL_AVAILABLE:
                # Use PIL for better quality
                with PILImage.open(asset_item.file_path) as pil_img:
                    # Convert to RGB if necessary
                    if pil_img.mode not in ('RGB', 'RGBA'):
                        pil_img = pil_img.convert('RGB')

                    # Create thumbnail
                    pil_img.thumbnail(self.thumbnail_size, PILImage.Resampling.LANCZOS)

                    # Convert to pygame surface
                    mode = pil_img.mode
                    size = pil_img.size
                    data = pil_img.tobytes()

                    # surface = pygame.image.fromstring(data, size, mode)
                    surface = pygame.image.frombytes(data, size, mode)
                    return surface
            else:
                # Use pygame directly
                original = pygame.image.load(str(asset_item.file_path))
                return pygame.transform.scale(original, self.thumbnail_size)

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error generating image thumbnail: {e}")
            return self._create_placeholder_thumbnail(asset_item)

    def _generate_text_thumbnail(self, asset_item: AssetItem) -> pygame.Surface:
        """Generate thumbnail for text asset"""
        surface = pygame.Surface(self.thumbnail_size)
        surface.fill((50, 50, 50))

        try:
            # Read first few lines of text
            with open(asset_item.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = [line.strip() for line in f.readlines()[:10] if line.strip()]

            # Render text
            font = pygame.font.Font(None, 12)
            y_offset = 5

            for line in lines[:8]:  # Max 8 lines
                if y_offset > self.thumbnail_size[1] - 15:
                    break

                # Truncate long lines
                if len(line) > 30:
                    line = line[:27] + "..."

                text_surface = font.render(line, True, (200, 200, 200))
                surface.blit(text_surface, (5, y_offset))
                y_offset += 14

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error generating text thumbnail: {e}")

        # Draw border
        pygame.draw.rect(surface, (100, 100, 100), surface.get_rect(), 1)
        return surface

    def _create_placeholder_thumbnail(self, asset_item: AssetItem) -> pygame.Surface:
        """Create placeholder thumbnail based on asset type"""
        surface = pygame.Surface(self.thumbnail_size)

        # Color by type
        type_colors = {
            AssetType.IMAGE: (100, 150, 100),
            AssetType.AUDIO: (150, 100, 150),
            AssetType.VIDEO: (150, 150, 100),
            AssetType.MODEL: (100, 100, 150),
            AssetType.TEXT: (120, 120, 120),
            AssetType.SCRIPT: (150, 120, 100),
            AssetType.FONT: (100, 120, 150),
            AssetType.OTHER: (100, 100, 100),
        }

        color = type_colors.get(asset_item.asset_type, (100, 100, 100))
        surface.fill(color)

        # Draw icon/text
        font = pygame.font.Font(None, 24)

        # Type-specific icons (simplified)
        icon_text = {
            AssetType.IMAGE: "IMAGE",
            AssetType.AUDIO: "AUDIO",
            AssetType.VIDEO: "VIDEO",
            AssetType.MODEL: "MODEL",
            AssetType.TEXT: "TEXT",
            AssetType.SCRIPT: "SCRIPT",
            AssetType.FONT: "FONT",
            AssetType.OTHER: "OTHER",
        }

        text = icon_text.get(asset_item.asset_type, "?")
        text_surface = font.render(text, True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=surface.get_rect().center)
        surface.blit(text_surface, text_rect)

        # Draw border
        pygame.draw.rect(surface, (150, 150, 150), surface.get_rect(), 2)

        return surface


@dataclass
class AssetBrowserConfig:
    """Configuration for the asset browser"""
    # View settings
    default_view_mode: AssetViewMode = AssetViewMode.GRID
    thumbnail_size: Tuple[int, int] = DEFAULT_THUMBNAIL_SIZE
    grid_columns: int = 4  # Auto-calculate if 0
    show_file_extensions: bool = True
    show_metadata_overlay: bool = True

    # Behavior
    allow_drag_drop: bool = True
    allow_multi_select: bool = True
    double_click_action: str = "open"  # "open", "edit", "select"
    auto_generate_thumbnails: bool = True
    cache_thumbnails: bool = True

    # Search and filtering
    search_in_metadata: bool = True
    search_in_tags: bool = True
    filter_by_type: bool = True
    sort_mode: AssetSortMode = AssetSortMode.NAME
    sort_ascending: bool = True

    # Performance
    max_visible_items: int = 1000
    thumbnail_generation_delay: float = 0.1
    lazy_loading: bool = True


class AssetItemUI:
    """UI representation of an asset item"""

    def __init__(self, asset_item: AssetItem, rect: pygame.Rect, config: AssetBrowserConfig):
        self.asset_item = asset_item
        self.rect = rect
        self.config = config

        # UI state
        self.is_selected = False
        self.is_hovered = False
        self.is_focused = False
        self.is_dragging = False

        # Layout
        self.thumbnail_rect = pygame.Rect(0, 0, 0, 0)
        self.text_rect = pygame.Rect(0, 0, 0, 0)
        self.metadata_rect = pygame.Rect(0, 0, 0, 0)

        self.calculate_layout()

    def calculate_layout(self):
        """Calculate internal layout based on view mode and rect"""
        if self.config.default_view_mode == AssetViewMode.GRID:
            # Grid layout: thumbnail on top, text below
            padding = GRID_ITEM_PADDING
            thumb_size = min(self.rect.width - padding * 2, self.rect.height - 30)

            self.thumbnail_rect = pygame.Rect(
                self.rect.centerx - thumb_size // 2,
                self.rect.y + padding,
                thumb_size,
                thumb_size
            )

            self.text_rect = pygame.Rect(
                self.rect.x + padding,
                self.thumbnail_rect.bottom + 2,
                self.rect.width - padding * 2,
                20
            )

        elif self.config.default_view_mode == AssetViewMode.LIST:
            # List layout: small thumbnail on left, text on right
            thumb_size = self.rect.height - 4

            self.thumbnail_rect = pygame.Rect(
                self.rect.x + 2,
                self.rect.y + 2,
                thumb_size,
                thumb_size
            )

            self.text_rect = pygame.Rect(
                self.thumbnail_rect.right + 8,
                self.rect.y,
                self.rect.width - self.thumbnail_rect.width - 10,
                self.rect.height
            )

        else:  # DETAIL
            # Detail layout: medium thumbnail, text, and metadata
            thumb_size = 64

            self.thumbnail_rect = pygame.Rect(
                self.rect.x + 4,
                self.rect.y + 4,
                thumb_size,
                thumb_size
            )

            self.text_rect = pygame.Rect(
                self.thumbnail_rect.right + 8,
                self.rect.y + 4,
                self.rect.width - thumb_size - 16,
                20
            )

            self.metadata_rect = pygame.Rect(
                self.thumbnail_rect.right + 8,
                self.text_rect.bottom + 2,
                self.rect.width - thumb_size - 16,
                self.rect.height - 30
            )

    def draw(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color],
             preview_generator: AssetPreviewGenerator):
        """Draw the asset item"""

        # Background
        if self.is_selected:
            pygame.draw.rect(surface, colors.get('selected_bg', pygame.Color(70, 130, 180)), self.rect)
        elif self.is_hovered:
            pygame.draw.rect(surface, colors.get('hovered_bg', pygame.Color(60, 60, 60)), self.rect)

        # Focus border
        if self.is_focused:
            pygame.draw.rect(surface, colors.get('focus_border', pygame.Color(255, 255, 255)), self.rect, 2)

        # Draw thumbnail
        self._draw_thumbnail(surface, preview_generator)

        # Draw text
        self._draw_text(surface, font, colors)

        # Draw metadata if in detail view
        if self.config.default_view_mode == AssetViewMode.DETAIL:
            self._draw_metadata(surface, font, colors)

        # Draw loading indicator
        if self.asset_item.is_loading_thumbnail:
            self._draw_loading_indicator(surface, colors)

    def _draw_thumbnail(self, surface: pygame.Surface, preview_generator: AssetPreviewGenerator):
        """Draw the asset thumbnail"""
        thumbnail = preview_generator.get_thumbnail_async(self.asset_item)

        if thumbnail:
            # Scale thumbnail to fit rect while maintaining aspect ratio
            thumb_rect = thumbnail.get_rect()

            # Calculate scaling to fit within thumbnail_rect
            scale_x = self.thumbnail_rect.width / thumb_rect.width
            scale_y = self.thumbnail_rect.height / thumb_rect.height
            scale = min(scale_x, scale_y)

            new_size = (int(thumb_rect.width * scale), int(thumb_rect.height * scale))
            scaled_thumbnail = pygame.transform.scale(thumbnail, new_size)

            # Center in thumbnail rect
            pos = (
                self.thumbnail_rect.centerx - new_size[0] // 2,
                self.thumbnail_rect.centery - new_size[1] // 2
            )

            surface.blit(scaled_thumbnail, pos)

        # Draw thumbnail border
        pygame.draw.rect(surface, pygame.Color(100, 100, 100), self.thumbnail_rect, 1)

    def _draw_text(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        """Draw asset name text"""
        text_color = colors.get('normal_text', pygame.Color(255, 255, 255))

        # Get display name
        display_name = self.asset_item.get_display_name()

        # Add file extension if configured
        if self.config.show_file_extensions and not self.asset_item.metadata.title:
            display_name += self.asset_item.get_file_extension()

        # Truncate if too long
        max_chars = 30 if self.config.default_view_mode == AssetViewMode.GRID else 50
        if len(display_name) > max_chars:
            display_name = display_name[:max_chars - 3] + "..."

        try:
            if hasattr(font, 'render_premul'):
                text_surface = font.render_premul(display_name, text_color)
            else:
                text_surface = font.render(display_name, True, text_color)

            # Center text in grid mode, left-align in others
            if self.config.default_view_mode == AssetViewMode.GRID:
                text_pos = (
                    self.text_rect.centerx - text_surface.get_width() // 2,
                    self.text_rect.y
                )
            else:
                text_pos = (self.text_rect.x, self.text_rect.centery - text_surface.get_height() // 2)

            surface.blit(text_surface, text_pos)

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error rendering asset text: {e}")

    def _draw_metadata(self, surface: pygame.Surface, font: Any, colors: Dict[str, pygame.Color]):
        """Draw metadata in detail view"""
        if not self.metadata_rect.width or not self.metadata_rect.height:
            return

        metadata_color = colors.get('secondary_text', pygame.Color(180, 180, 180))

        # Prepare metadata lines
        lines = []

        # File size
        lines.append(f"Size: {self.asset_item.get_file_size_str()}")

        # Dimensions for images
        if self.asset_item.metadata.width and self.asset_item.metadata.height:
            lines.append(f"Dimensions: {self.asset_item.metadata.width}x{self.asset_item.metadata.height}")

        # Tags
        if self.asset_item.metadata.tags:
            tags_str = ", ".join(list(self.asset_item.metadata.tags)[:3])
            if len(self.asset_item.metadata.tags) > 3:
                tags_str += "..."
            lines.append(f"Tags: {tags_str}")

        # Rating
        if self.asset_item.metadata.rating > 0:
            stars = "*" * self.asset_item.metadata.rating + "_" * (5 - self.asset_item.metadata.rating)
            lines.append(f"Rating: {stars}")

        # Draw lines
        try:
            y_offset = self.metadata_rect.y
            for line in lines[:3]:  # Max 3 lines
                if y_offset > self.metadata_rect.bottom - 15:
                    break

                if hasattr(font, 'render_premul'):
                    line_surface = font.render_premul(line, metadata_color)
                else:
                    line_surface = font.render(line, True, metadata_color)

                surface.blit(line_surface, (self.metadata_rect.x, y_offset))
                y_offset += 14

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error rendering metadata: {e}")

    def _draw_loading_indicator(self, surface: pygame.Surface, colors: Dict[str, pygame.Color]):
        """Draw loading indicator for thumbnails"""
        # Simple spinning circle
        center = self.thumbnail_rect.center
        radius = 8

        # Animate based on time
        angle = (time.time() * 360) % 360

        # Draw spinning arc
        loading_color = colors.get('accent', pygame.Color(100, 200, 100))

        # pygame doesn't have arc drawing, so draw a simple pulsing circle
        alpha = int(127 + 127 * abs(pygame.math.Vector2().rotate(angle).x))
        loading_color.a = alpha

        pygame.draw.circle(surface, loading_color, center, radius)

    def contains_point(self, pos: Tuple[int, int]) -> bool:
        """Check if point is within this item"""
        return self.rect.collidepoint(pos)

    def update_selection(self, selected: bool):
        """Update selection state"""
        self.is_selected = selected

    def update_hover(self, hovered: bool):
        """Update hover state"""
        self.is_hovered = hovered

    def update_focus(self, focused: bool):
        """Update focus state"""
        self.is_focused = focused


class AssetBrowserPanel(UIElement):
    """Main asset browser panel widget"""

    def __init__(self, relative_rect: pygame.Rect,
                 manager: pygame_gui.UIManager,
                 config: AssetBrowserConfig = None,
                 container: IContainerLikeInterface = None,
                 object_id: Union[ObjectID, str, None] = None,
                 anchors: Dict[str, str] = None):

        # Handle object_id properly
        if isinstance(object_id, ObjectID):
            self._object_id = object_id
        elif isinstance(object_id, str):
            self._object_id = ObjectID(object_id=object_id, class_id=None)
        else:
            self._object_id = ObjectID(object_id='#asset_browser', class_id=None)

        super().__init__(relative_rect, manager, container,
                         starting_height=1, layer_thickness=1,
                         anchors=anchors, object_id=self._object_id)

        self.config = config or AssetBrowserConfig()

        # Asset data
        self.assets: Dict[str, AssetItem] = {}
        self.collections: Dict[str, AssetCollection] = {}
        self.preview_generator = AssetPreviewGenerator(
            thumbnail_size=self.config.thumbnail_size
        )

        # UI state
        self.asset_item_uis: List[AssetItemUI] = []
        self.visible_assets: List[str] = []
        self.selected_assets: Set[str] = set()
        self.focused_asset: Optional[str] = None
        self.hovered_asset: Optional[str] = None

        # Current view settings
        self.current_collection: Optional[str] = None
        self.search_query: str = ""
        self.filter_types: Set[AssetType] = set()
        self.view_mode = self.config.default_view_mode

        # Drag and drop state
        self.dragging_assets: Set[str] = set()
        self.drag_start_pos: Optional[Tuple[int, int]] = None
        self.drop_target: Optional[str] = None

        # Scrolling
        self.scroll_y = 0
        self.max_scroll = 0
        self.content_height = 0

        # Performance tracking
        self.last_click_time = 0
        self.double_click_time = 500

        # Theme data
        self._update_theme_data()

        # Create the image surface
        self.image = pygame.Surface(self.rect.size).convert()

        # Initialize
        self.rebuild_ui()
        self._rebuild_image()

    def __del__(self):
        """Cleanup when destroyed"""
        if hasattr(self, 'preview_generator'):
            self.preview_generator.stop()

    def _update_theme_data(self):
        """Update theme-dependent data"""
        try:
            self.themed_colors = {}

            color_mappings = {
                'dark_bg': pygame.Color(40, 40, 40),
                'normal_text': pygame.Color(255, 255, 255),
                'secondary_text': pygame.Color(180, 180, 180),
                'selected_bg': pygame.Color(70, 130, 180),
                'hovered_bg': pygame.Color(60, 60, 60),
                'focused_bg': pygame.Color(100, 160, 220),
                'normal_border': pygame.Color(100, 100, 100),
                'focus_border': pygame.Color(255, 255, 255),
                'accent': pygame.Color(100, 200, 100),
                'grid_line': pygame.Color(80, 80, 80),
            }

            theme = self.ui_manager.get_theme()

            for color_id, default_color in color_mappings.items():
                try:
                    if hasattr(theme, 'get_colour_or_gradient'):
                        color = theme.get_colour_or_gradient(color_id, ['asset_browser'])
                        self.themed_colors[color_id] = color if color else default_color
                    else:
                        self.themed_colors[color_id] = default_color
                except Exception:
                    self.themed_colors[color_id] = default_color

            # Get themed font
            try:
                if hasattr(theme, 'get_font'):
                    self.themed_font = theme.get_font(['asset_browser'])
                else:
                    raise Exception("No font method")
            except Exception:
                try:
                    self.themed_font = pygame.font.SysFont('Arial', 12)
                except:
                    self.themed_font = pygame.font.Font(None, 12)

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error getting theme data: {e}")
            # Complete fallback
            self.themed_colors = {
                'dark_bg': pygame.Color(40, 40, 40),
                'normal_text': pygame.Color(255, 255, 255),
                'secondary_text': pygame.Color(180, 180, 180),
                'selected_bg': pygame.Color(70, 130, 180),
                'hovered_bg': pygame.Color(60, 60, 60),
                'focused_bg': pygame.Color(100, 160, 220),
                'normal_border': pygame.Color(100, 100, 100),
                'focus_border': pygame.Color(255, 255, 255),
                'accent': pygame.Color(100, 200, 100),
                'grid_line': pygame.Color(80, 80, 80),
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

    def add_asset(self, file_path: Union[str, Path], asset_type: AssetType = None,
                  collection_id: str = None) -> AssetItem:
        """Add an asset to the browser"""
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Asset file not found: {file_path}")

        # Auto-detect asset type if not provided
        if asset_type is None:
            asset_type = self._detect_asset_type(file_path)

        # Generate unique ID
        asset_id = self.generate_asset_id(file_path)

        # Create metadata
        metadata = self._extract_file_metadata(file_path)

        # Create asset item
        asset_item = AssetItem(
            id=asset_id,
            name=file_path.stem,
            file_path=file_path,
            asset_type=asset_type,
            metadata=metadata,
            collection_id=collection_id
        )

        self.assets[asset_id] = asset_item

        # Add to collection if specified
        if collection_id and collection_id in self.collections:
            self.collections[collection_id].add_asset(asset_id)

        # Rebuild UI to show new asset
        self.rebuild_ui()
        self._rebuild_image()

        # Fire event
        event_data = {
            'asset': asset_item,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_ASSET_IMPORT_REQUESTED, event_data))

        return asset_item

    def add_collection(self, name: str, description: str = "", parent_id: str = None) -> AssetCollection:
        """Add a new collection"""
        collection_id = self.generate_collection_id(name)

        collection = AssetCollection(
            id=collection_id,
            name=name,
            description=description,
            parent_id=parent_id
        )

        self.collections[collection_id] = collection

        # Add to parent if specified
        if parent_id and parent_id in self.collections:
            self.collections[parent_id].add_child_collection(collection_id)

        # Fire event
        event_data = {
            'collection': collection,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_ASSET_COLLECTION_CHANGED, event_data))

        return collection

    @staticmethod
    def _detect_asset_type(file_path: Path) -> AssetType:
        """Auto-detect asset type from file extension"""
        ext = file_path.suffix.lower()

        image_exts = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.gif', '.webp', '.tiff'}
        audio_exts = {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'}
        video_exts = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv'}
        text_exts = {'.txt', '.md', '.rtf'}
        script_exts = {'.py', '.js', '.html', '.css', '.json', '.xml', '.yml', '.yaml'}
        font_exts = {'.ttf', '.otf', '.woff', '.woff2'}
        model_exts = {'.obj', '.fbx', '.dae', '.3ds', '.blend', '.max'}

        if ext in image_exts:
            return AssetType.IMAGE
        elif ext in audio_exts:
            return AssetType.AUDIO
        elif ext in video_exts:
            return AssetType.VIDEO
        elif ext in text_exts:
            return AssetType.TEXT
        elif ext in script_exts:
            return AssetType.SCRIPT
        elif ext in font_exts:
            return AssetType.FONT
        elif ext in model_exts:
            return AssetType.MODEL
        else:
            return AssetType.OTHER

    def _extract_file_metadata(self, file_path: Path) -> AssetMetadata:
        """Extract metadata from file"""
        metadata = AssetMetadata()

        try:
            stat = file_path.stat()
            metadata.file_size = stat.st_size
            metadata.date_created = stat.st_ctime
            metadata.date_modified = stat.st_mtime

            # Generate file hash for caching
            metadata.file_hash = self._calculate_file_hash(file_path)

            # Extract format-specific metadata
            if file_path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.gif'}:
                try:
                    if PIL_AVAILABLE:
                        with PILImage.open(file_path) as img:
                            metadata.width, metadata.height = img.size
                            metadata.format = img.format
                            metadata.color_depth = len(img.getbands()) * 8
                    else:
                        # Fallback to pygame
                        img = pygame.image.load(str(file_path))
                        metadata.width, metadata.height = img.get_size()
                except:
                    pass

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error extracting metadata for {file_path}: {e}")

        return metadata

    @staticmethod
    def _calculate_file_hash(file_path: Path) -> str:
        """Calculate MD5 hash of file for caching"""
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except:
            return str(file_path)  # Fallback to path

    @staticmethod
    def generate_asset_id(file_path: Path) -> str:
        """Generate unique asset ID"""
        return f"asset_{abs(hash(str(file_path)))}"

    def generate_collection_id(self, name: str) -> str:
        """Generate unique collection ID"""
        base_id = f"collection_{name.lower().replace(' ', '_')}"
        counter = 1
        collection_id = base_id

        while collection_id in self.collections:
            collection_id = f"{base_id}_{counter}"
            counter += 1

        return collection_id

    def set_current_collection(self, collection_id: Optional[str]):
        """Set the currently viewed collection"""
        self.current_collection = collection_id
        self.rebuild_ui()
        self._rebuild_image()

    def set_search_query(self, query: str):
        """Set search query and filter assets"""
        self.search_query = query.strip()
        self.rebuild_ui()
        self._rebuild_image()

        # Fire search event
        event_data = {
            'query': self.search_query,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_ASSET_SEARCH_UPDATED, event_data))

    def set_view_mode(self, view_mode: AssetViewMode):
        """Change view mode"""
        if self.view_mode != view_mode:
            self.view_mode = view_mode
            self.config.default_view_mode = view_mode  # Update config
            self.rebuild_ui()
            self._rebuild_image()

    def _filter_and_sort_assets(self) -> List[str]:
        """Filter and sort assets based on current criteria"""
        filtered_assets = []

        for asset_id, asset in self.assets.items():
            # Collection filter
            if self.current_collection:
                if asset.collection_id != self.current_collection:
                    continue

            # Type filter
            if self.filter_types and asset.asset_type not in self.filter_types:
                continue

            # Search filter
            if self.search_query and not asset.matches_search(self.search_query):
                continue

            filtered_assets.append(asset_id)

        # Sort assets
        if self.config.sort_mode == AssetSortMode.NAME:
            filtered_assets.sort(key=lambda aid: self.assets[aid].get_display_name().lower(),
                                 reverse=not self.config.sort_ascending)
        elif self.config.sort_mode == AssetSortMode.TYPE:
            filtered_assets.sort(key=lambda aid: self.assets[aid].asset_type.value,
                                 reverse=not self.config.sort_ascending)
        elif self.config.sort_mode == AssetSortMode.SIZE:
            filtered_assets.sort(key=lambda aid: self.assets[aid].metadata.file_size,
                                 reverse=not self.config.sort_ascending)
        elif self.config.sort_mode == AssetSortMode.DATE_MODIFIED:
            filtered_assets.sort(key=lambda aid: self.assets[aid].metadata.date_modified,
                                 reverse=not self.config.sort_ascending)

        return filtered_assets

    def rebuild_ui(self):
        """Rebuild the UI layout"""
        if ASSET_DEBUG:
            print("Rebuilding asset browser UI...")

        # Get filtered and sorted assets
        self.visible_assets = self._filter_and_sort_assets()

        # Limit visible assets for performance
        if len(self.visible_assets) > self.config.max_visible_items:
            self.visible_assets = self.visible_assets[:self.config.max_visible_items]

        # Clear existing UI items
        self.asset_item_uis.clear()

        # Calculate layout based on view mode
        if self.view_mode == AssetViewMode.GRID:
            self._rebuild_grid_layout()
        elif self.view_mode == AssetViewMode.LIST:
            self._rebuild_list_layout()
        else:  # DETAIL
            self._rebuild_detail_layout()

        if ASSET_DEBUG:
            print(f"UI rebuilt: {len(self.visible_assets)} visible assets")

    def _rebuild_grid_layout(self):
        """Rebuild UI in grid layout"""
        # Calculate grid dimensions
        padding = GRID_ITEM_PADDING
        available_width = self.rect.width - padding * 2

        # Auto-calculate columns if configured
        if self.config.grid_columns == 0:
            min_item_width = self.config.thumbnail_size[0] + padding * 2
            columns = max(1, available_width // min_item_width)
        else:
            columns = self.config.grid_columns

        item_width = available_width // columns
        item_height = self.config.thumbnail_size[1] + 30 + padding * 2  # Thumbnail + text + padding

        # Create asset item UIs
        current_y = -self.scroll_y
        for i, asset_id in enumerate(self.visible_assets):
            row = i // columns
            col = i % columns

            x = col * item_width + padding
            y = current_y + row * item_height + padding

            rect = pygame.Rect(x, y, item_width - padding, item_height - padding)

            asset_item_ui = AssetItemUI(self.assets[asset_id], rect, self.config)
            asset_item_ui.is_selected = asset_id in self.selected_assets
            asset_item_ui.is_focused = asset_id == self.focused_asset
            asset_item_ui.is_hovered = asset_id == self.hovered_asset

            self.asset_item_uis.append(asset_item_ui)

        # Update scroll bounds
        if self.visible_assets:
            total_rows = (len(self.visible_assets) + columns - 1) // columns
            self.content_height = total_rows * item_height + padding * 2
        else:
            self.content_height = 0

        self.max_scroll = max(0, self.content_height - self.rect.height)

    def _rebuild_list_layout(self):
        """Rebuild UI in list layout"""
        item_height = LIST_ITEM_HEIGHT

        current_y = -self.scroll_y
        for i, asset_id in enumerate(self.visible_assets):
            y = current_y + i * item_height
            rect = pygame.Rect(0, y, self.rect.width, item_height)

            asset_item_ui = AssetItemUI(self.assets[asset_id], rect, self.config)
            asset_item_ui.is_selected = asset_id in self.selected_assets
            asset_item_ui.is_focused = asset_id == self.focused_asset
            asset_item_ui.is_hovered = asset_id == self.hovered_asset

            self.asset_item_uis.append(asset_item_ui)

        # Update scroll bounds
        self.content_height = len(self.visible_assets) * item_height
        self.max_scroll = max(0, self.content_height - self.rect.height)

    def _rebuild_detail_layout(self):
        """Rebuild UI in detail layout"""
        item_height = DETAIL_ITEM_HEIGHT

        current_y = -self.scroll_y
        for i, asset_id in enumerate(self.visible_assets):
            y = current_y + i * item_height
            rect = pygame.Rect(0, y, self.rect.width, item_height)

            asset_item_ui = AssetItemUI(self.assets[asset_id], rect, self.config)
            asset_item_ui.is_selected = asset_id in self.selected_assets
            asset_item_ui.is_focused = asset_id == self.focused_asset
            asset_item_ui.is_hovered = asset_id == self.hovered_asset

            self.asset_item_uis.append(asset_item_ui)

        # Update scroll bounds
        self.content_height = len(self.visible_assets) * item_height
        self.max_scroll = max(0, self.content_height - self.rect.height)

    def _rebuild_image(self):
        """Rebuild the image surface"""
        # Fill background
        bg_color = self.themed_colors.get('dark_bg', pygame.Color(40, 40, 40))
        self.image.fill(bg_color)

        # Draw asset items
        items_drawn = 0
        for asset_item_ui in self.asset_item_uis:
            # Only draw visible items
            if (asset_item_ui.rect.bottom >= 0 and
                    asset_item_ui.rect.top < self.rect.height):

                # Create subsurface for this item
                try:
                    # Calculate intersection with panel
                    visible_rect = asset_item_ui.rect.clip(pygame.Rect(0, 0, self.rect.width, self.rect.height))
                    if visible_rect.width > 0 and visible_rect.height > 0:
                        item_surface = self.image.subsurface(visible_rect)

                        # Adjust asset UI rect for drawing
                        old_rect = asset_item_ui.rect
                        asset_item_ui.rect = pygame.Rect(
                            old_rect.x - visible_rect.x,
                            old_rect.y - visible_rect.y,
                            old_rect.width,
                            old_rect.height
                        )

                        # Re-calculate layout for new rect
                        asset_item_ui.calculate_layout()

                        # Draw the asset
                        asset_item_ui.draw(item_surface, self.themed_font,
                                           self.themed_colors, self.preview_generator)

                        # Restore original rect
                        asset_item_ui.rect = old_rect
                        asset_item_ui.calculate_layout()

                        items_drawn += 1

                except (ValueError, pygame.error) as e:
                    if ASSET_DEBUG:
                        print(f"Error drawing asset item: {e}")

        # Draw grid lines in grid mode
        if self.view_mode == AssetViewMode.GRID and self.asset_item_uis:
            self._draw_grid_lines()

        # Draw border
        border_color = self.themed_colors.get('normal_border', pygame.Color(100, 100, 100))
        pygame.draw.rect(self.image, border_color, self.image.get_rect(), 1)

        if ASSET_DEBUG and items_drawn > 0:
            print(f"Image rebuilt: Drew {items_drawn} asset items")

    def _draw_grid_lines(self):
        """Draw grid lines for grid layout"""
        if not self.asset_item_uis:
            return

        grid_color = self.themed_colors.get('grid_line', pygame.Color(80, 80, 80))

        # Vertical lines
        if len(self.asset_item_uis) > 1:
            first_item = self.asset_item_uis[0]
            second_item = None

            # Find item in second column
            for item in self.asset_item_uis[1:]:
                if item.rect.x > first_item.rect.x:
                    second_item = item
                    break

            if second_item:
                column_width = second_item.rect.x - first_item.rect.x
                x = first_item.rect.x + first_item.rect.width + GRID_ITEM_PADDING // 2

                while x < self.rect.width:
                    pygame.draw.line(self.image, grid_color, (x, 0), (x, self.rect.height))
                    x += column_width

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
                consumed = self._handle_mouse_up(event.pos)

        elif event.type == pygame.MOUSEMOTION:
            relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)
            consumed = self._handle_mouse_motion(relative_pos)

        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                consumed = self._handle_scroll(event.y)

        elif event.type == pygame.KEYDOWN:
            consumed = self._handle_key_event(event)

        return consumed

    def _handle_left_click(self, pos: Tuple[int, int]) -> bool:
        """Handle left mouse click"""
        clicked_asset = self._get_asset_at_position(pos)

        if clicked_asset:
            # Check for double click
            current_time = pygame.time.get_ticks()
            is_double_click = (current_time - self.last_click_time < self.double_click_time and
                               clicked_asset == self.focused_asset)
            self.last_click_time = current_time

            # Handle selection
            keys = pygame.key.get_pressed()

            if keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]:
                # Ctrl+click: toggle selection
                if clicked_asset in self.selected_assets:
                    self.selected_assets.remove(clicked_asset)
                else:
                    self.selected_assets.add(clicked_asset)
            elif keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
                # Shift+click: range selection
                if self.focused_asset and self.focused_asset in self.visible_assets:
                    start_idx = self.visible_assets.index(self.focused_asset)
                    end_idx = self.visible_assets.index(clicked_asset)

                    start_idx, end_idx = min(start_idx, end_idx), max(start_idx, end_idx)

                    for i in range(start_idx, end_idx + 1):
                        self.selected_assets.add(self.visible_assets[i])
                else:
                    self.selected_assets = {clicked_asset}
            else:
                # Normal click: single selection
                self.selected_assets = {clicked_asset}

            self.focused_asset = clicked_asset

            # Fire selection event
            event_data = {
                'asset': self.assets[clicked_asset],
                'selected_assets': [self.assets[aid] for aid in self.selected_assets],
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_ASSET_SELECTED, event_data))

            # Fire double click event
            if is_double_click:
                event_data = {
                    'asset': self.assets[clicked_asset],
                    'ui_element': self
                }
                pygame.event.post(pygame.event.Event(UI_ASSET_DOUBLE_CLICKED, event_data))

            # Start drag if enabled
            if self.config.allow_drag_drop and len(self.selected_assets) > 0:
                self.dragging_assets = self.selected_assets.copy()
                self.drag_start_pos = pos

                event_data = {
                    'assets': [self.assets[aid] for aid in self.dragging_assets],
                    'ui_element': self
                }
                pygame.event.post(pygame.event.Event(UI_ASSET_DRAG_STARTED, event_data))

            self.rebuild_ui()
            self._rebuild_image()
            return True
        else:
            # Click on empty space: clear selection
            self.selected_assets.clear()
            self.focused_asset = None
            self.rebuild_ui()
            self._rebuild_image()
            return True

        return False

    def _handle_right_click(self, pos: Tuple[int, int]) -> bool:
        """Handle right mouse click"""
        clicked_asset = self._get_asset_at_position(pos)

        if clicked_asset:
            # Select asset if not already selected
            if clicked_asset not in self.selected_assets:
                self.selected_assets = {clicked_asset}
                self.focused_asset = clicked_asset
                self.rebuild_ui()
                self._rebuild_image()

            # Fire context menu event
            event_data = {
                'asset': self.assets[clicked_asset],
                'selected_assets': [self.assets[aid] for aid in self.selected_assets],
                'mouse_pos': pos,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_ASSET_RIGHT_CLICKED, event_data))
            return True

        return False

    def _handle_mouse_up(self, pos: Tuple[int, int]) -> bool:
        """Handle mouse up (end drag)"""
        if self.dragging_assets:
            # End drag operation
            self.dragging_assets.clear()
            self.drag_start_pos = None
            return True
        return False

    def _handle_mouse_motion(self, pos: Tuple[int, int]) -> bool:
        """Handle mouse motion"""
        new_hovered = self._get_asset_at_position(pos)

        if new_hovered != self.hovered_asset:
            self.hovered_asset = new_hovered
            self.rebuild_ui()
            self._rebuild_image()
            return True

        # Handle drag motion
        if self.dragging_assets and self.drag_start_pos:
            # Could implement drag preview here
            pass

        return False

    def _handle_scroll(self, delta: int) -> bool:
        """Handle scroll wheel"""
        if self.view_mode == AssetViewMode.GRID:
            scroll_speed = self.config.thumbnail_size[1] + 30
        else:
            scroll_speed = LIST_ITEM_HEIGHT * 3

        old_scroll = self.scroll_y
        self.scroll_y = max(0, min(self.max_scroll, self.scroll_y - delta * scroll_speed))

        if old_scroll != self.scroll_y:
            self.rebuild_ui()
            self._rebuild_image()
            return True

        return False

    def _handle_key_event(self, event: pygame.event.Event) -> bool:
        """Handle keyboard events"""
        if not self.visible_assets:
            return False

        if event.key == pygame.K_UP or event.key == pygame.K_DOWN:
            # Navigate assets
            direction = -1 if event.key == pygame.K_UP else 1

            if self.focused_asset and self.focused_asset in self.visible_assets:
                current_idx = self.visible_assets.index(self.focused_asset)
            else:
                current_idx = -1 if direction == 1 else len(self.visible_assets)

            new_idx = max(0, min(len(self.visible_assets) - 1, current_idx + direction))

            if 0 <= new_idx < len(self.visible_assets):
                self.focused_asset = self.visible_assets[new_idx]

                # Update selection if not holding ctrl
                keys = pygame.key.get_pressed()
                if not (keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]):
                    self.selected_assets = {self.focused_asset}

                self.rebuild_ui()
                self._rebuild_image()
                return True

        elif event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
            # Activate focused asset
            if self.focused_asset:
                event_data = {
                    'asset': self.assets[self.focused_asset],
                    'ui_element': self
                }
                pygame.event.post(pygame.event.Event(UI_ASSET_DOUBLE_CLICKED, event_data))
                return True

        elif event.key == pygame.K_DELETE:
            # Delete selected assets
            if self.selected_assets:
                # Fire delete event (let application handle actual deletion)
                event_data = {
                    'assets': [self.assets[aid] for aid in self.selected_assets],
                    'ui_element': self
                }
                pygame.event.post(pygame.event.Event(UI_ASSET_EXPORT_REQUESTED, event_data))
                return True

        return False

    def _get_asset_at_position(self, pos: Tuple[int, int]) -> Optional[str]:
        """Get asset at the given position"""
        for asset_item_ui in self.asset_item_uis:
            if asset_item_ui.contains_point(pos):
                return asset_item_ui.asset_item.id
        return None

    def update(self, time_delta: float):
        """Update the panel"""
        super().update(time_delta)

        # Update loading indicators
        has_loading = any(asset.is_loading_thumbnail for asset in self.assets.values())
        if has_loading:
            self._rebuild_image()

    # Public API methods
    def get_selected_assets(self) -> List[AssetItem]:
        """Get currently selected assets"""
        return [self.assets[aid] for aid in self.selected_assets if aid in self.assets]

    def select_asset(self, asset_id: str):
        """Programmatically select an asset"""
        if asset_id in self.assets:
            self.selected_assets = {asset_id}
            self.focused_asset = asset_id
            self.rebuild_ui()
            self._rebuild_image()

    def clear_selection(self):
        """Clear asset selection"""
        self.selected_assets.clear()
        self.focused_asset = None
        self.rebuild_ui()
        self._rebuild_image()

    def remove_asset(self, asset_id: str):
        """Remove an asset"""
        if asset_id in self.assets:
            # Remove from collections
            for collection in self.collections.values():
                collection.remove_asset(asset_id)

            # Remove from selection
            self.selected_assets.discard(asset_id)
            if self.focused_asset == asset_id:
                self.focused_asset = None

            # Remove asset
            del self.assets[asset_id]

            self.rebuild_ui()
            self._rebuild_image()

    def import_directory(self, directory_path: Union[str, Path], collection_name: str = None) -> List[AssetItem]:
        """Import all supported files from a directory"""
        directory_path = Path(directory_path)
        imported_assets = []

        if not directory_path.exists() or not directory_path.is_dir():
            return imported_assets

        # Create collection for directory if specified
        collection_id = None
        if collection_name:
            collection = self.add_collection(collection_name or directory_path.name)
            collection_id = collection.id

        # Scan directory
        for file_path in directory_path.rglob('*'):
            if file_path.is_file():
                try:
                    asset_type = self._detect_asset_type(file_path)
                    if asset_type != AssetType.OTHER:  # Only import recognized types
                        asset = self.add_asset(file_path, asset_type, collection_id)
                        imported_assets.append(asset)
                except Exception as e:
                    if ASSET_DEBUG:
                        print(f"Error importing {file_path}: {e}")

        return imported_assets

    def export_assets(self, asset_ids: List[str], destination: Union[str, Path]) -> bool:
        """Export assets to destination directory"""
        try:
            destination = Path(destination)
            destination.mkdir(parents=True, exist_ok=True)

            for asset_id in asset_ids:
                if asset_id in self.assets:
                    asset = self.assets[asset_id]
                    dest_file = destination / asset.file_path.name

                    # Copy file
                    import shutil
                    shutil.copy2(asset.file_path, dest_file)

            return True
        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error exporting assets: {e}")
            return False

    def save_metadata_to_file(self, file_path: Union[str, Path]):
        """Save asset metadata to JSON file"""
        try:
            data = {
                'assets': {
                    aid: {
                        'name': asset.name,
                        'file_path': str(asset.file_path),
                        'asset_type': asset.asset_type.value,
                        'metadata': asset.metadata.to_dict(),
                        'collection_id': asset.collection_id
                    }
                    for aid, asset in self.assets.items()
                },
                'collections': {
                    cid: {
                        'name': collection.name,
                        'description': collection.description,
                        'asset_ids': list(collection.asset_ids),
                        'parent_id': collection.parent_id,
                        'children_ids': list(collection.children_ids)
                    }
                    for cid, collection in self.collections.items()
                }
            }

            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error saving metadata: {e}")

    def load_metadata_from_file(self, file_path: Union[str, Path]):
        """Load asset metadata from JSON file"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            # Load assets
            for aid, asset_data in data.get('assets', {}).items():
                file_path = Path(asset_data['file_path'])
                if file_path.exists():
                    asset_type = AssetType(asset_data['asset_type'])
                    metadata = AssetMetadata.from_dict(asset_data['metadata'])

                    asset = AssetItem(
                        id=aid,
                        name=asset_data['name'],
                        file_path=file_path,
                        asset_type=asset_type,
                        metadata=metadata,
                        collection_id=asset_data.get('collection_id')
                    )

                    self.assets[aid] = asset

            # Load collections
            for cid, collection_data in data.get('collections', {}).items():
                collection = AssetCollection(
                    id=cid,
                    name=collection_data['name'],
                    description=collection_data['description'],
                    asset_ids=set(collection_data.get('asset_ids', [])),
                    parent_id=collection_data.get('parent_id'),
                    children_ids=set(collection_data.get('children_ids', []))
                )

                self.collections[cid] = collection

            self.rebuild_ui()
            self._rebuild_image()

        except Exception as e:
            if ASSET_DEBUG:
                print(f"Error loading metadata: {e}")

    def refresh(self):
        """Refresh the asset browser"""
        self.rebuild_ui()
        self._rebuild_image()


# Example theme for asset browser
ASSET_BROWSER_THEME = {
    "asset_browser": {
        "colours": {
            "dark_bg": "#2a2a2a",
            "normal_text": "#ffffff",
            "secondary_text": "#b0b0b0",
            "selected_bg": "#4a90e2",
            "hovered_bg": "#404040",
            "focused_bg": "#5aa3f0",
            "normal_border": "#646464",
            "focus_border": "#ffffff",
            "accent": "#64c864",
            "grid_line": "#505050"
        },
        "font": {
            "name": "arial",
            "size": "11",
            "bold": "0",
            "italic": "0"
        }
    }
}


def create_sample_assets(browser: AssetBrowserPanel) -> None:
    """Create sample assets for demonstration"""

    # Create some collections
    images_collection = browser.add_collection("Images", "Image assets")
    audio_collection = browser.add_collection("Audio", "Sound effects and music")
    documents_collection = browser.add_collection("Documents", "Text documents")

    # Create sample assets (these would normally be real files)
    sample_assets = [
        ("logo.png", AssetType.IMAGE, images_collection.id),
        ("background.jpg", AssetType.IMAGE, images_collection.id),
        ("character_sprite.png", AssetType.IMAGE, images_collection.id),
        ("explosion.wav", AssetType.AUDIO, audio_collection.id),
        ("background_music.ogg", AssetType.AUDIO, audio_collection.id),
        ("readme.txt", AssetType.TEXT, documents_collection.id),
        ("config.json", AssetType.SCRIPT, documents_collection.id),
        ("shader.glsl", AssetType.SCRIPT, None),
        ("font.ttf", AssetType.FONT, None),
    ]

    for name, asset_type, collection_id in sample_assets:
        # Create temporary file path (in real usage these would be actual files)
        temp_path = Path(f"temp_assets/{name}")

        # Create fake metadata
        metadata = AssetMetadata()
        metadata.file_size = hash(name) % 100000 + 1000  # Fake file size
        metadata.date_created = time.time() - (hash(name) % 10000)
        metadata.date_modified = time.time() - (hash(name) % 5000)

        if asset_type == AssetType.IMAGE:
            metadata.width = 256 + (hash(name) % 512)
            metadata.height = 256 + (hash(name[::-1]) % 512)
            metadata.format = "PNG" if name.endswith('.png') else "JPEG"

        # Add some sample tags
        if "sprite" in name:
            metadata.tags.add("character")
            metadata.tags.add("game")
        elif "background" in name:
            metadata.tags.add("environment")
        elif "explosion" in name:
            metadata.tags.add("sfx")
            metadata.tags.add("action")

        # Sample rating
        metadata.rating = hash(name) % 6  # 0-5 stars

        # Create asset item directly (since files don't exist)
        asset_id = browser.generate_asset_id(temp_path)
        asset = AssetItem(
            id=asset_id,
            name=Path(name).stem,
            file_path=temp_path,
            asset_type=asset_type,
            metadata=metadata,
            collection_id=collection_id
        )

        browser.assets[asset_id] = asset

        # Add to collection
        if collection_id and collection_id in browser.collections:
            browser.collections[collection_id].add_asset(asset_id)


def main():
    """Example demonstration of the Asset Browser Panel"""
    pygame.init()
    screen = pygame.display.set_mode((1200, 800))
    pygame.display.set_caption("Asset Browser Panel Demo")
    clock = pygame.time.Clock()

    # Create manager with theme
    manager = pygame_gui.UIManager((1200, 800), ASSET_BROWSER_THEME)

    # Configure asset browser
    config = AssetBrowserConfig()
    config.default_view_mode = AssetViewMode.GRID
    config.thumbnail_size = (128, 128)
    config.allow_multi_select = True
    config.auto_generate_thumbnails = True

    # Create asset browser
    asset_browser = AssetBrowserPanel(
        pygame.Rect(50, 50, 800, 600),
        manager,
        config,
        object_id=ObjectID(object_id='#main_browser', class_id='@asset_panel')
    )

    # Create sample assets
    create_sample_assets(asset_browser)

    # Instructions
    print("\nAsset Browser Panel Demo")
    print("\nFeatures:")
    print("- Grid, List, and Detail view modes")
    print("- Asset thumbnails and metadata")
    print("- Collections and tagging")
    print("- Search and filtering")
    print("- Multi-selection and drag/drop")
    print("- Metadata editing and import/export")

    print("\nControls:")
    print("- Click assets to select")
    print("- Ctrl+click for multi-select")
    print("- Shift+click for range select")
    print("- Double-click to activate")
    print("- Right-click for context menu")
    print("- Arrow keys to navigate")
    print("- Mouse wheel to scroll")

    print("\nPress G for Grid view, L for List view, D for Detail view")
    print("Press 1-3 to switch collections")
    print("Press S to toggle search simulation")
    print("Press C to clear selection")
    print("Press I to show asset info\n")

    # State variables
    # current_collection_idx = 0
    collections = list(asset_browser.collections.keys())
    search_active = False

    running = True
    while running:
        time_delta = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_g:
                    # Switch to grid view
                    asset_browser.set_view_mode(AssetViewMode.GRID)
                    print("Switched to Grid view")

                elif event.key == pygame.K_l:
                    # Switch to list view
                    asset_browser.set_view_mode(AssetViewMode.LIST)
                    print("Switched to List view")

                elif event.key == pygame.K_d:
                    # Switch to detail view
                    asset_browser.set_view_mode(AssetViewMode.DETAIL)
                    print("Switched to Detail view")

                elif event.key == pygame.K_1:
                    # Show all assets
                    asset_browser.set_current_collection(None)
                    print("Showing all assets")

                elif event.key == pygame.K_2:
                    # Show first collection
                    if collections:
                        asset_browser.set_current_collection(collections[0])
                        collection_name = asset_browser.collections[collections[0]].name
                        print(f"Showing collection: {collection_name}")

                elif event.key == pygame.K_3:
                    # Show second collection
                    if len(collections) > 1:
                        asset_browser.set_current_collection(collections[1])
                        collection_name = asset_browser.collections[collections[1]].name
                        print(f"Showing collection: {collection_name}")

                elif event.key == pygame.K_s:
                    # Toggle search
                    search_active = not search_active
                    if search_active:
                        asset_browser.set_search_query("background")
                        print("Search activated: 'background'")
                    else:
                        asset_browser.set_search_query("")
                        print("Search cleared")

                elif event.key == pygame.K_c:
                    # Clear selection
                    asset_browser.clear_selection()
                    print("Selection cleared")

                elif event.key == pygame.K_i:
                    # Show info about selected assets
                    selected = asset_browser.get_selected_assets()
                    if selected:
                        print(f"\nSelected Assets ({len(selected)}):")
                        for asset in selected[:5]:  # Show first 5
                            print(f"  {asset.get_display_name()}")
                            print(f"    Type: {asset.asset_type.value}")
                            print(f"    Size: {asset.get_file_size_str()}")
                            if asset.metadata.tags:
                                print(f"    Tags: {', '.join(asset.metadata.tags)}")
                            if asset.metadata.rating > 0:
                                stars = "*" * asset.metadata.rating + "_" * (5 - asset.metadata.rating)
                                print(f"    Rating: {stars}")
                            print()
                        if len(selected) > 5:
                            print(f"    ... and {len(selected) - 5} more")
                    else:
                        print("No assets selected")

            # Handle asset browser events
            elif event.type == UI_ASSET_SELECTED:
                asset = event.asset
                if ASSET_DEBUG:
                    print(f"Asset selected: {asset.get_display_name()}")

            elif event.type == UI_ASSET_DOUBLE_CLICKED:
                asset = event.asset
                print(f"Asset activated: {asset.get_display_name()}")

            elif event.type == UI_ASSET_RIGHT_CLICKED:
                asset = event.asset
                print(f"Context menu for: {asset.get_display_name()}")

            elif event.type == UI_ASSET_DRAG_STARTED:
                assets = event.assets
                print(f"Drag started with {len(assets)} asset(s)")

            elif event.type == UI_ASSET_SEARCH_UPDATED:
                query = event.query
                if ASSET_DEBUG:
                    print(f"Search updated: '{query}'")

            elif event.type == UI_ASSET_COLLECTION_CHANGED:
                collection = event.collection
                print(f"Collection changed: {collection.name}")

            # Forward events to manager
            manager.process_events(event)

        # Update
        manager.update(time_delta)

        # Draw
        screen.fill((30, 30, 30))

        # Draw some info
        font = pygame.font.Font(None, 24)
        info_text = font.render("Asset Browser Demo", True, pygame.Color(255, 255, 255))
        screen.blit(info_text, (900, 50))

        # Show current state
        y_offset = 100
        info_font = pygame.font.Font(None, 18)

        # View mode
        view_text = f"View Mode: {asset_browser.view_mode.value.title()}"
        text = info_font.render(view_text, True, pygame.Color(200, 200, 200))
        screen.blit(text, (900, y_offset))
        y_offset += 25

        # Current collection
        if asset_browser.current_collection:
            collection_name = asset_browser.collections[asset_browser.current_collection].name
            collection_text = f"Collection: {collection_name}"
        else:
            collection_text = "Collection: All Assets"
        text = info_font.render(collection_text, True, pygame.Color(200, 200, 200))
        screen.blit(text, (900, y_offset))
        y_offset += 25

        # Search query
        if asset_browser.search_query:
            search_text = f"Search: '{asset_browser.search_query}'"
            text = info_font.render(search_text, True, pygame.Color(200, 200, 200))
            screen.blit(text, (900, y_offset))
            y_offset += 25

        # Asset count
        total_assets = len(asset_browser.assets)
        visible_assets = len(asset_browser.visible_assets)
        count_text = f"Assets: {visible_assets} / {total_assets}"
        text = info_font.render(count_text, True, pygame.Color(200, 200, 200))
        screen.blit(text, (900, y_offset))
        y_offset += 25

        # Selection count
        selected_count = len(asset_browser.selected_assets)
        if selected_count > 0:
            selection_text = f"Selected: {selected_count}"
            text = info_font.render(selection_text, True, pygame.Color(100, 255, 100))
            screen.blit(text, (900, y_offset))
            y_offset += 25

        # Collections info
        y_offset += 10
        collections_text = "Collections:"
        text = info_font.render(collections_text, True, pygame.Color(255, 255, 255))
        screen.blit(text, (900, y_offset))
        y_offset += 20

        for i, (cid, collection) in enumerate(asset_browser.collections.items()):
            asset_count = len(collection.asset_ids)
            collection_info = f"  {collection.name} ({asset_count})"

            color = pygame.Color(150, 255, 150) if cid == asset_browser.current_collection else pygame.Color(180, 180,
                                                                                                             180)
            text = info_font.render(collection_info, True, color)
            screen.blit(text, (900, y_offset))
            y_offset += 18

        # Asset type distribution
        y_offset += 10
        type_counts = {}
        for asset in asset_browser.assets.values():
            type_counts[asset.asset_type] = type_counts.get(asset.asset_type, 0) + 1

        types_text = "Asset Types:"
        text = info_font.render(types_text, True, pygame.Color(255, 255, 255))
        screen.blit(text, (900, y_offset))
        y_offset += 20

        for asset_type, count in sorted(type_counts.items()):
            type_info = f"  {asset_type.value.title()}: {count}"
            text = info_font.render(type_info, True, pygame.Color(180, 180, 180))
            screen.blit(text, (900, y_offset))
            y_offset += 18

        manager.draw_ui(screen)
        pygame.display.flip()

    # Cleanup
    asset_browser.preview_generator.stop()
    pygame.quit()


if __name__ == "__main__":
    main()