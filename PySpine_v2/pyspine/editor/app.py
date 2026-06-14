from __future__ import annotations

from pathlib import Path

from pyspine.core.animation import sample_clip, solve_clip_pose
from pyspine.core.commands import RenameAttachmentPoint, RenameSprite, SetAttachmentPoint
from pyspine.core.geometry import Rect, Vec2, rotate
from pyspine.core.model import AttachmentPoint, Clip
from pyspine.core.solver import solve_pose, sprite_swap_problem
from pyspine.editor.state import EditorState, TextPrompt
from pyspine.editor.hierarchy import hierarchy_rows, matching_attachment_candidates, parent_candidates, validation_report
from pyspine.editor.timeline import find_nearest_key, timeline_rows
from pyspine.editor.tools import EditorTool, rotate_handle_position, scale_handle_position
from pyspine.io.jsonio import load_project, save_project


class EditorApp:
    def __init__(self, path: str | Path):
        import pygame  # type: ignore

        self.pygame = pygame
        self.path = Path(path)
        project = load_project(self.path)
        self.state = EditorState(project=project, path=self.path)
        self.state.current_clip = next(iter(project.clips), None)
        self.tool = EditorTool()
        self.screen = None
        self.clock = None
        self.font = None
        self.big_font = None
        self.sheet_surface = None
        self.sprite_cache: dict[str, object] = {}
        self.sidebar_rows: list[tuple[object, str, str]] = []

    def run(self) -> None:
        pygame = self.pygame
        pygame.init()
        self.screen = pygame.display.set_mode((1200, 800), pygame.RESIZABLE)
        pygame.display.set_caption("pyspine v13 Editor")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 15)
        self.big_font = pygame.font.SysFont("consolas", 20)
        self._load_sheet_surface()

        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            running = self._events()
            self._update(dt)
            self._draw()
        pygame.quit()

    def _load_sheet_surface(self) -> None:
        if not self.state.project.sheet.image:
            return
        image_path = Path(self.state.project.sheet.image)
        if not image_path.is_absolute():
            image_path = self.path.parent / image_path
        if image_path.exists():
            self.sheet_surface = self.pygame.image.load(str(image_path)).convert_alpha()
            self.sprite_cache.clear()
        else:
            self.state.message = f"sheet image missing: {image_path}"

    def _sprite_surface(self, sprite_name: str):
        if self.sheet_surface is None:
            return None
        if sprite_name in self.sprite_cache:
            return self.sprite_cache[sprite_name]
        pygame = self.pygame
        sprite = self.state.project.sheet.sprites[sprite_name]
        rect = pygame.Rect(int(sprite.rect.x), int(sprite.rect.y), int(sprite.rect.w), int(sprite.rect.h))
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        surface.blit(self.sheet_surface, (0, 0), rect)
        self.sprite_cache[sprite_name] = surface
        return surface

    def _events(self) -> bool:
        pygame = self.pygame
        assert self.screen is not None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if self.state.text_prompt is not None:
                if event.type == pygame.KEYDOWN:
                    self._prompt_key(event)
                continue
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                mods = pygame.key.get_mods()
                ctrl = bool(mods & pygame.KMOD_CTRL)
                shift = bool(mods & pygame.KMOD_SHIFT)
                if ctrl and event.key == pygame.K_s:
                    self._save()
                elif ctrl and event.key == pygame.K_z:
                    self.state.undo()
                    self.sprite_cache.clear()
                elif ctrl and event.key == pygame.K_y:
                    self.state.redo()
                    self.sprite_cache.clear()
                elif ctrl and event.key == pygame.K_c:
                    if shift and self.state.mode == "animation":
                        self.tool.copy_frame_keyframes(self.state, selected_only=False)
                    else:
                        self.tool.copy_pose(self.state, selected_only=not shift)
                elif ctrl and event.key == pygame.K_v:
                    if shift and self.state.mode == "animation":
                        self.tool.paste_frame_keyframes(self.state)
                    else:
                        self.tool.paste_pose(self.state)
                elif event.key == pygame.K_SPACE:
                    self.state.playing = not self.state.playing
                elif event.key == pygame.K_1:
                    self.state.mode = "sprite"
                    self.state.message = "Sprite Sheet Mode"
                elif event.key == pygame.K_2:
                    self.state.mode = "rig"
                    self.state.message = "Rig Mode"
                elif event.key == pygame.K_3:
                    self.state.mode = "animation"
                    self.state.message = "Animation Mode"
                elif event.key == pygame.K_F2:
                    self.tool.prompt_rename(self.state)
                elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE) and not ctrl:
                    if self.state.mode == "animation" and self.state.selected:
                        self.tool.delete_keyframe(self.state)
                    else:
                        self.tool.delete_selected(self.state)
                    self.sprite_cache.clear()
                elif event.key == pygame.K_a and self.state.mode == "sprite":
                    self.tool.add_point_at_mouse(self.state)
                elif event.key == pygame.K_i:
                    self.tool.add_instance(self.state, self.state.last_mouse_world)
                elif event.key == pygame.K_u and self.state.mode == "rig":
                    self.tool.reparent_selected_to_hover(self.state, None)
                elif event.key == pygame.K_p and self.state.mode == "rig":
                    parent = self._instance_under_mouse(exclude=self.state.selected)
                    if parent:
                        self.tool.reparent_selected_to_hover(self.state, parent)
                elif event.key == pygame.K_c and self.state.mode == "rig" and not ctrl:
                    self.tool.cycle_attachment_pair(self.state, -1 if shift else 1)
                elif event.key == pygame.K_k and self.state.mode == "animation":
                    if shift:
                        self.tool.set_pose_keyframes(self.state, selected_only=False)
                    else:
                        self.tool.set_keyframe(self.state)
                elif event.key == pygame.K_j and self.state.mode == "animation":
                    self.tool.set_pose_keyframes(self.state, selected_only=True)
                elif event.key == pygame.K_t and self.state.mode == "animation":
                    self.tool.toggle_interpolation(self.state)
                elif event.key == pygame.K_o and self.state.mode == "animation":
                    self.state.onion_skin = not self.state.onion_skin
                    self.state.message = "onion skin " + ("on" if self.state.onion_skin else "off")
                elif event.key == pygame.K_f and self.state.mode == "animation":
                    if shift:
                        self.tool.paste_frame_keyframes(self.state)
                    else:
                        self.tool.copy_frame_keyframes(self.state, selected_only=bool(ctrl and self.state.selected))
                elif event.key == pygame.K_m and self.state.mode == "animation":
                    self.tool.mirror_pose_keyframes(self.state)
                elif event.key == pygame.K_x and self.state.mode == "animation":
                    self.tool.reset_pose_keyframes(self.state, selected_only=shift)
                elif event.key == pygame.K_n and self.state.mode == "animation":
                    self.state.text_prompt = TextPrompt("save_pose", "pose", {})
                    self.state.message = "type pose name and press Enter"
                elif event.key in (pygame.K_LEFTBRACKET, pygame.K_COMMA):
                    self.tool.rotate_selected(self.state, -5.0 if not shift else -1.0)
                elif event.key in (pygame.K_RIGHTBRACKET, pygame.K_PERIOD):
                    self.tool.rotate_selected(self.state, 5.0 if not shift else 1.0)
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                    self.tool.adjust_z(self.state, 1)
                elif event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE):
                    self.tool.adjust_z(self.state, -1)
                elif event.key == pygame.K_LEFT:
                    self.state.frame = max(0.0, self.state.frame - (10.0 if shift else 1.0))
                elif event.key == pygame.K_RIGHT:
                    self.state.frame += 10.0 if shift else 1.0
                elif event.key == pygame.K_HOME:
                    self.state.frame = 0.0
                elif event.key == pygame.K_END and self.state.current_clip:
                    self.state.frame = self.state.project.clips[self.state.current_clip].length
                elif event.key == pygame.K_TAB:
                    self._cycle_selection(reverse=shift)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                pos = Vec2(*event.pos)
                world = self.state.viewport.screen_to_world(pos)
                self.state.last_mouse_world = world
                if event.button == 1:
                    hit = self._sidebar_hit(event.pos)
                    if hit:
                        kind, name = hit
                        if kind == "instance" and self.state.mode != "sprite":
                            self.state.sidebar_drag_instance = name
                            self.state.sidebar_hover_instance = None
                        self._sidebar_click_hit(kind, name)
                    elif self.state.mode == "animation" and self._timeline_contains(event.pos):
                        self._timeline_mouse_down(event.pos)
                    else:
                        self.tool.click(self.state, world, modifiers=pygame.key.get_mods())
                elif event.button == 2:
                    self.tool.add_instance(self.state, world)
                elif event.button == 3:
                    self._start_pan(event.pos)
                elif event.button == 4:
                    if self.state.mode == "animation" and self._timeline_contains(event.pos):
                        self.state.timeline_scroll = max(0, self.state.timeline_scroll - 1)
                    else:
                        self.state.viewport.zoom_at(pos, 1.1)
                elif event.button == 5:
                    if self.state.mode == "animation" and self._timeline_contains(event.pos):
                        self.state.timeline_scroll += 1
                    else:
                        self.state.viewport.zoom_at(pos, 1.0 / 1.1)
            elif event.type == pygame.MOUSEMOTION:
                pos = Vec2(*event.pos)
                world = self.state.viewport.screen_to_world(pos)
                self.state.last_mouse_world = world
                if event.buttons[0]:
                    if self.state.timeline_drag_key:
                        frame = self._timeline_frame_from_pos(event.pos)
                        self.state.frame = frame
                        inst, channel, old = self.state.timeline_drag_key
                        self.state.message = f"move key {inst}.{channel} {old:.0f} -> {frame:.0f}"
                    elif self.state.sidebar_drag_instance:
                        hit = self._sidebar_hit(event.pos)
                        self.state.sidebar_hover_instance = hit[1] if hit and hit[0] == "instance" else None
                    elif not (self.state.mode == "animation" and self._timeline_contains(event.pos)):
                        self.tool.drag_to(self.state, world)
                        if self.tool.drag and self.tool.drag.kind in {"point"}:
                            self.sprite_cache.clear()
                elif event.buttons[2]:
                    self.state.viewport.pan(event.rel[0], event.rel[1])
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    if self.state.timeline_drag_key:
                        self._timeline_mouse_up(event.pos)
                    elif self.state.sidebar_drag_instance:
                        self._sidebar_mouse_up(event.pos)
                    else:
                        self.tool.release(self.state)
                    self.sprite_cache.clear()
        return True

    def _prompt_key(self, event) -> None:
        pygame = self.pygame
        prompt = self.state.text_prompt
        assert prompt is not None
        if event.key == pygame.K_ESCAPE:
            self.state.text_prompt = None
            self.state.message = "cancelled"
            return
        if event.key == pygame.K_RETURN:
            self._commit_prompt()
            return
        if event.key == pygame.K_BACKSPACE:
            prompt.text = prompt.text[:-1]
            return
        if event.key == pygame.K_DELETE:
            prompt.text = ""
            return
        ch = getattr(event, "unicode", "")
        if ch and ch.isprintable() and ch not in "\\/:*?\"<>|":
            prompt.text += ch

    def _commit_prompt(self) -> None:
        prompt = self.state.text_prompt
        assert prompt is not None
        text = prompt.text.strip()
        self.state.text_prompt = None
        if not text:
            self.state.message = "empty name ignored"
            return
        if prompt.purpose == "rename_sprite":
            old = str(prompt.payload["old"])
            if text != old and self.state.run_command(RenameSprite(old, text)):
                self.state.selected_sprite = text
                self.sprite_cache.clear()
            return
        if prompt.purpose == "rename_point":
            old = str(prompt.payload["old"])
            sprite = str(prompt.payload["sprite"])
            if text != old and self.state.run_command(RenameAttachmentPoint(sprite, old, text)):
                self.state.selected_point = text
            return
        if prompt.purpose == "add_point":
            sprite = str(prompt.payload["sprite"])
            x = float(prompt.payload["x"])
            y = float(prompt.payload["y"])
            point = AttachmentPoint(text, x, y)
            if self.state.run_command(SetAttachmentPoint(sprite, text, None, point)):
                self.state.selected_sprite = sprite
                self.state.selected_point = text
            return
        if prompt.purpose == "save_pose":
            self.tool.save_named_pose(self.state, text)
            return

    def _start_pan(self, _pos) -> None:
        pass

    def _save(self) -> None:
        save_project(self.state.project, self.path)
        self.state.dirty = False
        self.state.message = f"saved {self.path.name}"

    def _update(self, dt: float) -> None:
        if self.state.playing and self.state.current_clip:
            clip = self.state.project.clips[self.state.current_clip]
            self.state.frame = (self.state.frame + dt * clip.fps) % clip.length

    def _current_pose(self):
        if self.state.current_clip:
            ov = sample_clip(self.state.project, self.state.current_clip, self.state.frame)
            return solve_pose(self.state.project, ov)
        return solve_pose(self.state.project)

    def _instance_under_mouse(self, exclude: str | None = None) -> str | None:
        from pyspine.editor.tools import pick_instance

        poses = self._current_pose()
        return pick_instance(self.state, poses, self.state.last_mouse_world, exclude=exclude)

    def _cycle_selection(self, *, reverse: bool = False) -> None:
        if self.state.mode == "sprite":
            names = sorted(self.state.project.sheet.sprites)
            cur = self.state.selected_sprite
            attr = "selected_sprite"
        else:
            names = sorted(self.state.project.rig.instances)
            cur = self.state.selected
            attr = "selected"
        if not names:
            return
        if cur not in names:
            setattr(self.state, attr, names[-1] if reverse else names[0])
        else:
            idx = names.index(cur) + (-1 if reverse else 1)
            setattr(self.state, attr, names[idx % len(names)])

    def _timeline_rect(self):
        pygame = self.pygame
        assert self.screen is not None
        w, h = self.screen.get_size()
        return pygame.Rect(0, h - self.state.timeline_height, w - 390, self.state.timeline_height)

    def _timeline_contains(self, pos) -> bool:
        return self._timeline_rect().collidepoint(pos)

    def _timeline_click(self, pos) -> None:
        if not self.state.current_clip:
            self.state.message = "no clip yet; press K to create anim"
            return
        rect = self._timeline_rect()
        clip = self.state.project.clips[self.state.current_clip]
        left = rect.x + 82
        right = rect.right - 18
        if right <= left:
            return
        t = max(0.0, min(1.0, (pos[0] - left) / (right - left)))
        self.state.frame = round(t * clip.length)
        self.state.message = f"frame {self.state.frame:.0f}"

    def _sidebar_click(self, pos) -> bool:
        for rect, kind, name in self.sidebar_rows:
            if rect.collidepoint(pos):
                if kind == "sprite":
                    self.state.selected_sprite = name
                    self.state.selected_point = None
                    self.state.mode = "sprite"
                    self.state.message = f"selected sprite {name}"
                    return True
                if kind == "instance":
                    self.state.selected = name
                    self.state.mode = "animation" if self.state.mode == "animation" else "rig"
                    self.state.message = f"selected instance {name}"
                    return True
                if kind == "attach_pair":
                    parent_point, self_point = name.split("|", 1)
                    self.tool.set_attachment_pair(self.state, parent_point, self_point)
                    return True
                if kind == "parent_candidate":
                    parent, parent_point, self_point = name.split("|", 2)
                    self.tool.reparent_selected_to_hover(self.state, parent)
                    # reparent_selected_to_hover picks the best common point; force the clicked pair if needed.
                    inst_name = self.state.selected
                    if inst_name and inst_name in self.state.project.rig.instances:
                        inst = self.state.project.rig.instances[inst_name]
                        if inst.parent == parent and (inst.parent_point, inst.self_point) != (parent_point, self_point):
                            self.tool.set_attachment_pair(self.state, parent_point, self_point)
                    return True
        return False

    def _draw(self) -> None:
        pygame = self.pygame
        assert self.screen is not None and self.font is not None
        self.screen.fill((31, 31, 34))
        self._draw_grid()
        if self.state.mode == "sprite":
            self._draw_sprite_sheet_mode()
        else:
            self._draw_rig_mode()
        if self.state.mode == "animation":
            self._draw_timeline()
        self._draw_sidebar()
        self._draw_prompt()
        pygame.display.flip()

    def _draw_grid(self) -> None:
        pygame = self.pygame
        assert self.screen is not None
        w, h = self.screen.get_size()
        step = max(8, int(50 * self.state.viewport.zoom))
        ox = int(self.state.viewport.offset.x) % step
        oy = int(self.state.viewport.offset.y) % step
        for x in range(ox, w, step):
            pygame.draw.line(self.screen, (42, 42, 46), (x, 0), (x, h))
        for y in range(oy, h, step):
            pygame.draw.line(self.screen, (42, 42, 46), (0, y), (w, y))

    def _draw_sprite_sheet_mode(self) -> None:
        pygame = self.pygame
        assert self.screen is not None
        if self.sheet_surface is not None:
            w, h = self.sheet_surface.get_size()
            size = (max(1, int(w * self.state.viewport.zoom)), max(1, int(h * self.state.viewport.zoom)))
            scaled = pygame.transform.scale(self.sheet_surface, size)
            self.screen.blit(scaled, self.state.viewport.world_to_screen(Vec2(0, 0)).as_tuple())
        for sprite in sorted(self.state.project.sheet.sprites.values(), key=lambda s: s.name):
            self._draw_sprite_rect(sprite.name)
        if self.state.pending_rect is not None:
            self._draw_rect_outline(self.state.pending_rect, (255, 255, 255), width=2)

    def _draw_sprite_rect(self, sprite_name: str) -> None:
        pygame = self.pygame
        assert self.screen is not None and self.font is not None
        sprite = self.state.project.sheet.sprites[sprite_name]
        selected = sprite_name == self.state.selected_sprite
        color = (255, 220, 80) if selected else (110, 190, 255)
        self._draw_rect_outline(sprite.rect, color, width=2 if selected else 1)
        label_pos = self.state.viewport.world_to_screen(Vec2(sprite.rect.x, sprite.rect.y - 16))
        surf = self.font.render(sprite.name, True, color)
        self.screen.blit(surf, (label_pos.x, label_pos.y))
        for name, point in sprite.points.items():
            p = Vec2(sprite.rect.x + point.x * sprite.rect.w, sprite.rect.y + point.y * sprite.rect.h)
            s = self.state.viewport.world_to_screen(p)
            point_color = (255, 90, 90) if selected and name == self.state.selected_point else (235, 235, 235)
            radius = 6 if selected and name == self.state.selected_point else 4
            pygame.draw.circle(self.screen, (15, 15, 18), (int(s.x), int(s.y)), radius + 2)
            pygame.draw.circle(self.screen, point_color, (int(s.x), int(s.y)), radius)
            if selected:
                t = self.font.render(name, True, point_color)
                self.screen.blit(t, (s.x + 8, s.y - 7))

    def _draw_rect_outline(self, rect: Rect, color: tuple[int, int, int], *, width: int = 1) -> None:
        pygame = self.pygame
        assert self.screen is not None
        p = self.state.viewport.world_to_screen(Vec2(rect.x, rect.y))
        r = pygame.Rect(int(p.x), int(p.y), int(rect.w * self.state.viewport.zoom), int(rect.h * self.state.viewport.zoom))
        pygame.draw.rect(self.screen, color, r, width)

    def _draw_rig_mode(self) -> None:
        if self.state.mode == "animation" and self.state.onion_skin and self.state.current_clip:
            clip = self.state.project.clips[self.state.current_clip]
            prev_frame = max(0.0, self.state.frame - max(1.0, clip.fps / 6.0))
            next_frame = min(clip.length, self.state.frame + max(1.0, clip.fps / 6.0))
            self._draw_rig(solve_clip_pose(self.state.project, clip, prev_frame), ghost=True)
            self._draw_rig(solve_clip_pose(self.state.project, clip, next_frame), ghost=True)
        poses = self._current_pose()
        self._draw_rig(poses)
        self._draw_rig_handles(poses)
        self._draw_snap_preview(poses)

    def _draw_rig(self, poses, *, ghost: bool = False) -> None:
        pygame = self.pygame
        assert self.screen is not None
        for pose in sorted(poses.values(), key=lambda p: (p.z, p.instance)):
            if not pose.visible:
                continue
            sprite = self.state.project.sheet.sprites[pose.sprite]
            surface = self._sprite_surface(pose.sprite)
            corners_world = [pose.local_to_world(c) for c in sprite.rect.corners()]
            corners = [self.state.viewport.world_to_screen(p) for p in corners_world]

            if surface is not None and not ghost:
                scale_for_surface = self.state.viewport.zoom * max(0.001, (abs(pose.scale_x) + abs(pose.scale_y)) / 2.0)
                # Non-uniform scale is handled geometrically for hit-testing; display uses average scale for now.
                scaled = pygame.transform.rotozoom(surface, -pose.rotation, scale_for_surface)
                center_world = Vec2(sum((p.x for p in corners_world), 0.0) / 4.0, sum((p.y for p in corners_world), 0.0) / 4.0)
                center = self.state.viewport.world_to_screen(center_world)
                rect = scaled.get_rect(center=(int(center.x), int(center.y)))
                self.screen.blit(scaled, rect)
            elif not ghost:
                color = (120, 160, 210) if pose.instance == self.state.selected else (95, 105, 120)
                pygame.draw.polygon(self.screen, color, [c.as_tuple() for c in corners], width=0)

            if ghost:
                outline = (80, 120, 190)
                pygame.draw.polygon(self.screen, outline, [c.as_tuple() for c in corners], width=1)
                continue

            outline = (255, 220, 80) if pose.instance == self.state.selected else (15, 15, 18)
            pygame.draw.polygon(self.screen, outline, [c.as_tuple() for c in corners], width=2 if pose.instance == self.state.selected else 1)
            anchor = self.state.viewport.world_to_screen(pose.anchor)
            pygame.draw.circle(self.screen, (255, 220, 80), (int(anchor.x), int(anchor.y)), 4)
            for point_name, point in pose.points.items():
                s = self.state.viewport.world_to_screen(point)
                color = (255, 90, 90) if point_name == "origin" else (235, 235, 235)
                pygame.draw.circle(self.screen, color, (int(s.x), int(s.y)), 2)
            inst = self.state.project.rig.instances[pose.instance]
            if inst.parent:
                parent_pose = poses.get(inst.parent)
                if parent_pose and inst.parent_point:
                    p0 = self.state.viewport.world_to_screen(parent_pose.point(inst.parent_point))
                    p1 = self.state.viewport.world_to_screen(pose.anchor)
                    pygame.draw.line(self.screen, (100, 100, 120), p0.as_tuple(), p1.as_tuple(), 1)

    def _draw_rig_handles(self, poses) -> None:
        if not self.state.selected or self.state.selected not in poses:
            return
        pygame = self.pygame
        assert self.screen is not None and self.font is not None
        pose = poses[self.state.selected]
        handle = rotate_handle_position(self.state, poses, self.state.selected)
        if handle is None:
            return
        anchor = self.state.viewport.world_to_screen(pose.anchor)
        h = self.state.viewport.world_to_screen(handle)
        pygame.draw.line(self.screen, (255, 220, 80), anchor.as_tuple(), h.as_tuple(), 1)
        pygame.draw.circle(self.screen, (15, 15, 18), (int(h.x), int(h.y)), 10)
        pygame.draw.circle(self.screen, (255, 220, 80), (int(h.x), int(h.y)), 7, 2)
        self.screen.blit(self.font.render("rotate", True, (255, 220, 80)), (h.x + 10, h.y - 8))
        sh = scale_handle_position(self.state, poses, self.state.selected)
        if sh is not None:
            ss = self.state.viewport.world_to_screen(sh)
            pygame.draw.line(self.screen, (130, 190, 255), anchor.as_tuple(), ss.as_tuple(), 1)
            pygame.draw.rect(self.screen, (15, 15, 18), (int(ss.x) - 8, int(ss.y) - 8, 16, 16))
            pygame.draw.rect(self.screen, (130, 190, 255), (int(ss.x) - 6, int(ss.y) - 6, 12, 12), 2)
            self.screen.blit(self.font.render("scale", True, (130, 190, 255)), (ss.x + 10, ss.y - 8))

    def _draw_snap_preview(self, poses) -> None:
        if not self.state.selected or not self.state.hover_snap_parent or not self.state.hover_snap_point:
            return
        if self.state.selected not in poses or self.state.hover_snap_parent not in poses:
            return
        pygame = self.pygame
        assert self.screen is not None and self.font is not None
        point = self.state.hover_snap_point
        child_pose = poses[self.state.selected]
        parent_pose = poses[self.state.hover_snap_parent]
        if point not in child_pose.points or point not in parent_pose.points:
            return
        a = self.state.viewport.world_to_screen(child_pose.point(point))
        b = self.state.viewport.world_to_screen(parent_pose.point(point))
        pygame.draw.line(self.screen, (130, 255, 170), a.as_tuple(), b.as_tuple(), 2)
        pygame.draw.circle(self.screen, (130, 255, 170), (int(a.x), int(a.y)), 6, 2)
        pygame.draw.circle(self.screen, (130, 255, 170), (int(b.x), int(b.y)), 6, 2)
        label = f"snap {point} -> {self.state.hover_snap_parent}.{point}"
        self.screen.blit(self.font.render(label, True, (130, 255, 170)), (b.x + 8, b.y - 8))

    def _draw_timeline(self) -> None:
        pygame = self.pygame
        assert self.screen is not None and self.font is not None
        rect = self._timeline_rect()
        pygame.draw.rect(self.screen, (18, 18, 22), rect)
        pygame.draw.rect(self.screen, (70, 70, 80), rect, 1)
        x = rect.x + 10
        y = rect.y + 8
        dim = (175, 175, 180)
        bright = (235, 235, 235)
        yellow = (255, 220, 80)
        blue = (130, 190, 255)
        if not self.state.current_clip or self.state.current_clip not in self.state.project.clips:
            self.screen.blit(self.font.render("Timeline: press K to create anim clip", True, dim), (x, y))
            return
        clip = self.state.project.clips[self.state.current_clip]
        left = rect.x + 82
        right = rect.right - 18
        top = rect.y + 28
        bottom = rect.bottom - 18
        self.screen.blit(self.font.render(f"{clip.name}  frame {self.state.frame:.0f}/{clip.length:.0f}", True, yellow), (x, y))
        # tick marks
        span = max(1.0, clip.length)
        tick = max(1, int(round(clip.fps / 2)))
        for f in range(0, int(clip.length) + 1, tick):
            px = left + int((f / span) * (right - left))
            pygame.draw.line(self.screen, (65, 65, 72), (px, top), (px, bottom))
            if f % max(1, int(clip.fps)) == 0:
                self.screen.blit(self.font.render(str(f), True, dim), (px + 2, rect.y + 8))
        # playhead
        play_x = left + int((max(0.0, min(clip.length, self.state.frame)) / span) * (right - left))
        pygame.draw.line(self.screen, (255, 220, 80), (play_x, top - 4), (play_x, bottom + 4), 2)
        # tracks
        row_h = 17
        row = 0
        for inst_name in sorted(self.state.project.rig.instances):
            yy = top + row * row_h
            if yy > bottom - row_h:
                break
            color = yellow if inst_name == self.state.selected else bright
            self.screen.blit(self.font.render(inst_name[:10], True, color), (rect.x + 8, yy - 2))
            pygame.draw.line(self.screen, (45, 45, 50), (left, yy + 7), (right, yy + 7))
            track = clip.tracks.get(inst_name)
            if track:
                for channel, keys in track.channels.items():
                    mode = track.interpolation.get(channel, "linear")
                    marker_color = blue if mode == "linear" else (255, 160, 80)
                    for frame in keys:
                        px = left + int((float(frame) / span) * (right - left))
                        pygame.draw.rect(self.screen, marker_color, (px - 3, yy + 3, 6, 8))
            row += 1

    def _draw_sidebar(self) -> None:
        pygame = self.pygame
        assert self.screen is not None and self.font is not None
        w, h = self.screen.get_size()
        panel_x = w - 390
        pygame.draw.rect(self.screen, (24, 24, 28), (panel_x, 0, 390, h))
        x = panel_x + 12
        y = 10
        lines = self._sidebar_lines()
        self.sidebar_rows.clear()
        for item in lines:
            if len(item) == 2:
                line, color = item
                kind = name = None
            else:
                line, color, kind, name = item
            surf = self.font.render(line[:62], True, color)
            self.screen.blit(surf, (x, y))
            if kind and name:
                self.sidebar_rows.append((pygame.Rect(panel_x, y - 1, 390, 19), kind, name))
            y += 19

    def _sidebar_lines(self) -> list[tuple]:
        s = self.state
        bright = (235, 235, 235)
        dim = (175, 175, 180)
        yellow = (255, 220, 80)
        blue = (130, 190, 255)
        red = (255, 130, 130)
        green = (130, 255, 170)
        orange = (255, 170, 90)
        lines: list[tuple] = [
            (f"pyspine v13 [{s.mode}] {'*' if s.dirty else ''}", yellow),
            ("Ctrl+S save | Ctrl+Z/Y undo/redo", dim),
            ("RMB pan | wheel zoom | Tab cycle", dim),
            ("1 sprite | 2 rig | 3 animation", dim),
        ]
        if s.mode == "sprite":
            lines += [
                ("", dim),
                ("Sprite Sheet Mode", blue),
                ("drag empty: create slice", dim),
                ("click/drag point: move pivot/attachment", dim),
                ("A add point | F2 rename selected point", dim),
                ("Del delete point/sprite", dim),
                (f"selected sprite: {s.selected_sprite or '-'}", bright),
                (f"selected point:  {s.selected_point or '-'}", bright),
                ("", dim),
                ("Sprites:", blue),
            ]
            for name in sorted(s.project.sheet.sprites):
                prefix = "> " if name == s.selected_sprite else "  "
                lines.append((prefix + name, yellow if name == s.selected_sprite else bright, "sprite", name))
        elif s.mode == "animation":
            lines += [
                ("", dim),
                ("Animation Mode", blue),
                ("click timeline to seek | Space play", dim),
                ("K key selected rot | Shift+K key full pose", dim),
                ("J key selected pose | Del delete selected key", dim),
                ("Ctrl+C/V pose | Ctrl+Shift+C/V frame", dim),
                ("F copy frame | Shift+F paste frame", dim),
                ("M mirror | X reset | N save named pose", dim),
                ("T linear/step | Shift+T easing | O onion", dim),
                (f"clip={s.current_clip or '-'} frame={s.frame:.1f} {'PLAY' if s.playing else ''}", bright),
                (f"selected: {s.selected or '-'}", bright),
                (f"onion: {'on' if s.onion_skin else 'off'}  Alt+arrows adjust", bright),
                ("", dim),
                ("Hierarchy:", blue),
            ]
            lines.extend(self._hierarchy_sidebar_rows(bright, yellow, dim))
            lines.extend(self._named_pose_sidebar_rows(bright, yellow, blue, dim, green))
        else:
            lines += [
                ("", dim),
                ("Rig Mode", blue),
                ("I add selected sprite; auto-attaches by matching point", dim),
                ("drag root: move/snap | rotate handle or []", dim),
                ("+/- z | P parent | U unparent | C cycle attach", dim),
                ("click hierarchy/inspector rows to edit", dim),
                (f"selected: {s.selected or '-'}", bright),
                ("", dim),
                ("Hierarchy:", blue),
            ]
            lines.extend(self._hierarchy_sidebar_rows(bright, yellow, dim))
            lines.extend(self._inspector_sidebar_rows(bright, yellow, blue, dim, green))
        lines.extend(self._validation_sidebar_rows(bright, blue, red, orange, dim))
        lines += [("", dim), (s.message, red if "failed" in s.message else dim)]
        return lines

    def _hierarchy_sidebar_rows(self, bright, yellow, dim) -> list[tuple]:
        rows: list[tuple] = []
        for row in hierarchy_rows(self.state.project):
            inst = self.state.project.rig.instances[row.instance]
            selected = row.instance == self.state.selected
            marker = ">" if selected else " "
            branch = "  " * row.depth + ("└ " if row.depth else "")
            parent_info = "root" if inst.parent is None else f"{inst.self_point}->{inst.parent_point}"
            line = f"{marker} {branch}{inst.name} [{inst.sprite}] z={inst.z} {parent_info}"
            rows.append((line, yellow if selected else bright, "instance", inst.name))
        if not rows:
            rows.append(("  <empty rig>", dim))
        return rows

    def _inspector_sidebar_rows(self, bright, yellow, blue, dim, green) -> list[tuple]:
        s = self.state
        rows: list[tuple] = [("", dim), ("Inspector:", blue)]
        if not s.selected or s.selected not in s.project.rig.instances:
            rows.append(("  select an instance", dim))
            return rows
        inst = s.project.rig.instances[s.selected]
        rows += [
            (f"  instance: {inst.name}", bright),
            (f"  sprite:   {inst.sprite}", bright),
            (f"  parent:   {inst.parent or 'root'}", bright),
            (f"  attach:   {inst.self_point} -> {inst.parent_point or '-'}", bright),
            (f"  root x/y:  {inst.x:.1f}, {inst.y:.1f}", bright if inst.parent is None else dim),
            (f"  rot:      {inst.rotation:.1f} / local {inst.local_rotation:.1f}", bright),
            (f"  z:        {inst.z}", bright),
        ]
        if inst.parent:
            pairs = matching_attachment_candidates(s.project, inst.name, inst.parent)
            rows += [("", dim), ("Attachment pairs:", blue)]
            if not pairs:
                rows.append(("  no matching named points", dim))
            for cand in pairs:
                active = cand.parent_point == inst.parent_point and cand.self_point == inst.self_point
                prefix = "> " if active else "  "
                payload = f"{cand.parent_point}|{cand.self_point}"
                rows.append((prefix + cand.label, yellow if active else green, "attach_pair", payload))
        rows += [("", dim), ("Compatible parents:", blue)]
        shown = 0
        for parent_name, pairs in parent_candidates(s.project, inst.name):
            if parent_name == inst.parent:
                continue
            first = pairs[0]
            payload = f"{parent_name}|{first.parent_point}|{first.self_point}"
            rows.append((f"  {parent_name}: {first.label}", green, "parent_candidate", payload))
            shown += 1
            if shown >= 6:
                rows.append(("  ...", dim))
                break
        if shown == 0:
            rows.append(("  none", dim))
        return rows

    def _validation_sidebar_rows(self, bright, blue, red, orange, dim) -> list[tuple]:
        errors, warnings, info = validation_report(self.state.project)
        rows: list[tuple] = [("", dim), ("Validation:", blue)]
        if not errors and not warnings:
            rows.append(("  OK", bright))
        for err in errors[:5]:
            rows.append(("  ERR " + err, red))
        if len(errors) > 5:
            rows.append((f"  ... {len(errors) - 5} more errors", red))
        for warn in warnings[:4]:
            rows.append(("  WARN " + warn, orange))
        if len(warnings) > 4:
            rows.append((f"  ... {len(warnings) - 4} more warnings", orange))
        for item in info[:3]:
            rows.append(("  " + item, dim))
        return rows

    def _draw_prompt(self) -> None:
        if self.state.text_prompt is None:
            return
        pygame = self.pygame
        assert self.screen is not None and self.font is not None and self.big_font is not None
        w, h = self.screen.get_size()
        box = pygame.Rect(120, h // 2 - 45, w - 240, 90)
        pygame.draw.rect(self.screen, (10, 10, 14), box)
        pygame.draw.rect(self.screen, (255, 220, 80), box, 2)
        prompt = self.state.text_prompt
        title = {
            "rename_sprite": "Rename sprite",
            "rename_point": "Rename attachment point",
            "add_point": "Add attachment point",
            "save_pose": "Save named pose",
        }.get(prompt.purpose, prompt.purpose)
        surf = self.big_font.render(title, True, (255, 220, 80))
        self.screen.blit(surf, (box.x + 14, box.y + 12))
        text = prompt.text + "_"
        body = self.big_font.render(text, True, (235, 235, 235))
        self.screen.blit(body, (box.x + 14, box.y + 46))


def run_editor(path: str | Path) -> None:
    EditorApp(path).run()


# ---------------------------------------------------------------------------
# v8 editor-method extensions.  Kept outside the original class body so the
# rewrite remains easy to review as a patch from v7.
# ---------------------------------------------------------------------------
def _v8_timeline_metrics(self):
    rect = self._timeline_rect()
    left = rect.x + 150
    right = rect.right - 18
    top = rect.y + 30
    row_h = 18
    return rect, left, right, top, row_h


def _v8_timeline_frame_from_pos(self, pos) -> float:
    if not self.state.current_clip or self.state.current_clip not in self.state.project.clips:
        return 0.0
    _rect, left, right, _top, _row_h = self._timeline_metrics()
    clip = self.state.project.clips[self.state.current_clip]
    if right <= left:
        return 0.0
    t = max(0.0, min(1.0, (pos[0] - left) / (right - left)))
    return round(t * clip.length)


def _v8_timeline_row_from_pos(self, pos):
    if not self.state.current_clip or self.state.current_clip not in self.state.project.clips:
        return None
    rect, _left, _right, top, row_h = self._timeline_metrics()
    if not rect.collidepoint(pos):
        return None
    clip = self.state.project.clips[self.state.current_clip]
    rows = timeline_rows(self.state.project, clip)
    idx = int((pos[1] - top) // row_h) + self.state.timeline_scroll
    if 0 <= idx < len(rows):
        return rows[idx]
    return None


def _v8_timeline_key_hit(self, pos):
    if not self.state.current_clip or self.state.current_clip not in self.state.project.clips:
        return None
    clip = self.state.project.clips[self.state.current_clip]
    row = self._timeline_row_from_pos(pos)
    if row is None:
        return None
    frame = self._timeline_frame_from_pos(pos)
    near = find_nearest_key(clip, row.instance, row.channel, frame, max_delta=max(0.75, clip.length / 120.0))
    if near is None:
        return None
    return (row.instance, row.channel, near)


def _v8_timeline_mouse_down(self, pos) -> None:
    if not self.state.current_clip:
        self.state.message = "no clip yet; press K to create anim"
        return
    key = self._timeline_key_hit(pos)
    if key:
        inst, channel, frame = key
        self.state.selected = inst
        self.state.selected_key_instance = inst
        self.state.selected_key_channel = channel
        self.state.selected_key_frame = frame
        self.state.timeline_drag_key = key
        self.state.frame = frame
        self.state.message = f"selected key {inst}.{channel} @{frame:.0f}"
        return
    row = self._timeline_row_from_pos(pos)
    if row:
        self.state.selected = row.instance
        self.state.selected_key_instance = None
        self.state.selected_key_channel = None
        self.state.selected_key_frame = None
    self.state.frame = self._timeline_frame_from_pos(pos)
    self.state.message = f"frame {self.state.frame:.0f}"


def _v8_timeline_mouse_up(self, pos) -> None:
    key = self.state.timeline_drag_key
    self.state.timeline_drag_key = None
    if not key:
        return
    inst, channel, old_frame = key
    new_frame = self._timeline_frame_from_pos(pos)
    self.state.selected_key_instance = inst
    self.state.selected_key_channel = channel
    self.state.selected_key_frame = old_frame
    self.tool.move_selected_keyframe(self.state, new_frame)


def _v8_sidebar_hit(self, pos):
    for rect, kind, name in self.sidebar_rows:
        if rect.collidepoint(pos):
            return kind, name
    return None


def _v8_sidebar_click_hit(self, kind: str, name: str) -> bool:
    if kind == "sprite":
        self.state.selected_sprite = name
        self.state.selected_point = None
        self.state.mode = "sprite"
        self.state.message = f"selected sprite {name}"
        return True
    if kind == "instance":
        self.state.selected = name
        self.state.mode = "animation" if self.state.mode == "animation" else "rig"
        self.state.message = f"selected instance {name}"
        return True
    if kind == "attach_pair":
        parent_point, self_point = name.split("|", 1)
        self.tool.set_attachment_pair(self.state, parent_point, self_point)
        return True
    if kind == "parent_candidate":
        parent, parent_point, self_point = name.split("|", 2)
        self.tool.reparent_selected_to_hover(self.state, parent)
        inst_name = self.state.selected
        if inst_name and inst_name in self.state.project.rig.instances:
            inst = self.state.project.rig.instances[inst_name]
            if inst.parent == parent and (inst.parent_point, inst.self_point) != (parent_point, self_point):
                self.tool.set_attachment_pair(self.state, parent_point, self_point)
        return True
    if kind == "named_pose":
        self.tool.apply_named_pose(self.state, name)
        return True
    return False


def _v8_sidebar_click(self, pos) -> bool:
    hit = self._sidebar_hit(pos)
    if hit:
        return self._sidebar_click_hit(hit[0], hit[1])
    return False


def _v8_sidebar_mouse_up(self, pos) -> None:
    child = self.state.sidebar_drag_instance
    self.state.sidebar_drag_instance = None
    hit = self._sidebar_hit(pos)
    self.state.sidebar_hover_instance = None
    if not child or not hit or hit[0] != "instance":
        return
    parent = hit[1]
    if parent == child:
        return
    self.tool.reparent_instance_to_parent(self.state, child, parent)


def _v8_draw_timeline(self) -> None:
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    rect = self._timeline_rect()
    pygame.draw.rect(self.screen, (18, 18, 22), rect)
    pygame.draw.rect(self.screen, (70, 70, 80), rect, 1)
    dim = (175, 175, 180)
    bright = (235, 235, 235)
    yellow = (255, 220, 80)
    blue = (130, 190, 255)
    orange = (255, 160, 80)
    green = (130, 255, 170)
    if not self.state.current_clip or self.state.current_clip not in self.state.project.clips:
        self.screen.blit(self.font.render("Timeline: press K to create anim clip", True, dim), (rect.x + 10, rect.y + 8))
        return
    clip = self.state.project.clips[self.state.current_clip]
    _rect, left, right, top, row_h = self._timeline_metrics()
    span = max(1.0, clip.length)
    self.screen.blit(self.font.render(f"{clip.name}  frame {self.state.frame:.0f}/{clip.length:.0f}", True, yellow), (rect.x + 10, rect.y + 8))
    self.screen.blit(self.font.render("diamonds: selected key can drag left/right", True, dim), (rect.x + 260, rect.y + 8))
    tick = max(1, int(round(clip.fps / 2)))
    bottom = rect.bottom - 12
    for f in range(0, int(clip.length) + 1, tick):
        px = left + int((f / span) * (right - left))
        pygame.draw.line(self.screen, (55, 55, 62), (px, top - 2), (px, bottom))
        if f % max(1, int(clip.fps)) == 0:
            self.screen.blit(self.font.render(str(f), True, dim), (px + 2, rect.y + 8))
    rows = timeline_rows(self.state.project, clip)
    visible_rows = max(1, (rect.bottom - top - 8) // row_h)
    self.state.timeline_scroll = max(0, min(self.state.timeline_scroll, max(0, len(rows) - visible_rows)))
    rows_to_draw = rows[self.state.timeline_scroll:self.state.timeline_scroll + visible_rows]
    for i, row in enumerate(rows_to_draw):
        yy = top + i * row_h
        selected_row = row.instance == self.state.selected
        label = ("  " * row.depth) + f"{row.instance}.{row.channel}"
        self.screen.blit(self.font.render(label[:18], True, yellow if selected_row else bright), (rect.x + 8, yy - 2))
        pygame.draw.line(self.screen, (45, 45, 50), (left, yy + 7), (right, yy + 7))
        track = clip.tracks.get(row.instance)
        if track:
            keys = track.channels.get(row.channel, {})
            mode = track.interpolation.get(row.channel, "linear")
            marker_color = blue if mode == "linear" else orange
            for frame in sorted(float(f) for f in keys):
                px = left + int((frame / span) * (right - left))
                diamond = [(px, yy), (px + 5, yy + 7), (px, yy + 14), (px - 5, yy + 7)]
                selected_key = (
                    self.state.selected_key_instance == row.instance and
                    self.state.selected_key_channel == row.channel and
                    self.state.selected_key_frame == frame
                )
                pygame.draw.polygon(self.screen, green if selected_key else marker_color, diamond)
                if selected_key:
                    pygame.draw.polygon(self.screen, (10, 10, 12), diamond, 1)
    play_x = left + int((max(0.0, min(clip.length, self.state.frame)) / span) * (right - left))
    pygame.draw.line(self.screen, yellow, (play_x, top - 6), (play_x, bottom + 4), 2)


def _v8_named_pose_sidebar_rows(self, bright, yellow, blue, dim, green) -> list[tuple]:
    poses = self.state.project.metadata.get("named_poses", {})
    rows: list[tuple] = [("", dim), ("Named poses:", blue)]
    if not poses:
        rows.append(("  N save current pose", dim))
        return rows
    for name in sorted(poses):
        count = len(poses.get(name, {})) if isinstance(poses.get(name), dict) else 0
        rows.append((f"  {name} ({count} parts)", green, "named_pose", name))
    rows.append(("  click pose to key it at current frame", dim))
    return rows


EditorApp._timeline_metrics = _v8_timeline_metrics
EditorApp._timeline_frame_from_pos = _v8_timeline_frame_from_pos
EditorApp._timeline_row_from_pos = _v8_timeline_row_from_pos
EditorApp._timeline_key_hit = _v8_timeline_key_hit
EditorApp._timeline_mouse_down = _v8_timeline_mouse_down
EditorApp._timeline_mouse_up = _v8_timeline_mouse_up
EditorApp._sidebar_hit = _v8_sidebar_hit
EditorApp._sidebar_click_hit = _v8_sidebar_click_hit
EditorApp._sidebar_click = _v8_sidebar_click
EditorApp._sidebar_mouse_up = _v8_sidebar_mouse_up
EditorApp._draw_timeline = _v8_draw_timeline
EditorApp._named_pose_sidebar_rows = _v8_named_pose_sidebar_rows

# ---------------------------------------------------------------------------
# v9 UI/layout extensions: resizable panels, scrollable sidebars, buttons,
# dropdowns, and context menus. Kept as monkey-patches to make the UI pass easy
# to review against v8.
# ---------------------------------------------------------------------------
from pyspine.editor.ui import (  # noqa: E402
    Dropdown,
    FloatingMenu,
    MenuItem,
    compute_layout,
    scroll_offset_for_content,
    scroll_thumb,
)

_v8_init = EditorApp.__init__


def _v9_init(self, path):
    _v8_init(self, path)
    self.context_menu = None
    self.dropdown = None
    self._right_down_pos = None
    self._right_panning = False
    self._sidebar_content_h = 0


def _v9_layout(self):
    assert self.screen is not None
    w, h = self.screen.get_size()
    return compute_layout(w, h, show_timeline=(self.state.mode == "animation"))


def _v9_timeline_rect(self):
    pygame = self.pygame
    return pygame.Rect(*self._layout().timeline_rect)


def _v9_sidebar_rect(self):
    pygame = self.pygame
    return pygame.Rect(*self._layout().sidebar_rect)


def _v9_canvas_rect(self):
    pygame = self.pygame
    return pygame.Rect(*self._layout().canvas_rect)


def _v9_timeline_metrics(self):
    rect = self._timeline_rect()
    left = rect.x + max(135, int(rect.w * 0.20))
    right = rect.right - 24
    top = rect.y + 34
    row_h = 18
    return rect, left, right, top, row_h


def _v9_button(self, rect, label, *, kind, name, active=False, enabled=True):
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    bg = (63, 63, 72) if active else (42, 42, 48)
    fg = (235, 235, 235) if enabled else (120, 120, 128)
    border = (255, 220, 80) if active else (88, 88, 98)
    pygame.draw.rect(self.screen, bg, rect, border_radius=4)
    pygame.draw.rect(self.screen, border, rect, 1, border_radius=4)
    surf = self.font.render(label, True, fg)
    self.screen.blit(surf, (rect.x + 8, rect.y + max(2, (rect.h - surf.get_height()) // 2)))
    if enabled:
        self.sidebar_rows.append((rect, kind, name))


def _v9_draw_sidebar(self) -> None:
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    panel = self._sidebar_rect()
    pygame.draw.rect(self.screen, (24, 24, 28), panel)
    pygame.draw.line(self.screen, (64, 64, 72), (panel.x, panel.y), (panel.x, panel.bottom))
    self.sidebar_rows.clear()

    yellow = (255, 220, 80)
    dim = (175, 175, 180)
    bright = (235, 235, 235)
    blue = (130, 190, 255)
    red = (255, 130, 130)

    x = panel.x + 12
    y = 9
    title = f"pyspine v9 [{self.state.mode}] {'*' if self.state.dirty else ''}"
    self.screen.blit(self.font.render(title, True, yellow), (x, y))
    y += 24

    gap = 6
    mode_w = max(76, (panel.w - 32 - 2 * gap) // 3)
    for label, mode, idx in (("Sprite", "sprite", 0), ("Rig", "rig", 1), ("Anim", "animation", 2)):
        r = pygame.Rect(x + idx * (mode_w + gap), y, mode_w, 25)
        self._ui_button(r, label, kind="mode_button", name=mode, active=self.state.mode == mode)
    y += 34

    small_w = max(62, (panel.w - 32 - 3 * gap) // 4)
    buttons = [
        ("Save", "save"),
        ("Undo", "undo"),
        ("Redo", "redo"),
        ("Fit", "fit"),
    ]
    for idx, (label, action) in enumerate(buttons):
        r = pygame.Rect(x + idx * (small_w + gap), y, small_w, 24)
        self._ui_button(r, label, kind="action_button", name=action)
    y += 31

    if self.state.mode == "animation":
        play_label = "Pause" if self.state.playing else "Play"
        w1 = (panel.w - 32 - 2 * gap) // 3
        for idx, (label, action) in enumerate(((play_label, "play"), ("Onion", "onion"), ("Clip ▾", "clip_dropdown"))):
            r = pygame.Rect(x + idx * (w1 + gap), y, w1, 24)
            self._ui_button(r, label, kind="action_button", name=action, active=(action == "onion" and self.state.onion_skin))
        y += 31

    help_line = "RMB menu | drag panels with wheel | MMB/RMB-drag pan"
    self.screen.blit(self.font.render(help_line[:58], True, dim), (x, y))
    y += 22

    content_top = y + 3
    content = pygame.Rect(panel.x + 8, content_top, panel.w - 18, max(1, panel.bottom - content_top - 8))
    pygame.draw.rect(self.screen, (20, 20, 24), content)
    pygame.draw.rect(self.screen, (45, 45, 52), content, 1)

    # Reuse the mode-sensitive v8 sidebar line builder, but replace its fixed
    # header with this real button/header area.
    lines = self._sidebar_lines()[4:]
    line_h = 19
    content_h = max(1, len(lines) * line_h + 4)
    self._sidebar_content_h = content_h
    self.state.sidebar_scroll_px = scroll_offset_for_content(self.state.sidebar_scroll_px, content.h, content_h)

    old_clip = self.screen.get_clip()
    self.screen.set_clip(content)
    yy = content.y + 4 - self.state.sidebar_scroll_px
    for item in lines:
        if len(item) == 2:
            line, color = item
            kind = name = None
        else:
            line, color, kind, name = item
        if yy > content.bottom:
            break
        if yy + line_h >= content.y:
            if kind and name:
                row_rect = pygame.Rect(content.x, yy - 1, content.w - 12, line_h)
                if kind == "instance" and name == self.state.sidebar_hover_instance:
                    pygame.draw.rect(self.screen, (48, 72, 56), row_rect)
                elif kind in {"attach_pair", "parent_candidate", "named_pose"}:
                    pygame.draw.rect(self.screen, (30, 34, 40), row_rect)
                self.sidebar_rows.append((row_rect, kind, name))
            surf = self.font.render(str(line)[:max(24, panel.w // 8)], True, color)
            self.screen.blit(surf, (content.x + 7, yy))
        yy += line_h
    self.screen.set_clip(old_clip)

    thumb = scroll_thumb(content.h, content_h, self.state.sidebar_scroll_px)
    if thumb:
        ty, th = thumb
        track = pygame.Rect(content.right - 9, content.y + 3, 5, content.h - 6)
        pygame.draw.rect(self.screen, (42, 42, 48), track, border_radius=3)
        pygame.draw.rect(self.screen, (120, 120, 132), (track.x, track.y + ty, track.w, th), border_radius=3)


def _v9_draw_dropdown(self) -> None:
    dd = getattr(self, "dropdown", None)
    if dd is None:
        return
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    rect = pygame.Rect(dd.x, dd.y, dd.width, dd.height())
    pygame.draw.rect(self.screen, (12, 12, 16), rect, border_radius=5)
    pygame.draw.rect(self.screen, (255, 220, 80), rect, 1, border_radius=5)
    y = dd.y + 4
    for label, value in dd.options:
        row = pygame.Rect(dd.x + 4, y, dd.width - 8, dd.row_h)
        active = value == self.state.current_clip
        if active:
            pygame.draw.rect(self.screen, (58, 58, 68), row, border_radius=3)
        self.screen.blit(self.font.render(label[:28], True, (235, 235, 235)), (row.x + 6, row.y + 4))
        y += dd.row_h


def _v9_draw_context_menu(self) -> None:
    menu = getattr(self, "context_menu", None)
    if menu is None:
        return
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    rect = pygame.Rect(menu.x, menu.y, menu.width, menu.height())
    pygame.draw.rect(self.screen, (12, 12, 16), rect, border_radius=6)
    pygame.draw.rect(self.screen, (255, 220, 80), rect, 1, border_radius=6)
    y = menu.y + 4
    for item in menu.items:
        row = pygame.Rect(menu.x + 4, y, menu.width - 8, menu.row_h)
        if item.enabled:
            pygame.draw.rect(self.screen, (24, 24, 30), row, border_radius=3)
        color = (235, 235, 235) if item.enabled else (100, 100, 110)
        self.screen.blit(self.font.render(item.label[:32], True, color), (row.x + 8, row.y + 4))
        y += menu.row_h


def _v9_draw(self) -> None:
    pygame = self.pygame
    assert self.screen is not None
    self.screen.fill((31, 31, 34))
    canvas = self._canvas_rect()
    old_clip = self.screen.get_clip()
    self.screen.set_clip(canvas)
    self._draw_grid()
    if self.state.mode == "sprite":
        self._draw_sprite_sheet_mode()
    else:
        self._draw_rig_mode()
    self.screen.set_clip(old_clip)
    if self.state.mode == "animation":
        self._draw_timeline()
    self._draw_sidebar()
    self._draw_prompt()
    self._draw_dropdown()
    self._draw_context_menu()
    pygame.display.flip()


def _v9_draw_timeline(self) -> None:
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    rect = self._timeline_rect()
    pygame.draw.rect(self.screen, (18, 18, 22), rect)
    pygame.draw.rect(self.screen, (70, 70, 80), rect, 1)
    dim = (175, 175, 180)
    bright = (235, 235, 235)
    yellow = (255, 220, 80)
    blue = (130, 190, 255)
    orange = (255, 160, 80)
    green = (130, 255, 170)
    if not self.state.current_clip or self.state.current_clip not in self.state.project.clips:
        self.screen.blit(self.font.render("Timeline: press K or right-click to create/key anim", True, dim), (rect.x + 10, rect.y + 8))
        return
    clip = self.state.project.clips[self.state.current_clip]
    _rect, left, right, top, row_h = self._timeline_metrics()
    span = max(1.0, clip.length)
    self.screen.blit(self.font.render(f"{clip.name}  frame {self.state.frame:.0f}/{clip.length:.0f}", True, yellow), (rect.x + 10, rect.y + 8))
    self.screen.blit(self.font.render("wheel: scroll rows | drag diamonds: move key", True, dim), (left + 5, rect.y + 8))
    tick = max(1, int(round(clip.fps / 2)))
    bottom = rect.bottom - 16
    for f in range(0, int(clip.length) + 1, tick):
        px = left + int((f / span) * (right - left))
        pygame.draw.line(self.screen, (55, 55, 62), (px, top - 2), (px, bottom))
        if f % max(1, int(clip.fps)) == 0:
            self.screen.blit(self.font.render(str(f), True, dim), (px + 2, rect.y + 8))
    rows = timeline_rows(self.state.project, clip)
    visible_rows = max(1, (rect.bottom - top - 10) // row_h)
    self.state.timeline_scroll = max(0, min(self.state.timeline_scroll, max(0, len(rows) - visible_rows)))
    rows_to_draw = rows[self.state.timeline_scroll:self.state.timeline_scroll + visible_rows]
    for i, row in enumerate(rows_to_draw):
        yy = top + i * row_h
        selected_row = row.instance == self.state.selected
        label = ("  " * row.depth) + f"{row.instance}.{row.channel}"
        row_rect = pygame.Rect(rect.x + 4, yy - 2, rect.w - 12, row_h)
        if selected_row:
            pygame.draw.rect(self.screen, (36, 36, 43), row_rect)
        self.screen.blit(self.font.render(label[:24], True, yellow if selected_row else bright), (rect.x + 8, yy - 2))
        pygame.draw.line(self.screen, (45, 45, 50), (left, yy + 7), (right, yy + 7))
        track = clip.tracks.get(row.instance)
        if track:
            keys = track.channels.get(row.channel, {})
            mode = track.interpolation.get(row.channel, "linear")
            marker_color = blue if mode == "linear" else orange
            for frame in sorted(float(f) for f in keys):
                px = left + int((frame / span) * (right - left))
                diamond = [(px, yy), (px + 5, yy + 7), (px, yy + 14), (px - 5, yy + 7)]
                selected_key = (
                    self.state.selected_key_instance == row.instance and
                    self.state.selected_key_channel == row.channel and
                    self.state.selected_key_frame == frame
                )
                pygame.draw.polygon(self.screen, green if selected_key else marker_color, diamond)
                if selected_key:
                    pygame.draw.polygon(self.screen, (10, 10, 12), diamond, 1)
    play_x = left + int((max(0.0, min(clip.length, self.state.frame)) / span) * (right - left))
    pygame.draw.line(self.screen, yellow, (play_x, top - 6), (play_x, bottom + 4), 2)
    thumb = scroll_thumb(visible_rows, len(rows), self.state.timeline_scroll, min_thumb=3)
    if thumb:
        ty, th = thumb
        track = pygame.Rect(rect.right - 10, top, 5, max(8, visible_rows * row_h))
        pygame.draw.rect(self.screen, (42, 42, 48), track, border_radius=3)
        # thumb coordinates are row units; scale to pixels
        max_units = max(1, visible_rows - th)
        max_px = max(1, track.h - max(8, th * row_h))
        y_px = int((ty / max_units) * max_px) if max_units else 0
        pygame.draw.rect(self.screen, (120, 120, 132), (track.x, track.y + y_px, track.w, max(8, th * row_h)), border_radius=3)


def _v9_sidebar_click_hit(self, kind: str, name: str) -> bool:
    if kind == "mode_button":
        self.state.mode = name
        self.state.message = f"{name} mode"
        return True
    if kind == "action_button":
        self._ui_action(name)
        return True
    return _v8_sidebar_click_hit(self, kind, name)


def _v9_ui_action(self, action: str) -> None:
    if action == "save":
        self._save()
    elif action == "undo":
        self.state.undo(); self.sprite_cache.clear()
    elif action == "redo":
        self.state.redo(); self.sprite_cache.clear()
    elif action == "fit":
        self._fit_view()
    elif action == "play":
        self.state.playing = not self.state.playing
    elif action == "onion":
        self.state.onion_skin = not self.state.onion_skin
        self.state.message = "onion skin " + ("on" if self.state.onion_skin else "off")
    elif action == "clip_dropdown":
        self._open_clip_dropdown()
    elif action == "add_instance":
        self.tool.add_instance(self.state, self.state.last_mouse_world)
    elif action == "add_point":
        self.tool.add_point_at_mouse(self.state)
    elif action == "rename":
        self.tool.prompt_rename(self.state)
    elif action == "delete":
        if self.state.mode == "animation" and self.state.selected_key_instance:
            self.tool.delete_keyframe(self.state)
        else:
            self.tool.delete_selected(self.state)
        self.sprite_cache.clear()
    elif action == "unparent":
        self.tool.reparent_selected_to_hover(self.state, None)
    elif action == "key_rotation":
        self.tool.set_keyframe(self.state)
    elif action == "key_pose":
        self.tool.set_pose_keyframes(self.state, selected_only=False)
    elif action == "copy_pose":
        self.tool.copy_pose(self.state, selected_only=False)
    elif action == "paste_pose":
        self.tool.paste_pose(self.state)
    elif action == "reset_pose":
        self.tool.reset_pose_keyframes(self.state, selected_only=False)
    elif action == "toggle_interp":
        self.tool.toggle_interpolation(self.state)
    elif action == "save_pose":
        self.state.text_prompt = TextPrompt("save_pose", "pose", {})
        self.state.message = "type pose name and press Enter"
    elif action.startswith("mode:"):
        self.state.mode = action.split(":", 1)[1]
    self.context_menu = None
    self.dropdown = None


def _v9_open_clip_dropdown(self) -> None:
    # v13.2: make the Clip button always visibly do something and route the
    # resulting dropdown as a clip picker instead of accidentally reusing the
    # property-inspector dropdown purpose from v12.
    panel = self._sidebar_rect()
    options = [(name, name) for name in sorted(self.state.project.clips)]
    options.append(("+ New clip...", "__new_clip__"))
    if not self.state.project.clips:
        options.insert(0, ("No clips yet", ""))
    self.dropdown = Dropdown(panel.x + 16, 102, max(220, panel.w - 32), options)
    self.dropdown_purpose = ("clip",)
    self.context_menu = None
    self.state.message = "choose clip"


def _v9_fit_view(self) -> None:
    # Fit all sprites in sprite mode, otherwise fit current pose bounds roughly.
    canvas = self._canvas_rect()
    if canvas.w <= 0 or canvas.h <= 0:
        return
    points = []
    if self.state.mode == "sprite" and self.sheet_surface is not None:
        w, h = self.sheet_surface.get_size()
        points = [Vec2(0, 0), Vec2(w, h)]
    else:
        poses = self._current_pose()
        for pose in poses.values():
            sprite = self.state.project.sheet.sprites[pose.sprite]
            points.extend([pose.local_to_world(c) for c in sprite.rect.corners()])
    if not points:
        self.state.viewport.offset = Vec2(canvas.x + canvas.w / 2, canvas.y + canvas.h / 2)
        self.state.viewport.zoom = 2.0
        return
    min_x = min(p.x for p in points); max_x = max(p.x for p in points)
    min_y = min(p.y for p in points); max_y = max(p.y for p in points)
    bw = max(1.0, max_x - min_x); bh = max(1.0, max_y - min_y)
    zoom = min(canvas.w / (bw + 40), canvas.h / (bh + 40))
    self.state.viewport.zoom = max(0.25, min(8.0, zoom))
    cx = (min_x + max_x) / 2.0; cy = (min_y + max_y) / 2.0
    self.state.viewport.offset = Vec2(canvas.x + canvas.w / 2 - cx * self.state.viewport.zoom, canvas.y + canvas.h / 2 - cy * self.state.viewport.zoom)
    self.state.message = "fit view"


def _v9_context_items(self) -> list[MenuItem]:
    s = self.state
    items: list[MenuItem] = []
    if s.mode == "sprite":
        items += [
            MenuItem("Add attachment point", "add_point", bool(s.selected_sprite)),
            MenuItem("Rename selected", "rename", bool(s.selected_sprite or s.selected_point)),
            MenuItem("Delete selected", "delete", bool(s.selected_sprite)),
            MenuItem("Add selected sprite to rig", "add_instance", bool(s.selected_sprite)),
            MenuItem("Switch to Rig mode", "mode:rig"),
        ]
    elif s.mode == "rig":
        inst_has_parent = bool(s.selected and s.selected in s.project.rig.instances and s.project.rig.instances[s.selected].parent)
        items += [
            MenuItem("Add selected sprite here", "add_instance", bool(s.selected_sprite)),
            MenuItem("Rename sprite/point", "rename", bool(s.selected_sprite or s.selected_point)),
            MenuItem("Unparent selected", "unparent", inst_has_parent),
            MenuItem("Delete selected instance", "delete", bool(s.selected)),
            MenuItem("Switch to Animation mode", "mode:animation"),
        ]
    else:
        items += [
            MenuItem("Key selected rotation", "key_rotation", bool(s.selected)),
            MenuItem("Key full pose", "key_pose", bool(s.project.rig.instances)),
            MenuItem("Copy pose", "copy_pose", bool(s.project.rig.instances)),
            MenuItem("Paste pose", "paste_pose", bool(s.pose_clipboard)),
            MenuItem("Reset pose", "reset_pose", bool(s.project.rig.instances)),
            MenuItem("Toggle interpolation", "toggle_interp", bool(s.selected)),
            MenuItem("Save named pose", "save_pose", bool(s.project.rig.instances)),
        ]
    return items


def _v9_show_context_menu(self, pos) -> None:
    assert self.screen is not None
    items = self._context_items()
    if not items:
        self.context_menu = None
        return
    w, h = self.screen.get_size()
    menu = FloatingMenu(int(pos[0]), int(pos[1]), items)
    menu.x = max(4, min(menu.x, w - menu.width - 4))
    menu.y = max(4, min(menu.y, h - menu.height() - 4))
    self.context_menu = menu
    self.dropdown = None


def _v9_menu_click(self, pos) -> bool:
    if self.dropdown is not None:
        value = self.dropdown.hit(pos[0], pos[1])
        if value is not None:
            if value:
                self.state.current_clip = value
                self.state.message = f"clip {value}"
            self.dropdown = None
            return True
        self.dropdown = None
    if self.context_menu is not None:
        item = self.context_menu.hit(pos[0], pos[1])
        if item is not None:
            self._ui_action(item.action)
            return True
        self.context_menu = None
    return False


def _v9_events(self) -> bool:
    pygame = self.pygame
    assert self.screen is not None
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if self.state.text_prompt is not None:
            if event.type == pygame.KEYDOWN:
                self._prompt_key(event)
            continue
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.context_menu or self.dropdown:
                    self.context_menu = None; self.dropdown = None
                    continue
                return False
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            shift = bool(mods & pygame.KMOD_SHIFT)
            if ctrl and event.key == pygame.K_s:
                self._save()
            elif ctrl and event.key == pygame.K_z:
                self.state.undo(); self.sprite_cache.clear()
            elif ctrl and event.key == pygame.K_y:
                self.state.redo(); self.sprite_cache.clear()
            elif ctrl and event.key == pygame.K_c:
                if shift and self.state.mode == "animation":
                    self.tool.copy_frame_keyframes(self.state, selected_only=False)
                else:
                    self.tool.copy_pose(self.state, selected_only=not shift)
            elif ctrl and event.key == pygame.K_v:
                if shift and self.state.mode == "animation":
                    self.tool.paste_frame_keyframes(self.state)
                else:
                    self.tool.paste_pose(self.state)
            elif event.key == pygame.K_SPACE:
                self.state.playing = not self.state.playing
            elif event.key == pygame.K_1:
                self.state.mode = "sprite"; self.state.message = "Sprite Sheet Mode"
            elif event.key == pygame.K_2:
                self.state.mode = "rig"; self.state.message = "Rig Mode"
            elif event.key == pygame.K_3:
                self.state.mode = "animation"; self.state.message = "Animation Mode"
            elif event.key == pygame.K_F2:
                self.tool.prompt_rename(self.state)
            elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE) and not ctrl:
                if self.state.mode == "animation" and self.state.selected_key_instance:
                    self.tool.delete_keyframe(self.state)
                else:
                    self.tool.delete_selected(self.state)
                self.sprite_cache.clear()
            elif event.key == pygame.K_a and self.state.mode == "sprite":
                self.tool.add_point_at_mouse(self.state)
            elif event.key == pygame.K_i:
                self.tool.add_instance(self.state, self.state.last_mouse_world)
            elif event.key == pygame.K_u and self.state.mode == "rig":
                self.tool.reparent_selected_to_hover(self.state, None)
            elif event.key == pygame.K_p and self.state.mode == "rig":
                parent = self._instance_under_mouse(exclude=self.state.selected)
                if parent:
                    self.tool.reparent_selected_to_hover(self.state, parent)
            elif event.key == pygame.K_c and self.state.mode == "rig" and not ctrl:
                self.tool.cycle_attachment_pair(self.state, -1 if shift else 1)
            elif event.key == pygame.K_k and self.state.mode == "animation":
                if shift:
                    self.tool.set_pose_keyframes(self.state, selected_only=False)
                else:
                    self.tool.set_keyframe(self.state)
            elif event.key == pygame.K_j and self.state.mode == "animation":
                self.tool.set_pose_keyframes(self.state, selected_only=True)
            elif event.key == pygame.K_t and self.state.mode == "animation":
                self.tool.toggle_interpolation(self.state)
            elif event.key == pygame.K_o and self.state.mode == "animation":
                self.state.onion_skin = not self.state.onion_skin
                self.state.message = "onion skin " + ("on" if self.state.onion_skin else "off")
            elif event.key == pygame.K_f and self.state.mode == "animation":
                if shift:
                    self.tool.paste_frame_keyframes(self.state)
                else:
                    self.tool.copy_frame_keyframes(self.state, selected_only=bool(ctrl and self.state.selected))
            elif event.key == pygame.K_m and self.state.mode == "animation":
                self.tool.mirror_pose_keyframes(self.state)
            elif event.key == pygame.K_x and self.state.mode == "animation":
                self.tool.reset_pose_keyframes(self.state, selected_only=shift)
            elif event.key == pygame.K_n and self.state.mode == "animation":
                self.state.text_prompt = TextPrompt("save_pose", "pose", {})
                self.state.message = "type pose name and press Enter"
            elif event.key in (pygame.K_LEFTBRACKET, pygame.K_COMMA):
                self.tool.rotate_selected(self.state, -5.0 if not shift else -1.0)
            elif event.key in (pygame.K_RIGHTBRACKET, pygame.K_PERIOD):
                self.tool.rotate_selected(self.state, 5.0 if not shift else 1.0)
            elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                self.tool.adjust_z(self.state, 1)
            elif event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE):
                self.tool.adjust_z(self.state, -1)
            elif event.key == pygame.K_LEFT:
                self.state.frame = max(0.0, self.state.frame - (10.0 if shift else 1.0))
            elif event.key == pygame.K_RIGHT:
                self.state.frame += 10.0 if shift else 1.0
            elif event.key == pygame.K_HOME:
                self.state.frame = 0.0
            elif event.key == pygame.K_END and self.state.current_clip:
                self.state.frame = self.state.project.clips[self.state.current_clip].length
            elif event.key == pygame.K_TAB:
                self._cycle_selection(reverse=shift)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            pos = Vec2(*event.pos)
            world = self.state.viewport.screen_to_world(pos)
            self.state.last_mouse_world = world
            if event.button == 1:
                if self._menu_click(event.pos):
                    continue
                hit = self._sidebar_hit(event.pos)
                if hit:
                    kind, name = hit
                    if kind == "instance" and self.state.mode != "sprite":
                        self.state.sidebar_drag_instance = name
                        self.state.sidebar_hover_instance = None
                    self._sidebar_click_hit(kind, name)
                elif self.state.mode == "animation" and self._timeline_contains(event.pos):
                    self._timeline_mouse_down(event.pos)
                else:
                    self.tool.click(self.state, world, modifiers=pygame.key.get_mods())
            elif event.button == 2:
                # Middle click is now a pure pan button. Add instance via toolbar, I, or context menu.
                self._right_down_pos = event.pos
                self._right_panning = True
            elif event.button == 3:
                self._right_down_pos = event.pos
                self._right_panning = False
            elif event.button in (4, 5):
                delta = -1 if event.button == 4 else 1
                if self._sidebar_rect().collidepoint(event.pos):
                    self.state.sidebar_scroll_px = scroll_offset_for_content(
                        self.state.sidebar_scroll_px + delta * 57,
                        max(1, self._sidebar_rect().h - 150),
                        max(1, getattr(self, "_sidebar_content_h", 1)),
                    )
                elif self.state.mode == "animation" and self._timeline_contains(event.pos):
                    self.state.timeline_scroll = max(0, self.state.timeline_scroll + delta * 3)
                else:
                    self.state.viewport.zoom_at(pos, 1.1 if event.button == 4 else 1.0 / 1.1)
        elif event.type == pygame.MOUSEMOTION:
            pos = Vec2(*event.pos)
            world = self.state.viewport.screen_to_world(pos)
            self.state.last_mouse_world = world
            if event.buttons[0]:
                if self.state.timeline_drag_key:
                    frame = self._timeline_frame_from_pos(event.pos)
                    self.state.frame = frame
                    inst, channel, old = self.state.timeline_drag_key
                    self.state.message = f"move key {inst}.{channel} {old:.0f} -> {frame:.0f}"
                elif self.state.sidebar_drag_instance:
                    hit = self._sidebar_hit(event.pos)
                    self.state.sidebar_hover_instance = hit[1] if hit and hit[0] == "instance" else None
                elif not (self.state.mode == "animation" and self._timeline_contains(event.pos)):
                    self.tool.drag_to(self.state, world)
                    if self.tool.drag and self.tool.drag.kind in {"point"}:
                        self.sprite_cache.clear()
            elif event.buttons[1] or event.buttons[2]:
                if event.buttons[2] and self._right_down_pos:
                    if abs(event.pos[0] - self._right_down_pos[0]) + abs(event.pos[1] - self._right_down_pos[1]) > 5:
                        self._right_panning = True
                        self.context_menu = None
                        self.dropdown = None
                self.state.viewport.pan(event.rel[0], event.rel[1])
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                if self.state.timeline_drag_key:
                    self._timeline_mouse_up(event.pos)
                elif self.state.sidebar_drag_instance:
                    self._sidebar_mouse_up(event.pos)
                else:
                    self.tool.release(self.state)
                self.sprite_cache.clear()
            elif event.button == 3:
                if not self._right_panning:
                    self._show_context_menu(event.pos)
                self._right_down_pos = None
                self._right_panning = False
            elif event.button == 2:
                self._right_down_pos = None
                self._right_panning = False
    return True


EditorApp.__init__ = _v9_init
EditorApp._layout = _v9_layout
EditorApp._timeline_rect = _v9_timeline_rect
EditorApp._sidebar_rect = _v9_sidebar_rect
EditorApp._canvas_rect = _v9_canvas_rect
EditorApp._timeline_metrics = _v9_timeline_metrics
EditorApp._ui_button = _v9_button
EditorApp._draw_sidebar = _v9_draw_sidebar
EditorApp._draw_dropdown = _v9_draw_dropdown
EditorApp._draw_context_menu = _v9_draw_context_menu
EditorApp._draw = _v9_draw
EditorApp._draw_timeline = _v9_draw_timeline
EditorApp._sidebar_click_hit = _v9_sidebar_click_hit
EditorApp._ui_action = _v9_ui_action
EditorApp._open_clip_dropdown = _v9_open_clip_dropdown
EditorApp._fit_view = _v9_fit_view
EditorApp._context_items = _v9_context_items
EditorApp._show_context_menu = _v9_show_context_menu
EditorApp._menu_click = _v9_menu_click
EditorApp._events = _v9_events

# ---------------------------------------------------------------------------
# v10 UI polish: draggable panel dividers, formal text/dropdown widgets, and
# stricter event-routing invariants.  v9 got the UI on screen; v10 makes the
# layout user-adjustable and keeps hit-testing constrained to the right panel.
# ---------------------------------------------------------------------------
from pyspine.editor.ui import (  # noqa: E402,F811
    TextInput,
    resize_sidebar_from_mouse,
    resize_timeline_from_mouse,
)

_v9_init_for_v10 = EditorApp.__init__


def _v10_init(self, path):
    _v9_init_for_v10(self, path)
    self.prompt_input = None
    self._prompt_id = None


def _v10_layout(self):
    assert self.screen is not None
    w, h = self.screen.get_size()
    return compute_layout(
        w,
        h,
        show_timeline=(self.state.mode == "animation"),
        sidebar_w=self.state.ui_sidebar_w,
        timeline_h=self.state.ui_timeline_h,
    )


def _v10_splitter_hit(self, pos):
    pygame = self.pygame
    layout = self._layout()
    if pygame.Rect(*layout.sidebar_splitter_rect).collidepoint(pos):
        return "sidebar"
    if self.state.mode == "animation" and pygame.Rect(*layout.timeline_splitter_rect).collidepoint(pos):
        return "timeline"
    return None


def _v10_draw_splitters(self) -> None:
    pygame = self.pygame
    assert self.screen is not None
    layout = self._layout()
    side = pygame.Rect(*layout.sidebar_splitter_rect)
    active_side = self.state.ui_drag_splitter == "sidebar" or self.state.ui_hover_splitter == "sidebar"
    pygame.draw.rect(self.screen, (82, 82, 94) if active_side else (50, 50, 58), side)
    pygame.draw.line(self.screen, (24, 24, 28), (side.centerx, side.y + 8), (side.centerx, side.bottom - 8))
    if self.state.mode == "animation":
        time = pygame.Rect(*layout.timeline_splitter_rect)
        active_time = self.state.ui_drag_splitter == "timeline" or self.state.ui_hover_splitter == "timeline"
        pygame.draw.rect(self.screen, (82, 82, 94) if active_time else (50, 50, 58), time)
        pygame.draw.line(self.screen, (24, 24, 28), (time.x + 8, time.centery), (time.right - 8, time.centery))


def _v10_draw(self) -> None:
    pygame = self.pygame
    assert self.screen is not None
    self.screen.fill((31, 31, 34))
    canvas = self._canvas_rect()
    old_clip = self.screen.get_clip()
    self.screen.set_clip(canvas)
    self._draw_grid()
    if self.state.mode == "sprite":
        self._draw_sprite_sheet_mode()
    else:
        self._draw_rig_mode()
    self.screen.set_clip(old_clip)
    if self.state.mode == "animation":
        self._draw_timeline()
    self._draw_sidebar()
    self._draw_splitters()
    self._draw_prompt()
    self._draw_dropdown()
    self._draw_context_menu()
    pygame.display.flip()


def _v10_draw_sidebar(self) -> None:
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    panel = self._sidebar_rect()
    pygame.draw.rect(self.screen, (24, 24, 28), panel)
    pygame.draw.line(self.screen, (64, 64, 72), (panel.x, panel.y), (panel.x, panel.bottom))
    self.sidebar_rows.clear()

    yellow = (255, 220, 80)
    dim = (175, 175, 180)
    bright = (235, 235, 235)

    x = panel.x + 12
    y = 9
    title = f"pyspine v12 [{self.state.mode}] {'*' if self.state.dirty else ''}"
    self.screen.blit(self.font.render(title, True, yellow), (x, y))
    y += 24

    gap = 6
    mode_w = max(76, (panel.w - 32 - 2 * gap) // 3)
    for label, mode, idx in (("Sprite", "sprite", 0), ("Rig", "rig", 1), ("Anim", "animation", 2)):
        r = pygame.Rect(x + idx * (mode_w + gap), y, mode_w, 25)
        self._ui_button(r, label, kind="mode_button", name=mode, active=self.state.mode == mode)
    y += 34

    small_w = max(62, (panel.w - 32 - 3 * gap) // 4)
    for idx, (label, action) in enumerate((("Save", "save"), ("Undo", "undo"), ("Redo", "redo"), ("Fit", "fit"))):
        r = pygame.Rect(x + idx * (small_w + gap), y, small_w, 24)
        self._ui_button(r, label, kind="action_button", name=action)
    y += 31

    if self.state.mode == "animation":
        play_label = "Pause" if self.state.playing else "Play"
        w1 = (panel.w - 32 - 2 * gap) // 3
        for idx, (label, action) in enumerate(((play_label, "play"), ("Onion", "onion"), ("Clip ▾", "clip_dropdown"))):
            r = pygame.Rect(x + idx * (w1 + gap), y, w1, 24)
            self._ui_button(r, label, kind="action_button", name=action, active=(action == "onion" and self.state.onion_skin))
        y += 31

    help_line = "Drag splitters | RMB menu | MMB/RMB-drag pan"
    self.screen.blit(self.font.render(help_line[:58], True, dim), (x, y))
    y += 22

    content_top = y + 3
    content = pygame.Rect(panel.x + 8, content_top, panel.w - 18, max(1, panel.bottom - content_top - 8))
    pygame.draw.rect(self.screen, (20, 20, 24), content)
    pygame.draw.rect(self.screen, (45, 45, 52), content, 1)

    lines = self._sidebar_lines()[4:]
    line_h = 19
    content_h = max(1, len(lines) * line_h + 4)
    self._sidebar_content_h = content_h
    self.state.sidebar_scroll_px = scroll_offset_for_content(self.state.sidebar_scroll_px, content.h, content_h)

    old_clip = self.screen.get_clip()
    self.screen.set_clip(content)
    yy = content.y + 4 - self.state.sidebar_scroll_px
    for item in lines:
        if len(item) == 2:
            line, color = item
            kind = name = None
        else:
            line, color, kind, name = item
        if yy > content.bottom:
            break
        if yy + line_h >= content.y:
            if kind and name:
                row_rect = pygame.Rect(content.x, yy - 1, content.w - 12, line_h)
                if kind == "instance" and name == self.state.sidebar_hover_instance:
                    pygame.draw.rect(self.screen, (48, 72, 56), row_rect)
                elif kind in {"attach_pair", "parent_candidate", "named_pose"}:
                    pygame.draw.rect(self.screen, (30, 34, 40), row_rect)
                self.sidebar_rows.append((row_rect, kind, name))
            surf = self.font.render(str(line)[:max(24, panel.w // 8)], True, color)
            self.screen.blit(surf, (content.x + 7, yy))
        yy += line_h
    self.screen.set_clip(old_clip)

    thumb = scroll_thumb(content.h, content_h, self.state.sidebar_scroll_px)
    if thumb:
        ty, th = thumb
        track = pygame.Rect(content.right - 9, content.y + 3, 5, content.h - 6)
        pygame.draw.rect(self.screen, (42, 42, 48), track, border_radius=3)
        pygame.draw.rect(self.screen, (120, 120, 132), (track.x, track.y + ty, track.w, th), border_radius=3)


def _v10_key_name(self, key) -> str:
    pygame = self.pygame
    names = {
        pygame.K_ESCAPE: "escape",
        pygame.K_RETURN: "return",
        pygame.K_KP_ENTER: "return",
        pygame.K_BACKSPACE: "backspace",
        pygame.K_DELETE: "delete",
        pygame.K_LEFT: "left",
        pygame.K_RIGHT: "right",
        pygame.K_HOME: "home",
        pygame.K_END: "end",
    }
    return names.get(key, "")


def _v10_sync_prompt_input(self) -> None:
    prompt = self.state.text_prompt
    if prompt is None:
        self.prompt_input = None
        self._prompt_id = None
        return
    ident = id(prompt)
    if self._prompt_id != ident or self.prompt_input is None:
        self.prompt_input = TextInput(prompt.text, cursor=len(prompt.text), max_len=96)
        self._prompt_id = ident


def _v10_prompt_key(self, event) -> None:
    pygame = self.pygame
    prompt = self.state.text_prompt
    if prompt is None:
        return
    self._sync_prompt_input()
    assert self.prompt_input is not None
    key_name = self._key_name(event.key)
    ctrl = bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
    result = self.prompt_input.handle_key(key_name, getattr(event, "unicode", ""), ctrl=ctrl)
    prompt.text = self.prompt_input.text
    if result == "cancel":
        self.state.text_prompt = None
        self.prompt_input = None
        self._prompt_id = None
        self.state.message = "cancelled"
    elif result == "commit":
        self._commit_prompt()
        self.prompt_input = None
        self._prompt_id = None


def _v10_draw_prompt(self) -> None:
    if self.state.text_prompt is None:
        return
    self._sync_prompt_input()
    pygame = self.pygame
    assert self.screen is not None and self.font is not None and self.big_font is not None
    assert self.prompt_input is not None
    w, h = self.screen.get_size()
    box_w = min(max(420, w // 2), w - 80)
    box = pygame.Rect((w - box_w) // 2, h // 2 - 48, box_w, 96)
    pygame.draw.rect(self.screen, (10, 10, 14), box, border_radius=6)
    pygame.draw.rect(self.screen, (255, 220, 80), box, 2, border_radius=6)
    prompt = self.state.text_prompt
    title = {
        "rename_sprite": "Rename sprite",
        "rename_point": "Rename attachment point",
        "add_point": "Add attachment point",
        "save_pose": "Save named pose",
    }.get(prompt.purpose, prompt.purpose)
    self.screen.blit(self.big_font.render(title, True, (255, 220, 80)), (box.x + 14, box.y + 12))
    input_rect = pygame.Rect(box.x + 14, box.y + 48, box.w - 28, 32)
    pygame.draw.rect(self.screen, (24, 24, 30), input_rect, border_radius=4)
    pygame.draw.rect(self.screen, (80, 80, 92), input_rect, 1, border_radius=4)
    txt = self.prompt_input.text
    self.screen.blit(self.big_font.render(txt, True, (235, 235, 235)), (input_rect.x + 8, input_rect.y + 5))
    cursor_prefix = txt[: self.prompt_input.cursor]
    cx = input_rect.x + 8 + self.big_font.size(cursor_prefix)[0]
    pygame.draw.line(self.screen, (255, 220, 80), (cx, input_rect.y + 5), (cx, input_rect.bottom - 5), 1)
    hint = "Enter commit | Esc cancel | arrows move cursor"
    self.screen.blit(self.font.render(hint, True, (175, 175, 180)), (input_rect.x, box.bottom - 18))


def _v10_draw_dropdown(self) -> None:
    dd = getattr(self, "dropdown", None)
    if dd is None:
        return
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    rect = pygame.Rect(dd.x, dd.y, dd.width, dd.height())
    pygame.draw.rect(self.screen, (12, 12, 16), rect, border_radius=5)
    pygame.draw.rect(self.screen, (255, 220, 80), rect, 1, border_radius=5)
    y = dd.y + 4
    for label, value in dd.visible_options():
        row = pygame.Rect(dd.x + 4, y, dd.width - 8, dd.row_h)
        active = value == self.state.current_clip
        if active:
            pygame.draw.rect(self.screen, (58, 58, 68), row, border_radius=3)
        self.screen.blit(self.font.render(label[:28], True, (235, 235, 235)), (row.x + 6, row.y + 4))
        y += dd.row_h
    if len(dd.options) > dd.max_visible:
        thumb = scroll_thumb(dd.max_visible, len(dd.options), dd.scroll, min_thumb=2)
        if thumb:
            ty, th = thumb
            track = pygame.Rect(rect.right - 8, rect.y + 5, 4, rect.h - 10)
            pygame.draw.rect(self.screen, (44, 44, 50), track, border_radius=2)
            # dropdown thumb is in row units; map to pixels.
            max_units = max(1, dd.max_visible - th)
            max_px = max(1, track.h - max(8, th * dd.row_h))
            y_px = int((ty / max_units) * max_px) if max_units else 0
            pygame.draw.rect(self.screen, (120, 120, 132), (track.x, track.y + y_px, track.w, max(8, th * dd.row_h)), border_radius=2)


def _v10_dropdown_rect(self):
    dd = getattr(self, "dropdown", None)
    if dd is None:
        return None
    pygame = self.pygame
    return pygame.Rect(dd.x, dd.y, dd.width, dd.height())


def _v10_menu_click(self, pos) -> bool:
    if self.dropdown is not None:
        value = self.dropdown.hit(pos[0], pos[1])
        if value is not None:
            if value:
                self.state.current_clip = value
                self.state.message = f"clip {value}"
            self.dropdown = None
            return True
        if self._dropdown_rect() and self._dropdown_rect().collidepoint(pos):
            return True
        self.dropdown = None
    if self.context_menu is not None:
        item = self.context_menu.hit(pos[0], pos[1])
        if item is not None:
            self._ui_action(item.action)
            return True
        self.context_menu = None
    return False


def _v10_events(self) -> bool:
    pygame = self.pygame
    assert self.screen is not None
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if self.state.text_prompt is not None:
            if event.type == pygame.KEYDOWN:
                self._prompt_key(event)
            continue
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.context_menu or self.dropdown:
                    self.context_menu = None; self.dropdown = None
                    continue
                return False
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            shift = bool(mods & pygame.KMOD_SHIFT)
            if ctrl and event.key == pygame.K_s:
                self._save()
            elif ctrl and event.key == pygame.K_z:
                self.state.undo(); self.sprite_cache.clear()
            elif ctrl and event.key == pygame.K_y:
                self.state.redo(); self.sprite_cache.clear()
            elif ctrl and event.key == pygame.K_c:
                if shift and self.state.mode == "animation":
                    self.tool.copy_frame_keyframes(self.state, selected_only=False)
                else:
                    self.tool.copy_pose(self.state, selected_only=not shift)
            elif ctrl and event.key == pygame.K_v:
                if shift and self.state.mode == "animation":
                    self.tool.paste_frame_keyframes(self.state)
                else:
                    self.tool.paste_pose(self.state)
            elif event.key == pygame.K_SPACE:
                self.state.playing = not self.state.playing
            elif event.key == pygame.K_1:
                self.state.mode = "sprite"; self.state.message = "Sprite Sheet Mode"
            elif event.key == pygame.K_2:
                self.state.mode = "rig"; self.state.message = "Rig Mode"
            elif event.key == pygame.K_3:
                self.state.mode = "animation"; self.state.message = "Animation Mode"
            elif event.key == pygame.K_F2:
                self.tool.prompt_rename(self.state)
            elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE) and not ctrl:
                if self.state.mode == "animation" and self.state.selected_key_instance:
                    self.tool.delete_keyframe(self.state)
                else:
                    self.tool.delete_selected(self.state)
                self.sprite_cache.clear()
            elif event.key == pygame.K_a and self.state.mode == "sprite":
                self.tool.add_point_at_mouse(self.state)
            elif event.key == pygame.K_i:
                self.tool.add_instance(self.state, self.state.last_mouse_world)
            elif event.key == pygame.K_u and self.state.mode == "rig":
                self.tool.reparent_selected_to_hover(self.state, None)
            elif event.key == pygame.K_p and self.state.mode == "rig":
                parent = self._instance_under_mouse(exclude=self.state.selected)
                if parent:
                    self.tool.reparent_selected_to_hover(self.state, parent)
            elif event.key == pygame.K_c and self.state.mode == "rig" and not ctrl:
                self.tool.cycle_attachment_pair(self.state, -1 if shift else 1)
            elif event.key == pygame.K_k and self.state.mode == "animation":
                if shift:
                    self.tool.set_pose_keyframes(self.state, selected_only=False)
                else:
                    self.tool.set_keyframe(self.state)
            elif event.key == pygame.K_j and self.state.mode == "animation":
                self.tool.set_pose_keyframes(self.state, selected_only=True)
            elif event.key == pygame.K_t and self.state.mode == "animation":
                self.tool.toggle_interpolation(self.state)
            elif event.key == pygame.K_o and self.state.mode == "animation":
                self.state.onion_skin = not self.state.onion_skin
                self.state.message = "onion skin " + ("on" if self.state.onion_skin else "off")
            elif event.key == pygame.K_f and self.state.mode == "animation":
                if shift:
                    self.tool.paste_frame_keyframes(self.state)
                else:
                    self.tool.copy_frame_keyframes(self.state, selected_only=bool(ctrl and self.state.selected))
            elif event.key == pygame.K_m and self.state.mode == "animation":
                self.tool.mirror_pose_keyframes(self.state)
            elif event.key == pygame.K_x and self.state.mode == "animation":
                self.tool.reset_pose_keyframes(self.state, selected_only=shift)
            elif event.key == pygame.K_n and self.state.mode == "animation":
                self.state.text_prompt = TextPrompt("save_pose", "pose", {})
                self.state.message = "type pose name and press Enter"
            elif event.key in (pygame.K_LEFTBRACKET, pygame.K_COMMA):
                self.tool.rotate_selected(self.state, -5.0 if not shift else -1.0)
            elif event.key in (pygame.K_RIGHTBRACKET, pygame.K_PERIOD):
                self.tool.rotate_selected(self.state, 5.0 if not shift else 1.0)
            elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                self.tool.adjust_z(self.state, 1)
            elif event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE):
                self.tool.adjust_z(self.state, -1)
            elif event.key == pygame.K_LEFT:
                self.state.frame = max(0.0, self.state.frame - (10.0 if shift else 1.0))
            elif event.key == pygame.K_RIGHT:
                self.state.frame += 10.0 if shift else 1.0
            elif event.key == pygame.K_HOME:
                self.state.frame = 0.0
            elif event.key == pygame.K_END and self.state.current_clip:
                self.state.frame = self.state.project.clips[self.state.current_clip].length
            elif event.key == pygame.K_TAB:
                self._cycle_selection(reverse=shift)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            pos = Vec2(*event.pos)
            world = self.state.viewport.screen_to_world(pos)
            self.state.last_mouse_world = world
            if event.button == 1:
                split = self._splitter_hit(event.pos)
                if split:
                    self.state.ui_drag_splitter = split
                    self.context_menu = None; self.dropdown = None
                    continue
                if self._menu_click(event.pos):
                    continue
                hit = self._sidebar_hit(event.pos)
                if hit:
                    kind, name = hit
                    if kind == "instance" and self.state.mode != "sprite":
                        self.state.sidebar_drag_instance = name
                        self.state.sidebar_hover_instance = None
                    self._sidebar_click_hit(kind, name)
                elif self.state.mode == "animation" and self._timeline_contains(event.pos):
                    self._timeline_mouse_down(event.pos)
                elif self._canvas_rect().collidepoint(event.pos):
                    self.tool.click(self.state, world, modifiers=pygame.key.get_mods())
            elif event.button == 2:
                self._right_down_pos = event.pos
                self._right_panning = True
            elif event.button == 3:
                self._right_down_pos = event.pos
                self._right_panning = False
            elif event.button in (4, 5):
                delta = -1 if event.button == 4 else 1
                dd_rect = self._dropdown_rect()
                if self.dropdown is not None and dd_rect is not None and dd_rect.collidepoint(event.pos):
                    self.dropdown.scroll_by(delta)
                elif self._sidebar_rect().collidepoint(event.pos):
                    self.state.sidebar_scroll_px = scroll_offset_for_content(
                        self.state.sidebar_scroll_px + delta * 57,
                        max(1, self._sidebar_rect().h - 150),
                        max(1, getattr(self, "_sidebar_content_h", 1)),
                    )
                elif self.state.mode == "animation" and self._timeline_contains(event.pos):
                    self.state.timeline_scroll = max(0, self.state.timeline_scroll + delta * 3)
                elif self._canvas_rect().collidepoint(event.pos):
                    self.state.viewport.zoom_at(pos, 1.1 if event.button == 4 else 1.0 / 1.1)
        elif event.type == pygame.MOUSEMOTION:
            pos = Vec2(*event.pos)
            world = self.state.viewport.screen_to_world(pos)
            self.state.last_mouse_world = world
            self.state.ui_hover_splitter = self._splitter_hit(event.pos)
            if event.buttons[0]:
                if self.state.ui_drag_splitter == "sidebar":
                    self.state.ui_sidebar_w = resize_sidebar_from_mouse(self.screen.get_width(), event.pos[0])
                    self.state.message = f"sidebar {self.state.ui_sidebar_w}px"
                elif self.state.ui_drag_splitter == "timeline":
                    self.state.ui_timeline_h = resize_timeline_from_mouse(self.screen.get_height(), event.pos[1])
                    self.state.message = f"timeline {self.state.ui_timeline_h}px"
                elif self.state.timeline_drag_key:
                    frame = self._timeline_frame_from_pos(event.pos)
                    self.state.frame = frame
                    inst, channel, old = self.state.timeline_drag_key
                    self.state.message = f"move key {inst}.{channel} {old:.0f} -> {frame:.0f}"
                elif self.state.sidebar_drag_instance:
                    hit = self._sidebar_hit(event.pos)
                    self.state.sidebar_hover_instance = hit[1] if hit and hit[0] == "instance" else None
                elif self._canvas_rect().collidepoint(event.pos) and not (self.state.mode == "animation" and self._timeline_contains(event.pos)):
                    self.tool.drag_to(self.state, world)
                    if self.tool.drag and self.tool.drag.kind in {"point"}:
                        self.sprite_cache.clear()
            elif event.buttons[1] or event.buttons[2]:
                if event.buttons[2] and self._right_down_pos:
                    if abs(event.pos[0] - self._right_down_pos[0]) + abs(event.pos[1] - self._right_down_pos[1]) > 5:
                        self._right_panning = True
                        self.context_menu = None
                        self.dropdown = None
                if self._canvas_rect().collidepoint(event.pos):
                    self.state.viewport.pan(event.rel[0], event.rel[1])
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                if self.state.ui_drag_splitter:
                    self.state.ui_drag_splitter = None
                elif self.state.timeline_drag_key:
                    self._timeline_mouse_up(event.pos)
                elif self.state.sidebar_drag_instance:
                    self._sidebar_mouse_up(event.pos)
                else:
                    self.tool.release(self.state)
                self.sprite_cache.clear()
            elif event.button == 3:
                if not self._right_panning:
                    self._show_context_menu(event.pos)
                self._right_down_pos = None
                self._right_panning = False
            elif event.button == 2:
                self._right_down_pos = None
                self._right_panning = False
    return True


EditorApp.__init__ = _v10_init
EditorApp._layout = _v10_layout
EditorApp._splitter_hit = _v10_splitter_hit
EditorApp._draw_splitters = _v10_draw_splitters
EditorApp._draw = _v10_draw
EditorApp._draw_sidebar = _v10_draw_sidebar
EditorApp._key_name = _v10_key_name
EditorApp._sync_prompt_input = _v10_sync_prompt_input
EditorApp._prompt_key = _v10_prompt_key
EditorApp._draw_prompt = _v10_draw_prompt
EditorApp._draw_dropdown = _v10_draw_dropdown
EditorApp._dropdown_rect = _v10_dropdown_rect
EditorApp._menu_click = _v10_menu_click
EditorApp._events = _v10_events

# ---------------------------------------------------------------------------
# v12 production workflow: better transform tools, property inspector editing,
# timeline batch operations, pose library polish, and safer file workflow.
# ---------------------------------------------------------------------------
from pathlib import Path as _PathV12  # noqa: E402
from pyspine.core.commands import SetInstanceFields  # noqa: E402
from pyspine.editor.workflow import (  # noqa: E402
    add_recent_file,
    autosave,
    clear_channel,
    clear_instance_keys,
    clear_pose_at_frame,
    delete_frame_range,
    descendant_chain,
    duplicate_keys,
    insert_frame_range,
    key_refs_in_box,
    missing_images,
    pose_to_keyframes,
    select_child,
    select_parent,
    validate_before_export,
)

_v10_save_for_v12 = EditorApp._save
_v10_update_for_v12 = EditorApp._update
_v10_commit_prompt_for_v12 = EditorApp._commit_prompt
_v10_sidebar_click_hit_for_v12 = EditorApp._sidebar_click_hit
_v10_menu_click_for_v12 = EditorApp._menu_click
_v10_events_for_v12 = EditorApp._events
_v10_context_items_for_v12 = EditorApp._context_items
_v10_ui_action_for_v12 = EditorApp._ui_action
_v10_init_for_v12b = EditorApp.__init__


def _v12_init(self, path):
    _v10_init_for_v12b(self, path)
    self.dropdown_purpose = None
    self._v12_last_save_backup = None


def _v12_save(self) -> None:
    from pyspine.editor.workflow import save_with_backup
    backup = save_with_backup(self.state.project, self.path)
    self._v12_last_save_backup = backup
    self.state.dirty = False
    self.state.autosave_elapsed = 0.0
    try:
        add_recent_file(self.path.parent / ".pyspine", self.path)
    except Exception:
        pass
    if backup:
        self.state.message = f"saved {self.path.name}; backup {backup.name}"
    else:
        self.state.message = f"saved {self.path.name}"


def _v12_update(self, dt: float) -> None:
    _v10_update_for_v12(self, dt)
    if self.state.dirty and self.state.path:
        self.state.autosave_elapsed += dt
        if self.state.autosave_elapsed >= self.state.autosave_seconds:
            try:
                out = autosave(self.state.project, self.state.path)
                self.state.autosave_elapsed = 0.0
                self.state.message = f"autosaved {out.name}"
            except Exception as exc:
                self.state.message = f"autosave failed: {exc}"


def _v12_current_keyrefs(self):
    from pyspine.editor.workflow import KeyRef
    return [KeyRef(a, b, c) for a, b, c in self.state.selected_keys]


def _v12_select_key_box(self, start_pos, end_pos) -> None:
    if not self.state.current_clip or self.state.current_clip not in self.state.project.clips:
        return
    row1 = self._timeline_row_from_pos(start_pos)
    row2 = self._timeline_row_from_pos(end_pos)
    if row1 is None or row2 is None:
        return
    rows_all = timeline_rows(self.state.project, self.state.project.clips[self.state.current_clip])
    try:
        i1 = rows_all.index(row1); i2 = rows_all.index(row2)
    except ValueError:
        return
    lo, hi = sorted((i1, i2))
    rows = [(r.instance, r.channel) for r in rows_all[lo:hi+1]]
    f0 = self._timeline_frame_from_pos(start_pos)
    f1 = self._timeline_frame_from_pos(end_pos)
    refs = key_refs_in_box(self.state.project, self.state.current_clip, rows, f0, f1)
    self.state.selected_keys = [(r.instance, r.channel, r.frame) for r in refs]
    self.state.message = f"selected {len(refs)} key(s)"


def _v12_prompt_property(self, field: str) -> None:
    inst_name = self.state.selected
    if not inst_name or inst_name not in self.state.project.rig.instances:
        return
    inst = self.state.project.rig.instances[inst_name]
    value = getattr(inst, field)
    self.state.text_prompt = TextPrompt("set_instance_field", str(value), {"instance": inst_name, "field": field})
    self.state.message = f"edit {inst_name}.{field}"


def _v12_open_property_dropdown(self, field: str) -> None:
    if not self.state.selected or self.state.selected not in self.state.project.rig.instances:
        return
    pygame = self.pygame
    panel = self._sidebar_rect()
    inst = self.state.project.rig.instances[self.state.selected]
    options = []
    if field == "sprite":
        options = [(name, name) for name in sorted(self.state.project.sheet.sprites)]
    elif field == "self_point":
        sprite = self.state.project.sheet.sprites[inst.sprite]
        options = [(name, name) for name in sorted(sprite.points)]
    elif field == "parent_point" and inst.parent:
        parent = self.state.project.rig.instances[inst.parent]
        sprite = self.state.project.sheet.sprites[parent.sprite]
        options = [(name, name) for name in sorted(sprite.points)]
    if not options:
        self.state.message = f"no options for {field}"
        return
    self.dropdown = Dropdown(panel.x + 16, 126, max(220, panel.w - 32), options)
    self.dropdown_purpose = ("instance_field", self.state.selected, field)
    self.context_menu = None


def _v12_menu_click(self, pos) -> bool:
    if self.dropdown is not None and self.dropdown_purpose:
        value = self.dropdown.hit(pos[0], pos[1])
        if value is not None:
            purpose = self.dropdown_purpose
            self.dropdown = None
            self.dropdown_purpose = None
            if purpose[0] == "clip":
                if value == "__new_clip__":
                    base = f"clip_{len(self.state.project.clips) + 1:02d}"
                    self.state.text_prompt = TextPrompt("new_clip", base, {})
                    self.state.message = "type new clip name and press Enter"
                elif value:
                    self.state.current_clip = value
                    self.state.frame = max(0.0, min(self.state.frame, self.state.project.clips[value].length))
                    self.state.message = f"clip {value}"
                else:
                    self.state.message = "no clips yet"
                return True
            if purpose[0] == "instance_field":
                inst_name, field = purpose[1], purpose[2]
                if inst_name in self.state.project.rig.instances:
                    inst = self.state.project.rig.instances[inst_name]
                    before = {field: getattr(inst, field)}
                    after = {field: value}
                    if field == "sprite":
                        # Preserve a valid self point when switching sprites.
                        sprite = self.state.project.sheet.sprites[value]
                        if inst.self_point not in sprite.points:
                            before["self_point"] = inst.self_point
                            after["self_point"] = "origin" if "origin" in sprite.points else next(iter(sprite.points))
                    self.state.run_command(SetInstanceFields(inst_name, before, after, label="Set inspector field"))
                    self.sprite_cache.clear()
            return True
        if self._dropdown_rect() and self._dropdown_rect().collidepoint(pos):
            return True
        self.dropdown = None
        self.dropdown_purpose = None
    return _v10_menu_click_for_v12(self, pos)


def _v12_commit_prompt(self) -> None:
    prompt = self.state.text_prompt
    if prompt is None:
        return
    if prompt.purpose == "set_instance_field":
        text = prompt.text.strip()
        self.state.text_prompt = None
        inst_name = str(prompt.payload["instance"])
        field = str(prompt.payload["field"])
        if not text or inst_name not in self.state.project.rig.instances:
            return
        inst = self.state.project.rig.instances[inst_name]
        try:
            if field == "z":
                value = int(float(text))
            elif field in {"x", "y", "rotation", "local_rotation", "scale_x", "scale_y"}:
                value = float(text)
            elif field in {"visible", "locked"}:
                value = text.lower() in {"1", "true", "yes", "on"}
            else:
                value = text
            self.state.run_command(SetInstanceFields(inst_name, {field: getattr(inst, field)}, {field: value}, label="Set inspector value"))
        except Exception as exc:
            self.state.message = f"invalid {field}: {exc}"
        return
    if prompt.purpose == "repair_image":
        text = prompt.text.strip()
        self.state.text_prompt = None
        if text:
            self.state.project.sheet.image = text
            self.state.dirty = True
            self._load_sheet_surface()
        return
    if prompt.purpose == "new_clip":
        text = prompt.text.strip()
        self.state.text_prompt = None
        if not text:
            self.state.message = "empty clip name ignored"
            return
        name = text
        n = 2
        while name in self.state.project.clips:
            name = f"{text}_{n}"
            n += 1
        self.state.project.clips[name] = Clip(name=name, length=24.0, fps=24.0, loop=True)
        self.state.current_clip = name
        self.state.mode = "animation"
        self.state.frame = 0.0
        self.state.dirty = True
        self.state.message = f"created clip {name}"
        return
    return _v10_commit_prompt_for_v12(self)


def _v12_sidebar_click_hit(self, kind: str, name: str) -> bool:
    if kind == "prop_edit":
        self._prompt_property(name)
        return True
    if kind == "prop_toggle":
        if self.state.selected and self.state.selected in self.state.project.rig.instances:
            inst = self.state.project.rig.instances[self.state.selected]
            before = {name: getattr(inst, name)}
            after = {name: not bool(getattr(inst, name))}
            self.state.run_command(SetInstanceFields(inst.name, before, after, label=f"Toggle {name}"))
        return True
    if kind == "prop_dropdown":
        self._open_property_dropdown(name)
        return True
    return _v10_sidebar_click_hit_for_v12(self, kind, name)


def _v12_inspector_sidebar_rows(self, bright, yellow, blue, dim, green) -> list[tuple]:
    s = self.state
    rows: list[tuple] = [("", dim), ("Inspector:", blue)]
    if not s.selected or s.selected not in s.project.rig.instances:
        rows.append(("  select an instance", dim))
        return rows
    inst = s.project.rig.instances[s.selected]
    rows += [
        (f"  instance: {inst.name}", bright),
        (f"  sprite:   {inst.sprite}  ▾", bright, "prop_dropdown", "sprite"),
        (f"  parent:   {inst.parent or 'root'}", bright),
        (f"  self pt:  {inst.self_point}  ▾", bright, "prop_dropdown", "self_point"),
        (f"  parent pt:{inst.parent_point or '-'}  ▾", bright if inst.parent else dim, "prop_dropdown", "parent_point"),
        (f"  x:        {inst.x:.2f}", bright if inst.parent is None else dim, "prop_edit", "x"),
        (f"  y:        {inst.y:.2f}", bright if inst.parent is None else dim, "prop_edit", "y"),
        (f"  rot:      {inst.rotation:.2f}", bright, "prop_edit", "rotation"),
        (f"  local:    {inst.local_rotation:.2f}", bright, "prop_edit", "local_rotation"),
        (f"  scale x:  {inst.scale_x:.3f}", bright, "prop_edit", "scale_x"),
        (f"  scale y:  {inst.scale_y:.3f}", bright, "prop_edit", "scale_y"),
        (f"  z:        {inst.z}", bright, "prop_edit", "z"),
        (f"  visible:  {'yes' if inst.visible else 'no'}", green if inst.visible else dim, "prop_toggle", "visible"),
        (f"  locked:   {'yes' if inst.locked else 'no'}", yellow if inst.locked else dim, "prop_toggle", "locked"),
    ]
    rows += [("", dim), ("Attachment pairs:", blue)]
    if inst.parent:
        pairs = matching_attachment_candidates(s.project, inst.name, inst.parent)
        if not pairs:
            rows.append(("  no matching named points", dim))
        for cand in pairs:
            active = cand.parent_point == inst.parent_point and cand.self_point == inst.self_point
            prefix = "> " if active else "  "
            payload = f"{cand.parent_point}|{cand.self_point}"
            rows.append((prefix + cand.label, yellow if active else green, "attach_pair", payload))
    else:
        rows.append(("  root instance", dim))
    rows += [("", dim), ("Compatible parents:", blue)]
    shown = 0
    for parent_name, pairs in parent_candidates(s.project, inst.name):
        if parent_name == inst.parent:
            continue
        first = pairs[0]
        payload = f"{parent_name}|{first.parent_point}|{first.self_point}"
        rows.append((f"  {parent_name}: {first.label}", green, "parent_candidate", payload))
        shown += 1
        if shown >= 6:
            rows.append(("  ...", dim)); break
    if shown == 0:
        rows.append(("  none", dim))
    return rows


def _v12_context_items(self):
    items = _v10_context_items_for_v12(self)
    s = self.state
    if s.mode in {"rig", "animation"} and s.selected:
        inst = s.project.rig.instances.get(s.selected)
        if inst:
            items.insert(0, MenuItem("Unlock selected" if inst.locked else "Lock selected", "toggle_lock"))
            items.insert(1, MenuItem("Show selected" if not inst.visible else "Hide selected", "toggle_visible"))
            items.append(MenuItem("Select parent", "select_parent", bool(inst.parent)))
            items.append(MenuItem("Select first child", "select_child", bool(select_child(s.project, s.selected))))
    if s.mode == "animation":
        items += [
            MenuItem("IK selected chain to mouse", "ik_to_mouse", bool(s.selected)),
            MenuItem("Foot/hand lock selected 6f", "foot_lock", bool(s.selected)),
            MenuItem("Detect planted ranges", "detect_plants", bool(s.selected)),
            MenuItem("Duplicate selected keys", "duplicate_keys", bool(s.selected_keys or s.selected_key_instance)),
            MenuItem("Insert 6 frames here", "insert_frames"),
            MenuItem("Delete 6-frame range here", "delete_frames"),
            MenuItem("Clear selected channel", "clear_channel", bool(s.selected_key_instance and s.selected_key_channel)),
            MenuItem("Clear pose at frame", "clear_pose"),
            MenuItem("Clear selected part", "clear_part", bool(s.selected)),
        ]
    return items


def _v12_ui_action(self, action: str) -> None:
    if action == "toggle_lock":
        self.tool.toggle_locked(self.state)
    elif action == "toggle_visible":
        self.tool.toggle_visible(self.state)
    elif action == "select_parent":
        p = select_parent(self.state.project, self.state.selected)
        if p:
            self.state.selected = p
    elif action == "select_child":
        c = select_child(self.state.project, self.state.selected)
        if c:
            self.state.selected = c
    elif action == "duplicate_keys":
        self._v12_duplicate_selected_keys()
    elif action == "insert_frames":
        self._v12_insert_frames(6)
    elif action == "delete_frames":
        self._v12_delete_frames(6)
    elif action == "clear_channel":
        self._v12_clear_channel()
    elif action == "clear_pose":
        self._v12_clear_pose()
    elif action == "clear_part":
        self._v12_clear_part()
    elif action == "repair_image":
        self.state.text_prompt = TextPrompt("repair_image", self.state.project.sheet.image or "", {})
    elif action == "ik_to_mouse":
        self._v13_apply_ik_to_mouse()
    elif action == "foot_lock":
        self._v13_foot_lock_selected(frames=6.0)
    elif action == "detect_plants":
        self._v13_detect_plants_selected()
    else:
        _v10_ui_action_for_v12(self, action)
        return
    self.context_menu = None
    self.dropdown = None


def _v12_duplicate_selected_keys(self):
    if not self.state.current_clip:
        return
    refs = self._v12_current_keyrefs()
    if not refs and self.state.selected_key_instance and self.state.selected_key_channel and self.state.selected_key_frame is not None:
        from pyspine.editor.workflow import KeyRef
        refs = [KeyRef(self.state.selected_key_instance, self.state.selected_key_channel, self.state.selected_key_frame)]
    if refs:
        self.state.run_command(duplicate_keys(self.state.project, self.state.current_clip, refs, offset=1.0))


def _v12_insert_frames(self, length: float):
    if self.state.current_clip:
        self.state.run_command(insert_frame_range(self.state.project, self.state.current_clip, self.state.frame, length))


def _v12_delete_frames(self, length: float):
    if self.state.current_clip:
        self.state.run_command(delete_frame_range(self.state.project, self.state.current_clip, self.state.frame, self.state.frame + length))


def _v12_clear_channel(self):
    if self.state.current_clip and self.state.selected_key_instance and self.state.selected_key_channel:
        self.state.run_command(clear_channel(self.state.project, self.state.current_clip, self.state.selected_key_instance, self.state.selected_key_channel))


def _v12_clear_pose(self):
    if self.state.current_clip:
        self.state.run_command(clear_pose_at_frame(self.state.project, self.state.current_clip, self.state.frame))


def _v12_clear_part(self):
    if self.state.current_clip and self.state.selected:
        self.state.run_command(clear_instance_keys(self.state.project, self.state.current_clip, self.state.selected))


def _v12_events(self) -> bool:
    # Most v12 UI uses v10 routing.  This pre-pass handles new global hotkeys;
    # all mouse routing/dropdowns/text prompts remain in the verified v10 loop.
    pygame = self.pygame
    queued = []
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and self.state.text_prompt is None:
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            shift = bool(mods & pygame.KMOD_SHIFT)
            if event.key == pygame.K_l and self.state.selected:
                self.tool.toggle_locked(self.state); continue
            if event.key == pygame.K_v and self.state.selected:
                self.tool.toggle_visible(self.state); continue
            if event.key == pygame.K_PAGEUP:
                p = select_parent(self.state.project, self.state.selected)
                if p: self.state.selected = p; self.state.message = f"selected parent {p}"
                continue
            if event.key == pygame.K_PAGEDOWN:
                c = select_child(self.state.project, self.state.selected)
                if c: self.state.selected = c; self.state.message = f"selected child {c}"
                continue
            if self.state.mode == "animation" and ctrl and event.key == pygame.K_d:
                self._v12_duplicate_selected_keys(); continue
            if self.state.mode == "animation" and ctrl and event.key == pygame.K_i:
                self._v12_insert_frames(6); continue
            if self.state.mode == "animation" and ctrl and event.key == pygame.K_BACKSPACE:
                self._v12_delete_frames(6); continue
        queued.append(event)
    # Push non-v12 events back onto pygame's queue and let the existing routing handle them.
    for event in queued:
        pygame.event.post(event)
    return _v10_events_for_v12(self)


# Patch timeline mouse methods for multi-key selection via Shift-drag rectangle.
_v8_timeline_mouse_down_for_v12 = EditorApp._timeline_mouse_down
_v8_timeline_mouse_up_for_v12 = EditorApp._timeline_mouse_up


def _v12_timeline_mouse_down(self, pos) -> None:
    mods = self.pygame.key.get_mods()
    if mods & self.pygame.KMOD_SHIFT:
        self.state.key_box_start = pos
        self.state.key_box_current = pos
        self.state.message = "box-select keyframes"
        return
    _v8_timeline_mouse_down_for_v12(self, pos)
    if self.state.selected_key_instance and self.state.selected_key_channel and self.state.selected_key_frame is not None:
        self.state.selected_keys = [(self.state.selected_key_instance, self.state.selected_key_channel, self.state.selected_key_frame)]


def _v12_timeline_mouse_up(self, pos) -> None:
    if self.state.key_box_start:
        self.state.key_box_current = pos
        self._v12_select_key_box(self.state.key_box_start, pos)
        self.state.key_box_start = None
        self.state.key_box_current = None
        return
    _v8_timeline_mouse_up_for_v12(self, pos)


EditorApp.__init__ = _v12_init
EditorApp._save = _v12_save
EditorApp._update = _v12_update
EditorApp._commit_prompt = _v12_commit_prompt
EditorApp._menu_click = _v12_menu_click
EditorApp._sidebar_click_hit = _v12_sidebar_click_hit
EditorApp._inspector_sidebar_rows = _v12_inspector_sidebar_rows
EditorApp._context_items = _v12_context_items
EditorApp._ui_action = _v12_ui_action
EditorApp._v12_current_keyrefs = _v12_current_keyrefs
EditorApp._v12_select_key_box = _v12_select_key_box
EditorApp._prompt_property = _v12_prompt_property
EditorApp._open_property_dropdown = _v12_open_property_dropdown
EditorApp._v12_duplicate_selected_keys = _v12_duplicate_selected_keys
EditorApp._v12_insert_frames = _v12_insert_frames
EditorApp._v12_delete_frames = _v12_delete_frames
EditorApp._v12_clear_channel = _v12_clear_channel
EditorApp._v12_clear_pose = _v12_clear_pose
EditorApp._v12_clear_part = _v12_clear_part
EditorApp._events = _v12_events
EditorApp._timeline_mouse_down = _v12_timeline_mouse_down
EditorApp._timeline_mouse_up = _v12_timeline_mouse_up

# ---- v13 animation-quality overlays / hotkeys ---------------------------------
from pyspine.core.commands import SetInterpolation as _V13SetInterpolation
from pyspine.core.easing import normalize_easing as _v13_normalize_easing
from pyspine.core.motion import motion_arc as _v13_motion_arc
from pyspine.editor.animation_quality import OnionSkinSettings as _V13OnionSkinSettings

_v12_draw_rig_mode_for_v13 = EditorApp._draw_rig_mode
_v12_events_for_v13 = EditorApp._events


def _v13_draw_motion_arc(self, poses) -> None:
    if self.state.mode != "animation" or not self.state.current_clip or not self.state.selected:
        return
    if self.state.current_clip not in self.state.project.clips:
        return
    if self.state.selected not in self.state.project.rig.instances:
        return
    pygame = self.pygame
    assert self.screen is not None
    clip = self.state.project.clips[self.state.current_clip]
    inst = self.state.project.rig.instances[self.state.selected]
    try:
        pts = _v13_motion_arc(self.state.project, clip, self.state.selected, point=inst.self_point, start=0, end=clip.length, step=max(1.0, clip.fps / 12.0))
    except Exception:
        return
    if len(pts) < 2:
        return
    screen_pts = [self.state.viewport.world_to_screen(p.point).as_tuple() for p in pts]
    pygame.draw.lines(self.screen, (130, 190, 255), False, screen_pts, 1)
    for p in pts:
        s = self.state.viewport.world_to_screen(p.point)
        pygame.draw.circle(self.screen, (130, 190, 255), (int(s.x), int(s.y)), 2)


def _v13_draw_rig_mode(self) -> None:
    if self.state.mode == "animation" and self.state.onion_skin and self.state.current_clip:
        clip = self.state.project.clips[self.state.current_clip]
        settings = _V13OnionSkinSettings.from_metadata(self.state.project.metadata)
        if settings.loop is False:
            settings = _V13OnionSkinSettings(settings.before, settings.after, settings.step, settings.base_alpha, settings.falloff, clip.loop)
        for onion in settings.frames(self.state.frame, clip.length):
            self._draw_rig(solve_clip_pose(self.state.project, clip, onion.frame), ghost=True)
    poses = self._current_pose()
    self._draw_rig(poses)
    self._v13_draw_motion_arc(poses)
    self._draw_rig_handles(poses)
    self._draw_snap_preview(poses)


def _v13_selected_channel(self):
    if not self.state.selected or self.state.selected not in self.state.project.rig.instances:
        return None
    inst = self.state.project.rig.instances[self.state.selected]
    return "rotation" if inst.parent is None else "local_rotation"


def _v13_cycle_selected_easing(self) -> None:
    if self.state.mode != "animation" or not self.state.selected:
        return
    clip_name = self.state.current_clip or "anim"
    channel = self._v13_selected_channel()
    if not channel:
        return
    modes = ["linear", "ease_in", "ease_out", "ease_in_out", "smoothstep", "smootherstep", "step"]
    clip = self.state.project.clips.get(clip_name)
    before = "linear"
    if clip and self.state.selected in clip.tracks:
        before = clip.tracks[self.state.selected].interpolation.get(channel, "linear")
    before = _v13_normalize_easing(before)
    after = modes[(modes.index(before) + 1) % len(modes)] if before in modes else "linear"
    if self.state.run_command(_V13SetInterpolation(clip_name, self.state.selected, channel, before, after)):
        self.state.current_clip = clip_name
        self.state.message = f"{self.state.selected}.{channel} easing = {after}"


def _v13_adjust_onion(self, *, count_delta: int = 0, step_delta: float = 0.0) -> None:
    s = _V13OnionSkinSettings.from_metadata(self.state.project.metadata)
    if count_delta:
        s = _V13OnionSkinSettings(max(0, s.before + count_delta), max(0, s.after + count_delta), s.step, s.base_alpha, s.falloff, s.loop)
    if step_delta:
        s = _V13OnionSkinSettings(s.before, s.after, max(1.0, s.step + step_delta), s.base_alpha, s.falloff, s.loop)
    self.state.project.metadata["onion_skin"] = s.to_metadata()
    self.state.dirty = True
    self.state.message = f"onion before/after={s.before}/{s.after} step={s.step:g}"


def _v13_events(self) -> bool:
    pygame = self.pygame
    queued = []
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and self.state.text_prompt is None:
            mods = pygame.key.get_mods()
            shift = bool(mods & pygame.KMOD_SHIFT)
            alt = bool(mods & pygame.KMOD_ALT)
            if self.state.mode == "animation" and shift and event.key == pygame.K_t:
                self._v13_cycle_selected_easing(); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_UP:
                self._v13_adjust_onion(count_delta=1); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_DOWN:
                self._v13_adjust_onion(count_delta=-1); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_RIGHT:
                self._v13_adjust_onion(step_delta=1.0); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_LEFT:
                self._v13_adjust_onion(step_delta=-1.0); continue
            if self.state.mode == "animation" and event.key == pygame.K_y:
                self._v13_apply_ik_to_mouse(bend_override=(-1 if shift else None)); continue
            if self.state.mode == "animation" and event.key == pygame.K_b:
                self._v13_foot_lock_selected(frames=(12.0 if shift else 6.0)); continue
            if self.state.mode == "animation" and event.key == pygame.K_g:
                self._v13_detect_plants_selected(); continue
        queued.append(event)
    for event in queued:
        pygame.event.post(event)
    return _v12_events_for_v13(self)



def _v13_find_two_bone_chain(self):
    """Return (upper, lower, end_point, bend) for a practical selected chain."""
    s = self.state
    if not s.selected or s.selected not in s.project.rig.instances:
        return None
    selected = s.selected
    inst = s.project.rig.instances[selected]
    children = [i.name for i in s.project.rig.instances.values() if i.parent == selected]
    if children:
        upper_name = selected
        # Prefer a child with a second named endpoint, otherwise use first child.
        lower_name = children[0]
        for child_name in children:
            child = s.project.rig.instances[child_name]
            sprite = s.project.sheet.sprites[child.sprite]
            candidates = [p for p in sprite.points if p not in {"origin", child.self_point, child.parent_point}]
            if candidates:
                lower_name = child_name
                break
    elif inst.parent:
        upper_name = inst.parent
        lower_name = selected
    else:
        return None
    lower = s.project.rig.instances[lower_name]
    lower_sprite = s.project.sheet.sprites[lower.sprite]
    candidates = [p for p in lower_sprite.points if p not in {"origin", lower.self_point, lower.parent_point}]
    if not candidates:
        # Hands/feet often only have a wrist/ankle plus origin. Fall back to origin.
        candidates = [p for p in lower_sprite.points if p != lower.self_point]
    if not candidates:
        return None
    preferred_suffixes = ("wrist", "ankle", "kneelower", "hand", "foot")
    end_point = candidates[0]
    for point in candidates:
        if any(point.endswith(suf) or suf in point for suf in preferred_suffixes):
            end_point = point
            break
    bend = -1 if "left" in upper_name or "left" in lower_name else 1
    return upper_name, lower_name, end_point, bend


def _v13_apply_ik_to_mouse(self, *, bend_override: int | None = None) -> None:
    if self.state.mode != "animation":
        self.state.message = "switch to Animation mode for IK"
        return
    chain = self._v13_find_two_bone_chain()
    if not chain:
        self.state.message = "select an upper/lower two-bone chain for IK"
        return
    if not self.state.current_clip:
        self.state.current_clip = "ik_test"
    upper, lower, end_point, bend = chain
    if bend_override is not None:
        bend = bend_override
    from pyspine.editor.animation_quality import two_bone_ik_keyframes
    try:
        cmd = two_bone_ik_keyframes(
            self.state.project,
            self.state.current_clip,
            upper,
            lower,
            self.state.last_mouse_world,
            self.state.frame,
            end_point=end_point,
            bend=bend,
        )
    except Exception as exc:
        self.state.message = f"IK failed: {exc}"
        return
    if self.state.run_command(cmd):
        self.state.selected = lower
        self.state.message = f"IK {upper}->{lower}.{end_point} @ {self.state.frame:g}"


def _v13_foot_lock_selected(self, *, frames: float = 6.0) -> None:
    if self.state.mode != "animation":
        self.state.message = "switch to Animation mode for foot lock"
        return
    if not self.state.current_clip:
        self.state.message = "choose/create a clip first"
        return
    if not self.state.selected or self.state.selected not in self.state.project.rig.instances:
        self.state.message = "select a foot/hand instance to lock"
        return
    roots = [i.name for i in self.state.project.rig.instances.values() if i.parent is None]
    if not roots:
        self.state.message = "foot lock needs a root instance"
        return
    inst = self.state.project.rig.instances[self.state.selected]
    locked_point = inst.self_point if inst.self_point else "origin"
    from pyspine.editor.animation_quality import foot_lock_keyframes
    try:
        cmd = foot_lock_keyframes(
            self.state.project,
            self.state.current_clip,
            roots[0],
            self.state.selected,
            locked_point,
            self.state.frame,
            self.state.frame + frames,
            step=1.0,
        )
    except Exception as exc:
        self.state.message = f"foot lock failed: {exc}"
        return
    if self.state.run_command(cmd):
        self.state.message = f"locked {self.state.selected}.{locked_point} frames {self.state.frame:g}-{self.state.frame + frames:g}"


def _v13_detect_plants_selected(self) -> None:
    if self.state.mode != "animation" or not self.state.current_clip or not self.state.selected:
        self.state.message = "select an animated foot/hand first"
        return
    inst = self.state.project.rig.instances.get(self.state.selected)
    if not inst:
        return
    from pyspine.editor.animation_quality import detect_plant_ranges
    try:
        ranges = detect_plant_ranges(self.state.project, self.state.current_clip, self.state.selected, inst.self_point, threshold=0.35, min_frames=2.0)
    except Exception as exc:
        self.state.message = f"plant detect failed: {exc}"
        return
    if not ranges:
        self.state.message = "no planted ranges detected"
    else:
        self.state.message = "; ".join(f"{r.start:g}-{r.end:g}" for r in ranges[:4])

EditorApp._v13_draw_motion_arc = _v13_draw_motion_arc
EditorApp._draw_rig_mode = _v13_draw_rig_mode
EditorApp._v13_selected_channel = _v13_selected_channel
EditorApp._v13_cycle_selected_easing = _v13_cycle_selected_easing
EditorApp._v13_adjust_onion = _v13_adjust_onion
EditorApp._v13_find_two_bone_chain = _v13_find_two_bone_chain
EditorApp._v13_apply_ik_to_mouse = _v13_apply_ik_to_mouse
EditorApp._v13_foot_lock_selected = _v13_foot_lock_selected
EditorApp._v13_detect_plants_selected = _v13_detect_plants_selected
EditorApp._events = _v13_events

# ---- v13.3 workflow/reliability hotfixes -------------------------------------
# Clip chooser is intentionally a centered popup now.  Anchoring it inside the
# sidebar made it too easy to miss or hide behind dense sidebar content on some
# window sizes.

def _v13_3_open_clip_dropdown(self) -> None:
    options = [(name, name) for name in sorted(self.state.project.clips)]
    options.append(("+ New clip...", "__new_clip__"))
    if not self.state.project.clips:
        options.insert(0, ("No clips yet", ""))
    width = 320
    max_visible = min(12, max(3, len(options)))
    if self.screen is not None:
        sw, sh = self.screen.get_size()
        x = max(12, min(sw - width - 12, (sw - width) // 2))
        height = max_visible * 24 + 32
        y = max(48, min(sh - height - 24, 84))
    else:
        x, y = 80, 84
    self.dropdown = Dropdown(x, y + 24, width, options, max_visible=max_visible)
    self.dropdown_purpose = ("clip",)
    self.context_menu = None
    self.state.message = "choose clip: click a row, + New clip, or Esc"


def _v13_3_draw_dropdown(self) -> None:
    dd = getattr(self, "dropdown", None)
    if dd is None:
        return
    pygame = self.pygame
    assert self.screen is not None and self.font is not None
    purpose = getattr(self, "dropdown_purpose", None)
    title_h = 24 if purpose and purpose[0] == "clip" else 0
    rect = pygame.Rect(dd.x, dd.y - title_h, dd.width, dd.height() + title_h)
    pygame.draw.rect(self.screen, (12, 12, 16), rect, border_radius=6)
    pygame.draw.rect(self.screen, (255, 220, 80), rect, 2 if purpose and purpose[0] == "clip" else 1, border_radius=6)
    if title_h:
        self.screen.blit(self.font.render("Clip chooser", True, (255, 220, 80)), (rect.x + 10, rect.y + 5))
        self.screen.blit(self.font.render("click row | Esc closes", True, (175, 175, 180)), (rect.right - 142, rect.y + 5))
    y = dd.y + 4
    for label, value in dd.visible_options():
        row = pygame.Rect(dd.x + 4, y, dd.width - 8, dd.row_h)
        active = value == self.state.current_clip
        if active:
            pygame.draw.rect(self.screen, (58, 58, 68), row, border_radius=3)
        elif value == "__new_clip__":
            pygame.draw.rect(self.screen, (30, 44, 38), row, border_radius=3)
        else:
            pygame.draw.rect(self.screen, (24, 24, 30), row, border_radius=3)
        color = (130, 255, 170) if value == "__new_clip__" else (235, 235, 235)
        self.screen.blit(self.font.render(label[:34], True, color), (row.x + 8, row.y + 4))
        y += dd.row_h
    if len(dd.options) > dd.max_visible:
        thumb = scroll_thumb(dd.max_visible, len(dd.options), dd.scroll, min_thumb=2)
        if thumb:
            ty, th = thumb
            track = pygame.Rect(rect.right - 9, dd.y + 5, 4, dd.height() - 10)
            pygame.draw.rect(self.screen, (44, 44, 50), track, border_radius=2)
            max_units = max(1, dd.max_visible - th)
            max_px = max(1, track.h - max(8, th * dd.row_h))
            y_px = int((ty / max_units) * max_px) if max_units else 0
            pygame.draw.rect(self.screen, (120, 120, 132), (track.x, track.y + y_px, track.w, max(8, th * dd.row_h)), border_radius=2)


def _v13_3_events(self) -> bool:
    pygame = self.pygame
    queued = []
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and self.state.text_prompt is None:
            mods = pygame.key.get_mods()
            shift = bool(mods & pygame.KMOD_SHIFT)
            alt = bool(mods & pygame.KMOD_ALT)
            ctrl = bool(mods & pygame.KMOD_CTRL)
            if self.state.mode == "animation" and not ctrl and not alt and not shift and event.key == pygame.K_c:
                self._open_clip_dropdown(); continue
            if self.state.mode == "animation" and shift and event.key == pygame.K_t:
                self._v13_cycle_selected_easing(); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_UP:
                self._v13_adjust_onion(count_delta=1); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_DOWN:
                self._v13_adjust_onion(count_delta=-1); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_RIGHT:
                self._v13_adjust_onion(step_delta=1.0); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_LEFT:
                self._v13_adjust_onion(step_delta=-1.0); continue
            if self.state.mode == "animation" and event.key == pygame.K_y:
                self._v13_apply_ik_to_mouse(bend_override=(-1 if shift else None)); continue
            if self.state.mode == "animation" and event.key == pygame.K_b:
                self._v13_foot_lock_selected(frames=(12.0 if shift else 6.0)); continue
            if self.state.mode == "animation" and event.key == pygame.K_g:
                self._v13_detect_plants_selected(); continue
        queued.append(event)
    for event in queued:
        pygame.event.post(event)
    return _v12_events_for_v13(self)


def _v13_3_run_editor(path: str | Path) -> None:
    try:
        EditorApp(path).run()
    except KeyboardInterrupt:
        # Ctrl+C from the launching console should shut down the editor cleanly,
        # not print a scary stack trace from whichever draw/update function was
        # interrupted.
        return


EditorApp._open_clip_dropdown = _v13_3_open_clip_dropdown
EditorApp._draw_dropdown = _v13_3_draw_dropdown
EditorApp._events = _v13_3_events
run_editor = _v13_3_run_editor

# ---- v13.4 workflow/IK polish ------------------------------------------------
# Make the Clip button use the same obvious centered chooser as the C hotkey,
# and switch IK from two-bone-only to whole-chain/full-body by default.

_v13_4_ui_action_base = EditorApp._ui_action
_v13_4_draw_dropdown_base = EditorApp._draw_dropdown
_v13_4_dropdown_rect_base = EditorApp._dropdown_rect
_v13_4_apply_ik_legacy = EditorApp._v13_apply_ik_to_mouse


def _v13_4_open_clip_dropdown(self) -> None:
    options = [(name, name) for name in sorted(self.state.project.clips)]
    options.append(("+ New clip...", "__new_clip__"))
    if not self.state.project.clips:
        options.insert(0, ("No clips yet", ""))
    width = 420
    max_visible = min(14, max(4, len(options)))
    if self.screen is not None:
        sw, sh = self.screen.get_size()
        x = max(12, min(sw - width - 12, (sw - width) // 2))
        y = max(60, min(sh - (max_visible * 26 + 84), 95))
    else:
        x, y = 80, 95
    # Dropdown.hit still handles the row area; drawing adds a big modal frame.
    self.dropdown = Dropdown(x + 18, y + 50, width - 36, options, row_h=26, max_visible=max_visible)
    self.dropdown_purpose = ("clip",)
    self.context_menu = None
    self.state.message = "Clip chooser open: click a row, + New clip, or Esc"


def _v13_4_dropdown_rect(self):
    dd = getattr(self, "dropdown", None)
    if dd is None:
        return None
    pygame = self.pygame
    purpose = getattr(self, "dropdown_purpose", None)
    if purpose and purpose[0] == "clip":
        return pygame.Rect(dd.x - 18, dd.y - 50, dd.width + 36, dd.height() + 68)
    return _v13_4_dropdown_rect_base(self)


def _v13_4_draw_dropdown(self) -> None:
    dd = getattr(self, "dropdown", None)
    if dd is None:
        return
    purpose = getattr(self, "dropdown_purpose", None)
    if not purpose or purpose[0] != "clip":
        return _v13_4_draw_dropdown_base(self)
    pygame = self.pygame
    assert self.screen is not None and self.font is not None and self.big_font is not None
    # Semi-transparent dimmer makes it impossible to miss the chooser even if
    # the sidebar is dense or the window is small.
    sw, sh = self.screen.get_size()
    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 105))
    self.screen.blit(overlay, (0, 0))

    rect = pygame.Rect(dd.x - 18, dd.y - 50, dd.width + 36, dd.height() + 68)
    pygame.draw.rect(self.screen, (14, 14, 20), rect, border_radius=10)
    pygame.draw.rect(self.screen, (255, 220, 80), rect, 2, border_radius=10)
    self.screen.blit(self.big_font.render("Choose clip", True, (255, 220, 80)), (rect.x + 16, rect.y + 13))
    self.screen.blit(self.font.render("Click a clip, choose + New clip..., or press Esc", True, (190, 190, 200)), (rect.x + 16, rect.y + 38))

    y = dd.y + 4
    for label, value in dd.visible_options():
        row = pygame.Rect(dd.x + 4, y, dd.width - 8, dd.row_h)
        active = bool(value and value == self.state.current_clip)
        if active:
            pygame.draw.rect(self.screen, (64, 64, 78), row, border_radius=4)
            pygame.draw.rect(self.screen, (130, 190, 255), row, 1, border_radius=4)
        elif value == "__new_clip__":
            pygame.draw.rect(self.screen, (28, 54, 38), row, border_radius=4)
        else:
            pygame.draw.rect(self.screen, (27, 27, 34), row, border_radius=4)
        color = (130, 255, 170) if value == "__new_clip__" else (235, 235, 240)
        suffix = "  ✓" if active else ""
        self.screen.blit(self.font.render((label + suffix)[:42], True, color), (row.x + 10, row.y + 5))
        y += dd.row_h

    if len(dd.options) > dd.max_visible:
        thumb = scroll_thumb(dd.max_visible, len(dd.options), dd.scroll, min_thumb=2)
        if thumb:
            ty, th = thumb
            track = pygame.Rect(rect.right - 13, dd.y + 4, 5, dd.height() - 8)
            pygame.draw.rect(self.screen, (42, 42, 50), track, border_radius=3)
            max_units = max(1, dd.max_visible - th)
            max_px = max(1, track.h - max(10, th * dd.row_h))
            y_px = int((ty / max_units) * max_px) if max_units else 0
            pygame.draw.rect(self.screen, (130, 130, 145), (track.x, track.y + y_px, track.w, max(10, th * dd.row_h)), border_radius=3)


def _v13_4_ui_action(self, action: str) -> None:
    if action == "clip_dropdown":
        self._open_clip_dropdown()
        return
    return _v13_4_ui_action_base(self, action)


def _v13_4_apply_ik_to_mouse(self, *, bend_override: int | None = None) -> None:
    if self.state.mode != "animation":
        self.state.message = "switch to Animation mode for IK"
        return
    if not self.state.selected:
        self.state.message = "select a hand, foot, or limb end for full-body IK"
        return
    if not self.state.current_clip:
        self.state.current_clip = "ik_test"
    from pyspine.editor.animation_quality import choose_end_effector_point, instance_ancestor_chain, whole_chain_ik_keyframes
    try:
        end_point = choose_end_effector_point(self.state.project, self.state.selected)
        chain = instance_ancestor_chain(self.state.project, self.state.selected)
        cmd = whole_chain_ik_keyframes(
            self.state.project,
            self.state.current_clip,
            self.state.selected,
            self.state.last_mouse_world,
            self.state.frame,
            end_point=end_point,
            iterations=16,
        )
    except Exception as exc:
        # Keep the old two-bone helper as a fallback for unusual rigs.
        try:
            return _v13_4_apply_ik_legacy(self, bend_override=bend_override)
        except Exception:
            self.state.message = f"full-body IK failed: {exc}"
            return
    if self.state.run_command(cmd):
        self.state.message = f"Full-body IK {len(chain)} part chain -> {self.state.selected}.{end_point} @ {self.state.frame:g}"


EditorApp._open_clip_dropdown = _v13_4_open_clip_dropdown
EditorApp._dropdown_rect = _v13_4_dropdown_rect
EditorApp._draw_dropdown = _v13_4_draw_dropdown
EditorApp._ui_action = _v13_4_ui_action
EditorApp._v13_apply_ik_to_mouse = _v13_4_apply_ik_to_mouse

_v13_4_events_base = EditorApp._events


def _v13_4_events(self) -> bool:
    pygame = self.pygame
    queued = []
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and self.state.text_prompt is None:
            mods = pygame.key.get_mods()
            shift = bool(mods & pygame.KMOD_SHIFT)
            alt = bool(mods & pygame.KMOD_ALT)
            ctrl = bool(mods & pygame.KMOD_CTRL)
            if event.key == pygame.K_ESCAPE and getattr(self, "dropdown", None) is not None:
                self.dropdown = None
                self.dropdown_purpose = None
                self.state.message = "chooser closed"
                continue
            if self.state.mode == "animation" and not ctrl and not alt and not shift and event.key == pygame.K_c:
                self._open_clip_dropdown(); continue
            if self.state.mode == "animation" and shift and event.key == pygame.K_t:
                self._v13_cycle_selected_easing(); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_UP:
                self._v13_adjust_onion(count_delta=1); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_DOWN:
                self._v13_adjust_onion(count_delta=-1); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_RIGHT:
                self._v13_adjust_onion(step_delta=1.0); continue
            if self.state.mode == "animation" and alt and event.key == pygame.K_LEFT:
                self._v13_adjust_onion(step_delta=-1.0); continue
            if self.state.mode == "animation" and event.key == pygame.K_y:
                self._v13_apply_ik_to_mouse(bend_override=(-1 if shift else None)); continue
            if self.state.mode == "animation" and event.key == pygame.K_b:
                self._v13_foot_lock_selected(frames=(12.0 if shift else 6.0)); continue
            if self.state.mode == "animation" and event.key == pygame.K_g:
                self._v13_detect_plants_selected(); continue
        queued.append(event)
    for event in queued:
        pygame.event.post(event)
    return _v12_events_for_v13(self)

EditorApp._events = _v13_4_events

# ---- v13.5 workflow polish ---------------------------------------------------
# * Any instance can be translated. Child x/y remain local offsets from their
#   attachment point, so the part stays attached while the animator nudges it.
# * Rig mode always shows the base rig pose; playback is Animation-mode only.
# * Per-mode viewports fix the Fit regression where Sprite/Rig/Animation shared
#   one camera.
# * Animation sprite swaps are keyframed through the sprite channel.
# * New clips start with explicit frame-0 keys for the current rig/base pose.

from pyspine.editor.viewport import Viewport as _V13_5Viewport  # noqa: E402
from pyspine.core.commands import SetManyKeyframes as _V13_5SetManyKeyframes  # noqa: E402

_v13_5_init_base = EditorApp.__init__
_v13_5_events_base = EditorApp._events
_v13_5_update_base = EditorApp._update
_v13_5_current_pose_base = EditorApp._current_pose
_v13_5_ui_action_base = EditorApp._ui_action
_v13_5_commit_prompt_base = EditorApp._commit_prompt
_v13_5_menu_click_base = EditorApp._menu_click
_v13_5_inspector_rows_base = EditorApp._inspector_sidebar_rows
_v13_5_context_items_base = EditorApp._context_items
_v13_5_draw_rig_base = EditorApp._draw_rig
_v13_5_fit_view_base = EditorApp._fit_view


def _v13_5_clone_viewport(vp):
    return _V13_5Viewport(zoom=float(vp.zoom), offset=Vec2(float(vp.offset.x), float(vp.offset.y)))


def _v13_5_init(self, path):
    _v13_5_init_base(self, path)
    self._mode_viewports = {
        "sprite": _v13_5_clone_viewport(self.state.viewport),
        "rig": _v13_5_clone_viewport(self.state.viewport),
        "animation": _v13_5_clone_viewport(self.state.viewport),
    }
    self._active_mode_for_viewport = self.state.mode
    self.rig_translucent = False
    self.rig_alpha = 0.55


def _v13_5_sync_mode_viewport(self) -> None:
    mode = self.state.mode
    old = getattr(self, "_active_mode_for_viewport", mode)
    if not hasattr(self, "_mode_viewports"):
        return
    if mode == old:
        self._mode_viewports[mode] = _v13_5_clone_viewport(self.state.viewport)
        return
    self._mode_viewports[old] = _v13_5_clone_viewport(self.state.viewport)
    self.state.viewport = _v13_5_clone_viewport(self._mode_viewports.get(mode, self.state.viewport))
    self._active_mode_for_viewport = mode
    if mode != "animation":
        self.state.playing = False


def _v13_5_current_pose(self):
    # Rig mode is the base rigging pose.  Only Animation mode samples clips.
    if self.state.mode == "animation" and self.state.current_clip:
        ov = sample_clip(self.state.project, self.state.current_clip, self.state.frame)
        return solve_pose(self.state.project, ov)
    return solve_pose(self.state.project)


def _v13_5_update(self, dt: float) -> None:
    if self.state.mode != "animation":
        self.state.playing = False
        return
    return _v13_5_update_base(self, dt)


def _v13_5_events(self) -> bool:
    before = self.state.mode
    try:
        ok = _v13_5_events_base(self)
    finally:
        self._v13_5_sync_mode_viewport()
    return ok


def _v13_5_fit_view(self) -> None:
    _v13_5_fit_view_base(self)
    if hasattr(self, "_mode_viewports"):
        self._mode_viewports[self.state.mode] = _v13_5_clone_viewport(self.state.viewport)


def _v13_5_base_pose_changes(self, clip_name: str, frame: float = 0.0):
    changes = []
    for name, inst in self.state.project.rig.instances.items():
        values = {
            "x": float(inst.x),
            "y": float(inst.y),
            "scale_x": float(inst.scale_x),
            "scale_y": float(inst.scale_y),
            "visible": 1.0 if inst.visible else 0.0,
            "sprite": inst.sprite,
        }
        values["rotation" if inst.parent is None else "local_rotation"] = float(inst.rotation if inst.parent is None else inst.local_rotation)
        for channel, value in values.items():
            changes.append((name, channel, float(frame), None, value))
    return changes


def _v13_5_create_clip_from_rig_pose(self, name: str) -> None:
    self.state.project.clips[name] = Clip(name=name, length=24.0, fps=24.0, loop=True)
    changes = self._v13_5_base_pose_changes(name, 0.0)
    if changes:
        cmd = _V13_5SetManyKeyframes(name, changes, label="Initialize clip from rig pose")
        cmd.apply(self.state.project)
    self.state.current_clip = name
    self.state.mode = "animation"
    self.state.frame = 0.0
    self.state.dirty = True
    self.state.message = f"created clip {name} from rig pose"


def _v13_5_ui_action(self, action: str) -> None:
    if action == "play":
        if self.state.mode != "animation":
            self.state.playing = False
            self.state.message = "playback is Animation-mode only"
            return
    if action.startswith("mode:"):
        target = action.split(":", 1)[1]
        if self.state.mode == "animation" and target != "animation":
            self.state.playing = False
    if action == "toggle_rig_alpha":
        self.rig_translucent = not bool(getattr(self, "rig_translucent", False))
        self.state.message = f"rig translucency {'on' if self.rig_translucent else 'off'} ({int(self.rig_alpha * 100)}%)"
        return
    if action == "cycle_rig_alpha":
        choices = [0.25, 0.40, 0.55, 0.70, 0.85]
        cur = min(range(len(choices)), key=lambda i: abs(choices[i] - float(getattr(self, 'rig_alpha', 0.55))))
        self.rig_alpha = choices[(cur + 1) % len(choices)]
        self.rig_translucent = True
        self.state.message = f"rig alpha {int(self.rig_alpha * 100)}%"
        return
    _v13_5_ui_action_base(self, action)


def _v13_5_commit_prompt(self) -> None:
    prompt = self.state.text_prompt
    if prompt is not None and prompt.purpose == "new_clip":
        text = prompt.text.strip()
        self.state.text_prompt = None
        if not text:
            self.state.message = "empty clip name ignored"
            return
        name = text
        n = 2
        while name in self.state.project.clips:
            name = f"{text}_{n}"
            n += 1
        self._v13_5_create_clip_from_rig_pose(name)
        return
    return _v13_5_commit_prompt_base(self)


def _v13_5_menu_click(self, pos) -> bool:
    # Override dropdown handling so Animation-mode sprite selection keys a sprite
    # swap instead of mutating the rest rig.  Other dropdowns keep the old path.
    if getattr(self, "dropdown", None) is not None and getattr(self, "dropdown_purpose", None):
        value = self.dropdown.hit(pos[0], pos[1])
        if value is not None:
            purpose = self.dropdown_purpose
            self.dropdown = None
            self.dropdown_purpose = None
            if purpose[0] == "clip":
                if value == "__new_clip__":
                    base = f"clip_{len(self.state.project.clips) + 1:02d}"
                    self.state.text_prompt = TextPrompt("new_clip", base, {})
                    self.state.message = "type new clip name and press Enter"
                elif value:
                    self.state.current_clip = value
                    self.state.frame = max(0.0, min(self.state.frame, self.state.project.clips[value].length))
                    self.state.mode = "animation"
                    self.state.message = f"clip {value}"
                else:
                    self.state.message = "no clips yet"
                return True
            if purpose[0] == "instance_field":
                inst_name, field = purpose[1], purpose[2]
                if inst_name in self.state.project.rig.instances:
                    inst = self.state.project.rig.instances[inst_name]
                    if self.state.mode == "animation" and field == "sprite":
                        problem = sprite_swap_problem(self.state.project, inst_name, str(value))
                        if problem:
                            self.state.message = f"can't attach sprite swap: {problem}"
                            self.sprite_cache.clear()
                            return True
                        clip_name = self.state.current_clip or "anim"
                        if clip_name not in self.state.project.clips:
                            self._v13_5_create_clip_from_rig_pose(clip_name)
                        clip = self.state.project.clips[clip_name]
                        track = clip.tracks.get(inst_name)
                        before = None
                        if track:
                            before = track.channels.get("sprite", {}).get(float(self.state.frame))
                        cmd = _V13_5SetManyKeyframes(clip_name, [(inst_name, "sprite", float(self.state.frame), before, str(value))], label="Sprite swap keyframe")
                        if self.state.run_command(cmd):
                            self.state.current_clip = clip_name
                            self.state.message = f"sprite swap {inst_name} -> {value} @ {self.state.frame:g}"
                        self.sprite_cache.clear()
                        return True
                    before = {field: getattr(inst, field)}
                    after = {field: value}
                    if field == "sprite":
                        problem = sprite_swap_problem(self.state.project, inst_name, str(value))
                        if problem:
                            self.state.message = f"can't attach sprite: {problem}"
                            self.sprite_cache.clear()
                            return True
                    self.state.run_command(SetInstanceFields(inst_name, before, after, label="Set inspector field"))
                    self.sprite_cache.clear()
                return True
        rect = self._dropdown_rect()
        if rect and rect.collidepoint(pos):
            return True
        self.dropdown = None
        self.dropdown_purpose = None
    return _v13_5_menu_click_base(self, pos)


def _v13_5_inspector_sidebar_rows(self, bright, yellow, blue, dim, green) -> list[tuple]:
    rows = _v13_5_inspector_rows_base(self, bright, yellow, blue, dim, green)
    s = self.state
    if s.mode == "rig":
        rows.append(("", dim))
        rows.append(("Rig view:", blue))
        rows.append((f"  translucent sprites: {'on' if getattr(self, 'rig_translucent', False) else 'off'}", green if getattr(self, 'rig_translucent', False) else dim, "action", "toggle_rig_alpha"))
        rows.append((f"  alpha: {int(float(getattr(self, 'rig_alpha', 0.55)) * 100)}%", yellow, "action", "cycle_rig_alpha"))
    if s.mode == "animation" and s.selected and s.selected in s.project.rig.instances:
        # Make it clear that the sprite dropdown is a per-frame swap in Anim mode.
        rows.append(("", dim))
        rows.append(("Sprite swap:", blue))
        rows.append(("  click sprite dropdown to key", dim))
    return rows


def _v13_5_context_items(self):
    items = _v13_5_context_items_base(self)
    if self.state.mode == "rig":
        items.append(MenuItem("Toggle translucent sprites", "toggle_rig_alpha"))
        items.append(MenuItem("Cycle translucency percent", "cycle_rig_alpha"))
    return items


def _v13_5_draw_rig(self, poses, *, ghost: bool = False) -> None:
    # Copy of the old drawer with an alpha path for Rig mode.  We keep outlines,
    # pivots, and attachment links fully opaque so the rig remains readable.
    pygame = self.pygame
    assert self.screen is not None
    use_alpha = (not ghost and self.state.mode == "rig" and bool(getattr(self, "rig_translucent", False)))
    alpha = max(0, min(255, int(float(getattr(self, "rig_alpha", 0.55)) * 255)))
    for pose in sorted(poses.values(), key=lambda p: (p.z, p.instance)):
        if not pose.visible:
            continue
        sprite = self.state.project.sheet.sprites[pose.sprite]
        surface = self._sprite_surface(pose.sprite)
        corners_world = [pose.local_to_world(c) for c in sprite.rect.corners()]
        corners = [self.state.viewport.world_to_screen(p) for p in corners_world]

        if surface is not None and not ghost:
            scale_for_surface = self.state.viewport.zoom * max(0.001, (abs(pose.scale_x) + abs(pose.scale_y)) / 2.0)
            scaled = pygame.transform.rotozoom(surface, -pose.rotation, scale_for_surface)
            if use_alpha:
                scaled = scaled.copy()
                scaled.set_alpha(alpha)
            center_world = Vec2(sum((p.x for p in corners_world), 0.0) / 4.0, sum((p.y for p in corners_world), 0.0) / 4.0)
            center = self.state.viewport.world_to_screen(center_world)
            rect = scaled.get_rect(center=(int(center.x), int(center.y)))
            self.screen.blit(scaled, rect)
        elif not ghost:
            color = (120, 160, 210) if pose.instance == self.state.selected else (95, 105, 120)
            pygame.draw.polygon(self.screen, color, [c.as_tuple() for c in corners], width=0)

        if ghost:
            outline = (80, 120, 190)
            pygame.draw.polygon(self.screen, outline, [c.as_tuple() for c in corners], width=1)
            continue

        outline = (255, 220, 80) if pose.instance == self.state.selected else (15, 15, 18)
        pygame.draw.polygon(self.screen, outline, [c.as_tuple() for c in corners], width=2 if pose.instance == self.state.selected else 1)
        anchor = self.state.viewport.world_to_screen(pose.anchor)
        pygame.draw.circle(self.screen, (255, 220, 80), (int(anchor.x), int(anchor.y)), 4)
        for point_name, point in pose.points.items():
            spt = self.state.viewport.world_to_screen(point)
            color = (255, 90, 90) if point_name == "origin" else (235, 235, 235)
            pygame.draw.circle(self.screen, color, (int(spt.x), int(spt.y)), 2)
        inst = self.state.project.rig.instances[pose.instance]
        if inst.parent:
            parent_pose = poses.get(inst.parent)
            if parent_pose and inst.parent_point:
                p0 = self.state.viewport.world_to_screen(parent_pose.point(inst.parent_point))
                p1 = self.state.viewport.world_to_screen(pose.anchor)
                pygame.draw.line(self.screen, (100, 100, 120), p0.as_tuple(), p1.as_tuple(), 1)


EditorApp.__init__ = _v13_5_init
EditorApp._v13_5_sync_mode_viewport = _v13_5_sync_mode_viewport
EditorApp._v13_5_base_pose_changes = _v13_5_base_pose_changes
EditorApp._v13_5_create_clip_from_rig_pose = _v13_5_create_clip_from_rig_pose
EditorApp._events = _v13_5_events
EditorApp._update = _v13_5_update
EditorApp._current_pose = _v13_5_current_pose
EditorApp._ui_action = _v13_5_ui_action
EditorApp._commit_prompt = _v13_5_commit_prompt
EditorApp._menu_click = _v13_5_menu_click
EditorApp._inspector_sidebar_rows = _v13_5_inspector_sidebar_rows
EditorApp._context_items = _v13_5_context_items
EditorApp._draw_rig = _v13_5_draw_rig
EditorApp._fit_view = _v13_5_fit_view

# ---- v13.6 attachment-safe translation / breakable points / clearer inspector --
# Reverts the v13.5 mistake where child translation offsets could silently defeat
# attachment points.  Animation-mode dragging of attached parts now poses the
# connected body chain using IK.  Deliberate attachment breaks are opt-in per
# attachment point and keyed per frame through the break_attach channel.

_v13_6_sidebar_lines_base = EditorApp._sidebar_lines
_v13_6_context_items_base = EditorApp._context_items
_v13_6_ui_action_base = EditorApp._ui_action
_v13_6_events_base = EditorApp._events


def _v13_6_breakable_map(project):
    raw = project.metadata.setdefault("breakable_points", {})
    if not isinstance(raw, dict):
        project.metadata["breakable_points"] = {}
        raw = project.metadata["breakable_points"]
    return raw


def _v13_6_is_point_breakable(project, sprite_name: str | None, point_name: str | None) -> bool:
    if not sprite_name or not point_name:
        return False
    raw = project.metadata.get("breakable_points", {})
    if not isinstance(raw, dict):
        return False
    return bool(raw.get(sprite_name, {}).get(point_name, False)) if isinstance(raw.get(sprite_name, {}), dict) else False


def _v13_6_set_point_breakable(project, sprite_name: str, point_name: str, value: bool) -> None:
    raw = _v13_6_breakable_map(project)
    sprite_flags = raw.setdefault(sprite_name, {})
    if not isinstance(sprite_flags, dict):
        raw[sprite_name] = {}
        sprite_flags = raw[sprite_name]
    if value:
        sprite_flags[point_name] = True
    else:
        sprite_flags.pop(point_name, None)
        if not sprite_flags:
            raw.pop(sprite_name, None)


def _v13_6_toggle_selected_point_breakable(self) -> None:
    s = self.state
    if s.mode != "sprite" or not s.selected_sprite or not s.selected_point:
        s.message = "select an attachment point in Sprite mode first"
        return
    if s.selected_point == "origin":
        s.message = "origin cannot be marked breakable"
        return
    before = _v13_6_is_point_breakable(s.project, s.selected_sprite, s.selected_point)
    _v13_6_set_point_breakable(s.project, s.selected_sprite, s.selected_point, not before)
    s.dirty = True
    s.message = f"{s.selected_sprite}.{s.selected_point} breakable = {not before}"


def _v13_6_toggle_break_key(self) -> None:
    s = self.state
    if s.mode != "animation" or not s.selected or s.selected not in s.project.rig.instances:
        s.message = "select an attached instance in Animation mode"
        return
    inst = s.project.rig.instances[s.selected]
    if inst.parent is None:
        s.message = "root instances do not use attachment breaks"
        return
    if not _v13_6_is_point_breakable(s.project, inst.sprite, inst.self_point):
        s.message = f"{inst.sprite}.{inst.self_point} is not breakable; mark it in Sprite mode first"
        return
    clip_name = s.current_clip or "anim"
    if clip_name not in s.project.clips:
        self._v13_5_create_clip_from_rig_pose(clip_name)
    clip = s.project.clips[clip_name]
    frame = float(s.frame)
    track = clip.tracks.get(inst.name)
    before = None
    if track:
        before = track.channels.get("break_attach", {}).get(frame)
    sampled = sample_clip(s.project, clip_name, frame) if clip_name in s.project.clips else {}
    current = bool(sampled.get(inst.name, {}).get("break_attach", False))
    after = 0.0 if current else 1.0
    cmd = _V13_5SetManyKeyframes(clip_name, [(inst.name, "break_attach", frame, before, after)], label="Toggle attachment break")
    if s.run_command(cmd):
        s.current_clip = clip_name
        s.message = f"{inst.name} break_attach={bool(after)} @ {frame:g}"


def _v13_6_open_sprite_swap(self) -> None:
    s = self.state
    if s.mode != "animation" or not s.selected or s.selected not in s.project.rig.instances:
        s.message = "select an instance in Animation mode first"
        return
    self._open_property_dropdown("sprite")
    s.message = "choose replacement sprite for a sprite-swap key"


def _v13_6_sidebar_lines(self) -> list[tuple]:
    rows = _v13_6_sidebar_lines_base(self)
    bright = (235, 235, 235)
    dim = (175, 175, 180)
    yellow = (255, 220, 80)
    blue = (130, 190, 255)
    green = (130, 255, 170)
    s = self.state

    extras: list[tuple] = []
    if s.mode == "sprite" and s.selected_sprite and s.selected_point:
        br = _v13_6_is_point_breakable(s.project, s.selected_sprite, s.selected_point)
        extras.extend([
            ("", dim),
            ("Attachment options:", blue),
            (f"  breakable: {'yes' if br else 'no'}", green if br else dim, "action", "toggle_breakable_point"),
            ("  B toggles breakable for selected point", dim),
        ])
    elif s.mode == "animation":
        extras.extend([
            ("", dim),
            ("PROPERTY INSPECTOR / SPRITE SWAP:", blue),
        ])
        extras.extend(self._inspector_sidebar_rows(bright, yellow, blue, dim, green))
        if s.selected and s.selected in s.project.rig.instances:
            inst = s.project.rig.instances[s.selected]
            if inst.parent:
                br = _v13_6_is_point_breakable(s.project, inst.sprite, inst.self_point)
                sampled = sample_clip(s.project, s.current_clip, s.frame) if s.current_clip in s.project.clips else {}
                broken = bool(sampled.get(inst.name, {}).get("break_attach", False)) if s.current_clip else False
                extras.extend([
                    ("", dim),
                    ("Attachment break:", blue),
                    (f"  point {inst.sprite}.{inst.self_point}: {'breakable' if br else 'not breakable'}", green if br else dim),
                    (f"  this frame: {'BROKEN' if broken else 'attached'}", yellow if broken else dim, "action", "toggle_break_key"),
                    ("  Ctrl+B toggles break on current frame", dim),
                    ("  S opens sprite-swap dropdown", dim),
                ])
    if extras:
        # Insert before the trailing blank/message pair when possible so the
        # message remains at the bottom of the sidebar.
        insert_at = max(0, len(rows) - 2)
        rows[insert_at:insert_at] = extras
    return rows


def _v13_6_context_items(self):
    items = _v13_6_context_items_base(self)
    s = self.state
    if s.mode == "sprite" and s.selected_sprite and s.selected_point and s.selected_point != "origin":
        br = _v13_6_is_point_breakable(s.project, s.selected_sprite, s.selected_point)
        items.insert(0, MenuItem("Make point non-breakable" if br else "Make point breakable", "toggle_breakable_point"))
    if s.mode == "animation" and s.selected:
        items.insert(0, MenuItem("Swap sprite at this frame", "swap_sprite", True))
        inst = s.project.rig.instances.get(s.selected)
        if inst and inst.parent:
            items.insert(1, MenuItem("Toggle attachment break at frame", "toggle_break_key", True))
    return items


def _v13_6_ui_action(self, action: str) -> None:
    if action == "toggle_breakable_point":
        self._v13_6_toggle_selected_point_breakable()
        self.context_menu = None
        return
    if action == "toggle_break_key":
        self._v13_6_toggle_break_key()
        self.context_menu = None
        return
    if action == "swap_sprite":
        self._v13_6_open_sprite_swap()
        self.context_menu = None
        return
    return _v13_6_ui_action_base(self, action)


def _v13_6_events(self) -> bool:
    pygame = self.pygame
    queued = []
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and self.state.text_prompt is None:
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            if self.state.mode == "sprite" and not ctrl and event.key == pygame.K_b:
                self._v13_6_toggle_selected_point_breakable(); continue
            if self.state.mode == "animation" and ctrl and event.key == pygame.K_b:
                self._v13_6_toggle_break_key(); continue
            if self.state.mode == "animation" and not ctrl and event.key == pygame.K_s:
                self._v13_6_open_sprite_swap(); continue
        queued.append(event)
    for event in queued:
        pygame.event.post(event)
    return _v13_6_events_base(self)


EditorApp._sidebar_lines = _v13_6_sidebar_lines
EditorApp._context_items = _v13_6_context_items
EditorApp._ui_action = _v13_6_ui_action
EditorApp._events = _v13_6_events
EditorApp._v13_6_toggle_selected_point_breakable = _v13_6_toggle_selected_point_breakable
EditorApp._v13_6_toggle_break_key = _v13_6_toggle_break_key
EditorApp._v13_6_open_sprite_swap = _v13_6_open_sprite_swap
