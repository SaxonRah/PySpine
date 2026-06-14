from __future__ import annotations

from pathlib import Path

from pyspine.io.jsonio import load_project
from pyspine.runtime.player import Player
from pyspine.runtime.renderer_pygame import PygameRenderer
from pyspine.runtime.bundle import load_runtime_bundle


def run_runtime_demo(project_or_bundle: str | Path, clip: str | None = None, *, width: int = 960, height: int = 640) -> None:
    import pygame  # type: ignore

    path = Path(project_or_bundle)
    bundle = None
    if path.suffix.lower() == ".zip" or (path / "manifest.json").exists():
        bundle = load_runtime_bundle(path)
        project = bundle.project
        project_path = bundle.root / bundle.manifest.get("project", "project.runtime.json")
    else:
        project = load_project(path)
        project_path = path

    try:
        if clip is None and project.clips:
            clip = sorted(project.clips.keys())[0]
        player = Player(project, clip=clip)
        pygame.init()
        screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption(f"pyspine runtime demo - {clip or 'rest pose'}")
        clock = pygame.time.Clock()
        renderer = PygameRenderer(project, project_path)
        running = True
        while running:
            dt = clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
                    elif event.key == pygame.K_SPACE:
                        player.playing = not player.playing
            player.update(dt)
            screen.fill((32, 32, 36))
            renderer.draw(screen, player.pose(), show_points=False)
            pygame.display.flip()
    finally:
        pygame.quit()
        if bundle is not None:
            bundle.close()
