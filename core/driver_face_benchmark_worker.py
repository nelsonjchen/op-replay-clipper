from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from functools import lru_cache
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
    default_facefusion_execution_providers,
    default_facefusion_output_video_encoder,
    facefusion_runtime_env,
)

RF_DETR_CANDIDATE_IDS = {
    "rf-detr-passenger-blackout",
    "rf-detr-passenger-blur",
    "rf-detr-passenger-white-static",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one driver-face benchmark candidate over a prepared sample.")
    parser.add_argument("--sample-dir", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--pixel-block-size", type=int, default=18)
    parser.add_argument("--facefusion-root")
    parser.add_argument("--facefusion-source-image")
    parser.add_argument("--facefusion-model", default="hyperswap_1b_256")
    parser.add_argument("--driver-face-donor-bank-dir", default="./assets/driver-face-donors")
    parser.add_argument("--rf-detr-model-id", default="rfdetr-seg-preview")
    parser.add_argument("--rf-detr-threshold", type=float, default=0.4)
    parser.add_argument("--rf-detr-frame-stride", type=int, default=3)
    parser.add_argument("--rf-detr-mask-dilate", type=int, default=15)
    parser.add_argument("--rf-detr-startup-hold-frames", type=int, default=6)
    parser.add_argument("--rf-detr-passenger-crop-margin-ratio", type=float, default=0.18)
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


def _dict_box_to_int_tuple(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, dict):
        return None
    return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])


def _telemetry(frame_row: dict[str, object], key: str, default):
    telemetry = frame_row.get("telemetry", {})
    if not isinstance(telemetry, dict):
        return default
    return telemetry.get(key, default)


def _passenger_side_for_frame(frame_row: dict[str, object]) -> str:
    selected_side = str(frame_row.get("selected_side") or "left").lower()
    # The prepared driver-source clip is mirrored like the stock driver camera
    # view, so the real passenger seat appears on the same image half as the
    # telemetry-selected driver side.
    return selected_side


@lru_cache(maxsize=1)
def _load_rf_detr_model(model_id: str):
    from rfdetr import RFDETRSegLarge, RFDETRSegMedium, RFDETRSegNano, RFDETRSegPreview, RFDETRSegSmall, RFDETRSegXLarge, RFDETRSeg2XLarge

    model_specs = {
        "rfdetr-seg-preview": (RFDETRSegPreview, "rf-detr-seg-preview.pt"),
        "rfdetr-seg-nano": (RFDETRSegNano, "rf-detr-seg-nano.pt"),
        "rfdetr-seg-small": (RFDETRSegSmall, "rf-detr-seg-small.pt"),
        "rfdetr-seg-medium": (RFDETRSegMedium, "rf-detr-seg-medium.pt"),
        "rfdetr-seg-large": (RFDETRSegLarge, "rf-detr-seg-large.pt"),
        "rfdetr-seg-xlarge": (RFDETRSegXLarge, "rf-detr-seg-xlarge.pt"),
        "rfdetr-seg-2xlarge": (RFDETRSeg2XLarge, "rf-detr-seg-xxlarge.pt"),
        "rfdetr-seg-xxlarge": (RFDETRSeg2XLarge, "rf-detr-seg-xxlarge.pt"),
    }
    try:
        model_class, weight_filename = model_specs[model_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported RF-DETR segmentation model id: {model_id}") from exc

    weights_dir = REPO_ROOT / ".cache/rfdetr"
    weights_dir.mkdir(parents=True, exist_ok=True)
    model = model_class(pretrain_weights=str((weights_dir / weight_filename).resolve()))
    optimize = getattr(model, "optimize_for_inference", None)
    if callable(optimize):
        optimize()
    return model


def _detections_masks(detections) -> np.ndarray | None:
    mask = getattr(detections, "mask", None)
    if mask is None:
        data = getattr(detections, "data", None)
        if isinstance(data, dict):
            mask = data.get("mask")
    if mask is None:
        return None
    return np.asarray(mask)


def _detections_xyxy(detections) -> np.ndarray:
    xyxy = getattr(detections, "xyxy", None)
    if xyxy is None:
        raise RuntimeError("RF-DETR detections object does not expose xyxy boxes")
    return np.asarray(xyxy)


def _detections_class_id(detections) -> np.ndarray | None:
    class_id = getattr(detections, "class_id", None)
    if class_id is None:
        return None
    return np.asarray(class_id)


def _detections_confidence(detections) -> np.ndarray | None:
    confidence = getattr(detections, "confidence", None)
    if confidence is None:
        return None
    return np.asarray(confidence)


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
) -> tuple[int, int, int, int]:
    passenger_side = _passenger_side_for_frame(frame_row)
    half_width = frame_width // 2
    overlap = int(round(frame_width * max(0.0, margin_ratio)))
    if passenger_side == "left":
        x0 = 0
        x1 = min(frame_width, half_width + overlap)
    else:
        x0 = max(0, half_width - overlap)
        x1 = frame_width
    return x0, 0, max(2, x1 - x0), frame_height


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


def _load_optional_passenger_anchor_rows(sample_dir: Path) -> dict[int, tuple[int, int, int, int]]:
    anchor_path = sample_dir / "passenger-face-track.json"
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


def _choose_passenger_mask(
    detections,
    *,
    frame_row: dict[str, object],
    frame_width: int,
    frame_height: int,
    anchor_rect: tuple[int, int, int, int] | None = None,
) -> tuple[np.ndarray | None, dict[str, object]]:
    masks = _detections_masks(detections)
    if masks is None or masks.size == 0:
        return None, {"reason": "no_masks"}

    xyxy = _detections_xyxy(detections)
    class_ids = _detections_class_id(detections)
    confidences = _detections_confidence(detections)
    passenger_side = _passenger_side_for_frame(frame_row)
    frame_mid_x = frame_width / 2.0
    chosen_mask: np.ndarray | None = None
    chosen_details: dict[str, object] = {"reason": "no_person_on_passenger_side"}
    chosen_score = float("-inf")
    inflated_anchor = (
        _inflate_rect(anchor_rect, scale=0.18, frame_width=frame_width, frame_height=frame_height)
        if anchor_rect is not None
        else None
    )

    for index in range(len(masks)):
        if confidences is not None and float(confidences[index]) <= 0.0:
            continue
        mask = _resize_mask(np.asarray(masks[index]), width=frame_width, height=frame_height)
        box = _box_from_mask(mask)
        if box is None:
            continue
        x, y, width, height = box
        center_x = x + (width / 2.0)
        if passenger_side == "right" and center_x < frame_mid_x:
            continue
        if passenger_side == "left" and center_x > frame_mid_x:
            continue
        area = int(mask.sum())
        area_fraction = area / max(1.0, frame_width * frame_height)
        if area_fraction < 0.01 or area_fraction > 0.55:
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
                "anchor_overlap": None if anchor_overlap is None else round(anchor_overlap, 4),
                "passenger_side": passenger_side,
            }
    return chosen_mask, chosen_details


def _dilate_mask(mask: np.ndarray, *, kernel_size: int) -> np.ndarray:
    if kernel_size <= 1:
        return mask
    kernel_size = max(1, kernel_size | 1)
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    return cv2.dilate(mask.astype(np.uint8), kernel, iterations=1).astype(bool)


def _blackout_mask(frame: np.ndarray, mask: np.ndarray) -> None:
    frame[mask] = 0


def _blur_mask(frame: np.ndarray, mask: np.ndarray) -> None:
    blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=18, sigmaY=18)
    frame[mask] = blurred[mask]


def _shift_mask(mask: np.ndarray, *, x: int = 0, y: int = 0) -> np.ndarray:
    shifted = np.zeros_like(mask)
    src_y_start = max(0, -y)
    src_y_end = mask.shape[0] - max(0, y)
    dst_y_start = max(0, y)
    dst_y_end = dst_y_start + max(0, src_y_end - src_y_start)
    src_x_start = max(0, -x)
    src_x_end = mask.shape[1] - max(0, x)
    dst_x_start = max(0, x)
    dst_x_end = dst_x_start + max(0, src_x_end - src_x_start)
    if src_y_start >= src_y_end or src_x_start >= src_x_end:
        return shifted
    shifted[dst_y_start:dst_y_end, dst_x_start:dst_x_end] = mask[src_y_start:src_y_end, src_x_start:src_x_end]
    return shifted


def _white_static_mask(frame: np.ndarray, mask: np.ndarray, *, frame_index: int) -> None:
    del frame_index
    if not np.any(mask):
        return

    original = frame.astype(np.float32)
    interior = mask.astype(np.uint8) * 255
    interior_alpha = cv2.GaussianBlur(interior, (0, 0), sigmaX=2.4, sigmaY=2.4).astype(np.float32) / 255.0
    interior_alpha[mask] = 1.0

    luminance = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    luminance = cv2.GaussianBlur(luminance, (0, 0), sigmaX=8.0, sigmaY=8.0)
    silhouette_fill = np.repeat(luminance[:, :, None], 3, axis=2).astype(np.float32)
    silhouette_fill = silhouette_fill * 0.08 + 242.0 * 0.92

    output = original.copy()
    inner_halo = _dilate_mask(mask, kernel_size=9) & ~mask
    outer_halo = _dilate_mask(mask, kernel_size=17) & ~_dilate_mask(mask, kernel_size=7)
    fringe_specs = (
        (_shift_mask(inner_halo, x=-2), np.array((255.0, 250.0, 210.0), dtype=np.float32), 0.38),
        (_shift_mask(inner_halo, x=2), np.array((228.0, 220.0, 255.0), dtype=np.float32), 0.34),
        (_shift_mask(outer_halo, x=-3), np.array((255.0, 245.0, 215.0), dtype=np.float32), 0.18),
        (_shift_mask(outer_halo, x=3), np.array((212.0, 205.0, 255.0), dtype=np.float32), 0.16),
    )
    for halo_mask, color, strength in fringe_specs:
        halo_alpha = cv2.GaussianBlur((halo_mask.astype(np.uint8) * 255), (0, 0), sigmaX=2.0, sigmaY=2.0).astype(np.float32) / 255.0
        halo_alpha *= strength
        output = output * (1.0 - halo_alpha[:, :, None]) + color * halo_alpha[:, :, None]

    output = output * (1.0 - interior_alpha[:, :, None]) + silhouette_fill * interior_alpha[:, :, None]
    frame[:] = np.clip(output, 0, 255).astype(np.uint8)


def _apply_rf_detr_effect(
    frame: np.ndarray,
    mask: np.ndarray,
    *,
    effect: str,
    frame_index: int,
) -> None:
    if effect == "blackout":
        _blackout_mask(frame, mask)
        return
    if effect == "blur":
        _blur_mask(frame, mask)
        return
    if effect == "white-silhouette":
        _white_static_mask(frame, mask, frame_index=frame_index)
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
    if candidate_id == "rf-detr-passenger-blackout":
        return "blackout"
    if candidate_id == "rf-detr-passenger-blur":
        return "blur"
    if candidate_id == "rf-detr-passenger-white-static":
        return "white-silhouette"
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
    elif candidate_id == "rf-detr-passenger-blackout":
        behavior = "Runs RF-DETR segmentation on the full driver clip, selects the passenger-side person mask, and blacks out that whole body silhouette."
    elif candidate_id == "rf-detr-passenger-blur":
        behavior = "Runs RF-DETR segmentation on the full driver clip, selects the passenger-side body mask, and heavily blurs the masked silhouette."
    elif candidate_id == "rf-detr-passenger-white-static":
        behavior = "Runs RF-DETR segmentation on the full driver clip, selects the passenger-side body mask, and replaces it with a stylized flat white silhouette plus soft chromatic edge fringe."
    else:
        behavior = "Processes the DM-guided ROI on the full-frame driver clip."
    notes = f"Generated `{output_name}` in {report['runtime_seconds']:.2f}s. {behavior}"
    with path.open("a") as handle:
        handle.write(
            f"| {candidate_id} | {scores['identity_leakage']} | {scores['temporal_stability']} | "
            f"{scores['gaze_eye_readability']} | {scores['pose_preservation']} | "
            f"{scores['occlusion_robustness']} | {scores['runtime_complexity']} | {notes} |\n"
        )


def _run_rf_detr_passenger_blackout(
    *,
    sample_dir: Path,
    output_path: Path,
    track: dict[str, object],
    model_id: str,
    threshold: float,
    frame_stride: int,
    mask_dilate: int,
    startup_hold_frames: int,
    passenger_crop_margin_ratio: float,
) -> dict[str, object]:
    source_path = sample_dir / "driver-source.mp4"
    frames = list(track["frames"])
    passenger_anchor_rows = _load_optional_passenger_anchor_rows(sample_dir)
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
        capture.release()
        raise RuntimeError(f"Failed to create output clip: {output_path}")

    candidate_id = output_path.stem
    effect = _rf_detr_effect_for_candidate(candidate_id)
    model = _load_rf_detr_model(model_id)
    stride = max(1, int(frame_stride))
    last_mask: np.ndarray | None = None
    last_mask_box: tuple[int, int, int, int] | None = None
    missed_detections_since_last_mask = 0
    missing_hold_frames = 6
    startup_mask_source_frame_index: int | None = None
    startup_hold = max(0, int(startup_hold_frames))
    redacted_frames = 0
    detector_frames = 0
    output_frames = 0
    frame_reports: list[dict[str, object]] = []
    started = time.perf_counter()

    try:
        for frame_index, frame_row in enumerate(frames):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Video ended early at frame {frame_index}")

            in_startup_hold = frame_index < startup_hold
            rerun_detector = in_startup_hold or frame_index % stride == 0 or last_mask is None
            detection_report: dict[str, object] = {
                "frame_index": frame_index,
                "used_detector": rerun_detector,
                "selected_side": frame_row.get("selected_side"),
                "passenger_side": _passenger_side_for_frame(frame_row),
            }

            if rerun_detector:
                detector_frames += 1
                crop_rect = _passenger_crop_rect(
                    frame_row=frame_row,
                    frame_width=width,
                    frame_height=height,
                    margin_ratio=passenger_crop_margin_ratio,
                )
                crop_x, crop_y, crop_width, crop_height = crop_rect
                cropped_frame = frame[crop_y: crop_y + crop_height, crop_x: crop_x + crop_width]
                rgb_frame = cv2.cvtColor(cropped_frame, cv2.COLOR_BGR2RGB)
                crop_detections = model.predict(rgb_frame, threshold=threshold)
                detections = _expand_crop_detections_to_full_frame(
                    crop_detections,
                    crop_rect=crop_rect,
                    frame_width=width,
                    frame_height=height,
                )
                anchor_rect = passenger_anchor_rows.get(frame_index)
                selected_mask, selection_details = _choose_passenger_mask(
                    detections,
                    frame_row=frame_row,
                    frame_width=width,
                    frame_height=height,
                    anchor_rect=anchor_rect,
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
                    missed_detections_since_last_mask = 0
                    if startup_mask_source_frame_index is None and in_startup_hold:
                        startup_mask_source_frame_index = frame_index
                else:
                    missed_detections_since_last_mask += 1
                    if missed_detections_since_last_mask > missing_hold_frames:
                        last_mask = None
                        last_mask_box = None
            elif last_mask_box is not None:
                detection_report["reason"] = "reused_previous_mask"
                detection_report["mask_box"] = {
                    "x": last_mask_box[0],
                    "y": last_mask_box[1],
                    "width": last_mask_box[2],
                    "height": last_mask_box[3],
                }

            if in_startup_hold:
                detection_report["startup_hidden_trimmed"] = True
                frame_reports.append(detection_report)
                continue

            if last_mask is not None:
                _apply_rf_detr_effect(frame, last_mask, effect=effect, frame_index=frame_index)
                redacted_frames += 1

            writer.write(frame)
            output_frames += 1
            frame_reports.append(detection_report)
    finally:
        capture.release()
        writer.release()

    runtime_seconds = time.perf_counter() - started
    return {
        "candidate_id": candidate_id,
        "sample_dir": str(sample_dir),
        "source_clip": str(source_path),
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
        "rf_detr_startup_hold_applied": min(startup_hold, len(frames)),
        "rf_detr_startup_hold_trimmed_from_output": min(startup_hold, len(frames)),
        "rf_detr_passenger_crop_margin_ratio": passenger_crop_margin_ratio,
        "rf_detr_missing_hold_frames": missing_hold_frames,
        "rf_detr_effect": effect,
        "startup_mask_source_frame_index": startup_mask_source_frame_index,
        "frame_reports": frame_reports,
    }


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

    if args.candidate_id in RF_DETR_CANDIDATE_IDS:
        report = _run_rf_detr_passenger_blackout(
            sample_dir=sample_dir,
            output_path=output_path,
            track=track,
            model_id=args.rf_detr_model_id,
            threshold=args.rf_detr_threshold,
            frame_stride=args.rf_detr_frame_stride,
            mask_dilate=args.rf_detr_mask_dilate,
            startup_hold_frames=args.rf_detr_startup_hold_frames,
            passenger_crop_margin_ratio=args.rf_detr_passenger_crop_margin_ratio,
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
