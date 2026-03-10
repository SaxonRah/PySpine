import copy
import json
import math
import os
from dataclasses import dataclass, field

import pygame

try:
    import tkinter as tk
    from tkinter import filedialog, simpledialog
except Exception:
    tk = None
    filedialog = None
    simpledialog = None

import pyspine_model as model
import pyspine_solver as solver

WINDOW_W = 1500
WINDOW_H = 940
LEFT_W = 280
RIGHT_W = 320
TOPBAR_H = 56
STATUS_H = 26
TIMELINE_H = 180
FPS = 60

BG = (24, 26, 30)
PANEL = (34, 37, 43)
PANEL_2 = (45, 49, 57)
PANEL_3 = (56, 62, 74)
TEXT = (230, 232, 236)
MUTED = (150, 155, 165)
GRID = (56, 60, 68)
WHITE = (245, 245, 245)
YELLOW = (255, 220, 110)
RED = (255, 110, 110)
BLUE = (110, 170, 255)
GREEN = (110, 220, 140)
ORANGE = (255, 170, 90)
PURPLE = (188, 118, 255)
CYAN = (110, 220, 220)
POINT_COLORS = [RED, BLUE, ORANGE, PURPLE, CYAN, YELLOW, GREEN, WHITE]
DEFAULT_ANIMATION = "mini_pyspine_animation.json"
DEFAULT_ASSEMBLY = "mini_pyspine_assembly.json"
HANDLE_R = 7
ROTATE_HANDLE_DIST = 42
TRACK_ORDER = ["root_x", "root_y", "rotation", "local_rotation"]
TRACK_LABELS = {
    "root_x": "root x",
    "root_y": "root y",
    "rotation": "root rot",
    "local_rotation": "local rot",
}
TRACK_COLORS = {
    "root_x": CYAN,
    "root_y": GREEN,
    "rotation": ORANGE,
    "local_rotation": PURPLE,
}


@dataclass
class AnimationClip:
    name: str
    length: int = 48
    fps: int = 12
    tracks: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=str(d.get("name", "anim")),
            length=max(1, int(d.get("length", 48))),
            fps=max(1, int(d.get("fps", 12))),
            tracks=copy.deepcopy(d.get("tracks", {})),
        )

    def to_dict(self):
        return {
            "name": self.name,
            "length": self.length,
            "fps": self.fps,
            "tracks": copy.deepcopy(self.tracks),
        }


class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Mini PySpine Animation Editor")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 16)
        self.small = pygame.font.SysFont("consolas", 14)
        self.big = pygame.font.SysFont("consolas", 18)

        self._tk_root = None
        if tk:
            self._tk_root = tk.Tk()
            self._tk_root.withdraw()

        self.sprite_project_path = None
        self.assembly_path = DEFAULT_ASSEMBLY if os.path.exists(DEFAULT_ASSEMBLY) else None
        self.animation_path = DEFAULT_ANIMATION if os.path.exists(DEFAULT_ANIMATION) else None
        self.sheet_path = None
        self.sheet_image = None

        self.sprites = {}
        self.sprite_order = []
        self.instances = {}
        self.instance_order = []
        self.animations = {}
        self.animation_order = []

        self.crops = {}
        self.thumb_cache = {}
        self.left_scroll = 0
        self.right_scroll = 0
        self.timeline_scroll_x = 0
        self.timeline_scroll_y = 0

        self.selected_animation = None
        self.selected_instance = None
        self.selected_track = "local_rotation"
        self.selected_point_name = None
        self.current_frame = 0.0
        self.playing = False
        self.loop = True

        self.zoom = 1.5
        self.offset = [LEFT_W + 150.0, TOPBAR_H + 90.0]
        self.space_down = False
        self.running = True
        self.status = "Ctrl+L load assembly | Ctrl+O load animation | K key | Space play | drag parts to pose"
        self.dirty = False

        self.mode = None
        self.drag_start_screen = (0, 0)
        self.drag_start_world = (0.0, 0.0)
        self.drag_origin_root = (0.0, 0.0)
        self.drag_rotate_anchor = (0.0, 0.0)
        self.drag_pivot_local_unrotated = (0.0, 0.0)
        self.drag_pose_instances = None
        self.drag_pose_selected_name = None
        self.drag_timeline_start_frame = 0.0

        if self.assembly_path and os.path.exists(self.assembly_path):
            self.load_assembly(self.assembly_path)
        if self.animation_path and os.path.exists(self.animation_path):
            self.load_animation(self.animation_path)
        if not self.animations:
            self.new_animation("anim_1")

    # ---------- basic helpers ----------
    def canvas_rect(self):
        w, h = self.screen.get_size()
        return pygame.Rect(
            LEFT_W,
            TOPBAR_H,
            max(10, w - LEFT_W - RIGHT_W),
            max(10, h - TOPBAR_H - STATUS_H - TIMELINE_H),
        )

    def timeline_rect(self):
        w, h = self.screen.get_size()
        return pygame.Rect(
            LEFT_W,
            h - STATUS_H - TIMELINE_H,
            max(10, w - LEFT_W - RIGHT_W),
            TIMELINE_H,
        )

    def project_dir(self):
        if self.animation_path:
            return os.path.dirname(os.path.abspath(self.animation_path))
        if self.assembly_path:
            return os.path.dirname(os.path.abspath(self.assembly_path))
        if self.sprite_project_path:
            return os.path.dirname(os.path.abspath(self.sprite_project_path))
        if self.sheet_path:
            return os.path.dirname(os.path.abspath(self.sheet_path))
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

    def draw_text(self, text, pos, color=TEXT, small=False, big=False):
        font = self.big if big else self.small if small else self.font
        surf = font.render(text, True, color)
        self.screen.blit(surf, pos)

    def world_to_screen(self, pos):
        return pos[0] * self.zoom + self.offset[0], pos[1] * self.zoom + self.offset[1]

    def screen_to_world(self, pos):
        return (pos[0] - self.offset[0]) / self.zoom, (pos[1] - self.offset[1]) / self.zoom

    def unique_instance_name(self, base):
        i = 1
        seed = base.replace(" ", "_") or "part"
        while f"{seed}_{i}" in self.instances:
            i += 1
        return f"{seed}_{i}"

    def unique_animation_name(self, base="anim"):
        i = 1
        while f"{base}_{i}" in self.animations:
            i += 1
        return f"{base}_{i}"

    def selected_inst(self):
        return self.instances.get(self.selected_instance)

    def selected_clip(self):
        return self.animations.get(self.selected_animation)

    def current_frame_index(self):
        clip = self.selected_clip()
        if not clip:
            return 0
        return max(0, min(clip.length - 1, int(round(self.current_frame))))

    # ---------- dialogs ----------
    @staticmethod
    def pick_open_path(title, filters):
        if not filedialog:
            return None
        return filedialog.askopenfilename(title=title, filetypes=filters) or None

    @staticmethod
    def pick_save_path(title, ext=".json"):
        if not filedialog:
            return None
        return filedialog.asksaveasfilename(
            title=title,
            defaultextension=ext,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        ) or None

    def prompt_text(self, title, label, initial=""):
        if not simpledialog:
            return None
        return simpledialog.askstring(title, label, initialvalue=initial, parent=self._tk_root)

    def prompt_int(self, title, label, initial=0):
        if not simpledialog:
            return None
        return simpledialog.askinteger(title, label, initialvalue=initial, parent=self._tk_root)

    # ---------- load/save ----------
    def load_sheet(self, path):
        try:
            self.sheet_image = pygame.image.load(path).convert_alpha()
            self.sheet_path = os.path.abspath(path)
            self.crops.clear()
            self.thumb_cache.clear()
            self.build_crops()
            return True
        except Exception as e:
            self.status = f"Image load failed: {e}"
            return False

    def build_crops(self):
        self.crops = {}
        self.thumb_cache = {}
        if not self.sheet_image:
            return
        for name in self.sprite_order:
            s = self.sprites[name]
            r = pygame.Rect(s.x, s.y, s.width, s.height)
            try:
                self.crops[name] = self.sheet_image.subsurface(r).copy()
            except Exception:
                pass

    def load_sprite_project(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pdata = data.get("data", data)
            sprites = pdata.get("sprites", {})
            self.sprites = {k: model.Sprite.from_dict(v) for k, v in sprites.items()}
            self.sprite_order = list(self.sprites.keys())
            self.sprite_project_path = os.path.abspath(path)
            img_path = pdata.get("sprite_sheet_path", data.get("sprite_sheet_path", ""))
            img_abs = self.resolve_path(img_path)
            if img_abs and os.path.exists(img_abs):
                self.load_sheet(img_abs)
            return True
        except Exception as e:
            self.status = f"Sprite project load failed: {e}"
            return False

    def load_assembly(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assembly_path = os.path.abspath(path)
            sprite_project = data.get("sprite_project_path", "")
            sprite_abs = self.resolve_path(sprite_project)
            if sprite_abs and os.path.exists(sprite_abs):
                self.load_sprite_project(sprite_abs)
            self.instances = {}
            self.instance_order = []
            for raw in data.get("instances", []):
                inst = model.Instance.from_dict(raw)
                self.instances[inst.name] = inst
                self.instance_order.append(inst.name)
            self.selected_instance = self.instance_order[0] if self.instance_order else None
            ui = data.get("ui_state", {})
            self.zoom = float(ui.get("zoom", self.zoom))
            off = ui.get("offset", self.offset)
            if isinstance(off, list) and len(off) == 2:
                self.offset = [float(off[0]), float(off[1])]
            self.status = f"Loaded assembly: {os.path.basename(path)}"
            return True
        except Exception as e:
            self.status = f"Assembly load failed: {e}"
            return False

    def load_animation(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.animation_path = os.path.abspath(path)
            assembly_rel = data.get("assembly_path", "")
            assembly_abs = self.resolve_path(assembly_rel)
            if assembly_abs and os.path.exists(assembly_abs):
                self.load_assembly(assembly_abs)
            self.animations = {}
            self.animation_order = []
            for raw in data.get("animations", []):
                clip = AnimationClip.from_dict(raw)
                self.animations[clip.name] = clip
                self.animation_order.append(clip.name)
            self.selected_animation = self.animation_order[0] if self.animation_order else None
            ui = data.get("ui_state", {})
            self.current_frame = float(ui.get("current_frame", 0.0))
            self.timeline_scroll_x = int(ui.get("timeline_scroll_x", 0))
            self.timeline_scroll_y = int(ui.get("timeline_scroll_y", 0))
            self.status = f"Loaded animation: {os.path.basename(path)}"
            self.dirty = False
            return True
        except Exception as e:
            self.status = f"Animation load failed: {e}"
            return False

    def save_animation(self, path=None):
        if path:
            self.animation_path = os.path.abspath(path)
        elif not self.animation_path:
            path = self.pick_save_path("Save animation")
            if not path:
                return False
            self.animation_path = os.path.abspath(path)

        data = {
            "editor_type": "Mini PySpine Animation v1",
            "assembly_path": self.compact_path_for_save(self.assembly_path) if self.assembly_path else "",
            "animations": [self.animations[name].to_dict() for name in self.animation_order if name in self.animations],
            "ui_state": {
                "current_frame": self.current_frame,
                "timeline_scroll_x": self.timeline_scroll_x,
                "timeline_scroll_y": self.timeline_scroll_y,
            },
        }
        try:
            with open(self.animation_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.status = f"Saved animation: {os.path.basename(self.animation_path)}"
            self.dirty = False
            return True
        except Exception as e:
            self.status = f"Save failed: {e}"
            return False

    # ---------- animation data ----------
    def new_animation(self, name=None):
        name = name or self.unique_animation_name()
        clip = AnimationClip(name=name, length=48, fps=12, tracks={})
        self.animations[name] = clip
        self.animation_order.append(name)
        self.selected_animation = name
        self.current_frame = 0.0
        self.dirty = True
        self.status = f"Created animation: {name}"

    def rename_selected_animation(self):
        clip = self.selected_clip()
        if not clip:
            return
        new_name = self.prompt_text("Rename animation", "New name:", clip.name)
        if not new_name or new_name == clip.name or new_name in self.animations:
            return
        old = clip.name
        self.animations.pop(old)
        clip.name = new_name
        self.animations[new_name] = clip
        self.animation_order[self.animation_order.index(old)] = new_name
        self.selected_animation = new_name
        self.dirty = True
        self.status = f"Renamed animation to {new_name}"

    def delete_selected_animation(self):
        clip = self.selected_clip()
        if not clip:
            return
        name = clip.name
        self.animations.pop(name, None)
        if name in self.animation_order:
            self.animation_order.remove(name)
        self.selected_animation = self.animation_order[0] if self.animation_order else None
        if not self.selected_animation:
            self.new_animation(self.unique_animation_name())
        self.current_frame = 0.0
        self.dirty = True
        self.status = f"Deleted animation: {name}"

    def track_dict(self, clip, inst_name, track_name, create=False):
        it = clip.tracks.get(inst_name)
        if it is None and create:
            it = {}
            clip.tracks[inst_name] = it
        if it is None:
            return None
        tr = it.get(track_name)
        if tr is None and create:
            tr = {}
            it[track_name] = tr
        return tr

    def get_track_value_at(self, clip, inst_name, track_name, frame, default_value):
        tr = self.track_dict(clip, inst_name, track_name, create=False)
        if not tr:
            return default_value
        items = []
        for k, v in tr.items():
            try:
                items.append((int(k), float(v)))
            except Exception:
                pass
        if not items:
            return default_value
        items.sort()
        if frame <= items[0][0]:
            return items[0][1]
        if frame >= items[-1][0]:
            return items[-1][1]
        for i in range(len(items) - 1):
            f0, v0 = items[i]
            f1, v1 = items[i + 1]
            if f0 <= frame <= f1:
                if f0 == f1:
                    return v0
                t = (frame - f0) / (f1 - f0)
                return v0 + (v1 - v0) * t
        return default_value

    def posed_instances(self, frame=None):
        frame = self.current_frame if frame is None else frame
        posed = {name: copy.deepcopy(inst) for name, inst in self.instances.items()}
        clip = self.selected_clip()
        if not clip:
            return posed
        for name in self.instance_order:
            inst = posed.get(name)
            base = self.instances.get(name)
            if not inst or not base:
                continue
            inst.root_x = self.get_track_value_at(clip, name, "root_x", frame, base.root_x)
            inst.root_y = self.get_track_value_at(clip, name, "root_y", frame, base.root_y)
            inst.rotation = self.get_track_value_at(clip, name, "rotation", frame, base.rotation)
            inst.local_rotation = self.get_track_value_at(clip, name, "local_rotation", frame, base.local_rotation)
        return posed

    def selected_pose_instance(self):
        posed = self.posed_instances()
        return posed.get(self.selected_instance)

    def set_key(self, track_name=None, frame=None, value=None):
        clip = self.selected_clip()
        inst = self.selected_inst()
        if not clip or not inst:
            return
        track_name = track_name or self.selected_track
        frame = self.current_frame_index() if frame is None else int(frame)
        posed = self.posed_instances(frame)
        pose_inst = posed.get(inst.name)
        if not pose_inst:
            return
        if value is None:
            value = getattr(pose_inst, track_name)
        tr = self.track_dict(clip, inst.name, track_name, create=True)
        tr[str(frame)] = float(value)
        self.dirty = True
        self.status = f"Keyed {inst.name}.{track_name} @ {frame}"

    def delete_key(self, track_name=None, frame=None):
        clip = self.selected_clip()
        inst = self.selected_inst()
        if not clip or not inst:
            return
        track_name = track_name or self.selected_track
        frame = self.current_frame_index() if frame is None else int(frame)
        tr = self.track_dict(clip, inst.name, track_name, create=False)
        if not tr or str(frame) not in tr:
            return
        del tr[str(frame)]
        if not tr:
            clip.tracks.get(inst.name, {}).pop(track_name, None)
        self.dirty = True
        self.status = f"Deleted key {inst.name}.{track_name} @ {frame}"

    def has_key(self, inst_name, track_name, frame):
        clip = self.selected_clip()
        if not clip:
            return False
        tr = self.track_dict(clip, inst_name, track_name, create=False)
        return bool(tr and str(int(frame)) in tr)

    def clear_selected_instance_keys(self):
        clip = self.selected_clip()
        inst = self.selected_inst()
        if not clip or not inst:
            return
        if inst.name in clip.tracks:
            clip.tracks.pop(inst.name, None)
            self.dirty = True
            self.status = f"Cleared keys for {inst.name}"

    # ---------- hit testing ----------
    def point_hit(self, posed_instances, screen_pos):
        best = None
        best_d2 = (HANDLE_R + 6) ** 2
        for name in self.instance_order:
            inst = posed_instances.get(name)
            sprite = solver.get_sprite(self.sprites, inst)
            if not sprite:
                continue
            for i, p in enumerate(sprite.attachment_points):
                wp = solver.get_world_point(posed_instances, self.sprites, name, p.name)
                sp = self.world_to_screen(wp)
                d2 = (sp[0] - screen_pos[0]) ** 2 + (sp[1] - screen_pos[1]) ** 2
                if d2 <= best_d2:
                    best_d2 = d2
                    best = (name, p.name, i)
        return best

    def instance_screen_poly(self, posed_instances, name):
        inst = posed_instances.get(name)
        sprite = solver.get_sprite(self.sprites, inst) if inst else None
        if not inst or not sprite:
            return None
        tf = solver.get_world_transform(posed_instances, self.sprites, name)
        corners = [(0, 0), (sprite.width, 0), (sprite.width, sprite.height), (0, sprite.height)]
        poly = []
        for c in corners:
            wc = solver.rotate_vec(c, tf["rotation"])
            world = (tf["root"][0] + wc[0], tf["root"][1] + wc[1])
            poly.append(self.world_to_screen(world))
        return poly

    @staticmethod
    def point_in_poly(pt, poly):
        inside = False
        x, y = pt
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            hit = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi)
            if hit:
                inside = not inside
            j = i
        return inside

    def instance_hit(self, posed_instances, screen_pos):
        for name in reversed(self.instance_order):
            poly = self.instance_screen_poly(posed_instances, name)
            if poly and self.point_in_poly(screen_pos, poly):
                return name
        return None

    def rotate_handle_screen(self, posed_instances, name):
        inst = posed_instances.get(name)
        sprite = solver.get_sprite(self.sprites, inst) if inst else None
        if not inst or not sprite:
            return None
        tf = solver.get_world_transform(posed_instances, self.sprites, name)
        pivot_name = inst.self_point if inst.parent else (self.selected_point_name or (sprite.attachment_points[0].name if sprite.attachment_points else None))
        if pivot_name:
            pivot = solver.get_world_point(posed_instances, self.sprites, name, pivot_name)
        else:
            center_local = solver.rotate_vec((sprite.width / 2, sprite.height / 2), tf["rotation"])
            pivot = (tf["root"][0] + center_local[0], tf["root"][1] + center_local[1])
        local_right = solver.rotate_vec((ROTATE_HANDLE_DIST / self.zoom, 0), tf["rotation"])
        screen_pivot = self.world_to_screen(pivot)
        return screen_pivot[0] + local_right[0] * self.zoom, screen_pivot[1] + local_right[1] * self.zoom

    # ---------- drawing helpers ----------
    def get_thumb(self, sprite_name, h=48):
        key = (sprite_name, h)
        if key in self.thumb_cache:
            return self.thumb_cache[key]
        surf = self.crops.get(sprite_name)
        if not surf:
            return None
        scale = h / max(1, surf.get_height())
        w = max(1, int(round(surf.get_width() * scale)))
        thumb = pygame.transform.smoothscale(surf, (w, h))
        self.thumb_cache[key] = thumb
        return thumb

    def timeline_metrics(self):
        rect = self.timeline_rect()
        frame_w = 18
        row_h = 24
        header_h = 28
        label_w = 120
        return rect, frame_w, row_h, header_h, label_w

    # ---------- input ----------
    def left_panel_click(self, pos):
        y = TOPBAR_H + 34 - self.left_scroll
        for name in self.animation_order:
            row = pygame.Rect(10, y, LEFT_W - 20, 28)
            if row.collidepoint(pos):
                self.selected_animation = name
                self.current_frame = min(self.current_frame, max(0, self.selected_clip().length - 1))
                return True
            y += 32
        y += 8
        for name in self.instance_order:
            row = pygame.Rect(10, y, LEFT_W - 20, 24)
            if row.collidepoint(pos):
                self.selected_instance = name
                return True
            y += 28
        return False

    def right_panel_click(self, pos):
        x0 = self.screen.get_width() - RIGHT_W
        inst = self.selected_inst()
        if not inst:
            return False
        y = TOPBAR_H + 36 - self.right_scroll
        for t in TRACK_ORDER:
            row = pygame.Rect(x0 + 10, y, RIGHT_W - 20, 24)
            if row.collidepoint(pos):
                self.selected_track = t
                return True
            y += 28
        return False

    def timeline_click(self, pos):
        rect, frame_w, row_h, header_h, label_w = self.timeline_metrics()
        if not rect.collidepoint(pos):
            return False
        local_x = pos[0] - rect.x
        local_y = pos[1] - rect.y
        if local_y < header_h:
            frame = (local_x - label_w + self.timeline_scroll_x) // frame_w
            clip = self.selected_clip()
            if clip:
                self.current_frame = max(0, min(clip.length - 1, float(frame)))
            self.mode = "scrub"
            return True

        row = int((local_y - header_h + self.timeline_scroll_y) // row_h)
        if row < 0:
            return True
        if row >= len(self.instance_order) * len(TRACK_ORDER):
            return True
        inst_idx = row // len(TRACK_ORDER)
        track_idx = row % len(TRACK_ORDER)
        self.selected_instance = self.instance_order[inst_idx]
        self.selected_track = TRACK_ORDER[track_idx]

        frame = int((local_x - label_w + self.timeline_scroll_x) // frame_w)
        clip = self.selected_clip()
        if clip:
            frame = max(0, min(clip.length - 1, frame))
            self.current_frame = float(frame)
        return True

    def start_left_drag(self, pos):
        if pos[1] < TOPBAR_H:
            return
        if self.timeline_rect().collidepoint(pos):
            self.timeline_click(pos)
            return
        if pos[0] < LEFT_W:
            self.left_panel_click(pos)
            return
        if pos[0] >= self.screen.get_width() - RIGHT_W:
            self.right_panel_click(pos)
            return
        if self.space_down:
            self.mode = "pan"
            self.drag_start_screen = pos
            return

        posed = self.posed_instances()
        point_hit = self.point_hit(posed, pos)
        if point_hit:
            name, point_name, _ = point_hit
            self.selected_instance = name
            self.selected_point_name = point_name

        inst_name = self.instance_hit(posed, pos)
        if not inst_name:
            self.selected_instance = None
            return

        self.selected_instance = inst_name
        self.drag_pose_instances = posed
        self.drag_pose_selected_name = inst_name
        inst = posed[inst_name]
        sprite = solver.get_sprite(self.sprites, inst)
        tf = solver.get_world_transform(posed, self.sprites, inst_name)

        def set_rotate_pivot(pivot_world):
            self.drag_rotate_anchor = pivot_world
            self.drag_start_screen = pos
            world_offset = (pivot_world[0] - tf["root"][0], pivot_world[1] - tf["root"][1])
            self.drag_pivot_local_unrotated = solver.rotate_vec(world_offset, -tf["rotation"])

        def get_pivot_world():
            pivot_name = inst.self_point if inst.parent else (
                self.selected_point_name or (sprite.attachment_points[0].name if sprite and sprite.attachment_points else None)
            )
            if pivot_name:
                return solver.get_world_point(posed, self.sprites, inst_name, pivot_name)
            if sprite:
                center_local = solver.rotate_vec((sprite.width / 2, sprite.height / 2), tf["rotation"])
                return tf["root"][0] + center_local[0], tf["root"][1] + center_local[1]
            return tf["root"]

        handle = self.rotate_handle_screen(posed, inst_name)
        if handle and (handle[0] - pos[0]) ** 2 + (handle[1] - pos[1]) ** 2 <= (HANDLE_R + 4) ** 2:
            self.mode = "rotate_pose"
            set_rotate_pivot(get_pivot_world())
            return

        if inst.parent:
            self.mode = "rotate_pose"
            pivot_name = inst.self_point or (sprite.attachment_points[0].name if sprite and sprite.attachment_points else None)
            if pivot_name:
                set_rotate_pivot(solver.get_world_point(posed, self.sprites, inst_name, pivot_name))
            else:
                set_rotate_pivot(get_pivot_world())
        else:
            mods = pygame.key.get_mods()
            if mods & pygame.KMOD_ALT:
                self.mode = "rotate_pose"
                set_rotate_pivot(get_pivot_world())
            else:
                self.mode = "move_pose"
                self.drag_origin_root = (inst.root_x, inst.root_y)
                self.drag_start_world = self.screen_to_world(pos)

    def update_left_drag(self, pos):
        if self.mode == "pan":
            dx = pos[0] - self.drag_start_screen[0]
            dy = pos[1] - self.drag_start_screen[1]
            self.offset[0] += dx
            self.offset[1] += dy
            self.drag_start_screen = pos
            return
        if self.mode == "scrub":
            rect, frame_w, row_h, header_h, label_w = self.timeline_metrics()
            clip = self.selected_clip()
            if clip:
                frame = int((pos[0] - rect.x - label_w + self.timeline_scroll_x) // frame_w)
                self.current_frame = float(max(0, min(clip.length - 1, frame)))
            return

        posed = self.drag_pose_instances
        name = self.drag_pose_selected_name
        if not posed or not name or name not in posed:
            return
        inst = posed[name]
        if self.mode == "move_pose" and not inst.parent:
            cur = self.screen_to_world(pos)
            dx = cur[0] - self.drag_start_world[0]
            dy = cur[1] - self.drag_start_world[1]
            inst.root_x = self.drag_origin_root[0] + dx
            inst.root_y = self.drag_origin_root[1] + dy
            self.set_key("root_x", value=inst.root_x)
            self.set_key("root_y", value=inst.root_y)
        elif self.mode == "rotate_pose":
            pivot = self.drag_rotate_anchor
            mx, my = self.screen_to_world(pos)
            ang = math.degrees(math.atan2(my - pivot[1], mx - pivot[0]))
            base = solver.get_world_transform(posed, self.sprites, inst.parent)["rotation"] if inst.parent and inst.parent in posed else 0.0
            if inst.parent:
                inst.local_rotation = ang - base
                self.set_key("local_rotation", value=inst.local_rotation)
            else:
                inst.rotation = ang
                rotated = solver.rotate_vec(self.drag_pivot_local_unrotated, ang)
                inst.root_x = pivot[0] - rotated[0]
                inst.root_y = pivot[1] - rotated[1]
                self.set_key("rotation", value=inst.rotation)
                self.set_key("root_x", value=inst.root_x)
                self.set_key("root_y", value=inst.root_y)

    def end_left_drag(self):
        self.mode = None
        self.drag_pose_instances = None
        self.drag_pose_selected_name = None

    def zoom_at(self, factor, screen_pos):
        old_world = self.screen_to_world(screen_pos)
        self.zoom = max(0.1, min(10.0, self.zoom * factor))
        self.offset[0] = screen_pos[0] - old_world[0] * self.zoom
        self.offset[1] = screen_pos[1] - old_world[1] * self.zoom

    # ---------- draw ----------
    def draw_left_panel(self):
        _, h = self.screen.get_size()
        pygame.draw.rect(self.screen, PANEL, (0, TOPBAR_H, LEFT_W, h - TOPBAR_H - STATUS_H))
        pygame.draw.line(self.screen, PANEL_2, (LEFT_W, TOPBAR_H), (LEFT_W, h - STATUS_H), 1)
        self.draw_text("Animations", (12, TOPBAR_H + 10), WHITE)
        y = TOPBAR_H + 34 - self.left_scroll
        for name in self.animation_order:
            row = pygame.Rect(10, y, LEFT_W - 20, 28)
            color = PANEL_3 if name == self.selected_animation else PANEL_2
            pygame.draw.rect(self.screen, color, row, border_radius=6)
            self.draw_text(name, (16, y + 5), WHITE if name == self.selected_animation else TEXT, small=True)
            y += 32

        y += 8
        self.draw_text("Parts", (12, y), WHITE, small=True)
        y += 22
        for name in self.instance_order:
            row = pygame.Rect(10, y, LEFT_W - 20, 24)
            color = PANEL_3 if name == self.selected_instance else PANEL_2
            pygame.draw.rect(self.screen, color, row, border_radius=6)
            self.draw_text(name, (16, y + 4), WHITE if name == self.selected_instance else TEXT, small=True)
            y += 28

        self.draw_text("A new anim | F2 rename anim", (12, h - STATUS_H - 58), MUTED, small=True)
        self.draw_text("Del anim | C clear part keys", (12, h - STATUS_H - 40), MUTED, small=True)
        self.draw_text("K key | Shift+K delete key", (12, h - STATUS_H - 22), MUTED, small=True)

    def draw_right_panel(self):
        w, h = self.screen.get_size()
        x0 = w - RIGHT_W
        pygame.draw.rect(self.screen, PANEL, (x0, TOPBAR_H, RIGHT_W, h - TOPBAR_H - STATUS_H))
        pygame.draw.line(self.screen, PANEL_2, (x0, TOPBAR_H), (x0, h - STATUS_H), 1)
        self.draw_text("Selection", (x0 + 12, TOPBAR_H + 10), WHITE)

        clip = self.selected_clip()
        inst = self.selected_inst()
        y = TOPBAR_H + 36 - self.right_scroll
        if clip:
            self.draw_text(f"anim: {clip.name}", (x0 + 12, y), TEXT, small=True)
            y += 18
            self.draw_text(f"length: {clip.length}  fps: {clip.fps}", (x0 + 12, y), TEXT, small=True)
            y += 18
            self.draw_text(f"frame: {self.current_frame:.2f}", (x0 + 12, y), TEXT, small=True)
            y += 24

        if inst:
            self.draw_text(f"part: {inst.name}", (x0 + 12, y), WHITE, small=True)
            y += 18
            self.draw_text(f"sprite: {inst.sprite_name}", (x0 + 12, y), TEXT, small=True)
            y += 24
            posed = self.posed_instances()
            pose_inst = posed.get(inst.name)
            for t in TRACK_ORDER:
                row = pygame.Rect(x0 + 10, y, RIGHT_W - 20, 24)
                active = t == self.selected_track
                pygame.draw.rect(self.screen, PANEL_3 if active else PANEL_2, row, border_radius=6)
                val = getattr(pose_inst, t) if pose_inst else 0.0
                c = TRACK_COLORS[t]
                pygame.draw.circle(self.screen, c, (x0 + 20, y + 12), 5)
                self.draw_text(TRACK_LABELS[t], (x0 + 32, y + 4), WHITE if active else TEXT, small=True)
                self.draw_text(f"{val:.2f}", (x0 + RIGHT_W - 88, y + 4), MUTED, small=True)
                y += 28

        self.draw_text("[, ] step frame", (x0 + 12, h - STATUS_H - 76), MUTED, small=True)
        self.draw_text("< > jump keyframe", (x0 + 12, h - STATUS_H - 58), MUTED, small=True)
        self.draw_text("L set length | P set fps", (x0 + 12, h - STATUS_H - 40), MUTED, small=True)
        self.draw_text("drag parts in viewport to pose", (x0 + 12, h - STATUS_H - 22), MUTED, small=True)

    def draw_canvas(self):
        canvas = self.canvas_rect()
        pygame.draw.rect(self.screen, (20, 22, 25), canvas)
        clip_prev = self.screen.get_clip()
        self.screen.set_clip(canvas)

        step = max(16, int(round(64 * self.zoom)))
        ox = int(self.offset[0]) % step
        oy = int(self.offset[1]) % step
        for x in range(canvas.left - step + ox, canvas.right + step, step):
            pygame.draw.line(self.screen, GRID, (x, canvas.top), (x, canvas.bottom))
        for y in range(canvas.top - step + oy, canvas.bottom + step, step):
            pygame.draw.line(self.screen, GRID, (canvas.left, y), (canvas.right, y))

        posed = self.posed_instances()

        for name in self.instance_order:
            inst = posed[name]
            if inst.parent and inst.parent in posed and inst.self_point and inst.parent_point:
                a = self.world_to_screen(solver.get_world_point(posed, self.sprites, name, inst.self_point))
                b = self.world_to_screen(solver.get_world_point(posed, self.sprites, inst.parent, inst.parent_point))
                pygame.draw.line(self.screen, CYAN, a, b, 2)

        for name in self.instance_order:
            inst = posed[name]
            sprite = solver.get_sprite(self.sprites, inst)
            surf = self.crops.get(inst.sprite_name)
            if not sprite or surf is None:
                continue
            tf = solver.get_world_transform(posed, self.sprites, name)
            angle = tf["rotation"]
            world_root = tf["root"]
            rot = pygame.transform.rotozoom(surf, -angle, self.zoom)
            corners = [
                solver.rotate_vec((0, 0), angle),
                solver.rotate_vec((sprite.width, 0), angle),
                solver.rotate_vec((sprite.width, sprite.height), angle),
                solver.rotate_vec((0, sprite.height), angle),
            ]
            minx = min(p[0] for p in corners)
            miny = min(p[1] for p in corners)
            screen_root = self.world_to_screen(world_root)
            blit = (round(screen_root[0] + minx * self.zoom), round(screen_root[1] + miny * self.zoom))
            self.screen.blit(rot, blit)
            poly = self.instance_screen_poly(posed, name)
            outline = YELLOW if name == self.selected_instance else GREEN
            pygame.draw.polygon(self.screen, outline, poly, 2)
            self.draw_text(name, (poly[0][0] + 2, poly[0][1] - 18), outline, small=True)
            for i, p in enumerate(sprite.attachment_points):
                sp = self.world_to_screen(solver.get_world_point(posed, self.sprites, name, p.name))
                c = POINT_COLORS[i % len(POINT_COLORS)]
                pygame.draw.circle(self.screen, c, (round(sp[0]), round(sp[1])), HANDLE_R)
                if name == self.selected_instance and p.name == self.selected_point_name:
                    pygame.draw.circle(self.screen, WHITE, (round(sp[0]), round(sp[1])), HANDLE_R + 3, 1)
                    self.draw_text(p.name, (sp[0] + 8, sp[1] - 18), WHITE, small=True)

        if self.selected_instance:
            handle = self.rotate_handle_screen(posed, self.selected_instance)
            if handle:
                sel = posed.get(self.selected_instance)
                sel_tf = solver.get_world_transform(posed, self.sprites, self.selected_instance)
                sel_sprite = solver.get_sprite(self.sprites, sel)
                pivot_name = sel.self_point if sel and sel.parent else self.selected_point_name
                if pivot_name:
                    pivot_world = solver.get_world_point(posed, self.sprites, self.selected_instance, pivot_name)
                elif sel_sprite:
                    center_local = solver.rotate_vec((sel_sprite.width / 2, sel_sprite.height / 2), sel_tf["rotation"])
                    pivot_world = (sel_tf["root"][0] + center_local[0], sel_tf["root"][1] + center_local[1])
                else:
                    pivot_world = sel_tf["root"]
                pivot = self.world_to_screen(pivot_world)
                pygame.draw.line(self.screen, MUTED, pivot, handle, 1)
                pygame.draw.circle(self.screen, ORANGE, (round(handle[0]), round(handle[1])), HANDLE_R)

        self.screen.set_clip(clip_prev)
        inst = self.selected_inst()
        clip = self.selected_clip()
        if inst and clip:
            tf = solver.get_world_transform(posed, self.sprites, inst.name)
            self.draw_text(
                f"{clip.name}  frame:{self.current_frame:.2f}/{clip.length - 1}  {inst.name} rot:{tf['rotation']:.1f}",
                (canvas.x + 12, canvas.y + 10),
                WHITE,
                small=True,
            )

    def draw_timeline(self):
        rect, frame_w, row_h, header_h, label_w = self.timeline_metrics()
        pygame.draw.rect(self.screen, PANEL, rect)

        clip = self.selected_clip()
        if not clip:
            pygame.draw.line(self.screen, PANEL_2, (rect.left, rect.top), (rect.right, rect.top), 1)
            pygame.draw.line(self.screen, PANEL_2, (rect.left, rect.top + header_h), (rect.right, rect.top + header_h),
                             1)
            pygame.draw.line(self.screen, PANEL_2, (rect.left + label_w, rect.top), (rect.left + label_w, rect.bottom),
                             1)
            return

        visible_frames = max(1, (rect.width - label_w) // frame_w + 2)
        start_frame = max(0, self.timeline_scroll_x // frame_w)
        end_frame = min(clip.length, start_frame + visible_frames)

        # ---------- scrolling track area ----------
        body_rect = pygame.Rect(rect.x, rect.y + header_h, rect.w, rect.h - header_h)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(body_rect)

        # move the sprite bars/tracks down by one visible entry so the header always has room
        y0 = rect.y + header_h + row_h - self.timeline_scroll_y

        row_index = 0
        for name in self.instance_order:
            for track_name in TRACK_ORDER:
                y = y0 + row_index * row_h
                row_rect = pygame.Rect(rect.x, y, rect.width, row_h)

                if row_rect.bottom < body_rect.top or row_rect.top > body_rect.bottom:
                    row_index += 1
                    continue

                pygame.draw.rect(self.screen, PANEL_2 if row_index % 2 == 0 else PANEL, row_rect)

                active = name == self.selected_instance and track_name == self.selected_track
                if active:
                    pygame.draw.rect(self.screen, PANEL_3, row_rect)

                pygame.draw.line(self.screen, GRID, (rect.x, y + row_h - 1), (rect.right, y + row_h - 1), 1)

                pygame.draw.circle(self.screen, TRACK_COLORS[track_name], (rect.x + 12, y + row_h // 2), 5)
                label = f"{name}.{TRACK_LABELS[track_name]}"
                self.draw_text(label, (rect.x + 22, y + 4), WHITE if active else TEXT, small=True)

                tr = self.track_dict(clip, name, track_name, create=False) or {}
                for fk, val in tr.items():
                    try:
                        frame = int(fk)
                    except Exception:
                        continue
                    if not (start_frame <= frame < end_frame):
                        continue
                    cx = rect.x + label_w + (frame * frame_w - self.timeline_scroll_x) + frame_w // 2
                    cy = y + row_h // 2
                    pygame.draw.circle(self.screen, TRACK_COLORS[track_name], (cx, cy), 5)
                    if frame == self.current_frame_index():
                        pygame.draw.circle(self.screen, WHITE, (cx, cy), 8, 1)

                row_index += 1

        self.screen.set_clip(old_clip)

        # ---------- non-scrolling header drawn last ----------
        pygame.draw.rect(self.screen, PANEL, (rect.x, rect.y, rect.w, header_h))
        pygame.draw.line(self.screen, PANEL_2, (rect.left, rect.top), (rect.right, rect.top), 1)
        pygame.draw.line(self.screen, PANEL_2, (rect.left, rect.top + header_h), (rect.right, rect.top + header_h), 1)
        pygame.draw.line(self.screen, PANEL_2, (rect.left + label_w, rect.top), (rect.left + label_w, rect.bottom), 1)

        for f in range(start_frame, end_frame):
            x = rect.x + label_w + (f * frame_w - self.timeline_scroll_x)
            if f % clip.fps == 0:
                pygame.draw.line(self.screen, PANEL_3, (x, rect.top), (x, rect.bottom), 1)
            else:
                pygame.draw.line(self.screen, GRID, (x, rect.top + header_h), (x, rect.bottom), 1)

            self.draw_text(
                str(f),
                (x + 2, rect.y + 6),
                WHITE if f == self.current_frame_index() else MUTED,
                small=True,
            )

        play_x = rect.x + label_w + (self.current_frame * frame_w - self.timeline_scroll_x)
        pygame.draw.line(self.screen, YELLOW, (play_x, rect.top), (play_x, rect.bottom), 2)

    def draw_top_bar(self):
        w, _ = self.screen.get_size()
        pygame.draw.rect(self.screen, PANEL, (0, 0, w, TOPBAR_H))
        pygame.draw.line(self.screen, PANEL_2, (0, TOPBAR_H - 1), (w, TOPBAR_H - 1), 1)
        self.draw_text("Mini PySpine Animation Editor", (12, 11), WHITE, big=True)
        self.draw_text(
            "Ctrl+L assembly | Ctrl+O animation | Ctrl+S save | Space play | K key | Shift+K delete key | drag parts to pose",
            (360, 16),
            MUTED,
            small=True,
        )

    def draw_status(self):
        w, h = self.screen.get_size()
        pygame.draw.rect(self.screen, PANEL, (0, h - STATUS_H, w, STATUS_H))
        self.draw_text(self.status, (8, h - 22), MUTED, small=True)

    def draw(self):
        self.screen.fill(BG)
        self.draw_canvas()
        self.draw_timeline()
        self.draw_left_panel()
        self.draw_right_panel()
        self.draw_top_bar()
        self.draw_status()
        pygame.display.flip()

    # ---------- playback ----------
    def update_playback(self, dt):
        clip = self.selected_clip()
        if not self.playing or not clip:
            return
        self.current_frame += clip.fps * dt
        if self.loop:
            while self.current_frame >= clip.length:
                self.current_frame -= clip.length
        else:
            if self.current_frame >= clip.length - 1:
                self.current_frame = float(clip.length - 1)
                self.playing = False

    def next_keyframe(self, direction=1):
        clip = self.selected_clip()
        inst = self.selected_inst()
        if not clip or not inst:
            return
        tr = self.track_dict(clip, inst.name, self.selected_track, create=False) or {}
        frames = sorted(int(k) for k in tr.keys())
        if not frames:
            return
        cur = self.current_frame_index()
        if direction > 0:
            for f in frames:
                if f > cur:
                    self.current_frame = float(f)
                    return
            self.current_frame = float(frames[0])
        else:
            for f in reversed(frames):
                if f < cur:
                    self.current_frame = float(f)
                    return
            self.current_frame = float(frames[-1])

    # ---------- events ----------
    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            shift = bool(mods & pygame.KMOD_SHIFT)
            if e.key == pygame.K_SPACE:
                if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                    self.space_down = True
                else:
                    self.playing = not self.playing
            elif ctrl and e.key == pygame.K_l:
                path = self.pick_open_path("Load assembly", [("JSON files", "*.json"), ("All files", "*.*")])
                if path:
                    self.load_assembly(path)
            elif ctrl and e.key == pygame.K_o:
                path = self.pick_open_path("Load animation", [("JSON files", "*.json"), ("All files", "*.*")])
                if path:
                    self.load_animation(path)
            elif ctrl and e.key == pygame.K_s:
                self.save_animation(self.pick_save_path("Save animation") if shift else None)
            elif e.key == pygame.K_a:
                self.new_animation(self.unique_animation_name())
            elif e.key == pygame.K_F2:
                self.rename_selected_animation()
            elif e.key == pygame.K_DELETE:
                self.delete_selected_animation()
            elif e.key == pygame.K_c:
                self.clear_selected_instance_keys()
            elif e.key == pygame.K_k and shift:
                self.delete_key()
            elif e.key == pygame.K_k:
                self.set_key()
            elif e.key == pygame.K_LEFTBRACKET:
                clip = self.selected_clip()
                if clip:
                    self.current_frame = max(0.0, self.current_frame - 1)
            elif e.key == pygame.K_RIGHTBRACKET:
                clip = self.selected_clip()
                if clip:
                    self.current_frame = min(float(clip.length - 1), self.current_frame + 1)
            elif e.key == pygame.K_COMMA:
                self.next_keyframe(-1)
            elif e.key == pygame.K_PERIOD:
                self.next_keyframe(1)
            elif e.key == pygame.K_l:
                clip = self.selected_clip()
                if clip:
                    val = self.prompt_int("Animation length", "Frame count:", clip.length)
                    if val and val > 0:
                        clip.length = int(val)
                        self.current_frame = min(self.current_frame, clip.length - 1)
                        self.dirty = True
            elif e.key == pygame.K_p:
                clip = self.selected_clip()
                if clip:
                    val = self.prompt_int("Animation fps", "FPS:", clip.fps)
                    if val and val > 0:
                        clip.fps = int(val)
                        self.dirty = True
            elif e.key == pygame.K_TAB:
                idx = TRACK_ORDER.index(self.selected_track) if self.selected_track in TRACK_ORDER else 0
                self.selected_track = TRACK_ORDER[(idx + 1) % len(TRACK_ORDER)]
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
            if mx < LEFT_W:
                left_content_h = len(self.animation_order) * 32 + len(self.instance_order) * 28 + 120
                left_max = max(0, left_content_h - (self.screen.get_height() - TOPBAR_H - STATUS_H))
                self.left_scroll = max(0, min(left_max, self.left_scroll - e.y * 24))
            elif mx > self.screen.get_width() - RIGHT_W:
                self.right_scroll = max(0, self.right_scroll - e.y * 24)
            elif self.timeline_rect().collidepoint((mx, my)):
                mods = pygame.key.get_mods()
                if mods & pygame.KMOD_SHIFT:
                    self.timeline_scroll_x = max(0, self.timeline_scroll_x - e.y * 24)
                else:
                    self.timeline_scroll_y = max(0, self.timeline_scroll_y - e.y * 24)
            else:
                self.zoom_at(1.1 if e.y > 0 else 1 / 1.1, (mx, my))

    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for e in pygame.event.get():
                self.handle_event(e)
            self.update_playback(dt)
            self.draw()
        if self._tk_root:
            self._tk_root.destroy()
        pygame.quit()
        import sys
        sys.exit(0)


if __name__ == "__main__":
    App().run()
