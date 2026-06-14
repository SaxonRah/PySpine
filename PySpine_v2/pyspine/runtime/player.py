from __future__ import annotations

from dataclasses import dataclass

from pyspine.core.animation import sample_clip
from pyspine.core.model import Clip, Project
from pyspine.core.solver import Pose, solve_pose


@dataclass(slots=True)
class Player:
    project: Project
    clip: Clip | str | None = None
    frame: float = 0.0
    playing: bool = True

    def set_clip(self, clip: Clip | str | None) -> None:
        self.clip = clip
        self.frame = 0.0

    def update(self, dt_seconds: float) -> None:
        if not self.playing or self.clip is None:
            return
        clip = self._clip_obj()
        self.frame += dt_seconds * clip.fps
        if clip.loop and clip.length > 0:
            self.frame %= clip.length
        else:
            self.frame = min(self.frame, clip.length)

    def pose(self) -> dict[str, Pose]:
        if self.clip is None:
            return solve_pose(self.project)
        return solve_pose(self.project, sample_clip(self.project, self._clip_obj(), self.frame))

    def _clip_obj(self) -> Clip:
        if isinstance(self.clip, str):
            return self.project.clips[self.clip]
        assert self.clip is not None
        return self.clip
