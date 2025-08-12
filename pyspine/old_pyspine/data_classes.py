from typing import List, Optional
from dataclasses import dataclass
from enum import Enum


class InterpolationType(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    BEZIER = "bezier"


class BoneLayer(Enum):
    BEHIND = "behind"
    MIDDLE = "middle"
    FRONT = "front"


class ResizeHandle(Enum):
    NONE = 0
    TOP_LEFT = 1
    TOP_RIGHT = 2
    BOTTOM_LEFT = 3
    BOTTOM_RIGHT = 4
    TOP = 5
    BOTTOM = 6
    LEFT = 7
    RIGHT = 8


class AttachmentPoint(Enum):
    START = "start"
    END = "end"


@dataclass
class SpriteRect:
    name: str
    x: int
    y: int
    width: int
    height: int
    origin_x: float = 0.5  # Relative origin (0-1)
    origin_y: float = 0.5


@dataclass
class SpriteInstance:
    id: str
    sprite_name: str
    bone_name: Optional[str] = None
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_rotation: float = 0.0
    scale: float = 1.0
    bone_attachment_point: AttachmentPoint = AttachmentPoint.START  # NEW: Added this field


@dataclass
class Bone:
    name: str
    x: float
    y: float
    length: float
    angle: float = 0.0
    parent: Optional[str] = None
    parent_attachment_point: AttachmentPoint = AttachmentPoint.END  # NEW: Which end of parent to attach to
    children: List[str] = None
    layer: BoneLayer = BoneLayer.MIDDLE
    layer_order: int = 0  # Order within bone layer (higher = renders on top)

    def __post_init__(self):
        if self.children is None:
            self.children = []


@dataclass
class BoneTransform:
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale: float = 1.0


@dataclass
class BoneKeyframe:
    time: float
    bone_name: str
    transform: BoneTransform
    interpolation: InterpolationType = InterpolationType.LINEAR
    sprite_instance_id: Optional[str] = None


class BoneEditMode(Enum):
    BONE_CREATION = "bone_creation"
    BONE_EDITING = "bone_editing"
