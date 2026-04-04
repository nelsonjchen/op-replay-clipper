from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.driver_face_eval import FaceTrackConfig, build_face_track_manifest, manifest_has_active_crop, write_face_crop_video, write_json
from core.openpilot_integration import apply_openpilot_runtime_patches, build_openpilot_compatible_data_dir
from renderers import video_renderer
from renderers.big_ui_engine import IndexedFrameQueue, _add_openpilot_to_sys_path, load_route_metadata, load_segment_messages
from renderers.driver_debug_engine import build_driver_render_steps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Internal worker for driver face evaluation crop generation.")
    parser.add_argument("--route", required=True)
    parser.add_argument("--route-or-url", required=True)
    parser.add_argument("--start-seconds", type=int, required=True)
    parser.add_argument("--length-seconds", type=int, required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--openpilot-dir", required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--track-metadata", required=True)
    parser.add_argument("--crop-clip", required=True)
    parser.add_argument("--source-clip", required=True)
    parser.add_argument("--seat-side", choices=["selected", "left", "right"], default="selected")
    parser.add_argument("--crop-target-mb", type=int, default=4)
    parser.add_argument("--accel", choices=["auto", "cpu", "videotoolbox", "nvidia"], default="auto")
    parser.add_argument("--manifest-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    openpilot_path = Path(args.openpilot_dir).resolve()
    patch_report = apply_openpilot_runtime_patches(openpilot_path)
    if patch_report.changed:
        print(f"Applied openpilot runtime patches for eval worker: {patch_report}")
    _add_openpilot_to_sys_path(openpilot_path)

    compat_root = build_openpilot_compatible_data_dir(args.route, Path(args.data_dir))
    from openpilot.tools.lib.route import Route

    route = Route(args.route, data_dir=str(compat_root))
    metadata = load_route_metadata(route)
    seg_start = args.start_seconds // 60
    seg_end = ((args.start_seconds + args.length_seconds) - 1) // 60 + 1
    messages_by_segment = load_segment_messages(route, seg_start=seg_start, seg_end=seg_end)
    render_steps = build_driver_render_steps(
        messages_by_segment,
        start=args.start_seconds,
        end=args.start_seconds + args.length_seconds,
    )

    driver_paths = route.dcamera_paths()
    frame_queue = IndexedFrameQueue(
        driver_paths[seg_start:seg_end],
        [step.camera_ref for step in render_steps],
        use_qcam=False,
    )
    try:
        manifest = build_face_track_manifest(
            render_steps,
            frame_width=frame_queue.frame_w,
            frame_height=frame_queue.frame_h,
            device_type=metadata.get("device_type", "unknown"),
            config=FaceTrackConfig(),
            seat_side=args.seat_side,
        )
        manifest.update(
            {
                "sample_id": args.sample_id,
                "category": args.category,
                "route": args.route,
                "route_or_url": args.route_or_url,
                "start_seconds": args.start_seconds,
                "length_seconds": args.length_seconds,
                "notes": args.notes,
                "seat_side": args.seat_side,
                "source_clip": args.source_clip,
                "crop_clip": args.crop_clip,
            }
        )
        crop_clip_written = manifest_has_active_crop(manifest)
        manifest["has_active_crop"] = crop_clip_written
        if crop_clip_written and not args.manifest_only:
            write_face_crop_video(
                frame_queue=frame_queue,
                manifest=manifest,
                output_path=Path(args.crop_clip),
                target_mb=args.crop_target_mb,
                length_seconds=args.length_seconds,
                acceleration=args.accel,
            )
        else:
            crop_clip_path = Path(args.crop_clip)
            if crop_clip_path.exists():
                crop_clip_path.unlink()
    finally:
        frame_queue.stop()

    write_json(Path(args.track_metadata), manifest)
    print(
        json.dumps(
            {
                "track_metadata": args.track_metadata,
                "crop_clip": args.crop_clip,
                "crop_clip_written": bool(manifest["has_active_crop"] and not args.manifest_only),
                "has_active_crop": manifest["has_active_crop"],
                "manifest_only": args.manifest_only,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
