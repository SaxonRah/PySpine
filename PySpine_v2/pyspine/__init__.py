"""pyspine clean-room 2D sprite hierarchy animation toolkit."""

from .core.model import AttachmentPoint, Clip, Instance, Project, Rig, Sprite, SpriteSheet, Track
from .core.solver import Pose, solve_pose, world_point
from .core.animation import sample_clip
from .core.easing import apply_easing
from .core.motion import motion_arc
from .core.ik import solve_two_bone_ik

__all__ = [
    "AttachmentPoint",
    "Clip",
    "Instance",
    "Pose",
    "Project",
    "Rig",
    "Sprite",
    "SpriteSheet",
    "Track",
    "apply_easing",
    "motion_arc",
    "sample_clip",
    "solve_two_bone_ik",
    "solve_pose",
    "world_point",
]

__version__ = "0.13.0"
