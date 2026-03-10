import json
import os
import pygame

try:
    import tkinter as tk
    from tkinter import filedialog, simpledialog
except Exception:
    tk = None
    filedialog = None
    simpledialog = None

import _ps_model as model

WINDOW_W = 1280
WINDOW_H = 820
SIDEBAR_W = 270
TOPBAR_H = 54
STATUS_H = 26
FPS = 60
BG = (24, 26, 30)
PANEL = (34, 37, 43)
PANEL_2 = (45, 49, 57)
PANEL_3 = (56, 62, 74)
TEXT = (230, 232, 236)
MUTED = (150, 155, 165)
GRID = (55, 60, 68)
WHITE = (245, 245, 245)
YELLOW = (255, 220, 110)
RED = (255, 100, 100)
BLUE = (100, 170, 255)
GREEN = (110, 220, 140)
ORANGE = (255, 170, 90)
PURPLE = (188, 118, 255)
CYAN = (100, 220, 220)
DEFAULT_PROJECT = "sprite_sheet_editor_v1.0_project.json"
DEFAULT_IMAGE = "PySpineGuy.png"
HANDLE_R = 6
CORNER_R = 5
POINT_COLORS = [RED, BLUE, ORANGE, PURPLE, CYAN, YELLOW, GREEN, WHITE]
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Mini PySpine Editor")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 16)
        self.small = pygame.font.SysFont("consolas", 14)

        self.project_path = DEFAULT_PROJECT if os.path.exists(DEFAULT_PROJECT) else None
        self.image_path = None
        self.image = None
        self.sprites = {}
        self.order = []
        self.selected = None
        self.selected_point = 0

        self.zoom = 2.0
        self.offset = [SIDEBAR_W + 40.0, TOPBAR_H + 30.0]
        self.sidebar_scroll = 0
        self.space_down = False
        self.running = True
        self.status = "Ctrl+L load png/json | Ctrl+S save | drag empty to create | A add point"

        self.mode = None
        self.drag_start_world = (0, 0)
        self.drag_start_screen = (0, 0)
        self.drag_sprite_start = None
        self.drag_offset = (0, 0)
        self.resize_corner = None
        self.temp_rect = None
        self._scaled_image = None
        self._scaled_zoom = None

        self.dirty = False

        self._tk_root = None
        if tk:
            self._tk_root = tk.Tk()
            self._tk_root.withdraw()

        if self.project_path:
            self.load_project(self.project_path)
        elif os.path.exists(DEFAULT_IMAGE):
            self.load_image(DEFAULT_IMAGE)

    def canvas_rect(self):
        w, h = self.screen.get_size()
        return pygame.Rect(SIDEBAR_W, TOPBAR_H, w - SIDEBAR_W, h - TOPBAR_H - STATUS_H)

    def screen_to_world(self, pos):
        return (pos[0] - self.offset[0]) / self.zoom, (pos[1] - self.offset[1]) / self.zoom

    def world_to_screen(self, pos):
        return pos[0] * self.zoom + self.offset[0], pos[1] * self.zoom + self.offset[1]

    def sprite_screen_rect(self, s):
        x, y = self.world_to_screen((s.x, s.y))
        return pygame.Rect(round(x), round(y), round(s.width * self.zoom), round(s.height * self.zoom))

    def project_dir(self):
        if self.project_path:
            return os.path.dirname(os.path.abspath(self.project_path))
        if self.image_path:
            return os.path.dirname(os.path.abspath(self.image_path))
        return os.getcwd()

    def resolve_path(self, path):
        if not path:
            return None
        if os.path.isabs(path):
            return path
        return os.path.join(self.project_dir(), path)

    def compact_path_for_save(self, path):
        if not path:
            return ""
        try:
            rel = os.path.relpath(path, self.project_dir())
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
        except Exception:
            pass
        return path.replace("\\", "/")

    def load_image(self, path):
        try:
            self._scaled_image = None
            self._scaled_zoom = None
            self.image = pygame.image.load(path).convert_alpha()
            self.image_path = os.path.abspath(path)
            self.status = f"Loaded image: {os.path.basename(path)}"
            self.dirty = True
            return True
        except Exception as e:
            self.status = f"Image load failed: {e}"
            return False

    def load_project(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pdata = data.get("data", data)
            sprites = pdata.get("sprites", {})
            self.sprites = {k: model.Sprite.from_dict(v) for k, v in sprites.items()}
            self.order = list(self.sprites.keys())
            self.selected = self.order[0] if self.order else None
            self.selected_point = 0
            self.project_path = os.path.abspath(path)

            ui = data.get("ui_state", {}).get("viewport", {})
            self.zoom = float(ui.get("zoom", self.zoom))
            off = ui.get("offset", self.offset)
            if isinstance(off, list) and len(off) == 2:
                self.offset = [float(off[0]), float(off[1])]

            image_path = pdata.get("sprite_sheet_path", data.get("sprite_sheet_path", ""))
            img_abs = self.resolve_path(image_path)
            if img_abs and os.path.exists(img_abs):
                self.load_image(img_abs)
            self.status = f"Loaded project: {os.path.basename(path)}"
            return True
        except Exception as e:
            self.status = f"Project load failed: {e}"
            return False

    def save_project(self, path=None):
        if path:
            self.project_path = os.path.abspath(path)
        elif not self.project_path:
            path = self.pick_save_path()
            if not path:
                return False
            self.project_path = os.path.abspath(path)

        data = {
            "editor_type": "Sprite Sheet Editor v1.1",
            "data": {
                "sprites": {name: self.sprites[name].to_dict() for name in self.order if name in self.sprites},
                "sprite_sheet_path": self.compact_path_for_save(self.image_path) if self.image_path else "",
            },
            "ui_state": {
                "viewport": {"offset": self.offset, "zoom": self.zoom},
            },
        }
        try:
            with open(self.project_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.status = f"Saved: {os.path.basename(self.project_path)}"
            self.dirty = False
            return True
        except Exception as e:
            self.status = f"Save failed: {e}"
            return False

    @staticmethod
    def pick_open_path(title):
        if not filedialog:
            return None
        return filedialog.askopenfilename(
            title=title,
            filetypes=[
                ("Images or JSON", "*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.json"),
                ("JSON files", "*.json"),
                ("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
                ("All files", "*.*"),
            ],
        ) or None

    @staticmethod
    def pick_save_path():
        if not filedialog:
            return None
        return filedialog.asksaveasfilename(
            title="Save project",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        ) or None

    def confirm_discard(self):
        if not self.dirty:
            return True
        if not tk:
            return True
        import tkinter.messagebox as mb
        return mb.askokcancel("Unsaved changes", "You have unsaved changes. Quit anyway?", parent=self._tk_root)

    def prompt_text(self, title, label, initial=""):
        if not simpledialog:
            return None
        return simpledialog.askstring(title, label, initialvalue=initial, parent=self._tk_root)

    def unique_name(self, base="sprite"):
        i = 1
        while f"{base}_{i}" in self.sprites:
            i += 1
        return f"{base}_{i}"

    def selected_sprite(self):
        return self.sprites.get(self.selected)

    def select(self, name):
        if name not in self.sprites:
            return
        self.selected = name
        self.selected_point = min(self.selected_point, max(0, len(self.sprites[name].attachment_points) - 1))

    def sprite_at(self, world):
        for name in reversed(self.order):
            s = self.sprites[name]
            if s.x <= world[0] <= s.x + s.width and s.y <= world[1] <= s.y + s.height:
                return name
        return None

    @staticmethod
    def point_world(s, idx):
        p = s.attachment_points[idx]
        return s.x + s.width * p.x, s.y + s.height * p.y

    @staticmethod
    def set_point_world(s, idx, world):
        p = s.attachment_points[idx]
        p.x = min(1.0, max(0.0, (world[0] - s.x) / max(1, s.width)))
        p.y = min(1.0, max(0.0, (world[1] - s.y) / max(1, s.height)))

    def point_hit(self, s, world):
        hit = None
        best = 1e9
        rad2 = (HANDLE_R / max(self.zoom, 0.001) * 1.8) ** 2
        for i in range(len(s.attachment_points)):
            px, py = self.point_world(s, i)
            d2 = (px - world[0]) ** 2 + (py - world[1]) ** 2
            if d2 <= rad2 and d2 < best:
                hit, best = i, d2
        return hit

    def corner_hit(self, s, screen):
        rect = self.sprite_screen_rect(s)
        corners = {"tl": rect.topleft, "tr": rect.topright, "bl": rect.bottomleft, "br": rect.bottomright}
        for key, p in corners.items():
            if (p[0] - screen[0]) ** 2 + (p[1] - screen[1]) ** 2 <= (CORNER_R + 3) ** 2:
                return key
        return None

    def rename_selected(self):
        if not self.selected:
            return
        new_name = self.prompt_text("Rename sprite", "New name:", self.selected)
        if not new_name or new_name == self.selected or new_name in self.sprites:
            return
        s = self.sprites.pop(self.selected)
        s.name = new_name
        self.sprites[new_name] = s
        self.order[self.order.index(self.selected)] = new_name
        self.selected = new_name
        self.status = f"Renamed sprite to {new_name}"
        self.dirty = True

    def rename_selected_point(self):
        s = self.selected_sprite()
        if not s or not s.attachment_points:
            return
        p = s.attachment_points[self.selected_point]
        new_name = self.prompt_text("Rename point", "Point name:", p.name)
        if new_name:
            p.name = new_name
            self.status = f"Renamed point to {new_name}"
            self.dirty = True

    def delete_selected(self):
        if not self.selected:
            return
        name = self.selected
        self.sprites.pop(name, None)
        if name in self.order:
            self.order.remove(name)
        self.selected = self.order[-1] if self.order else None
        self.selected_point = 0
        self.status = f"Deleted {name}"
        self.dirty = True

    def delete_selected_point(self):
        s = self.selected_sprite()
        if not s or not s.attachment_points:
            return
        removed = s.attachment_points.pop(self.selected_point)
        self.selected_point = max(0, min(self.selected_point, len(s.attachment_points) - 1))
        self.status = f"Deleted point {removed.name}"
        self.dirty = True

    def add_point(self, world=None):
        s = self.selected_sprite()
        if not s:
            return
        names = {p.name for p in s.attachment_points}
        i = 1
        while f"point_{i}" in names:
            i += 1
        p = model.AttachPoint(f"point_{i}", 0.5, 0.5)
        s.attachment_points.append(p)
        self.selected_point = len(s.attachment_points) - 1
        if world is not None:
            self.set_point_world(s, self.selected_point, world)
        self.status = f"Added {p.name}"
        self.dirty = True

    def sidebar_click(self, pos):
        y = TOPBAR_H + 36 - self.sidebar_scroll  # match draw_sidebar exactly
        for name in self.order:
            row = pygame.Rect(10, y, SIDEBAR_W - 20, 24)
            if row.collidepoint(pos):
                self.select(name)
                return True
            y += 28

        s = self.selected_sprite()
        if s:
            y += 10  # match the gap in draw_sidebar
            y += 24  # match the "Attachment points" label row
            for i, p in enumerate(s.attachment_points):
                row = pygame.Rect(10, y, SIDEBAR_W - 20, 22)
                if row.collidepoint(pos):
                    self.selected_point = i
                    return True
                y += 24
        return False

    def load_any(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            return self.load_project(path)
        if ext in IMAGE_EXTS:
            return self.load_image(path)
        self.status = f"Unsupported file type: {ext or path}"
        return False

    def start_left_drag(self, screen_pos):
        if screen_pos[1] < TOPBAR_H:
            return
        if screen_pos[0] < SIDEBAR_W:
            self.sidebar_click(screen_pos)
            return
        world = self.screen_to_world(screen_pos)
        if self.space_down:
            self.mode = "pan"
            self.drag_start_screen = screen_pos
            return

        # Check corners of selected sprite FIRST, before sprite_at
        if self.selected:
            s = self.sprites[self.selected]
            corner = self.corner_hit(s, screen_pos)
            if corner:
                self.mode = "resize"
                self.resize_corner = corner
                self.drag_sprite_start = model.Sprite.from_dict(s.to_dict())
                self.drag_start_world = world
                return

        hit = self.sprite_at(world)
        if hit:
            s = self.sprites[hit]
            self.select(hit)
            pidx = self.point_hit(s, world)
            if pidx is not None:
                self.selected_point = pidx
                self.mode = "point"
                return
            self.mode = "move"
            self.drag_offset = (world[0] - s.x, world[1] - s.y)
            return

        self.selected = None
        self.mode = "create"
        self.drag_start_world = world
        self.temp_rect = pygame.Rect(round(world[0]), round(world[1]), 0, 0)

    def update_left_drag(self, screen_pos):
        world = self.screen_to_world(screen_pos)
        if self.mode == "pan":
            dx = screen_pos[0] - self.drag_start_screen[0]
            dy = screen_pos[1] - self.drag_start_screen[1]
            self.offset[0] += dx
            self.offset[1] += dy
            self.drag_start_screen = screen_pos
        elif self.mode == "move" and self.selected:
            s = self.sprites[self.selected]
            s.x = round(world[0] - self.drag_offset[0])
            s.y = round(world[1] - self.drag_offset[1])
            self.dirty = True
        elif self.mode == "point" and self.selected:
            s = self.sprites[self.selected]
            if 0 <= self.selected_point < len(s.attachment_points):
                self.set_point_world(s, self.selected_point, world)
            self.dirty = True
        elif self.mode == "create" and self.temp_rect is not None:
            x0, y0 = self.drag_start_world
            x1, y1 = world
            left, right = sorted((round(x0), round(x1)))
            top, bot = sorted((round(y0), round(y1)))
            self.temp_rect = pygame.Rect(left, top, right - left, bot - top)
        elif self.mode == "resize" and self.selected:
            s0 = self.drag_sprite_start
            if not s0:
                return
            x0, y0 = s0.x, s0.y
            x1, y1 = s0.x + s0.width, s0.y + s0.height
            wx, wy = round(world[0]), round(world[1])

            MIN_SIZE = 4
            if "l" in self.resize_corner:
                x0 = min(wx, x1 - MIN_SIZE)
            if "r" in self.resize_corner:
                x1 = max(wx, x0 + MIN_SIZE)
            if "t" in self.resize_corner:
                y0 = min(wy, y1 - MIN_SIZE)
            if "b" in self.resize_corner:
                y1 = max(wy, y0 + MIN_SIZE)

            s = self.sprites[self.selected]
            old_points = [self.point_world(s0, i) for i in range(len(s0.attachment_points))]
            s.x, s.y, s.width, s.height = x0, y0, x1 - x0, y1 - y0
            for i, p in enumerate(old_points):
                if i < len(s.attachment_points):
                    self.set_point_world(s, i, p)

            self.dirty = True

    def end_left_drag(self):
        if self.mode == "create" and self.temp_rect and self.temp_rect.w > 1 and self.temp_rect.h > 1:
            name = self.unique_name()
            self.sprites[name] = model.Sprite(
                name,
                self.temp_rect.x,
                self.temp_rect.y,
                self.temp_rect.w,
                self.temp_rect.h,
                [model.AttachPoint("origin", 0.5, 0.5), model.AttachPoint("endpoint", 0.5, 0.85)],
            )
            self.order.append(name)
            self.selected = name
            self.selected_point = 0
            self.status = f"Created {name}"
            self.dirty = True

        self.mode = None
        self.temp_rect = None
        self.drag_sprite_start = None
        self.resize_corner = None

    def zoom_at(self, factor, screen_pos):
        old_world = self.screen_to_world(screen_pos)
        self.zoom = max(0.1, min(64.0, self.zoom * factor))
        self.offset[0] = screen_pos[0] - old_world[0] * self.zoom
        self.offset[1] = screen_pos[1] - old_world[1] * self.zoom

    def draw_text(self, text, pos, color=TEXT, small=False):
        surf = (self.small if small else self.font).render(text, True, color)
        self.screen.blit(surf, pos)

    def draw_top_bar(self):
        w, _ = self.screen.get_size()
        pygame.draw.rect(self.screen, PANEL, (0, 0, w, TOPBAR_H))
        pygame.draw.line(self.screen, PANEL_2, (0, TOPBAR_H - 1), (w, TOPBAR_H - 1), 1)
        self.draw_text("Mini PySpine Editor", (12, 10), WHITE)
        self.draw_text(
            "Ctrl+L load png/json | Ctrl+S save | Ctrl+Shift+S save as | A add point | Tab next point | F2 rename sprite | Shift+F2 rename point",
            (240, 12), MUTED, True)

    def draw_sidebar(self):
        _, h = self.screen.get_size()
        pygame.draw.rect(self.screen, PANEL, (0, TOPBAR_H, SIDEBAR_W, h - TOPBAR_H - STATUS_H))
        pygame.draw.line(self.screen, PANEL_2, (SIDEBAR_W, TOPBAR_H), (SIDEBAR_W, h - STATUS_H), 1)
        self.draw_text("Sprites", (12, TOPBAR_H + 10))
        y = TOPBAR_H + 36 - self.sidebar_scroll
        for name in self.order:
            row = pygame.Rect(10, y, SIDEBAR_W - 20, 24)
            color = (70, 86, 112) if name == self.selected else PANEL_2
            pygame.draw.rect(self.screen, color, row, border_radius=6)
            self.draw_text(name, (16, y + 4), WHITE if name == self.selected else TEXT, True)
            y += 28

        s = self.selected_sprite()
        if s:
            y += 10
            self.draw_text("Attachment points", (12, y), WHITE, True)
            y += 24
            for i, p in enumerate(s.attachment_points):
                row = pygame.Rect(10, y, SIDEBAR_W - 20, 22)
                color = PANEL_3 if i == self.selected_point else PANEL_2
                pygame.draw.rect(self.screen, color, row, border_radius=6)
                c = POINT_COLORS[i % len(POINT_COLORS)]
                pygame.draw.circle(self.screen, c, (20, y + 11), 5)
                self.draw_text(p.name, (32, y + 3), WHITE if i == self.selected_point else TEXT, True)
                self.draw_text(f"({p.x:.2f}, {p.y:.2f})", (SIDEBAR_W - 105, y + 3), MUTED, True)
                y += 24
            self.draw_text("Del sprite | Shift+Del point", (12, h - STATUS_H - 24), MUTED, True)

    def draw_canvas(self):
        canvas = self.canvas_rect()
        pygame.draw.rect(self.screen, (20, 22, 25), canvas)
        clip_prev = self.screen.get_clip()
        self.screen.set_clip(canvas)

        if self.image:
            for ix in range(0, self.image.get_width() + 1, 32):
                x, _ = self.world_to_screen((ix, 0))
                pygame.draw.line(self.screen, GRID, (x, canvas.top), (x, canvas.bottom))
            for iy in range(0, self.image.get_height() + 1, 32):
                _, y = self.world_to_screen((0, iy))
                pygame.draw.line(self.screen, GRID, (canvas.left, y), (canvas.right, y))
            img_w = max(1, round(self.image.get_width() * self.zoom))
            img_h = max(1, round(self.image.get_height() * self.zoom))

            if self._scaled_zoom != self.zoom:
                self._scaled_image = pygame.transform.scale(self.image, (img_w, img_h))
                self._scaled_zoom = self.zoom
            self.screen.blit(self._scaled_image, (round(self.offset[0]), round(self.offset[1])))

        for name in self.order:
            s = self.sprites[name]
            rect = self.sprite_screen_rect(s)
            color = YELLOW if name == self.selected else GREEN
            pygame.draw.rect(self.screen, color, rect, 2)
            self.draw_text(name, (rect.x + 2, rect.y - 18), color, True)
            for i, p in enumerate(s.attachment_points):
                wp = self.point_world(s, i)
                sp = self.world_to_screen(wp)
                c = POINT_COLORS[i % len(POINT_COLORS)]
                pygame.draw.circle(self.screen, c, (round(sp[0]), round(sp[1])), HANDLE_R)
                if name == self.selected and i == self.selected_point:
                    pygame.draw.circle(self.screen, WHITE, (round(sp[0]), round(sp[1])), HANDLE_R + 3, 1)
                    self.draw_text(p.name, (sp[0] + 8, sp[1] - 18), WHITE, True)
            if name == self.selected:
                for p in (rect.topleft, rect.topright, rect.bottomleft, rect.bottomright):
                    pygame.draw.circle(self.screen, WHITE, p, CORNER_R)

        if self.temp_rect:
            x, y = self.world_to_screen((self.temp_rect.x, self.temp_rect.y))
            r = pygame.Rect(round(x), round(y), round(self.temp_rect.w * self.zoom),
                            round(self.temp_rect.h * self.zoom))
            pygame.draw.rect(self.screen, YELLOW, r, 2)

        self.screen.set_clip(clip_prev)

        s = self.selected_sprite()
        if s:
            info = f"{s.name}  x:{s.x} y:{s.y} w:{s.width} h:{s.height}  points:{len(s.attachment_points)}"
            self.draw_text(info, (canvas.x + 12, canvas.y + 10), WHITE, True)
            if s.attachment_points:
                p = s.attachment_points[self.selected_point]
                self.draw_text(f"selected point: {p.name} ({p.x:.2f}, {p.y:.2f})", (canvas.x + 12, canvas.y + 28),
                               MUTED, True)

    def draw_status(self):
        w, h = self.screen.get_size()
        pygame.draw.rect(self.screen, PANEL, (0, h - STATUS_H, w, STATUS_H))
        self.draw_text(self.status, (8, h - 22), MUTED, True)

    def draw(self):
        self.screen.fill(BG)
        self.draw_canvas()
        self.draw_sidebar()
        self.draw_top_bar()  # draw last so it stays above viewport content
        self.draw_status()
        pygame.display.flip()

    def handle_event(self, e):
        if e.type == pygame.QUIT:
            if self.confirm_discard():
                self.running = False

        elif e.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            shift = bool(mods & pygame.KMOD_SHIFT)
            if e.key == pygame.K_SPACE:
                self.space_down = True
            elif ctrl and e.key == pygame.K_l:
                path = self.pick_open_path("Load image or project")
                if path:
                    self.load_any(path)
            elif ctrl and e.key == pygame.K_s:
                self.save_project(self.pick_save_path() if shift else None)
            elif e.key == pygame.K_F2 and shift:
                self.rename_selected_point()
            elif e.key == pygame.K_F2:
                self.rename_selected()
            elif e.key == pygame.K_DELETE and shift:
                self.delete_selected_point()
            elif e.key == pygame.K_DELETE:
                self.delete_selected()
            elif e.key == pygame.K_TAB:
                s = self.selected_sprite()
                if s and s.attachment_points:
                    self.selected_point = (self.selected_point + 1) % len(s.attachment_points)
            elif e.key == pygame.K_a:
                mx, my = pygame.mouse.get_pos()
                self.add_point(self.screen_to_world((mx, my)) if self.canvas_rect().collidepoint((mx, my)) else None)
        elif e.type == pygame.KEYUP and e.key == pygame.K_SPACE:
            self.space_down = False
        elif e.type == pygame.MOUSEBUTTONDOWN:
            if e.button == 1:
                self.start_left_drag(e.pos)
            elif e.button == 2:
                self.mode = "pan"
                self.drag_start_screen = e.pos

        elif e.type == pygame.MOUSEBUTTONUP:
            if e.button == 1:
                self.end_left_drag()
            elif e.button == 2 and self.mode == "pan":
                self.mode = None
        elif e.type == pygame.MOUSEMOTION and self.mode:
            self.update_left_drag(e.pos)
        elif e.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if mx < SIDEBAR_W:
                s = self.selected_sprite()
                points_count = len(s.attachment_points) if s else 0
                content_h = len(self.order) * 28 + points_count * 24 + 80
                max_scroll = max(0, content_h - (self.screen.get_height() - TOPBAR_H - STATUS_H))
                self.sidebar_scroll = max(0, min(max_scroll, self.sidebar_scroll - e.y * 24))
            else:
                self.zoom_at(1.1 if e.y > 0 else 1 / 1.1, (mx, my))

    def run(self):
        while self.running:
            for e in pygame.event.get():
                self.handle_event(e)
            self.draw()
            self.clock.tick(FPS)
        if self._tk_root:
            self._tk_root.destroy()
        pygame.quit()


if __name__ == "__main__":
    App().run()
