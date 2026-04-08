from __future__ import annotations

import argparse
import functools
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.driver_face_swap import (
    DriverFaceSwapOptions,
    _auto_select_source_image,
    _ffmpeg_encoder_available,
    _has_nvidia,
    default_facefusion_execution_providers,
    default_facefusion_output_video_encoder,
    facefusion_runtime_env,
)
from core.rf_detr_runtime import (
    DEFAULT_RF_DETR_MODEL_ID,
    default_rf_detr_device as _default_rf_detr_device,
    detections_class_id as _detections_class_id,
    detections_confidence as _detections_confidence,
    detections_masks as _detections_masks,
    detections_xyxy as _detections_xyxy,
    load_rf_detr_model as _load_rf_detr_model,
    model_device as _rf_detr_model_device,
    predict_rf_detr as _predict_rf_detr,
)

RF_DETR_CANDIDATE_IDS = {
    "rf-detr-passenger-blur",
    "rf-detr-passenger-silhouette",
}
RF_DETR_SILHOUETTE_STYLE_PALETTES = {
    "silhouette": (255, 255, 255),
    "black_silhouette": (27, 27, 30),
    "ir_tint": (88, 64, 158),
}
DEFAULT_RF_DETR_THRESHOLD = 0.4
DEFAULT_RF_DETR_FRAME_STRIDE = 5
DEFAULT_RF_DETR_MASK_DILATE = 15
DEFAULT_RF_DETR_STARTUP_HOLD_FRAMES = 6
DEFAULT_RF_DETR_PASSENGER_CROP_MARGIN_RATIO = 0.10
DEFAULT_RF_DETR_MISSING_HOLD_FRAMES = 10
DEFAULT_RF_DETR_BLUR_SIZE = 271
DEFAULT_RF_DETR_BLUR_MASK_DILATE = 51
DEFAULT_RF_DETR_PROGRESS_INTERVAL_SECONDS = 5.0

DM_INPUT_SIZE = (1440.0, 960.0)
AR_OX_DRIVER_FRAME = (1928.0, 1208.0)
OS_DRIVER_FRAME = (1344.0, 760.0)
AR_OX_DRIVER_FOCAL = 567.0
OS_DRIVER_FOCAL = AR_OX_DRIVER_FOCAL * 0.75
DM_INTRINSIC_CX = DM_INPUT_SIZE[0] / 2.0
DM_INTRINSIC_CY = (DM_INPUT_SIZE[1] / 2.0) - ((AR_OX_DRIVER_FRAME[1] - DM_INPUT_SIZE[1]) / 2.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one driver-face benchmark candidate over a prepared sample.")
    parser.add_argument("--sample-dir", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--pixel-block-size", type=int, default=18)
    parser.add_argument("--facefusion-root")
    parser.add_argument("--facefusion-source-image")
    parser.add_argument("--facefusion-model", default="hyperswap_1b_256")
    parser.add_argument("--driver-face-donor-bank-dir", default="./assets/driver-face-donors")
    parser.add_argument("--rf-detr-model-id", default=DEFAULT_RF_DETR_MODEL_ID)
    parser.add_argument("--rf-detr-threshold", type=float, default=DEFAULT_RF_DETR_THRESHOLD)
    parser.add_argument("--rf-detr-frame-stride", type=int, default=DEFAULT_RF_DETR_FRAME_STRIDE)
    parser.add_argument("--rf-detr-mask-dilate", type=int, default=DEFAULT_RF_DETR_MASK_DILATE)
    parser.add_argument("--rf-detr-startup-hold-frames", type=int, default=DEFAULT_RF_DETR_STARTUP_HOLD_FRAMES)
    parser.add_argument("--rf-detr-passenger-crop-margin-ratio", type=float, default=DEFAULT_RF_DETR_PASSENGER_CROP_MARGIN_RATIO)
    parser.add_argument("--rf-detr-missing-hold-frames", type=int, default=DEFAULT_RF_DETR_MISSING_HOLD_FRAMES)
    parser.add_argument("--rf-detr-test-target-side", choices=("passenger", "driver"), default="passenger")
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


def _intermediate_output_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.intermediate{output_path.suffix}")


def _mask_intermediate_output_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.mask.intermediate{output_path.suffix}")


def _default_benchmark_data_root() -> Path:
    override = os.environ.get("DRIVER_FACE_BENCHMARK_DATA_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (REPO_ROOT / "shared/data_dir").resolve()


def _preferred_source_target_mb(length_seconds: int) -> int:
    override = os.environ.get("DRIVER_FACE_BENCHMARK_SOURCE_TARGET_MB", "").strip()
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass
    # Aim closer to the underlying raw driver-camera data rate than the tiny
    # convenience eval clip, while keeping the working clip size bounded.
    return max(24, min(128, int(np.ceil(max(1, length_seconds) * 1.25))))


def _route_data_dir_from_track(track: dict[str, object]) -> Path | None:
    route = str(track.get("route") or "").strip()
    if "|" not in route:
        return None
    dongle_id = route.split("|", 1)[0]
    return (_default_benchmark_data_root() / dongle_id).resolve()


def _raw_driver_segment_path_from_track(track: dict[str, object]) -> Path | None:
    route = str(track.get("route") or "").strip()
    if "|" not in route:
        return None
    _, route_date = route.split("|", 1)
    data_dir = _route_data_dir_from_track(track)
    if data_dir is None:
        return None
    start_seconds = int(track.get("start_seconds") or 0)
    segment = max(0, start_seconds // 60)
    candidate = data_dir / f"{route_date}--{segment}" / "dcamera.hevc"
    if candidate.exists():
        return candidate
    return None


def _resolve_preferred_source_clip(sample_dir: Path, track: dict[str, object]) -> tuple[Path, str]:
    prepared_clip = sample_dir / "driver-source.mp4"
    raw_driver_segment = _raw_driver_segment_path_from_track(track)
    route = str(track.get("route") or "").strip()
    start_seconds = int(track.get("start_seconds") or 0)
    length_seconds = int(track.get("length_seconds") or 0)

    if raw_driver_segment is None or not route or length_seconds <= 0:
        return prepared_clip, "prepared_eval_h264_clip"

    hq_clip = sample_dir / "driver-source-hq-hevc.mp4"
    if not hq_clip.exists():
        from renderers import video_renderer

        video_renderer.render_video_clip(
            video_renderer.VideoRenderOptions(
                render_type="driver",
                data_dir=str(raw_driver_segment.parent.parent),
                route_or_segment=route,
                start_seconds=start_seconds,
                length_seconds=length_seconds,
                target_mb=_preferred_source_target_mb(length_seconds),
                file_format="hevc",
                acceleration="auto",
                output_path=str(hq_clip),
            )
        )
    return hq_clip, "raw_hevc_derived_working_clip"


def _shareable_h264_encoder_args() -> list[str]:
    override = os.environ.get("DRIVER_FACE_BENCHMARK_OUTPUT_VIDEO_ENCODER", "").strip()
    encoder = override or ""
    if not encoder:
        if platform.system() == "Darwin" and _ffmpeg_encoder_available("h264_videotoolbox"):
            encoder = "h264_videotoolbox"
        elif _has_nvidia() and _ffmpeg_encoder_available("h264_nvenc"):
            encoder = "h264_nvenc"
        else:
            encoder = "libx264"

    if encoder == "h264_videotoolbox":
        return [
            "-c:v",
            "h264_videotoolbox",
            "-allow_sw",
            "1",
            "-realtime",
            "1",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
        ]
    if encoder == "h264_nvenc":
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-pix_fmt",
            "yuv420p",
        ]
    return [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
    ]


def _shareable_h264_encoder_name() -> str:
    args = _shareable_h264_encoder_args()
    return args[1]


@functools.lru_cache(maxsize=1)
def _ffmpeg_filter_names() -> frozenset[str]:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return frozenset()

    filters: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0][0] in {".", "T", "S", "|"}:
            filters.add(parts[1])
    return frozenset(filters)


def _ffmpeg_filter_available(name: str) -> bool:
    return name in _ffmpeg_filter_names()


@functools.lru_cache(maxsize=1)
def _ffmpeg_hwaccel_names() -> frozenset[str]:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-hwaccels"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return frozenset()

    names = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("Hardware acceleration methods:")
    }
    return frozenset(names)


def _rf_detr_blur_backend_preference() -> str:
    cleaned = os.environ.get("DRIVER_FACE_BENCHMARK_RF_DETR_BLUR_BACKEND", "auto").strip().lower()
    if cleaned in {"auto", "opencl", "cpu"}:
        return cleaned
    return "auto"


def _rf_detr_opencl_blur_available() -> bool:
    return (
        "opencl" in _ffmpeg_hwaccel_names()
        and _ffmpeg_filter_available("avgblur_opencl")
        and _ffmpeg_filter_available("maskedmerge")
    )


def _rf_detr_blur_backend_candidates() -> list[str]:
    preference = _rf_detr_blur_backend_preference()
    if preference == "cpu":
        return ["cpu"]
    if preference == "opencl":
        return ["opencl", "cpu"]
    if _rf_detr_opencl_blur_available():
        return ["opencl", "cpu"]
    return ["cpu"]


def _rf_detr_blur_size() -> int:
    raw = os.environ.get("DRIVER_FACE_BENCHMARK_RF_DETR_BLUR_SIZE", "").strip()
    if raw:
        try:
            return max(3, min(255, int(raw)))
        except ValueError:
            pass
    return DEFAULT_RF_DETR_BLUR_SIZE


def _rf_detr_blur_mask_dilate() -> int:
    raw = os.environ.get("DRIVER_FACE_BENCHMARK_RF_DETR_BLUR_MASK_DILATE", "").strip()
    if raw:
        try:
            return max(0, min(255, int(raw)))
        except ValueError:
            pass
    return DEFAULT_RF_DETR_BLUR_MASK_DILATE


def _rf_detr_progress_interval_seconds() -> float:
    raw = os.environ.get("DRIVER_FACE_BENCHMARK_RF_DETR_PROGRESS_INTERVAL_SECONDS", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_RF_DETR_PROGRESS_INTERVAL_SECONDS


def _rf_detr_blur_filter_graph(*, backend: str, blur_size: int | None = None) -> str:
    blur_size = _rf_detr_blur_size() if blur_size is None else blur_size
    if backend == "opencl":
        return (
            f"[0:v]format=yuv420p,split=2[base][to_blur];"
            f"[to_blur]format=nv12,hwupload,avgblur_opencl=sizeX={blur_size}:sizeY={blur_size},"
            f"hwdownload,format=nv12,format=yuv420p[blurred];"
            f"[1:v]format=gray[mask];"
            f"[base][blurred][mask]maskedmerge[out]"
        )
    if backend == "cpu":
        return (
            f"[0:v]format=yuv420p,split=2[base][to_blur];"
            f"[to_blur]avgblur=sizeX={blur_size}:sizeY={blur_size}[blurred];"
            f"[1:v]format=gray[mask];"
            f"[base][blurred][mask]maskedmerge[out]"
        )
    raise ValueError(f"Unsupported RF-DETR blur backend: {backend}")


def _finalize_shareable_mp4(intermediate_path: Path, output_path: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(intermediate_path),
        "-an",
        *_shareable_h264_encoder_args(),
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        raise RuntimeError(f"Failed to finalize shareable mp4 {output_path}: {stderr}") from exc
    finally:
        intermediate_path.unlink(missing_ok=True)


def _finalize_shareable_masked_blur_mp4(
    *,
    base_path: Path,
    mask_path: Path,
    output_path: Path,
) -> str:
    backends = _rf_detr_blur_backend_candidates()
    last_error: RuntimeError | None = None
    for backend in backends:
        command = ["ffmpeg", "-y"]
        if backend == "opencl":
            command.extend(["-init_hw_device", "opencl=ocl", "-filter_hw_device", "ocl"])
        command.extend(
            [
                "-i",
                str(base_path),
                "-i",
                str(mask_path),
                "-filter_complex",
                _rf_detr_blur_filter_graph(backend=backend),
                "-map",
                "[out]",
                "-an",
                *_shareable_h264_encoder_args(),
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return backend
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip()
            print(f"RF-DETR blur finalize backend {backend} failed; trying fallback if available: {stderr}")
            last_error = RuntimeError(f"Failed to finalize masked blur mp4 via {backend}: {stderr}")
    if last_error is None:
        raise RuntimeError(f"No RF-DETR blur backends available for {output_path}")
    raise last_error



def _load_rect(frame_row: dict[str, object], key: str) -> tuple[int, int, int, int] | None:
    value = frame_row.get(key)
    if not isinstance(value, dict):
        return None
    return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])


def _dict_box_to_int_tuple(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, dict):
        return None
    return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])


def _telemetry(frame_row: dict[str, object], key: str, default):
    telemetry = frame_row.get("telemetry", {})
    if not isinstance(telemetry, dict):
        return default
    return telemetry.get(key, default)


def _opposite_side(side: str) -> str:
    return "right" if side == "left" else "left"


def _target_side_for_frame(frame_row: dict[str, object], *, target_side: str = "passenger") -> str:
    selected_side = str(frame_row.get("selected_side") or "left").lower()
    # The prepared driver-source clip is mirrored like the stock driver camera
    # view, so the real passenger seat appears on the same image half as the
    # telemetry-selected driver side, while the visible driver appears on the
    # opposite image half.
    if target_side == "driver":
        return _opposite_side(selected_side)
    return selected_side


def _normalize_driver_monitoring_device_type(
    device_type: object,
    *,
    frame_width: int,
    frame_height: int,
) -> str:
    normalized = str(device_type or "").strip().lower()
    if normalized == "tizi":
        return "tici"
    if normalized in {"tici", "mici"}:
        return normalized
    if int(round(frame_width)) == int(OS_DRIVER_FRAME[0]) and int(round(frame_height)) == int(OS_DRIVER_FRAME[1]):
        return "mici"
    if frame_width > 0 and frame_height > 0:
        return "tici"
    return "unknown"


def _driver_monitoring_input_crop_rect(
    *,
    frame_width: int,
    frame_height: int,
    device_type: object,
) -> tuple[int, int, int, int]:
    frame_width = int(frame_width)
    frame_height = int(frame_height)
    if frame_width <= 0 or frame_height <= 0:
        return 0, 0, 2, 2

    normalized_device_type = _normalize_driver_monitoring_device_type(
        device_type,
        frame_width=frame_width,
        frame_height=frame_height,
    )
    focal_length = OS_DRIVER_FOCAL if normalized_device_type == "mici" else AR_OX_DRIVER_FOCAL

    cam_cx = frame_width / 2.0
    cam_cy = frame_height / 2.0
    scale = focal_length / AR_OX_DRIVER_FOCAL
    translate_x = cam_cx - (DM_INTRINSIC_CX * scale)
    translate_y = cam_cy - (DM_INTRINSIC_CY * scale)
    max_dm_x = translate_x + (scale * (DM_INPUT_SIZE[0] - 1.0))
    max_dm_y = translate_y + (scale * (DM_INPUT_SIZE[1] - 1.0))

    x0 = max(0, int(np.floor(translate_x)))
    y0 = max(0, int(np.floor(translate_y)))
    x1 = min(frame_width, int(np.ceil(max_dm_x)) + 1)
    y1 = min(frame_height, int(np.ceil(max_dm_y)) + 1)
    return x0, y0, max(2, x1 - x0), max(2, y1 - y0)


def _resize_mask(mask: np.ndarray, *, width: int, height: int) -> np.ndarray:
    if mask.shape[0] == height and mask.shape[1] == width:
        return mask.astype(bool)
    resized = cv2.resize(mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST)
    return resized.astype(bool)


def _passenger_crop_rect(
    *,
    frame_row: dict[str, object],
    frame_width: int,
    frame_height: int,
    margin_ratio: float,
    device_type: object,
    target_side: str = "passenger",
) -> tuple[int, int, int, int]:
    target_image_side = _target_side_for_frame(frame_row, target_side=target_side)
    dm_x, dm_y, dm_width, dm_height = _driver_monitoring_input_crop_rect(
        frame_width=frame_width,
        frame_height=frame_height,
        device_type=device_type,
    )
    dm_x1 = dm_x + dm_width
    frame_mid_x = frame_width / 2.0
    overlap = int(round(dm_width * max(0.0, margin_ratio)))
    if target_image_side == "left":
        x0 = dm_x
        x1 = min(dm_x1, int(round(frame_mid_x)) + overlap)
    else:
        x0 = max(dm_x, int(round(frame_mid_x)) - overlap)
        x1 = dm_x1
    return x0, dm_y, max(2, x1 - x0), dm_height


def _expand_crop_detections_to_full_frame(
    detections,
    *,
    crop_rect: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
):
    crop_x, crop_y, crop_width, crop_height = crop_rect
    xyxy = _detections_xyxy(detections).copy()
    xyxy[:, [0, 2]] += crop_x
    xyxy[:, [1, 3]] += crop_y

    class_id = _detections_class_id(detections)
    confidence = _detections_confidence(detections)
    masks = _detections_masks(detections)

    expanded_masks: np.ndarray | None = None
    if masks is not None and len(masks):
        expanded = np.zeros((len(masks), frame_height, frame_width), dtype=bool)
        for index, mask in enumerate(masks):
            resized_mask = _resize_mask(np.asarray(mask), width=crop_width, height=crop_height)
            expanded[index, crop_y: crop_y + crop_height, crop_x: crop_x + crop_width] = resized_mask
        expanded_masks = expanded

    data = getattr(detections, "data", {})
    return SimpleNamespace(
        xyxy=xyxy,
        class_id=None if class_id is None else np.asarray(class_id),
        confidence=None if confidence is None else np.asarray(confidence),
        mask=expanded_masks,
        data=data if isinstance(data, dict) else {},
    )


def _box_from_mask(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return None
    min_x = int(xs.min())
    max_x = int(xs.max())
    min_y = int(ys.min())
    max_y = int(ys.max())
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1


def _intersection_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0 = max(ax, bx)
    y0 = max(ay, by)
    x1 = min(ax + aw, bx + bw)
    y1 = min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0
    return (x1 - x0) * (y1 - y0)


def _inflate_rect(rect: tuple[int, int, int, int], *, scale: float, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    grow_x = int(round(w * max(0.0, scale)))
    grow_y = int(round(h * max(0.0, scale)))
    x0 = max(0, x - grow_x)
    y0 = max(0, y - grow_y)
    x1 = min(frame_width, x + w + grow_x)
    y1 = min(frame_height, y + h + grow_y)
    return x0, y0, max(2, x1 - x0), max(2, y1 - y0)


def _anchor_track_path(sample_dir: Path, *, target_side: str) -> Path:
    if target_side == "driver":
        return sample_dir / "face-track.json"
    passenger_path = sample_dir / "passenger-face-track.json"
    if passenger_path.exists():
        return passenger_path
    return sample_dir / "face-track.json"


def _load_optional_anchor_rows(sample_dir: Path, *, target_side: str) -> dict[int, tuple[int, int, int, int]]:
    anchor_path = _anchor_track_path(sample_dir, target_side=target_side)
    if not anchor_path.exists():
        return {}
    track = json.loads(anchor_path.read_text())
    anchors: dict[int, tuple[int, int, int, int]] = {}
    for row in track.get("frames", []):
        rect = _dict_box_to_int_tuple(row.get("crop_rect")) or _dict_box_to_int_tuple(row.get("padded_box"))
        frame_index = int(row.get("frame_index", -1))
        if rect is not None and frame_index >= 0:
            anchors[frame_index] = rect
    return anchors


def _rect_center(rect: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, w, h = rect
    return x + (w / 2.0), y + (h / 2.0)


def _warp_mask_between_anchors(
    mask: np.ndarray,
    *,
    from_anchor_rect: tuple[int, int, int, int],
    to_anchor_rect: tuple[int, int, int, int],
) -> np.ndarray:
    from_cx, from_cy = _rect_center(from_anchor_rect)
    to_cx, to_cy = _rect_center(to_anchor_rect)
    from_scale = max(1.0, float(max(from_anchor_rect[2], from_anchor_rect[3])))
    to_scale = max(1.0, float(max(to_anchor_rect[2], to_anchor_rect[3])))
    scale = float(np.clip(to_scale / from_scale, 0.8, 1.25))
    matrix = np.array(
        [
            [scale, 0.0, to_cx - (scale * from_cx)],
            [0.0, scale, to_cy - (scale * from_cy)],
        ],
        dtype=np.float32,
    )
    warped = cv2.warpAffine(
        mask.astype(np.uint8),
        matrix,
        (mask.shape[1], mask.shape[0]),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return warped.astype(bool)


def _fallback_mask_from_anchor(
    *,
    anchor_rect: tuple[int, int, int, int] | None,
    previous_mask: np.ndarray | None,
    previous_anchor_rect: tuple[int, int, int, int] | None,
    frame_width: int,
    frame_height: int,
) -> tuple[np.ndarray | None, str | None]:
    del frame_width, frame_height
    if previous_mask is None:
        return None, None
    if anchor_rect is None or previous_anchor_rect is None:
        return previous_mask.copy(), "held_previous_mask"
    shifted_previous = _warp_mask_between_anchors(
        previous_mask,
        from_anchor_rect=previous_anchor_rect,
        to_anchor_rect=anchor_rect,
    )
    return shifted_previous, "anchor_shifted_mask_fallback"


def _choose_passenger_mask(
    detections,
    *,
    frame_row: dict[str, object],
    frame_width: int,
    frame_height: int,
    anchor_rect: tuple[int, int, int, int] | None = None,
    crop_rect: tuple[int, int, int, int] | None = None,
    target_side: str = "passenger",
) -> tuple[np.ndarray | None, dict[str, object]]:
    masks = _detections_masks(detections)
    if masks is None or masks.size == 0:
        return None, {"reason": "no_masks"}

    xyxy = _detections_xyxy(detections)
    class_ids = _detections_class_id(detections)
    confidences = _detections_confidence(detections)
    target_image_side = _target_side_for_frame(frame_row, target_side=target_side)
    frame_mid_x = frame_width / 2.0
    chosen_mask: np.ndarray | None = None
    chosen_details: dict[str, object] = {"reason": f"no_person_on_{target_side}_side"}
    chosen_score = float("-inf")
    inflated_anchor = (
        _inflate_rect(anchor_rect, scale=0.18, frame_width=frame_width, frame_height=frame_height)
        if anchor_rect is not None
        else None
    )
    crop_width = crop_rect[2] if crop_rect is not None else frame_width
    crop_height = crop_rect[3] if crop_rect is not None else frame_height

    for index in range(len(masks)):
        if confidences is not None and float(confidences[index]) <= 0.0:
            continue
        mask = _resize_mask(np.asarray(masks[index]), width=frame_width, height=frame_height)
        box = _box_from_mask(mask)
        if box is None:
            continue
        x, y, width, height = box
        center_x = x + (width / 2.0)
        if target_image_side == "right" and center_x < frame_mid_x:
            continue
        if target_image_side == "left" and center_x > frame_mid_x:
            continue
        area = int(mask.sum())
        area_fraction = area / max(1.0, frame_width * frame_height)
        crop_area_fraction = area / max(1.0, crop_width * crop_height)
        crop_width_fraction = width / max(1.0, crop_width)
        crop_height_fraction = height / max(1.0, crop_height)
        if area_fraction < 0.01 or area_fraction > 0.55:
            continue
        if crop_area_fraction > 0.82:
            continue
        if crop_width_fraction > 0.94 and crop_height_fraction > 0.9:
            continue
        if width >= int(frame_width * 0.92) and height >= int(frame_height * 0.92):
            continue
        anchor_overlap = None
        if inflated_anchor is not None:
            overlap_area = _intersection_area(box, inflated_anchor)
            anchor_overlap = overlap_area / max(1, inflated_anchor[2] * inflated_anchor[3])
            if overlap_area == 0:
                continue
        confidence = float(confidences[index]) if confidences is not None else 0.0
        side_bias = abs(center_x - frame_mid_x) / max(1.0, frame_mid_x)
        person_label_bonus = 0.75 if class_ids is not None and int(class_ids[index]) == 0 else 0.0
        anchor_bonus = 0.0 if anchor_overlap is None else anchor_overlap * 8.0
        score = (confidence * 3.0) + (area_fraction * 4.0) + side_bias + person_label_bonus + anchor_bonus
        if score > chosen_score:
            chosen_score = score
            chosen_mask = mask
            chosen_details = {
                "reason": "selected",
                "index": index,
                "class_id": int(class_ids[index]) if class_ids is not None else None,
                "confidence": round(confidence, 4),
                "box_xyxy": [float(value) for value in np.asarray(xyxy[index]).tolist()],
                "mask_box": {"x": x, "y": y, "width": width, "height": height},
                "mask_area": area,
                "mask_area_fraction": round(area_fraction, 4),
                "mask_crop_area_fraction": round(crop_area_fraction, 4),
                "anchor_overlap": None if anchor_overlap is None else round(anchor_overlap, 4),
                "target_side": target_side,
                "target_image_side": target_image_side,
            }
    return chosen_mask, chosen_details


def _dilate_mask(mask: np.ndarray, *, kernel_size: int) -> np.ndarray:
    if kernel_size <= 1:
        return mask
    kernel_size = max(1, kernel_size | 1)
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    return cv2.dilate(mask.astype(np.uint8), kernel, iterations=1).astype(bool)


def _blur_mask(frame: np.ndarray, mask: np.ndarray) -> None:
    blur_mask = _dilate_mask(mask, kernel_size=_rf_detr_blur_mask_dilate())
    blur_size = max(1, int(_rf_detr_blur_size()))
    blur_size |= 1
    blurred = cv2.blur(frame, (blur_size, blur_size))
    frame[blur_mask] = blurred[blur_mask]


def _silhouette_style_palette(effect: str) -> tuple[int, int, int]:
    try:
        return RF_DETR_SILHOUETTE_STYLE_PALETTES[effect]
    except KeyError as exc:
        raise ValueError(f"Unsupported RF-DETR silhouette effect: {effect}") from exc


def _silhouette_mask(
    frame: np.ndarray,
    mask: np.ndarray,
    *,
    frame_index: int,
    effect: str = "silhouette",
) -> None:
    if not np.any(mask):
        return

    del frame_index
    fill_color = _silhouette_style_palette(effect)
    contour_mask = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(contour_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return

    approx_contours = [
        cv2.approxPolyDP(contour, epsilon=max(2.0, 0.01 * cv2.arcLength(contour, True)), closed=True)
        for contour in contours
        if len(contour) >= 3
    ]
    if not approx_contours:
        return

    frame[mask] = fill_color
    cv2.drawContours(frame, approx_contours, -1, fill_color, thickness=cv2.FILLED, lineType=cv2.LINE_AA)


def _apply_rf_detr_effect(
    frame: np.ndarray,
    mask: np.ndarray,
    *,
    effect: str,
    frame_index: int,
) -> None:
    if effect == "blur":
        _blur_mask(frame, mask)
        return
    if effect in RF_DETR_SILHOUETTE_STYLE_PALETTES:
        _silhouette_mask(frame, mask, frame_index=frame_index, effect=effect)
        return
    raise ValueError(f"Unsupported RF-DETR effect: {effect}")


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


def _score_rf_detr_sample(track: dict[str, object], *, redacted_frames: int) -> dict[str, str]:
    frames = list(track.get("frames", []))
    held_frames = sum(1 for frame in frames if int(frame.get("held_without_detection", 0) or 0) > 0)
    redaction_ratio = redacted_frames / max(1, len(frames))
    return {
        "identity_leakage": "low" if redaction_ratio >= 0.7 else "manual review",
        "temporal_stability": "medium" if held_frames else "manual review",
        "gaze_eye_readability": "not applicable",
        "pose_preservation": "high silhouette",
        "occlusion_robustness": "manual review",
        "runtime_complexity": "detector + segmentation pass",
    }


def _rf_detr_effect_for_candidate(candidate_id: str) -> str:
    if candidate_id == "rf-detr-passenger-blur":
        return "blur"
    if candidate_id == "rf-detr-passenger-silhouette":
        return "silhouette"
    raise ValueError(f"Unsupported RF-DETR candidate id: {candidate_id}")


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

    execution_providers = default_facefusion_execution_providers()
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
        *execution_providers,
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
    env = facefusion_runtime_env(facefusion_root)
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
    elif candidate_id == "rf-detr-passenger-blur":
        behavior = "Runs RF-DETR segmentation on a driver-debug-style passenger crop, selects the passenger-side body mask, and heavily blurs the masked silhouette."
    elif candidate_id == "rf-detr-passenger-silhouette":
        behavior = "Runs RF-DETR segmentation on a driver-debug-style passenger crop, selects the passenger-side body mask, and replaces it with a flat white silhouette plus a static paper-cutout dotted outline."
    else:
        behavior = "Processes the DM-guided ROI on the full-frame driver clip."
    notes = f"Generated `{output_name}` in {report['runtime_seconds']:.2f}s. {behavior}"
    with path.open("a") as handle:
        handle.write(
            f"| {candidate_id} | {scores['identity_leakage']} | {scores['temporal_stability']} | "
            f"{scores['gaze_eye_readability']} | {scores['pose_preservation']} | "
            f"{scores['occlusion_robustness']} | {scores['runtime_complexity']} | {notes} |\n"
        )


def render_rf_detr_redacted_clip(
    *,
    sample_dir: Path,
    output_path: Path,
    source_path: Path,
    source_kind: str,
    track: dict[str, object],
    model_id: str,
    threshold: float,
    frame_stride: int,
    mask_dilate: int,
    startup_hold_frames: int,
    passenger_crop_margin_ratio: float,
    missing_hold_frames: int,
    target_side: str,
    effect: str,
    banner_text: str = "",
    source_clip_description: str = "",
    trim_startup_from_output: bool = True,
) -> dict[str, object]:
    frames = list(track["frames"])
    device_type = track.get("device_type")
    anchor_rows = _load_optional_anchor_rows(sample_dir, target_side=target_side)
    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open source clip: {source_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 20.0)
    intermediate_output_path = _intermediate_output_path(output_path)
    blur_video_backend: str | None = None
    writer = cv2.VideoWriter(
        str(intermediate_output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Failed to create output clip: {output_path}")
    candidate_id = output_path.stem
    requested_device = _default_rf_detr_device()
    model = _load_rf_detr_model(model_id, device=requested_device)
    actual_device = _rf_detr_model_device(model)
    print(
        "RF-DETR acceleration: "
        f"candidate_id={candidate_id}, "
        f"requested_device={requested_device}, "
        f"actual_model_device={actual_device}, "
        f"model_id={model_id}, "
        f"effect={effect}"
    )
    stride = max(1, int(frame_stride))
    last_mask: np.ndarray | None = None
    last_mask_box: tuple[int, int, int, int] | None = None
    last_detected_mask: np.ndarray | None = None
    last_detected_anchor_rect: tuple[int, int, int, int] | None = None
    missed_detections_since_last_mask = 0
    missing_hold_frames = max(0, int(missing_hold_frames))
    startup_mask_source_frame_index: int | None = None
    startup_hold = max(0, int(startup_hold_frames))
    startup_trimmed_frames = 0
    startup_buffer: list[tuple[np.ndarray, dict[str, object]]] = []
    redacted_frames = 0
    detector_frames = 0
    output_frames = 0
    frame_reports: list[dict[str, object]] = []
    read_seconds = 0.0
    detector_seconds = 0.0
    effect_seconds = 0.0
    writer_seconds = 0.0
    finalize_seconds = 0.0
    started = time.perf_counter()
    total_frames = len(frames)
    progress_interval_seconds = _rf_detr_progress_interval_seconds()
    last_progress_log_at = started

    def _log_rf_detr_progress(*, frame_index: int, force: bool = False) -> None:
        nonlocal last_progress_log_at
        now = time.perf_counter()
        if not force and progress_interval_seconds > 0.0 and now - last_progress_log_at < progress_interval_seconds:
            return
        last_progress_log_at = now
        processed_frames = min(total_frames, frame_index + 1)
        percent_complete = (processed_frames / total_frames) * 100.0 if total_frames else 100.0
        print(
            "RF-DETR progress: "
            f"frame={processed_frames}/{total_frames} ({percent_complete:.1f}%), "
            f"output={output_frames}, "
            f"detector={detector_frames}, "
            f"redacted={redacted_frames}, "
            f"elapsed={now - started:.2f}s, "
            f"detector_time={detector_seconds:.2f}s, "
            f"effect_time={effect_seconds:.2f}s, "
            f"writer_time={writer_seconds:.2f}s"
        )

    def _emit_output_frame(frame_to_write: np.ndarray, detection_report: dict[str, object]) -> None:
        nonlocal output_frames, redacted_frames, effect_seconds, writer_seconds
        effect_started = time.perf_counter()
        if banner_text:
            from core.driver_face_reintegrate import _draw_banner

            _draw_banner(frame_to_write, banner_text)
        if last_mask is not None:
            _apply_rf_detr_effect(frame_to_write, last_mask, effect=effect, frame_index=int(detection_report["frame_index"]))
            redacted_frames += 1
        effect_seconds += time.perf_counter() - effect_started
        writer_started = time.perf_counter()
        writer.write(frame_to_write)
        writer_seconds += time.perf_counter() - writer_started
        output_frames += 1
        frame_reports.append(detection_report)

    try:
        for frame_index, frame_row in enumerate(frames):
            read_started = time.perf_counter()
            ok, frame = capture.read()
            read_seconds += time.perf_counter() - read_started
            if not ok:
                raise RuntimeError(f"Video ended early at frame {frame_index}")

            anchor_rect = anchor_rows.get(frame_index)
            should_extend_startup_trim = startup_mask_source_frame_index is None
            in_startup_hold = frame_index < startup_hold or should_extend_startup_trim
            rerun_detector = in_startup_hold or frame_index % stride == 0 or last_mask is None
            detection_report: dict[str, object] = {
                "frame_index": frame_index,
                "used_detector": rerun_detector,
                "selected_side": frame_row.get("selected_side"),
                "target_side": target_side,
                "target_image_side": _target_side_for_frame(frame_row, target_side=target_side),
            }

            if rerun_detector:
                detector_started = time.perf_counter()
                detector_frames += 1
                crop_rect = _passenger_crop_rect(
                    frame_row=frame_row,
                    frame_width=width,
                    frame_height=height,
                    margin_ratio=passenger_crop_margin_ratio,
                    device_type=device_type,
                    target_side=target_side,
                )
                crop_x, crop_y, crop_width, crop_height = crop_rect
                cropped_frame = frame[crop_y: crop_y + crop_height, crop_x: crop_x + crop_width]
                rgb_frame = cv2.cvtColor(cropped_frame, cv2.COLOR_BGR2RGB)
                crop_detections = _predict_rf_detr(model, rgb_frame, threshold=threshold)
                detections = _expand_crop_detections_to_full_frame(
                    crop_detections,
                    crop_rect=crop_rect,
                    frame_width=width,
                    frame_height=height,
                )
                selected_mask, selection_details = _choose_passenger_mask(
                    detections,
                    frame_row=frame_row,
                    frame_width=width,
                    frame_height=height,
                    anchor_rect=anchor_rect,
                    crop_rect=crop_rect,
                    target_side=target_side,
                )
                detection_report.update(selection_details)
                detection_report["crop_rect"] = {
                    "x": crop_x,
                    "y": crop_y,
                    "width": crop_width,
                    "height": crop_height,
                }
                if anchor_rect is not None:
                    detection_report["anchor_rect"] = {
                        "x": anchor_rect[0],
                        "y": anchor_rect[1],
                        "width": anchor_rect[2],
                        "height": anchor_rect[3],
                    }
                if selected_mask is not None:
                    last_mask = _dilate_mask(selected_mask, kernel_size=mask_dilate)
                    last_mask_box = _box_from_mask(last_mask)
                    last_detected_mask = last_mask.copy()
                    last_detected_anchor_rect = anchor_rect
                    missed_detections_since_last_mask = 0
                    if startup_mask_source_frame_index is None:
                        startup_mask_source_frame_index = frame_index
                else:
                    missed_detections_since_last_mask += 1
                    fallback_mask: np.ndarray | None = None
                    fallback_reason: str | None = None
                    if last_detected_mask is not None and (anchor_rect is not None or missed_detections_since_last_mask <= missing_hold_frames):
                        fallback_mask, fallback_reason = _fallback_mask_from_anchor(
                            anchor_rect=anchor_rect,
                            previous_mask=last_detected_mask,
                            previous_anchor_rect=last_detected_anchor_rect,
                            frame_width=width,
                            frame_height=height,
                        )
                    if fallback_mask is not None:
                        last_mask = _dilate_mask(fallback_mask, kernel_size=mask_dilate)
                        last_mask_box = _box_from_mask(last_mask)
                        detection_report["reason"] = fallback_reason
                    elif anchor_rect is not None:
                        fallback_mask, fallback_reason = _fallback_mask_from_anchor(
                            anchor_rect=anchor_rect,
                            previous_mask=None,
                            previous_anchor_rect=None,
                            frame_width=width,
                            frame_height=height,
                        )
                        if fallback_mask is not None:
                            last_mask = _dilate_mask(fallback_mask, kernel_size=mask_dilate)
                            last_mask_box = _box_from_mask(last_mask)
                            detection_report["reason"] = fallback_reason
                            if startup_mask_source_frame_index is None:
                                startup_mask_source_frame_index = frame_index
                    elif last_mask is None:
                        last_mask_box = None
                detector_seconds += time.perf_counter() - detector_started
            elif last_mask_box is not None:
                detection_report["reason"] = "reused_previous_mask"
                detection_report["mask_box"] = {
                    "x": last_mask_box[0],
                    "y": last_mask_box[1],
                    "width": last_mask_box[2],
                    "height": last_mask_box[3],
                }

            if last_mask_box is not None and detection_report.get("mask_box") is None:
                detection_report["mask_box"] = {
                    "x": last_mask_box[0],
                    "y": last_mask_box[1],
                    "width": last_mask_box[2],
                    "height": last_mask_box[3],
                }

            should_trim_output = startup_mask_source_frame_index is None or frame_index < startup_hold
            if should_trim_output:
                detection_report["startup_hidden_trimmed"] = trim_startup_from_output
                detection_report["startup_hidden_buffered"] = not trim_startup_from_output
                startup_trimmed_frames += 1
                if not trim_startup_from_output:
                    startup_buffer.append((frame.copy(), detection_report))
                    _log_rf_detr_progress(frame_index=frame_index)
                    continue
                frame_reports.append(detection_report)
                _log_rf_detr_progress(frame_index=frame_index)
                continue

            if startup_buffer:
                for buffered_frame, buffered_report in startup_buffer:
                    _emit_output_frame(buffered_frame, buffered_report)
                startup_buffer.clear()

            _emit_output_frame(frame, detection_report)
            _log_rf_detr_progress(frame_index=frame_index)
    finally:
        capture.release()
        writer.release()

    finalize_started = time.perf_counter()
    _finalize_shareable_mp4(intermediate_output_path, output_path)
    finalize_seconds = time.perf_counter() - finalize_started

    runtime_seconds = time.perf_counter() - started
    runtime_breakdown = {
        "read_seconds": round(read_seconds, 4),
        "detector_seconds": round(detector_seconds, 4),
        "effect_seconds": round(effect_seconds, 4),
        "writer_seconds": round(writer_seconds, 4),
        "finalize_seconds": round(finalize_seconds, 4),
        "untracked_seconds": round(
            max(0.0, runtime_seconds - read_seconds - detector_seconds - effect_seconds - writer_seconds - finalize_seconds),
            4,
        ),
        "detector_frames": detector_frames,
        "output_frames": output_frames,
        "avg_detector_ms": round((detector_seconds / detector_frames) * 1000.0, 2) if detector_frames else 0.0,
        "avg_effect_ms": round((effect_seconds / output_frames) * 1000.0, 2) if output_frames else 0.0,
        "avg_writer_ms": round((writer_seconds / output_frames) * 1000.0, 2) if output_frames else 0.0,
    }
    _log_rf_detr_progress(frame_index=max(0, total_frames - 1), force=True)
    print(
        "RF-DETR runtime breakdown: "
        f"detector={detector_seconds:.2f}s/{detector_frames} frames, "
        f"effect={effect_seconds:.2f}s/{output_frames} frames, "
        f"writer={writer_seconds:.2f}s/{output_frames} frames, "
        f"finalize={finalize_seconds:.2f}s, "
        f"read={read_seconds:.2f}s, "
        f"other={max(0.0, runtime_breakdown['untracked_seconds']):.2f}s"
    )
    if blur_video_backend is not None:
        print(f"RF-DETR blur video backend: {blur_video_backend}")
    return {
        "candidate_id": candidate_id,
        "sample_dir": str(sample_dir),
        "source_clip": str(source_path),
        "source_clip_kind": source_kind,
        "output_clip": str(output_path),
        "source_frames_processed": len(frames),
        "frames_processed": output_frames,
        "redacted_frames": redacted_frames,
        "detector_frames": detector_frames,
        "runtime_seconds": runtime_seconds,
        "scores": _score_rf_detr_sample(track, redacted_frames=redacted_frames),
        "rf_detr_model_id": model_id,
        "rf_detr_threshold": threshold,
        "rf_detr_frame_stride": stride,
        "rf_detr_mask_dilate": mask_dilate,
        "rf_detr_startup_hold_frames": startup_hold,
        "rf_detr_startup_hold_applied": startup_trimmed_frames,
        "rf_detr_startup_hold_trimmed_from_output": startup_trimmed_frames if trim_startup_from_output else 0,
        "rf_detr_startup_hold_buffered_in_output": startup_trimmed_frames if not trim_startup_from_output else 0,
        "rf_detr_passenger_crop_margin_ratio": passenger_crop_margin_ratio,
        "rf_detr_passenger_crop_strategy": "driver_debug_dm_input_passenger_half",
        "rf_detr_driver_monitoring_device_type": _normalize_driver_monitoring_device_type(
            device_type,
            frame_width=width,
            frame_height=height,
        ),
        "rf_detr_test_target_side": target_side,
        "rf_detr_missing_hold_frames": missing_hold_frames,
        "rf_detr_effect": effect,
        "rf_detr_blur_video_backend": blur_video_backend,
        "rf_detr_requested_device": requested_device,
        "rf_detr_device": actual_device,
        "output_video_encoder": _shareable_h264_encoder_name(),
        "startup_mask_source_frame_index": startup_mask_source_frame_index,
        "trim_startup_from_output": trim_startup_from_output,
        "source_clip_description": source_clip_description or source_kind,
        "runtime_breakdown": runtime_breakdown,
        "frame_reports": frame_reports,
    }


def _run_rf_detr_passenger_effect(
    *,
    sample_dir: Path,
    output_path: Path,
    source_path: Path,
    source_kind: str,
    track: dict[str, object],
    model_id: str,
    threshold: float,
    frame_stride: int,
    mask_dilate: int,
    startup_hold_frames: int,
    passenger_crop_margin_ratio: float,
    missing_hold_frames: int,
    test_target_side: str,
) -> dict[str, object]:
    return render_rf_detr_redacted_clip(
        sample_dir=sample_dir,
        output_path=output_path,
        source_path=source_path,
        source_kind=source_kind,
        track=track,
        model_id=model_id,
        threshold=threshold,
        frame_stride=frame_stride,
        mask_dilate=mask_dilate,
        startup_hold_frames=startup_hold_frames,
        passenger_crop_margin_ratio=passenger_crop_margin_ratio,
        missing_hold_frames=missing_hold_frames,
        target_side=test_target_side,
        effect=_rf_detr_effect_for_candidate(output_path.stem),
    )


def main() -> int:
    args = parse_args()
    sample_dir = Path(args.sample_dir).resolve()
    track_path = sample_dir / "face-track.json"
    evaluation_path = sample_dir / "evaluation.md"
    output_path = sample_dir / f"{args.candidate_id}.mp4"
    report_path = sample_dir / f"{args.candidate_id}.json"

    track = json.loads(track_path.read_text())
    source_path, source_kind = _resolve_preferred_source_clip(sample_dir, track)
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

    if args.candidate_id in RF_DETR_CANDIDATE_IDS:
        report = _run_rf_detr_passenger_effect(
            sample_dir=sample_dir,
            output_path=output_path,
            source_path=source_path,
            source_kind=source_kind,
            track=track,
            model_id=args.rf_detr_model_id,
            threshold=args.rf_detr_threshold,
            frame_stride=args.rf_detr_frame_stride,
            mask_dilate=args.rf_detr_mask_dilate,
            startup_hold_frames=args.rf_detr_startup_hold_frames,
            passenger_crop_margin_ratio=args.rf_detr_passenger_crop_margin_ratio,
            missing_hold_frames=args.rf_detr_missing_hold_frames,
            test_target_side=args.rf_detr_test_target_side,
        )
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
    intermediate_output_path = _intermediate_output_path(output_path)
    writer = cv2.VideoWriter(
        str(intermediate_output_path),
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
    _finalize_shareable_mp4(intermediate_output_path, output_path)
    runtime_seconds = time.perf_counter() - started

    scores = _score_sample(track) if args.candidate_id == "dm-box-pixelize" else _score_surrogate_sample(track)
    report = {
        "candidate_id": args.candidate_id,
        "sample_dir": str(sample_dir),
        "source_clip": str(source_path),
        "source_clip_kind": source_kind,
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
