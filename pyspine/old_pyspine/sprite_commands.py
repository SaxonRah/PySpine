import copy
from typing import Dict
from undo_redo_common import UndoRedoCommand
from data_classes import SpriteRect, SpriteInstance, AttachmentPoint


class CreateSpriteCommand(UndoRedoCommand):
    """Command for creating a new sprite rectangle"""

    def __init__(self, sprites_dict: Dict[str, SpriteRect], sprite: SpriteRect, description: str = ""):
        super().__init__(description or f"Create sprite {sprite.name}")
        self.sprites_dict = sprites_dict
        self.sprite = copy.deepcopy(sprite)
        self.sprite_name = sprite.name

    def execute(self) -> None:
        self.sprites_dict[self.sprite_name] = copy.deepcopy(self.sprite)

    def undo(self) -> None:
        if self.sprite_name in self.sprites_dict:
            del self.sprites_dict[self.sprite_name]


class DeleteSpriteCommand(UndoRedoCommand):
    """Command for deleting a sprite rectangle"""

    def __init__(self, sprites_dict: Dict[str, SpriteRect], sprite_name: str, description: str = ""):
        super().__init__(description or f"Delete sprite {sprite_name}")
        self.sprites_dict = sprites_dict
        self.sprite_name = sprite_name
        self.sprite = copy.deepcopy(sprites_dict[sprite_name]) if sprite_name in sprites_dict else None

    def execute(self) -> None:
        if self.sprite_name in self.sprites_dict:
            del self.sprites_dict[self.sprite_name]

    def undo(self) -> None:
        if self.sprite:
            self.sprites_dict[self.sprite_name] = copy.deepcopy(self.sprite)


class MoveSpriteCommand(UndoRedoCommand):
    """Command for moving a sprite rectangle"""

    def __init__(self, sprite: SpriteRect, old_pos: tuple, new_pos: tuple, description: str = ""):
        super().__init__(description or f"Move sprite {sprite.name}")
        self.sprite = sprite
        self.old_x, self.old_y = old_pos
        self.new_x, self.new_y = new_pos

    def execute(self) -> None:
        self.sprite.x = self.new_x
        self.sprite.y = self.new_y

    def undo(self) -> None:
        self.sprite.x = self.old_x
        self.sprite.y = self.old_y


class ResizeSpriteCommand(UndoRedoCommand):
    """Command for resizing a sprite rectangle"""

    def __init__(self, sprite: SpriteRect, old_bounds: tuple, new_bounds: tuple, description: str = ""):
        super().__init__(description or f"Resize sprite {sprite.name}")
        self.sprite = sprite
        self.old_x, self.old_y, self.old_w, self.old_h = old_bounds
        self.new_x, self.new_y, self.new_w, self.new_h = new_bounds

    def execute(self) -> None:
        self.sprite.x = self.new_x
        self.sprite.y = self.new_y
        self.sprite.width = self.new_w
        self.sprite.height = self.new_h

    def undo(self) -> None:
        self.sprite.x = self.old_x
        self.sprite.y = self.old_y
        self.sprite.width = self.old_w
        self.sprite.height = self.old_h


class ChangeOriginCommand(UndoRedoCommand):
    """Command for changing sprite origin"""

    def __init__(self, sprite: SpriteRect, old_origin: tuple, new_origin: tuple, description: str = ""):
        super().__init__(description or f"Change {sprite.name} origin")
        self.sprite = sprite
        self.old_origin_x, self.old_origin_y = old_origin
        self.new_origin_x, self.new_origin_y = new_origin

    def execute(self) -> None:
        self.sprite.origin_x = self.new_origin_x
        self.sprite.origin_y = self.new_origin_y

    def undo(self) -> None:
        self.sprite.origin_x = self.old_origin_x
        self.sprite.origin_y = self.old_origin_y


class CreateSpriteInstanceCommand(UndoRedoCommand):
    """Command for creating a sprite instance"""

    def __init__(self, instances_dict: Dict[str, SpriteInstance], instance: SpriteInstance, description: str = ""):
        super().__init__(description or f"Create sprite instance {instance.id}")
        self.instances_dict = instances_dict
        self.instance = copy.deepcopy(instance)
        self.instance_id = instance.id

    def execute(self) -> None:
        self.instances_dict[self.instance_id] = copy.deepcopy(self.instance)

    def undo(self) -> None:
        if self.instance_id in self.instances_dict:
            del self.instances_dict[self.instance_id]


class DeleteSpriteInstanceCommand(UndoRedoCommand):
    """Command for deleting a sprite instance"""

    def __init__(self, instances_dict: Dict[str, SpriteInstance], instance_id: str, description: str = ""):
        super().__init__(description or f"Delete sprite instance {instance_id}")
        self.instances_dict = instances_dict
        self.instance_id = instance_id
        self.instance = copy.deepcopy(instances_dict[instance_id]) if instance_id in instances_dict else None

    def execute(self) -> None:
        if self.instance_id in self.instances_dict:
            del self.instances_dict[self.instance_id]

    def undo(self) -> None:
        if self.instance:
            self.instances_dict[self.instance_id] = copy.deepcopy(self.instance)


class MoveSpriteInstanceCommand(UndoRedoCommand):
    """Command for moving a sprite instance"""

    def __init__(self, instance: SpriteInstance, old_offset: tuple, new_offset: tuple, description: str = ""):
        super().__init__(description or f"Move sprite instance {instance.id}")
        self.instance = instance
        self.old_offset_x, self.old_offset_y = old_offset
        self.new_offset_x, self.new_offset_y = new_offset

    def execute(self) -> None:
        self.instance.offset_x = self.new_offset_x
        self.instance.offset_y = self.new_offset_y

    def undo(self) -> None:
        self.instance.offset_x = self.old_offset_x
        self.instance.offset_y = self.old_offset_y


class RotateSpriteInstanceCommand(UndoRedoCommand):
    """Command for rotating a sprite instance"""

    def __init__(self, instance: SpriteInstance, old_rotation: float, new_rotation: float, description: str = ""):
        super().__init__(description or f"Rotate sprite instance {instance.id}")
        self.instance = instance
        self.old_rotation = old_rotation
        self.new_rotation = new_rotation

    def execute(self) -> None:
        self.instance.offset_rotation = self.new_rotation

    def undo(self) -> None:
        self.instance.offset_rotation = self.old_rotation


class AttachSpriteInstanceCommand(UndoRedoCommand):
    """Command for attaching sprite instance to bone"""

    def __init__(self, instance: SpriteInstance, old_bone: str, new_bone: str,
                 old_attachment: AttachmentPoint, new_attachment: AttachmentPoint, description: str = ""):
        super().__init__(description or f"Attach {instance.id} to {new_bone}")
        self.instance = instance
        self.old_bone = old_bone
        self.new_bone = new_bone
        self.old_attachment = old_attachment
        self.new_attachment = new_attachment

    def execute(self) -> None:
        self.instance.bone_name = self.new_bone
        self.instance.bone_attachment_point = self.new_attachment

    def undo(self) -> None:
        self.instance.bone_name = self.old_bone
        self.instance.bone_attachment_point = self.old_attachment


# NEW: Additional commands for sprite attachment editor

class LoadSpriteProjectCommand(UndoRedoCommand):
    """Command for loading a sprite project (with full state backup)"""

    def __init__(self, project, filename: str, description: str = ""):
        super().__init__(description or f"Load sprite project {filename}")
        self.project = project
        self.filename = filename

        # Store old state
        self.old_sprite_sheet = project.sprite_sheet
        self.old_sprite_sheet_path = project.sprite_sheet_path
        self.old_sprites = copy.deepcopy(project.sprites)

        # Try loading the new project data
        self.load_success = project.load_sprite_project(filename)
        if self.load_success:
            # Store new state after loading
            self.new_sprite_sheet = project.sprite_sheet
            self.new_sprite_sheet_path = project.sprite_sheet_path
            self.new_sprites = copy.deepcopy(project.sprites)
        else:
            self.new_sprite_sheet = self.old_sprite_sheet
            self.new_sprite_sheet_path = self.old_sprite_sheet_path
            self.new_sprites = self.old_sprites

    def execute(self) -> None:
        if self.load_success:
            self.project.sprite_sheet = self.new_sprite_sheet
            self.project.sprite_sheet_path = self.new_sprite_sheet_path
            self.project.sprites = copy.deepcopy(self.new_sprites)
            print(f"Loaded sprite project: {self.filename}")
        else:
            print(f"Failed to load sprite project: {self.filename}")

    def undo(self) -> None:
        self.project.sprite_sheet = self.old_sprite_sheet
        self.project.sprite_sheet_path = self.old_sprite_sheet_path
        self.project.sprites = copy.deepcopy(self.old_sprites)
        print(f"Restored previous sprite project state")


class LoadBoneProjectCommand(UndoRedoCommand):
    """Command for loading a bone project (with full state backup)"""

    def __init__(self, project, filename: str, description: str = ""):
        super().__init__(description or f"Load bone project {filename}")
        self.project = project
        self.filename = filename

        # Store old state
        self.old_bones = copy.deepcopy(project.bones)

        # Try loading the new project data
        self.load_success = project.load_bone_project(filename)
        if self.load_success:
            # Store new state after loading
            self.new_bones = copy.deepcopy(project.bones)
        else:
            self.new_bones = self.old_bones

    def execute(self) -> None:
        if self.load_success:
            self.project.bones = copy.deepcopy(self.new_bones)
            print(f"Loaded bone project: {self.filename}")
        else:
            print(f"Failed to load bone project: {self.filename}")

    def undo(self) -> None:
        self.project.bones = copy.deepcopy(self.old_bones)
        print(f"Restored previous bone project state")


class LoadAttachmentConfigCommand(UndoRedoCommand):
    """Command for loading attachment configuration (with full state backup)"""

    def __init__(self, editor, filename: str, description: str = ""):
        super().__init__(description or f"Load attachment config {filename}")
        self.editor = editor
        self.filename = filename

        # Store old state
        self.old_sprite_sheet = editor.project.sprite_sheet
        self.old_sprite_sheet_path = editor.project.sprite_sheet_path
        self.old_sprites = copy.deepcopy(editor.project.sprites)
        self.old_bones = copy.deepcopy(editor.project.bones)
        self.old_sprite_instances = copy.deepcopy(editor.project.sprite_instances)
        self.old_selected_sprite_instance = editor.selected_sprite_instance
        self.old_selected_bone = editor.selected_bone

        # Try loading the config (store result for later)
        from file_common import load_json_project
        self.data = load_json_project(filename)
        self.load_success = self.data is not None

    def execute(self) -> None:
        if self.load_success:
            try:
                self.editor.load_attachment_configuration_from_data(self.data)
                print(f"Loaded attachment configuration: {self.filename}")
            except Exception as e:
                print(f"Error loading attachment configuration: {e}")
                self.load_success = False
        else:
            print(f"Failed to load attachment configuration: {self.filename}")

    def undo(self) -> None:
        self.editor.project.sprite_sheet = self.old_sprite_sheet
        self.editor.project.sprite_sheet_path = self.old_sprite_sheet_path
        self.editor.project.sprites = copy.deepcopy(self.old_sprites)
        self.editor.project.bones = copy.deepcopy(self.old_bones)
        self.editor.project.sprite_instances = copy.deepcopy(self.old_sprite_instances)
        self.editor.selected_sprite_instance = self.old_selected_sprite_instance
        self.editor.selected_bone = self.old_selected_bone
        print(f"Restored previous attachment configuration state")


class ChangeScaleCommand(UndoRedoCommand):
    """Command for changing sprite instance scale"""

    def __init__(self, instance: SpriteInstance, old_scale: float, new_scale: float, description: str = ""):
        super().__init__(description or f"Change {instance.id} scale")
        self.instance = instance
        self.old_scale = old_scale
        self.new_scale = new_scale

    def execute(self) -> None:
        self.instance.scale = self.new_scale

    def undo(self) -> None:
        self.instance.scale = self.old_scale
