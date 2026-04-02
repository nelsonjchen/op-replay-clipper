from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.driver_face_swap import DriverFaceSwapOptions, _auto_select_source_image, default_facefusion_output_video_encoder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one driver-face benchmark candidate over a prepared sample.")
    parser.add_argument("--sample-dir", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--pixel-block-size", type=int, default=18)
    parser.add_argument("--facefusion-root")
    parser.add_argument("--facefusion-source-image")
    parser.add_argument("--facefusion-model", default="hyperswap_1b_256")
    parser.add_argument("--driver-face-donor-bank-dir", default="./assets/driver-face-donors")
    return parser.parse_args()


def _pixelize_roi(frame, rect: tuple[int, int, int, int], *, block_size: int) -> None:
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return
    roi = frame[y:y + h, x:x + w]
    if roi.size == 0:
        return
    down_w = max(1, w // max(1, block_size))
    down_h = max(1, h // max(1, block_size))
    small = cv2.resize(roi, (down_w, down_h), interpolation=cv2.INTER_LINEAR)
    pixelized = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    frame[y:y + h, x:x + w] = pixelized


def _load_rect(frame_row: dict[str, object], key: str) -> tuple[int, int, int, int] | None:
    value = frame_row.get(key)
    if not isinstance(value, dict):
        return None
    return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])


def _telemetry(frame_row: dict[str, object], key: str, default):
    telemetry = frame_row.get("telemetry", {})
    if not isinstance(telemetry, dict):
        return default
    return telemetry.get(key, default)


def _mean_skin_color_bgr(roi) -> tuple[int, int, int]:
    if roi.size == 0:
        return (180, 170, 160)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 1] > 24) & (hsv[:, :, 2] > 48)
    pixels = roi[mask]
    if pixels.size == 0:
        pixels = roi.reshape(-1, 3)
    mean = pixels.mean(axis=0)
    return tuple(int(np.clip(value, 60, 225)) for value in mean.tolist())


def _draw_surrogate_avatar(frame, rect: tuple[int, int, int, int], frame_row: dict[str, object]) -> None:
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return
    roi = frame[y:y + h, x:x + w]
    if roi.size == 0:
        return
    blur_k = max(5, (min(w, h) // 6) | 1)
    frame[y:y + h, x:x + w] = cv2.GaussianBlur(roi, (blur_k, blur_k), 0)

    skin_bgr = _mean_skin_color_bgr(roi)
    skin = tuple(int(v) for v in skin_bgr)
    hair = tuple(max(10, int(v * 0.38)) for v in skin_bgr)
    eye_dark = (28, 28, 28)
    white = (240, 240, 240)
    lip = (max(35, int(skin[0] * 0.85)), max(25, int(skin[1] * 0.55)), max(55, int(skin[2] * 0.75)))

    yaw = float((_telemetry(frame_row, "face_orientation", [0.0, 0.0, 0.0]) or [0.0, 0.0, 0.0])[1] or 0.0)
    pitch = float((_telemetry(frame_row, "face_orientation", [0.0, 0.0, 0.0]) or [0.0, 0.0, 0.0])[0] or 0.0)
    left_blink = float(_telemetry(frame_row, "left_blink_prob", 0.0) or 0.0)
    right_blink = float(_telemetry(frame_row, "right_blink_prob", 0.0) or 0.0)
    sunglasses = float(_telemetry(frame_row, "sunglasses_prob", 0.0) or 0.0)

    center = (x + (w // 2), y + (h // 2))
    face_axes = (max(12, int(w * 0.31)), max(14, int(h * 0.37)))
    face_center = (center[0] + int(yaw * w * 0.08), center[1] + int(pitch * h * 0.04))

    cv2.ellipse(frame, face_center, face_axes, 0, 0, 360, skin, -1, cv2.LINE_AA)
    cv2.ellipse(
        frame,
        (face_center[0], face_center[1] - int(face_axes[1] * 0.55)),
        (face_axes[0], max(6, int(face_axes[1] * 0.42))),
        0,
        180,
        360,
        hair,
        -1,
        cv2.LINE_AA,
    )

    eye_y = face_center[1] - int(face_axes[1] * 0.12)
    eye_offset_x = int(face_axes[0] * 0.42)
    iris_shift_x = int(np.clip(yaw, -0.9, 0.9) * face_axes[0] * 0.10)
    iris_shift_y = int(np.clip(pitch, -0.9, 0.9) * face_axes[1] * 0.06)
    eye_rx = max(6, int(face_axes[0] * 0.18))
    eye_ry = max(3, int(face_axes[1] * 0.08))

    if sunglasses > 0.45:
        glass_y1 = eye_y - eye_ry - 6
        glass_y2 = eye_y + eye_ry + 6
        left_glass = (face_center[0] - eye_offset_x - eye_rx - 4, glass_y1, eye_rx * 2 + 8, glass_y2 - glass_y1)
        right_glass = (face_center[0] + eye_offset_x - eye_rx - 4, glass_y1, eye_rx * 2 + 8, glass_y2 - glass_y1)
        for gx, gy, gw, gh in (left_glass, right_glass):
            cv2.rectangle(frame, (gx, gy), (gx + gw, gy + gh), (18, 18, 18), -1)
            cv2.rectangle(frame, (gx, gy), (gx + gw, gy + gh), (90, 90, 90), 2)
        cv2.line(frame, (left_glass[0] + left_glass[2], eye_y), (right_glass[0], eye_y), (50, 50, 50), 2)
    else:
        for eye_center_x, blink in ((face_center[0] - eye_offset_x, left_blink), (face_center[0] + eye_offset_x, right_blink)):
            if blink > 0.45:
                cv2.line(frame, (eye_center_x - eye_rx, eye_y), (eye_center_x + eye_rx, eye_y), eye_dark, 2, cv2.LINE_AA)
            else:
                cv2.ellipse(frame, (eye_center_x, eye_y), (eye_rx, eye_ry), 0, 0, 360, white, -1, cv2.LINE_AA)
                cv2.circle(
                    frame,
                    (eye_center_x + iris_shift_x, eye_y + iris_shift_y),
                    max(2, eye_ry),
                    eye_dark,
                    -1,
                    cv2.LINE_AA,
                )

    nose_top = (face_center[0], face_center[1] - int(face_axes[1] * 0.02))
    nose_bottom = (face_center[0] + int(yaw * face_axes[0] * 0.08), face_center[1] + int(face_axes[1] * 0.16))
    cv2.line(frame, nose_top, nose_bottom, tuple(max(40, int(v * 0.75)) for v in skin), 2, cv2.LINE_AA)

    mouth_y = face_center[1] + int(face_axes[1] * 0.26)
    mouth_w = max(10, int(face_axes[0] * 0.34))
    cv2.ellipse(frame, (face_center[0], mouth_y), (mouth_w // 2, max(3, int(face_axes[1] * 0.05))), 0, 0, 180, lip, 2, cv2.LINE_AA)


def _score_sample(track: dict[str, object]) -> dict[str, str]:
    frames = list(track.get("frames", []))
    held_frames = sum(1 for frame in frames if int(frame.get("held_without_detection", 0) or 0) > 0)
    missing_padded = sum(1 for frame in frames if frame.get("padded_box") is None)
    identity_leakage = "low" if missing_padded < max(2, len(frames) // 8) else "medium"
    temporal_stability = "medium" if held_frames else "high"
    gaze_readability = "low"
    pose_preservation = "low"
    occlusion_robustness = "medium" if held_frames else "low"
    runtime_complexity = "highly practical"
    return {
        "identity_leakage": identity_leakage,
        "temporal_stability": temporal_stability,
        "gaze_eye_readability": gaze_readability,
        "pose_preservation": pose_preservation,
        "occlusion_robustness": occlusion_robustness,
        "runtime_complexity": runtime_complexity,
    }


def _score_surrogate_sample(track: dict[str, object]) -> dict[str, str]:
    frames = list(track.get("frames", []))
    held_frames = sum(1 for frame in frames if int(frame.get("held_without_detection", 0) or 0) > 0)
    return {
        "identity_leakage": "low",
        "temporal_stability": "medium" if held_frames else "high",
        "gaze_eye_readability": "medium",
        "pose_preservation": "medium",
        "occlusion_robustness": "medium" if held_frames else "low",
        "runtime_complexity": "practical local baseline",
    }


def _score_facefusion_sample() -> dict[str, str]:
    return {
        "identity_leakage": "manual review",
        "temporal_stability": "manual review",
        "gaze_eye_readability": "manual review",
        "pose_preservation": "manual review",
        "occlusion_robustness": "manual review",
        "runtime_complexity": "heavy creator stack",
    }


def _run_facefusion_crop_swap(
    *,
    sample_dir: Path,
    output_path: Path,
    facefusion_root: Path,
    source_image: Path,
    model_name: str,
    preset: str = "quality",
) -> tuple[int, float]:
    output_video_encoder = default_facefusion_output_video_encoder()
    facefusion_python = facefusion_root / ".venv/bin/python"
    facefusion_entry = facefusion_root / "facefusion.py"
    target_path = sample_dir / "face-crop.mp4"
    jobs_path = sample_dir / "facefusion-jobs"
    temp_path = sample_dir / "facefusion-temp"

    if not facefusion_python.exists():
        raise RuntimeError(f"FaceFusion interpreter not found at {facefusion_python}")
    if not facefusion_entry.exists():
        raise RuntimeError(f"FaceFusion entry point not found at {facefusion_entry}")
    if not source_image.exists():
        raise RuntimeError(f"FaceFusion source image not found at {source_image}")
    if not target_path.exists():
        raise RuntimeError(f"FaceFusion target clip not found at {target_path}")

    output_path.unlink(missing_ok=True)
    jobs_path.mkdir(parents=True, exist_ok=True)
    temp_path.mkdir(parents=True, exist_ok=True)

    command = [
        str(facefusion_python),
        str(facefusion_entry),
        "headless-run",
        "--jobs-path",
        str(jobs_path),
        "--temp-path",
        str(temp_path),
        "--processors",
        "face_swapper",
        "--face-swapper-model",
        model_name,
        "--face-swapper-weight",
        "1.0",
        "--face-selector-mode",
        "one",
        "--face-detector-model",
        "yunet",
        "--face-detector-score",
        "0.35",
        "--face-mask-padding",
        "8",
        "8",
        "8",
        "8",
        "--execution-providers",
        "coreml",
        "cpu",
        "--video-memory-strategy",
        "tolerant",
        "--system-memory-limit",
        "0",
        "-s",
        str(source_image),
        "-t",
        str(target_path),
        "-o",
        str(output_path),
        "--log-level",
        "info",
    ]
    if preset == "fast":
        command.extend(
            [
                "--face-swapper-pixel-boost",
                "256x256",
                "--face-mask-types",
                "box",
                "--face-mask-blur",
                "0.1",
                "--execution-thread-count",
                "4",
                "--output-video-encoder",
                output_video_encoder,
                "--output-video-quality",
                "75",
                "--output-video-preset",
                "veryfast",
                "--temp-frame-format",
                "jpeg",
            ]
        )
    else:
        command.extend(
            [
                "--face-swapper-pixel-boost",
                "512x512",
                "--face-mask-types",
                "box",
                "occlusion",
                "--face-mask-blur",
                "0.15",
                "--execution-thread-count",
                "1",
                "--output-video-encoder",
                output_video_encoder,
                "--output-video-quality",
                "85",
                "--output-video-preset",
                "fast",
                "--temp-frame-format",
                "png",
            ]
        )
    env = dict(os.environ)
    env["SYSTEM_VERSION_COMPAT"] = "0"
    started = time.perf_counter()
    subprocess.run(command, check=True, cwd=facefusion_root, env=env)
    runtime_seconds = time.perf_counter() - started

    capture = cv2.VideoCapture(str(output_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open FaceFusion output clip: {output_path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    finally:
        capture.release()
    return frame_count, runtime_seconds


def _append_evaluation_markdown(path: Path, *, candidate_id: str, report: dict[str, object], output_name: str) -> None:
    scores = report["scores"]
    if candidate_id == "dm-box-pixelize":
        behavior = "Pixelizes the DM-guided padded ROI on the full-frame driver clip."
    elif candidate_id == "surrogate-avatar":
        behavior = "Blurs the DM-guided ROI and overlays a stylized surrogate face using tone plus simple blink/yaw cues."
    elif candidate_id == "facefusion-hyperswap":
        behavior = "Runs FaceFusion on the prepared `face-crop.mp4` clip using a generic donor image and the configured hyperswap face swapper."
    elif candidate_id == "facefusion-auto-best-match":
        behavior = "Auto-selects a same-tone donor from the donor bank on a short selection clip, then runs fast FaceFusion with that donor."
    else:
        behavior = "Processes the DM-guided ROI on the full-frame driver clip."
    notes = f"Generated `{output_name}` in {report['runtime_seconds']:.2f}s. {behavior}"
    with path.open("a") as handle:
        handle.write(
            f"| {candidate_id} | {scores['identity_leakage']} | {scores['temporal_stability']} | "
            f"{scores['gaze_eye_readability']} | {scores['pose_preservation']} | "
            f"{scores['occlusion_robustness']} | {scores['runtime_complexity']} | {notes} |\n"
        )


def main() -> int:
    args = parse_args()
    sample_dir = Path(args.sample_dir).resolve()
    track_path = sample_dir / "face-track.json"
    source_path = sample_dir / "driver-source.mp4"
    evaluation_path = sample_dir / "evaluation.md"
    output_path = sample_dir / f"{args.candidate_id}.mp4"
    report_path = sample_dir / f"{args.candidate_id}.json"

    track = json.loads(track_path.read_text())
    frames = list(track["frames"])

    if args.candidate_id in {"facefusion-hyperswap", "facefusion-auto-best-match"}:
        if not args.facefusion_root:
            raise RuntimeError("FaceFusion candidate requires --facefusion-root")
        if args.candidate_id == "facefusion-hyperswap" and not args.facefusion_source_image:
            raise RuntimeError("Manual FaceFusion candidate requires --facefusion-source-image")
        source_image: Path
        extra_report_fields: dict[str, object] = {}
        preset = "quality"
        if args.candidate_id == "facefusion-auto-best-match":
            selection_report_path = sample_dir / "facefusion-auto-best-match-selection.json"
            source_image, _report_path = _auto_select_source_image(
                sample_dir=sample_dir,
                options=DriverFaceSwapOptions(
                    mode="facefusion",
                    facefusion_root=str(Path(args.facefusion_root).resolve()),
                    facefusion_model=args.facefusion_model,
                    preset="fast",
                    selection_mode="auto_best_match",
                    donor_bank_dir=str(Path(args.driver_face_donor_bank_dir).resolve()),
                ),
                output_path=selection_report_path,
            )
            selection_report = json.loads(selection_report_path.read_text())
            extra_report_fields = {
                "selection_report": str(selection_report_path),
                "selection_timings": selection_report.get("timings", {}),
                "selected_donor_image": selection_report.get("selected_donor_image"),
            }
            preset = "fast"
        else:
            source_image = Path(args.facefusion_source_image).resolve()
        frame_count, runtime_seconds = _run_facefusion_crop_swap(
            sample_dir=sample_dir,
            output_path=output_path,
            facefusion_root=Path(args.facefusion_root).resolve(),
            source_image=source_image,
            model_name=args.facefusion_model,
            preset=preset,
        )
        report = {
            "candidate_id": args.candidate_id,
            "sample_dir": str(sample_dir),
            "source_clip": str(sample_dir / "face-crop.mp4"),
            "output_clip": str(output_path),
            "frames_processed": frame_count,
            "runtime_seconds": runtime_seconds,
            "scores": _score_facefusion_sample(),
            "source_image": str(source_image),
            "facefusion_model": args.facefusion_model,
            **extra_report_fields,
        }
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        _append_evaluation_markdown(
            evaluation_path,
            candidate_id=args.candidate_id,
            report=report,
            output_name=output_path.name,
        )
        print(json.dumps({"output_clip": str(output_path), "report": str(report_path)}))
        return 0

    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open source clip: {source_path}")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 20.0)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Failed to create output clip: {output_path}")

    started = time.perf_counter()
    frame_count = 0
    try:
        for frame_row in frames:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Video ended early at frame {frame_count}")
            rect = _load_rect(frame_row, "padded_box") or _load_rect(frame_row, "crop_rect")
            if rect is not None:
                if args.candidate_id == "dm-box-pixelize":
                    _pixelize_roi(frame, rect, block_size=args.pixel_block_size)
                elif args.candidate_id == "surrogate-avatar":
                    _draw_surrogate_avatar(frame, rect, frame_row)
                else:
                    raise ValueError(f"Unsupported candidate id: {args.candidate_id}")
            writer.write(frame)
            frame_count += 1
    finally:
        capture.release()
        writer.release()
    runtime_seconds = time.perf_counter() - started

    scores = _score_sample(track) if args.candidate_id == "dm-box-pixelize" else _score_surrogate_sample(track)
    report = {
        "candidate_id": args.candidate_id,
        "sample_dir": str(sample_dir),
        "source_clip": str(source_path),
        "output_clip": str(output_path),
        "frames_processed": frame_count,
        "runtime_seconds": runtime_seconds,
        "scores": scores,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    _append_evaluation_markdown(
        evaluation_path,
        candidate_id=args.candidate_id,
        report=report,
        output_name=output_path.name,
    )
    print(json.dumps({"output_clip": str(output_path), "report": str(report_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
