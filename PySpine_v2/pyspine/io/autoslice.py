from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pyspine.core.geometry import Rect
from pyspine.core.model import AttachmentPoint, Instance, Project, Rig, Sprite, SpriteSheet


@dataclass(frozen=True, slots=True)
class SliceBox:
    name: str
    rect: Rect
    area: int
    dominant: str


def autoslice_project(
    image_path: str | Path,
    *,
    min_area: int = 50,
    padding: int = 1,
    prefix: str = "part",
    relative_to: str | Path | None = None,
) -> Project:
    """Create a simple project by connected-component slicing an RGBA sprite sheet.

    The slicer treats every non-transparent island as one sprite. It is deliberately
    small and deterministic: the real editor can refine names, pivots, and hierarchy
    afterwards, but this gives a useful first pass for Aseprite-exported PNG sheets.
    """

    boxes = find_alpha_slices(image_path, min_area=min_area, padding=padding, prefix=prefix)
    image_ref = _image_reference(image_path, relative_to)
    sprites = {box.name: sprite_from_slice(box) for box in boxes}
    instances: dict[str, Instance] = {}

    # Lay all pieces out as a gallery so validate/sample/editor immediately works.
    x = 40.0
    y = 60.0
    row_h = 0.0
    for i, box in enumerate(boxes):
        sprite = sprites[box.name]
        if x + sprite.rect.w > 920:
            x = 40.0
            y += row_h + 30.0
            row_h = 0.0
        instances[box.name] = Instance(
            name=box.name,
            sprite=box.name,
            self_point="origin",
            x=x + sprite.rect.w * 0.5,
            y=y + sprite.rect.h * 0.5,
            z=i,
        )
        x += sprite.rect.w + 24.0
        row_h = max(row_h, sprite.rect.h)

    return Project(
        sheet=SpriteSheet(image=image_ref, sprites=sprites),
        rig=Rig(instances=instances),
        metadata={
            "generator": "pyspine.io.autoslice",
            "source_image": Path(image_path).name,
            "min_area": min_area,
            "padding": padding,
        },
    )


def find_alpha_slices(
    image_path: str | Path,
    *,
    min_area: int = 50,
    padding: int = 1,
    prefix: str = "part",
) -> list[SliceBox]:
    from PIL import Image

    image = Image.open(image_path).convert("RGBA")
    w, h = image.size
    pix = image.load()
    visited = [[False] * w for _ in range(h)]
    boxes: list[tuple[int, int, int, int, int, str]] = []

    for y in range(h):
        for x in range(w):
            if visited[y][x] or pix[x, y][3] == 0:
                continue
            stack = [(x, y)]
            visited[y][x] = True
            xs: list[int] = []
            ys: list[int] = []
            colors: dict[tuple[int, int, int], int] = {}
            while stack:
                cx, cy = stack.pop()
                xs.append(cx)
                ys.append(cy)
                r, g, b, a = pix[cx, cy]
                if a and (r, g, b) != (0, 0, 0):
                    colors[(r, g, b)] = colors.get((r, g, b), 0) + 1
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx = cx + dx
                        ny = cy + dy
                        if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx] and pix[nx, ny][3] != 0:
                            visited[ny][nx] = True
                            stack.append((nx, ny))

            area = len(xs)
            if area < min_area:
                continue
            x0 = max(0, min(xs) - padding)
            y0 = max(0, min(ys) - padding)
            x1 = min(w, max(xs) + 1 + padding)
            y1 = min(h, max(ys) + 1 + padding)
            boxes.append((x0, y0, x1, y1, area, _dominant_name(colors)))

    boxes.sort(key=lambda b: (b[1], b[0]))
    counts: dict[str, int] = {}
    out: list[SliceBox] = []
    for x0, y0, x1, y1, area, dominant in boxes:
        counts[dominant] = counts.get(dominant, 0) + 1
        name = f"{prefix}_{dominant}_{counts[dominant]:02d}"
        out.append(SliceBox(name=name, rect=Rect(float(x0), float(y0), float(x1 - x0), float(y1 - y0)), area=area, dominant=dominant))
    return out


def sprite_from_slice(box: SliceBox) -> Sprite:
    w = box.rect.w
    h = box.rect.h
    points: dict[str, AttachmentPoint] = {
        "origin": AttachmentPoint("origin", 0.5, 0.5),
        "center": AttachmentPoint("center", 0.5, 0.5),
        "top": AttachmentPoint("top", 0.5, 0.08),
        "bottom": AttachmentPoint("bottom", 0.5, 0.92),
        "left": AttachmentPoint("left", 0.08, 0.5),
        "right": AttachmentPoint("right", 0.92, 0.5),
    }
    if h >= w * 1.2:
        points["proximal"] = AttachmentPoint("proximal", 0.5, 0.08)
        points["distal"] = AttachmentPoint("distal", 0.5, 0.92)
    elif w >= h * 1.2:
        points["proximal"] = AttachmentPoint("proximal", 0.08, 0.5)
        points["distal"] = AttachmentPoint("distal", 0.92, 0.5)
    else:
        points["proximal"] = AttachmentPoint("proximal", 0.5, 0.12)
        points["distal"] = AttachmentPoint("distal", 0.5, 0.88)
    return Sprite(name=box.name, rect=box.rect, points=points)


def _dominant_name(colors: dict[tuple[int, int, int], int]) -> str:
    if not colors:
        return "ink"
    (r, g, b), _ = max(colors.items(), key=lambda kv: kv[1])
    if g > r and g > b:
        return "green"
    if b > r and b > g:
        return "blue"
    if r > g and r > b:
        return "red"
    return "ink"


def _image_reference(image_path: str | Path, relative_to: str | Path | None) -> str:
    image = Path(image_path)
    if relative_to is None:
        return str(image)
    try:
        return str(image.resolve().relative_to(Path(relative_to).resolve()))
    except ValueError:
        return str(image)
