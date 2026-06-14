from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pyspine.io.jsonio import load_project
from pyspine.runtime.renderer_pillow import PillowRenderer, clip_bounds


@dataclass(frozen=True, slots=True)
class FrameExportResult:
    output: Path
    frames: list[Path]
    width: int
    height: int


def frame_numbers_for_clip(length: float, *, start: float = 0.0, end: float | None = None, step: float = 1.0) -> list[float]:
    if step <= 0:
        raise ValueError("step must be greater than zero")
    if end is None:
        end = length
    if end < start:
        raise ValueError("end must be greater than or equal to start")
    frames: list[float] = []
    f = float(start)
    # Include the end frame when it lands exactly on the step. Add epsilon for
    # non-integer frame stepping.
    while f <= float(end) + 1.0e-9:
        frames.append(round(f, 6))
        f += float(step)
    return frames or [float(start)]


def export_clip_frames(project_path: str | Path, clip_name: str, output_dir: str | Path, *, start: float = 0.0, end: float | None = None, step: float = 1.0, margin: int = 8, prefix: str = "frame") -> FrameExportResult:
    project_path = Path(project_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    project = load_project(project_path)
    clip = project.clips[clip_name]
    frames = frame_numbers_for_clip(clip.length, start=start, end=end, step=step)
    bounds = clip_bounds(project, clip_name, frames)
    renderer = PillowRenderer(project, project_path)
    written: list[Path] = []
    width = height = 0
    for i, frame in enumerate(frames):
        image = renderer.render_clip_frame(clip_name, frame, margin=margin, bounds=bounds)
        width, height = image.size
        frame_name = _frame_name(prefix, i, frame)
        path = output_dir / frame_name
        image.save(path)
        written.append(path)
    return FrameExportResult(output_dir, written, width, height)


def export_clip_strip(project_path: str | Path, clip_name: str, output_png: str | Path, *, start: float = 0.0, end: float | None = None, step: float = 1.0, margin: int = 8, vertical: bool = False) -> Path:
    project_path = Path(project_path)
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    project = load_project(project_path)
    clip = project.clips[clip_name]
    frames = frame_numbers_for_clip(clip.length, start=start, end=end, step=step)
    bounds = clip_bounds(project, clip_name, frames)
    renderer = PillowRenderer(project, project_path)
    images = [renderer.render_clip_frame(clip_name, frame, margin=margin, bounds=bounds) for frame in frames]
    if not images:
        raise ValueError("no frames to export")
    w, h = images[0].size
    if vertical:
        strip = renderer.Image.new("RGBA", (w, h * len(images)), (0, 0, 0, 0))
        for i, image in enumerate(images):
            strip.alpha_composite(image, (0, i * h))
    else:
        strip = renderer.Image.new("RGBA", (w * len(images), h), (0, 0, 0, 0))
        for i, image in enumerate(images):
            strip.alpha_composite(image, (i * w, 0))
    strip.save(output_png)
    return output_png


def export_clip_gif(project_path: str | Path, clip_name: str, output_gif: str | Path, *, start: float = 0.0, end: float | None = None, step: float = 1.0, margin: int = 8) -> Path:
    project_path = Path(project_path)
    output_gif = Path(output_gif)
    output_gif.parent.mkdir(parents=True, exist_ok=True)
    project = load_project(project_path)
    clip = project.clips[clip_name]
    frames = frame_numbers_for_clip(clip.length, start=start, end=end, step=step)
    bounds = clip_bounds(project, clip_name, frames)
    renderer = PillowRenderer(project, project_path)
    images = [renderer.render_clip_frame(clip_name, frame, margin=margin, bounds=bounds) for frame in frames]
    if not images:
        raise ValueError("no frames to export")
    duration_ms = max(1, int(round(1000.0 * step / max(clip.fps, 1.0))))
    images[0].save(
        output_gif,
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0 if clip.loop else 1,
        disposal=2,
    )
    return output_gif


def _frame_name(prefix: str, index: int, frame: float) -> str:
    if abs(frame - round(frame)) < 1.0e-6:
        suffix = f"{int(round(frame)):04d}"
    else:
        suffix = str(frame).replace(".", "p")
    return f"{prefix}_{index:04d}_f{suffix}.png"
