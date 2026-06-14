from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pyspine.core.commands import Command
from pyspine.core.geometry import Rect, Vec2
from pyspine.core.model import Project
from pyspine.editor.viewport import Viewport


@dataclass(slots=True)
class TextPrompt:
    purpose: str
    text: str = ""
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class EditorState:
    project: Project
    path: Path | None = None
    selected: str | None = None
    selected_sprite: str | None = None
    selected_point: str | None = None
    hovered: str | None = None
    mode: str = "rig"
    viewport: Viewport = field(default_factory=lambda: Viewport(zoom=1.0))
    dirty: bool = False
    undo_stack: list[Command] = field(default_factory=list)
    redo_stack: list[Command] = field(default_factory=list)
    message: str = ""
    text_prompt: TextPrompt | None = None
    last_mouse_world: Vec2 = Vec2()
    pending_rect: Rect | None = None
    current_clip: str | None = None
    frame: float = 0.0
    playing: bool = False
    onion_skin: bool = False
    pose_clipboard: dict[str, dict[str, float | bool]] | None = None
    frame_clipboard: list[tuple[str, str, float]] | None = None
    timeline_height: int = 190
    timeline_scroll: int = 0
    sidebar_scroll_px: int = 0
    timeline_horizontal_scroll: int = 0
    selected_key_instance: str | None = None
    selected_key_channel: str | None = None
    selected_key_frame: float | None = None
    timeline_drag_key: tuple[str, str, float] | None = None
    sidebar_drag_instance: str | None = None
    sidebar_hover_instance: str | None = None
    hover_snap_parent: str | None = None
    hover_snap_point: str | None = None
    rig_snap_enabled: bool = True
    ui_sidebar_w: int | None = None
    ui_timeline_h: int | None = None
    ui_drag_splitter: str | None = None
    ui_hover_splitter: str | None = None
    selected_keys: list[tuple[str, str, float]] = field(default_factory=list)
    key_box_start: tuple[int, int] | None = None
    key_box_current: tuple[int, int] | None = None
    autosave_seconds: float = 60.0
    autosave_elapsed: float = 0.0
    recent_config_dir: str | None = None

    def run_command(self, command: Command) -> bool:
        try:
            command.apply(self.project)
        except Exception as exc:
            self.message = f"{getattr(command, 'label', 'command')} failed: {exc}"
            return False
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self.dirty = True
        self.message = getattr(command, "label", "command")
        return True

    def undo(self) -> None:
        if not self.undo_stack:
            self.message = "nothing to undo"
            return
        command = self.undo_stack.pop()
        try:
            command.undo(self.project)
        except Exception as exc:
            self.message = f"undo failed: {exc}"
            self.undo_stack.append(command)
            return
        self.redo_stack.append(command)
        self.dirty = True
        self.message = f"undo: {getattr(command, 'label', 'command')}"

    def redo(self) -> None:
        if not self.redo_stack:
            self.message = "nothing to redo"
            return
        command = self.redo_stack.pop()
        try:
            command.apply(self.project)
        except Exception as exc:
            self.message = f"redo failed: {exc}"
            self.redo_stack.append(command)
            return
        self.undo_stack.append(command)
        self.dirty = True
        self.message = f"redo: {getattr(command, 'label', 'command')}"

    def unique_sprite_name(self, prefix: str = "sprite") -> str:
        n = 1
        while f"{prefix}_{n:03d}" in self.project.sheet.sprites:
            n += 1
        return f"{prefix}_{n:03d}"

    def unique_point_name(self, prefix: str = "point") -> str:
        sprite = self.project.sheet.sprites.get(self.selected_sprite or "")
        n = 1
        existing = sprite.points if sprite else {}
        while f"{prefix}_{n:02d}" in existing:
            n += 1
        return f"{prefix}_{n:02d}"

    def unique_instance_name(self, sprite_name: str) -> str:
        safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in sprite_name).strip("_") or "inst"
        n = 1
        while f"{safe}_{n:02d}" in self.project.rig.instances:
            n += 1
        return f"{safe}_{n:02d}"
