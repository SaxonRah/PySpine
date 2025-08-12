import json
import copy
import math
from enum import Enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

import pygame


# ============================================================================
# CORE DATA STRUCTURES
# ============================================================================

@dataclass
class ViewportState:
    offset: List[float] = field(default_factory=lambda: [0, 0])
    zoom: float = 1.0
    dragging: bool = False
    last_mouse_pos: Tuple[int, int] = (0, 0)


@dataclass
class UIState:
    panels: Dict[str, Any] = field(default_factory=dict)
    selected_objects: Dict[str, List[str]] = field(default_factory=dict)
    active_tool: str = "select"
    scroll_positions: Dict[str, int] = field(default_factory=dict)


@dataclass
class Command:
    action: str  # create, modify, delete
    object_type: str
    object_id: str
    old_data: Any
    new_data: Any
    description: str = ""


@dataclass
class HierarchyNode:
    """Represents a node in the hierarchy tree"""
    id: str
    display_name: str
    object_type: str
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    expanded: bool = True
    level: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class PanelType(Enum):
    HIERARCHY = "hierarchy"
    PROPERTIES = "properties"
    TIMELINE = "timeline"
    PALETTE = "palette"


# ============================================================================
# UNIVERSAL EDITOR BASE CLASS
# ============================================================================

class UniversalEditor(ABC):
    """Base class for all editors with common functionality"""

    def __init__(self, width=1400, height=800):
        pygame.init()
        self.screen_size = (width, height)
        self.screen = pygame.display.set_mode(self.screen_size)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        # Core state
        self.viewport = ViewportState()
        self.ui_state = UIState()
        self.data_objects: Dict[str, Dict[str, Any]] = {}

        # Undo/redo system
        self.command_history: List[Command] = []
        self.redo_stack: List[Command] = []
        self.max_history = 50

        # Operation tracking
        self.operation_in_progress = False
        self.drag_start_data = None

        # ========================================================================
        # HIERARCHY SYSTEM
        # ========================================================================
        self.hierarchy_nodes: Dict[str, HierarchyNode] = {}
        self.hierarchy_scroll = 0
        self.hierarchy_display_items = []
        self.hierarchy_panel_width = 250

        # ========================================================================
        # NAME EDITING SYSTEM
        # ========================================================================
        self.editing_name = False
        self.editing_object_id = None
        self.editing_object_type = None
        self.editing_text = ""
        self.last_click_time = 0
        self.last_clicked_object = None
        self.double_click_timeout = 500  # milliseconds

        # ========================================================================
        # SELECTION CYCLING SYSTEM
        # ========================================================================
        self.objects_at_cursor = []
        self.selection_cycle_index = 0
        self.last_click_pos = None
        self.click_tolerance = 5
        self.selection_feedback_timer = 0

        # ========================================================================
        # PANEL MANAGEMENT
        # ========================================================================
        self.panel_configs = {
            PanelType.HIERARCHY: {
                'rect': pygame.Rect(0, 60, 250, 0),  # height set dynamically
                'visible': True,
                'scrollable': True
            },
            PanelType.PROPERTIES: {
                'rect': pygame.Rect(0, 60, 300, 0),  # positioned right, height set dynamically
                'visible': True,
                'scrollable': True
            }
        }

        # Setup editor-specific data
        self.setup_data_structures()
        self.setup_key_bindings()
        self.update_panel_positions()

    @abstractmethod
    def setup_data_structures(self):
        """Setup editor-specific data structures"""
        pass

    @abstractmethod
    def setup_key_bindings(self):
        """Setup editor-specific key bindings"""
        pass

    @abstractmethod
    def get_editor_name(self) -> str:
        """Return the editor name for display"""
        pass

    # ========================================================================
    # HIERARCHY SYSTEM
    # ========================================================================

    def build_hierarchy(self):
        """Build hierarchy from current data objects - override in subclasses"""
        self.hierarchy_nodes.clear()

        # Default implementation - flat list of all objects
        for object_type, objects in self.data_objects.items():
            for obj_id, obj_data in objects.items():
                self.add_hierarchy_node(
                    obj_id,
                    obj_id,
                    object_type,
                    metadata={'object': obj_data}
                )

    def add_hierarchy_node(self, node_id: str, display_name: str, object_type: str,
                           parent_id: Optional[str] = None, metadata: Dict[str, Any] = None):
        """Add a node to the hierarchy"""
        node = HierarchyNode(
            id=node_id,
            display_name=display_name,
            object_type=object_type,
            parent_id=parent_id,
            metadata=metadata or {}
        )

        self.hierarchy_nodes[node_id] = node

        # Update parent-child relationships
        if parent_id and parent_id in self.hierarchy_nodes:
            parent = self.hierarchy_nodes[parent_id]
            if node_id not in parent.children:
                parent.children.append(node_id)

        self.update_hierarchy_levels()

    def update_hierarchy_levels(self):
        """Update hierarchy levels for proper indentation"""

        def set_level(node_id: str, level: int):
            if node_id in self.hierarchy_nodes:
                t_node = self.hierarchy_nodes[node_id]
                t_node.level = level
                for child_id in t_node.children:
                    set_level(child_id, level + 1)

        # Set levels for root nodes
        for temp_node in self.hierarchy_nodes.values():
            if temp_node.parent_id is None:
                set_level(temp_node.id, 0)

    def get_hierarchy_display_list(self) -> List[Tuple[str, str, int, bool]]:
        """Get flattened hierarchy for display: (node_id, display_name, level, is_selected)"""
        display_list = []

        def add_node_and_children(node_id: str):
            if node_id not in self.hierarchy_nodes:
                return

            t_node = self.hierarchy_nodes[node_id]
            is_selected = self.is_object_selected(t_node.object_type, node_id)
            display_list.append((node_id, t_node.display_name, t_node.level, is_selected))

            if t_node.expanded:
                for child_id in t_node.children:
                    add_node_and_children(child_id)

        # Add root nodes
        for temp_node in self.hierarchy_nodes.values():
            if temp_node.parent_id is None:
                add_node_and_children(temp_node.id)

        return display_list

    def handle_hierarchy_click(self, pos: Tuple[int, int], hierarchy_rect: pygame.Rect):
        """Handle clicks in hierarchy panel"""
        x, y = pos

        if self.editing_name:
            self.complete_name_edit()
            return

        # Calculate which item was clicked
        item_height = 25
        scroll_offset = self.ui_state.scroll_positions.get('hierarchy', 0)

        display_list = self.get_hierarchy_display_list()

        for i, (node_id, display_name, level, is_selected) in enumerate(display_list):
            item_y = hierarchy_rect.y + 30 + i * item_height - scroll_offset

            if item_y <= y <= item_y + item_height:
                node = self.hierarchy_nodes[node_id]

                # Check for double-click
                current_time = pygame.time.get_ticks()
                is_double_click = (
                        hasattr(self, 'last_click_time') and
                        current_time - self.last_click_time < self.double_click_timeout and
                        hasattr(self, 'last_clicked_object') and
                        self.last_clicked_object == node_id
                )

                if is_double_click:
                    self.start_name_edit(node_id, node.object_type)
                else:
                    self.select_object(node.object_type, node_id)

                self.last_click_time = current_time
                self.last_clicked_object = node_id
                break

    def draw_hierarchy_panel(self, panel_rect: pygame.Rect):
        """Draw the hierarchy panel"""
        # Panel background
        pygame.draw.rect(self.screen, (200, 200, 200), panel_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), panel_rect, 2)

        # Title
        title = self.font.render("Hierarchy", True, (0, 0, 0))
        self.screen.blit(title, (panel_rect.x + 10, panel_rect.y + 5))

        # Build and display hierarchy
        self.build_hierarchy()
        display_list = self.get_hierarchy_display_list()

        item_height = 25
        scroll_offset = self.ui_state.scroll_positions.get('hierarchy', 0)

        self.hierarchy_display_items.clear()

        for i, (node_id, display_name, level, is_selected) in enumerate(display_list):
            item_y = panel_rect.y + 30 + i * item_height - scroll_offset

            if panel_rect.y < item_y < panel_rect.bottom:
                self.hierarchy_display_items.append((node_id, item_y, level))

                # Selection highlight
                if is_selected:
                    highlight_rect = pygame.Rect(panel_rect.x, item_y, panel_rect.width, item_height)
                    pygame.draw.rect(self.screen, (255, 255, 0), highlight_rect)

                # Indentation
                indent_x = panel_rect.x + 10 + level * 20

                # Object icon/type indicator
                node = self.hierarchy_nodes[node_id]
                type_color = self.get_object_type_color(node.object_type)
                icon_rect = pygame.Rect(indent_x, item_y + 5, 15, 15)
                pygame.draw.rect(self.screen, type_color, icon_rect)
                pygame.draw.rect(self.screen, (0, 0, 0), icon_rect, 1)

                # Text
                if self.editing_name and self.editing_object_id == node_id:
                    # Show editing field
                    edit_rect = pygame.Rect(indent_x + 20, item_y + 2, panel_rect.width - indent_x - 30, 20)
                    pygame.draw.rect(self.screen, (255, 255, 255), edit_rect)
                    pygame.draw.rect(self.screen, (0, 0, 0), edit_rect, 1)

                    # Show text being edited
                    edit_text = self.small_font.render(self.editing_text + "|", True, (0, 0, 0))
                    self.screen.blit(edit_text, (edit_rect.x + 2, edit_rect.y + 2))
                else:
                    # Normal text
                    color = (0, 0, 0) if is_selected else (64, 64, 64)
                    text = self.small_font.render(display_name, True, color)
                    self.screen.blit(text, (indent_x + 20, item_y + 5))

    def get_object_type_color(self, object_type: str) -> Tuple[int, int, int]:
        """Get color for object type icon - override in subclasses"""
        colors = {
            'sprites': (255, 100, 100),
            'bones': (100, 255, 100),
            'sprite_instances': (100, 100, 255),
            'animations': (255, 255, 100)
        }
        return colors.get(object_type, (128, 128, 128))

    # ========================================================================
    # NAME EDITING SYSTEM
    # ========================================================================

    def start_name_edit(self, object_id: str, object_type: str):
        """Start editing an object's name"""
        self.editing_name = True
        self.editing_object_id = object_id
        self.editing_object_type = object_type
        self.editing_text = object_id  # Default to current name

    def complete_name_edit(self):
        """Complete name editing"""
        if not self.editing_name or not self.editing_object_id:
            return

        new_name = self.editing_text.strip()
        old_name = self.editing_object_id
        object_type = self.editing_object_type

        # Validate new name
        if not new_name or new_name == old_name:
            self.cancel_name_edit()
            return

        if new_name in self.data_objects.get(object_type, {}):
            print(f"Name '{new_name}' already exists")
            self.cancel_name_edit()
            return

        # Perform rename
        if self.rename_object(object_type, old_name, new_name):
            print(f"Renamed {old_name} to {new_name}")

        self.cancel_name_edit()

    def cancel_name_edit(self):
        """Cancel name editing"""
        self.editing_name = False
        self.editing_object_id = None
        self.editing_object_type = None
        self.editing_text = ""

    def rename_object(self, object_type: str, old_name: str, new_name: str) -> bool:
        """Rename an object - override in subclasses for type-specific logic"""
        if object_type not in self.data_objects:
            return False

        if old_name not in self.data_objects[object_type]:
            return False

        # Generic rename
        obj = self.data_objects[object_type][old_name]
        del self.data_objects[object_type][old_name]

        # Update object's name property if it has one
        if hasattr(obj, 'name'):
            obj.name = new_name

        self.data_objects[object_type][new_name] = obj

        # Update selection
        selected = self.ui_state.selected_objects.get(object_type, [])
        if old_name in selected:
            selected[selected.index(old_name)] = new_name

        # Create undo command
        command = Command(
            action="modify",
            object_type="rename",
            object_id=f"{old_name}->{new_name}",
            old_data={'old_name': old_name, 'new_name': new_name, 'object': obj, 'type': object_type},
            new_data={'old_name': old_name, 'new_name': new_name, 'object': obj, 'type': object_type},
            description=f"Rename {old_name} to {new_name}"
        )

        self.command_history.append(command)
        self.redo_stack.clear()
        if len(self.command_history) > self.max_history:
            self.command_history.pop(0)

        return True

    # ========================================================================
    # SELECTION CYCLING SYSTEM
    # ========================================================================

    def get_objects_at_position(self, pos: Tuple[float, float]) -> List[Tuple[str, str, Any]]:
        """Get all objects at position - override in subclasses"""
        # Returns list of (object_type, object_id, interaction_data)
        return []

    def handle_selection_at_position(self, pos: Tuple[float, float], screen_pos: Tuple[int, int]):
        """Handle selection with cycling support"""
        # Check if this is a click in the same area
        same_area = False
        if self.last_click_pos:
            dx = screen_pos[0] - self.last_click_pos[0]
            dy = screen_pos[1] - self.last_click_pos[1]
            if math.sqrt(dx * dx + dy * dy) < self.click_tolerance:
                same_area = True

        # Get all objects at this position
        objects_at_pos = self.get_objects_at_position(pos)

        if objects_at_pos:
            if same_area and self.objects_at_cursor == objects_at_pos:
                # Cycle through objects
                self.selection_cycle_index = (self.selection_cycle_index + 1) % len(objects_at_pos)
                print(f"CYCLING: {self.selection_cycle_index + 1}/{len(objects_at_pos)} overlapping objects")
            else:
                # New area - start fresh
                self.objects_at_cursor = objects_at_pos
                self.selection_cycle_index = 0
                if len(objects_at_pos) > 1:
                    print(f"FOUND: {len(objects_at_pos)} overlapping objects. Press C to cycle.")

            # Select the object
            object_type, object_id, interaction_data = objects_at_pos[self.selection_cycle_index]
            self.select_object(object_type, object_id)
            self.selection_feedback_timer = 60
        else:
            # No objects at position
            self.clear_selection()
            self.objects_at_cursor = []
            self.selection_cycle_index = 0

        self.last_click_pos = screen_pos

    def cycle_selection(self):
        """Cycle through objects at cursor position"""
        if self.objects_at_cursor and len(self.objects_at_cursor) > 1:
            self.selection_cycle_index = (self.selection_cycle_index + 1) % len(self.objects_at_cursor)
            object_type, object_id, interaction_data = self.objects_at_cursor[self.selection_cycle_index]
            self.select_object(object_type, object_id)
            self.selection_feedback_timer = 60
            print(
                f"CYCLED to: {object_type} {object_id} [{self.selection_cycle_index + 1}/{len(self.objects_at_cursor)}]")
        else:
            print("No overlapping objects to cycle through")

    def draw_selection_feedback(self):
        """Draw selection cycling feedback"""
        if len(self.objects_at_cursor) > 1 and self.selection_feedback_timer > 0:
            object_type, object_id, _ = self.objects_at_cursor[self.selection_cycle_index]
            feedback_text = f"Selected: {object_type} {object_id} [{self.selection_cycle_index + 1}/{len(self.objects_at_cursor)}] - Press C to cycle"
            feedback_surface = self.small_font.render(feedback_text, True, (255, 255, 0))

            # Draw with background
            text_rect = feedback_surface.get_rect()
            text_rect.topleft = (10, 70)
            bg_rect = text_rect.inflate(10, 5)
            pygame.draw.rect(self.screen, (0, 0, 0), bg_rect)
            pygame.draw.rect(self.screen, (255, 255, 0), bg_rect, 1)
            self.screen.blit(feedback_surface, text_rect)

        self.selection_feedback_timer = max(0, self.selection_feedback_timer - 1)

    # ========================================================================
    # SELECTION MANAGEMENT
    # ========================================================================

    def select_object(self, object_type: str, object_id: str, multi_select: bool = False):
        """Select an object"""
        if not multi_select:
            self.ui_state.selected_objects.clear()

        if object_type not in self.ui_state.selected_objects:
            self.ui_state.selected_objects[object_type] = []

        if object_id not in self.ui_state.selected_objects[object_type]:
            self.ui_state.selected_objects[object_type].append(object_id)

    def deselect_object(self, object_type: str, object_id: str):
        """Deselect an object"""
        if object_type in self.ui_state.selected_objects:
            if object_id in self.ui_state.selected_objects[object_type]:
                self.ui_state.selected_objects[object_type].remove(object_id)

    def clear_selection(self):
        """Clear all selections"""
        self.ui_state.selected_objects.clear()

    def is_object_selected(self, object_type: str, object_id: str) -> bool:
        """Check if object is selected"""
        return object_id in self.ui_state.selected_objects.get(object_type, [])

    def get_selected_objects(self, object_type: str) -> List[str]:
        """Get selected objects of a type"""
        return self.ui_state.selected_objects.get(object_type, [])

    def get_first_selected(self, object_type: str) -> Optional[str]:
        """Get first selected object of a type"""
        selected = self.get_selected_objects(object_type)
        return selected[0] if selected else None

    # ========================================================================
    # PANEL MANAGEMENT
    # ========================================================================

    def update_panel_positions(self):
        """Update panel positions based on screen size"""
        screen_w, screen_h = self.screen.get_size()

        # Hierarchy panel (left)
        hierarchy_config = self.panel_configs[PanelType.HIERARCHY]
        hierarchy_config['rect'].width = self.hierarchy_panel_width
        hierarchy_config['rect'].height = screen_h - 60

        # Properties panel (right)
        properties_config = self.panel_configs[PanelType.PROPERTIES]
        properties_config['rect'].x = screen_w - 300
        properties_config['rect'].height = screen_h - 60

    def get_main_viewport_rect(self) -> pygame.Rect:
        """Get main viewport rectangle accounting for panels"""
        screen_w, screen_h = self.screen.get_size()
        hierarchy_width = self.hierarchy_panel_width if self.panel_configs[PanelType.HIERARCHY]['visible'] else 0
        properties_width = 300 if self.panel_configs[PanelType.PROPERTIES]['visible'] else 0

        return pygame.Rect(
            hierarchy_width, 60,
            screen_w - hierarchy_width - properties_width,
            screen_h - 60
        )

    # ========================================================================
    # OBJECT MANAGEMENT
    # ========================================================================

    def get_next_object_name(self, object_type: str, base_name: str = None) -> str:
        """Generate next available object name"""
        if base_name is None:
            base_name = object_type.rstrip('s') + "_"  # sprites -> sprite_

        if object_type not in self.data_objects:
            return f"{base_name}1"

        existing_numbers = []
        for name in self.data_objects[object_type].keys():
            if name.startswith(base_name):
                try:
                    number = int(name[len(base_name):])
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

    # ========================================================================
    # EVENT HANDLING
    # ========================================================================

    def handle_keydown(self, event) -> bool:
        """Keyboard handling"""
        # Handle text editing first
        if self.editing_name:
            if event.key == pygame.K_RETURN:
                self.complete_name_edit()
                return True
            elif event.key == pygame.K_ESCAPE:
                self.cancel_name_edit()
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.editing_text = self.editing_text[:-1]
                return True
            else:
                # Add printable characters
                if event.unicode and event.unicode.isprintable():
                    self.editing_text += event.unicode
                return True

        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]
        shift_pressed = pygame.key.get_pressed()[pygame.K_LSHIFT]

        # Universal shortcuts
        if ctrl_pressed:
            if event.key == pygame.K_s:
                self.save_project()
                return True
            elif event.key == pygame.K_l:
                self.load_project()
                return True
            elif event.key == pygame.K_z:
                self.undo()
                return True
            elif event.key == pygame.K_y:
                self.redo()
                return True

        # Selection and editing
        if event.key == pygame.K_DELETE:
            self.delete_selected()
            return True
        elif event.key == pygame.K_r:
            self.reset_viewport()
            return True
        elif event.key == pygame.K_F2:
            # F2 to rename selected object
            for object_type, selected_list in self.ui_state.selected_objects.items():
                if selected_list:
                    self.start_name_edit(selected_list[0], object_type)
                    return True
        elif event.key == pygame.K_c or (shift_pressed and event.key == pygame.K_TAB):
            self.cycle_selection()
            return True
        elif event.key == pygame.K_ESCAPE:
            self.clear_selection()
            self.cancel_name_edit()
            return True

        return False

    def handle_mouse_down(self, event):
        """Mouse down handling"""
        if event.button == 1:  # Left click
            self.handle_left_click(event.pos)
        elif event.button == 2:  # Middle click
            self.viewport.dragging = True
            self.viewport.last_mouse_pos = event.pos
        elif event.button == 3:  # Right click
            self.handle_right_click(event.pos)

    def handle_left_click(self, pos):
        """Left click handling with panel detection"""
        x, y = pos

        # Check panels first
        if self.panel_configs[PanelType.HIERARCHY]['visible']:
            hierarchy_rect = self.panel_configs[PanelType.HIERARCHY]['rect']
            if hierarchy_rect.collidepoint(pos):
                self.handle_hierarchy_click(pos, hierarchy_rect)
                return

        if self.panel_configs[PanelType.PROPERTIES]['visible']:
            properties_rect = self.panel_configs[PanelType.PROPERTIES]['rect']
            if properties_rect.collidepoint(pos):
                self.handle_properties_click(pos, properties_rect)
                return

        # Check main viewport
        viewport_rect = self.get_main_viewport_rect()
        if viewport_rect.collidepoint(pos):
            self.handle_viewport_click(pos)

    def handle_properties_click(self, pos: Tuple[int, int], properties_rect: pygame.Rect):
        """Handle clicks in properties panel - override in subclasses"""
        pass

    def handle_viewport_click(self, pos: Tuple[int, int]):
        """Handle clicks in main viewport - override in subclasses"""
        pass

    def handle_mouse_wheel(self, event):
        """Mouse wheel handling"""
        mouse_x, mouse_y = pygame.mouse.get_pos()

        # Check which panel/area is being scrolled
        if self.panel_configs[PanelType.HIERARCHY]['visible']:
            hierarchy_rect = self.panel_configs[PanelType.HIERARCHY]['rect']
            if hierarchy_rect.collidepoint((mouse_x, mouse_y)):
                scroll_key = 'hierarchy'
                if scroll_key not in self.ui_state.scroll_positions:
                    self.ui_state.scroll_positions[scroll_key] = 0
                self.ui_state.scroll_positions[scroll_key] -= event.y * 30
                self.ui_state.scroll_positions[scroll_key] = max(0, self.ui_state.scroll_positions[scroll_key])
                return

        # Main viewport zoom
        viewport_rect = self.get_main_viewport_rect()
        if viewport_rect.collidepoint((mouse_x, mouse_y)):
            zoom_factor = 1.1 if event.y > 0 else 0.9
            old_zoom = self.viewport.zoom
            self.viewport.zoom = max(0.1, min(5.0, self.viewport.zoom * zoom_factor))

            # Zoom towards mouse position
            zoom_ratio = self.viewport.zoom / old_zoom
            self.viewport.offset[0] = mouse_x - (mouse_x - self.viewport.offset[0]) * zoom_ratio
            self.viewport.offset[1] = mouse_y - (mouse_y - self.viewport.offset[1]) * zoom_ratio

    # Override these for editor-specific behavior
    def handle_left_click_release(self, pos):
        pass

    def handle_right_click(self, pos):
        pass

    def handle_right_click_release(self, pos):
        pass

    def handle_mouse_drag(self, pos):
        pass

    # ========================================================================
    # DRAWING SYSTEM
    # ========================================================================

    def draw(self):
        """Drawing pipeline"""
        self.screen.fill((64, 64, 64))  # Dark gray background

        # Update panel positions
        self.update_panel_positions()

        # Draw components
        self.draw_main_viewport()
        self.draw_panels()
        self.draw_toolbar()
        self.draw_status_info()
        self.draw_selection_feedback()

        pygame.display.flip()

    def draw_main_viewport(self):
        """Draw the main editing viewport"""
        viewport_rect = self.get_main_viewport_rect()
        pygame.draw.rect(self.screen, (0, 0, 0), viewport_rect)
        self.screen.set_clip(viewport_rect)

        self.draw_grid()
        self.draw_objects()
        self.draw_overlays()

        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, (255, 255, 255), viewport_rect, 2)

    def draw_panels(self):
        """Draw all visible panels"""
        if self.panel_configs[PanelType.HIERARCHY]['visible']:
            hierarchy_rect = self.panel_configs[PanelType.HIERARCHY]['rect']
            self.draw_hierarchy_panel(hierarchy_rect)

        if self.panel_configs[PanelType.PROPERTIES]['visible']:
            properties_rect = self.panel_configs[PanelType.PROPERTIES]['rect']
            self.draw_properties_panel(properties_rect)

    def draw_properties_panel(self, panel_rect: pygame.Rect):
        """Draw the properties panel"""
        pygame.draw.rect(self.screen, (200, 200, 200), panel_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), panel_rect, 2)

        y_offset = panel_rect.y + 10
        title = self.font.render("Properties", True, (0, 0, 0))
        self.screen.blit(title, (panel_rect.x + 10, y_offset))
        y_offset += 40

        # Undo/redo status
        y_offset = self.draw_undo_status(panel_rect, y_offset)

        # Editor-specific content
        self.draw_properties_content(panel_rect, y_offset)

    def draw_properties_content(self, panel_rect: pygame.Rect, y_offset: int):
        """Draw properties panel content - override in subclasses"""
        # Show selected objects info
        for object_type, selected_list in self.ui_state.selected_objects.items():
            if selected_list:
                for obj_id in selected_list:
                    text = self.small_font.render(f"Selected {object_type}: {obj_id}", True, (0, 0, 0))
                    self.screen.blit(text, (panel_rect.x + 10, y_offset))
                    y_offset += 20

    def draw_toolbar(self):
        """Toolbar with more info"""
        toolbar_rect = pygame.Rect(0, 0, self.screen.get_width(), 60)
        pygame.draw.rect(self.screen, (128, 128, 128), toolbar_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), toolbar_rect, 2)

        # Editor name
        name_text = self.font.render(self.get_editor_name(), True, (255, 255, 255))
        self.screen.blit(name_text, (10, 10))

        # Universal shortcuts
        shortcuts_text = "Ctrl+S: Save | Ctrl+L: Load | Ctrl+Z: Undo | Ctrl+Y: Redo | Del: Delete | F2: Rename | C: Cycle | R: Reset View"
        shortcuts_surface = self.small_font.render(shortcuts_text, True, (255, 255, 255))
        self.screen.blit(shortcuts_surface, (10, 35))

    # ========================================================================
    # UNDO/REDO WITH RENAME SUPPORT
    # ========================================================================

    def undo(self):
        """Undo with rename support"""
        if not self.command_history:
            return

        command = self.command_history.pop()
        self.redo_stack.append(command)

        # Handle rename operations specially
        if command.object_type == "rename":
            data = command.old_data
            old_name = data['old_name']
            new_name = data['new_name']
            obj = data['object']
            object_type = data['type']

            # Remove new name and restore old name
            if new_name in self.data_objects[object_type]:
                del self.data_objects[object_type][new_name]

            # Update object's name property if it has one
            if hasattr(obj, 'name'):
                obj.name = old_name

            self.data_objects[object_type][old_name] = obj

            # Update selection
            selected = self.ui_state.selected_objects.get(object_type, [])
            if new_name in selected:
                selected[selected.index(new_name)] = old_name
        else:
            # Standard undo logic
            if command.action == "create":
                if command.object_id in self.data_objects[command.object_type]:
                    del self.data_objects[command.object_type][command.object_id]
                    # Clear selection if the deleted object was selected
                    selected = self.ui_state.selected_objects.get(command.object_type, [])
                    if command.object_id in selected:
                        selected.remove(command.object_id)
            elif command.action == "modify":
                self.data_objects[command.object_type][command.object_id] = copy.deepcopy(command.old_data)
            elif command.action == "delete":
                self.data_objects[command.object_type][command.object_id] = copy.deepcopy(command.old_data)

        print(f"Undid: {command.description or command.action}")

    def execute_command(self, command: Command):
        """Execute a command and add to history"""
        # Execute the command
        if command.action == "create":
            self.data_objects[command.object_type][command.object_id] = copy.deepcopy(command.new_data)
        elif command.action == "modify":
            self.data_objects[command.object_type][command.object_id] = copy.deepcopy(command.new_data)
        elif command.action == "delete":
            if command.object_id in self.data_objects[command.object_type]:
                del self.data_objects[command.object_type][command.object_id]

        # Add to history
        self.command_history.append(command)
        self.redo_stack.clear()

        # Limit history size
        if len(self.command_history) > self.max_history:
            self.command_history.pop(0)

        print(f"Executed: {command.description or command.action}")

    def redo(self):
        """Redo the last undone command"""
        if not self.redo_stack:
            return

        command = self.redo_stack.pop()
        self.execute_command(command)
        # Remove the duplicate from history (execute_command adds it)
        self.command_history.pop()
        self.command_history.append(command)

        print(f"Redid: {command.description or command.action}")

    def complete_current_operation(self):
        """Complete any operation in progress and create undo command"""
        if self.operation_in_progress and self.drag_start_data:
            self.create_operation_command()
            self.operation_in_progress = False
            self.drag_start_data = None

    def create_operation_command(self):
        """Override in subclasses to create appropriate commands"""
        pass

    # ========================================================================
    # COORDINATE SYSTEM (unchanged)
    # ========================================================================

    def screen_to_viewport(self, pos: Tuple[int, int], toolbar_height=60) -> Tuple[float, float]:
        """Convert screen coordinates to viewport coordinates"""
        viewport_rect = self.get_main_viewport_rect()
        x = (pos[0] - viewport_rect.x - self.viewport.offset[0]) / self.viewport.zoom
        y = (pos[1] - viewport_rect.y - self.viewport.offset[1]) / self.viewport.zoom
        return x, y

    def viewport_to_screen(self, pos: Tuple[float, float]) -> Tuple[int, int]:
        """Convert viewport coordinates to screen coordinates"""
        viewport_rect = self.get_main_viewport_rect()
        x = int(pos[0] * self.viewport.zoom + self.viewport.offset[0] + viewport_rect.x)
        y = int(pos[1] * self.viewport.zoom + self.viewport.offset[1] + viewport_rect.y)
        return x, y

    def is_in_viewport(self, x: int, y: int) -> bool:
        """Check if screen coordinates are in main viewport"""
        viewport_rect = self.get_main_viewport_rect()
        return viewport_rect.collidepoint(x, y)

    def reset_viewport(self):
        """Reset viewport to default position"""
        self.viewport.offset = [50, 50]
        self.viewport.zoom = 1.0

    # ========================================================================
    # DRAWING SYSTEM (same structure)
    # ========================================================================

    def draw_grid(self):
        """Draw grid in viewport"""
        viewport_rect = self.get_main_viewport_rect()
        grid_size = int(50 * self.viewport.zoom)
        if grid_size < 10:
            return

        start_x = int(-self.viewport.offset[0] % grid_size) + viewport_rect.x
        start_y = int(-self.viewport.offset[1] % grid_size) + viewport_rect.y

        # Vertical lines
        x = start_x
        while x < viewport_rect.right:
            pygame.draw.line(self.screen, (32, 32, 32), (x, viewport_rect.y), (x, viewport_rect.bottom))
            x += grid_size

        # Horizontal lines
        y = start_y
        while y < viewport_rect.bottom:
            pygame.draw.line(self.screen, (32, 32, 32), (viewport_rect.x, y), (viewport_rect.right, y))
            y += grid_size

    def draw_undo_status(self, panel_rect, y_offset):
        """Draw undo/redo status"""
        if self.command_history:
            last_cmd = str(self.command_history[-1].description or self.command_history[-1].action)
            if len(last_cmd) > 25:
                last_cmd = last_cmd[:22] + "..."
            undo_text = f"Undo: {last_cmd}"
            color = (0, 0, 0)
        else:
            undo_text = "Undo: No actions"
            color = (128, 128, 128)

        undo_surface = self.small_font.render(undo_text, True, color)
        self.screen.blit(undo_surface, (panel_rect.x + 10, y_offset))
        y_offset += 20

        if self.redo_stack:
            next_cmd = str(self.redo_stack[-1].description or self.redo_stack[-1].action)
            if len(next_cmd) > 25:
                next_cmd = next_cmd[:22] + "..."
            redo_text = f"Redo: {next_cmd}"
            color = (0, 0, 0)
        else:
            redo_text = "Redo: No actions"
            color = (128, 128, 128)

        redo_surface = self.small_font.render(redo_text, True, color)
        self.screen.blit(redo_surface, (panel_rect.x + 10, y_offset))
        y_offset += 20

        history_text = f"History: {len(self.command_history)}/{self.max_history}"
        history_surface = self.small_font.render(history_text, True, (0, 0, 255))
        self.screen.blit(history_surface, (panel_rect.x + 10, y_offset))

        return y_offset + 40

    def draw_status_info(self):
        """Draw status information"""
        info_lines = [
            f"Zoom: {self.viewport.zoom:.1f}x",
            f"Tool: {self.ui_state.active_tool}",
        ]

        if self.operation_in_progress:
            info_lines.append("Operation in progress...")

        if self.editing_name:
            info_lines.append("Editing name...")

        for i, line in enumerate(info_lines):
            text = self.small_font.render(line, True, (255, 255, 255))
            self.screen.blit(text, (10, self.screen.get_height() - 80 + i * 20))

    # Abstract methods - override in subclasses
    @abstractmethod
    def draw_objects(self):
        """Draw all objects in the viewport"""
        pass

    def draw_overlays(self):
        """Draw overlays like selection highlights"""
        pass

    # ========================================================================
    # FILE OPERATIONS
    # ========================================================================

    def save_project(self):
        """Save project to file"""
        filename = f"{self.get_editor_name().lower().replace(' ', '_')}_project.json"
        try:
            project_data = {
                'editor_type': self.get_editor_name(),
                'data': self.serialize_data_objects(),
                'ui_state': {
                    'viewport': {
                        'offset': self.viewport.offset,
                        'zoom': self.viewport.zoom
                    },
                    'selected': self.ui_state.selected_objects,
                    'scroll_positions': self.ui_state.scroll_positions
                }
            }
            with open(filename, 'w') as f:
                json.dump(project_data, f, indent=2, default=str)
            print(f"Saved project: {filename}")
        except Exception as e:
            print(f"Save failed: {e}")

    def serialize_data_objects(self) -> Dict[str, Any]:
        """Serialize data objects for saving - override for complex objects"""
        return self.data_objects

    def load_project(self, given_filename: str = None):
        """Load project from file"""
        if given_filename is not None:
            filename = given_filename
        else:
            filename = f"{self.get_editor_name().lower().replace(' ', '_')}_project.json"
        try:
            with open(filename, 'r') as f:
                project_data = json.load(f)

            self.data_objects = self.deserialize_data_objects(project_data.get('data', {}))
            ui_state = project_data.get('ui_state', {})

            if 'viewport' in ui_state:
                self.viewport.offset = ui_state['viewport'].get('offset', [50, 50])
                self.viewport.zoom = ui_state['viewport'].get('zoom', 1.0)

            self.ui_state.selected_objects = ui_state.get('selected', {})
            self.ui_state.scroll_positions = ui_state.get('scroll_positions', {})

            # Clear undo history on load
            self.command_history.clear()
            self.redo_stack.clear()

            print(f"Loaded project: {filename}")
            return True
        except Exception as e:
            print(f"Load failed: {e}")
            return False

    def deserialize_data_objects(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Deserialize data objects from loading - override for complex objects"""
        return data

    # Override for editor-specific operations
    def delete_selected(self):
        """Delete selected objects"""
        pass

    # ========================================================================
    # MAIN LOOP (unchanged)
    # ========================================================================

    def run(self):
        """Main editor loop"""
        pygame.display.set_caption(self.get_editor_name())
        running = True
        while running:
            running = self.handle_events()
            self.draw()
            self.clock.tick(60)

        pygame.quit()

    # ========================================================================
    # EVENT HANDLING CORE (unchanged structure)
    # ========================================================================

    def handle_events(self) -> bool:
        """Universal event handling system"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            elif event.type == pygame.KEYDOWN:
                if self.handle_keydown(event):
                    continue
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self.handle_mouse_down(event)
            elif event.type == pygame.MOUSEBUTTONUP:
                self.handle_mouse_up(event)
            elif event.type == pygame.MOUSEMOTION:
                self.handle_mouse_motion(event)
            elif event.type == pygame.MOUSEWHEEL:
                self.handle_mouse_wheel(event)
        return True

    def handle_mouse_up(self, event):
        """Universal mouse up handling"""
        if event.button == 1:
            self.complete_current_operation()
            self.handle_left_click_release(event.pos)
        elif event.button == 2:
            self.viewport.dragging = False
        elif event.button == 3:
            self.handle_right_click_release(event.pos)

    def handle_mouse_motion(self, event):
        """Universal mouse motion handling"""
        # Handle viewport dragging
        if self.viewport.dragging:
            dx = event.pos[0] - self.viewport.last_mouse_pos[0]
            dy = event.pos[1] - self.viewport.last_mouse_pos[1]
            self.viewport.offset[0] += dx
            self.viewport.offset[1] += dy

        self.handle_mouse_drag(event.pos)
        self.viewport.last_mouse_pos = event.pos
