import pygame
import sys
import math
from typing import Dict, List, Tuple

from configuration import *
from data_classes import Bone, BoneEditMode, BoneLayer, AttachmentPoint

# Import the new common modules
from viewport_common import ViewportManager
from drawing_common import draw_grid, draw_panel_background, draw_text_lines
from bone_common import (
    draw_bone, draw_bone_hierarchy_connections, draw_bones_by_layer_order,
    get_all_bones_at_position, get_attachment_point_at_position
)
from file_common import save_json_project, load_json_project, serialize_dataclass_dict
from event_common import BaseEventHandler

# Import undo/redo system
from undo_redo_common import UndoRedoMixin, UndoRedoCommand
from bone_commands import (
    CreateBoneCommand, DeleteBoneCommand, MoveBoneCommand, RotateBoneCommand,
    ChangeBoneLayerCommand, ChangeAttachmentPointCommand
)

# Initialize Pygame
pygame.init()


BONE_EDITOR_NAME_VERSION = "Bone Editor v0.1"


class LoadBoneProjectCommand(UndoRedoCommand):
    """Command for loading a bone project (with full state backup)"""

    def __init__(self, editor, filename: str, description: str = ""):
        super().__init__(description or f"Load bone project {filename}")
        self.editor = editor
        self.filename = filename

        # Store old state
        self.old_bones = editor.bones.copy()
        self.old_selected_bone = editor.selected_bone

        # Try loading the new project data
        try:
            data = load_json_project(filename)
            if data:
                from file_common import deserialize_bone_data
                new_bones = {}
                for name, bone_data in data.get("bones", {}).items():
                    try:
                        new_bones[name] = deserialize_bone_data(bone_data)
                    except Exception as e:
                        print(f"Error loading bone {name}: {e}")
                        continue
                self.new_bones = new_bones
                self.load_success = True
            else:
                self.new_bones = {}
                self.load_success = False
        except Exception as e:
            self.new_bones = {}
            self.load_success = False

    def execute(self) -> None:
        if self.load_success:
            self.editor.bones = self.new_bones.copy()
            self.editor.selected_bone = None
            print(f"Loaded bone project: {self.filename}")
        else:
            print(f"Failed to load bone project: {self.filename}")

    def undo(self) -> None:
        self.editor.bones = self.old_bones.copy()
        self.editor.selected_bone = self.old_selected_bone
        print(f"Restored previous bone project state")


class ClearBonesCommand(UndoRedoCommand):
    """Command for clearing all bones"""

    def __init__(self, editor, description: str = "Clear all bones"):
        super().__init__(description)
        self.editor = editor
        self.old_bones = editor.bones.copy()
        self.old_selected_bone = editor.selected_bone

    def execute(self) -> None:
        self.editor.bones.clear()
        self.editor.selected_bone = None
        print("Cleared all bones")

    def undo(self) -> None:
        self.editor.bones = self.old_bones.copy()
        self.editor.selected_bone = self.old_selected_bone
        print(f"Restored {len(self.old_bones)} bones")


class BoneSheetEditor(BaseEventHandler, UndoRedoMixin):
    def __init__(self):
        super().__init__()
        BaseEventHandler.__init__(self)
        UndoRedoMixin.__init__(self)

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(f"{BONE_EDITOR_NAME_VERSION}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)
        self.tiny_font = pygame.font.Font(None, 14)

        # State
        self.bones: Dict[str, Bone] = {}
        self.edit_mode = BoneEditMode.BONE_CREATION
        self.selected_bone = None

        # Bone creation/editing
        self.creating_bone = False
        self.bone_start_pos = None
        self.dragging_bone_start = False
        self.dragging_bone_end = False
        self.dragging_bone_body = False
        self.drag_offset = (0, 0)

        # UNDO/REDO: Operation tracking
        self.operation_in_progress = False
        self.drag_start_position = None
        self.drag_start_angle_length = None
        self.drag_start_bounds = None

        # Selection cycling system
        self.bones_at_cursor = []
        self.selection_cycle_index = 0
        self.last_click_pos = None
        self.click_tolerance = 3
        self.selection_feedback_timer = 0

        # Hierarchy drag and drop
        self.dragging_hierarchy_bone = False
        self.hierarchy_drag_bone = None
        self.hierarchy_drag_offset = (0, 0)
        self.hierarchy_drop_target = None
        self.hierarchy_drop_position = "child"

        # UI state
        self.hierarchy_scroll = 0
        self.hierarchy_display_items: List[Tuple[str, int, int, int]] = []

        # Initialize viewport manager
        initial_offset = [HIERARCHY_PANEL_WIDTH + 50, TOOLBAR_HEIGHT + 50]
        self.viewport_manager = ViewportManager(initial_offset)

        # Setup undo/redo key handlers
        self.setup_undo_redo_keys()

        # Setup additional bone editor specific key handlers
        self.setup_bone_editor_keys()

    def setup_bone_editor_keys(self):
        """Setup bone editor specific keyboard shortcuts"""
        self.key_handlers.update({
            (pygame.K_1, None): lambda: setattr(self, 'edit_mode', BoneEditMode.BONE_CREATION),
            (pygame.K_2, None): lambda: setattr(self, 'edit_mode', BoneEditMode.BONE_EDITING),
            # Layer management shortcuts
            (pygame.K_4, None): self._set_bone_layer_behind,
            (pygame.K_5, None): self._set_bone_layer_middle,
            (pygame.K_6, None): self._set_bone_layer_front,
            (pygame.K_TAB, None): self._cycle_bone_layer,
            # Layer ordering shortcuts
            (pygame.K_PAGEUP, None): self._increase_layer_order,
            (pygame.K_PAGEDOWN, None): self._decrease_layer_order,
            (pygame.K_UP, pygame.K_LSHIFT): self._increase_layer_order,
            (pygame.K_DOWN, pygame.K_LSHIFT): self._decrease_layer_order,
            # Selection cycling
            (pygame.K_TAB, pygame.K_LSHIFT): self._cycle_selection,
            (pygame.K_c, None): self._cycle_selection,
            # Attachment point switching
            (pygame.K_a, None): self._toggle_attachment_point,
            # File operations (undoable)
            (pygame.K_n, pygame.K_LCTRL): self._create_new_bone,
            (pygame.K_x, pygame.K_LCTRL): self._clear_all_bones,
        })

    def _complete_current_operation(self):
        """Complete any operation that's in progress and create undo command"""
        if not self.operation_in_progress or not self.selected_bone or self.selected_bone not in self.bones:
            return

        bone = self.bones[self.selected_bone]

        if self.dragging_bone_end and self.drag_start_angle_length:
            # Complete rotation/resize operation
            old_angle, old_length = self.drag_start_angle_length
            new_angle, new_length = bone.angle, bone.length

            if abs(old_angle - new_angle) > 0.1 or abs(old_length - new_length) > 0.1:
                rotate_command = RotateBoneCommand(
                    bone, old_angle, new_angle, old_length, new_length,
                    self._update_child_bone_positions,
                    f"Rotate/Resize {bone.name}"
                )
                # Add command to history without executing (already performed during drag)
                self.undo_manager.undo_stack.append(rotate_command)
                self.undo_manager.redo_stack.clear()
                print(f"Recorded rotate command: {rotate_command}")

        elif (self.dragging_bone_start or self.dragging_bone_body) and self.drag_start_position:
            # Complete move operation
            old_pos = self.drag_start_position
            new_pos = (bone.x, bone.y)

            if abs(old_pos[0] - new_pos[0]) > 0.1 or abs(old_pos[1] - new_pos[1]) > 0.1:
                move_command = MoveBoneCommand(
                    bone, old_pos, new_pos,
                    self._update_child_bone_positions,
                    f"Move {bone.name}"
                )
                # Add command to history without executing (already performed during drag)
                self.undo_manager.undo_stack.append(move_command)
                self.undo_manager.redo_stack.clear()
                print(f"Recorded move command: {move_command}")

        # Clear operation state
        self.operation_in_progress = False
        self.drag_start_position = None
        self.drag_start_angle_length = None
        self.drag_start_bounds = None

    # Layer management methods (now undoable)
    def _set_bone_layer_behind(self):
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            old_layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            old_order = getattr(bone, 'layer_order', 0)

            if old_layer != BoneLayer.BEHIND:
                layer_command = ChangeBoneLayerCommand(
                    bone, old_layer, BoneLayer.BEHIND, old_order, old_order,
                    f"Set {bone.name} to BEHIND layer"
                )
                self.execute_command(layer_command)

    def _set_bone_layer_middle(self):
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            old_layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            old_order = getattr(bone, 'layer_order', 0)

            if old_layer != BoneLayer.MIDDLE:
                layer_command = ChangeBoneLayerCommand(
                    bone, old_layer, BoneLayer.MIDDLE, old_order, old_order,
                    f"Set {bone.name} to MIDDLE layer"
                )
                self.execute_command(layer_command)

    def _set_bone_layer_front(self):
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            old_layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            old_order = getattr(bone, 'layer_order', 0)

            if old_layer != BoneLayer.FRONT:
                layer_command = ChangeBoneLayerCommand(
                    bone, old_layer, BoneLayer.FRONT, old_order, old_order,
                    f"Set {bone.name} to FRONT layer"
                )
                self.execute_command(layer_command)

    def _cycle_bone_layer(self):
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            current_layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            current_order = getattr(bone, 'layer_order', 0)

            if current_layer == BoneLayer.BEHIND:
                new_layer = BoneLayer.MIDDLE
            elif current_layer == BoneLayer.MIDDLE:
                new_layer = BoneLayer.FRONT
            else:  # FRONT
                new_layer = BoneLayer.BEHIND

            layer_command = ChangeBoneLayerCommand(
                bone, current_layer, new_layer, current_order, current_order,
                f"Cycle {bone.name} to {new_layer.value.upper()} layer"
            )
            self.execute_command(layer_command)

    def _increase_layer_order(self):
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            current_layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            old_order = getattr(bone, 'layer_order', 0)
            new_order = old_order + 1

            layer_command = ChangeBoneLayerCommand(
                bone, current_layer, current_layer, old_order, new_order,
                f"Increase {bone.name} layer order"
            )
            self.execute_command(layer_command)

    def _decrease_layer_order(self):
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            current_layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            old_order = getattr(bone, 'layer_order', 0)
            new_order = max(0, old_order - 1)

            if new_order != old_order:
                layer_command = ChangeBoneLayerCommand(
                    bone, current_layer, current_layer, old_order, new_order,
                    f"Decrease {bone.name} layer order"
                )
                self.execute_command(layer_command)

    def _toggle_attachment_point(self):
        """Toggle attachment point of selected bone between START and END (undoable)"""
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            if bone.parent:
                old_attachment = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)
                new_attachment = AttachmentPoint.START if old_attachment == AttachmentPoint.END else AttachmentPoint.END

                attachment_command = ChangeAttachmentPointCommand(
                    bone, old_attachment, new_attachment, self._update_bone_attachment_position,
                    f"Toggle {bone.name} attachment point"
                )
                self.execute_command(attachment_command)
            else:
                print("Selected bone has no parent - cannot change attachment point")

    def _cycle_selection(self):
        """Cycle through bones at the current cursor position"""
        if self.bones_at_cursor and len(self.bones_at_cursor) > 1:
            self.selection_cycle_index = (self.selection_cycle_index + 1) % len(self.bones_at_cursor)
            bone_name, interaction_type, _ = self.bones_at_cursor[self.selection_cycle_index]
            self.selected_bone = bone_name
            self.selection_feedback_timer = 60

            interaction_desc = {
                "end": "ENDPOINT (resize/rotate)",
                "start": "STARTPOINT (move base)",
                "body": "BODY (move entire bone)"
            }

            print(
                f"CYCLED to: {bone_name} - {interaction_desc[interaction_type]} [{self.selection_cycle_index + 1}/{len(self.bones_at_cursor)}]")
        else:
            print("No overlapping elements to cycle through")

    def _create_new_bone(self):
        """Create a new bone at the center of the viewport using command system"""
        center_screen = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        center_viewport = self.viewport_manager.screen_to_viewport(center_screen, TOOLBAR_HEIGHT)
        self._create_bone_at_position(center_viewport)

    def _clear_all_bones(self):
        """Clear all bones using command system"""
        if self.bones:
            clear_command = ClearBonesCommand(self)
            self.execute_command(clear_command)

    def _create_bone_at_position(self, pos):
        """Create a new bone at the given position using command system"""
        x, y = pos
        default_length = 50

        bone_name = self._get_next_bone_name()

        # Check for attachment points
        parent_bone, attachment_point = get_attachment_point_at_position(
            self.bones, pos, self.viewport_manager.viewport_zoom, tolerance=20)

        new_bone = Bone(
            name=bone_name,
            x=x,
            y=y,
            length=default_length,
            angle=0.0,
            parent=parent_bone,
            parent_attachment_point=attachment_point if attachment_point else AttachmentPoint.END
        )

        create_command = CreateBoneCommand(self.bones, new_bone)
        self.execute_command(create_command)

        # Update parent's children and position if needed
        if parent_bone and parent_bone in self.bones:
            parent = self.bones[parent_bone]
            if bone_name not in parent.children:
                parent.children.append(bone_name)

        self.selected_bone = bone_name
        attachment_text = f" (attached to {parent_bone} {attachment_point.value})" if parent_bone else ""
        print(f"Created bone: {bone_name}{attachment_text}")

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.KEYDOWN:
                if not self.handle_keydown(event):
                    pass

            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._handle_mouse_down(event)

            elif event.type == pygame.MOUSEBUTTONUP:
                self._handle_mouse_up(event)

            elif event.type == pygame.MOUSEMOTION:
                self._handle_mouse_motion(event)

            elif event.type == pygame.MOUSEWHEEL:
                self._handle_mouse_wheel(event)

        return True

    def _handle_mouse_down(self, event):
        if event.button == 1:  # Left click
            self._handle_left_click(event.pos)
        elif event.button == 2:  # Middle click
            self.viewport_manager.dragging_viewport = True
            self.viewport_manager.last_mouse_pos = event.pos

    def _handle_mouse_up(self, event):
        """Complete any undo-enabled operations BEFORE clearing states"""
        if event.button == 1:
            # Complete current operation first
            self._complete_current_operation()

            # Handle bone creation completion
            if self.creating_bone and self.bone_start_pos:
                self._complete_bone_creation()

            # Clear all dragging states
            self.creating_bone = False
            self.dragging_bone_start = False
            self.dragging_bone_end = False
            self.dragging_bone_body = False

            if self.dragging_hierarchy_bone:
                self._complete_hierarchy_drag(event.pos)
            self.dragging_hierarchy_bone = False
            self.hierarchy_drag_bone = None
            self.hierarchy_drop_target = None

        elif event.button == 2:
            self.viewport_manager.dragging_viewport = False

    def _complete_bone_creation(self):
        """Complete bone creation and use command system"""
        if self.bone_start_pos:
            mouse_pos = pygame.mouse.get_pos()
            if self._is_in_main_viewport(mouse_pos[0], mouse_pos[1]):
                viewport_pos = self.viewport_manager.screen_to_viewport(mouse_pos, TOOLBAR_HEIGHT)

                start_x, start_y = self.bone_start_pos
                end_x, end_y = viewport_pos

                length = math.sqrt((end_x - start_x) ** 2 + (end_y - start_y) ** 2)
                angle = math.degrees(math.atan2(end_y - start_y, end_x - start_x))

                if length > 10:  # Minimum length
                    bone_name = self._get_next_bone_name()

                    # Check for attachment points
                    parent_bone, attachment_point = get_attachment_point_at_position(
                        self.bones, self.bone_start_pos, self.viewport_manager.viewport_zoom, tolerance=20)

                    new_bone = Bone(
                        name=bone_name,
                        x=start_x,
                        y=start_y,
                        length=length,
                        angle=angle,
                        parent=parent_bone,
                        parent_attachment_point=attachment_point if attachment_point else AttachmentPoint.END
                    )

                    create_command = CreateBoneCommand(self.bones, new_bone)
                    self.execute_command(create_command)

                    # Add to parent's children
                    if parent_bone and parent_bone in self.bones:
                        parent = self.bones[parent_bone]
                        if bone_name not in parent.children:
                            parent.children.append(bone_name)

                    self.selected_bone = bone_name
                    attachment_text = f" (attached to {parent_bone} {attachment_point.value})" if parent_bone else ""
                    print(f"Created bone: {bone_name}{attachment_text}")

            self.bone_start_pos = None

    def _handle_mouse_motion(self, event):
        """Handle mouse motion with proper coordinate handling"""
        self.viewport_manager.handle_drag(event.pos)

        # Handle bone manipulation during drag operations
        if self.creating_bone and self.bone_start_pos:
            pass  # Visual feedback only, no actual creation until mouse up
        elif self.dragging_bone_start and self.selected_bone:
            self._update_bone_start_drag(event.pos)
        elif self.dragging_bone_end and self.selected_bone:
            self._update_bone_end_drag(event.pos)
        elif self.dragging_bone_body and self.selected_bone:
            self._update_bone_body_drag(event.pos)
        elif self.dragging_hierarchy_bone:
            self._update_hierarchy_drag(event.pos)

        self.viewport_manager.last_mouse_pos = event.pos

    def _handle_mouse_wheel(self, event):
        mouse_x, mouse_y = pygame.mouse.get_pos()

        if self._is_in_main_viewport(mouse_x, mouse_y):
            self.viewport_manager.handle_zoom(event, (mouse_x, mouse_y))
        elif mouse_x < HIERARCHY_PANEL_WIDTH:
            self.hierarchy_scroll -= event.y * 30
            self.hierarchy_scroll = max(0, self.hierarchy_scroll)

    def _handle_left_click(self, pos):
        x, y = pos

        if x < HIERARCHY_PANEL_WIDTH:  # Hierarchy panel
            self._handle_hierarchy_panel_click(pos)
        elif x > SCREEN_WIDTH - PROPERTY_PANEL_WIDTH:  # Property panel
            self._handle_property_panel_click(pos)
        elif y < TOOLBAR_HEIGHT:  # Toolbar
            self._handle_toolbar_click(pos)
        else:  # Main viewport
            self._handle_viewport_click(pos)

    def _handle_viewport_click(self, pos):
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

        if self.edit_mode == BoneEditMode.BONE_CREATION:
            if not self.creating_bone:
                self.creating_bone = True
                self.bone_start_pos = viewport_pos

        elif self.edit_mode == BoneEditMode.BONE_EDITING:
            self._handle_bone_selection(viewport_pos, pos)

    def _handle_bone_selection(self, viewport_pos, screen_pos):
        """Handle bone selection with proper endpoint detection"""
        # Check if this is a click in the same area as the last click
        same_area = False
        if self.last_click_pos:
            dx = screen_pos[0] - self.last_click_pos[0]
            dy = screen_pos[1] - self.last_click_pos[1]
            if math.sqrt(dx * dx + dy * dy) < self.click_tolerance:
                same_area = True

        # Get all bones at this position
        bones_at_pos = get_all_bones_at_position(self.bones, viewport_pos, self.viewport_manager.viewport_zoom,
                                                 tolerance=4)

        if bones_at_pos:
            if same_area and self.bones_at_cursor == bones_at_pos:
                # Same area click - cycle through bones
                self.selection_cycle_index = (self.selection_cycle_index + 1) % len(bones_at_pos)
                print(f"CYCLING: {self.selection_cycle_index + 1}/{len(bones_at_pos)} overlapping elements")
            else:
                # New area click - start fresh
                self.bones_at_cursor = bones_at_pos
                self.selection_cycle_index = 0
                if len(bones_at_pos) > 1:
                    print(f"FOUND: {len(bones_at_pos)} overlapping elements. Click again to cycle.")

            # Select the bone and determine interaction mode
            bone_name, interaction_type, _ = bones_at_pos[self.selection_cycle_index]
            self.selected_bone = bone_name
            self.selection_feedback_timer = 60

            # Set up dragging based on interaction type and store initial state for undo
            bone = self.bones[bone_name]
            self.operation_in_progress = True

            if interaction_type == "end":
                self.dragging_bone_end = True
                self.drag_start_angle_length = (bone.angle, bone.length)
                print(f"SELECTED: {bone_name} ENDPOINT - Ready for rotation/resize")
            elif interaction_type == "start":
                self.dragging_bone_start = True
                self.drag_start_position = (bone.x, bone.y)
                print(f"SELECTED: {bone_name} STARTPOINT - Ready for position")
            else:  # body
                self.drag_offset = (viewport_pos[0] - bone.x, viewport_pos[1] - bone.y)
                self.dragging_bone_body = True
                self.drag_start_position = (bone.x, bone.y)
                print(f"SELECTED: {bone_name} BODY - Ready for moving")

        else:
            # No bones at position
            self.selected_bone = None
            self.bones_at_cursor = []
            self.selection_cycle_index = 0
            # Clear all dragging flags
            self.dragging_bone_end = False
            self.dragging_bone_start = False
            self.dragging_bone_body = False

        self.last_click_pos = screen_pos

    def _handle_hierarchy_panel_click(self, pos):
        """Handle clicks in the bone hierarchy panel using actual display positions"""
        x, y = pos

        clicked_bone = None
        for bone_name, bone_y, indent, level in self.hierarchy_display_items:
            if abs(y - bone_y) < 12:
                clicked_bone = bone_name
                break

        if clicked_bone:
            if not self.dragging_hierarchy_bone:
                self.selected_bone = clicked_bone
                print(f"Selected bone: {clicked_bone}")

                if self.edit_mode == BoneEditMode.BONE_EDITING:
                    self.dragging_hierarchy_bone = True
                    self.hierarchy_drag_bone = clicked_bone
                    self.hierarchy_drag_offset = (x - 10, y - TOOLBAR_HEIGHT - 40)
                    print(f"Started dragging {clicked_bone}")

    def _update_hierarchy_drag(self, pos):
        """Update hierarchy drag state and determine drop target"""
        if not self.dragging_hierarchy_bone or not self.hierarchy_drag_bone:
            return

        x, y = pos
        self.hierarchy_drop_target = None
        self.hierarchy_drop_position = "child"

        for bone_name, bone_y, indent, level in self.hierarchy_display_items:
            if abs(y - bone_y) < 12:
                if bone_name != self.hierarchy_drag_bone:
                    if not self._is_descendant(bone_name, self.hierarchy_drag_bone):
                        self.hierarchy_drop_target = bone_name

                        relative_y = y - bone_y
                        if relative_y < -4:
                            self.hierarchy_drop_position = "before"
                        elif relative_y > 4:
                            self.hierarchy_drop_position = "after"
                        else:
                            self.hierarchy_drop_position = "child"
                break

    def _complete_hierarchy_drag(self, pos):
        """Complete the hierarchy drag operation using commands"""
        if not self.dragging_hierarchy_bone or not self.hierarchy_drag_bone:
            return

        if self.hierarchy_drop_target:
            drag_bone = self.bones[self.hierarchy_drag_bone]
            target_bone = self.bones[self.hierarchy_drop_target]

            # Store old parent for undo
            old_parent = drag_bone.parent

            # Remove from current parent
            if drag_bone.parent and drag_bone.parent in self.bones:
                old_parent_bone = self.bones[drag_bone.parent]
                if self.hierarchy_drag_bone in old_parent_bone.children:
                    old_parent_bone.children.remove(self.hierarchy_drag_bone)

            if self.hierarchy_drop_position == "child":
                drag_bone.parent = self.hierarchy_drop_target
                if self.hierarchy_drag_bone not in target_bone.children:
                    target_bone.children.append(self.hierarchy_drag_bone)
                # Update position to match new parent
                self._update_bone_attachment_position(self.hierarchy_drag_bone)
                print(f"Made {self.hierarchy_drag_bone} a child of {self.hierarchy_drop_target}")

            elif self.hierarchy_drop_position in ["before", "after"]:
                drag_bone.parent = target_bone.parent
                if target_bone.parent and target_bone.parent in self.bones:
                    parent = self.bones[target_bone.parent]
                    try:
                        target_index = parent.children.index(self.hierarchy_drop_target)
                        if self.hierarchy_drop_position == "after":
                            target_index += 1
                        parent.children.insert(target_index, self.hierarchy_drag_bone)
                    except ValueError:
                        parent.children.append(self.hierarchy_drag_bone)
                    # Update position to match new parent
                    self._update_bone_attachment_position(self.hierarchy_drag_bone)
                print(
                    f"Made {self.hierarchy_drag_bone} a sibling of {self.hierarchy_drop_target} ({self.hierarchy_drop_position})")

            # Note: For simplicity, hierarchy changes are not easily undoable due to complexity
            # This could be implemented with a more complex command that tracks all relationship changes

    def _is_descendant(self, potential_descendant: str, ancestor: str) -> bool:
        """Check if potential_descendant is a descendant of ancestor"""
        if potential_descendant not in self.bones:
            return False

        current = self.bones[potential_descendant]
        while current.parent:
            if current.parent == ancestor:
                return True
            if current.parent not in self.bones:
                break
            current = self.bones[current.parent]
        return False

    def _handle_property_panel_click(self, pos):
        """Handle property panel clicks"""
        pass

    def _handle_toolbar_click(self, pos):
        """Handle toolbar button clicks"""
        pass

    def _update_bone_start_drag(self, pos):
        """Update bone start position - direct manipulation for responsiveness"""
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

            bone.x = viewport_pos[0]
            bone.y = viewport_pos[1]

            self._update_child_bone_positions(self.selected_bone)

    def _update_bone_end_drag(self, pos):
        """Update bone end position for rotation and length - direct manipulation"""
        if not self.selected_bone or self.selected_bone not in self.bones:
            return

        bone = self.bones[self.selected_bone]
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

        # Calculate vector from bone start to mouse position
        dx = viewport_pos[0] - bone.x
        dy = viewport_pos[1] - bone.y

        # Calculate new length and angle
        new_length = math.sqrt(dx * dx + dy * dy)
        new_angle = math.degrees(math.atan2(dy, dx))

        # Apply minimum length constraint
        if new_length > 5:  # Minimum length
            bone.length = new_length
            bone.angle = new_angle

            # Update child bone positions to maintain hierarchy
            self._update_child_bone_positions(self.selected_bone)

    def _update_bone_body_drag(self, pos):
        """Update bone position by dragging the body - direct manipulation"""
        if not self.selected_bone or self.selected_bone not in self.bones:
            return

        bone = self.bones[self.selected_bone]
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, TOOLBAR_HEIGHT)

        bone.x = viewport_pos[0] - self.drag_offset[0]
        bone.y = viewport_pos[1] - self.drag_offset[1]

        # Update child bone positions
        self._update_child_bone_positions(self.selected_bone)

    def _update_bone_attachment_position(self, bone_name):
        """Update bone position based on its attachment point"""
        if bone_name not in self.bones:
            return

        bone = self.bones[bone_name]
        if not bone.parent or bone.parent not in self.bones:
            return

        parent_bone = self.bones[bone.parent]
        attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)

        if attachment_point == AttachmentPoint.END:
            # Attach to parent's end
            bone.x = parent_bone.x + parent_bone.length * math.cos(math.radians(parent_bone.angle))
            bone.y = parent_bone.y + parent_bone.length * math.sin(math.radians(parent_bone.angle))
        else:
            # Attach to parent's start
            bone.x = parent_bone.x
            bone.y = parent_bone.y

        # Recursively update children
        self._update_child_bone_positions(bone_name)

    def _update_child_bone_positions(self, bone_name):
        """Update child bone positions recursively based on attachment points"""
        if bone_name not in self.bones:
            return

        bone = self.bones[bone_name]

        for child_name in bone.children:
            if child_name in self.bones:
                child_bone = self.bones[child_name]
                attachment_point = getattr(child_bone, 'parent_attachment_point', AttachmentPoint.END)

                if attachment_point == AttachmentPoint.END:
                    # Child attaches to this bone's end
                    child_bone.x = bone.x + bone.length * math.cos(math.radians(bone.angle))
                    child_bone.y = bone.y + bone.length * math.sin(math.radians(bone.angle))
                else:
                    # Child attaches to this bone's start
                    child_bone.x = bone.x
                    child_bone.y = bone.y

                self._update_child_bone_positions(child_name)

    def update(self):
        """Update editor state including selection feedback timer"""
        if self.selection_feedback_timer > 0:
            self.selection_feedback_timer -= 1

    @staticmethod
    def _is_in_main_viewport(x, y):
        return (HIERARCHY_PANEL_WIDTH < x < SCREEN_WIDTH - PROPERTY_PANEL_WIDTH and
                TOOLBAR_HEIGHT < y < SCREEN_HEIGHT)

    def delete_selected(self):
        """Delete selected bone using command system"""
        if self.selected_bone and self.selected_bone in self.bones:
            delete_command = DeleteBoneCommand(self.bones, self.selected_bone)
            self.execute_command(delete_command)
            self.selected_bone = None

    def reset_viewport(self):
        """Reset viewport to default position and zoom"""
        default_offset = [HIERARCHY_PANEL_WIDTH + 50, TOOLBAR_HEIGHT + 50]
        self.viewport_manager.reset_viewport(default_offset)

    def _get_next_bone_name(self):
        """Find the next available bone name"""
        base_name = "bone_"
        existing_numbers = []

        for name in self.bones.keys():
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

    def draw(self):
        self.screen.fill(DARK_GRAY)

        self._draw_main_viewport()
        self._draw_hierarchy_panel()
        self._draw_property_panel()
        self._draw_toolbar()
        self._draw_ui_info()

        pygame.display.flip()

    def _draw_main_viewport(self):
        """Draw main viewport"""
        viewport_rect = pygame.Rect(
            HIERARCHY_PANEL_WIDTH, TOOLBAR_HEIGHT,
            SCREEN_WIDTH - HIERARCHY_PANEL_WIDTH - PROPERTY_PANEL_WIDTH,
            SCREEN_HEIGHT - TOOLBAR_HEIGHT
        )
        pygame.draw.rect(self.screen, BLACK, viewport_rect)

        self.screen.set_clip(viewport_rect)

        draw_grid(self.screen, self.viewport_manager, viewport_rect, TOOLBAR_HEIGHT)
        self._draw_bones(viewport_rect)
        self._draw_creation_guides()

        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, WHITE, viewport_rect, 2)

    def _draw_bones(self, viewport_rect):
        """Draw bone hierarchy with better endpoint visualization"""
        draw_bone_hierarchy_connections(self.screen, self.viewport_manager, self.bones)
        draw_bones_by_layer_order(self.screen, self.viewport_manager, self.bones,
                                  self.selected_bone, font=self.tiny_font)

        # endpoint visualization for selected bone
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]

            # Calculate endpoint
            end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

            # Draw larger, more visible endpoints for selected bone
            start_screen = self.viewport_manager.viewport_to_screen((bone.x, bone.y), TOOLBAR_HEIGHT)
            end_screen = self.viewport_manager.viewport_to_screen((end_x, end_y), TOOLBAR_HEIGHT)

            # startpoint (blue)
            pygame.draw.circle(self.screen, BLUE, (int(start_screen[0]), int(start_screen[1])), 8)
            pygame.draw.circle(self.screen, WHITE, (int(start_screen[0]), int(start_screen[1])), 8, 2)

            # endpoint (red) - this is what you drag to rotate
            pygame.draw.circle(self.screen, RED, (int(end_screen[0]), int(end_screen[1])), 8)
            pygame.draw.circle(self.screen, WHITE, (int(end_screen[0]), int(end_screen[1])), 8, 2)

            # Draw selection state indicators
            if self.dragging_bone_end:
                pygame.draw.circle(self.screen, YELLOW, (int(end_screen[0]), int(end_screen[1])), 12, 3)
            elif self.dragging_bone_start:
                pygame.draw.circle(self.screen, YELLOW, (int(start_screen[0]), int(start_screen[1])), 12, 3)

        # Show selection cycle indicator
        if len(self.bones_at_cursor) > 1:
            cycle_text = f"Selection: {self.selection_cycle_index + 1}/{len(self.bones_at_cursor)} (Click again to cycle)"
            cycle_surface = self.small_font.render(cycle_text, True, YELLOW)
            self.screen.blit(cycle_surface, (viewport_rect.x + 10, viewport_rect.y + 10))

    def _draw_creation_guides(self):
        """Draw guides for bone creation"""
        if self.creating_bone and self.bone_start_pos:
            mouse_pos = pygame.mouse.get_pos()
            if self._is_in_main_viewport(mouse_pos[0], mouse_pos[1]):
                start_screen = self.viewport_manager.viewport_to_screen(self.bone_start_pos, TOOLBAR_HEIGHT)
                pygame.draw.line(self.screen, GREEN, start_screen, mouse_pos, 3)

                # Show potential attachment point
                parent_bone, attachment_point = get_attachment_point_at_position(
                    self.bones, self.bone_start_pos, self.viewport_manager.viewport_zoom, tolerance=20)

                if parent_bone and attachment_point:
                    attachment_text = f"Will attach to {parent_bone} {attachment_point.value}"
                    attachment_surface = self.small_font.render(attachment_text, True, CYAN)
                    self.screen.blit(attachment_surface, (start_screen[0] + 10, start_screen[1] - 20))

    def _draw_hierarchy_panel(self):
        """Draw bone hierarchy panel with drag and drop support"""
        panel_rect = pygame.Rect(0, TOOLBAR_HEIGHT, HIERARCHY_PANEL_WIDTH, SCREEN_HEIGHT - TOOLBAR_HEIGHT)
        draw_panel_background(self.screen, panel_rect)

        title = self.font.render("Bone Hierarchy", True, BLACK)
        self.screen.blit(title, (10, TOOLBAR_HEIGHT + 10))

        # undo/redo status
        y_offset = TOOLBAR_HEIGHT + 40
        y_offset = self._draw_undo_redo_status(panel_rect, y_offset)

        self.hierarchy_display_items.clear()

        y_offset = y_offset - self.hierarchy_scroll
        root_bones = [name for name, bone in self.bones.items() if bone.parent is None]

        for root_name in root_bones:
            y_offset = self._draw_bone_tree_node(root_name, 10, y_offset, 0)

        # Draw drag preview
        if self.dragging_hierarchy_bone and self.hierarchy_drag_bone:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            if mouse_x < HIERARCHY_PANEL_WIDTH:
                preview_text = self.small_font.render(f"Moving: {self.hierarchy_drag_bone}", True, YELLOW)
                self.screen.blit(preview_text, (mouse_x + 10, mouse_y - 10))

                if self.hierarchy_drop_target:
                    drop_text = f"Drop {self.hierarchy_drop_position} {self.hierarchy_drop_target}"
                    drop_surface = self.small_font.render(drop_text, True, GREEN)
                    self.screen.blit(drop_surface, (mouse_x + 10, mouse_y + 10))

    def _draw_undo_redo_status(self, panel_rect, y_offset):
        """Draw undo/redo status information with more detail"""
        # Undo status
        if self.can_undo():
            undo_color = BLACK
            last_action = str(self.undo_manager.undo_stack[-1])
            if len(last_action) > 20:
                last_action = last_action[:17] + "..."
            undo_text = f"Undo: {last_action}"
        else:
            undo_color = GRAY
            undo_text = "Undo: No actions"

        # Redo status
        if self.can_redo():
            redo_color = BLACK
            next_action = str(self.undo_manager.redo_stack[-1])
            if len(next_action) > 20:
                next_action = next_action[:17] + "..."
            redo_text = f"Redo: {next_action}"
        else:
            redo_color = GRAY
            redo_text = "Redo: No actions"

        # History count
        history_text = f"History: {len(self.undo_manager.undo_stack)}/{self.undo_manager.history_limit}"

        undo_surface = self.small_font.render(undo_text, True, undo_color)
        redo_surface = self.small_font.render(redo_text, True, redo_color)
        history_surface = self.small_font.render(history_text, True, BLUE)

        self.screen.blit(undo_surface, (panel_rect.x + 10, y_offset))
        self.screen.blit(redo_surface, (panel_rect.x + 10, y_offset + 18))
        self.screen.blit(history_surface, (panel_rect.x + 10, y_offset + 36))

        return y_offset + 60

    def _draw_bone_tree_node(self, bone_name, x, y, indent):
        """Recursively draw bone hierarchy tree with position tracking"""
        if bone_name not in self.bones or y > SCREEN_HEIGHT:
            return y

        bone = self.bones[bone_name]

        if TOOLBAR_HEIGHT < y < SCREEN_HEIGHT:
            self.hierarchy_display_items.append(
                (bone_name, y, indent, len([p for p in self._get_bone_ancestry(bone_name)])))

            if bone_name == self.selected_bone:
                highlight_rect = pygame.Rect(0, y - 2, HIERARCHY_PANEL_WIDTH, 22)
                pygame.draw.rect(self.screen, YELLOW, highlight_rect)

            if self.hierarchy_drop_target == bone_name and self.dragging_hierarchy_bone:
                drop_color = GREEN if self.hierarchy_drop_position == "child" else CYAN
                drop_rect = pygame.Rect(0, y - 2, HIERARCHY_PANEL_WIDTH, 22)
                pygame.draw.rect(self.screen, drop_color, drop_rect, 2)

            color = BLACK if bone_name == self.selected_bone else BLUE

            # Show layer, layer order, and attachment point info
            layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            layer_order = getattr(bone, 'layer_order', 0)
            attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)

            layer_char = layer.value[0].upper()
            attachment_char = attachment_point.value[0].upper() if bone.parent else ""

            layer_suffix = f"[{layer_char}{layer_order}"
            if attachment_char:
                layer_suffix += f"->{attachment_char}"
            layer_suffix += "]"

            display_text = "  " * indent + bone_name + " " + layer_suffix
            text = self.small_font.render(display_text, True, color)
            self.screen.blit(text, (x, y))

        y += 25

        for child_name in bone.children:
            y = self._draw_bone_tree_node(child_name, x, y, indent + 1)

        return y

    def _get_bone_ancestry(self, bone_name):
        """Get list of ancestors for a bone"""
        ancestry = []
        current = bone_name
        while current and current in self.bones:
            bone = self.bones[current]
            if bone.parent:
                ancestry.append(bone.parent)
                current = bone.parent
            else:
                break
        return ancestry

    def _draw_property_panel(self):
        """Draw property panel with attachment point information"""
        panel_rect = pygame.Rect(SCREEN_WIDTH - PROPERTY_PANEL_WIDTH, TOOLBAR_HEIGHT,
                                 PROPERTY_PANEL_WIDTH, SCREEN_HEIGHT - TOOLBAR_HEIGHT)
        draw_panel_background(self.screen, panel_rect)

        y_offset = TOOLBAR_HEIGHT + 20

        title = self.font.render("Properties", True, BLACK)
        self.screen.blit(title, (panel_rect.x + 10, y_offset))
        y_offset += 40

        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]

            bone_text = self.font.render(f"Bone: {bone.name}", True, BLACK)
            self.screen.blit(bone_text, (panel_rect.x + 10, y_offset))
            y_offset += 30

            # Layer information
            layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            layer_order = getattr(bone, 'layer_order', 0)
            layer_color = BLACK
            if layer == BoneLayer.BEHIND:
                layer_color = (0, 100, 200)
            elif layer == BoneLayer.FRONT:
                layer_color = (200, 0, 0)
            else:
                layer_color = (0, 150, 0)

            layer_text = self.small_font.render(f"Layer: {layer.value.upper()}", True, layer_color)
            self.screen.blit(layer_text, (panel_rect.x + 10, y_offset))
            y_offset += 20

            order_text = self.small_font.render(f"Layer Order: {layer_order}", True, BLACK)
            self.screen.blit(order_text, (panel_rect.x + 10, y_offset))
            y_offset += 25

            # Attachment point information
            if bone.parent:
                attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)
                attachment_color = (150, 0, 150) if attachment_point == AttachmentPoint.START else (0, 150, 150)
                attachment_text = self.small_font.render(f"Attaches to: {attachment_point.value.upper()}", True,
                                                         attachment_color)
                self.screen.blit(attachment_text, (panel_rect.x + 10, y_offset))
                y_offset += 25

            props = [
                f"X: {bone.x:.1f}",
                f"Y: {bone.y:.1f}",
                f"Length: {bone.length:.1f}",
                f"Angle: {bone.angle:.1f}°",
                f"Parent: {bone.parent or 'None'}",
                f"Children: {len(bone.children)}"
            ]

            y_offset = draw_text_lines(self.screen, self.small_font, props,
                                       (panel_rect.x + 10, y_offset), BLACK, 20)

        # instructions with undo/redo info
        y_offset += 30
        instructions = [
            BONE_EDITOR_NAME_VERSION,
            "",
            "UNDO/REDO:",
            "Ctrl+Z: Undo | Ctrl+Y: Redo",
            f"History: {len(self.undo_manager.undo_stack)} actions",
            "",
            "SELECTION:",
            "Click: Select bone/cycle overlaps",
            "Shift+Tab: Cycle selection",
            "Drag blue: Move start point",
            "Drag red: Resize bone",
            "Drag body: Move with children",
            "",
            "ATTACHMENT:",
            "A: Toggle attachment point",
            "Green line: Creating bone",
            "Cyan text: Attachment preview",
            "",
            "LAYER CONTROLS:",
            "4=Behind | 5=Middle | 6=Front",
            "TAB=Cycle layers",
            "PgUp/Dn=Layer order",
            "",
            "MODES:",
            "1: Create Mode | 2: Edit Mode",
            "DEL: Delete bone",
            "R: Reset view"
        ]

        for instruction in instructions:
            if instruction:
                if instruction.startswith(BONE_EDITOR_NAME_VERSION):
                    color = GREEN
                elif instruction.startswith(("ALL OPERATIONS", "UNDO/REDO", "SELECTION", "ATTACHMENT", "LAYER CONTROLS", "MODES")):
                    color = RED
                elif instruction.startswith("✓"):
                    color = GREEN
                elif instruction.startswith(("Ctrl+Z", "Ctrl+Y", "History")):
                    color = CYAN
                else:
                    color = BLACK
                text = self.small_font.render(instruction, True, color)
                self.screen.blit(text, (panel_rect.x + 10, y_offset))
            y_offset += 16

    def _draw_toolbar(self):
        """Draw toolbar with undo/redo information"""
        toolbar_rect = pygame.Rect(0, 0, SCREEN_WIDTH, TOOLBAR_HEIGHT)
        pygame.draw.rect(self.screen, GRAY, toolbar_rect)

        modes = [
            ("1 - Create Bones", BoneEditMode.BONE_CREATION),
            ("2 - Edit Bones", BoneEditMode.BONE_EDITING)
        ]

        x_offset = 10
        for text, mode in modes:
            color = YELLOW if self.edit_mode == mode else WHITE
            button_text = self.font.render(text, True, color)
            self.screen.blit(button_text, (x_offset, 10))
            x_offset += 200

        # Enhanced toolbar with undo/redo info
        file_text = self.small_font.render("Ctrl+S: Save | Ctrl+L: Load | DEL: Delete | R: Reset", True, WHITE)
        self.screen.blit(file_text, (x_offset, 5))

        undo_text = self.small_font.render("Ctrl+Z: Undo | Ctrl+Y: Redo | A: Toggle Attach | Layers: 4/5/6", True, CYAN)
        self.screen.blit(undo_text, (x_offset, 25))

    def _draw_ui_info(self):
        """Draw additional UI information with detailed undo/redo status"""
        info_lines = [
            f"{BONE_EDITOR_NAME_VERSION}",
            f"Mode: {self.edit_mode.value}",
            f"Zoom: {self.viewport_manager.viewport_zoom:.1f}x",
            f"Bones: {len(self.bones)}",
            f"Selected: {self.selected_bone or 'None'}",
            ""
        ]

        # Add undo/redo status
        if self.can_undo():
            last_action = str(self.undo_manager.undo_stack[-1])
            if len(last_action) > 40:
                last_action = last_action[:37] + "..."
            info_lines.extend([
                f"Last Action: {last_action}",
                f"Undo Stack: {len(self.undo_manager.undo_stack)} | Redo Stack: {len(self.undo_manager.redo_stack)}"
            ])
        else:
            info_lines.extend([
                "No actions to undo",
                f"History: {len(self.undo_manager.undo_stack)} actions (max: {self.undo_manager.history_limit})"
            ])

        # Add operation status
        if self.operation_in_progress:
            if self.dragging_bone_end:
                info_lines.append("ROTATING/RESIZING - Release to record in history")
            elif self.dragging_bone_start or self.dragging_bone_body:
                info_lines.append("MOVING - Release to record in history")

        # Show detailed selection state
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            info_lines.extend([
                "",
                f"Selected Bone Details:",
                f"  Position: ({bone.x:.1f}, {bone.y:.1f})",
                f"  Length: {bone.length:.1f}",
                f"  Angle: {bone.angle:.1f}°",
                f"  Parent: {bone.parent or 'None'}",
            ])

        # Show dragging state
        drag_states = []
        if self.dragging_bone_end:
            drag_states.append("ENDPOINT")
        if self.dragging_bone_start:
            drag_states.append("STARTPOINT")
        if self.dragging_bone_body:
            drag_states.append("BODY")
        if self.creating_bone:
            drag_states.append("CREATING")

        if drag_states:
            info_lines.append(f"Dragging: {', '.join(drag_states)}")

        # Show layer distribution
        behind_count = sum(1 for b in self.bones.values() if getattr(b, 'layer', BoneLayer.MIDDLE) == BoneLayer.BEHIND)
        middle_count = sum(1 for b in self.bones.values() if getattr(b, 'layer', BoneLayer.MIDDLE) == BoneLayer.MIDDLE)
        front_count = sum(1 for b in self.bones.values() if getattr(b, 'layer', BoneLayer.MIDDLE) == BoneLayer.FRONT)

        info_lines.extend([
            "",
            f"Layer Distribution:",
            f"Behind: {behind_count} | Middle: {middle_count} | Front: {front_count}",
        ])

        # Show selection cycling info
        if len(self.bones_at_cursor) > 1:
            info_lines.append(f"OVERLAPPING: {len(self.bones_at_cursor)} elements")
            if self.selection_feedback_timer > 0:
                current_bone, current_type, _ = self.bones_at_cursor[self.selection_cycle_index]
                info_lines.append(
                    f"SELECTED: {current_bone} ({current_type}) [{self.selection_cycle_index + 1}/{len(self.bones_at_cursor)}]")

        # Color-code lines
        for i, line in enumerate(info_lines):
            if line.startswith(BONE_EDITOR_NAME_VERSION):
                color = GREEN
            elif line.startswith("Last Action") and self.can_undo():
                color = CYAN
            elif line.startswith(("ROTATING", "MOVING")):
                color = ORANGE
            elif line.startswith(("Selected Bone", "Layer Distribution")):
                color = YELLOW
            elif line.startswith("OVERLAPPING"):
                color = PURPLE
            elif line == "":
                continue
            else:
                color = WHITE

            text = self.small_font.render(line, True, color)
            self.screen.blit(text, (HIERARCHY_PANEL_WIDTH + 10, SCREEN_HEIGHT - 300 + i * 14))

    def save_project(self):
        """Save the current project"""
        project_data = {
            "bones": serialize_dataclass_dict(self.bones)
        }
        save_json_project("bone_project.json", project_data, "Bone project saved successfully!")

    def load_project(self):
        """Load a project using command system"""
        load_command = LoadBoneProjectCommand(self, "bone_project.json")
        self.execute_command(load_command)

    def run(self):
        running = True
        while running:
            running = self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    editor = BoneSheetEditor()
    editor.run()