import pygame
import pygame_gui
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

BONE_EDITOR_NAME_VERSION = "Bone Editor GUI v0.1"


class LoadBoneProjectCommand(UndoRedoCommand):
    """Command for loading a bone project (with full state backup)"""

    def __init__(self, given_editor, filename: str, description: str = ""):
        super().__init__(description or f"Load bone project {filename}")
        self.editor = given_editor
        self.filename = filename

        # Store old state
        self.old_bones = given_editor.bones.copy()
        self.old_selected_bone = given_editor.selected_bone

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
            self.editor.update_ui_elements()
            print(f"Loaded bone project: {self.filename}")
        else:
            print(f"Failed to load bone project: {self.filename}")

    def undo(self) -> None:
        self.editor.bones = self.old_bones.copy()
        self.editor.selected_bone = self.old_selected_bone
        self.editor.update_ui_elements()
        print(f"Restored previous bone project state")


class ClearBonesCommand(UndoRedoCommand):
    """Command for clearing all bones"""

    def __init__(self, given_editor, description: str = "Clear all bones"):
        super().__init__(description)
        self.editor = given_editor
        self.old_bones = given_editor.bones.copy()
        self.old_selected_bone = given_editor.selected_bone

    def execute(self) -> None:
        self.editor.bones.clear()
        self.editor.selected_bone = None
        self.editor.update_ui_elements()
        print("Cleared all bones")

    def undo(self) -> None:
        self.editor.bones = self.old_bones.copy()
        self.editor.selected_bone = self.old_selected_bone
        self.editor.update_ui_elements()
        print(f"Restored {len(self.old_bones)} bones")


class BoneSheetEditorGUI(BaseEventHandler, UndoRedoMixin):
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

        # Initialize pygame-gui
        self.ui_manager = pygame_gui.UIManager((SCREEN_WIDTH, SCREEN_HEIGHT))

        # Define layout dimensions
        self.hierarchy_panel_width = HIERARCHY_PANEL_WIDTH
        self.property_panel_width = PROPERTY_PANEL_WIDTH
        self.toolbar_height = TOOLBAR_HEIGHT
        self.main_viewport_width = SCREEN_WIDTH - self.hierarchy_panel_width - self.property_panel_width
        self.main_viewport_height = SCREEN_HEIGHT - self.toolbar_height

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
        initial_offset = [self.hierarchy_panel_width + 50, self.toolbar_height + 50]
        self.viewport_manager = ViewportManager(initial_offset)
        self.reset_viewport()

        # Create UI elements
        self._create_ui_elements()

        # Setup undo/redo key handlers
        self.setup_undo_redo_keys()

        # Setup additional bone editor specific key handlers
        self.setup_bone_editor_keys()

    def setup_bone_editor_keys(self):
        """Setup bone editor specific keyboard shortcuts"""
        self.key_handlers.update({
            (pygame.K_1, None): lambda: self._set_mode(BoneEditMode.BONE_CREATION),
            (pygame.K_2, None): lambda: self._set_mode(BoneEditMode.BONE_EDITING),
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

    def _set_mode(self, mode):
        """Set edit mode and update UI"""
        self.edit_mode = mode
        self.update_ui_elements()

    def _create_ui_elements(self):
        """Create pygame-gui UI elements"""

        # Main toolbar panel
        self.toolbar_panel = pygame_gui.elements.UIPanel(
            relative_rect=pygame.Rect(0, 0, SCREEN_WIDTH, self.toolbar_height),
            manager=self.ui_manager
        )

        # Toolbar buttons
        button_width = 100
        button_height = 20
        button_spacing = 10
        x_offset = 10
        y_offset = 10

        self.create_mode_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Create Mode',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.edit_mode_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Edit Mode',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.save_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Save Project',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.load_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Load Project',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.new_bone_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='New Bone',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += button_width + button_spacing

        self.clear_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, button_width, button_height),
            text='Clear All',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )

        # Undo/Redo buttons
        x_offset += button_width + button_spacing * 2
        self.undo_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, 80, button_height),
            text='Undo',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )
        x_offset += 80 + button_spacing

        self.redo_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x_offset, y_offset, 80, button_height),
            text='Redo',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )

        # Status label in toolbar
        self.status_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 45, 1000, 25),
            text='Ready - Click to create bones, drag to edit',
            manager=self.ui_manager,
            container=self.toolbar_panel
        )

        # Left side panel for bone hierarchy
        self.hierarchy_panel = pygame_gui.elements.UIPanel(
            relative_rect=pygame.Rect(0, self.toolbar_height,
                                      self.hierarchy_panel_width, self.main_viewport_height),
            manager=self.ui_manager
        )

        # Hierarchy title
        self.hierarchy_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 10, 200, 25),
            text='Bone Hierarchy:',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        # Bone list
        self.bone_selection_list = pygame_gui.elements.UISelectionList(
            relative_rect=pygame.Rect(10, 40, self.hierarchy_panel_width - 20, 300),
            item_list=[],
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        # Layer controls
        layer_y = 350
        self.layer_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, layer_y, 200, 25),
            text='Layer Controls:',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        layer_y += 30
        self.behind_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(10, layer_y, 70, 25),
            text='Behind',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        self.middle_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(85, layer_y, 70, 25),
            text='Middle',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        self.front_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(160, layer_y, 70, 25),
            text='Front',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        layer_y += 35
        self.layer_up_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(10, layer_y, 100, 25),
            text='Layer Up',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        self.layer_down_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(120, layer_y, 100, 25),
            text='Layer Down',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        # Delete bone button
        self.delete_bone_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(10, layer_y + 40, 100, 30),
            text='Delete',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        # Toggle attachment button
        self.toggle_attachment_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(120, layer_y + 40, 120, 30),
            text='Toggle Attach',
            manager=self.ui_manager,
            container=self.hierarchy_panel
        )

        # Right side panel for properties
        self.property_panel = pygame_gui.elements.UIPanel(
            relative_rect=pygame.Rect(SCREEN_WIDTH - self.property_panel_width, self.toolbar_height,
                                      self.property_panel_width, self.main_viewport_height),
            manager=self.ui_manager
        )

        # Properties title
        self.properties_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 10, 200, 25),
            text='Properties:',
            manager=self.ui_manager,
            container=self.property_panel
        )

        # Properties display
        self.properties_text = pygame_gui.elements.UITextBox(
            relative_rect=pygame.Rect(10, 40, self.property_panel_width - 20, 300),
            html_text='<font color="#000000">No bone selected</font>',
            manager=self.ui_manager,
            container=self.property_panel
        )

        # Instructions
        self.instructions_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 350, 200, 25),
            text='Instructions:',
            manager=self.ui_manager,
            container=self.property_panel
        )

        self.instructions_text = pygame_gui.elements.UITextBox(
            relative_rect=pygame.Rect(10, 380, self.property_panel_width - 20, 200),
            html_text=self._get_instructions_html(),
            manager=self.ui_manager,
            container=self.property_panel
        )

        # Undo/Redo history display
        self.history_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(10, 590, 200, 25),
            text='History:',
            manager=self.ui_manager,
            container=self.property_panel
        )

        self.history_text = pygame_gui.elements.UITextBox(
            relative_rect=pygame.Rect(10, 620, self.property_panel_width - 20, 100),
            html_text='<font color="#000000">No history</font>',
            manager=self.ui_manager,
            container=self.property_panel
        )

        # Initial UI update - delay this to avoid errors during initialization
        pygame.time.set_timer(pygame.USEREVENT + 1, 100)  # Update UI after 100ms

    def _get_instructions_html(self):
        """Get instructions HTML"""
        return '''<font color="#000000">
<b>BONE EDITOR GUI v0.1</b><br><br>

<b>MODES:</b><br>
- Create Mode: Click to create bones<br>
- Edit Mode: Drag to edit bones<br><br>

<b>EDITING:</b><br>
- Drag blue dot: Move start point<br>
- Drag red dot: Resize/rotate<br>
- Drag body: Move with children<br>
- Shift+Tab: Cycle overlapping<br><br>

<b>LAYERS:</b><br>
- Behind/Middle/Front buttons<br>
- Layer Up/Down for ordering<br>
- TAB: Cycle layers<br><br>

<b>SHORTCUTS:</b><br>
- 1: Create Mode | 2: Edit Mode<br>
- 4/5/6: Behind/Middle/Front<br>
- A: Toggle attachment point<br>
- DEL: Delete bone<br>
- R: Reset view<br>
- Ctrl+Z/Y: Undo/Redo<br>
</font>'''

    def update_ui_elements(self):
        """Update UI elements to reflect current state"""
        # Update bone list
        bone_names = list(self.bones.keys())
        self.bone_selection_list.set_item_list(bone_names)

        # Update properties display
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]

            # Layer information
            layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
            layer_order = getattr(bone, 'layer_order', 0)
            attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)

            properties_html = f'''<font color="#000000">
<b>Bone: {bone.name}</b><br>
Position: ({bone.x:.1f}, {bone.y:.1f})<br>
Length: {bone.length:.1f}<br>
Angle: {bone.angle:.1f}°<br>
Parent: {bone.parent or 'None'}<br>
Children: {len(bone.children)}<br><br>

<b>Layer Info:</b><br>
Layer: {layer.value.upper()}<br>
Order: {layer_order}<br>
{f"Attaches to: {attachment_point.value.upper()}<br>" if bone.parent else ""}
<br>

<b>Controls:</b><br>
- Drag endpoints to move/resize<br>
- Use layer buttons to change depth<br>
- Toggle attachment point<br>
- Drag in hierarchy to reparent<br>
</font>'''
        else:
            properties_html = f'''<font color="#000000">
<b>No bone selected</b><br><br>

<b>Usage:</b><br>
1. Switch to Create Mode<br>
2. Click to create bones<br>
3. Switch to Edit Mode<br>
4. Drag to modify bones<br>
5. Use layer controls<br>
6. Save project when done<br><br>

<b>Current Mode:</b><br>
{self.edit_mode.value.title()}<br><br>

<b>Stats:</b><br>
Bones: {len(self.bones)}<br>
Selected: {self.selected_bone or 'None'}<br>
</font>'''

        self.properties_text.set_text(properties_html)

        # Update history display
        undo_list = self.undo_manager.get_undo_list()
        redo_list = self.undo_manager.get_redo_list()

        history_html = f'<font color="#000000">'
        if undo_list:
            history_html += f'<b>Can Undo ({len(undo_list)}):</b><br>'
            for i, action in enumerate(undo_list[:3]):  # Show last 3
                history_html += f'{i + 1}. {action}<br>'
            if len(undo_list) > 3:
                history_html += f'... and {len(undo_list) - 3} more<br>'
        else:
            history_html += '<b>No undo history</b><br>'

        if redo_list:
            history_html += f'<br><b>Can Redo ({len(redo_list)}):</b><br>'
            for i, action in enumerate(redo_list[:2]):  # Show next 2
                history_html += f'{i + 1}. {action}<br>'

        history_html += '</font>'
        self.history_text.set_text(history_html)

        # Update button states
        if self.can_undo():
            self.undo_button.enable()
        else:
            self.undo_button.disable()

        if self.can_redo():
            self.redo_button.enable()
        else:
            self.redo_button.disable()

        if self.selected_bone is not None:
            self.delete_bone_button.enable()
            self.toggle_attachment_button.enable()
            self.behind_button.enable()
            self.middle_button.enable()
            self.front_button.enable()
            self.layer_up_button.enable()
            self.layer_down_button.enable()
        else:
            self.delete_bone_button.disable()
            self.toggle_attachment_button.disable()
            self.behind_button.disable()
            self.middle_button.disable()
            self.front_button.disable()
            self.layer_up_button.disable()
            self.layer_down_button.disable()

        # Update mode button appearance based on current mode
        if self.edit_mode == BoneEditMode.BONE_CREATION:
            self.create_mode_button.disable()
            self.edit_mode_button.enable()
        else:
            self.create_mode_button.enable()
            self.edit_mode_button.disable()

        # Update status
        status_text = f'Mode: {self.edit_mode.value.title()} | Bones: {len(self.bones)} | Zoom: {self.viewport_manager.viewport_zoom:.1f}x'
        if self.selected_bone:
            status_text += f' | Selected: {self.selected_bone}'
        self.status_label.set_text(status_text)

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

        # Update UI after operation
        self.update_ui_elements()

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
            self.update_ui_elements()
        else:
            print("No overlapping elements to cycle through")

    def _create_new_bone(self):
        """Create a new bone at the center of the viewport using command system"""
        center_screen = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        center_viewport = self.viewport_manager.screen_to_viewport(center_screen, self.toolbar_height)
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

            # Let pygame-gui process the event first - with error handling
            ui_consumed = False
            try:
                ui_consumed = self.ui_manager.process_events(event)
            except AttributeError as e:
                # Handle pygame-gui bug with ui_element attribute
                if "'pygame.event.Event' object has no attribute 'ui_element'" in str(e):
                    ui_consumed = False  # Continue processing
                else:
                    raise  # Re-raise if it's a different error

            # Handle delayed UI initialization
            if event.type == pygame.USEREVENT + 1:
                pygame.time.set_timer(pygame.USEREVENT + 1, 0)  # Cancel the timer
                self.update_ui_elements()  # Now safe to update UI
                continue

            # Handle pygame-gui events - check both possible event types
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                self._handle_ui_event(event)
            elif event.type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION:
                self._handle_ui_event(event)
            elif event.type == pygame.USEREVENT:
                # Check if this is a pygame-gui event
                if hasattr(event, 'user_type'):
                    if (event.user_type == pygame_gui.UI_BUTTON_PRESSED or
                            event.user_type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION):
                        self._handle_ui_event(event)

            # Handle non-UI events only if they weren't consumed by UI and are in main viewport
            if not ui_consumed:
                if event.type == pygame.KEYDOWN:
                    if not self.handle_keydown(event):
                        pass

            # Handle mouse events in main viewport regardless of UI consumption
            if event.type == pygame.MOUSEBUTTONDOWN:
                if self._is_in_main_viewport(event.pos[0], event.pos[1]):
                    self._handle_mouse_down(event)

            elif event.type == pygame.MOUSEBUTTONUP:
                if self._is_in_main_viewport(event.pos[0], event.pos[1]):
                    self._handle_mouse_up(event)

            elif event.type == pygame.MOUSEMOTION:
                if self._is_in_main_viewport(event.pos[0], event.pos[1]):
                    self._handle_mouse_motion(event)

            elif event.type == pygame.MOUSEWHEEL:
                if self._is_in_main_viewport(pygame.mouse.get_pos()[0], pygame.mouse.get_pos()[1]):
                    self._handle_mouse_wheel(event)

        return True

    def _handle_ui_event(self, event):
        """Handle pygame-gui UI events"""
        # Handle both direct pygame-gui events and USEREVENT wrapped events
        event_type = None
        ui_element = None

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            event_type = pygame_gui.UI_BUTTON_PRESSED
            ui_element = event.ui_element
        elif event.type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION:
            event_type = pygame_gui.UI_SELECTION_LIST_NEW_SELECTION
            ui_element = event.ui_element
        elif event.type == pygame.USEREVENT and hasattr(event, 'user_type'):
            event_type = event.user_type
            ui_element = getattr(event, 'ui_element', None)

        if event_type == pygame_gui.UI_BUTTON_PRESSED:
            if ui_element == self.create_mode_button:
                self._set_mode(BoneEditMode.BONE_CREATION)
            elif ui_element == self.edit_mode_button:
                self._set_mode(BoneEditMode.BONE_EDITING)
            elif ui_element == self.save_button:
                self.save_project()
            elif ui_element == self.load_button:
                self.load_project()
            elif ui_element == self.new_bone_button:
                self._create_new_bone()
            elif ui_element == self.clear_button:
                self._clear_all_bones()
            elif ui_element == self.undo_button:
                self.undo()
            elif ui_element == self.redo_button:
                self.redo()
            elif ui_element == self.delete_bone_button:
                self.delete_selected()
            elif ui_element == self.toggle_attachment_button:
                self._toggle_attachment_point()
            elif ui_element == self.behind_button:
                self._set_bone_layer_behind()
            elif ui_element == self.middle_button:
                self._set_bone_layer_middle()
            elif ui_element == self.front_button:
                self._set_bone_layer_front()
            elif ui_element == self.layer_up_button:
                self._increase_layer_order()
            elif ui_element == self.layer_down_button:
                self._decrease_layer_order()

        elif event_type == pygame_gui.UI_SELECTION_LIST_NEW_SELECTION:
            if ui_element == self.bone_selection_list:
                selected_bone = event.text
                if selected_bone in self.bones:
                    self.selected_bone = selected_bone
                    self.update_ui_elements()

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
                viewport_pos = self.viewport_manager.screen_to_viewport(mouse_pos, self.toolbar_height)

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
        mouse_pos = pygame.mouse.get_pos()
        self.viewport_manager.handle_zoom(event, mouse_pos)

    def _handle_left_click(self, pos):
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

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

            self.update_ui_elements()

        else:
            # No bones at position
            self.selected_bone = None
            self.bones_at_cursor = []
            self.selection_cycle_index = 0
            # Clear all dragging flags
            self.dragging_bone_end = False
            self.dragging_bone_start = False
            self.dragging_bone_body = False
            self.update_ui_elements()

        self.last_click_pos = screen_pos

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

            self.update_ui_elements()

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

    def _update_bone_start_drag(self, pos):
        """Update bone start position - direct manipulation for responsiveness"""
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]
            viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

            bone.x = viewport_pos[0]
            bone.y = viewport_pos[1]

            self._update_child_bone_positions(self.selected_bone)

    def _update_bone_end_drag(self, pos):
        """Update bone end position for rotation and length - direct manipulation"""
        if not self.selected_bone or self.selected_bone not in self.bones:
            return

        bone = self.bones[self.selected_bone]
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

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
        viewport_pos = self.viewport_manager.screen_to_viewport(pos, self.toolbar_height)

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

    def update(self, dt):
        """Update editor state including selection feedback timer"""
        if self.selection_feedback_timer > 0:
            self.selection_feedback_timer -= 1

        self.ui_manager.update(dt)

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

    # Override base class methods
    def save_project(self):
        """Save the current project"""
        project_data = {
            "bones": serialize_dataclass_dict(self.bones)
        }
        save_json_project("bone_project.json", project_data, "Bone project saved successfully!")
        self.update_ui_elements()

    def load_project(self):
        """Load a project using command system"""
        load_command = LoadBoneProjectCommand(self, "bone_project.json")
        self.execute_command(load_command)

    # Override undo/redo to update UI
    def undo(self, count: int = 1) -> bool:
        result = super().undo(count)
        if result:
            self.update_ui_elements()
        return result

    def redo(self, count: int = 1) -> bool:
        result = super().redo(count)
        if result:
            self.update_ui_elements()
        return result

    def draw(self):
        self.screen.fill(DARK_GRAY)

        self._draw_main_viewport()

        # Draw pygame-gui elements
        self.ui_manager.draw_ui(self.screen)

        pygame.display.flip()

    def _draw_main_viewport(self):
        """Draw main viewport"""
        viewport_rect = pygame.Rect(
            self.hierarchy_panel_width, self.toolbar_height,
            self.main_viewport_width, self.main_viewport_height
        )
        pygame.draw.rect(self.screen, BLACK, viewport_rect)

        self.screen.set_clip(viewport_rect)

        draw_grid(self.screen, self.viewport_manager, viewport_rect, self.toolbar_height)
        self._draw_bones(viewport_rect)
        self._draw_creation_guides()

        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, WHITE, viewport_rect, 2)

    def _draw_bones(self, viewport_rect):
        """Draw bone hierarchy with better endpoint visualization"""
        draw_bone_hierarchy_connections(self.screen, self.viewport_manager, self.bones)
        draw_bones_by_layer_order(self.screen, self.viewport_manager, self.bones,
                                  self.selected_bone, font=self.tiny_font)

        # Enhanced endpoint visualization for selected bone
        if self.selected_bone and self.selected_bone in self.bones:
            bone = self.bones[self.selected_bone]

            # Calculate endpoint
            end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
            end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

            # Draw larger, more visible endpoints for selected bone
            start_screen = self.viewport_manager.viewport_to_screen((bone.x, bone.y), self.toolbar_height)
            end_screen = self.viewport_manager.viewport_to_screen((end_x, end_y), self.toolbar_height)

            # Start point (blue)
            pygame.draw.circle(self.screen, BLUE, (int(start_screen[0]), int(start_screen[1])), 8)
            pygame.draw.circle(self.screen, WHITE, (int(start_screen[0]), int(start_screen[1])), 8, 2)

            # End point (red) - this is what you drag to rotate
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
                start_screen = self.viewport_manager.viewport_to_screen(self.bone_start_pos, self.toolbar_height)
                pygame.draw.line(self.screen, GREEN, start_screen, mouse_pos, 3)

                # Show potential attachment point
                parent_bone, attachment_point = get_attachment_point_at_position(
                    self.bones, self.bone_start_pos, self.viewport_manager.viewport_zoom, tolerance=20)

                if parent_bone and attachment_point:
                    attachment_text = f"Will attach to {parent_bone} {attachment_point.value}"
                    attachment_surface = self.small_font.render(attachment_text, True, CYAN)
                    self.screen.blit(attachment_surface, (start_screen[0] + 10, start_screen[1] - 20))

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0  # Delta time in seconds

            running = self.handle_events()
            self.update(dt)
            self.draw()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    editor = BoneSheetEditorGUI()
    editor.run()