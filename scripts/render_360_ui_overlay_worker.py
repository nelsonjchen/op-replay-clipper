#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from renderers import path_overlay_360


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render transparent openpilot UI overlays for the 360-ui renderer.")
    parser.add_argument("route")
    parser.add_argument("start_seconds", type=int)
    parser.add_argument("length_seconds", type=int)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--openpilot-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--frame-width", type=int, required=True)
    parser.add_argument("--frame-height", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path_overlay_360.add_openpilot_to_sys_path(args.openpilot_dir)
    segments = path_overlay_360.segment_numbers(args.start_seconds, args.length_seconds)
    messages_by_segment = path_overlay_360.load_segment_messages(args.data_dir, args.route, segments)
    steps = path_overlay_360.build_openpilot_ui_overlay_steps(
        messages_by_segment,
        start_seconds=args.start_seconds,
        length_seconds=args.length_seconds,
    )
    result = path_overlay_360.generate_openpilot_ui_overlay_png_sequence(
        args.output_dir,
        steps,
        frame_width=args.frame_width,
        frame_height=args.frame_height,
        frame_count=args.length_seconds * path_overlay_360.FRAMERATE,
    )
    print(
        "Overlay frames: "
        f"{result.rendered_count} rendered, "
        f"{result.reused_count} reused, "
        f"{result.frame_count} total"
    )
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
