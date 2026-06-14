from __future__ import annotations

from pathlib import Path
from typing import Any

from pyspine.core.geometry import Vec2, rotate
from pyspine.core.model import Project
from pyspine.core.solver import Pose


class PygameRenderer:
    """Small optional renderer. Importing this file requires pygame only at construction time."""

    def __init__(self, project: Project, project_path: str | Path | None = None):
        import pygame  # type: ignore

        self.pygame = pygame
        self.project = project
        self.sheet_surface = None
        self.cache: dict[str, Any] = {}
        if project.sheet.image:
            image_path = Path(project.sheet.image)
            if not image_path.is_absolute() and project_path is not None:
                image_path = Path(project_path).parent / image_path
            if image_path.exists():
                self.sheet_surface = pygame.image.load(str(image_path)).convert_alpha()

    def draw(self, target: Any, poses: dict[str, Pose], *, show_points: bool = True) -> None:
        for pose in sorted(poses.values(), key=lambda p: (p.z, p.instance)):
            if not pose.visible:
                continue
            self._draw_pose(target, pose)
            if show_points:
                self._draw_points(target, pose)

    def _draw_pose(self, target: Any, pose: Pose) -> None:
        pygame = self.pygame
        sprite = self.project.sheet.sprites[pose.sprite]
        surface = self._sprite_surface(pose.sprite)
        if surface is not None:
            scale = max(0.001, (abs(pose.scale_x) + abs(pose.scale_y)) / 2.0)
            surface2 = pygame.transform.smoothscale(surface, (max(1, int(surface.get_width()*abs(pose.scale_x))), max(1, int(surface.get_height()*abs(pose.scale_y)))))
            rotated = pygame.transform.rotate(surface2, -pose.rotation)
            corners = [pose.local_to_world(c) for c in sprite.rect.corners()]
            cx = sum(c.x for c in corners) / 4.0
            cy = sum(c.y for c in corners) / 4.0
            rect = rotated.get_rect(center=(cx, cy))
            target.blit(rotated, rect)
            return

        corners = [pose.local_to_world(c) for c in sprite.rect.corners()]
        pygame.draw.polygon(target, (130, 130, 130), [c.as_tuple() for c in corners], width=0)
        pygame.draw.polygon(target, (20, 20, 20), [c.as_tuple() for c in corners], width=1)

    def _draw_points(self, target: Any, pose: Pose) -> None:
        pygame = self.pygame
        for point in pose.points.values():
            pygame.draw.circle(target, (255, 255, 255), (int(point.x), int(point.y)), 3)
            pygame.draw.circle(target, (20, 20, 20), (int(point.x), int(point.y)), 3, width=1)

    def _sprite_surface(self, sprite_name: str):
        if self.sheet_surface is None:
            return None
        if sprite_name in self.cache:
            return self.cache[sprite_name]
        pygame = self.pygame
        sprite = self.project.sheet.sprites[sprite_name]
        rect = pygame.Rect(int(sprite.rect.x), int(sprite.rect.y), int(sprite.rect.w), int(sprite.rect.h))
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        surface.blit(self.sheet_surface, (0, 0), rect)
        self.cache[sprite_name] = surface
        return surface
