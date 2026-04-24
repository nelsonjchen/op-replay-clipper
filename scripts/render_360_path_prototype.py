#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.openpilot_config import default_local_openpilot_root
from renderers import path_overlay_360
from renderers.video_renderer import (
    OutputFormat,
    _inject_360_metadata,
    _probe_video_dimensions,
    select_video_acceleration,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental 360 renderer that paints openpilot model path overlays into "
            "the wide-road fisheye half before v360 equirect conversion."
        )
    )
    parser.add_argument("route", help="Route ID in dongle|YYYY-MM-DD--HH-MM-SS form")
    parser.add_argument("start_seconds", type=int)
    parser.add_argument("length_seconds", type=int)
    parser.add_argument("--data-dir", required=True, help="Prepared route data directory containing route segment folders")
    parser.add_argument("--openpilot-dir", default=default_local_openpilot_root())
    parser.add_argument("-o", "--output", default="./shared/360-path-prototype.mp4")
    parser.add_argument(
        "--overlay-mode",
        choices=["path", "ui"],
        default="path",
        help="Overlay to composite onto the wide fisheye before 360 conversion.",
    )
    parser.add_argument("--file-size-mb", type=int, default=25)
    parser.add_argument("--file-format", choices=["h264", "hevc"], default="hevc")
    parser.add_argument("--accel", choices=["auto", "cpu", "videotoolbox", "nvidia"], default="auto")
    parser.add_argument(
        "--overlay-dir",
        help="Optional directory for generated transparent overlay PNGs. Defaults to a temporary directory.",
    )
    parser.add_argument("--keep-overlays", action="store_true", help="Keep generated overlay PNGs when using a temp dir")
    args = parser.parse_args()
    if args.length_seconds <= 0:
        parser.error("length_seconds must be positive")
    return args


def _video_dimensions_or_fail(path: Path, label: str) -> tuple[int, int]:
    dimensions = _probe_video_dimensions(path)
    if dimensions is None:
        raise RuntimeError(f"Could not probe {label} dimensions from {path}")
    return dimensions


def _inject_360_metadata_with_fallback(output_path: Path) -> None:
    try:
        _inject_360_metadata(output_path)
        return
    except ModuleNotFoundError as exc:
        if exc.name != "spatialmedia":
            raise

    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "from renderers.video_renderer import _inject_360_metadata; "
                "_inject_360_metadata(Path(__import__('sys').argv[1]))"
            ),
            str(output_path),
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    args = parse_args()
    openpilot_dir = Path(args.openpilot_dir).expanduser().resolve()
    path_overlay_360.add_openpilot_to_sys_path(openpilot_dir)

    data_dir = Path(args.data_dir).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    segments = path_overlay_360.segment_numbers(args.start_seconds, args.length_seconds)
    first_segment = segments[0]
    wide_probe = path_overlay_360.segment_file_path(data_dir, args.route, first_segment, "ecamera.hevc")
    driver_probe = path_overlay_360.segment_file_path(data_dir, args.route, first_segment, "dcamera.hevc")
    wide_width, wide_height = _video_dimensions_or_fail(wide_probe, "wide road camera")
    _video_dimensions_or_fail(driver_probe, "driver camera")

    overlay_root: Path
    temp_root: Path | None = None
    if args.overlay_dir:
        overlay_root = Path(args.overlay_dir).expanduser().resolve()
        overlay_root.mkdir(parents=True, exist_ok=True)
    else:
        temp_root = Path(tempfile.mkdtemp(prefix="360-path-overlay-"))
        overlay_root = temp_root

    ui_render_succeeded = False
    try:
        print(f"Loading route logs and rendering {args.overlay_mode} overlays...")
        messages_by_segment = path_overlay_360.load_segment_messages(data_dir, args.route, segments)
        if args.overlay_mode == "ui":
            overlays = path_overlay_360.build_openpilot_ui_overlay_steps(
                messages_by_segment,
                start_seconds=args.start_seconds,
                length_seconds=args.length_seconds,
            )
            overlay_result = path_overlay_360.generate_openpilot_ui_overlay_png_sequence(
                overlay_root,
                overlays,
                frame_width=wide_width,
                frame_height=wide_height,
                frame_count=args.length_seconds * path_overlay_360.FRAMERATE,
            )
        else:
            overlays = path_overlay_360.build_path_overlay_frames(
                messages_by_segment,
                start_seconds=args.start_seconds,
                length_seconds=args.length_seconds,
                frame_width=wide_width,
                frame_height=wide_height,
            )
            overlay_result = path_overlay_360.generate_overlay_png_sequence(
                overlay_root,
                overlays,
                frame_width=wide_width,
                frame_height=wide_height,
                frame_count=args.length_seconds * path_overlay_360.FRAMERATE,
            )
        print(
            "Overlay frames: "
            f"{overlay_result.rendered_count} rendered, "
            f"{overlay_result.reused_count} reused, "
            f"{overlay_result.frame_count} total"
        )

        driver_input = path_overlay_360.concat_string(data_dir, args.route, segments, "dcamera.hevc")
        wide_input = path_overlay_360.concat_string(data_dir, args.route, segments, "ecamera.hevc")
        filter_complex = path_overlay_360.build_360_path_filter_complex(
            start_seconds=args.start_seconds,
            length_seconds=args.length_seconds,
            wide_height=wide_height,
        )
        accel = select_video_acceleration(args.accel, args.file_format)
        command = path_overlay_360.build_360_path_ffmpeg_command(
            driver_input=driver_input,
            wide_input=wide_input,
            overlay_pattern=overlay_result.pattern,
            filter_complex=filter_complex,
            accel=accel,
            target_mb=args.file_size_mb,
            length_seconds=args.length_seconds,
            output_path=str(output_path),
        )
        path_overlay_360.run_logged(command)
        _inject_360_metadata_with_fallback(output_path)
        print(f"Wrote spherical 360 path prototype: {output_path}")
        if args.overlay_mode == "ui":
            ui_render_succeeded = True
    finally:
        if temp_root is not None and temp_root.exists() and not args.keep_overlays:
            shutil.rmtree(temp_root, ignore_errors=True)

    if ui_render_succeeded:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
