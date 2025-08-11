import pygame
import pygame_gui
from pygame_gui.core import UIElement, ObjectID
from pygame_gui.core.interfaces import IContainerLikeInterface
from pygame_gui.elements import UIWindow, UILabel, UITextEntryLine, UIButton, UIDropDownMenu, UITextBox
from typing import List, Optional, Dict, Any, Union, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import math
import uuid
import json
import copy

try:
    from pygame_gui.core.interfaces.gui_font_interface import IGUIFontInterface
except ImportError:
    IGUIFontInterface = None

NODE_EDITOR_DEBUG = False

# Constants
DEFAULT_NODE_WIDTH = 120
DEFAULT_NODE_HEIGHT = 80
SOCKET_RADIUS = 8
SOCKET_SPACING = 20
CONNECTION_WIDTH = 3
GRID_SIZE = 20
MIN_ZOOM = 0.2
MAX_ZOOM = 3.0
ZOOM_STEP = 0.1
PAN_SPEED = 1.0
BEZIER_SEGMENTS = 32
NODE_HEADER_HEIGHT = 24
NODE_BORDER_WIDTH = 2
SELECTION_BORDER_WIDTH = 3

# Define custom pygame-gui events
UI_NODE_SELECTED = pygame.USEREVENT + 100
UI_NODE_DESELECTED = pygame.USEREVENT + 101
UI_NODE_MOVED = pygame.USEREVENT + 102
UI_NODE_DELETED = pygame.USEREVENT + 103
UI_NODE_ADDED = pygame.USEREVENT + 104
UI_CONNECTION_CREATED = pygame.USEREVENT + 105
UI_CONNECTION_DELETED = pygame.USEREVENT + 106
UI_NODE_DOUBLE_CLICKED = pygame.USEREVENT + 107
UI_NODE_RIGHT_CLICKED = pygame.USEREVENT + 108
UI_GRAPH_CHANGED = pygame.USEREVENT + 109
UI_NODE_PROPERTY_CHANGED = pygame.USEREVENT + 110


class SocketType(Enum):
    """Socket data types for type checking"""
    EXEC = "exec"  # Execution flow
    NUMBER = "number"  # Numeric data
    STRING = "string"  # Text data
    BOOLEAN = "boolean"  # True/false
    VECTOR = "vector"  # Vector data
    COLOR = "color"  # Color data
    OBJECT = "object"  # Generic object
    ANY = "any"  # Accepts any type


class SocketDirection(Enum):
    """Socket input/output direction"""
    INPUT = "input"
    OUTPUT = "output"


class NodeType(Enum):
    """Built-in node types"""
    BASIC = "basic"
    MATH = "math"
    LOGIC = "logic"
    CONSTANT = "constant"
    VARIABLE = "variable"
    FUNCTION = "function"
    EVENT = "event"
    CUSTOM = "custom"


@dataclass
class NodeSocket:
    """Represents an input or output socket on a node"""
    id: str
    label: str
    socket_type: SocketType
    direction: SocketDirection
    position: Tuple[int, int] = (0, 0)  # Relative to node
    connections: List['NodeConnection'] = field(default_factory=list)
    default_value: Any = None
    is_multiple: bool = False  # Can have multiple connections
    is_required: bool = False  # Must be connected
    metadata: Dict[str, Any] = field(default_factory=dict)

    def can_connect_to(self, other: 'NodeSocket') -> bool:
        """Check if this socket can connect to another"""
        if self.direction == other.direction:
            return False  # Same direction can't connect
        if self == other:
            return False  # Can't connect to self
        if not self.is_multiple and len(self.connections) > 0:
            return False  # Single connection socket already connected
        if not other.is_multiple and len(other.connections) > 0:
            return False  # Other socket already connected

        # Type compatibility check
        if self.socket_type == SocketType.ANY or other.socket_type == SocketType.ANY:
            return True
        return self.socket_type == other.socket_type

    def add_connection(self, connection: 'NodeConnection'):
        """Add a connection to this socket"""
        if connection not in self.connections:
            self.connections.append(connection)

    def remove_connection(self, connection: 'NodeConnection'):
        """Remove a connection from this socket"""
        if connection in self.connections:
            self.connections.remove(connection)

    def get_absolute_position(self, node_pos: Tuple[int, int]) -> Tuple[int, int]:
        """Get absolute position of socket"""
        return node_pos[0] + self.position[0], node_pos[1] + self.position[1]


@dataclass
class NodeConnection:
    """Represents a connection between two sockets"""
    id: str
    start_socket: NodeSocket
    end_socket: NodeSocket
    color: pygame.Color = field(default_factory=lambda: pygame.Color(255, 255, 255))
    width: int = CONNECTION_WIDTH
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def get_bezier_points(start_pos: Tuple[int, int], end_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Calculate bezier curve points for the connection"""
        # Calculate control points for smooth curves
        dx = end_pos[0] - start_pos[0]
        control_offset = max(50, int(abs(dx) * 0.5))

        # Control points for horizontal bezier
        cp1 = (start_pos[0] + control_offset, start_pos[1])
        cp2 = (end_pos[0] - control_offset, end_pos[1])

        # Generate bezier curve points
        points = []
        for i in range(BEZIER_SEGMENTS + 1):
            t = i / BEZIER_SEGMENTS

            # Cubic bezier formula
            x = (1 - t) ** 3 * start_pos[0] + 3 * (1 - t) ** 2 * t * cp1[0] + 3 * (1 - t) * t ** 2 * cp2[0] + t ** 3 * \
                end_pos[0]
            y = (1 - t) ** 3 * start_pos[1] + 3 * (1 - t) ** 2 * t * cp1[1] + 3 * (1 - t) * t ** 2 * cp2[1] + t ** 3 * \
                end_pos[1]

            points.append((int(x), int(y)))

        return points


@dataclass
class Node:
    """Base node class for the node editor"""
    id: str
    title: str
    node_type: NodeType
    position: Tuple[int, int] = (0, 0)
    size: Tuple[int, int] = (DEFAULT_NODE_WIDTH, DEFAULT_NODE_HEIGHT)
    input_sockets: List[NodeSocket] = field(default_factory=list)
    output_sockets: List[NodeSocket] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    color: pygame.Color = field(default_factory=lambda: pygame.Color(80, 80, 80))
    header_color: pygame.Color = field(default_factory=lambda: pygame.Color(60, 60, 60))
    is_selected: bool = False
    is_collapsed: bool = False
    category: str = "General"
    description: str = ""

    def __post_init__(self):
        """Initialize socket positions after creation"""
        self._update_socket_positions()

    def _update_socket_positions(self):
        """Update socket positions based on node size"""
        # Input sockets on the left
        for i, socket in enumerate(self.input_sockets):
            socket.position = (
                -SOCKET_RADIUS,
                NODE_HEADER_HEIGHT + (i + 1) * SOCKET_SPACING
            )

        # Output sockets on the right
        for i, socket in enumerate(self.output_sockets):
            socket.position = (
                self.size[0] + SOCKET_RADIUS,
                NODE_HEADER_HEIGHT + (i + 1) * SOCKET_SPACING
            )

    def add_input_socket(self, socket: NodeSocket):
        """Add an input socket"""
        socket.direction = SocketDirection.INPUT
        self.input_sockets.append(socket)
        self._update_socket_positions()

    def add_output_socket(self, socket: NodeSocket):
        """Add an output socket"""
        socket.direction = SocketDirection.OUTPUT
        self.output_sockets.append(socket)
        self._update_socket_positions()

    def remove_socket(self, socket: NodeSocket):
        """Remove a socket and its connections"""
        if socket in self.input_sockets:
            self.input_sockets.remove(socket)
        elif socket in self.output_sockets:
            self.output_sockets.remove(socket)

        # Remove all connections to this socket
        for connection in socket.connections.copy():
            socket.remove_connection(connection)
            # Also remove from the other socket
            other_socket = connection.end_socket if connection.start_socket == socket else connection.start_socket
            other_socket.remove_connection(connection)

        self._update_socket_positions()

    def get_socket_at_position(self, relative_pos: Tuple[int, int]) -> Optional[NodeSocket]:
        """Get socket at the given position relative to node"""
        for socket in self.input_sockets + self.output_sockets:
            socket_pos = socket.position
            distance = math.sqrt((relative_pos[0] - socket_pos[0]) ** 2 + (relative_pos[1] - socket_pos[1]) ** 2)
            if distance <= SOCKET_RADIUS * 2:  # Larger click area
                return socket
        return None

    def get_rect(self) -> pygame.Rect:
        """Get the node's bounding rectangle"""
        return pygame.Rect(self.position[0], self.position[1], self.size[0], self.size[1])

    def contains_point(self, pos: Tuple[int, int]) -> bool:
        """Check if point is inside the node"""
        return self.get_rect().collidepoint(pos)

    def move_to(self, new_position: Tuple[int, int]):
        """Move node to new position"""
        self.position = new_position

    def resize(self, new_size: Tuple[int, int]):
        """Resize the node"""
        self.size = new_size
        self._update_socket_positions()

    def get_all_sockets(self) -> List[NodeSocket]:
        """Get all sockets (input and output)"""
        return self.input_sockets + self.output_sockets

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the node logic (override in subclasses)"""
        # Base implementation just passes through
        outputs = {}
        for socket in self.output_sockets:
            outputs[socket.id] = inputs.get(socket.id, socket.default_value)
        return outputs


def make_json_serializable(obj):
    """Convert objects to JSON-serializable format"""
    if isinstance(obj, dict):
        return {key: make_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [make_json_serializable(item) for item in obj]
    elif isinstance(obj, (SocketType, NodeType, SocketDirection)):
        return obj.value  # Convert enum to string value
    elif isinstance(obj, pygame.Color):
        return [obj.r, obj.g, obj.b, obj.a]  # Convert color to list
    elif hasattr(obj, '__dict__'):
        # For other objects, try to convert their __dict__
        return make_json_serializable(obj.__dict__)
    else:
        return obj  # Return as-is for basic types (str, int, float, bool, None)

@dataclass
class NodeEditorConfig:
    """Configuration for the node editor"""
    # Grid settings
    show_grid: bool = True
    grid_size: int = GRID_SIZE
    grid_color: pygame.Color = field(default_factory=lambda: pygame.Color(40, 40, 40))

    # Zoom and pan
    zoom_enabled: bool = True
    pan_enabled: bool = True
    min_zoom: float = MIN_ZOOM
    max_zoom: float = MAX_ZOOM
    zoom_step: float = ZOOM_STEP
    pan_speed: float = PAN_SPEED

    # Node settings
    node_border_width: int = NODE_BORDER_WIDTH
    selection_border_width: int = SELECTION_BORDER_WIDTH
    socket_radius: int = SOCKET_RADIUS
    connection_width: int = CONNECTION_WIDTH

    # Behavior
    auto_arrange: bool = False
    snap_to_grid: bool = False
    allow_multiple_selection: bool = True
    show_connection_labels: bool = False
    show_socket_labels: bool = True

    # Performance
    max_bezier_segments: int = BEZIER_SEGMENTS
    cull_offscreen_nodes: bool = True
    cull_offscreen_connections: bool = True


class NodeGraph:
    """Container for all nodes and connections"""

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.connections: Dict[str, NodeConnection] = {}
        self.metadata: Dict[str, Any] = {}
        self.version: str = "1.0"

    def add_node(self, node: Node) -> bool:
        """Add a node to the graph"""
        if node.id in self.nodes:
            return False
        self.nodes[node.id] = node
        return True

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all its connections"""
        if node_id not in self.nodes:
            return False

        node = self.nodes[node_id]

        # Remove all connections involving this node
        connections_to_remove = []
        for connection in self.connections.values():
            if (connection.start_socket in node.get_all_sockets() or
                    connection.end_socket in node.get_all_sockets()):
                connections_to_remove.append(connection.id)

        for conn_id in connections_to_remove:
            self.remove_connection(conn_id)

        # Remove the node
        del self.nodes[node_id]
        return True

    def add_connection(self, connection: NodeConnection) -> bool:
        """Add a connection between sockets"""
        if connection.id in self.connections:
            return False

        # Check if connection is valid
        if not connection.start_socket.can_connect_to(connection.end_socket):
            return False

        # Add connection to sockets
        connection.start_socket.add_connection(connection)
        connection.end_socket.add_connection(connection)

        self.connections[connection.id] = connection
        return True

    def remove_connection(self, connection_id: str) -> bool:
        """Remove a connection"""
        if connection_id not in self.connections:
            return False

        connection = self.connections[connection_id]

        # Remove from sockets
        connection.start_socket.remove_connection(connection)
        connection.end_socket.remove_connection(connection)

        del self.connections[connection_id]
        return True

    def get_node_by_id(self, node_id: str) -> Optional[Node]:
        """Get node by ID"""
        return self.nodes.get(node_id)

    def get_connection_by_id(self, connection_id: str) -> Optional[NodeConnection]:
        """Get connection by ID"""
        return self.connections.get(connection_id)

    def get_nodes_in_rect(self, rect: pygame.Rect) -> List[Node]:
        """Get all nodes that intersect with the given rectangle"""
        result = []
        for node in self.nodes.values():
            if node.get_rect().colliderect(rect):
                result.append(node)
        return result

    def clear(self):
        """Clear all nodes and connections"""
        self.nodes.clear()
        self.connections.clear()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to dictionary"""
        return {
            "version": self.version,
            "metadata": self.metadata,
            "nodes": {
                node_id: {
                    "id": node.id,
                    "title": node.title,
                    "node_type": node.node_type.value,
                    "position": node.position,
                    "size": node.size,
                    "properties": node.properties,
                    "metadata": node.metadata,
                    "category": node.category,
                    "description": node.description,
                    "color": [node.color.r, node.color.g, node.color.b, node.color.a],
                    "header_color": [node.header_color.r, node.header_color.g, node.header_color.b,
                                     node.header_color.a],
                    "input_sockets": [
                        {
                            "id": s.id,
                            "label": s.label,
                            "socket_type": s.socket_type.value,
                            "default_value": s.default_value,
                            "is_multiple": s.is_multiple,
                            "is_required": s.is_required,
                            "metadata": s.metadata
                        } for s in node.input_sockets
                    ],
                    "output_sockets": [
                        {
                            "id": s.id,
                            "label": s.label,
                            "socket_type": s.socket_type.value,
                            "default_value": s.default_value,
                            "is_multiple": s.is_multiple,
                            "is_required": s.is_required,
                            "metadata": s.metadata
                        } for s in node.output_sockets
                    ]
                } for node_id, node in self.nodes.items()
            },
            "connections": {
                conn_id: {
                    "id": conn.id,
                    "start_node": next(n.id for n in self.nodes.values() if conn.start_socket in n.get_all_sockets()),
                    "start_socket": conn.start_socket.id,
                    "end_node": next(n.id for n in self.nodes.values() if conn.end_socket in n.get_all_sockets()),
                    "end_socket": conn.end_socket.id,
                    "color": [conn.color.r, conn.color.g, conn.color.b, conn.color.a],
                    "width": conn.width,
                    "metadata": conn.metadata
                } for conn_id, conn in self.connections.items()
            }
        }


class NodeRenderer:
    """Handles rendering of nodes"""

    def __init__(self, config: NodeEditorConfig):
        self.config = config

    def draw_node(self, surface: pygame.Surface, node: Node, font: Any, colors: Dict[str, pygame.Color],
                  zoom: float = 1.0, offset: Tuple[int, int] = (0, 0)):
        """Draw a single node"""
        # Calculate screen position
        screen_x = int((node.position[0] + offset[0]) * zoom)
        screen_y = int((node.position[1] + offset[1]) * zoom)
        screen_width = int(node.size[0] * zoom)
        screen_height = int(node.size[1] * zoom)

        node_rect = pygame.Rect(screen_x, screen_y, screen_width, screen_height)
        header_rect = pygame.Rect(screen_x, screen_y, screen_width, int(NODE_HEADER_HEIGHT * zoom))

        # Node body
        body_color = node.color
        if node.is_selected:
            # Draw selection border
            selection_rect = node_rect.inflate(self.config.selection_border_width * 2,
                                               self.config.selection_border_width * 2)
            pygame.draw.rect(surface, colors.get('selection', pygame.Color(255, 255, 0)),
                             selection_rect, self.config.selection_border_width)

        pygame.draw.rect(surface, body_color, node_rect)
        pygame.draw.rect(surface, colors.get('node_border', pygame.Color(100, 100, 100)),
                         node_rect, max(1, int(self.config.node_border_width * zoom)))

        # Node header
        pygame.draw.rect(surface, node.header_color, header_rect)
        pygame.draw.line(surface, colors.get('node_border', pygame.Color(100, 100, 100)),
                         (header_rect.left, header_rect.bottom),
                         (header_rect.right, header_rect.bottom), max(1, int(zoom)))

        # Node title
        if zoom > 0.5:  # Only draw text if the zoom is reasonable
            self._draw_node_title(surface, node, header_rect, font, colors, zoom)

        # Draw sockets
        if zoom > 0.3:  # Only draw sockets if the zoom is reasonable
            self._draw_node_sockets(surface, node, screen_x, screen_y, colors, zoom)

    @staticmethod
    def _draw_node_title(surface: pygame.Surface, node: Node, header_rect: pygame.Rect,
                         font: Any, colors: Dict[str, pygame.Color], zoom: float):
        """Draw node title text"""
        try:
            text_color = colors.get('node_text', pygame.Color(255, 255, 255))

            # Scale font if needed (simplified approach)
            title_text = node.title
            if zoom < 0.8:
                # Truncate title for small zoom
                max_chars = max(3, int(len(node.title) * zoom))
                title_text = node.title[:max_chars]
                if len(title_text) < len(node.title):
                    title_text += "..."

            if hasattr(font, 'render_premul'):
                text_surface = font.render_premul(title_text, text_color)
            else:
                text_surface = font.render(title_text, True, text_color)

            # Scale text surface if zoom is very different
            if zoom != 1.0 and zoom > 0.5:
                scaled_width = max(1, int(text_surface.get_width() * zoom))
                scaled_height = max(1, int(text_surface.get_height() * zoom))
                text_surface = pygame.transform.scale(text_surface, (scaled_width, scaled_height))

            # Center text in header
            text_rect = text_surface.get_rect()
            text_rect.center = header_rect.center

            # Clip to header rect
            surface.set_clip(header_rect)
            surface.blit(text_surface, text_rect)
            surface.set_clip(None)

        except Exception as e:
            if NODE_EDITOR_DEBUG:
                print(f"Error drawing node title: {e}")

    def _draw_node_sockets(self, surface: pygame.Surface, node: Node, screen_x: int, screen_y: int,
                           colors: Dict[str, pygame.Color], zoom: float):
        """Draw node sockets"""
        socket_radius = max(2, int(self.config.socket_radius * zoom))

        # Socket colors by type
        socket_colors = {
            SocketType.EXEC: colors.get('socket_exec', pygame.Color(255, 255, 255)),
            SocketType.NUMBER: colors.get('socket_number', pygame.Color(100, 200, 100)),
            SocketType.STRING: colors.get('socket_string', pygame.Color(200, 100, 100)),
            SocketType.BOOLEAN: colors.get('socket_boolean', pygame.Color(200, 200, 100)),
            SocketType.VECTOR: colors.get('socket_vector', pygame.Color(100, 100, 200)),
            SocketType.COLOR: colors.get('socket_color', pygame.Color(200, 100, 200)),
            SocketType.OBJECT: colors.get('socket_object', pygame.Color(150, 150, 150)),
            SocketType.ANY: colors.get('socket_any', pygame.Color(100, 100, 100)),
        }

        # Draw all sockets
        for socket in node.input_sockets + node.output_sockets:
            socket_screen_x = screen_x + int(socket.position[0] * zoom)
            socket_screen_y = screen_y + int(socket.position[1] * zoom)

            socket_color = socket_colors.get(socket.socket_type, pygame.Color(128, 128, 128))

            # Draw socket circle
            pygame.draw.circle(surface, socket_color,
                               (socket_screen_x, socket_screen_y), socket_radius)
            pygame.draw.circle(surface, colors.get('socket_border', pygame.Color(200, 200, 200)),
                               (socket_screen_x, socket_screen_y), socket_radius, max(1, int(zoom)))

            # Draw connection indicator if connected
            if socket.connections:
                inner_radius = max(1, socket_radius - 2)
                pygame.draw.circle(surface, colors.get('socket_connected', pygame.Color(255, 255, 0)),
                                   (socket_screen_x, socket_screen_y), inner_radius)


class ConnectionRenderer:
    """Handles rendering of connections"""

    def __init__(self, config: NodeEditorConfig):
        self.config = config

    @staticmethod
    def draw_connection(surface: pygame.Surface, connection: NodeConnection,
                        start_pos: Tuple[int, int], end_pos: Tuple[int, int],
                        colors: Dict[str, pygame.Color], zoom: float = 1.0):
        """Draw a connection between two sockets"""
        # Scale connection width with zoom
        scaled_width = max(1, int(connection.width * zoom))

        # Get bezier curve points
        bezier_points = connection.get_bezier_points(start_pos, end_pos)

        # Draw connection line
        if len(bezier_points) >= 2:
            try:
                # Draw main connection
                pygame.draw.lines(surface, connection.color, False, bezier_points, scaled_width)

                # Draw connection shadow/outline for better visibility
                if scaled_width > 1:
                    shadow_color = pygame.Color(0, 0, 0, 128)
                    pygame.draw.lines(surface, shadow_color, False, bezier_points, scaled_width + 2)
                    pygame.draw.lines(surface, connection.color, False, bezier_points, scaled_width)

            except Exception as e:
                if NODE_EDITOR_DEBUG:
                    print(f"Error drawing connection: {e}")
                # Fallback to simple line
                pygame.draw.line(surface, connection.color, start_pos, end_pos, scaled_width)

    def draw_temp_connection(self, surface: pygame.Surface, start_pos: Tuple[int, int],
                             end_pos: Tuple[int, int], color: pygame.Color, zoom: float = 1.0):
        """Draw a temporary connection while dragging"""
        scaled_width = max(1, int(self.config.connection_width * zoom))

        # Create temporary connection for bezier calculation
        temp_connection = NodeConnection("temp", None, None, color, scaled_width)
        bezier_points = temp_connection.get_bezier_points(start_pos, end_pos)

        if len(bezier_points) >= 2:
            try:
                # Draw with alpha for temporary effect
                temp_color = pygame.Color(color.r, color.g, color.b, 128)
                pygame.draw.lines(surface, temp_color, False, bezier_points, scaled_width)
            except:
                # Fallback
                pygame.draw.line(surface, color, start_pos, end_pos, scaled_width)


class NodeEditorPanel(UIElement):
    """Main node editor panel widget"""

    def __init__(self, relative_rect: pygame.Rect,
                 manager: pygame_gui.UIManager,
                 config: NodeEditorConfig = None,
                 container: IContainerLikeInterface = None,
                 object_id: Union[ObjectID, str, None] = None,
                 anchors: Dict[str, str] = None):

        # Handle object_id properly
        if isinstance(object_id, ObjectID):
            self._object_id = object_id
        elif isinstance(object_id, str):
            self._object_id = ObjectID(object_id=object_id, class_id=None)
        else:
            self._object_id = ObjectID(object_id='#node_editor', class_id=None)

        super().__init__(relative_rect, manager, container,
                         starting_height=1, layer_thickness=1,
                         anchors=anchors, object_id=self._object_id)

        self.config = config or NodeEditorConfig()
        self.graph = NodeGraph()

        # Renderers
        self.node_renderer = NodeRenderer(self.config)
        self.connection_renderer = ConnectionRenderer(self.config)

        # View state
        self.zoom = 1.0
        self.pan_offset = [0, 0]  # Use list for mutability
        self.grid_offset = [0, 0]

        # Selection state
        self.selected_nodes: Set[str] = set()
        self.selection_rect: Optional[pygame.Rect] = None
        self.selection_start: Optional[Tuple[int, int]] = None

        # Connection state
        self.selected_connections: Set[str] = set()
        self.hovered_connection: Optional[str] = None

        # Interaction state
        self.is_panning = False
        self.is_selecting = False
        self.is_dragging_nodes = False
        self.is_connecting = False
        self.drag_start: Optional[Tuple[int, int]] = None
        self.last_mouse_pos: Optional[Tuple[int, int]] = None
        self.hovered_node: Optional[str] = None
        self.hovered_socket: Optional[Tuple[str, str]] = None  # (node_id, socket_id)

        # Connection state
        self.connecting_from_socket: Optional[Tuple[str, str]] = None  # (node_id, socket_id)
        self.temp_connection_end: Optional[Tuple[int, int]] = None

        # Keyboard state
        self.is_focused = False
        self.keys_pressed: Set[int] = set()

        # Performance optimization
        self.viewport_rect = pygame.Rect(0, 0, 0, 0)
        self.visible_nodes: Set[str] = set()
        self.visible_connections: Set[str] = set()

        # Theme data
        self._update_theme_data()

        # Create the image surface
        self.image = pygame.Surface(self.rect.size).convert()

        # Initialize
        self.update_viewport()
        self.rebuild_image()

    def _get_connection_at_screen_pos(self, screen_pos: Tuple[int, int], tolerance: int = 8) -> Optional[str]:
        """Get connection at screen position using distance to bezier curve"""
        for conn_id in self.visible_connections:
            connection = self.graph.connections[conn_id]

            # Get socket positions
            start_node = next((n for n in self.graph.nodes.values()
                               if connection.start_socket in n.get_all_sockets()), None)
            end_node = next((n for n in self.graph.nodes.values()
                             if connection.end_socket in n.get_all_sockets()), None)

            if start_node and end_node:
                start_abs_pos = connection.start_socket.get_absolute_position(start_node.position)
                end_abs_pos = connection.end_socket.get_absolute_position(end_node.position)

                # Convert to screen space
                start_screen = (
                    int((start_abs_pos[0] + self.pan_offset[0]) * self.zoom),
                    int((start_abs_pos[1] + self.pan_offset[1]) * self.zoom)
                )
                end_screen = (
                    int((end_abs_pos[0] + self.pan_offset[0]) * self.zoom),
                    int((end_abs_pos[1] + self.pan_offset[1]) * self.zoom)
                )

                # Get bezier points
                bezier_points = connection.get_bezier_points(start_screen, end_screen)

                # Check distance to bezier curve segments
                min_distance = float('inf')
                for i in range(len(bezier_points) - 1):
                    distance = self._point_to_line_distance(
                        screen_pos, bezier_points[i], bezier_points[i + 1]
                    )
                    min_distance = min(min_distance, distance)

                if min_distance <= tolerance:
                    return conn_id

        return None

    @staticmethod
    def _point_to_line_distance(point: Tuple[int, int],
                                line_start: Tuple[int, int], line_end: Tuple[int, int]) -> float:
        """Calculate distance from point to line segment"""
        x0, y0 = point
        x1, y1 = line_start
        x2, y2 = line_end

        # Vector from line_start to line_end
        dx = x2 - x1
        dy = y2 - y1

        # If line is just a point
        if dx == 0 and dy == 0:
            return math.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2)

        # Calculate parameter t for closest point on the line
        t = max(0, min(1, int(((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy))))

        # Find the closest point on the line segment
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy

        # Return distance to the closest point
        return math.sqrt((x0 - closest_x) ** 2 + (y0 - closest_y) ** 2)

    def _update_theme_data(self):
        """Update theme-dependent data"""
        try:
            self.themed_colors = {}

            color_mappings = {
                'background': pygame.Color(30, 30, 30),
                'grid': pygame.Color(40, 40, 40),
                'node_border': pygame.Color(100, 100, 100),
                'node_text': pygame.Color(255, 255, 255),
                'selection': pygame.Color(255, 255, 0),
                'selection_rect': pygame.Color(100, 150, 255, 64),
                'socket_border': pygame.Color(200, 200, 200),
                'socket_connected': pygame.Color(255, 255, 0),
                'socket_exec': pygame.Color(255, 255, 255),
                'socket_number': pygame.Color(100, 200, 100),
                'socket_string': pygame.Color(200, 100, 100),
                'socket_boolean': pygame.Color(200, 200, 100),
                'socket_vector': pygame.Color(100, 100, 200),
                'socket_color': pygame.Color(200, 100, 200),
                'socket_object': pygame.Color(150, 150, 150),
                'socket_any': pygame.Color(100, 100, 100),
                'connection_default': pygame.Color(200, 200, 200),
                'temp_connection': pygame.Color(255, 255, 255, 128),
            }

            theme = self.ui_manager.get_theme()

            for color_id, default_color in color_mappings.items():
                try:
                    if hasattr(theme, 'get_colour_or_gradient'):
                        color = theme.get_colour_or_gradient(color_id, ['node_editor'])
                        self.themed_colors[color_id] = color if color else default_color
                    else:
                        self.themed_colors[color_id] = default_color
                except Exception:
                    self.themed_colors[color_id] = default_color

            # Get themed font
            try:
                if hasattr(theme, 'get_font'):
                    self.themed_font = theme.get_font(['node_editor'])
                else:
                    raise Exception("No font method")
            except Exception:
                try:
                    self.themed_font = pygame.font.SysFont('Arial', 12)
                except:
                    self.themed_font = pygame.font.Font(None, 12)

        except Exception as e:
            if NODE_EDITOR_DEBUG:
                print(f"Error getting theme data: {e}")
            # Complete fallback
            self.themed_colors = {
                'background': pygame.Color(30, 30, 30),
                'grid': pygame.Color(40, 40, 40),
                'node_border': pygame.Color(100, 100, 100),
                'node_text': pygame.Color(255, 255, 255),
                'selection': pygame.Color(255, 255, 0),
                'selection_rect': pygame.Color(100, 150, 255, 64),
                'socket_border': pygame.Color(200, 200, 200),
                'socket_connected': pygame.Color(255, 255, 0),
                'socket_exec': pygame.Color(255, 255, 255),
                'socket_number': pygame.Color(100, 200, 100),
                'socket_string': pygame.Color(200, 100, 100),
                'socket_boolean': pygame.Color(200, 200, 100),
                'socket_vector': pygame.Color(100, 100, 200),
                'socket_color': pygame.Color(200, 100, 200),
                'socket_object': pygame.Color(150, 150, 150),
                'socket_any': pygame.Color(100, 100, 100),
                'connection_default': pygame.Color(200, 200, 200),
                'temp_connection': pygame.Color(255, 255, 255, 128),
            }
            try:
                self.themed_font = pygame.font.SysFont('Arial', 12)
            except:
                self.themed_font = pygame.font.Font(None, 12)

    def rebuild_from_changed_theme_data(self):
        """Called when theme data changes"""
        self._update_theme_data()
        self.rebuild_image()

    def update_viewport(self):
        """Update viewport rectangle for culling"""
        # Calculate world space viewport
        zoom_inv = 1.0 / self.zoom if self.zoom > 0 else 1.0
        viewport_padding = 100  # Extra padding for smooth scrolling

        self.viewport_rect = pygame.Rect(
            int((-self.pan_offset[0] - viewport_padding) * zoom_inv),
            int((-self.pan_offset[1] - viewport_padding) * zoom_inv),
            int((self.rect.width + viewport_padding * 2) * zoom_inv),
            int((self.rect.height + viewport_padding * 2) * zoom_inv)
        )

        # Update visible nodes and connections for culling
        if self.config.cull_offscreen_nodes:
            self.visible_nodes.clear()
            for node_id, node in self.graph.nodes.items():
                if self.viewport_rect.colliderect(node.get_rect()):
                    self.visible_nodes.add(node_id)
        else:
            self.visible_nodes = set(self.graph.nodes.keys())

        if self.config.cull_offscreen_connections:
            self.visible_connections.clear()
            for conn_id, connection in self.graph.connections.items():
                # Check if connection endpoints are in viewport
                start_node = next((n for n in self.graph.nodes.values()
                                   if connection.start_socket in n.get_all_sockets()), None)
                end_node = next((n for n in self.graph.nodes.values()
                                 if connection.end_socket in n.get_all_sockets()), None)

                if start_node and end_node:
                    # Simple check: if either node is visible, show connection
                    if (start_node.id in self.visible_nodes or
                            end_node.id in self.visible_nodes):
                        self.visible_connections.add(conn_id)
        else:
            self.visible_connections = set(self.graph.connections.keys())

    def rebuild_image(self):
        """Rebuild the image surface"""
        # Clear background
        bg_color = self.themed_colors.get('background', pygame.Color(30, 30, 30))
        self.image.fill(bg_color)

        # Draw grid
        if self.config.show_grid:
            self._draw_grid()

        # Draw connections first (behind nodes)
        self._draw_connections()

        # Draw nodes
        self._draw_nodes()

        # Draw temporary connection
        if self.is_connecting and self.temp_connection_end:
            self._draw_temp_connection()

        # Draw selection rectangle
        if self.selection_rect:
            self._draw_selection_rect()

        # Draw border
        border_color = self.themed_colors.get('node_border', pygame.Color(100, 100, 100))
        pygame.draw.rect(self.image, border_color, self.image.get_rect(), 1)

        # Draw focus indicator
        if self.is_focused:
            focus_color = self.themed_colors.get('selection', pygame.Color(255, 255, 0))
            pygame.draw.rect(self.image, focus_color, self.image.get_rect(), 2)

    def _draw_grid(self):
        """Draw the background grid"""
        grid_color = self.themed_colors.get('grid', pygame.Color(40, 40, 40))

        # Calculate grid spacing in screen space
        grid_spacing = int(self.config.grid_size * self.zoom)

        # Only draw grid if spacing is reasonable
        if grid_spacing < 4:
            return

        # Calculate grid offset
        grid_offset_x = int(self.pan_offset[0] % grid_spacing)
        grid_offset_y = int(self.pan_offset[1] % grid_spacing)

        # Draw vertical lines
        x = grid_offset_x
        while x < self.rect.width:
            pygame.draw.line(self.image, grid_color, (x, 0), (x, self.rect.height))
            x += grid_spacing

        # Draw horizontal lines
        y = grid_offset_y
        while y < self.rect.height:
            pygame.draw.line(self.image, grid_color, (0, y), (self.rect.width, y))
            y += grid_spacing

    def _draw_nodes(self):
        """Draw all visible nodes"""
        for node_id in self.visible_nodes:
            node = self.graph.nodes[node_id]
            node.is_selected = node_id in self.selected_nodes
            self.node_renderer.draw_node(self.image, node, self.themed_font,
                                         self.themed_colors, self.zoom, self.pan_offset)

    def _draw_connections(self):
        """Draw all visible connections"""
        for conn_id in self.visible_connections:
            connection = self.graph.connections[conn_id]

            # Get socket positions
            start_node = next((n for n in self.graph.nodes.values()
                               if connection.start_socket in n.get_all_sockets()), None)
            end_node = next((n for n in self.graph.nodes.values()
                             if connection.end_socket in n.get_all_sockets()), None)

            if start_node and end_node:
                start_abs_pos = connection.start_socket.get_absolute_position(start_node.position)
                end_abs_pos = connection.end_socket.get_absolute_position(end_node.position)

                # Convert to screen space
                start_screen = (
                    int((start_abs_pos[0] + self.pan_offset[0]) * self.zoom),
                    int((start_abs_pos[1] + self.pan_offset[1]) * self.zoom)
                )
                end_screen = (
                    int((end_abs_pos[0] + self.pan_offset[0]) * self.zoom),
                    int((end_abs_pos[1] + self.pan_offset[1]) * self.zoom)
                )

                # Draw selection highlight for selected connections
                if conn_id in self.selected_connections:
                    # Draw thicker line behind for selection
                    selection_color = self.themed_colors.get('selection', pygame.Color(255, 255, 0))
                    temp_connection = NodeConnection("temp", None, None, selection_color, connection.width + 4)
                    self.connection_renderer.draw_connection(self.image, temp_connection,
                                                             start_screen, end_screen,
                                                             self.themed_colors, self.zoom)

                # Draw normal connection
                self.connection_renderer.draw_connection(self.image, connection,
                                                         start_screen, end_screen,
                                                         self.themed_colors, self.zoom)

    def _draw_temp_connection(self):
        """Draw temporary connection while connecting"""
        if not (self.connecting_from_socket and self.temp_connection_end):
            return

        node_id, socket_id = self.connecting_from_socket
        node = self.graph.get_node_by_id(node_id)
        if not node:
            return

        socket = next((s for s in node.get_all_sockets() if s.id == socket_id), None)
        if not socket:
            return

        start_abs_pos = socket.get_absolute_position(node.position)
        start_screen = (
            int((start_abs_pos[0] + self.pan_offset[0]) * self.zoom),
            int((start_abs_pos[1] + self.pan_offset[1]) * self.zoom)
        )

        temp_color = self.themed_colors.get('temp_connection', pygame.Color(255, 255, 255, 128))
        self.connection_renderer.draw_temp_connection(self.image, start_screen,
                                                      self.temp_connection_end, temp_color, self.zoom)

    def _draw_selection_rect(self):
        """Draw selection rectangle"""
        if not self.selection_rect:
            return

        selection_color = self.themed_colors.get('selection_rect', pygame.Color(100, 150, 255, 64))

        # Create a surface with per-pixel alpha for the selection rectangle
        try:
            selection_surface = pygame.Surface((self.selection_rect.width, self.selection_rect.height), pygame.SRCALPHA)
            selection_surface.fill(selection_color)
            self.image.blit(selection_surface, self.selection_rect.topleft)

            # Draw border
            border_color = self.themed_colors.get('selection', pygame.Color(255, 255, 0))
            pygame.draw.rect(self.image, border_color, self.selection_rect, 2)
        except Exception as e:
            if NODE_EDITOR_DEBUG:
                print(f"Error drawing selection rect: {e}")

    def screen_to_world(self, screen_pos: Tuple[int, int]) -> Tuple[int, int]:
        """Convert screen coordinates to world coordinates"""
        return (
            int((screen_pos[0] - self.pan_offset[0]) / self.zoom),
            int((screen_pos[1] - self.pan_offset[1]) / self.zoom)
        )

    def world_to_screen(self, world_pos: Tuple[int, int]) -> Tuple[int, int]:
        """Convert world coordinates to screen coordinates"""
        return (
            int((world_pos[0] + self.pan_offset[0]) * self.zoom),
            int((world_pos[1] + self.pan_offset[1]) * self.zoom)
        )

    def process_event(self, event: pygame.event.Event) -> bool:
        """Process pygame events"""
        consumed = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.is_focused = True
                relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)

                if event.button == 1:  # Left click
                    consumed = self._handle_left_click(relative_pos)
                elif event.button == 2:  # Middle click
                    consumed = self._handle_middle_click(relative_pos)
                elif event.button == 3:  # Right click
                    consumed = self._handle_right_click(relative_pos)
            else:
                self.is_focused = False

        elif event.type == pygame.MOUSEBUTTONUP:
            relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)

            if event.button == 1:  # Left click
                consumed = self._handle_left_release(relative_pos)
            elif event.button == 2:  # Middle click
                consumed = self._handle_middle_release(relative_pos)

        elif event.type == pygame.MOUSEMOTION:
            relative_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)
            consumed = self._handle_mouse_motion(relative_pos)

        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                consumed = self._handle_scroll(event.y)

        elif event.type == pygame.KEYDOWN and self.is_focused:
            consumed = self._handle_key_down(event)

        elif event.type == pygame.KEYUP and self.is_focused:
            consumed = self._handle_key_up(event)

        return consumed

    def _handle_left_click(self, pos: Tuple[int, int]) -> bool:
        """Handle left mouse button down"""
        world_pos = self.screen_to_world(pos)

        # Check for socket click first
        socket_info = self._get_socket_at_screen_pos(pos)
        if socket_info:
            node_id, socket = socket_info
            self._start_connection(node_id, socket.id)
            return True

        # Check for connection click
        clicked_connection = self._get_connection_at_screen_pos(pos)
        if clicked_connection:
            # Handle connection selection
            if pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]:
                # Toggle selection
                if clicked_connection in self.selected_connections:
                    self.selected_connections.remove(clicked_connection)
                else:
                    self.selected_connections.add(clicked_connection)
            else:
                # Single selection - clear other selections first
                self.selected_connections.clear()
                self.selected_connections.add(clicked_connection)

            # Clear node selection
            if self.selected_nodes:
                old_selection = self.selected_nodes.copy()
                self.selected_nodes.clear()
                for node_id in old_selection:
                    self.fire_node_deselected(node_id)

            self.rebuild_image()  # Refresh display
            return True

        # Check for node click
        clicked_node_id = self._get_node_at_world_pos(world_pos)
        if clicked_node_id:
            # Clear connection selection when selecting nodes
            if self.selected_connections:
                self.selected_connections.clear()

            # Handle node selection
            if pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]:
                # Toggle selection
                if clicked_node_id in self.selected_nodes:
                    self.selected_nodes.remove(clicked_node_id)
                    self.fire_node_deselected(clicked_node_id)
                else:
                    self.selected_nodes.add(clicked_node_id)
                    self.fire_node_selected(clicked_node_id)
            else:
                # Single selection
                if clicked_node_id not in self.selected_nodes:
                    old_selection = self.selected_nodes.copy()
                    self.selected_nodes.clear()
                    for node_id in old_selection:
                        self.fire_node_deselected(node_id)

                    self.selected_nodes.add(clicked_node_id)
                    self.fire_node_selected(clicked_node_id)

            # Start dragging
            self.is_dragging_nodes = True
            self.drag_start = world_pos

            self.rebuild_image()  # Refresh display
            return True

        # Start selection rectangle
        self.is_selecting = True
        self.selection_start = pos
        self.selection_rect = pygame.Rect(pos[0], pos[1], 0, 0)

        # Clear selection if not holding ctrl
        if not (pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]):
            old_node_selection = self.selected_nodes.copy()
            self.selected_nodes.clear()
            self.selected_connections.clear()  # Also clear connections
            for node_id in old_node_selection:
                self.fire_node_deselected(node_id)

            self.rebuild_image()  # Refresh display

        return True

    def _handle_left_release(self, pos: Tuple[int, int]) -> bool:
        """Handle left mouse button up"""
        consumed = False

        if self.is_connecting:
            # Try to complete connection
            socket_info = self._get_socket_at_screen_pos(pos)
            if socket_info:
                target_node_id, target_socket = socket_info
                self._complete_connection(target_node_id, target_socket.id)
            # Both _complete_connection and _cancel_connection now handle their own refreshes
            self._cancel_connection()
            consumed = True
            self.update_viewport()
            self.rebuild_image()

        elif self.is_dragging_nodes:
            # Stop dragging nodes
            if self.selected_nodes and self.drag_start:
                for node_id in self.selected_nodes:
                    self.fire_node_moved(node_id)

            self.is_dragging_nodes = False
            self.drag_start = None
            consumed = True

        elif self.is_selecting:
            # Complete selection
            if self.selection_rect:
                self._complete_selection()

            self.is_selecting = False
            self.selection_start = None
            self.selection_rect = None
            self.rebuild_image()  # Refresh display after selection
            consumed = True

        return consumed

    def _handle_middle_click(self, pos: Tuple[int, int]) -> bool:
        """Handle middle mouse button down (pan)"""
        if self.config.pan_enabled:
            self.is_panning = True
            self.last_mouse_pos = pos
            return True
        return False

    def _handle_middle_release(self, pos: Tuple[int, int]) -> bool:
        """Handle middle mouse button up"""
        if self.is_panning:
            self.is_panning = False
            self.last_mouse_pos = None
            return True
        return False

    def _handle_right_click(self, pos: Tuple[int, int]) -> bool:
        """Handle right mouse button down"""
        world_pos = self.screen_to_world(pos)

        # Check for connection right-click first
        clicked_connection = self._get_connection_at_screen_pos(pos)
        if clicked_connection:
            event_data = {
                'ui_element': self,
                'connection_id': clicked_connection,
                'screen_pos': pos
            }
            pygame.event.post(pygame.event.Event(UI_NODE_RIGHT_CLICKED, event_data))
            return True

        # Check for node right-click
        clicked_node_id = self._get_node_at_world_pos(world_pos)
        if clicked_node_id:
            event_data = {
                'ui_element': self,
                'node_id': clicked_node_id,
                'screen_pos': pos
            }
            pygame.event.post(pygame.event.Event(UI_NODE_RIGHT_CLICKED, event_data))
            return True

        # Fire general right-click event for context menu (background)
        event_data = {
            'ui_element': self,
            'world_pos': world_pos,
            'screen_pos': pos
        }
        pygame.event.post(pygame.event.Event(UI_NODE_RIGHT_CLICKED, event_data))
        return True

    def _handle_mouse_motion(self, pos: Tuple[int, int]) -> bool:
        """Handle mouse motion"""
        consumed = False

        if self.is_panning and self.last_mouse_pos:
            # Pan the view
            dx = pos[0] - self.last_mouse_pos[0]
            dy = pos[1] - self.last_mouse_pos[1]
            self.pan_offset[0] += dx * self.config.pan_speed
            self.pan_offset[1] += dy * self.config.pan_speed
            self.last_mouse_pos = pos
            self.update_viewport()
            self.rebuild_image()
            consumed = True

        elif self.is_dragging_nodes and self.drag_start:
            # Drag selected nodes
            world_pos = self.screen_to_world(pos)
            dx = world_pos[0] - self.drag_start[0]
            dy = world_pos[1] - self.drag_start[1]

            for node_id in self.selected_nodes:
                node = self.graph.get_node_by_id(node_id)
                if node:
                    new_pos = (node.position[0] + dx, node.position[1] + dy)
                    if self.config.snap_to_grid:
                        new_pos = self._snap_to_grid(new_pos)
                    node.move_to(new_pos)

            self.drag_start = world_pos
            self.update_viewport()
            self.rebuild_image()
            consumed = True

        elif self.is_selecting and self.selection_start:
            # Update selection rectangle
            self.selection_rect = pygame.Rect(
                min(self.selection_start[0], pos[0]),
                min(self.selection_start[1], pos[1]),
                abs(pos[0] - self.selection_start[0]),
                abs(pos[1] - self.selection_start[1])
            )
            self.rebuild_image()
            consumed = True

        elif self.is_connecting:
            # Update temporary connection
            self.temp_connection_end = pos
            self.rebuild_image()
            consumed = True

        else:
            # Update hover state
            world_pos = self.screen_to_world(pos)
            new_hovered_node = self._get_node_at_world_pos(world_pos)

            if new_hovered_node != self.hovered_node:
                self.hovered_node = new_hovered_node
                consumed = True

            # Update socket hover
            socket_info = self._get_socket_at_screen_pos(pos)
            new_hovered_socket = (socket_info[0], socket_info[1].id) if socket_info else None

            if new_hovered_socket != self.hovered_socket:
                self.hovered_socket = new_hovered_socket
                consumed = True

        return consumed

    def _handle_scroll(self, delta: int) -> bool:
        """Handle mouse wheel scroll (zoom)"""
        if not self.config.zoom_enabled:
            return False

        # Get mouse position for zoom center
        mouse_pos = pygame.mouse.get_pos()
        relative_pos = (mouse_pos[0] - self.rect.x, mouse_pos[1] - self.rect.y)

        # Calculate world position before zoom
        world_pos_before = self.screen_to_world(relative_pos)

        # Apply zoom
        old_zoom = self.zoom
        if delta > 0:
            self.zoom = min(self.config.max_zoom, self.zoom + self.config.zoom_step)
        else:
            self.zoom = max(self.config.min_zoom, self.zoom - self.config.zoom_step)

        # Adjust pan to keep zoom centered on mouse
        if self.zoom != old_zoom:
            world_pos_after = self.screen_to_world(relative_pos)
            self.pan_offset[0] += (world_pos_after[0] - world_pos_before[0]) * self.zoom
            self.pan_offset[1] += (world_pos_after[1] - world_pos_before[1]) * self.zoom

            self.update_viewport()
            self.rebuild_image()

        return True

    def _handle_key_down(self, event: pygame.event.Event) -> bool:
        """Handle key down events"""
        self.keys_pressed.add(event.key)

        if event.key == pygame.K_DELETE or event.key == pygame.K_BACKSPACE:
            # Delete selected nodes and connections
            self.delete_selected_nodes()
            return True

        elif event.key == pygame.K_a and (
                pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]):
            # Select all nodes
            old_selection = self.selected_nodes.copy()
            self.selected_nodes = set(self.graph.nodes.keys())

            for node_id in self.selected_nodes:
                if node_id not in old_selection:
                    self.fire_node_selected(node_id)

            self.rebuild_image()  # Refresh display
            return True

        elif event.key == pygame.K_c and (
                pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]):
            # Copy selected nodes (placeholder)
            if NODE_EDITOR_DEBUG:
                print(f"Copy {len(self.selected_nodes)} nodes")
            return True

        elif event.key == pygame.K_v and (
                pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]):
            # Paste nodes (placeholder)
            if NODE_EDITOR_DEBUG:
                print("Paste nodes")
            return True

        elif event.key == pygame.K_f:
            # Frame all nodes
            self.frame_all_nodes()
            return True

        elif event.key == pygame.K_g:
            # Toggle grid
            self.config.show_grid = not self.config.show_grid
            self.rebuild_image()  # Refresh display
            return True

        return False

    def _handle_key_up(self, event: pygame.event.Event) -> bool:
        """Handle key up events"""
        if event.key in self.keys_pressed:
            self.keys_pressed.remove(event.key)
        return False

    def _get_node_at_world_pos(self, world_pos: Tuple[int, int]) -> Optional[str]:
        """Get node at world position"""
        for node_id in self.visible_nodes:
            node = self.graph.nodes[node_id]
            if node.contains_point(world_pos):
                return node_id
        return None

    def _get_socket_at_screen_pos(self, screen_pos: Tuple[int, int]) -> Optional[Tuple[str, NodeSocket]]:
        """Get socket at screen position"""
        world_pos = self.screen_to_world(screen_pos)

        for node_id in self.visible_nodes:
            node = self.graph.nodes[node_id]
            socket = node.get_socket_at_position((world_pos[0] - node.position[0], world_pos[1] - node.position[1]))
            if socket:
                return node_id, socket

        return None

    def _start_connection(self, node_id: str, socket_id: str):
        """Start creating a connection from a socket"""
        self.is_connecting = True
        self.connecting_from_socket = (node_id, socket_id)
        self.temp_connection_end = None
        self.rebuild_image() # Refresh to clear any previous temp connections

    def _complete_connection(self, target_node_id: str, target_socket_id: str):
        """Complete a connection to a target socket"""
        if not self.connecting_from_socket:
            return

        start_node_id, start_socket_id = self.connecting_from_socket

        # Get sockets
        start_node = self.graph.get_node_by_id(start_node_id)
        target_node = self.graph.get_node_by_id(target_node_id)

        if not start_node or not target_node:
            return

        start_socket = next((s for s in start_node.get_all_sockets() if s.id == start_socket_id), None)
        target_socket = next((s for s in target_node.get_all_sockets() if s.id == target_socket_id), None)

        if not start_socket or not target_socket:
            return

        # Ensure proper direction (output to input)
        if start_socket.direction == SocketDirection.INPUT:
            start_socket, target_socket = target_socket, start_socket

        # Check if connection is valid
        if start_socket.can_connect_to(target_socket):
            # Create connection
            connection_id = str(uuid.uuid4())
            connection = NodeConnection(
                id=connection_id,
                start_socket=start_socket,
                end_socket=target_socket,
                color=self._get_connection_color(start_socket.socket_type)
            )

            # Add to graph
            if self.graph.add_connection(connection):
                self.fire_connection_created(connection_id)
                if NODE_EDITOR_DEBUG:
                    print(f"Created connection: {start_socket.label} -> {target_socket.label}")
                # Update viewport first to ensure new connection is in visible_connections
                # self.update_viewport()
                # self.rebuild_image()  # Refresh after successful connection

    def _cancel_connection(self):
        """Cancel connection creation"""
        self.is_connecting = False
        self.connecting_from_socket = None
        self.temp_connection_end = None

    def _complete_selection(self):
        """Complete selection rectangle"""
        if not self.selection_rect:
            return

        # Convert selection rect to world space
        world_rect = pygame.Rect(
            *self.screen_to_world(self.selection_rect.topleft),
            int(self.selection_rect.width / self.zoom),
            int(self.selection_rect.height / self.zoom)
        )

        # Find nodes in selection
        nodes_in_selection = self.graph.get_nodes_in_rect(world_rect)

        # Update selection
        for node in nodes_in_selection:
            if node.id not in self.selected_nodes:
                self.selected_nodes.add(node.id)
                self.fire_node_selected(node.id)

        self.rebuild_image()  # Refresh display

    def delete_selected_nodes(self):
        """Delete all selected nodes and connections"""
        # Delete selected connections first
        connections_to_delete = list(self.selected_connections)
        for conn_id in connections_to_delete:
            if self.graph.remove_connection(conn_id):
                self.fire_connection_deleted(conn_id)
        self.selected_connections.clear()

        # Delete selected nodes
        nodes_to_delete = list(self.selected_nodes)
        self.selected_nodes.clear()

        for node_id in nodes_to_delete:
            if self.graph.remove_node(node_id):
                self.fire_node_deleted(node_id)

        self.update_viewport()
        self.rebuild_image()

    def frame_all_nodes(self):
        """Frame all nodes in view"""
        if not self.graph.nodes:
            return

        # Calculate bounding box of all nodes
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')

        for node in self.graph.nodes.values():
            rect = node.get_rect()
            min_x = min(min_x, rect.left)
            min_y = min(min_y, rect.top)
            max_x = max(max_x, rect.right)
            max_y = max(max_y, rect.bottom)

        # Add padding
        padding = 50
        min_x -= padding
        min_y -= padding
        max_x += padding
        max_y += padding

        # Calculate zoom to fit
        content_width = max_x - min_x
        content_height = max_y - min_y

        zoom_x = self.rect.width / content_width if content_width > 0 else 1.0
        zoom_y = self.rect.height / content_height if content_height > 0 else 1.0

        self.zoom = min(zoom_x, zoom_y, self.config.max_zoom)
        self.zoom = max(self.zoom, self.config.min_zoom)

        # Center view
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        self.pan_offset[0] = self.rect.width / 2 - center_x * self.zoom
        self.pan_offset[1] = self.rect.height / 2 - center_y * self.zoom

        self.update_viewport()
        self.rebuild_image()

    def _snap_to_grid(self, pos: Tuple[int, int]) -> Tuple[int, int]:
        """Snap position to grid"""
        if not self.config.snap_to_grid:
            return pos

        grid_size = self.config.grid_size
        return (
            round(pos[0] / grid_size) * grid_size,
            round(pos[1] / grid_size) * grid_size
        )

    def _get_connection_color(self, socket_type: SocketType) -> pygame.Color:
        """Get color for connection based on socket type"""
        type_colors = {
            SocketType.EXEC: self.themed_colors.get('socket_exec', pygame.Color(255, 255, 255)),
            SocketType.NUMBER: self.themed_colors.get('socket_number', pygame.Color(100, 200, 100)),
            SocketType.STRING: self.themed_colors.get('socket_string', pygame.Color(200, 100, 100)),
            SocketType.BOOLEAN: self.themed_colors.get('socket_boolean', pygame.Color(200, 200, 100)),
            SocketType.VECTOR: self.themed_colors.get('socket_vector', pygame.Color(100, 100, 200)),
            SocketType.COLOR: self.themed_colors.get('socket_color', pygame.Color(200, 100, 200)),
            SocketType.OBJECT: self.themed_colors.get('socket_object', pygame.Color(150, 150, 150)),
            SocketType.ANY: self.themed_colors.get('socket_any', pygame.Color(100, 100, 100)),
        }
        return type_colors.get(socket_type, self.themed_colors.get('connection_default', pygame.Color(200, 200, 200)))

    # Event firing methods
    def fire_node_selected(self, node_id: str):
        """Fire node selected event"""
        node = self.graph.get_node_by_id(node_id)
        if node:
            event_data = {
                'node': node,
                'node_id': node_id,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_NODE_SELECTED, event_data))

    def fire_node_deselected(self, node_id: str):
        """Fire node deselected event"""
        node = self.graph.get_node_by_id(node_id)
        if node:
            event_data = {
                'node': node,
                'node_id': node_id,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_NODE_DESELECTED, event_data))

    def fire_node_moved(self, node_id: str):
        """Fire node moved event"""
        node = self.graph.get_node_by_id(node_id)
        if node:
            event_data = {
                'node': node,
                'node_id': node_id,
                'position': node.position,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_NODE_MOVED, event_data))

    def fire_node_deleted(self, node_id: str):
        """Fire node deleted event"""
        event_data = {
            'node_id': node_id,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_NODE_DELETED, event_data))

    def fire_node_added(self, node_id: str):
        """Fire node added event"""
        node = self.graph.get_node_by_id(node_id)
        if node:
            event_data = {
                'node': node,
                'node_id': node_id,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_NODE_ADDED, event_data))

    def fire_connection_created(self, connection_id: str):
        """Fire connection created event"""
        connection = self.graph.get_connection_by_id(connection_id)
        if connection:
            event_data = {
                'connection': connection,
                'connection_id': connection_id,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_CONNECTION_CREATED, event_data))

    def fire_connection_deleted(self, connection_id: str):
        """Fire connection deleted event"""
        event_data = {
            'connection_id': connection_id,
            'ui_element': self
        }
        pygame.event.post(pygame.event.Event(UI_CONNECTION_DELETED, event_data))

    def fire_node_right_clicked(self, node_id: str, screen_pos: Tuple[int, int]):
        """Fire node right click event"""
        node = self.graph.get_node_by_id(node_id)
        if node:
            event_data = {
                'node': node,
                'node_id': node_id,
                'screen_pos': screen_pos,
                'ui_element': self
            }
            pygame.event.post(pygame.event.Event(UI_NODE_RIGHT_CLICKED, event_data))

    def get_selected_connections(self) -> List[NodeConnection]:
        """Get all selected connections"""
        return [self.graph.connections[conn_id] for conn_id in self.selected_connections
                if conn_id in self.graph.connections]

    def select_connection(self, connection_id: str):
        """Select a connection"""
        if connection_id in self.graph.connections and connection_id not in self.selected_connections:
            self.selected_connections.add(connection_id)
            self.rebuild_image()

    def deselect_connection(self, connection_id: str):
        """Deselect a connection"""
        if connection_id in self.selected_connections:
            self.selected_connections.remove(connection_id)
            self.rebuild_image()

    def clear_selection(self):
        """Clear all selection"""
        old_node_selection = self.selected_nodes.copy()
        self.selected_nodes.clear()
        self.selected_connections.clear()

        for node_id in old_node_selection:
            self.fire_node_deselected(node_id)

        self.rebuild_image()

    def update(self, time_delta: float):
        """Update the panel"""
        super().update(time_delta)

    # Public API methods
    def add_node(self, node: Node) -> bool:
        """Add a node to the editor"""
        if self.graph.add_node(node):
            self.update_viewport()
            self.rebuild_image()
            self.fire_node_added(node.id)
            return True
        return False

    def remove_node(self, node_id: str) -> bool:
        """Remove a node from the editor"""
        if node_id in self.selected_nodes:
            self.selected_nodes.remove(node_id)

        if self.graph.remove_node(node_id):
            self.update_viewport()
            self.rebuild_image()
            self.fire_node_deleted(node_id)
            return True
        return False

    def remove_connection(self, connection_id: str) -> bool:
        """Remove a connection from the editor"""
        if connection_id in self.selected_connections:
            self.selected_connections.remove(connection_id)

        if self.graph.remove_connection(connection_id):
            self.update_viewport()
            self.rebuild_image()
            self.fire_connection_deleted(connection_id)
            return True
        return False

    def get_selected_nodes(self) -> List[Node]:
        """Get all selected nodes"""
        return [self.graph.nodes[node_id] for node_id in self.selected_nodes if node_id in self.graph.nodes]

    def select_node(self, node_id: str):
        """Select a node"""
        if node_id in self.graph.nodes and node_id not in self.selected_nodes:
            self.selected_nodes.add(node_id)
            self.fire_node_selected(node_id)
            self.rebuild_image()

    def deselect_node(self, node_id: str):
        """Deselect a node"""
        if node_id in self.selected_nodes:
            self.selected_nodes.remove(node_id)
            self.fire_node_deselected(node_id)
            self.rebuild_image()



    def set_zoom(self, zoom: float):
        """Set zoom level"""
        self.zoom = max(self.config.min_zoom, min(self.config.max_zoom, zoom))
        self.update_viewport()
        self.rebuild_image()

    def set_pan(self, offset: Tuple[int, int]):
        """Set pan offset"""
        self.pan_offset[0] = offset[0]
        self.pan_offset[1] = offset[1]
        self.update_viewport()
        self.rebuild_image()

    def frame_nodes(self, node_ids: List[str] = None):
        """Frame specific nodes or all nodes if None"""
        if node_ids is None:
            self.frame_all_nodes()
        elif node_ids:
            # Frame specific nodes
            nodes = [self.graph.get_node_by_id(nid) for nid in node_ids if nid in self.graph.nodes]
            if not nodes:
                return

            # Calculate bounding box
            min_x = min_y = float('inf')
            max_x = max_y = float('-inf')

            for node in nodes:
                rect = node.get_rect()
                min_x = min(min_x, rect.left)
                min_y = min(min_y, rect.top)
                max_x = max(max_x, rect.right)
                max_y = max(max_y, rect.bottom)

            # Add padding and center
            padding = 50
            min_x -= padding
            min_y -= padding
            max_x += padding
            max_y += padding

            content_width = max_x - min_x
            content_height = max_y - min_y

            zoom_x = self.rect.width / content_width if content_width > 0 else 1.0
            zoom_y = self.rect.height / content_height if content_height > 0 else 1.0

            self.zoom = min(zoom_x, zoom_y, self.config.max_zoom)
            self.zoom = max(self.zoom, self.config.min_zoom)

            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2

            self.pan_offset[0] = self.rect.width / 2 - center_x * self.zoom
            self.pan_offset[1] = self.rect.height / 2 - center_y * self.zoom

            self.update_viewport()
            self.rebuild_image()

    def get_graph_data(self) -> Dict[str, Any]:
        """Get serializable graph data"""
        return self.graph.to_dict()

    def clear_graph(self):
        """Clear the entire graph"""
        self.selected_nodes.clear()
        self.graph.clear()
        self.update_viewport()
        self.rebuild_image()


class ConnectionPropertiesDialog(UIWindow):
    """Dialog for editing connection properties"""

    def __init__(self, rect: pygame.Rect, manager: pygame_gui.UIManager,
                 connection: NodeConnection, node_editor: 'NodeEditorPanel'):
        super().__init__(rect, manager, window_display_title="Connection Properties",
                         object_id=ObjectID(object_id='#connection_properties_dialog'))

        self.connection = connection
        self.node_editor = node_editor

        # Create the UI elements
        self._create_property_editors()

    def _create_property_editors(self):
        """Create UI elements for editing connection properties"""
        y_pos = 10

        # Connection info (read-only)
        start_node = next((n for n in self.node_editor.graph.nodes.values()
                           if self.connection.start_socket in n.get_all_sockets()), None)
        end_node = next((n for n in self.node_editor.graph.nodes.values()
                         if self.connection.end_socket in n.get_all_sockets()), None)

        if start_node and end_node:
            info_text = f"From: {start_node.title}.{self.connection.start_socket.label}\nTo: {end_node.title}.{self.connection.end_socket.label}"
        else:
            info_text = "Connection info unavailable"

        UILabel(pygame.Rect(10, y_pos, 100, 25), "Connection:",
                manager=self.ui_manager, container=self)

        self.info_textbox = UITextBox(
            f"<pre>{info_text}</pre>",
            pygame.Rect(10, y_pos + 30, 320, 60),
            manager=self.ui_manager,
            container=self
        )
        y_pos += 100

        # Connection width
        UILabel(pygame.Rect(10, y_pos, 100, 25), "Width:",
                manager=self.ui_manager, container=self)

        self.width_entry = UITextEntryLine(
            pygame.Rect(120, y_pos, 100, 25),
            manager=self.ui_manager,
            container=self,
            initial_text=str(self.connection.width)
        )
        y_pos += 35

        # Connection color
        UILabel(pygame.Rect(10, y_pos, 100, 25), "Color (R,G,B,A):",
                manager=self.ui_manager, container=self)

        color_text = f"{self.connection.color.r},{self.connection.color.g},{self.connection.color.b},{self.connection.color.a}"
        self.color_entry = UITextEntryLine(
            pygame.Rect(120, y_pos, 150, 25),
            manager=self.ui_manager,
            container=self,
            initial_text=color_text
        )
        y_pos += 35

        # Custom metadata - use safe serialization
        if self.connection.metadata:
            UILabel(pygame.Rect(10, y_pos, 320, 25), "Metadata (JSON):",
                    manager=self.ui_manager, container=self)
            y_pos += 30

            try:
                serializable_metadata = make_json_serializable(self.connection.metadata)
                metadata_json = json.dumps(serializable_metadata, indent=2)
            except Exception as e:
                metadata_json = f"Error serializing metadata: {str(e)}\nRaw metadata: {str(self.connection.metadata)}"

            self.metadata_textbox = UITextBox(
                f"<pre>{metadata_json}</pre>",
                pygame.Rect(10, y_pos, 320, 80),
                manager=self.ui_manager,
                container=self
            )
            y_pos += 90
        else:
            self.metadata_textbox = None

        # Buttons
        self.ok_button = UIButton(
            pygame.Rect(180, y_pos, 80, 30),
            text="OK",
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(object_id='#ok_button')
        )

        self.cancel_button = UIButton(
            pygame.Rect(270, y_pos, 80, 30),
            text="Cancel",
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(object_id='#cancel_button')
        )

        # Resize window to fit content
        new_height = y_pos + 95
        self.set_dimensions((390, new_height))

    def process_event(self, event: pygame.event.Event) -> bool:
        """Handle dialog events"""
        if super().process_event(event):
            return True

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.ok_button:
                self._apply_changes()
                self.kill()
                return True
            elif event.ui_element == self.cancel_button:
                self.kill()
                return True

        return False

    def _apply_changes(self):
        """Apply the changes to the connection"""
        # Width
        try:
            width = int(self.width_entry.get_text())
            self.connection.width = max(1, width)
        except ValueError:
            pass  # Keep original width if invalid

        # Color
        try:
            color_parts = [int(x.strip()) for x in self.color_entry.get_text().split(',')]
            if len(color_parts) >= 3:
                r = max(0, min(255, color_parts[0]))
                g = max(0, min(255, color_parts[1]))
                b = max(0, min(255, color_parts[2]))
                a = max(0, min(255, color_parts[3])) if len(color_parts) > 3 else 255
                self.connection.color = pygame.Color(r, g, b, a)
        except (ValueError, IndexError):
            pass  # Keep original color if invalid

        # Metadata
        if self.metadata_textbox:
            try:
                html_text = self.metadata_textbox.html_text
                if "<pre>" in html_text and "</pre>" in html_text:
                    json_text = html_text.split("<pre>")[1].split("</pre>")[0]
                    new_metadata = json.loads(json_text)
                    self.connection.metadata = new_metadata
            except (json.JSONDecodeError, IndexError):
                pass  # Keep original metadata if invalid JSON

        # Refresh the node editor
        self.node_editor.update_viewport()
        self.node_editor.rebuild_image()

        print(f"Updated connection properties: width={self.connection.width}, color={self.connection.color}")

class NodeEditorContextMenu:
    """Context menu for the node editor"""

    def __init__(self, manager: pygame_gui.UIManager, node_editor: NodeEditorPanel):
        self.manager = manager
        self.node_editor = node_editor
        self.context_menu = None
        self.context_target = None  # What was right-clicked
        self.context_pos = None  # Where the menu should appear

        # Add clipboard
        self.clipboard = NodeClipboard()

        # Current properties dialog
        self.properties_dialog: Optional[NodePropertiesDialog] = None

    def show_context_menu(self, screen_pos: Tuple[int, int], target_type: str, target_data: Any = None):
        """Show context menu at the given position"""
        self.hide_context_menu()  # Hide any existing menu

        self.context_target = (target_type, target_data)
        self.context_pos = screen_pos

        # Create menu items based on context
        menu_items = self._get_menu_items(target_type, target_data)

        if menu_items:
            # Calculate menu size
            item_height = 25
            menu_width = 180
            menu_height = len(menu_items) * item_height + 10

            # Get screen size from manager
            screen_width = self.manager.get_root_container().rect.width
            screen_height = self.manager.get_root_container().rect.height

            # Ensure menu stays on screen
            menu_x = min(screen_pos[0], screen_width - menu_width)
            menu_y = min(screen_pos[1], screen_height - menu_height)

            # Create context menu
            menu_rect = pygame.Rect(menu_x, menu_y, menu_width, menu_height)
            self.context_menu = pygame_gui.elements.UIPanel(
                relative_rect=menu_rect,
                starting_height=10,  # High layer
                manager=self.manager,
                object_id=ObjectID(object_id='#context_menu')
            )

            print(f"Created context menu with {len(menu_items)} items")

            # Add menu items
            for i, (label, command) in enumerate(menu_items):
                if label == "---":  # Skip separators for now
                    continue

                button_rect = pygame.Rect(5, 5 + i * item_height, menu_width - 10, item_height - 2)
                object_id = ObjectID(object_id=f'#context_item_{command}')
                print(f"Creating button: {label} with object_id: {object_id}")

                button = pygame_gui.elements.UIButton(
                    relative_rect=button_rect,
                    text=label,
                    container=self.context_menu,
                    manager=self.manager,
                    object_id=object_id
                )

    def update(self, time_delta: float):
        """Update dialogs and handle cleanup"""
        if self.properties_dialog:
            # Check if dialog was closed
            if not self.properties_dialog.alive():
                self.properties_dialog = None

    def kill_dialogs(self):
        """Clean up any open dialogs"""
        if self.properties_dialog:
            self.properties_dialog.kill()
            self.properties_dialog = None

    def hide_context_menu(self):
        """Hide the context menu"""
        if self.context_menu:
            self.context_menu.kill()
            self.context_menu = None
            self.context_target = None
            self.context_pos = None

    def _get_menu_items(self, target_type: str, target_data: Any) -> List[Tuple[str, str]]:
        """Get menu items based on what was right-clicked"""
        items = []

        if target_type == "node":
            # Node context menu
            node_id = target_data
            items.extend([
                ("Delete Node", "delete_node"),
                ("Duplicate Node", "duplicate_node"),
                ("Copy Node", "copy_node"),
                ("Node Properties", "node_properties"),
                ("Collapse Node", "collapse_node"),
            ])

        elif target_type == "connection":
            # Connection context menu
            connection_id = target_data
            items.extend([
                ("Delete Connection", "delete_connection"),
                ("Connection Properties", "connection_properties"),
            ])

        elif target_type == "background":
            # Background context menu
            items.extend([
                ("Add Math Node", "add_math_add"),
                ("Add Constant", "add_const_number"),
                ("Add Print Node", "add_print"),
                ("Paste", "paste"),
                ("Select All", "select_all"),
                ("Clear Selection", "clear_selection"),
                ("Frame All", "frame_all"),
                ("Reset View", "reset_view"),
            ])

        # Add common items if nodes are selected
        if self.node_editor.selected_nodes and target_type == "background":
            items.insert(-4, ("Delete Selected", "delete_selected"))
            items.insert(-4, ("Group Selected", "group_selected"))

        return items

    def handle_menu_selection(self, command: str):
        """Handle context menu selection"""
        target_type, target_data = self.context_target if self.context_target else (None, None)

        if command == "delete_node" and target_type == "node":
            self.node_editor.remove_node(target_data)

        elif command == "duplicate_node" and target_type == "node":
            self._duplicate_node(target_data)

        elif command == "copy_node" and target_type == "node":
            print(f"Copy node: {target_data}")  # TODO: Implement clipboard

        elif command == "node_properties" and target_type == "node":
            self._show_node_properties(target_data)

        elif command == "collapse_node" and target_type == "node":
            node = self.node_editor.graph.get_node_by_id(target_data)
            if node:
                node.is_collapsed = not node.is_collapsed
                self.node_editor.rebuild_image()

        elif command == "delete_connection" and target_type == "connection":
            self.node_editor.remove_connection(target_data)

        elif command == "connection_properties" and target_type == "connection":
            self._show_connection_properties(target_data)

        elif command == "paste":
            print("Paste nodes")  # TODO: Implement clipboard

        elif command == "select_all":
            old_selection = self.node_editor.selected_nodes.copy()
            self.node_editor.selected_nodes = set(self.node_editor.graph.nodes.keys())
            for node_id in self.node_editor.selected_nodes:
                if node_id not in old_selection:
                    self.node_editor.fire_node_selected(node_id)
            self.node_editor.rebuild_image()

        elif command == "clear_selection":
            self.node_editor.clear_selection()

        elif command == "delete_selected":
            self.node_editor.delete_selected_nodes()

        elif command == "group_selected":
            print("Group selected nodes")  # TODO: Implement grouping

        elif command == "frame_all":
            self.node_editor.frame_all_nodes()

        elif command == "reset_view":
            self.node_editor.zoom = 1.0
            self.node_editor.pan_offset = [0, 0]
            self.node_editor.update_viewport()
            self.node_editor.rebuild_image()

        # Add node commands
        elif command.startswith("add_"):
            self._add_node_by_type(command)

        self.hide_context_menu()

    def _duplicate_node(self, node_id: str):
        """Duplicate a node"""
        original = self.node_editor.graph.get_node_by_id(node_id)
        if not original:
            return

        # Create new node of same type
        new_id = f"{original.id}_copy_{len(self.node_editor.graph.nodes)}"

        if isinstance(original, MathNode):
            new_node = MathNode(new_id, original.properties.get("operation", "add"))
        elif isinstance(original, ConstantNode):
            new_node = ConstantNode(new_id,
                                    original.properties.get("value_type", SocketType.NUMBER),
                                    original.properties.get("value", 0))
        elif isinstance(original, PrintNode):
            new_node = PrintNode(new_id)
        else:
            # Generic node duplication
            new_node = Node(
                id=new_id,
                title=f"{original.title} Copy",
                node_type=original.node_type,
                size=original.size,
                color=original.color,
                header_color=original.header_color
            )
            # Copy sockets (simplified)
            for socket in original.input_sockets:
                new_node.add_input_socket(NodeSocket(
                    socket.id, socket.label, socket.socket_type, socket.direction,
                    default_value=socket.default_value
                ))
            for socket in original.output_sockets:
                new_node.add_output_socket(NodeSocket(
                    socket.id, socket.label, socket.socket_type, socket.direction,
                    default_value=socket.default_value
                ))

        # Position offset
        new_node.position = (original.position[0] + 50, original.position[1] + 50)
        self.node_editor.add_node(new_node)

    def _show_node_properties(self, node_id: str):
        """Show node properties dialog"""
        node = self.node_editor.graph.get_node_by_id(node_id)
        if not node:
            print(f"Node {node_id} not found")
            return

        # Close existing dialog if open
        if self.properties_dialog:
            self.properties_dialog.kill()

        # Create new properties dialog
        dialog_rect = pygame.Rect(100, 100, 380, 400)
        self.properties_dialog = NodePropertiesDialog(
            dialog_rect, self.manager, node, self.node_editor
        )
        print(f"Opened properties dialog for node: {node.title}")

    def _show_connection_properties(self, connection_id: str):
        """Show connection properties dialog"""
        connection = self.node_editor.graph.get_connection_by_id(connection_id)
        if not connection:
            print(f"Connection {connection_id} not found")
            return

        # Close existing dialog if open
        if self.properties_dialog:
            self.properties_dialog.kill()

        # Create connection properties dialog
        dialog_rect = pygame.Rect(100, 100, 350, 300)
        self.properties_dialog = ConnectionPropertiesDialog(
            dialog_rect, self.manager, connection, self.node_editor
        )
        print(f"Opened properties dialog for connection")

    def _add_node_by_type(self, command: str):
        """Add a node based on command"""
        world_pos = self.node_editor.screen_to_world(self.context_pos) if self.context_pos else (100, 100)
        node_id = f"node_{len(self.node_editor.graph.nodes) + 1}"

        if command == "add_math_add":
            node = MathNode(node_id, "add")
        elif command == "add_math_subtract":
            node = MathNode(node_id, "subtract")
        elif command == "add_math_multiply":
            node = MathNode(node_id, "multiply")
        elif command == "add_math_divide":
            node = MathNode(node_id, "divide")
        elif command == "add_const_number":
            node = ConstantNode(node_id, SocketType.NUMBER, 0)
        elif command == "add_const_string":
            node = ConstantNode(node_id, SocketType.STRING, "")
        elif command == "add_const_boolean":
            node = ConstantNode(node_id, SocketType.BOOLEAN, False)
        elif command == "add_print":
            node = PrintNode(node_id)
        else:
            return

        node.position = world_pos
        self.node_editor.add_node(node)

    def process_event(self, event: pygame.event.Event) -> bool:
        """Process events for context menu"""
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            # Debug: Print button info and try different object_id methods
            print(f"Button pressed: {event.ui_element}")

            # Try different ways to get object_id
            if hasattr(event.ui_element, 'object_ids'):
                print(f"object_ids: {event.ui_element.object_ids}")

            if hasattr(event.ui_element, 'get_object_ids'):
                print(f"get_object_ids(): {event.ui_element.get_object_ids()}")

            if hasattr(event.ui_element, 'most_specific_combined_id'):
                print(f"most_specific_combined_id: {event.ui_element.most_specific_combined_id}")

            if hasattr(event.ui_element, 'get_most_specific_combined_id'):
                print(f"get_most_specific_combined_id(): {event.ui_element.get_most_specific_combined_id()}")

            if self.context_menu:
                # Try to get the object_id using the available methods
                object_id_str = None

                # Method 1: Check object_ids attribute
                if hasattr(event.ui_element, 'object_ids') and event.ui_element.object_ids:
                    object_ids = event.ui_element.object_ids
                    # object_ids might be a list, get the first one or look for our pattern
                    if isinstance(object_ids, list) and object_ids:
                        for oid in object_ids:
                            if isinstance(oid, str) and oid.startswith('#context_item_'):
                                object_id_str = oid
                                break
                    elif isinstance(object_ids, str):
                        object_id_str = object_ids

                # Method 2: Try get_object_ids()
                if not object_id_str and hasattr(event.ui_element, 'get_object_ids'):
                    try:
                        object_ids = event.ui_element.get_object_ids()
                        if isinstance(object_ids, list) and object_ids:
                            for oid in object_ids:
                                if isinstance(oid, str) and oid.startswith('#context_item_'):
                                    object_id_str = oid
                                    break
                        elif isinstance(object_ids, str):
                            object_id_str = object_ids
                    except:
                        pass

                # Method 3: Try most_specific_combined_id
                if not object_id_str and hasattr(event.ui_element, 'most_specific_combined_id'):
                    try:
                        combined_id = event.ui_element.most_specific_combined_id
                        if isinstance(combined_id, str) and '#context_item_' in combined_id:
                            object_id_str = combined_id
                    except:
                        pass

                print(f"Final object_id_str: {object_id_str}")

                if object_id_str and '#context_item_' in object_id_str:
                    # Extract command from the object_id
                    command = object_id_str.replace('#context_item_', '')
                    print(f"Extracted command: {command}")
                    if command and command != "separator":
                        self.handle_menu_selection(command)
                        return True

        elif event.type == pygame.MOUSEBUTTONDOWN:
            # Hide context menu when clicking elsewhere
            if self.context_menu:
                # Check if click is outside the context menu
                if not self.context_menu.rect.collidepoint(event.pos):
                    self.hide_context_menu()

        return False


class NodePropertiesDialog(UIWindow):
    """Dialog for editing node properties"""

    def __init__(self, rect: pygame.Rect, manager: pygame_gui.UIManager, node: Node, node_editor: 'NodeEditorPanel'):
        super().__init__(rect, manager, window_display_title=f"Properties - {node.title}",
                         object_id=ObjectID(object_id='#node_properties_dialog'))

        self.node = node
        self.node_editor = node_editor
        self.property_widgets: Dict[str, Any] = {}

        # Create the UI elements
        self._create_property_editors()

    def _create_property_editors(self):
        """Create UI elements for editing node properties"""
        y_pos = 10

        # Node title
        UILabel(pygame.Rect(10, y_pos, 100, 25), "Title:",
                manager=self.ui_manager, container=self)

        self.title_entry = UITextEntryLine(
            pygame.Rect(120, y_pos, 200, 25),
            manager=self.ui_manager,
            container=self,
            initial_text=self.node.title
        )
        y_pos += 35

        # Node description
        UILabel(pygame.Rect(10, y_pos, 100, 25), "Description:",
                manager=self.ui_manager, container=self)

        self.description_entry = UITextEntryLine(
            pygame.Rect(120, y_pos, 200, 25),
            manager=self.ui_manager,
            container=self,
            initial_text=self.node.description
        )
        y_pos += 35

        # Node category
        UILabel(pygame.Rect(10, y_pos, 100, 25), "Category:",
                manager=self.ui_manager, container=self)

        self.category_entry = UITextEntryLine(
            pygame.Rect(120, y_pos, 200, 25),
            manager=self.ui_manager,
            container=self,
            initial_text=self.node.category
        )
        y_pos += 35

        # Node size
        UILabel(pygame.Rect(10, y_pos, 100, 25), "Width:",
                manager=self.ui_manager, container=self)

        self.width_entry = UITextEntryLine(
            pygame.Rect(120, y_pos, 80, 25),
            manager=self.ui_manager,
            container=self,
            initial_text=str(self.node.size[0])
        )

        UILabel(pygame.Rect(210, y_pos, 50, 25), "Height:",
                manager=self.ui_manager, container=self)

        self.height_entry = UITextEntryLine(
            pygame.Rect(270, y_pos, 80, 25),
            manager=self.ui_manager,
            container=self,
            initial_text=str(self.node.size[1])
        )
        y_pos += 35

        # Custom properties for specific node types
        if isinstance(self.node, MathNode):
            self._create_math_node_properties(y_pos)
            y_pos += 35
        elif isinstance(self.node, ConstantNode):
            self._create_constant_node_properties(y_pos)
            y_pos += 35

        # Generic properties - use the helper function here
        if self.node.properties:
            UILabel(pygame.Rect(10, y_pos, 340, 25), "Custom Properties:",
                    manager=self.ui_manager, container=self)
            y_pos += 30

            # Convert properties to JSON-serializable format
            try:
                serializable_properties = make_json_serializable(self.node.properties)
                properties_json = json.dumps(serializable_properties, indent=2)
            except Exception as e:
                # Fallback if serialization still fails
                properties_json = f"Error serializing properties: {str(e)}\nRaw properties: {str(self.node.properties)}"

            # Create a text box for JSON editing of properties
            self.properties_textbox = UITextBox(
                f"<pre>{properties_json}</pre>",
                pygame.Rect(10, y_pos, 340, 100),
                manager=self.ui_manager,
                container=self
            )
            y_pos += 110

        # Buttons
        self.ok_button = UIButton(
            pygame.Rect(200, y_pos, 80, 30),
            text="OK",
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(object_id='#ok_button')
        )

        self.cancel_button = UIButton(
            pygame.Rect(290, y_pos, 80, 30),
            text="Cancel",
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(object_id='#cancel_button')
        )

        # Resize window to fit content
        new_height = y_pos + 95
        self.set_dimensions((410, new_height))

    def _create_math_node_properties(self, y_pos: int):
        """Create properties specific to math nodes"""
        UILabel(pygame.Rect(10, y_pos, 100, 25), "Operation:",
                manager=self.ui_manager, container=self)

        operations = ["add", "subtract", "multiply", "divide", "sin", "cos", "tan", "sqrt"]
        current_op = self.node.properties.get("operation", "add")

        self.operation_dropdown = UIDropDownMenu(
            operations,
            current_op,
            pygame.Rect(120, y_pos, 150, 25),
            manager=self.ui_manager,
            container=self
        )

    def _create_constant_node_properties(self, y_pos: int):
        """Create properties specific to constant nodes"""
        UILabel(pygame.Rect(10, y_pos, 100, 25), "Value:",
                manager=self.ui_manager, container=self)

        current_value = self.node.properties.get("value", "0")
        self.value_entry = UITextEntryLine(
            pygame.Rect(120, y_pos, 150, 25),
            manager=self.ui_manager,
            container=self,
            initial_text=str(current_value)
        )

    def process_event(self, event: pygame.event.Event) -> bool:
        """Handle dialog events"""
        if super().process_event(event):
            return True

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.ok_button:
                self._apply_changes()
                self.kill()
                return True
            elif event.ui_element == self.cancel_button:
                self.kill()
                return True

        return False

    def _apply_changes(self):
        """Apply the changes to the node"""
        # Basic properties
        self.node.title = self.title_entry.get_text()
        self.node.description = self.description_entry.get_text()
        self.node.category = self.category_entry.get_text()

        # Size
        try:
            width = int(self.width_entry.get_text())
            height = int(self.height_entry.get_text())
            self.node.resize((max(50, width), max(30, height)))
        except ValueError:
            pass  # Keep original size if invalid

        # Specific node type properties
        if isinstance(self.node, MathNode) and hasattr(self, 'operation_dropdown'):
            self.node.properties["operation"] = self.operation_dropdown.selected_option
            # Update title to reflect operation
            self.node.title = f"Math ({self.operation_dropdown.selected_option.title()})"

        elif isinstance(self.node, ConstantNode) and hasattr(self, 'value_entry'):
            try:
                # Try to parse as number first
                value_text = self.value_entry.get_text()
                if '.' in value_text:
                    self.node.properties["value"] = float(value_text)
                else:
                    self.node.properties["value"] = int(value_text)
            except ValueError:
                # Keep as string if not a number
                self.node.properties["value"] = self.value_entry.get_text()

        # Custom properties from JSON
        if hasattr(self, 'properties_textbox'):
            try:
                # Extract text from HTML content
                html_text = self.properties_textbox.html_text
                # Simple extraction - in practice you might want more robust parsing
                if "<pre>" in html_text and "</pre>" in html_text:
                    json_text = html_text.split("<pre>")[1].split("</pre>")[0]
                    new_properties = json.loads(json_text)
                    self.node.properties.update(new_properties)
            except (json.JSONDecodeError, IndexError):
                pass  # Keep original properties if invalid JSON

        # Fire property changed event
        event_data = {
            'node': self.node,
            'node_id': self.node.id,
            'ui_element': self.node_editor
        }
        pygame.event.post(pygame.event.Event(UI_NODE_PROPERTY_CHANGED, event_data))

        # Refresh the node editor
        self.node_editor.update_viewport()
        self.node_editor.rebuild_image()


class NodeClipboard:
    """Clipboard system for copying and pasting nodes"""

    def __init__(self):
        self.copied_nodes: List[Dict[str, Any]] = []
        self.copy_offset = (50, 50)  # Offset for pasted nodes

    def copy_nodes(self, nodes: List[Node]) -> bool:
        """Copy nodes to clipboard"""
        if not nodes:
            return False

        self.copied_nodes.clear()

        for node in nodes:
            node_data = self._serialize_node(node)
            self.copied_nodes.append(node_data)

        return True

    def paste_nodes(self, node_editor: 'NodeEditorPanel', paste_position: Optional[Tuple[int, int]] = None) -> List[
        str]:
        """Paste nodes from clipboard"""
        if not self.copied_nodes:
            return []

        new_node_ids = []

        # Calculate paste position
        if paste_position is None:
            # Default to center of current view
            screen_center = (node_editor.rect.width // 2, node_editor.rect.height // 2)
            paste_position = node_editor.screen_to_world(screen_center)

        # Find center of copied nodes for relative positioning
        if self.copied_nodes:
            center_x = sum(node_data['position'][0] for node_data in self.copied_nodes) / len(self.copied_nodes)
            center_y = sum(node_data['position'][1] for node_data in self.copied_nodes) / len(self.copied_nodes)
            copy_center = (center_x, center_y)
        else:
            copy_center = (0, 0)

        # Create new nodes
        for node_data in self.copied_nodes:
            new_node = self._deserialize_node(node_data, node_editor.graph.nodes)
            if new_node:
                # Adjust position relative to paste position
                relative_x = node_data['position'][0] - copy_center[0]
                relative_y = node_data['position'][1] - copy_center[1]
                new_node.position = (
                    paste_position[0] + relative_x + self.copy_offset[0],
                    paste_position[1] + relative_y + self.copy_offset[1]
                )

                if node_editor.add_node(new_node):
                    new_node_ids.append(new_node.id)

        return new_node_ids

    def _serialize_node(self, node: Node) -> Dict[str, Any]:
        """Serialize a node to dictionary"""
        return {
            'class_name': node.__class__.__name__,
            'id': node.id,
            'title': node.title,
            'node_type': node.node_type.value,
            'position': node.position,
            'size': node.size,
            'properties': copy.deepcopy(node.properties),
            'metadata': copy.deepcopy(node.metadata),
            'color': [node.color.r, node.color.g, node.color.b, node.color.a],
            'header_color': [node.header_color.r, node.header_color.g, node.header_color.b, node.header_color.a],
            'category': node.category,
            'description': node.description,
            'input_sockets': [self._serialize_socket(s) for s in node.input_sockets],
            'output_sockets': [self._serialize_socket(s) for s in node.output_sockets]
        }

    @staticmethod
    def _serialize_socket(socket: NodeSocket) -> Dict[str, Any]:
        """Serialize a socket to dictionary"""
        return {
            'id': socket.id,
            'label': socket.label,
            'socket_type': socket.socket_type.value,
            'default_value': socket.default_value,
            'is_multiple': socket.is_multiple,
            'is_required': socket.is_required,
            'metadata': copy.deepcopy(socket.metadata)
        }

    @staticmethod
    def _deserialize_node(node_data: Dict[str, Any], existing_nodes: Dict[str, Node]) -> Optional[Node]:
        """Deserialize a node from dictionary"""
        # Generate unique ID
        base_id = node_data['id']
        new_id = base_id
        counter = 1
        while new_id in existing_nodes:
            new_id = f"{base_id}_copy_{counter}"
            counter += 1

        try:
            # Create node based on class name
            class_name = node_data['class_name']

            if class_name == 'MathNode':
                operation = node_data['properties'].get('operation', 'add')
                node = MathNode(new_id, operation)
            elif class_name == 'ConstantNode':
                value_type = SocketType(node_data['properties'].get('value_type', 'number'))
                value = node_data['properties'].get('value', 0)
                node = ConstantNode(new_id, value_type, value)
            elif class_name == 'PrintNode':
                node = PrintNode(new_id)
            else:
                # Generic node
                node = Node(
                    id=new_id,
                    title=node_data['title'],
                    node_type=NodeType(node_data['node_type']),
                    size=tuple(node_data['size']),
                    color=pygame.Color(*node_data['color']),
                    header_color=pygame.Color(*node_data['header_color'])
                )

                # Add sockets for generic nodes
                for socket_data in node_data['input_sockets']:
                    socket = NodeSocket(
                        id=socket_data['id'],
                        label=socket_data['label'],
                        socket_type=SocketType(socket_data['socket_type']),
                        direction=SocketDirection.INPUT,
                        default_value=socket_data['default_value'],
                        is_multiple=socket_data['is_multiple'],
                        is_required=socket_data['is_required'],
                        metadata=socket_data['metadata']
                    )
                    node.add_input_socket(socket)

                for socket_data in node_data['output_sockets']:
                    socket = NodeSocket(
                        id=socket_data['id'],
                        label=socket_data['label'],
                        socket_type=SocketType(socket_data['socket_type']),
                        direction=SocketDirection.OUTPUT,
                        default_value=socket_data['default_value'],
                        is_multiple=socket_data['is_multiple'],
                        is_required=socket_data['is_required'],
                        metadata=socket_data['metadata']
                    )
                    node.add_output_socket(socket)

            # Set common properties
            node.title = node_data['title']
            node.category = node_data['category']
            node.description = node_data['description']
            node.properties = copy.deepcopy(node_data['properties'])
            node.metadata = copy.deepcopy(node_data['metadata'])

            return node

        except Exception as e:
            if NODE_EDITOR_DEBUG:
                print(f"Error deserializing node: {e}")
            return None

    def has_nodes(self) -> bool:
        """Check if clipboard has nodes"""
        return len(self.copied_nodes) > 0

    def clear(self):
        """Clear the clipboard"""
        self.copied_nodes.clear()


# Example theme for node editor
NODE_EDITOR_THEME = {
    "node_editor": {
        "colours": {
            "background": "#1e1e1e",
            "grid": "#282828",
            "node_border": "#646464",
            "node_text": "#ffffff",
            "selection": "#ffff00",
            "selection_rect": "#6496ff40",
            "socket_border": "#c8c8c8",
            "socket_connected": "#ffff00",
            "socket_exec": "#ffffff",
            "socket_number": "#64c864",
            "socket_string": "#c86464",
            "socket_boolean": "#c8c864",
            "socket_vector": "#6464c8",
            "socket_color": "#c864c8",
            "socket_object": "#969696",
            "socket_any": "#646464",
            "connection_default": "#c8c8c8",
            "temp_connection": "#ffffff80"
        },
        "font": {
            "name": "arial",
            "size": "12",
            "bold": "0",
            "italic": "0"
        }
    }
}


# Built-in node types
class MathNode(Node):
    """Math operation node"""

    def __init__(self, node_id: str, operation: str = "add"):
        super().__init__(
            id=node_id,
            title=f"Math ({operation.title()})",
            node_type=NodeType.MATH,
            size=(140, 80),
            color=pygame.Color(60, 80, 60),
            header_color=pygame.Color(40, 60, 40),
            category="Math",
            description=f"Performs {operation} operation"
        )

        self.properties["operation"] = operation

        # Add sockets based on operation
        if operation in ["add", "subtract", "multiply", "divide"]:
            self.add_input_socket(NodeSocket("a", "A", SocketType.NUMBER, SocketDirection.INPUT, default_value=0))
            self.add_input_socket(NodeSocket("b", "B", SocketType.NUMBER, SocketDirection.INPUT, default_value=0))
            self.add_output_socket(NodeSocket("result", "Result", SocketType.NUMBER, SocketDirection.OUTPUT))
        elif operation in ["sin", "cos", "tan", "sqrt"]:
            self.add_input_socket(
                NodeSocket("input", "Input", SocketType.NUMBER, SocketDirection.INPUT, default_value=0))
            self.add_output_socket(NodeSocket("result", "Result", SocketType.NUMBER, SocketDirection.OUTPUT))

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute math operation"""
        operation = self.properties.get("operation", "add")

        try:
            if operation == "add":
                result = inputs.get("a", 0) + inputs.get("b", 0)
            elif operation == "subtract":
                result = inputs.get("a", 0) - inputs.get("b", 0)
            elif operation == "multiply":
                result = inputs.get("a", 0) * inputs.get("b", 0)
            elif operation == "divide":
                b = inputs.get("b", 1)
                result = inputs.get("a", 0) / b if b != 0 else 0
            elif operation == "sin":
                result = math.sin(inputs.get("input", 0))
            elif operation == "cos":
                result = math.cos(inputs.get("input", 0))
            elif operation == "tan":
                result = math.tan(inputs.get("input", 0))
            elif operation == "sqrt":
                input_val = inputs.get("input", 0)
                result = math.sqrt(input_val) if input_val >= 0 else 0
            else:
                result = 0

            return {"result": result}
        except:
            return {"result": 0}


class ConstantNode(Node):
    """Constant value node"""

    def __init__(self, node_id: str, value_type: SocketType = SocketType.NUMBER, value: Any = 0):
        super().__init__(
            id=node_id,
            title=f"Constant ({value_type.value.title()})",
            node_type=NodeType.CONSTANT,
            size=(120, 60),
            color=pygame.Color(80, 60, 60),
            header_color=pygame.Color(60, 40, 40),
            category="Constants",
            description=f"Constant {value_type.value} value"
        )

        self.properties["value_type"] = value_type
        self.properties["value"] = value

        # Add output socket
        self.add_output_socket(NodeSocket("value", "Value", value_type, SocketDirection.OUTPUT, default_value=value))

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Return constant value"""
        return {"value": self.properties.get("value", 0)}


class PrintNode(Node):
    """Debug print node"""

    def __init__(self, node_id: str):
        super().__init__(
            id=node_id,
            title="Print",
            node_type=NodeType.FUNCTION,
            size=(100, 60),
            color=pygame.Color(80, 80, 60),
            header_color=pygame.Color(60, 60, 40),
            category="Debug",
            description="Print value to console"
        )

        # Add sockets
        self.add_input_socket(NodeSocket("exec_in", "", SocketType.EXEC, SocketDirection.INPUT))
        self.add_input_socket(NodeSocket("value", "Value", SocketType.ANY, SocketDirection.INPUT))
        self.add_output_socket(NodeSocket("exec_out", "", SocketType.EXEC, SocketDirection.OUTPUT))

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Print the input value"""
        value = inputs.get("value", "")
        print(f"Print Node: {value}")
        return {"exec_out": True}



def create_sample_graph() -> NodeGraph:
    """Create a sample node graph for testing"""
    graph = NodeGraph()

    # Create sample nodes
    const1 = ConstantNode("const1", SocketType.NUMBER, 5)
    const1.position = (50, 100)

    const2 = ConstantNode("const2", SocketType.NUMBER, 3)
    const2.position = (50, 200)

    math_add = MathNode("math1", "add")
    math_add.position = (250, 150)

    math_multiply = MathNode("math2", "multiply")
    math_multiply.position = (450, 150)

    const3 = ConstantNode("const3", SocketType.NUMBER, 2)
    const3.position = (250, 250)

    print_node = PrintNode("print1")
    print_node.position = (650, 150)

    # Add nodes to graph
    graph.add_node(const1)
    graph.add_node(const2)
    graph.add_node(math_add)
    graph.add_node(math_multiply)
    graph.add_node(const3)
    graph.add_node(print_node)

    # Create connections
    conn1 = NodeConnection(
        id="conn1",
        start_socket=const1.output_sockets[0],
        end_socket=math_add.input_sockets[0],
        color=pygame.Color(100, 200, 100)
    )

    conn2 = NodeConnection(
        id="conn2",
        start_socket=const2.output_sockets[0],
        end_socket=math_add.input_sockets[1],
        color=pygame.Color(100, 200, 100)
    )

    conn3 = NodeConnection(
        id="conn3",
        start_socket=math_add.output_sockets[0],
        end_socket=math_multiply.input_sockets[0],
        color=pygame.Color(100, 200, 100)
    )

    conn4 = NodeConnection(
        id="conn4",
        start_socket=const3.output_sockets[0],
        end_socket=math_multiply.input_sockets[1],
        color=pygame.Color(100, 200, 100)
    )

    # Add connections
    graph.add_connection(conn1)
    graph.add_connection(conn2)
    graph.add_connection(conn3)
    graph.add_connection(conn4)

    return graph


def main():
    """Example demonstration of the Node Editor Panel"""
    pygame.init()
    screen = pygame.display.set_mode((1200, 800))
    pygame.display.set_caption("Node Editor Panel Demo")
    clock = pygame.time.Clock()

    # Create manager with theme
    manager = pygame_gui.UIManager((1200, 800), NODE_EDITOR_THEME)

    # Configure node editor
    config = NodeEditorConfig()
    config.show_grid = True
    config.snap_to_grid = False
    config.allow_multiple_selection = True

    # Create node editor
    node_editor = NodeEditorPanel(
        pygame.Rect(50, 50, 800, 600),
        manager,
        config,
        object_id=ObjectID(object_id='#main_editor', class_id='@node_panel')
    )

    # Create context menu handler
    context_menu = NodeEditorContextMenu(manager, node_editor)

    # Load sample graph
    sample_graph = create_sample_graph()
    node_editor.graph = sample_graph
    node_editor.update_viewport()
    node_editor.rebuild_image()

    # Instructions
    print("\nNode Editor Panel Demo")
    print("\nFeatures:")
    print("- Visual node graph with bezier connections")
    print("- Zoom and pan navigation (mouse wheel + middle mouse)")
    print("- Node selection and dragging")
    print("- CONNECTION SELECTION AND DELETION")
    print("- Socket-based connections with type checking")
    print("- Multiple node types (Math, Constants, Functions)")

    print("\nControls:")
    print("- Left click: Select nodes/connections, drag nodes, create connections")
    print("- Left click on connections: Select connections (yellow highlight)")
    print("- Middle mouse: Pan view")
    print("- Mouse wheel: Zoom in/out")
    print("- Ctrl+click: Multi-select nodes and connections")
    print("- Right click: Context menu")
    print("- Delete: Remove selected nodes AND connections")
    print("- Ctrl+A: Select all nodes")
    print("- F: Frame all nodes")
    print("- G: Toggle grid")

    print("\nPress N to add new node")
    print("Press C to clear graph")
    print("Press S to save graph data")
    print("Press L to load sample graph")
    print("Press X to demonstrate connection selection\n")

    running = True
    node_counter = 10

    while running:
        time_delta = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif context_menu.process_event(event):
                continue

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_n:
                    # Add new random node
                    import random
                    node_types = ["add", "multiply", "sin", "cos"]
                    operation = random.choice(node_types)

                    new_node = MathNode(f"node_{node_counter}", operation)
                    new_node.position = (
                        random.randint(100, 600),
                        random.randint(100, 400)
                    )

                    node_editor.add_node(new_node)
                    node_counter += 1
                    print(f"Added new {operation} node")

                elif event.key == pygame.K_c:
                    # Clear graph
                    node_editor.clear_graph()
                    print("Cleared graph")

                elif event.key == pygame.K_s:
                    # Save graph data
                    graph_data = node_editor.get_graph_data()
                    print(f"Graph data: {len(graph_data['nodes'])} nodes, {len(graph_data['connections'])} connections")

                elif event.key == pygame.K_l:
                    # Load sample graph
                    node_editor.clear_graph()
                    sample_graph = create_sample_graph()
                    node_editor.graph = sample_graph
                    node_editor.update_viewport()
                    node_editor.rebuild_image()
                    print("Loaded sample graph")

                elif event.key == pygame.K_x:
                    # Demonstrate connection selection
                    if node_editor.graph.connections:
                        first_conn_id = next(iter(node_editor.graph.connections.keys()))
                        node_editor.select_connection(first_conn_id)
                        print(f"Selected connection: {first_conn_id}")
                    else:
                        print("No connections to select")

            # Handle context menu
            elif event.type == pygame.KEYDOWN and node_editor.is_focused:
                if event.key == pygame.K_c and (
                        pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]):
                    # Copy selected nodes
                    selected_nodes = node_editor.get_selected_nodes()
                    if selected_nodes:
                        context_menu.clipboard.copy_nodes(selected_nodes)
                        print(f"Copied {len(selected_nodes)} nodes")

                elif event.key == pygame.K_v and (
                        pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]):
                    # Paste nodes
                    if context_menu.clipboard.has_nodes():
                        new_node_ids = context_menu.clipboard.paste_nodes(node_editor)
                        if new_node_ids:
                            print(f"Pasted {len(new_node_ids)} nodes")
                            # Select the newly pasted nodes
                            node_editor.clear_selection()
                            for node_id in new_node_ids:
                                node_editor.select_node(node_id)

                elif event.key == pygame.K_p and (
                        pygame.key.get_pressed()[pygame.K_LCTRL] or pygame.key.get_pressed()[pygame.K_RCTRL]):
                    # Show properties for selected node
                    if len(node_editor.selected_nodes) == 1:
                        node_id = next(iter(node_editor.selected_nodes))
                        context_menu._show_node_properties(node_id)


            # Handle node editor events
            elif event.type == UI_NODE_SELECTED:
                if NODE_EDITOR_DEBUG:
                    print(f"Node selected: {event.node.title}")

            elif event.type == UI_NODE_DESELECTED:
                if NODE_EDITOR_DEBUG:
                    print(f"Node deselected: {event.node.title}")

            elif event.type == UI_NODE_MOVED:
                if NODE_EDITOR_DEBUG:
                    print(f"Node moved: {event.node.title} to {event.position}")

            elif event.type == UI_NODE_DELETED:
                if NODE_EDITOR_DEBUG:
                    print(f"Node deleted: {event.node_id}")

            elif event.type == UI_NODE_ADDED:
                if NODE_EDITOR_DEBUG:
                    print(f"Node added: {event.node.title}")

            elif event.type == UI_CONNECTION_CREATED:
                if NODE_EDITOR_DEBUG:
                    print(
                        f"Connection created: {event.connection.start_socket.label} -> {event.connection.end_socket.label}")

            elif event.type == UI_CONNECTION_DELETED:
                if NODE_EDITOR_DEBUG:
                    print(f"Connection deleted: {event.connection_id}")


            elif event.type == UI_NODE_RIGHT_CLICKED:
                if hasattr(event, 'node_id'):
                    # Right-clicked on a node
                    context_menu.show_context_menu(event.screen_pos, "node", event.node_id)
                elif hasattr(event, 'connection_id'):
                    # Right-clicked on a connection
                    context_menu.show_context_menu(event.screen_pos, "connection", event.connection_id)
                else:
                    # Right-clicked on background
                    context_menu.show_context_menu(event.screen_pos, "background")

            # Forward events to manager
            manager.process_events(event)

        # Update
        manager.update(time_delta)

        # Draw
        screen.fill((20, 20, 20))

        # Draw info text
        font = pygame.font.Font(None, 24)
        info_text = font.render("Node Editor Demo", True, pygame.Color(255, 255, 255))
        screen.blit(info_text, (900, 50))

        # Draw graph info
        info_font = pygame.font.Font(None, 18)
        y_offset = 100

        selected_nodes = node_editor.get_selected_nodes()
        selected_connections = node_editor.get_selected_connections()

        info_lines = [
            f"Nodes: {len(node_editor.graph.nodes)}",
            f"Connections: {len(node_editor.graph.connections)}",
            f"Selected Nodes: {len(selected_nodes)}",
            f"Selected Connections: {len(selected_connections)}",
            f"Zoom: {node_editor.zoom:.2f}",
            f"Pan: ({int(node_editor.pan_offset[0])}, {int(node_editor.pan_offset[1])})",
            "",
            "Selected Items:"
        ]

        for line in info_lines:
            color = pygame.Color(200, 200, 200)
            if "Selected Connections" in line and selected_connections:
                color = pygame.Color(255, 255, 100)  # Highlight if connections selected
            text = info_font.render(line, True, color)
            screen.blit(text, (900, y_offset))
            y_offset += 20

        # Show selected node details
        for node in selected_nodes[:3]:  # Show first 3 selected
            node_info = f"  Node: {node.title}"
            text = info_font.render(node_info, True, pygame.Color(150, 255, 150))
            screen.blit(text, (900, y_offset))
            y_offset += 18

        # Show selected connection details
        for connection in selected_connections[:3]:  # Show first 3 selected
            conn_info = f"  Conn: {connection.start_socket.label}->{connection.end_socket.label}"
            text = info_font.render(conn_info, True, pygame.Color(255, 255, 150))
            screen.blit(text, (900, y_offset))
            y_offset += 18

        total_selected = len(selected_nodes) + len(selected_connections)
        if total_selected > 6:
            more_text = f"  ... and {total_selected - 6} more"
            text = info_font.render(more_text, True, pygame.Color(150, 150, 255))
            screen.blit(text, (900, y_offset))

        context_menu.update(time_delta)
        manager.draw_ui(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()