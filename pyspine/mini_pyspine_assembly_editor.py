import json
import math
import os
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

WINDOW_W = 1400
WINDOW_H = 900
LEFT_W = 260
RIGHT_W = 300
TOPBAR_H = 56
STATUS_H = 26
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
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
DEFAULT_PROJECT = "sprite_sheet_editor_v1.0_project.json"
DEFAULT_ASSEMBLY = "mini_pyspine_assembly.json"
HANDLE_R = 7
ROTATE_HANDLE_DIST = 42


class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Mini PySpine Assembly Editor")
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
        self.sheet_path = None
        self.sheet_image = None
        self.sprites = {}
        self.sprite_order = []
        self.instances = {}
        self.instance_order = []
        self.crops = {}
        self.thumb_cache = {}

        self.selected_sprite_def = None
        self.selected_instance = None
        self.selected_point_name = None
        self.left_scroll = 0
        self.right_scroll = 0

        self.zoom = 1.5
        self.offset = [LEFT_W + 120.0, TOPBAR_H + 80.0]
        self.space_down = False
        self.running = True
        self.status = "Ctrl+L load sprite project | Ctrl+O load assembly | N new instance | Shift+click point to attach"

        self.mode = None
        self.drag_start_screen = (0, 0)
        self.drag_start_world = (0.0, 0.0)
        self.drag_origin_root = (0.0, 0.0)
        self.drag_start_rotation = 0.0
        self.drag_rotate_anchor = (0.0, 0.0)
        self.drag_pivot_local_unrotated = (0.0, 0.0)

        if os.path.exists(DEFAULT_PROJECT):
            self.load_sprite_project(DEFAULT_PROJECT)
        if self.assembly_path and os.path.exists(self.assembly_path):
            self.load_assembly(self.assembly_path)

    # ---------- basic helpers ----------
    def canvas_rect(self):
        w, h = self.screen.get_size()
        return pygame.Rect(LEFT_W, TOPBAR_H, max(10, w - LEFT_W - RIGHT_W), max(10, h - TOPBAR_H - STATUS_H))

    def project_dir(self):
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

    def unique_instance_name(self, base):
        i = 1
        seed = base.replace(" ", "_") or "part"
        while f"{seed}_{i}" in self.instances:
            i += 1
        return f"{seed}_{i}"

    def selected_sprite(self):
        return self.sprites.get(self.selected_sprite_def)

    def selected_inst(self):
        return self.instances.get(self.selected_instance)

    def world_to_screen(self, pos):
        return pos[0] * self.zoom + self.offset[0], pos[1] * self.zoom + self.offset[1]

    def screen_to_world(self, pos):
        return (pos[0] - self.offset[0]) / self.zoom, (pos[1] - self.offset[1]) / self.zoom

    # ---------- file dialogs ----------
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
            self.selected_sprite_def = self.sprite_order[0] if self.sprite_order else None
            self.sprite_project_path = os.path.abspath(path)
            img_path = pdata.get("sprite_sheet_path", data.get("sprite_sheet_path", ""))
            img_abs = self.resolve_path(img_path)
            if img_abs and os.path.exists(img_abs):
                self.load_sheet(img_abs)
            self.status = f"Loaded sprite project: {os.path.basename(path)}"
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

    def save_assembly(self, path=None):
        if path:
            self.assembly_path = os.path.abspath(path)
        elif not self.assembly_path:
            path = self.pick_save_path("Save assembly")
            if not path:
                return False
            self.assembly_path = os.path.abspath(path)

        data = {
            "editor_type": "Mini PySpine Assembly v1",
            "sprite_project_path": self.compact_path_for_save(
                self.sprite_project_path) if self.sprite_project_path else "",
            "instances": [self.instances[name].to_dict() for name in self.instance_order if name in self.instances],
            "ui_state": {"zoom": self.zoom, "offset": self.offset},
        }
        try:
            with open(self.assembly_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.status = f"Saved assembly: {os.path.basename(self.assembly_path)}"
            return True
        except Exception as e:
            self.status = f"Save failed: {e}"
            return False

    # ---------- instance editing ----------
    def create_instance(self):
        sprite_name = self.selected_sprite_def
        if not sprite_name:
            self.status = "Load a sprite project first"
            return
        name = self.unique_instance_name(sprite_name)
        center = self.screen_to_world(self.canvas_rect().center)
        sprite = self.sprites[sprite_name]
        inst = model.Instance(name=name, sprite_name=sprite_name, root_x=center[0] - sprite.width / 2,
                              root_y=center[1] - sprite.height / 2)
        self.instances[name] = inst
        self.instance_order.append(name)
        self.selected_instance = name
        self.selected_point_name = sprite.attachment_points[0].name if sprite.attachment_points else None
        self.status = f"Created instance: {name}"

    def delete_selected_instance(self):
        name = self.selected_instance
        if not name or name not in self.instances:
            return
        # Detach children BEFORE removing parent so transform math still works
        for other in self.instances.values():
            if other.parent == name:
                solver.detach_instance(self.instances, self.sprites, other.name)
        self.instances.pop(name, None)
        if name in self.instance_order:
            self.instance_order.remove(name)
        self.selected_instance = self.instance_order[-1] if self.instance_order else None
        self.status = f"Deleted instance: {name}"

    def rename_selected_instance(self):
        inst = self.selected_inst()
        if not inst:
            return
        new_name = self.prompt_text("Rename instance", "New name:", inst.name)
        if not new_name or new_name == inst.name or new_name in self.instances:
            return
        old = inst.name
        self.instances.pop(old)
        inst.name = new_name
        self.instances[new_name] = inst
        self.instance_order[self.instance_order.index(old)] = new_name
        for other in self.instances.values():
            if other.parent == old:
                other.parent = new_name
        self.selected_instance = new_name
        self.status = f"Renamed instance to {new_name}"

    def move_instance_up(self):
        name = self.selected_instance
        if not name or name not in self.instance_order:
            return
        idx = self.instance_order.index(name)
        if idx < len(self.instance_order) - 1:
            self.instance_order[idx], self.instance_order[idx + 1] = (
                self.instance_order[idx + 1], self.instance_order[idx]
            )
            self.status = f"{name} moved up in draw order"

    def move_instance_down(self):
        name = self.selected_instance
        if not name or name not in self.instance_order:
            return
        idx = self.instance_order.index(name)
        if idx > 0:
            self.instance_order[idx], self.instance_order[idx - 1] = (
                self.instance_order[idx - 1], self.instance_order[idx]
            )
            self.status = f"{name} moved down in draw order"

    def reparent_selected_to_target(self, parent_name, parent_point_name):
        child = self.selected_inst()
        if not child or not parent_name or child.name == parent_name:
            return
        if solver.would_cycle(self.instances, child.name, parent_name):
            self.status = "Cannot create cycle"
            return
        child_sprite = solver.get_sprite(self.sprites, child)
        if not child_sprite or not child_sprite.attachment_points:
            self.status = "Selected instance has no attachment points"
            return
        self_point = self.selected_point_name or child_sprite.attachment_points[0].name
        child_tf = solver.get_world_transform(self.instances, self.sprites, child.name)
        parent_tf = solver.get_world_transform(self.instances, self.sprites, parent_name)
        child.parent = parent_name
        child.parent_point = parent_point_name
        child.self_point = self_point
        child.local_rotation = child_tf["rotation"] - parent_tf["rotation"]
        self.status = f"Attached {child.name}.{self_point} -> {parent_name}.{parent_point_name}"

    # ---------- hit testing ----------
    def point_hit(self, screen_pos):
        best = None
        best_d2 = (HANDLE_R + 6) ** 2
        for name in self.instance_order:
            inst = self.instances[name]
            sprite = solver.get_sprite(self.sprites, inst)
            if not sprite:
                continue
            for i, p in enumerate(sprite.attachment_points):
                wp = solver.get_world_point(self.instances, self.sprites, name, p.name)
                sp = self.world_to_screen(wp)
                d2 = (sp[0] - screen_pos[0]) ** 2 + (sp[1] - screen_pos[1]) ** 2
                if d2 <= best_d2:
                    best_d2 = d2
                    best = (name, p.name, i)
        return best

    def instance_hit(self, screen_pos):
        for name in reversed(self.instance_order):
            poly = self.instance_screen_poly(name)
            if poly and self.point_in_poly(screen_pos, poly):
                return name
        return None

    def duplicate_selected_instance(self):
        inst = self.selected_inst()
        if not inst:
            return
        import copy
        new_inst = copy.deepcopy(inst)
        new_inst.name = self.unique_instance_name(inst.sprite_name)
        # Place it slightly offset so it's visually distinct from the original
        new_inst.root_x += 10
        new_inst.root_y += 10
        # Detach from parent — duplicate starts as a free root instance
        new_inst.parent = None
        new_inst.parent_point = None
        new_inst.self_point = None
        new_inst.local_rotation = 0.0
        new_inst.rotation = inst.rotation  # preserve visual rotation
        self.instances[new_inst.name] = new_inst
        self.instance_order.append(new_inst.name)
        self.selected_instance = new_inst.name
        self.status = f"Duplicated {inst.name} -> {new_inst.name}"

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

    def instance_screen_poly(self, name):
        inst = self.instances.get(name)
        sprite = solver.get_sprite(self.sprites, inst) if inst else None
        if not inst or not sprite:
            return None
        tf = solver.get_world_transform(self.instances, self.sprites, name)
        corners = [(0, 0), (sprite.width, 0), (sprite.width, sprite.height), (0, sprite.height)]
        poly = []
        for c in corners:
            wc = solver.rotate_vec(c, tf["rotation"])
            world = (tf["root"][0] + wc[0], tf["root"][1] + wc[1])
            poly.append(self.world_to_screen(world))
        return poly

    def rotate_handle_screen(self, name):
        inst = self.instances.get(name)
        sprite = solver.get_sprite(self.sprites, inst) if inst else None
        if not inst or not sprite:
            return None
        tf = solver.get_world_transform(self.instances, self.sprites, name)
        pivot_name = inst.self_point if inst.parent else (self.selected_point_name or (
            sprite.attachment_points[0].name if sprite.attachment_points else None))

        if pivot_name:
            pivot = solver.get_world_point(self.instances, self.sprites, name, pivot_name)
        else:
            if sprite:
                center_local = solver.rotate_vec((sprite.width / 2, sprite.height / 2), tf["rotation"])
                pivot = (tf["root"][0] + center_local[0], tf["root"][1] + center_local[1])
            else:
                pivot = tf["root"]

        # atan2 returns 0 = right, 90 = down, so handle should sit to the right at 0 degrees
        local_up = solver.rotate_vec((ROTATE_HANDLE_DIST / self.zoom, 0), tf["rotation"])
        screen_pivot = self.world_to_screen(pivot)
        return screen_pivot[0] + local_up[0] * self.zoom, screen_pivot[1] + local_up[1] * self.zoom

    # ---------- input ----------
    def left_panel_click(self, pos):
        y = TOPBAR_H + 34 - self.left_scroll
        for name in self.sprite_order:
            row = pygame.Rect(10, y, LEFT_W - 20, 54)
            if row.collidepoint(pos):
                self.selected_sprite_def = name
                return True
            y += 60
        return False

    def right_panel_click(self, pos):
        x0 = self.screen.get_width() - RIGHT_W
        y = TOPBAR_H + 34 - self.right_scroll
        for name in self.instance_order:
            row = pygame.Rect(x0 + 10, y, RIGHT_W - 20, 42)
            if row.collidepoint(pos):
                self.selected_instance = name
                inst = self.instances[name]
                sprite = solver.get_sprite(self.sprites, inst)
                self.selected_point_name = sprite.attachment_points[
                    0].name if sprite and sprite.attachment_points else None
                return True
            y += 46

        # attachment point rows for selected instance
        inst = self.selected_inst()
        if inst:
            sprite = solver.get_sprite(self.sprites, inst)
            y += 12  # gap
            y += 22  # "Selected" label
            y += 18  # instance name
            y += 18  # sprite name
            y += 18  # world rot
            if sprite and sprite.attachment_points:
                y += 26  # "attach points" label
                for i, p in enumerate(sprite.attachment_points):
                    row = pygame.Rect(x0 + 12, y, RIGHT_W - 24, 22)
                    if row.collidepoint(pos):
                        self.selected_point_name = p.name
                        return True
                    y += 24
        return False

    def start_left_drag(self, pos):
        if pos[1] < TOPBAR_H:
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

        point_hit = self.point_hit(pos)
        mods = pygame.key.get_mods()
        shift = bool(mods & pygame.KMOD_SHIFT)

        if point_hit:
            name, point_name, _ = point_hit
            if shift and self.selected_instance and self.selected_instance != name:
                self.reparent_selected_to_target(name, point_name)
                return
            self.selected_instance = name
            self.selected_point_name = point_name

        inst_name = self.instance_hit(pos)
        if inst_name:
            self.selected_instance = inst_name
            inst = self.instances[inst_name]
            sprite = solver.get_sprite(self.sprites, inst)
            if point_hit and point_hit[0] == inst_name:
                self.selected_point_name = point_hit[1]

            tf = solver.get_world_transform(self.instances, self.sprites, inst_name)

            def set_rotate_pivot(pivot_world):
                self.drag_rotate_anchor = pivot_world
                self.drag_start_rotation = inst.local_rotation if inst.parent else inst.rotation
                self.drag_start_screen = pos
                world_offset = (pivot_world[0] - tf["root"][0], pivot_world[1] - tf["root"][1])
                self.drag_pivot_local_unrotated = solver.rotate_vec(world_offset, -tf["rotation"])

            def get_pivot_world():
                temp_pivot_name = inst.self_point if inst.parent else (
                        self.selected_point_name or (
                    sprite.attachment_points[0].name if sprite and sprite.attachment_points else None)
                )
                if temp_pivot_name:
                    return solver.get_world_point(self.instances, self.sprites, inst_name, temp_pivot_name)
                if sprite:
                    center_local = solver.rotate_vec((sprite.width / 2, sprite.height / 2), tf["rotation"])
                    return tf["root"][0] + center_local[0], tf["root"][1] + center_local[1]
                return tf["root"]

            handle = self.rotate_handle_screen(inst_name)
            if handle and (handle[0] - pos[0]) ** 2 + (handle[1] - pos[1]) ** 2 <= (HANDLE_R + 4) ** 2:
                self.mode = "rotate"
                set_rotate_pivot(get_pivot_world())
                return

            if inst.parent:
                self.mode = "rotate"
                pivot_name = inst.self_point or (
                    sprite.attachment_points[0].name if sprite and sprite.attachment_points else None)
                if pivot_name:
                    set_rotate_pivot(solver.get_world_point(self.instances, self.sprites, inst_name, pivot_name))
                else:
                    set_rotate_pivot(get_pivot_world())
            else:
                if mods & pygame.KMOD_ALT:
                    self.mode = "rotate"
                    set_rotate_pivot(get_pivot_world())
                else:
                    self.mode = "move"
                    self.drag_origin_root = (inst.root_x, inst.root_y)
                    self.drag_start_world = self.screen_to_world(pos)
            return

        self.selected_instance = None

    def update_left_drag(self, pos):
        if self.mode == "pan":
            dx = pos[0] - self.drag_start_screen[0]
            dy = pos[1] - self.drag_start_screen[1]
            self.offset[0] += dx
            self.offset[1] += dy
            self.drag_start_screen = pos
            return
        inst = self.selected_inst()
        if not inst:
            return
        if self.mode == "move" and not inst.parent:
            cur = self.screen_to_world(pos)
            dx = cur[0] - self.drag_start_world[0]
            dy = cur[1] - self.drag_start_world[1]
            inst.root_x = self.drag_origin_root[0] + dx
            inst.root_y = self.drag_origin_root[1] + dy
        elif self.mode == "rotate":
            pivot = self.drag_rotate_anchor
            mx, my = self.screen_to_world(pos)
            ang = math.degrees(math.atan2(my - pivot[1], mx - pivot[0]))
            base = solver.get_world_transform(self.instances, self.sprites, inst.parent)[
                "rotation"] if inst.parent and inst.parent in self.instances else 0.0
            if inst.parent:
                inst.local_rotation = ang - base
            else:
                inst.rotation = ang
                # Keep the pivot point fixed in world space by repositioning root.
                # Unrotate the stored local offset, rotate it to the new angle,
                # then solve: root = pivot - rotated_local_offset
                rotated = solver.rotate_vec(self.drag_pivot_local_unrotated, ang)
                inst.root_x = pivot[0] - rotated[0]
                inst.root_y = pivot[1] - rotated[1]

    def end_left_drag(self):
        self.mode = None

    def zoom_at(self, factor, screen_pos):
        old_world = self.screen_to_world(screen_pos)
        self.zoom = max(0.1, min(10.0, self.zoom * factor))
        self.offset[0] = screen_pos[0] - old_world[0] * self.zoom
        self.offset[1] = screen_pos[1] - old_world[1] * self.zoom

    # ---------- draw ----------
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

    def draw_left_panel(self):
        _, h = self.screen.get_size()
        pygame.draw.rect(self.screen, PANEL, (0, TOPBAR_H, LEFT_W, h - TOPBAR_H - STATUS_H))
        pygame.draw.line(self.screen, PANEL_2, (LEFT_W, TOPBAR_H), (LEFT_W, h - STATUS_H), 1)
        self.draw_text("Sprite defs", (12, TOPBAR_H + 10), WHITE)
        y = TOPBAR_H + 34 - self.left_scroll
        for name in self.sprite_order:
            row = pygame.Rect(10, y, LEFT_W - 20, 54)
            color = PANEL_3 if name == self.selected_sprite_def else PANEL_2
            pygame.draw.rect(self.screen, color, row, border_radius=8)
            thumb = self.get_thumb(name)
            if thumb:
                self.screen.blit(thumb, (16, y + 3))
            self.draw_text(name, (74, y + 8), WHITE if name == self.selected_sprite_def else TEXT, small=True)
            s = self.sprites[name]
            self.draw_text(f"{s.width}x{s.height}  pts:{len(s.attachment_points)}", (74, y + 28), MUTED, small=True)
            y += 60
        self.draw_text("N create instance", (12, h - STATUS_H - 40), MUTED, small=True)
        self.draw_text("Ctrl+L load sprite project", (12, h - STATUS_H - 22), MUTED, small=True)

    def draw_right_panel(self):
        w, h = self.screen.get_size()
        x0 = w - RIGHT_W
        pygame.draw.rect(self.screen, PANEL, (x0, TOPBAR_H, RIGHT_W, h - TOPBAR_H - STATUS_H))
        pygame.draw.line(self.screen, PANEL_2, (x0, TOPBAR_H), (x0, h - STATUS_H), 1)
        self.draw_text("Assembly", (x0 + 12, TOPBAR_H + 10), WHITE)
        y = TOPBAR_H + 34 - self.right_scroll
        for name in self.instance_order:
            inst = self.instances[name]
            row = pygame.Rect(x0 + 10, y, RIGHT_W - 20, 42)
            color = PANEL_3 if name == self.selected_instance else PANEL_2
            pygame.draw.rect(self.screen, color, row, border_radius=8)
            self.draw_text(name, (x0 + 18, y + 6), WHITE if name == self.selected_instance else TEXT, small=True)
            parent = inst.parent or "root"
            self.draw_text(f"{inst.sprite_name}  <-  {parent}", (x0 + 18, y + 24), MUTED, small=True)
            y += 46

        y += 12
        inst = self.selected_inst()
        if inst:
            sprite = solver.get_sprite(self.sprites, inst)
            self.draw_text("Selected", (x0 + 12, y), WHITE, small=True)
            y += 22
            self.draw_text(f"instance: {inst.name}", (x0 + 12, y), TEXT, small=True)
            y += 18
            self.draw_text(f"sprite: {inst.sprite_name}", (x0 + 12, y), TEXT, small=True)
            y += 18
            tf = solver.get_world_transform(self.instances, self.sprites, inst.name)
            self.draw_text(f"world rot: {tf['rotation']:.1f}", (x0 + 12, y), TEXT, small=True)
            y += 18
            if sprite and sprite.attachment_points:
                self.draw_text("attach points", (x0 + 12, y + 4), WHITE, small=True)
                y += 26
                for i, p in enumerate(sprite.attachment_points):
                    c = POINT_COLORS[i % len(POINT_COLORS)]
                    row = pygame.Rect(x0 + 12, y, RIGHT_W - 24, 22)
                    active = p.name == self.selected_point_name
                    pygame.draw.rect(self.screen, PANEL_3 if active else PANEL_2, row, border_radius=6)
                    pygame.draw.circle(self.screen, c, (x0 + 22, y + 11), 5)
                    self.draw_text(p.name, (x0 + 34, y + 4), WHITE if active else TEXT, small=True)
                    if inst.parent and p.name == inst.self_point:
                        self.draw_text("attached", (x0 + RIGHT_W - 72, y + 4), MUTED, small=True)
                    y += 24
        self.draw_text("Shift+click point: attach selected", (x0 + 12, h - STATUS_H - 58), MUTED, small=True)
        self.draw_text("U detach | Del delete | F2 rename", (x0 + 12, h - STATUS_H - 40), MUTED, small=True)
        self.draw_text("drag root to move | drag handle/body to rotate", (x0 + 12, h - STATUS_H - 22), MUTED,
                       small=True)

    def draw_canvas(self):
        canvas = self.canvas_rect()
        pygame.draw.rect(self.screen, (20, 22, 25), canvas)
        clip_prev = self.screen.get_clip()
        self.screen.set_clip(canvas)

        # grid
        step = max(16, int(round(64 * self.zoom)))
        ox = int(self.offset[0]) % step
        oy = int(self.offset[1]) % step
        for x in range(canvas.left - step + ox, canvas.right + step, step):
            pygame.draw.line(self.screen, GRID, (x, canvas.top), (x, canvas.bottom))
        for y in range(canvas.top - step + oy, canvas.bottom + step, step):
            pygame.draw.line(self.screen, GRID, (canvas.left, y), (canvas.right, y))

        # connection lines
        for name in self.instance_order:
            inst = self.instances[name]
            if inst.parent and inst.parent in self.instances and inst.self_point and inst.parent_point:
                a = self.world_to_screen(solver.get_world_point(self.instances, self.sprites, name, inst.self_point))
                b = self.world_to_screen(
                    solver.get_world_point(self.instances, self.sprites, inst.parent, inst.parent_point))
                pygame.draw.line(self.screen, CYAN, a, b, 2)

        # parts
        for name in self.instance_order:
            inst = self.instances[name]
            sprite = solver.get_sprite(self.sprites, inst)
            surf = self.crops.get(inst.sprite_name)
            if not sprite or surf is None:
                continue
            tf = solver.get_world_transform(self.instances, self.sprites, name)
            angle = tf["rotation"]
            world_root = tf["root"]
            rot = pygame.transform.rotozoom(surf, -angle, self.zoom)
            rot.set_alpha(180)  # 0=invisible, 255=fully opaque, 180 is a good balance
            corners = [solver.rotate_vec((0, 0), angle), solver.rotate_vec((sprite.width, 0), angle),
                       solver.rotate_vec((sprite.width, sprite.height), angle),
                       solver.rotate_vec((0, sprite.height), angle)]
            minx = min(p[0] for p in corners)
            miny = min(p[1] for p in corners)
            screen_root = self.world_to_screen(world_root)
            blit = (round(screen_root[0] + minx * self.zoom), round(screen_root[1] + miny * self.zoom))
            self.screen.blit(rot, blit)
            poly = self.instance_screen_poly(name)
            outline = YELLOW if name == self.selected_instance else GREEN
            pygame.draw.polygon(self.screen, outline, poly, 2)
            self.draw_text(name, (poly[0][0] + 2, poly[0][1] - 18), outline, small=True)
            for i, p in enumerate(sprite.attachment_points):
                sp = self.world_to_screen(solver.get_world_point(self.instances, self.sprites, name, p.name))
                c = POINT_COLORS[i % len(POINT_COLORS)]
                pygame.draw.circle(self.screen, c, (round(sp[0]), round(sp[1])), HANDLE_R)
                if name == self.selected_instance and p.name == self.selected_point_name:
                    pygame.draw.circle(self.screen, WHITE, (round(sp[0]), round(sp[1])), HANDLE_R + 3, 1)
                    self.draw_text(p.name, (sp[0] + 8, sp[1] - 18), WHITE, small=True)

        if self.selected_instance:
            handle = self.rotate_handle_screen(self.selected_instance)
            if handle:
                sel = self.selected_inst()
                pivot_name = sel.self_point if sel and sel.parent else self.selected_point_name

                sel_tf = solver.get_world_transform(self.instances, self.sprites, self.selected_instance)
                sel_sprite = solver.get_sprite(self.sprites, sel)
                if pivot_name:
                    pivot_world = solver.get_world_point(self.instances, self.sprites, self.selected_instance,
                                                         pivot_name)
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
        if inst:
            tf = solver.get_world_transform(self.instances, self.sprites, inst.name)
            info = f"{inst.name}  sprite:{inst.sprite_name}  rot:{tf['rotation']:.1f}"
            if inst.parent:
                info += f"  attached {inst.self_point} -> {inst.parent}.{inst.parent_point}"
            else:
                info += "  root"
            self.draw_text(info, (canvas.x + 12, canvas.y + 10), WHITE, small=True)

    def draw_top_bar(self):
        w, _ = self.screen.get_size()
        pygame.draw.rect(self.screen, PANEL, (0, 0, w, TOPBAR_H))
        pygame.draw.line(self.screen, PANEL_2, (0, TOPBAR_H - 1), (w, TOPBAR_H - 1), 1)
        self.draw_text("Mini PySpine Assembly Editor", (12, 11), WHITE, big=True)
        self.draw_text(
            "Ctrl+L sprite project | Ctrl+O assembly | Ctrl+S save | N new instance | Shift+click point to attach | U detach | PgUp/PgDn draw order",
            (320, 16),
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
        self.draw_left_panel()
        self.draw_right_panel()
        self.draw_top_bar()
        self.draw_status()
        pygame.display.flip()

    # ---------- events ----------
    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            shift = bool(mods & pygame.KMOD_SHIFT)
            if e.key == pygame.K_SPACE:
                self.space_down = True
            elif ctrl and e.key == pygame.K_l:
                path = self.pick_open_path("Load sprite project", [("JSON files", "*.json"), ("All files", "*.*")])
                if path:
                    self.load_sprite_project(path)
            elif ctrl and e.key == pygame.K_o:
                path = self.pick_open_path("Load assembly", [("JSON files", "*.json"), ("All files", "*.*")])
                if path:
                    self.load_assembly(path)
            elif ctrl and e.key == pygame.K_s:
                self.save_assembly(self.pick_save_path("Save assembly") if shift else None)
            elif ctrl and e.key == pygame.K_d:
                self.duplicate_selected_instance()
            elif e.key == pygame.K_n:
                self.create_instance()
            elif e.key == pygame.K_DELETE:
                self.delete_selected_instance()
            elif e.key == pygame.K_F2:
                self.rename_selected_instance()
            elif e.key == pygame.K_u:
                if self.selected_instance:
                    solver.detach_instance(self.instances, self.sprites, self.selected_instance)
                    self.status = f"Detached {self.selected_instance}"
            elif e.key == pygame.K_TAB:
                inst = self.selected_inst()
                sprite = solver.get_sprite(self.sprites, inst) if inst else None
                if sprite and sprite.attachment_points:
                    names = sprite.point_names()
                    cur = self.selected_point_name if self.selected_point_name in names else names[0]
                    self.selected_point_name = names[(names.index(cur) + 1) % len(names)]
            elif e.key == pygame.K_PAGEUP:
                self.move_instance_up()
            elif e.key == pygame.K_PAGEDOWN:
                self.move_instance_down()
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
                left_content_h = len(self.sprite_order) * 60 + 80
                left_max = max(0, left_content_h - (self.screen.get_height() - TOPBAR_H - STATUS_H))
                self.left_scroll = max(0, min(left_max, self.left_scroll - e.y * 24))

            elif mx > self.screen.get_width() - RIGHT_W:
                right_content_h = len(self.instance_order) * 46 + 200
                right_max = max(0, right_content_h - (self.screen.get_height() - TOPBAR_H - STATUS_H))
                self.right_scroll = max(0, min(right_max, self.right_scroll - e.y * 24))
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
        import sys
        sys.exit(0)


if __name__ == "__main__":
    App().run()
