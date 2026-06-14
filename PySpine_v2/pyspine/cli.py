from __future__ import annotations

import argparse
from pathlib import Path

from pyspine.core.animation import sample_clip
from pyspine.core.solver import solve_pose
from pyspine.core.validation import validate_project
from pyspine.io.jsonio import load_project, save_project
from pyspine.io.legacy import load_legacy_bundle
from pyspine.io.autoslice import autoslice_project
from pyspine.editor.workflow import validate_before_export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pyspine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="validate a pyspine project")
    p_validate.add_argument("project")

    p_sample = sub.add_parser("sample", help="print solved pose for a clip/frame")
    p_sample.add_argument("project")
    p_sample.add_argument("clip")
    p_sample.add_argument("frame", type=float)

    p_editor = sub.add_parser("editor", help="open the pygame editor")
    p_editor.add_argument("project")

    p_new = sub.add_parser("new", help="create an empty pyspine project from a sprite sheet PNG")
    p_new.add_argument("image")
    p_new.add_argument("output")

    p_import = sub.add_parser("import-legacy", help="convert legacy multi-file data into pyspine JSON")
    p_import.add_argument("sprites")
    p_import.add_argument("output")
    p_import.add_argument("--assembly")
    p_import.add_argument("--animation")
    p_import.add_argument("--image")
    p_import.add_argument("--angles", choices=["degrees", "radians"], default="degrees")

    p_autoslice = sub.add_parser("autoslice", help="make a first-pass project from non-transparent PNG islands")
    p_autoslice.add_argument("image")
    p_autoslice.add_argument("output")
    p_autoslice.add_argument("--min-area", type=int, default=50)
    p_autoslice.add_argument("--padding", type=int, default=1)
    p_autoslice.add_argument("--prefix", default="part")

    p_pack = sub.add_parser("export-pack", help="export a standalone runtime bundle directory or .zip")
    p_pack.add_argument("project")
    p_pack.add_argument("output")
    p_pack.add_argument("--dir", action="store_true", help="force directory output even if the name ends in .zip")
    p_pack.add_argument("--zip", action="store_true", help="force zip output")

    p_runtime_json = sub.add_parser("export-runtime-json", help="export normalized runtime JSON")
    p_runtime_json.add_argument("project")
    p_runtime_json.add_argument("output")

    p_frames = sub.add_parser("export-frames", help="export a clip as numbered PNG frames")
    p_frames.add_argument("project")
    p_frames.add_argument("clip")
    p_frames.add_argument("output_dir")
    _add_frame_args(p_frames)
    p_frames.add_argument("--prefix", default="frame")

    p_strip = sub.add_parser("export-strip", help="export a clip as a horizontal or vertical PNG sprite strip")
    p_strip.add_argument("project")
    p_strip.add_argument("clip")
    p_strip.add_argument("output_png")
    _add_frame_args(p_strip)
    p_strip.add_argument("--vertical", action="store_true")

    p_gif = sub.add_parser("export-gif", help="export a clip as an animated GIF preview")
    p_gif.add_argument("project")
    p_gif.add_argument("clip")
    p_gif.add_argument("output_gif")
    _add_frame_args(p_gif)

    p_play = sub.add_parser("runtime-play", help="play a project or packed bundle with the tiny pygame runtime")
    p_play.add_argument("project_or_bundle")
    p_play.add_argument("clip", nargs="?")
    p_play.add_argument("--width", type=int, default=960)
    p_play.add_argument("--height", type=int, default=640)

    p_ik = sub.add_parser("demo-ik", help="write a project with one two-bone IK keyframe applied")
    p_ik.add_argument("project")
    p_ik.add_argument("output")
    p_ik.add_argument("--clip", default="ik_test")
    p_ik.add_argument("--upper", default="left_bicep_01")
    p_ik.add_argument("--lower", default="left_forearm_01")
    p_ik.add_argument("--end-point", default="left_wrist")
    p_ik.add_argument("--frame", type=float, default=6.0)
    p_ik.add_argument("--target-x", type=float, default=45.0)
    p_ik.add_argument("--target-y", type=float, default=65.0)
    p_ik.add_argument("--bend", type=int, default=-1)

    p_lock = sub.add_parser("demo-footlock", help="write a project with root x/y keys to pin a selected point")
    p_lock.add_argument("project")
    p_lock.add_argument("output")
    p_lock.add_argument("--clip", default="walk_test")
    p_lock.add_argument("--root", default="shoulders_01")
    p_lock.add_argument("--instance", default="left_foot_01")
    p_lock.add_argument("--point", default="left_ankle")
    p_lock.add_argument("--start", type=float, default=0.0)
    p_lock.add_argument("--end", type=float, default=6.0)
    p_lock.add_argument("--step", type=float, default=1.0)

    p_plants = sub.add_parser("detect-plants", help="print low-motion planted ranges for a point")
    p_plants.add_argument("project")
    p_plants.add_argument("clip")
    p_plants.add_argument("instance")
    p_plants.add_argument("point")
    p_plants.add_argument("--threshold", type=float, default=0.35)
    p_plants.add_argument("--min-frames", type=float, default=2.0)

    args = parser.parse_args(argv)

    if args.cmd == "validate":
        project = load_project(args.project)
        warnings = validate_project(project)
        print("OK")
        for warning in warnings:
            print("warning:", warning)
        return 0

    if args.cmd == "sample":
        project = load_project(args.project)
        overrides = sample_clip(project, args.clip, args.frame)
        poses = solve_pose(project, overrides)
        for name, pose in poses.items():
            print(f"{name}: anchor=({pose.anchor.x:.2f},{pose.anchor.y:.2f}) top_left=({pose.top_left.x:.2f},{pose.top_left.y:.2f}) rot={pose.rotation:.2f}")
        return 0

    if args.cmd == "editor":
        from pyspine.editor.app import run_editor

        run_editor(args.project)
        return 0

    if args.cmd == "new":
        from pyspine.core.model import Project, SpriteSheet
        output = Path(args.output)
        image = Path(args.image)
        try:
            image_ref = image.relative_to(output.parent).as_posix()
        except ValueError:
            image_ref = image.as_posix()
        project = Project(sheet=SpriteSheet(image=image_ref))
        save_project(project, output)
        print(f"wrote {output}")
        return 0

    if args.cmd == "import-legacy":
        project = load_legacy_bundle(args.sprites, args.assembly, args.animation, image=args.image, angle_mode=args.angles)
        save_project(project, args.output)
        print(f"wrote {args.output}")
        return 0

    if args.cmd == "autoslice":
        output = Path(args.output)
        project = autoslice_project(
            args.image,
            min_area=args.min_area,
            padding=args.padding,
            prefix=args.prefix,
            relative_to=output.parent,
        )
        save_project(project, output)
        print(f"wrote {output}")
        return 0

    if args.cmd == "export-pack":
        from pyspine.exporting.bundle import export_packed_bundle

        _ensure_export_ok(args.project)
        as_zip = True if args.zip else False if args.dir else None
        out = export_packed_bundle(args.project, args.output, as_zip=as_zip)
        print(f"wrote {out}")
        return 0

    if args.cmd == "export-runtime-json":
        from pyspine.exporting.bundle import export_runtime_json

        _ensure_export_ok(args.project)
        out = export_runtime_json(args.project, args.output)
        print(f"wrote {out}")
        return 0

    if args.cmd == "export-frames":
        from pyspine.exporting.frames import export_clip_frames

        _ensure_export_ok(args.project)
        result = export_clip_frames(args.project, args.clip, args.output_dir, start=args.start, end=args.end, step=args.step, margin=args.margin, prefix=args.prefix)
        print(f"wrote {len(result.frames)} frames to {result.output} ({result.width}x{result.height})")
        return 0

    if args.cmd == "export-strip":
        from pyspine.exporting.frames import export_clip_strip

        _ensure_export_ok(args.project)
        out = export_clip_strip(args.project, args.clip, args.output_png, start=args.start, end=args.end, step=args.step, margin=args.margin, vertical=args.vertical)
        print(f"wrote {out}")
        return 0

    if args.cmd == "export-gif":
        from pyspine.exporting.frames import export_clip_gif

        _ensure_export_ok(args.project)
        out = export_clip_gif(args.project, args.clip, args.output_gif, start=args.start, end=args.end, step=args.step, margin=args.margin)
        print(f"wrote {out}")
        return 0

    if args.cmd == "runtime-play":
        from pyspine.runtime.demo import run_runtime_demo

        run_runtime_demo(args.project_or_bundle, args.clip, width=args.width, height=args.height)
        return 0

    if args.cmd == "demo-ik":
        from pyspine.core.geometry import Vec2
        from pyspine.editor.animation_quality import two_bone_ik_keyframes

        project = load_project(args.project)
        cmd = two_bone_ik_keyframes(
            project,
            args.clip,
            args.upper,
            args.lower,
            Vec2(args.target_x, args.target_y),
            args.frame,
            end_point=args.end_point,
            bend=args.bend,
        )
        cmd.apply(project)
        if args.clip in project.clips:
            project.clips[args.clip].length = max(project.clips[args.clip].length, args.frame + 6)
        save_project(project, args.output)
        print(f"wrote {args.output}; IK keyed {args.upper}->{args.lower}.{args.end_point} at frame {args.frame:g}")
        return 0

    if args.cmd == "demo-footlock":
        from pyspine.editor.animation_quality import foot_lock_keyframes

        project = load_project(args.project)
        cmd = foot_lock_keyframes(
            project,
            args.clip,
            args.root,
            args.instance,
            args.point,
            args.start,
            args.end,
            step=args.step,
        )
        cmd.apply(project)
        save_project(project, args.output)
        print(f"wrote {args.output}; locked {args.instance}.{args.point} from {args.start:g} to {args.end:g}")
        return 0

    if args.cmd == "detect-plants":
        from pyspine.editor.animation_quality import detect_plant_ranges

        project = load_project(args.project)
        ranges = detect_plant_ranges(project, args.clip, args.instance, args.point, threshold=args.threshold, min_frames=args.min_frames)
        if not ranges:
            print("no planted ranges detected")
        else:
            for r in ranges:
                print(f"{r.start:g}-{r.end:g} max_speed={r.max_speed:.4f}")
        return 0

    raise AssertionError(args.cmd)


def _ensure_export_ok(project_path: str) -> None:
    project = load_project(project_path)
    errors, warnings = validate_before_export(project, project_path)
    if errors:
        raise SystemExit("export blocked by validation errors:\n" + "\n".join(errors))
    for warning in warnings:
        print("warning:", warning)


def _add_frame_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--step", type=float, default=1.0)
    parser.add_argument("--margin", type=int, default=8)


if __name__ == "__main__":
    raise SystemExit(main())
