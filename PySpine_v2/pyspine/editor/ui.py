from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal


# ---------------------------------------------------------------------------
# General UI math
# ---------------------------------------------------------------------------


def clamp_i(value: int, lo: int, hi: int) -> int:
    if hi < lo:
        hi = lo
    return max(lo, min(hi, value))


def clamp_f(value: float, lo: float, hi: float) -> float:
    if hi < lo:
        hi = lo
    return max(lo, min(hi, value))


@dataclass(frozen=True, slots=True)
class PanelLayout:
    screen_w: int
    screen_h: int
    sidebar_w: int
    timeline_h: int
    topbar_h: int = 0
    splitter_w: int = 6

    @property
    def sidebar_x(self) -> int:
        return self.screen_w - self.sidebar_w

    @property
    def canvas_rect(self) -> tuple[int, int, int, int]:
        h = self.screen_h - (self.timeline_h if self.timeline_h else 0)
        return (0, self.topbar_h, self.sidebar_x, max(1, h - self.topbar_h))

    @property
    def sidebar_rect(self) -> tuple[int, int, int, int]:
        return (self.sidebar_x, 0, self.sidebar_w, self.screen_h)

    @property
    def timeline_rect(self) -> tuple[int, int, int, int]:
        if self.timeline_h <= 0:
            return (0, self.screen_h, self.sidebar_x, 0)
        return (0, self.screen_h - self.timeline_h, self.sidebar_x, self.timeline_h)

    @property
    def sidebar_splitter_rect(self) -> tuple[int, int, int, int]:
        x = max(0, self.sidebar_x - self.splitter_w // 2)
        return (x, 0, self.splitter_w, self.screen_h)

    @property
    def timeline_splitter_rect(self) -> tuple[int, int, int, int]:
        if self.timeline_h <= 0:
            return (0, self.screen_h, 0, 0)
        y = max(0, self.screen_h - self.timeline_h - self.splitter_w // 2)
        return (0, y, self.sidebar_x, self.splitter_w)


def default_sidebar_width(width: int) -> int:
    sidebar = clamp_i(int(width * 0.31), 320, 500)
    return min(sidebar, max(260, width - 420))


def default_timeline_height(height: int) -> int:
    timeline = clamp_i(int(height * 0.27), 180, 320)
    return min(timeline, max(150, height - 320))


def compute_layout(
    width: int,
    height: int,
    *,
    show_timeline: bool = False,
    sidebar_w: int | None = None,
    timeline_h: int | None = None,
    min_canvas_w: int = 360,
    min_canvas_h: int = 260,
) -> PanelLayout:
    """Return a layout that keeps the canvas usable on very small windows.

    v10 changed layout from pure autosizing to autosize + user overrides.  The
    important invariant is that dragging a panel divider can never eat the whole
    canvas; this function is the single source of truth for those limits.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    max_sidebar = max(260, width - min_canvas_w)
    sidebar = default_sidebar_width(width) if sidebar_w is None else int(sidebar_w)
    sidebar = clamp_i(sidebar, 260, min(620, max_sidebar))

    timeline = 0
    if show_timeline:
        max_timeline = max(150, height - min_canvas_h)
        timeline = default_timeline_height(height) if timeline_h is None else int(timeline_h)
        timeline = clamp_i(timeline, 150, min(420, max_timeline))
    return PanelLayout(width, height, sidebar, timeline)


def resize_sidebar_from_mouse(screen_w: int, mouse_x: int, *, min_canvas_w: int = 360) -> int:
    return compute_layout(screen_w, 1, sidebar_w=screen_w - mouse_x, min_canvas_w=min_canvas_w).sidebar_w


def resize_timeline_from_mouse(screen_h: int, mouse_y: int, *, min_canvas_h: int = 260) -> int:
    return compute_layout(1000, screen_h, show_timeline=True, timeline_h=screen_h - mouse_y, min_canvas_h=min_canvas_h).timeline_h


# ---------------------------------------------------------------------------
# Scrollbars
# ---------------------------------------------------------------------------


def scroll_offset_for_content(offset: int, viewport_h: int, content_h: int) -> int:
    return clamp_i(offset, 0, max(0, content_h - max(0, viewport_h)))


def scroll_thumb(viewport_h: int, content_h: int, offset: int, *, min_thumb: int = 24) -> tuple[int, int] | None:
    if content_h <= viewport_h or viewport_h <= 0:
        return None
    thumb_h = max(min_thumb, int(viewport_h * (viewport_h / content_h)))
    thumb_h = min(thumb_h, max(1, viewport_h))
    max_y = max(1, viewport_h - thumb_h)
    max_offset = max(1, content_h - viewport_h)
    thumb_y = int((offset / max_offset) * max_y)
    return thumb_y, thumb_h


@dataclass(slots=True)
class ScrollArea:
    viewport_h: int
    content_h: int
    offset: int = 0

    def scroll(self, delta_px: int) -> None:
        self.offset = scroll_offset_for_content(self.offset + delta_px, self.viewport_h, self.content_h)

    def set_content_height(self, content_h: int) -> None:
        self.content_h = max(0, int(content_h))
        self.offset = scroll_offset_for_content(self.offset, self.viewport_h, self.content_h)


# ---------------------------------------------------------------------------
# Hit-testable widgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MenuItem:
    label: str
    action: str
    enabled: bool = True


@dataclass(slots=True)
class FloatingMenu:
    x: int
    y: int
    items: list[MenuItem]
    width: int = 230
    row_h: int = 24

    def height(self) -> int:
        return max(1, len(self.items)) * self.row_h + 8

    def hit(self, px: int, py: int) -> MenuItem | None:
        if px < self.x or px > self.x + self.width:
            return None
        rel = py - self.y - 4
        if rel < 0:
            return None
        idx = rel // self.row_h
        if 0 <= idx < len(self.items):
            item = self.items[int(idx)]
            return item if item.enabled else None
        return None


@dataclass(slots=True)
class Button:
    rect: tuple[int, int, int, int]
    label: str
    action: str
    active: bool = False
    enabled: bool = True

    def hit(self, px: int, py: int) -> bool:
        x, y, w, h = self.rect
        return self.enabled and x <= px <= x + w and y <= py <= y + h


@dataclass(slots=True)
class Dropdown:
    x: int
    y: int
    width: int
    options: list[tuple[str, str]]
    row_h: int = 24
    max_visible: int = 12
    scroll: int = 0

    def height(self) -> int:
        return max(1, min(len(self.options), self.max_visible)) * self.row_h + 8

    def visible_options(self) -> list[tuple[str, str]]:
        start = clamp_i(self.scroll, 0, max(0, len(self.options) - self.max_visible))
        return self.options[start:start + self.max_visible]

    def hit(self, px: int, py: int) -> str | None:
        if px < self.x or px > self.x + self.width:
            return None
        rel = py - self.y - 4
        if rel < 0:
            return None
        idx = rel // self.row_h
        options = self.visible_options()
        if 0 <= idx < len(options):
            return options[int(idx)][1]
        return None

    def scroll_by(self, delta_rows: int) -> None:
        self.scroll = clamp_i(self.scroll + delta_rows, 0, max(0, len(self.options) - self.max_visible))


# Better name for new code; Dropdown is kept for compatibility with v9 tests.
SelectBox = Dropdown


@dataclass(slots=True)
class TextInput:
    text: str = ""
    cursor: int = 0
    max_len: int = 80
    allowed_filename_chars: bool = True

    def __post_init__(self) -> None:
        self.cursor = clamp_i(self.cursor or len(self.text), 0, len(self.text))

    def set_text(self, text: str) -> None:
        self.text = text[: self.max_len]
        self.cursor = min(self.cursor, len(self.text))

    def insert(self, s: str) -> None:
        for ch in s:
            if not ch.isprintable():
                continue
            if self.allowed_filename_chars and ch in "\\/:*?\"<>|":
                continue
            if len(self.text) >= self.max_len:
                break
            self.text = self.text[: self.cursor] + ch + self.text[self.cursor :]
            self.cursor += 1

    def backspace(self) -> None:
        if self.cursor > 0:
            self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
            self.cursor -= 1

    def delete(self) -> None:
        if self.cursor < len(self.text):
            self.text = self.text[: self.cursor] + self.text[self.cursor + 1 :]

    def move_left(self, *, word: bool = False) -> None:
        if not word:
            self.cursor = max(0, self.cursor - 1)
            return
        i = self.cursor
        while i > 0 and self.text[i - 1].isspace():
            i -= 1
        while i > 0 and not self.text[i - 1].isspace():
            i -= 1
        self.cursor = i

    def move_right(self, *, word: bool = False) -> None:
        if not word:
            self.cursor = min(len(self.text), self.cursor + 1)
            return
        i = self.cursor
        while i < len(self.text) and not self.text[i].isspace():
            i += 1
        while i < len(self.text) and self.text[i].isspace():
            i += 1
        self.cursor = i

    def handle_key(self, key: str, unicode: str = "", *, ctrl: bool = False) -> Literal["commit", "cancel", "changed", "noop"]:
        if key in {"escape", "esc"}:
            return "cancel"
        if key in {"return", "enter"}:
            return "commit"
        before = (self.text, self.cursor)
        if key == "backspace":
            self.backspace()
        elif key == "delete":
            self.delete()
        elif key == "left":
            self.move_left(word=ctrl)
        elif key == "right":
            self.move_right(word=ctrl)
        elif key == "home":
            self.cursor = 0
        elif key == "end":
            self.cursor = len(self.text)
        elif unicode:
            self.insert(unicode)
        return "changed" if (self.text, self.cursor) != before else "noop"
