import copy
from typing import Dict, Any
from undo_redo_common import UndoRedoCommand
from data_classes import Bone, BoneLayer, AttachmentPoint


class CreateBoneCommand(UndoRedoCommand):
    """Command for creating a new bone"""

    def __init__(self, bones_dict: Dict[str, Bone], bone: Bone, description: str = ""):
        super().__init__(description or f"Create bone {bone.name}")
        self.bones_dict = bones_dict
        self.bone = copy.deepcopy(bone)
        self.bone_name = bone.name

    def execute(self) -> None:
        self.bones_dict[self.bone_name] = copy.deepcopy(self.bone)

        # Add to parent's children if it has a parent
        if self.bone.parent and self.bone.parent in self.bones_dict:
            parent = self.bones_dict[self.bone.parent]
            if self.bone_name not in parent.children:
                parent.children.append(self.bone_name)

    def undo(self) -> None:
        # Remove from parent's children
        if self.bone.parent and self.bone.parent in self.bones_dict:
            parent = self.bones_dict[self.bone.parent]
            if self.bone_name in parent.children:
                parent.children.remove(self.bone_name)

        # Remove bone
        if self.bone_name in self.bones_dict:
            del self.bones_dict[self.bone_name]


class DeleteBoneCommand(UndoRedoCommand):
    """Command for deleting a bone"""

    def __init__(self, bones_dict: Dict[str, Bone], bone_name: str, description: str = ""):
        super().__init__(description or f"Delete bone {bone_name}")
        self.bones_dict = bones_dict
        self.bone_name = bone_name
        self.bone = copy.deepcopy(bones_dict[bone_name]) if bone_name in bones_dict else None
        self.child_parent_updates = []  # Store children that need parent updates

        # Store which children will be updated
        if self.bone:
            for child_name in self.bone.children:
                if child_name in bones_dict:
                    self.child_parent_updates.append(child_name)

    def execute(self) -> None:
        if not self.bone or self.bone_name not in self.bones_dict:
            return

        # Remove from parent's children
        if self.bone.parent and self.bone.parent in self.bones_dict:
            parent = self.bones_dict[self.bone.parent]
            if self.bone_name in parent.children:
                parent.children.remove(self.bone_name)

        # Update children to have this bone's parent
        for child_name in self.bone.children:
            if child_name in self.bones_dict:
                child_bone = self.bones_dict[child_name]
                child_bone.parent = self.bone.parent

                if self.bone.parent and self.bone.parent in self.bones_dict:
                    grandparent = self.bones_dict[self.bone.parent]
                    if child_name not in grandparent.children:
                        grandparent.children.append(child_name)

        # Delete the bone
        del self.bones_dict[self.bone_name]

    def undo(self) -> None:
        if not self.bone:
            return

        # Restore the bone
        self.bones_dict[self.bone_name] = copy.deepcopy(self.bone)

        # Restore parent relationship
        if self.bone.parent and self.bone.parent in self.bones_dict:
            parent = self.bones_dict[self.bone.parent]
            if self.bone_name not in parent.children:
                parent.children.append(self.bone_name)

        # Restore children relationships
        for child_name in self.child_parent_updates:
            if child_name in self.bones_dict:
                child_bone = self.bones_dict[child_name]
                child_bone.parent = self.bone_name

                # Remove from grandparent if needed
                if self.bone.parent and self.bone.parent in self.bones_dict:
                    grandparent = self.bones_dict[self.bone.parent]
                    if child_name in grandparent.children:
                        grandparent.children.remove(child_name)


class MoveBoneCommand(UndoRedoCommand):
    """Command for moving a bone position"""

    def __init__(self, bone: Bone, old_pos: tuple, new_pos: tuple, update_children_func=None, description: str = ""):
        super().__init__(description or f"Move bone {bone.name}")
        self.bone = bone
        self.old_x, self.old_y = old_pos
        self.new_x, self.new_y = new_pos
        self.update_children_func = update_children_func

    def execute(self) -> None:
        self.bone.x = self.new_x
        self.bone.y = self.new_y
        if self.update_children_func:
            self.update_children_func(self.bone.name)

    def undo(self) -> None:
        self.bone.x = self.old_x
        self.bone.y = self.old_y
        if self.update_children_func:
            self.update_children_func(self.bone.name)


class RotateBoneCommand(UndoRedoCommand):
    """Command for rotating a bone"""

    def __init__(self, bone: Bone, old_angle: float, new_angle: float,
                 old_length: float = None, new_length: float = None,
                 update_children_func=None, description: str = ""):
        super().__init__(description or f"Rotate bone {bone.name}")
        self.bone = bone
        self.old_angle = old_angle
        self.new_angle = new_angle
        self.old_length = old_length if old_length is not None else bone.length
        self.new_length = new_length if new_length is not None else bone.length
        self.update_children_func = update_children_func

    def execute(self) -> None:
        self.bone.angle = self.new_angle
        self.bone.length = self.new_length
        if self.update_children_func:
            self.update_children_func(self.bone.name)

    def undo(self) -> None:
        self.bone.angle = self.old_angle
        self.bone.length = self.old_length
        if self.update_children_func:
            self.update_children_func(self.bone.name)


class ChangeBoneLayerCommand(UndoRedoCommand):
    """Command for changing bone layer"""

    def __init__(self, bone: Bone, old_layer: BoneLayer, new_layer: BoneLayer,
                 old_order: int = None, new_order: int = None, description: str = ""):
        super().__init__(description or f"Change {bone.name} layer")
        self.bone = bone
        self.old_layer = old_layer
        self.new_layer = new_layer
        self.old_order = old_order if old_order is not None else getattr(bone, 'layer_order', 0)
        self.new_order = new_order if new_order is not None else getattr(bone, 'layer_order', 0)

    def execute(self) -> None:
        self.bone.layer = self.new_layer
        self.bone.layer_order = self.new_order

    def undo(self) -> None:
        self.bone.layer = self.old_layer
        self.bone.layer_order = self.old_order


class ChangeAttachmentPointCommand(UndoRedoCommand):
    """Command for changing bone attachment point"""

    def __init__(self, bone: Bone, old_attachment: AttachmentPoint, new_attachment: AttachmentPoint,
                 update_position_func=None, description: str = ""):
        super().__init__(description or f"Change {bone.name} attachment")
        self.bone = bone
        self.old_attachment = old_attachment
        self.new_attachment = new_attachment
        self.update_position_func = update_position_func

    def execute(self) -> None:
        self.bone.parent_attachment_point = self.new_attachment
        if self.update_position_func:
            self.update_position_func(self.bone.name)

    def undo(self) -> None:
        self.bone.parent_attachment_point = self.old_attachment
        if self.update_position_func:
            self.update_position_func(self.bone.name)
