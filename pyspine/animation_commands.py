import copy
from undo_redo_common import UndoRedoCommand
from data_classes import BoneKeyframe, BoneTransform, InterpolationType


class AddKeyframeCommand(UndoRedoCommand):
    """Command for adding an animation keyframe"""

    def __init__(self, track, keyframe: BoneKeyframe, description: str = ""):
        super().__init__(description or f"Add keyframe at {keyframe.time:.2f}s")
        self.track = track
        self.keyframe = copy.deepcopy(keyframe)

    def execute(self) -> None:
        self.track.add_keyframe(copy.deepcopy(self.keyframe))

    def undo(self) -> None:
        # Find and remove the keyframe
        for i, kf in enumerate(self.track.keyframes):
            if (abs(kf.time - self.keyframe.time) < 0.01 and
                    kf.bone_name == self.keyframe.bone_name):
                self.track.keyframes.pop(i)
                break


class DeleteKeyframeCommand(UndoRedoCommand):
    """Command for deleting an animation keyframe"""

    def __init__(self, track, keyframe_index: int, description: str = ""):
        super().__init__(description or f"Delete keyframe")
        self.track = track
        self.keyframe_index = keyframe_index
        self.keyframe = copy.deepcopy(track.keyframes[keyframe_index]) if 0 <= keyframe_index < len(
            track.keyframes) else None

    def execute(self) -> None:
        if 0 <= self.keyframe_index < len(self.track.keyframes):
            self.track.keyframes.pop(self.keyframe_index)

    def undo(self) -> None:
        if self.keyframe:
            self.track.add_keyframe(copy.deepcopy(self.keyframe))


class ModifyKeyframeCommand(UndoRedoCommand):
    """Command for modifying an animation keyframe"""

    def __init__(self, keyframe: BoneKeyframe, old_transform: BoneTransform, new_transform: BoneTransform,
                 old_time: float = None, new_time: float = None,
                 old_interpolation: InterpolationType = None, new_interpolation: InterpolationType = None,
                 description: str = ""):
        super().__init__(description or f"Modify keyframe")
        self.keyframe = keyframe
        self.old_transform = copy.deepcopy(old_transform)
        self.new_transform = copy.deepcopy(new_transform)
        self.old_time = old_time if old_time is not None else keyframe.time
        self.new_time = new_time if new_time is not None else keyframe.time
        self.old_interpolation = old_interpolation if old_interpolation is not None else keyframe.interpolation
        self.new_interpolation = new_interpolation if new_interpolation is not None else keyframe.interpolation

    def execute(self) -> None:
        self.keyframe.transform = copy.deepcopy(self.new_transform)
        self.keyframe.time = self.new_time
        self.keyframe.interpolation = self.new_interpolation

    def undo(self) -> None:
        self.keyframe.transform = copy.deepcopy(self.old_transform)
        self.keyframe.time = self.old_time
        self.keyframe.interpolation = self.old_interpolation


class MoveKeyframeCommand(UndoRedoCommand):
    """Command for moving a keyframe in time"""

    def __init__(self, track, keyframe_index: int, old_time: float, new_time: float, description: str = ""):
        super().__init__(description or f"Move keyframe to {new_time:.2f}s")
        self.track = track
        self.keyframe_index = keyframe_index
        self.old_time = old_time
        self.new_time = new_time

    def execute(self) -> None:
        if 0 <= self.keyframe_index < len(self.track.keyframes):
            self.track.keyframes[self.keyframe_index].time = self.new_time
            # Re-sort keyframes by time
            self.track.keyframes.sort(key=lambda kf: kf.time)

    def undo(self) -> None:
        # Find the keyframe by time and restore original time
        for kf in self.track.keyframes:
            if abs(kf.time - self.new_time) < 0.01:
                kf.time = self.old_time
                break
        # Re-sort keyframes by time
        self.track.keyframes.sort(key=lambda kf: kf.time)


class SetInterpolationCommand(UndoRedoCommand):
    """Command for changing keyframe interpolation"""

    def __init__(self, keyframe: BoneKeyframe, old_interpolation: InterpolationType,
                 new_interpolation: InterpolationType, description: str = ""):
        super().__init__(description or f"Set interpolation to {new_interpolation.value}")
        self.keyframe = keyframe
        self.old_interpolation = old_interpolation
        self.new_interpolation = new_interpolation

    def execute(self) -> None:
        self.keyframe.interpolation = self.new_interpolation

    def undo(self) -> None:
        self.keyframe.interpolation = self.old_interpolation


# NEW: Additional commands for animation editor

class LoadAttachmentConfigurationCommand(UndoRedoCommand):
    """Command for loading attachment configuration (with full state backup)"""

    def __init__(self, project, filename: str, description: str = ""):
        super().__init__(description or f"Load attachment config {filename}")
        self.project = project
        self.filename = filename

        # Store old state
        self.old_sprite_sheet = project.sprite_sheet
        self.old_sprite_sheet_path = project.sprite_sheet_path
        self.old_sprites = copy.deepcopy(project.sprites)
        self.old_bones = copy.deepcopy(project.bones)
        self.old_sprite_instances = copy.deepcopy(project.sprite_instances)
        self.old_bone_tracks = copy.deepcopy(project.bone_tracks)
        self.old_original_bone_positions = copy.deepcopy(project.original_bone_positions)

        # Try loading the new config
        self.load_success = project.load_attachment_configuration(filename)

    def execute(self) -> None:
        if self.load_success:
            print(f"Loaded attachment configuration: {self.filename}")
        else:
            print(f"Failed to load attachment configuration: {self.filename}")

    def undo(self) -> None:
        self.project.sprite_sheet = self.old_sprite_sheet
        self.project.sprite_sheet_path = self.old_sprite_sheet_path
        self.project.sprites = copy.deepcopy(self.old_sprites)
        self.project.bones = copy.deepcopy(self.old_bones)
        self.project.sprite_instances = copy.deepcopy(self.old_sprite_instances)
        self.project.bone_tracks = copy.deepcopy(self.old_bone_tracks)
        self.project.original_bone_positions = copy.deepcopy(self.old_original_bone_positions)
        print(f"Restored previous attachment configuration state")


class LoadAnimationProjectCommand(UndoRedoCommand):
    """Command for loading animation project (with full state backup)"""

    def __init__(self, project, filename: str, description: str = ""):
        super().__init__(description or f"Load animation project {filename}")
        self.project = project
        self.filename = filename

        # Store old state
        self.old_duration = project.duration
        self.old_fps = project.fps
        self.old_bone_tracks = copy.deepcopy(project.bone_tracks)
        self.old_original_bone_positions = copy.deepcopy(project.original_bone_positions)
        self.old_sprite_instances = copy.deepcopy(project.sprite_instances)
        self.old_current_time = project.current_time

        # Try loading the new project
        from file_common import load_json_project
        self.animation_data = load_json_project(filename)
        self.load_success = self.animation_data is not None

    def execute(self) -> None:
        if self.load_success:
            self._load_animation_data()
            print(f"Loaded animation project: {self.filename}")
        else:
            print(f"Failed to load animation project: {self.filename}")

    def undo(self) -> None:
        self.project.duration = self.old_duration
        self.project.fps = self.old_fps
        self.project.bone_tracks = copy.deepcopy(self.old_bone_tracks)
        self.project.original_bone_positions = copy.deepcopy(self.old_original_bone_positions)
        self.project.sprite_instances = copy.deepcopy(self.old_sprite_instances)
        self.project.current_time = self.old_current_time
        print(f"Restored previous animation project state")

    def _load_animation_data(self):
        """Load animation data from stored data"""
        try:
            from data_classes import SpriteInstance, BoneKeyframe, BoneTransform, InterpolationType, AttachmentPoint

            self.project.duration = self.animation_data.get("duration", 5.0)
            self.project.fps = self.animation_data.get("fps", 30)

            # Load original bone positions
            self.project.original_bone_positions = self.animation_data.get("original_bone_positions", {})

            # Load sprite instances with attachment point support
            self.project.sprite_instances = {}
            for instance_id, instance_data in self.animation_data.get("sprite_instances", {}).items():
                # Handle attachment point field (maybe missing in old files)
                attachment_point_value = instance_data.get("bone_attachment_point", "start")
                try:
                    attachment_point = AttachmentPoint(attachment_point_value)
                except ValueError:
                    attachment_point = AttachmentPoint.START

                sprite_instance = SpriteInstance(
                    id=instance_data["id"],
                    sprite_name=instance_data["sprite_name"],
                    bone_name=instance_data.get("bone_name"),
                    offset_x=instance_data.get("offset_x", 0.0),
                    offset_y=instance_data.get("offset_y", 0.0),
                    offset_rotation=instance_data.get("offset_rotation", 0.0),
                    scale=instance_data.get("scale", 1.0),
                    bone_attachment_point=attachment_point
                )
                self.project.sprite_instances[instance_id] = sprite_instance

            # Load bone tracks
            for bone_name, track_data in self.animation_data.get("bone_tracks", {}).items():
                if bone_name in self.project.bone_tracks:
                    track = self.project.bone_tracks[bone_name]
                    track.keyframes = []

                    for kf_data in track_data.get("keyframes", []):
                        transform = BoneTransform(**kf_data["transform"])
                        interpolation = InterpolationType(kf_data.get("interpolation", "linear"))

                        keyframe = BoneKeyframe(
                            time=kf_data["time"],
                            bone_name=bone_name,
                            transform=transform,
                            interpolation=interpolation,
                            sprite_instance_id=kf_data.get("sprite_instance_id")
                        )
                        track.add_keyframe(keyframe)

        except Exception as e:
            print(f"Error loading animation data: {e}")
            raise


class ClearAnimationCommand(UndoRedoCommand):
    """Command for clearing all animation data"""

    def __init__(self, project, description: str = "Clear all animation"):
        super().__init__(description)
        self.project = project
        self.old_bone_tracks = copy.deepcopy(project.bone_tracks)
        self.old_current_time = project.current_time

    def execute(self) -> None:
        # Clear all keyframes from all tracks
        for track in self.project.bone_tracks.values():
            track.keyframes.clear()
            track.selected_keyframe = None
        self.project.current_time = 0.0
        print("Cleared all animation data")

    def undo(self) -> None:
        self.project.bone_tracks = copy.deepcopy(self.old_bone_tracks)
        self.project.current_time = self.old_current_time
        print(
            f"Restored animation data with {sum(len(track.keyframes) for track in self.old_bone_tracks.values())} keyframes")


class BoneManipulationCommand(UndoRedoCommand):
    """Command for bone manipulation during animation (translation/rotation)"""

    def __init__(self, track, bone_name: str, old_transform: BoneTransform, new_transform: BoneTransform,
                 current_time: float, description: str = ""):
        super().__init__(description or f"Animate {bone_name}")
        self.track = track
        self.bone_name = bone_name
        self.old_transform = copy.deepcopy(old_transform)
        self.new_transform = copy.deepcopy(new_transform)
        self.current_time = current_time

    def execute(self) -> None:
        # Create or update keyframe at current time with new transform
        existing_keyframe = None
        for i, kf in enumerate(self.track.keyframes):
            if abs(kf.time - self.current_time) < 0.01:
                existing_keyframe = i
                break

        if existing_keyframe is not None:
            # Update existing keyframe
            self.track.keyframes[existing_keyframe].transform = copy.deepcopy(self.new_transform)
        else:
            # Create new keyframe
            keyframe = BoneKeyframe(
                time=self.current_time,
                bone_name=self.bone_name,
                transform=copy.deepcopy(self.new_transform)
            )
            self.track.add_keyframe(keyframe)

    def undo(self) -> None:
        # Restore old transform or remove keyframe if it was newly created
        existing_keyframe = None
        for i, kf in enumerate(self.track.keyframes):
            if abs(kf.time - self.current_time) < 0.01:
                existing_keyframe = i
                break

        if existing_keyframe is not None:
            # Check if this was a modification or creation
            if (self.old_transform.x == 0 and self.old_transform.y == 0 and
                    self.old_transform.rotation == 0 and self.old_transform.scale == 0):
                # This was a new keyframe, remove it
                self.track.keyframes.pop(existing_keyframe)
            else:
                # This was a modification, restore old transform
                self.track.keyframes[existing_keyframe].transform = copy.deepcopy(self.old_transform)
