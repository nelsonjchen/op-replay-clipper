from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np

from core.rf_detr_runtime import (
    DEFAULT_RF_DETR_MODEL_ID,
    detections_class_id,
    detections_confidence,
    detections_masks,
    detections_xyxy,
    load_rf_detr_model,
    model_device,
    predict_rf_detr,
    resolve_rf_detr_device,
    supported_rf_detr_model_ids,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a tiny standalone RF-DETR repro on a still image or short video.")
    parser.add_argument("--input", required=True, help="Input image or video path.")
    parser.add_argument("--output-dir", required=True, help="Directory for report and overlays.")
    parser.add_argument("--model-id", default=DEFAULT_RF_DETR_MODEL_ID, choices=supported_rf_detr_model_ids())
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda", "mps"))
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--crop-mode", default="full", choices=("full", "left_half", "right_half", "center_square"))
    parser.add_argument("--write-overlay-video", action="store_true")
    parser.add_argument("--bundle-path", default="", help="Optional zip bundle output path.")
    return parser.parse_args(argv)


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _crop_rect(frame_width: int, frame_height: int, crop_mode: str) -> tuple[int, int, int, int]:
    if crop_mode == "left_half":
        return 0, 0, max(1, frame_width // 2), frame_height
    if crop_mode == "right_half":
        x = max(0, frame_width // 2)
        return x, 0, max(1, frame_width - x), frame_height
    if crop_mode == "center_square":
        side = max(1, min(frame_width, frame_height))
        x = max(0, (frame_width - side) // 2)
        y = max(0, (frame_height - side) // 2)
        return x, y, side, side
    return 0, 0, frame_width, frame_height


def _resize_mask(mask: np.ndarray, *, width: int, height: int) -> np.ndarray:
    if mask.shape[0] == height and mask.shape[1] == width:
        return mask.astype(bool)
    resized = cv2.resize(mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST)
    return resized.astype(bool)


def _render_overlay(
    frame_bgr: np.ndarray,
    *,
    crop_rect: tuple[int, int, int, int],
    detections,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    overlay = frame_bgr.copy()
    x0, y0, crop_width, crop_height = crop_rect
    cv2.rectangle(overlay, (x0, y0), (x0 + crop_width - 1, y0 + crop_height - 1), (0, 255, 255), 2)
    crop_canvas = overlay[y0:y0 + crop_height, x0:x0 + crop_width]

    boxes = detections_xyxy(detections)
    class_ids = detections_class_id(detections)
    confidences = detections_confidence(detections)
    masks = detections_masks(detections)
    serialized: list[dict[str, object]] = []

    for index, box in enumerate(boxes):
        x1, y1, x2, y2 = [int(round(value)) for value in box.tolist()]
        cv2.rectangle(crop_canvas, (x1, y1), (x2, y2), (0, 220, 0), 2)
        confidence = float(confidences[index]) if confidences is not None and index < len(confidences) else None
        class_id = int(class_ids[index]) if class_ids is not None and index < len(class_ids) else None
        label = f"id={class_id}" if class_id is not None else "id=?"
        if confidence is not None:
            label = f"{label} conf={confidence:.2f}"
        cv2.putText(
            crop_canvas,
            label,
            (x1, max(18, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            2,
            lineType=cv2.LINE_AA,
        )
        mask_area = None
        if masks is not None and index < len(masks):
            mask = _resize_mask(np.asarray(masks[index]), width=crop_width, height=crop_height)
            mask_area = int(mask.sum())
            green = np.zeros_like(crop_canvas)
            green[:, :, 1] = 255
            crop_canvas[mask] = cv2.addWeighted(crop_canvas[mask], 0.35, green[mask], 0.65, 0)
        serialized.append(
            {
                "index": index,
                "box_xyxy": [x1, y1, x2, y2],
                "class_id": class_id,
                "confidence": confidence,
                "mask_area": mask_area,
            }
        )
    return overlay, serialized


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _finalize_overlay_mp4(intermediate_path: Path, output_path: Path) -> Path | None:
    if not _ffmpeg_available():
        return None
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(intermediate_path),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    intermediate_path.unlink(missing_ok=True)
    return output_path


def bundle_repro_artifacts(output_dir: Path, bundle_path: Path) -> Path:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for child in sorted(output_dir.rglob("*")):
            if child.is_file():
                archive.write(child, child.relative_to(output_dir))
    return bundle_path


def run_rf_detr_repro(
    *,
    input_path: Path,
    output_dir: Path,
    model_id: str = DEFAULT_RF_DETR_MODEL_ID,
    requested_device: str = "auto",
    threshold: float = 0.4,
    max_frames: int = 8,
    crop_mode: str = "full",
    write_overlay_video: bool = False,
) -> dict[str, object]:
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "input_path": str(input_path),
        "input_kind": "image" if _is_image_path(input_path) else "video",
        "model_id": model_id,
        "requested_device": requested_device,
        "threshold": threshold,
        "crop_mode": crop_mode,
        "max_frames": max_frames,
        "ffmpeg_available": _ffmpeg_available(),
        "environment": {
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "driver_face_benchmark_rf_detr_device": os.environ.get("DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE"),
        },
        "frames": [],
        "exception": None,
    }
    writer = None
    intermediate_video_path = output_dir / "overlay.intermediate.mp4"
    final_overlay_video_path = output_dir / "overlay.mp4"

    try:
        resolved_device = resolve_rf_detr_device(requested_device)
        report["resolved_device"] = resolved_device
        model = load_rf_detr_model(model_id, device=resolved_device)
        report["actual_model_device"] = model_device(model)

        frames: list[np.ndarray] = []
        fps = 0.0
        if _is_image_path(input_path):
            frame = cv2.imread(str(input_path))
            if frame is None:
                raise RuntimeError(f"Failed to read image input: {input_path}")
            frames = [frame]
        else:
            cap = cv2.VideoCapture(str(input_path))
            try:
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
                while len(frames) < max_frames:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    frames.append(frame)
            finally:
                cap.release()
            if not frames:
                raise RuntimeError(f"Failed to read any frames from video input: {input_path}")
        report["frames_requested"] = max_frames
        report["frames_processed"] = len(frames)
        report["video_fps"] = fps

        for frame_index, frame_bgr in enumerate(frames):
            frame_height, frame_width = frame_bgr.shape[:2]
            crop_rect = _crop_rect(frame_width, frame_height, crop_mode)
            x, y, w, h = crop_rect
            crop_bgr = frame_bgr[y:y + h, x:x + w]
            crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
            started = time.perf_counter()
            detections = predict_rf_detr(model, crop_rgb, threshold=threshold)
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            overlay, serialized = _render_overlay(frame_bgr, crop_rect=crop_rect, detections=detections)
            overlay_path = output_dir / f"frame-{frame_index:03d}-overlay.png"
            cv2.imwrite(str(overlay_path), overlay)
            report["frames"].append(
                {
                    "frame_index": frame_index,
                    "elapsed_ms": elapsed_ms,
                    "crop_rect": {"x": x, "y": y, "width": w, "height": h},
                    "detections_count": len(serialized),
                    "detections": serialized,
                    "overlay_path": overlay_path.name,
                }
            )
            if write_overlay_video and report["input_kind"] == "video":
                if writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(str(intermediate_video_path), fourcc, fps or 5.0, (frame_width, frame_height))
                writer.write(overlay)
        if writer is not None:
            writer.release()
            writer = None
            finalized = _finalize_overlay_mp4(intermediate_video_path, final_overlay_video_path)
            report["overlay_video_path"] = finalized.name if finalized is not None else intermediate_video_path.name
    except Exception as exc:
        report["exception"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        raise
    finally:
        if writer is not None:
            writer.release()

        frames_report = report["frames"]
        if isinstance(frames_report, list) and frames_report:
            first = frames_report[0]
            if isinstance(first, dict):
                report["first_frame_elapsed_ms"] = first.get("elapsed_ms")
                report["first_frame_detections"] = first.get("detections_count")
            if len(frames_report) > 1 and isinstance(frames_report[1], dict):
                report["second_frame_elapsed_ms"] = frames_report[1].get("elapsed_ms")
                report["second_frame_detections"] = frames_report[1].get("detections_count")
            report["total_detections"] = sum(
                int(frame.get("detections_count", 0))
                for frame in frames_report
                if isinstance(frame, dict)
            )

        report_path = output_dir / "report.json"
        report_path.write_text(json.dumps(report, indent=2))

    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    report = run_rf_detr_repro(
        input_path=Path(args.input),
        output_dir=output_dir,
        model_id=args.model_id,
        requested_device=args.device,
        threshold=args.threshold,
        max_frames=args.max_frames,
        crop_mode=args.crop_mode,
        write_overlay_video=args.write_overlay_video,
    )
    if args.bundle_path:
        bundle_repro_artifacts(output_dir, Path(args.bundle_path))
    print(json.dumps({"report_path": str((output_dir / "report.json").resolve()), "actual_model_device": report["actual_model_device"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
