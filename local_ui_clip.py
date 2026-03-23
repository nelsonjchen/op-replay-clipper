#!/usr/bin/env python3
"""
Deprecated UI-only wrapper around the primary local CLI.

Use `local_clip.py` for the full local pipeline. This wrapper keeps the old
UI-focused command working while forcing BIG-first UI behavior.
"""

from __future__ import annotations

import argparse
import sys

import local_clip


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local_ui_clip.py",
        description="Deprecated UI-only wrapper around local_clip.py. Keeps the old UI-only workflow working with BIG-first behavior.",
    )
    return local_clip.add_common_arguments(parser, include_render_type=False)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_args)
    has_output_flag = "--output" in raw_args or "-o" in raw_args
    has_smear_flag = "--smear-seconds" in raw_args or "--smear-amount" in raw_args
    forwarded_args: list[str] = []
    if args.route:
        forwarded_args.append(args.route)
    if args.demo:
        forwarded_args.append("--demo")
    if args.start_seconds is not None:
        forwarded_args.extend(["--start-seconds", str(args.start_seconds)])
    if args.length_seconds is not None:
        forwarded_args.extend(["--length-seconds", str(args.length_seconds)])
    if args.smear_seconds != 5:
        forwarded_args.extend(["--smear-seconds", str(args.smear_seconds)])
    elif not has_smear_flag:
        forwarded_args.extend(["--smear-seconds", "3"])
    if args.jwt_token:
        forwarded_args.extend(["--jwt-token", args.jwt_token])
    if not has_output_flag:
        forwarded_args.extend(["--output", "./shared/local-ui-clip.mp4"])
    elif args.output:
        forwarded_args.extend(["--output", args.output])
    if args.video_cwd:
        forwarded_args.extend(["--video-cwd", args.video_cwd])
    if args.openpilot_dir != "./.cache/openpilot-local":
        forwarded_args.extend(["--openpilot-dir", args.openpilot_dir])
    if args.openpilot_branch != "master":
        forwarded_args.extend(["--openpilot-branch", args.openpilot_branch])
    if args.file_size_mb != 9:
        forwarded_args.extend(["--file-size-mb", str(args.file_size_mb)])
    if args.file_format != "auto":
        forwarded_args.extend(["--file-format", args.file_format])
    if args.speedhack_ratio != 1.0:
        forwarded_args.extend(["--speedhack-ratio", str(args.speedhack_ratio)])
    if args.metric:
        forwarded_args.append("--metric")
    if args.ui_mode != "auto":
        forwarded_args.extend(["--ui-mode", args.ui_mode])
    if args.ui_backend != "modern":
        forwarded_args.extend(["--ui-backend", args.ui_backend])
    if args.qcam:
        forwarded_args.append("--qcam")
    if args.windowed:
        forwarded_args.append("--windowed")
    if args.skip_openpilot_update:
        forwarded_args.append("--skip-openpilot-update")
    if args.skip_openpilot_bootstrap:
        forwarded_args.append("--skip-openpilot-bootstrap")
    if args.data_root != "./shared/data_dir":
        forwarded_args.extend(["--data-root", args.data_root])
    if args.data_dir:
        forwarded_args.extend(["--data-dir", args.data_dir])
    if args.skip_download:
        forwarded_args.append("--skip-download")
    if args.accel != "auto":
        forwarded_args.extend(["--accel", args.accel])
    if args.ntfysh:
        forwarded_args.extend(["--ntfysh", args.ntfysh])
    if args.vnc:
        forwarded_args.extend(["--vnc", args.vnc])
    if args.hidden_dongle_id:
        forwarded_args.append("--hidden-dongle-id")
    if args.nv_hardware_rendering:
        forwarded_args.append("--nv-hardware-rendering")
    if args.nv_hybrid_encoding:
        forwarded_args.append("--nv-hybrid-encoding")
    if args.nv_fast_encoding:
        forwarded_args.append("--nv-fast-encoding")
    if args.nv_direct_encoding:
        forwarded_args.append("--nv-direct-encoding")
    return local_clip.main(["ui", *forwarded_args])


if __name__ == "__main__":
    raise SystemExit(main())
