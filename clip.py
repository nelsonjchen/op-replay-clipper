#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from core.clip_orchestrator import ClipRequest, RenderType, is_ui_render_type, run_clip
from core.openpilot_bootstrap import bootstrap_openpilot, ensure_openpilot_checkout
from core.openpilot_config import default_local_openpilot_root, default_openpilot_branch, default_openpilot_repo_url


DEMO_ROUTE = "a2a0ccea32023010|2023-07-27--13-01-19"
DEMO_START_SECONDS = 90
DEMO_LENGTH_SECONDS = 15
RENDER_TYPES: tuple[RenderType, ...] = (
    "ui",
    "ui-alt",
    "forward",
    "wide",
    "driver",
    "360",
    "forward_upon_wide",
    "360_forward_upon_wide",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Primary local CLI for openpilot replay clipping. Use this for cheap local validation before GCE."
    )
    parser.add_argument("render_type", choices=RENDER_TYPES)
    parser.add_argument("route", nargs="?", help='Comma Connect URL or route id (e.g. "dongle|route")')
    parser.add_argument("--demo", action="store_true", help="Use a known public demo route")
    parser.add_argument("-s", "--start-seconds", type=int, default=None)
    parser.add_argument("-l", "--length-seconds", type=int, default=None)
    parser.add_argument("--smear-seconds", type=int, default=5)
    parser.add_argument("-j", "--jwt-token", default="")
    parser.add_argument("-o", "--output", default="./shared/local-clip.mp4")
    parser.add_argument("--openpilot-dir", default=default_local_openpilot_root())
    parser.add_argument("--openpilot-branch", default=default_openpilot_branch())
    parser.add_argument("--openpilot-repo-url", default=default_openpilot_repo_url())
    parser.add_argument("-m", "--file-size-mb", type=int, default=9)
    parser.add_argument("--file-format", choices=["auto", "h264", "hevc"], default="auto")
    parser.add_argument("--forward-upon-wide-h", type=float, default=2.2)
    parser.add_argument("--qcam", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--skip-openpilot-update", action="store_true")
    parser.add_argument("--skip-openpilot-bootstrap", action="store_true")
    parser.add_argument("--data-root", default="./shared/data_dir")
    parser.add_argument("--data-dir", default="", help="Explicit data dir. If unset, uses --data-root/<dongle-id>.")
    parser.add_argument("--skip-download", action="store_true", help="Reuse already-downloaded route data.")
    parser.add_argument("--accel", choices=["auto", "cpu", "videotoolbox", "nvidia"], default="auto")
    return parser


def _resolve_route_and_timing(args: argparse.Namespace) -> tuple[str, int, int]:
    if args.demo:
        start_seconds = DEMO_START_SECONDS if args.start_seconds is None else args.start_seconds
        length_seconds = DEMO_LENGTH_SECONDS if args.length_seconds is None else args.length_seconds
        return DEMO_ROUTE, start_seconds, length_seconds
    if not args.route:
        raise SystemExit("route is required unless --demo is used")
    start_seconds = 50 if args.start_seconds is None else args.start_seconds
    length_seconds = 20 if args.length_seconds is None else args.length_seconds
    return args.route, start_seconds, length_seconds


def _prepare_openpilot_if_needed(args: argparse.Namespace) -> str:
    openpilot_path = Path(args.openpilot_dir).expanduser().resolve()
    openpilot_dir = str(openpilot_path)
    if not is_ui_render_type(args.render_type):
        return openpilot_dir
    if args.skip_openpilot_update and not openpilot_path.exists():
        raise SystemExit(
            f"Openpilot checkout not found at {openpilot_dir}. Remove --skip-openpilot-update or point --openpilot-dir at an existing checkout."
        )
    if not args.skip_openpilot_update:
        ensure_openpilot_checkout(
            openpilot_path,
            branch=args.openpilot_branch,
            repo_url=args.openpilot_repo_url,
        )
    if not args.skip_openpilot_bootstrap:
        bootstrap_openpilot(openpilot_path)
    elif not (openpilot_path / ".venv/bin/python").exists():
        raise SystemExit(
            f"Openpilot is not bootstrapped at {openpilot_dir}. Remove --skip-openpilot-bootstrap or run bootstrap first."
        )
    return openpilot_dir


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    route, start_seconds, length_seconds = _resolve_route_and_timing(args)
    openpilot_dir = _prepare_openpilot_if_needed(args)

    try:
        result = run_clip(
            ClipRequest(
                render_type=args.render_type,
                route_or_url=route,
                start_seconds=start_seconds,
                length_seconds=length_seconds,
                target_mb=args.file_size_mb,
                file_format=args.file_format,
                output_path=args.output,
                smear_seconds=args.smear_seconds if is_ui_render_type(args.render_type) else 0,
                jwt_token=args.jwt_token or None,
                forward_upon_wide_h=args.forward_upon_wide_h,
                explicit_data_dir=args.data_dir or None,
                data_root=args.data_root,
                execution_context="local",
                minimum_length_seconds=1,
                maximum_length_seconds=300,
                local_acceleration=args.accel,
                openpilot_dir=openpilot_dir,
                qcam=args.qcam,
                headless=not args.windowed,
                skip_download=args.skip_download,
            )
        )
    except ModuleNotFoundError as error:
        raise SystemExit(
            f"Missing local dependency: {error.name}. Run `uv sync` and then use `uv run python clip.py ...`."
        ) from error

    print(f"Wrote clip: {result.output_path}")
    if result.acceleration:
        print(f"Acceleration: {result.acceleration}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
