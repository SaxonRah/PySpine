from __future__ import annotations

from dataclasses import dataclass

from pyspine.core.geometry import Vec2


@dataclass(slots=True)
class Viewport:
    zoom: float = 1.0
    offset: Vec2 = Vec2(0.0, 0.0)

    def world_to_screen(self, p: Vec2) -> Vec2:
        return Vec2(p.x * self.zoom + self.offset.x, p.y * self.zoom + self.offset.y)

    def screen_to_world(self, p: Vec2) -> Vec2:
        return Vec2((p.x - self.offset.x) / self.zoom, (p.y - self.offset.y) / self.zoom)

    def pan(self, dx: float, dy: float) -> None:
        self.offset = Vec2(self.offset.x + dx, self.offset.y + dy)

    def zoom_at(self, screen: Vec2, factor: float) -> None:
        before = self.screen_to_world(screen)
        self.zoom = max(0.05, min(20.0, self.zoom * factor))
        after = self.screen_to_world(screen)
        delta = after - before
        self.offset = Vec2(self.offset.x + delta.x * self.zoom, self.offset.y + delta.y * self.zoom)
