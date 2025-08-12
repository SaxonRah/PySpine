# bone_editor.py - Complete bone editor built on the base system
import pygame
import math
import os
from typing import Dict, Tuple, Optional, List, Any
from dataclasses import dataclass
from enum import Enum
from core_base import UniversalEditor, Command


@dataclass
class Bone:
    name: str
    x: float
    y: float
    length: float
    angle: float = 0.0
    parent: Optional[str] = None
    parent_attachment_point: 'AttachmentPoint' = None
    children: List[str] = None
    layer: 'BoneLayer' = None
    layer_order: int = 0

    def __post_init__(self):
        if self.children is None:
            self.children = []
        if self.parent_attachment_point is None:
            self.parent_attachment_point = AttachmentPoint.END
        if self.layer is None:
            self.layer = BoneLayer.MIDDLE


class BoneLayer(Enum):
    BEHIND = "behind"
    MIDDLE = "middle"
    FRONT = "front"


class AttachmentPoint(Enum):
    START = "start"
    END = "end"


class BoneEditMode(Enum):
    CREATION = "creation"
    EDITING = "editing"


class BoneEditor(UniversalEditor):
    """Complete bone editor implementation"""

    def __init__(self):
        super().__init__()

        # Bone-specific state
        self.edit_mode = BoneEditMode.CREATION

        # Creation state
        self.creating_bone = False
        self.bone_start_pos = None

        # Interaction state
        self.dragging_bone_start = False
        self.dragging_bone_end = False
        self.dragging_bone_body = False
        self.drag_offset = (0, 0)

        # Try to auto-load if project exists
        self.try_auto_load()

    def setup_data_structures(self):
        """Setup bone editor data structures"""
        self.data_objects = {
            'bones': {}
        }

    def setup_key_bindings(self):
        """Setup bone editor key bindings"""
        pass  # Use base class bindings

    def get_editor_name(self) -> str:
        return "Bone Editor v1.0"

    def try_auto_load(self):
        """Try to auto-load existing bone project"""
        if os.path.exists("bone_editor_v1.0_project.json"):
            self.load_project()

    # ========================================================================
    # HIERARCHY SYSTEM OVERRIDE
    # ========================================================================

    def build_hierarchy(self):
        """Build bone hierarchy from current data"""
        self.hierarchy_nodes.clear()

        # Get root bones first
        root_bones = [name for name, bone in self.data_objects['bones'].items() if bone.parent is None]

        # Add root bones to hierarchy
        for bone_name in root_bones:
            self.add_hierarchy_node(
                bone_name,
                self.format_bone_display_name(bone_name),
                'bones',
                metadata={'object': self.data_objects['bones'][bone_name]}
            )

        # Add child bones recursively
        for bone_name in root_bones:
            self.add_bone_children_to_hierarchy(bone_name)

    def add_bone_children_to_hierarchy(self, parent_name: str):
        """Recursively add bone children to hierarchy"""
        if parent_name not in self.data_objects['bones']:
            return

        parent_bone = self.data_objects['bones'][parent_name]
        for child_name in parent_bone.children:
            if child_name in self.data_objects['bones']:
                self.add_hierarchy_node(
                    child_name,
                    self.format_bone_display_name(child_name),
                    'bones',
                    parent_id=parent_name,
                    metadata={'object': self.data_objects['bones'][child_name]}
                )
                self.add_bone_children_to_hierarchy(child_name)

    def format_bone_display_name(self, bone_name: str) -> str:
        """Format bone name for display in hierarchy"""
        if bone_name not in self.data_objects['bones']:
            return bone_name

        bone = self.data_objects['bones'][bone_name]
        layer_char = bone.layer.value[0].upper()
        attachment_char = bone.parent_attachment_point.value[0].upper() if bone.parent else ""

        layer_suffix = f"[{layer_char}{bone.layer_order}"
        if attachment_char:
            layer_suffix += f"->{attachment_char}"
        layer_suffix += "]"

        return f"{bone_name} {layer_suffix}"

    def get_object_type_color(self, object_type: str) -> Tuple[int, int, int]:
        """Get color for object type icon"""
        if object_type == 'bones':
            return (100, 255, 100)
        return (128, 128, 128)

    # ========================================================================
    # SELECTION SYSTEM OVERRIDE
    # ========================================================================

    def get_objects_at_position(self, pos: Tuple[float, float]) -> List[Tuple[str, str, Any]]:
        """Get all bones at position with interaction data"""
        x, y = pos
        adjusted_tolerance = max(4, int(8 / self.viewport.zoom))

        found_objects = []

        for bone_name, bone in self.data_objects['bones'].items():
            end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

            # Check end point (highest priority)
            if math.sqrt((x - end_x) ** 2 + (y - end_y) ** 2) < adjusted_tolerance:
                found_objects.append(('bones', bone_name, {'interaction': 'end', 'priority': 0}))

            # Check start point (medium priority)
            elif math.sqrt((x - bone.x) ** 2 + (y - bone.y) ** 2) < adjusted_tolerance:
                found_objects.append(('bones', bone_name, {'interaction': 'start', 'priority': 1}))

            # Check body (lowest priority)
            else:
                dist = self.point_to_line_distance((x, y), (bone.x, bone.y), (end_x, end_y))
                if dist < adjusted_tolerance * 0.7:
                    found_objects.append(('bones', bone_name, {'interaction': 'body', 'priority': 2}))

        # Sort by priority
        found_objects.sort(key=lambda x: (x[2]['priority'], x[1]))
        return found_objects

    # ========================================================================
    # EVENT HANDLING OVERRIDES
    # ========================================================================

    def handle_keydown(self, event) -> bool:
        """Handle bone editor specific keys"""
        if super().handle_keydown(event):
            return True

        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]
        shift_pressed = pygame.key.get_pressed()[pygame.K_LSHIFT]

        # Mode switching
        if event.key == pygame.K_1:
            self.edit_mode = BoneEditMode.CREATION
            print("Switched to CREATION mode")
            return True
        elif event.key == pygame.K_2:
            self.edit_mode = BoneEditMode.EDITING
            print("Switched to EDITING mode")
            return True

        # Layer management
        elif event.key == pygame.K_4:
            self.set_selected_bone_layer(BoneLayer.BEHIND)
            return True
        elif event.key == pygame.K_5:
            self.set_selected_bone_layer(BoneLayer.MIDDLE)
            return True
        elif event.key == pygame.K_6:
            self.set_selected_bone_layer(BoneLayer.FRONT)
            return True
        elif event.key == pygame.K_TAB and not shift_pressed:
            self.cycle_selected_bone_layer()
            return True

        # Layer ordering
        elif event.key == pygame.K_PAGEUP or (shift_pressed and event.key == pygame.K_UP):
            self.change_selected_bone_layer_order(1)
            return True
        elif event.key == pygame.K_PAGEDOWN or (shift_pressed and event.key == pygame.K_DOWN):
            self.change_selected_bone_layer_order(-1)
            return True

        # Attachment point toggle
        elif event.key == pygame.K_a:
            self.toggle_selected_bone_attachment()
            return True

        # Bone creation/management
        elif ctrl_pressed and event.key == pygame.K_n:
            self.create_bone_at_center()
            return True
        elif ctrl_pressed and event.key == pygame.K_x:
            self.clear_all_bones()
            return True

        return False

    def handle_viewport_click(self, pos: Tuple[int, int]):
        """Handle clicks in the main viewport"""
        viewport_pos = self.screen_to_viewport(pos)

        if self.edit_mode == BoneEditMode.CREATION:
            if not self.creating_bone:
                # Start bone creation
                self.start_bone_creation(viewport_pos)
            # Bone completion happens on mouse up

        elif self.edit_mode == BoneEditMode.EDITING:
            self.handle_bone_selection(viewport_pos, pos)

    def handle_bone_selection(self, viewport_pos, screen_pos):
        """Handle bone selection with cycling support"""
        self.handle_selection_at_position(viewport_pos, screen_pos)

        # Set up dragging based on interaction type
        selected_bones = self.get_selected_objects('bones')
        if selected_bones:
            bone_name = selected_bones[0]
            bone = self.data_objects['bones'][bone_name]

            # Get interaction data from objects at cursor
            if self.objects_at_cursor:
                _, _, interaction_data = self.objects_at_cursor[self.selection_cycle_index]
                interaction_type = interaction_data.get('interaction', 'body')

                self.operation_in_progress = True

                if interaction_type == "end":
                    self.dragging_bone_end = True
                    self.drag_start_data = {
                        'type': 'rotate_resize',
                        'bone_name': bone_name,
                        'old_angle': bone.angle,
                        'old_length': bone.length
                    }
                    print(f"SELECTED: {bone_name} ENDPOINT - Ready for rotation/resize")
                elif interaction_type == "start":
                    self.dragging_bone_start = True
                    self.drag_start_data = {
                        'type': 'move_start',
                        'bone_name': bone_name,
                        'old_pos': (bone.x, bone.y)
                    }
                    print(f"SELECTED: {bone_name} STARTPOINT - Ready for position")
                else:  # body
                    self.drag_offset = (viewport_pos[0] - bone.x, viewport_pos[1] - bone.y)
                    self.dragging_bone_body = True
                    self.drag_start_data = {
                        'type': 'move_body',
                        'bone_name': bone_name,
                        'old_pos': (bone.x, bone.y)
                    }
                    print(f"SELECTED: {bone_name} BODY - Ready for moving")

    def handle_left_click_release(self, pos):
        """Handle left click release"""
        if self.creating_bone and self.bone_start_pos:
            self.complete_bone_creation(pos)

        # Clear interaction states
        self.creating_bone = False
        self.dragging_bone_start = False
        self.dragging_bone_end = False
        self.dragging_bone_body = False

    def handle_mouse_drag(self, pos):
        """Handle mouse dragging"""
        viewport_rect = self.get_main_viewport_rect()
        if not viewport_rect.collidepoint(pos):
            return

        viewport_pos = self.screen_to_viewport(pos)

        if self.creating_bone:
            # Visual feedback only - creation completes on mouse up
            pass
        elif self.dragging_bone_start:
            self.update_bone_start_drag(viewport_pos)
        elif self.dragging_bone_end:
            self.update_bone_end_drag(viewport_pos)
        elif self.dragging_bone_body:
            self.update_bone_body_drag(viewport_pos)

    # ========================================================================
    # BONE OPERATIONS
    # ========================================================================

    def start_bone_creation(self, pos):
        """Start creating a new bone"""
        self.creating_bone = True
        self.bone_start_pos = pos
        self.clear_selection()

    def complete_bone_creation(self, end_pos):
        """Complete bone creation"""
        if not self.bone_start_pos:
            return

        viewport_end = self.screen_to_viewport(end_pos)
        start_x, start_y = self.bone_start_pos
        end_x, end_y = viewport_end

        # Calculate length and angle
        length = math.sqrt((end_x - start_x) ** 2 + (end_y - start_y) ** 2)
        angle = math.degrees(math.atan2(end_y - start_y, end_x - start_x))

        if length > 10:  # Minimum length
            # Check for parent attachment
            parent_bone, attachment_point = self.get_attachment_point_at_position(self.bone_start_pos)

            bone_name = self.get_next_object_name('bones', 'bone_')
            new_bone = Bone(
                name=bone_name,
                x=start_x,
                y=start_y,
                length=length,
                angle=angle,
                parent=parent_bone,
                parent_attachment_point=attachment_point or AttachmentPoint.END
            )

            command = Command(
                action="create",
                object_type="bones",
                object_id=bone_name,
                old_data=None,
                new_data=new_bone,
                description=f"Create bone {bone_name}"
            )

            self.execute_command(command)

            # Update parent's children list
            if parent_bone and parent_bone in self.data_objects['bones']:
                parent = self.data_objects['bones'][parent_bone]
                if bone_name not in parent.children:
                    parent.children.append(bone_name)

            self.select_object('bones', bone_name)

            attachment_text = f" (attached to {parent_bone} {attachment_point.value})" if parent_bone else ""
            print(f"Created bone: {bone_name}{attachment_text}")

        self.bone_start_pos = None

    def update_bone_start_drag(self, pos):
        """Update bone start position while dragging"""
        selected_bones = self.get_selected_objects('bones')
        if not selected_bones:
            return

        bone = self.data_objects['bones'][selected_bones[0]]
        bone.x = pos[0]
        bone.y = pos[1]

        # Update child bone positions
        self.update_child_bone_positions(selected_bones[0])

    def update_bone_end_drag(self, pos):
        """Update bone end position (rotation and length)"""
        selected_bones = self.get_selected_objects('bones')
        if not selected_bones:
            return

        bone = self.data_objects['bones'][selected_bones[0]]

        # Calculate new length and angle
        dx = pos[0] - bone.x
        dy = pos[1] - bone.y

        new_length = math.sqrt(dx * dx + dy * dy)
        new_angle = math.degrees(math.atan2(dy, dx))

        if new_length > 5:  # Minimum length
            bone.length = new_length
            bone.angle = new_angle

            # Update child positions
            self.update_child_bone_positions(selected_bones[0])

    def update_bone_body_drag(self, pos):
        """Update bone position by dragging the body"""
        selected_bones = self.get_selected_objects('bones')
        if not selected_bones:
            return

        bone = self.data_objects['bones'][selected_bones[0]]
        bone.x = pos[0] - self.drag_offset[0]
        bone.y = pos[1] - self.drag_offset[1]

        # Update child positions
        self.update_child_bone_positions(selected_bones[0])

    def create_bone_at_center(self):
        """Create a bone at the center of the viewport"""
        viewport_rect = self.get_main_viewport_rect()
        center_screen = (viewport_rect.centerx, viewport_rect.centery)
        center_viewport = self.screen_to_viewport(center_screen)

        bone_name = self.get_next_object_name('bones', 'bone_')
        new_bone = Bone(
            name=bone_name,
            x=center_viewport[0],
            y=center_viewport[1],
            length=50,
            angle=0
        )

        command = Command(
            action="create",
            object_type="bones",
            object_id=bone_name,
            old_data=None,
            new_data=new_bone,
            description=f"Create bone {bone_name}"
        )

        self.execute_command(command)
        self.select_object('bones', bone_name)

    def clear_all_bones(self):
        """Clear all bones"""
        if not self.data_objects['bones']:
            return

        for bone_name in list(self.data_objects['bones'].keys()):
            bone = self.data_objects['bones'][bone_name]
            command = Command(
                action="delete",
                object_type="bones",
                object_id=bone_name,
                old_data=bone,
                new_data=None,
                description=f"Clear all bones"
            )
            self.execute_command(command)

        self.clear_selection()
        print(f"Cleared all bones")

    def create_operation_command(self):
        """Create undo command for completed operation"""
        if not self.drag_start_data:
            return

        data = self.drag_start_data
        bone_name = data['bone_name']
        current_bone = self.data_objects['bones'][bone_name]

        if data['type'] == 'move_start' or data['type'] == 'move_body':
            old_bone = Bone(
                name=current_bone.name,
                x=data['old_pos'][0],
                y=data['old_pos'][1],
                length=current_bone.length,
                angle=current_bone.angle,
                parent=current_bone.parent,
                parent_attachment_point=current_bone.parent_attachment_point,
                children=current_bone.children.copy(),
                layer=current_bone.layer,
                layer_order=current_bone.layer_order
            )
            command = Command(
                action="modify",
                object_type="bones",
                object_id=bone_name,
                old_data=old_bone,
                new_data=current_bone,
                description=f"Move {bone_name}"
            )
        elif data['type'] == 'rotate_resize':
            old_bone = Bone(
                name=current_bone.name,
                x=current_bone.x,
                y=current_bone.y,
                length=data['old_length'],
                angle=data['old_angle'],
                parent=current_bone.parent,
                parent_attachment_point=current_bone.parent_attachment_point,
                children=current_bone.children.copy(),
                layer=current_bone.layer,
                layer_order=current_bone.layer_order
            )
            command = Command(
                action="modify",
                object_type="bones",
                object_id=bone_name,
                old_data=old_bone,
                new_data=current_bone,
                description=f"Rotate/Resize {bone_name}"
            )
        else:
            return

        # Add to history manually
        self.command_history.append(command)
        self.redo_stack.clear()
        if len(self.command_history) > self.max_history:
            self.command_history.pop(0)

    # ========================================================================
    # BONE HIERARCHY AND RELATIONSHIPS
    # ========================================================================

    def update_child_bone_positions(self, bone_name):
        """Update child bone positions recursively"""
        if bone_name not in self.data_objects['bones']:
            return

        bone = self.data_objects['bones'][bone_name]

        for child_name in bone.children:
            if child_name in self.data_objects['bones']:
                child_bone = self.data_objects['bones'][child_name]

                # Calculate attachment position
                if child_bone.parent_attachment_point == AttachmentPoint.END:
                    # Child attaches to parent's end
                    attach_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                    attach_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
                else:
                    # Child attaches to parent's start
                    attach_x = bone.x
                    attach_y = bone.y

                child_bone.x = attach_x
                child_bone.y = attach_y

                # Recursively update grandchildren
                self.update_child_bone_positions(child_name)

    def get_attachment_point_at_position(self, pos, tolerance=20):
        """Find attachment point at position"""
        x, y = pos
        adjusted_tolerance = max(10, int(tolerance / self.viewport.zoom))

        for bone_name, bone in self.data_objects['bones'].items():
            # Check end point
            end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

            if math.sqrt((x - end_x) ** 2 + (y - end_y) ** 2) < adjusted_tolerance:
                return bone_name, AttachmentPoint.END

            # Check start point
            if math.sqrt((x - bone.x) ** 2 + (y - bone.y) ** 2) < adjusted_tolerance:
                return bone_name, AttachmentPoint.START

        return None, None

    # ========================================================================
    # LAYER MANAGEMENT
    # ========================================================================

    def set_selected_bone_layer(self, layer: BoneLayer):
        """Set layer for selected bone"""
        selected_bones = self.get_selected_objects('bones')
        if not selected_bones:
            return

        bone = self.data_objects['bones'][selected_bones[0]]
        if bone.layer != layer:
            old_bone = self.copy_bone(bone)
            bone.layer = layer

            self.create_layer_change_command(selected_bones[0], old_bone, bone)
            print(f"Set {selected_bones[0]} to {layer.value.upper()} layer")

    def cycle_selected_bone_layer(self):
        """Cycle through layers for selected bone"""
        selected_bones = self.get_selected_objects('bones')
        if not selected_bones:
            return

        bone = self.data_objects['bones'][selected_bones[0]]
        old_bone = self.copy_bone(bone)

        if bone.layer == BoneLayer.BEHIND:
            bone.layer = BoneLayer.MIDDLE
        elif bone.layer == BoneLayer.MIDDLE:
            bone.layer = BoneLayer.FRONT
        else:
            bone.layer = BoneLayer.BEHIND

        self.create_layer_change_command(selected_bones[0], old_bone, bone)
        print(f"Cycled {selected_bones[0]} to {bone.layer.value.upper()} layer")

    def change_selected_bone_layer_order(self, delta: int):
        """Change layer order for selected bone"""
        selected_bones = self.get_selected_objects('bones')
        if not selected_bones:
            return

        bone = self.data_objects['bones'][selected_bones[0]]
        old_bone = self.copy_bone(bone)
        new_order = max(0, bone.layer_order + delta)

        if new_order != bone.layer_order:
            bone.layer_order = new_order
            self.create_layer_change_command(selected_bones[0], old_bone, bone)
            print(f"Changed {selected_bones[0]} layer order to {new_order}")

    def toggle_selected_bone_attachment(self):
        """Toggle attachment point for selected bone"""
        selected_bones = self.get_selected_objects('bones')
        if not selected_bones:
            return

        bone = self.data_objects['bones'][selected_bones[0]]
        if not bone.parent:
            print("Selected bone has no parent - cannot change attachment")
            return

        old_bone = self.copy_bone(bone)
        bone.parent_attachment_point = (
            AttachmentPoint.START if bone.parent_attachment_point == AttachmentPoint.END
            else AttachmentPoint.END
        )

        # Update position based on new attachment
        self.update_bone_attachment_position(selected_bones[0])

        command = Command(
            action="modify",
            object_type="bones",
            object_id=selected_bones[0],
            old_data=old_bone,
            new_data=bone,
            description=f"Toggle {selected_bones[0]} attachment point"
        )
        self.execute_command(command)

        print(f"Toggled {selected_bones[0]} attachment to {bone.parent_attachment_point.value.upper()}")

    def update_bone_attachment_position(self, bone_name):
        """Update bone position based on attachment point"""
        if bone_name not in self.data_objects['bones']:
            return

        bone = self.data_objects['bones'][bone_name]
        if not bone.parent or bone.parent not in self.data_objects['bones']:
            return

        parent_bone = self.data_objects['bones'][bone.parent]

        if bone.parent_attachment_point == AttachmentPoint.END:
            # Attach to parent's end
            bone.x = parent_bone.x + parent_bone.length * math.cos(math.radians(parent_bone.angle))
            bone.y = parent_bone.y + parent_bone.length * math.sin(math.radians(parent_bone.angle))
        else:
            # Attach to parent's start
            bone.x = parent_bone.x
            bone.y = parent_bone.y

        # Update children
        self.update_child_bone_positions(bone_name)

    def create_layer_change_command(self, bone_name, old_bone, new_bone):
        """Create command for layer changes"""
        command = Command(
            action="modify",
            object_type="bones",
            object_id=bone_name,
            old_data=old_bone,
            new_data=new_bone,
            description=f"Change {bone_name} layer"
        )
        self.execute_command(command)

    def copy_bone(self, bone: Bone) -> Bone:
        """Create a copy of a bone"""
        return Bone(
            name=bone.name,
            x=bone.x,
            y=bone.y,
            length=bone.length,
            angle=bone.angle,
            parent=bone.parent,
            parent_attachment_point=bone.parent_attachment_point,
            children=bone.children.copy(),
            layer=bone.layer,
            layer_order=bone.layer_order
        )

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def point_to_line_distance(self, point, line_start, line_end):
        """Calculate distance from point to line segment"""
        px, py = point
        x1, y1 = line_start
        x2, y2 = line_end

        dx = x2 - x1
        dy = y2 - y1

        if dx == 0 and dy == 0:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy

        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

    def rename_object(self, object_type: str, old_name: str, new_name: str) -> bool:
        """Rename a bone with relationship updates"""
        if not super().rename_object(object_type, old_name, new_name):
            return False

        # Update parent-child relationships
        if object_type == 'bones':
            for bone in self.data_objects['bones'].values():
                # Update parent references
                if bone.parent == old_name:
                    bone.parent = new_name

                # Update children lists
                if old_name in bone.children:
                    bone.children[bone.children.index(old_name)] = new_name

        return True

    def delete_selected(self):
        """Delete selected bone"""
        selected_bones = self.get_selected_objects('bones')
        if not selected_bones:
            return

        bone_name = selected_bones[0]
        bone = self.data_objects['bones'][bone_name]

        # Handle parent-child relationships
        # Remove from parent's children
        if bone.parent and bone.parent in self.data_objects['bones']:
            parent = self.data_objects['bones'][bone.parent]
            if bone_name in parent.children:
                parent.children.remove(bone_name)

        # Update children to have this bone's parent
        for child_name in bone.children:
            if child_name in self.data_objects['bones']:
                child_bone = self.data_objects['bones'][child_name]
                child_bone.parent = bone.parent

                if bone.parent and bone.parent in self.data_objects['bones']:
                    grandparent = self.data_objects['bones'][bone.parent]
                    if child_name not in grandparent.children:
                        grandparent.children.append(child_name)

        command = Command(
            action="delete",
            object_type="bones",
            object_id=bone_name,
            old_data=bone,
            new_data=None,
            description=f"Delete bone {bone_name}"
        )

        self.execute_command(command)
        self.clear_selection()
        print(f"Deleted bone: {bone_name}")

    # ========================================================================
    # FILE OPERATIONS OVERRIDE
    # ========================================================================

    def serialize_data_objects(self) -> Dict[str, any]:
        """Serialize bones for saving"""
        return {
            'bones': {
                name: {
                    'name': bone.name,
                    'x': bone.x,
                    'y': bone.y,
                    'length': bone.length,
                    'angle': bone.angle,
                    'parent': bone.parent,
                    'parent_attachment_point': bone.parent_attachment_point.value,
                    'children': bone.children,
                    'layer': bone.layer.value,
                    'layer_order': bone.layer_order
                }
                for name, bone in self.data_objects['bones'].items()
            }
        }

    def deserialize_data_objects(self, data: Dict[str, any]) -> Dict[str, any]:
        """Deserialize bones from loading"""
        result = {'bones': {}}

        for bone_name, bone_data in data.get('bones', {}).items():
            # Handle enum fields
            if 'layer' in bone_data:
                bone_data['layer'] = BoneLayer(bone_data['layer'])
            else:
                bone_data['layer'] = BoneLayer.MIDDLE

            if 'parent_attachment_point' in bone_data:
                bone_data['parent_attachment_point'] = AttachmentPoint(bone_data['parent_attachment_point'])
            else:
                bone_data['parent_attachment_point'] = AttachmentPoint.END

            if 'children' not in bone_data:
                bone_data['children'] = []

            result['bones'][bone_name] = Bone(**bone_data)

        return result

    # ========================================================================
    # DRAWING OVERRIDES
    # ========================================================================

    def draw_objects(self):
        """Draw all bones with proper layering"""
        # Draw hierarchy connections first
        self.draw_bone_hierarchy_connections()

        # Group bones by layer
        layered_bones = {
            BoneLayer.BEHIND: [],
            BoneLayer.MIDDLE: [],
            BoneLayer.FRONT: []
        }

        for bone_name, bone in self.data_objects['bones'].items():
            layer_order = bone.layer_order
            layered_bones[bone.layer].append((layer_order, bone_name, bone))

        # Sort each layer by layer_order
        for layer in layered_bones:
            layered_bones[layer].sort(key=lambda x: x[0])

        # Draw in layer order: BEHIND -> MIDDLE -> FRONT
        selected_bones = self.get_selected_objects('bones')
        for layer in [BoneLayer.BEHIND, BoneLayer.MIDDLE, BoneLayer.FRONT]:
            for layer_order, bone_name, bone in layered_bones[layer]:
                selected = bone_name in selected_bones
                self.draw_bone(bone, selected)

    def draw_bone_hierarchy_connections(self):
        """Draw connections between parent and child bones"""
        for bone_name, bone in self.data_objects['bones'].items():
            if bone.parent and bone.parent in self.data_objects['bones']:
                parent_bone = self.data_objects['bones'][bone.parent]

                # Calculate attachment position
                if bone.parent_attachment_point == AttachmentPoint.END:
                    parent_attach_x = parent_bone.x + parent_bone.length * math.cos(math.radians(parent_bone.angle))
                    parent_attach_y = parent_bone.y + parent_bone.length * math.sin(math.radians(parent_bone.angle))
                    connection_color = (100, 100, 100)  # Gray for end attachment
                else:
                    parent_attach_x = parent_bone.x
                    parent_attach_y = parent_bone.y
                    connection_color = (150, 100, 150)  # Purple for start attachment

                parent_attach_screen = self.viewport_to_screen((parent_attach_x, parent_attach_y))
                child_start_screen = self.viewport_to_screen((bone.x, bone.y))

                pygame.draw.line(self.screen, connection_color, parent_attach_screen, child_start_screen, 2)

    def draw_bone(self, bone: Bone, selected: bool):
        """Draw a single bone with layer-based colors"""
        # Get layer-specific colors
        colors = self.get_bone_layer_colors(bone.layer, selected)

        # Calculate positions
        start_screen = self.viewport_to_screen((bone.x, bone.y))
        end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
        end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))
        end_screen = self.viewport_to_screen((end_x, end_y))

        # Draw bone line
        width = max(1, int(3 * self.viewport.zoom))
        pygame.draw.line(self.screen, colors['line'], start_screen, end_screen, width)

        # Draw joint points with CORRECTED COLORS to match sprite editor
        start_radius = max(3, int(5 * self.viewport.zoom))
        end_radius = max(3, int(5 * self.viewport.zoom))

        # Start point (RED - to match sprite origin)
        pygame.draw.circle(self.screen, (255, 0, 0),
                           (int(start_screen[0]), int(start_screen[1])), start_radius)
        pygame.draw.circle(self.screen, (255, 255, 255),
                           (int(start_screen[0]), int(start_screen[1])), start_radius, 1)

        # End point (BLUE - to match sprite endpoint)
        pygame.draw.circle(self.screen, (0, 0, 255),
                           (int(end_screen[0]), int(end_screen[1])), end_radius)
        pygame.draw.circle(self.screen, (255, 255, 255),
                           (int(end_screen[0]), int(end_screen[1])), end_radius, 1)

        # Draw labels for selected bone
        if selected and self.viewport.zoom > 0.5:
            # "S" for start (red)
            s_text = self.small_font.render("S", True, (255, 255, 255))
            s_rect = s_text.get_rect()
            s_rect.center = (int(start_screen[0]), int(start_screen[1]))
            self.screen.blit(s_text, s_rect)

            # "E" for end (blue)
            e_text = self.small_font.render("E", True, (255, 255, 255))
            e_rect = e_text.get_rect()
            e_rect.center = (int(end_screen[0]), int(end_screen[1]))
            self.screen.blit(e_text, e_rect)

        # Draw bone name and info
        if self.viewport.zoom > 0.4:
            mid_x = (start_screen[0] + end_screen[0]) / 2
            mid_y = (start_screen[1] + end_screen[1]) / 2

            # Show attachment info for child bones
            attachment_info = ""
            if bone.parent:
                attachment_char = "E" if bone.parent_attachment_point == AttachmentPoint.END else "S"
                attachment_info = f"->{attachment_char}"

            display_name = f"{bone.name}{attachment_info}"
            text_color = colors['line']
            text = self.small_font.render(display_name, True, text_color)
            self.screen.blit(text, (mid_x, mid_y - 15))

    """
    def get_bone_layer_colors(self, bone_layer: BoneLayer, selected: bool):
        "Get color scheme based on bone layer"
        if bone_layer == BoneLayer.BEHIND:
            # Blues for behind layer
            if selected:
                return {
                    'line': (0, 150, 255),  # Bright blue
                    'start': (0, 255, 255),  # Cyan
                    'end': (0, 100, 255)  # Deep blue
                }
            else:
                return {
                    'line': (0, 100, 200),  # Dark blue
                    'start': (0, 150, 255),  # Medium blue
                    'end': (0, 0, 200)  # Navy blue
                }
        elif bone_layer == BoneLayer.FRONT:
            # Reds for front layer
            if selected:
                return {
                    'line': (255, 165, 0),  # Orange
                    'start': (255, 100, 100),  # Light red
                    'end': (255, 165, 0)  # Orange
                }
            else:
                return {
                    'line': (255, 0, 0),  # Red
                    'start': (200, 0, 0),  # Dark red
                    'end': (255, 100, 0)  # Red-orange
                }
        else:  # MIDDLE (default)
            # Greens for middle layer
            if selected:
                return {
                    'line': (255, 165, 0),  # Orange for selected
                    'start': (0, 255, 255),  # Cyan for selected start
                    'end': (255, 165, 0)  # Orange for selected end
                }
            else:
                return {
                    'line': (0, 255, 0),  # Green
                    'start': (0, 0, 255),  # Blue for start
                    'end': (255, 0, 0)  # Red for end
                }
    """

    def get_bone_layer_colors(self, bone_layer: BoneLayer, selected: bool):
        """Get color scheme based on bone layer"""
        if bone_layer == BoneLayer.BEHIND:
            # Blues for behind layer
            return {
                'line': (0, 150, 255) if selected else (0, 100, 200)
            }
        elif bone_layer == BoneLayer.FRONT:
            # Reds for front layer
            return {
                'line': (255, 165, 0) if selected else (255, 0, 0)
            }
        else:  # MIDDLE (default)
            # Greens for middle layer
            return {
                'line': (255, 165, 0) if selected else (0, 255, 0)
            }
    def draw_overlays(self):
        """Draw overlays like creation guides"""
        # Draw bone creation guide
        if self.creating_bone and self.bone_start_pos:
            mouse_pos = pygame.mouse.get_pos()
            viewport_rect = self.get_main_viewport_rect()
            if viewport_rect.collidepoint(mouse_pos):
                start_screen = self.viewport_to_screen(self.bone_start_pos)
                pygame.draw.line(self.screen, (0, 255, 0), start_screen, mouse_pos, 3)

                # Show potential attachment point
                parent_bone, attachment_point = self.get_attachment_point_at_position(self.bone_start_pos)
                if parent_bone and attachment_point:
                    attachment_text = f"Will attach to {parent_bone} {attachment_point.value}"
                    text_surface = self.small_font.render(attachment_text, True, (0, 255, 255))
                    self.screen.blit(text_surface, (start_screen[0] + 10, start_screen[1] - 20))

        # Draw properties overlay
        self.draw_viewport_overlay()

    def draw_viewport_overlay(self):
        """Draw bone properties overlay in bottom right of viewport"""
        viewport_rect = self.get_main_viewport_rect()

        # Collect overlay content
        overlay_lines = []

        # Mode indicator
        mode_text = f"Mode: {self.edit_mode.value.upper()}"
        mode_color = (255, 0, 0) if self.edit_mode == BoneEditMode.CREATION else (0, 0, 255)
        overlay_lines.append((mode_text, mode_color))

        # Selected bone info
        selected_bones = self.get_selected_objects('bones')
        if selected_bones:
            bone_name = selected_bones[0]
            bone = self.data_objects['bones'][bone_name]

            overlay_lines.append((f"Bone: {bone_name}", (255, 255, 255)))

            # Layer with color
            layer_color = self.get_bone_layer_colors(bone.layer, False)['line']
            overlay_lines.append((f"Layer: {bone.layer.value.upper()}", layer_color))

            # Properties
            props = [
                f"Position: ({bone.x:.1f}, {bone.y:.1f})",
                f"Length: {bone.length:.1f}",
                f"Angle: {bone.angle:.1f}°",
                f"Parent: {bone.parent or 'None'}",
                f"Children: {len(bone.children)}",
                f"Layer Order: {bone.layer_order}"
            ]

            if bone.parent:
                props.insert(-2, f"Attachment: {bone.parent_attachment_point.value.upper()}")

            for prop in props:
                overlay_lines.append((prop, (200, 200, 200)))

        # Project stats
        stats = [
            f"Total Bones: {len(self.data_objects['bones'])}",
            f"Root Bones: {len([b for b in self.data_objects['bones'].values() if b.parent is None])}"
        ]

        # Layer distribution
        behind_count = sum(1 for b in self.data_objects['bones'].values() if b.layer == BoneLayer.BEHIND)
        middle_count = sum(1 for b in self.data_objects['bones'].values() if b.layer == BoneLayer.MIDDLE)
        front_count = sum(1 for b in self.data_objects['bones'].values() if b.layer == BoneLayer.FRONT)

        stats.append(f"Behind: {behind_count} | Middle: {middle_count} | Front: {front_count}")

        for stat in stats:
            overlay_lines.append((stat, (160, 160, 160)))

        # Calculate overlay size
        line_height = 16
        overlay_height = len(overlay_lines) * line_height + 20
        overlay_width = 280

        # Position in bottom right of viewport
        overlay_x = viewport_rect.right - overlay_width - 10
        overlay_y = viewport_rect.bottom - overlay_height - 10

        # Draw background
        overlay_rect = pygame.Rect(overlay_x, overlay_y, overlay_width, overlay_height)
        overlay_surface = pygame.Surface((overlay_width, overlay_height), pygame.SRCALPHA)
        pygame.draw.rect(overlay_surface, (0, 0, 0, 180), overlay_surface.get_rect())
        pygame.draw.rect(overlay_surface, (100, 100, 100), overlay_surface.get_rect(), 1)
        self.screen.blit(overlay_surface, (overlay_x, overlay_y))

        # Draw text lines
        y_pos = overlay_y + 10
        for text, color in overlay_lines:
            text_surface = self.small_font.render(text, True, color)
            self.screen.blit(text_surface, (overlay_x + 10, y_pos))
            y_pos += line_height

    def draw_properties_content(self, panel_rect: pygame.Rect, y_offset: int):
        """Draw shortcuts and instructions in properties panel"""
        instructions = [
            "MODES:",
            "1: Creation Mode | 2: Edit Mode",
            "",
            "CREATION MODE:",
            "• Drag to create bones",
            "• Auto-attach to nearby bones",
            "",
            "EDITING MODE:",
            "• Blue dot: Move start point",
            "• Red dot: Resize/rotate",
            "• Body: Move entire bone",
            "• C/Shift+Tab: Cycle selection",
            "",
            "LAYERS:",
            "4=Behind | 5=Middle | 6=Front",
            "Tab=Cycle | PgUp/Dn=Order",
            "",
            "ATTACHMENT:",
            "A: Toggle attachment point",
            "",
            "SHORTCUTS:",
            "Del: Delete | R: Reset view",
            "Ctrl+N: New bone",
            "Ctrl+X: Clear all"
        ]

        for instruction in instructions:
            if instruction:
                if instruction.endswith(":"):
                    color = (255, 0, 0)
                elif instruction.startswith("•"):
                    color = (0, 0, 255)
                else:
                    color = (0, 0, 0)
                text = self.small_font.render(instruction, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 16


# Run the bone editor
if __name__ == "__main__":
    editor = BoneEditor()
    editor.run()