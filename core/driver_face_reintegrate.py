from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Composite a swapped face-crop video back into the full driver clip.")
    parser.add_argument("--sample-dir", required=True)
    parser.add_argument("--source-video")
    parser.add_argument("--track-metadata")
    parser.add_argument("--target-crop")
    parser.add_argument("--swapped-crop", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--mask-box", choices=("padded_box", "raw_box", "crop_rect"), default="padded_box")
    parser.add_argument("--mask-expand", type=float, default=1.12)
    parser.add_argument("--feather-ratio", type=float, default=0.18)
    parser.add_argument("--banner-text", default="FACE ANONYMIZED")
    parser.add_argument("--facefusion-root")
    parser.add_argument("--bridge-landmark-fallback", action="store_true")
    parser.add_argument("--bridge-max-gap", type=int, default=2)
    parser.add_argument("--bridge-preroll-frames", type=int, default=0)
    parser.add_argument("--bridge-report")
    return parser


def _box(frame_row: dict[str, object], key: str) -> tuple[int, int, int, int] | None:
    value = frame_row.get(key)
    if not isinstance(value, dict):
        return None
    return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])


def _pick_mask_box(frame_row: dict[str, object], preferred: str) -> tuple[int, int, int, int] | None:
    for key in (preferred, "padded_box", "raw_box", "crop_rect"):
        rect = _box(frame_row, key)
        if rect is not None:
            return rect
    return None


def _clamp_rect(rect: tuple[float, float, float, float], *, width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    x1 = max(0, min(width, int(round(x))))
    y1 = max(0, min(height, int(round(y))))
    x2 = max(x1, min(width, int(round(x + w))))
    y2 = max(y1, min(height, int(round(y + h))))
    return x1, y1, max(0, x2 - x1), max(0, y2 - y1)


def _expand_rect(rect: tuple[int, int, int, int], *, scale: float, bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    bx, by, bw, bh = bounds
    x, y, w, h = rect
    center_x = x + (w / 2.0)
    center_y = y + (h / 2.0)
    expanded_w = w * scale
    expanded_h = h * scale
    local_x = center_x - (expanded_w / 2.0) - bx
    local_y = center_y - (expanded_h / 2.0) - by
    return _clamp_rect((local_x, local_y, expanded_w, expanded_h), width=bw, height=bh)


def _project_to_crop(mask_rect: tuple[int, int, int, int], crop_rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    mx, my, mw, mh = mask_rect
    cx, cy, cw, ch = crop_rect
    return mx - cx, my - cy, mw, mh


def _mask_for_crop(
    crop_size: tuple[int, int],
    crop_rect: tuple[int, int, int, int],
    mask_rect_frame: tuple[int, int, int, int] | None,
    *,
    mask_expand: float,
    feather_ratio: float,
) -> np.ndarray:
    crop_w, crop_h = crop_size
    if mask_rect_frame is None:
        return np.ones((crop_h, crop_w), dtype=np.float32)

    local_rect = _project_to_crop(mask_rect_frame, crop_rect)
    expanded_local = _expand_rect(local_rect, scale=mask_expand, bounds=(0, 0, crop_w, crop_h))
    mx, my, mw, mh = expanded_local
    if mw <= 0 or mh <= 0:
        return np.ones((crop_h, crop_w), dtype=np.float32)

    mask = np.zeros((crop_h, crop_w), dtype=np.float32)
    cv2.rectangle(mask, (mx, my), (mx + mw, my + mh), 1.0, thickness=-1)
    blur_size = max(3, int(round(min(mw, mh) * feather_ratio)))
    if blur_size % 2 == 0:
        blur_size += 1
    if blur_size > 1:
        mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)
    return np.clip(mask, 0.0, 1.0)


def _draw_banner(frame, text: str) -> None:
    if not text:
        return
    height, width = frame.shape[:2]
    pad_x = max(18, width // 50)
    pad_y = max(18, height // 40)
    font = cv2.FONT_HERSHEY_DUPLEX
    font_scale = max(0.75, min(1.6, width / 900.0))
    thickness = max(2, int(round(width / 640)))
    (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    box_x1 = pad_x
    box_y1 = pad_y
    box_x2 = min(width - pad_x, box_x1 + text_w + 28)
    box_y2 = min(height - pad_y, box_y1 + text_h + baseline + 26)
    cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), (0, 235, 255), thickness=-1)
    cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), (0, 0, 0), thickness=max(2, thickness))
    text_origin = (box_x1 + 14, box_y2 - baseline - 10)
    cv2.putText(frame, text, text_origin, font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)


def _bridge_spans(flags: list[bool], *, max_gap: int) -> list[dict[str, int | None]]:
    spans: list[dict[str, int | None]] = []
    gap_limit = max(1, int(max_gap))
    start_index: int | None = None

    def _append_span(end_index: int, next_good: int | None) -> None:
        nonlocal start_index
        assert start_index is not None
        previous_good: int | None = start_index - 1 if start_index > 0 else None
        gap_length = end_index - start_index + 1
        if gap_length <= gap_limit and (previous_good is not None or next_good is not None):
            spans.append(
                {
                    "start": start_index,
                    "end": end_index,
                    "previous_good": previous_good,
                    "next_good": next_good,
                }
            )
        start_index = None

    for frame_index, is_fallback in enumerate(flags):
        if is_fallback:
            if start_index is None:
                start_index = frame_index
            continue
        if start_index is None:
            continue
        _append_span(frame_index - 1, frame_index)
    if start_index is not None:
        _append_span(len(flags) - 1, None)
    return spans


def _adaptive_gap_limit(
    metric_rows: list[dict[str, object]],
    *,
    start_index: int,
    end_index: int,
    max_gap: int,
) -> int:
    limit = max(1, int(max_gap))
    run_rows = metric_rows[start_index:end_index + 1]
    if not run_rows:
        return limit
    if any(bool(row.get("target_missing", False) or row.get("swapped_missing", False)) for row in run_rows):
        limit += 2
    if any(bool(row.get("prefail_extended", False)) for row in run_rows):
        limit += 1
    visible_trail_frames = sum(
        1
        for row in run_rows
        if row.get("swapped_landmark_jump") is not None
        and float(row.get("swapped_landmark_jump") or 0.0) >= 5.0
        and float(row.get("swapped_delta_mean", 0.0) or 0.0) >= 1.2
    )
    if visible_trail_frames >= 3:
        limit += 2
    if visible_trail_frames >= 5:
        limit += 1
    return min(limit, 12)


def _adaptive_bridge_spans(
    flags: list[bool],
    metric_rows: list[dict[str, object]],
    *,
    max_gap: int,
) -> list[dict[str, int | None]]:
    spans: list[dict[str, int | None]] = []
    start_index: int | None = None

    def _append_span(end_index: int, next_good: int | None) -> None:
        nonlocal start_index
        assert start_index is not None
        previous_good: int | None = start_index - 1 if start_index > 0 else None
        gap_length = end_index - start_index + 1
        adaptive_limit = _adaptive_gap_limit(metric_rows, start_index=start_index, end_index=end_index, max_gap=max_gap)
        if gap_length <= adaptive_limit and (previous_good is not None or next_good is not None):
            spans.append(
                {
                    "start": start_index,
                    "end": end_index,
                    "previous_good": previous_good,
                    "next_good": next_good,
                    "gap_limit": adaptive_limit,
                }
            )
        start_index = None

    for frame_index, is_bad in enumerate(flags):
        if is_bad:
            if start_index is None:
                start_index = frame_index
            continue
        if start_index is None:
            continue
        _append_span(frame_index - 1, frame_index)
    if start_index is not None:
        _append_span(len(flags) - 1, None)
    return spans


def _collect_bridge_entries(spans: list[dict[str, int | None]]) -> dict[int, tuple[int | None, int | None]]:
    entries: dict[int, tuple[int | None, int | None]] = {}
    for span in spans:
        previous_good = span["previous_good"]
        next_good = span["next_good"]
        for frame_index in range(int(span["start"]), int(span["end"]) + 1):
            entries[frame_index] = (previous_good, next_good)
    return entries


def _apply_preroll_entries(
    entries: dict[int, tuple[int | None, int | None]],
    flags: list[bool],
    *,
    preroll_frames: int,
) -> tuple[dict[int, tuple[int | None, int | None]], dict[str, int | None]]:
    frame_count = len(flags)
    preroll_limit = max(0, min(int(preroll_frames), frame_count))
    if preroll_limit <= 0 or frame_count <= 1:
        return entries, {"requested_frames": preroll_limit, "applied_frames": 0, "anchor_frame": None}

    anchor_frame = next((index for index in range(preroll_limit, frame_count) if not flags[index]), None)
    if anchor_frame is None:
        return entries, {"requested_frames": preroll_limit, "applied_frames": 0, "anchor_frame": None}

    updated_entries = dict(entries)
    for frame_index in range(preroll_limit):
        updated_entries[frame_index] = (None, anchor_frame)

    return updated_entries, {
        "requested_frames": preroll_limit,
        "applied_frames": preroll_limit,
        "anchor_frame": anchor_frame,
    }


def _interpolate_frame(previous_frame: np.ndarray, next_frame: np.ndarray, *, weight: float) -> np.ndarray:
    clipped_weight = max(0.0, min(1.0, float(weight)))
    return cv2.addWeighted(previous_frame, 1.0 - clipped_weight, next_frame, clipped_weight, 0.0)


def _extract_selected_frames(video_path: Path, frame_indices: set[int]) -> dict[int, np.ndarray]:
    if not frame_indices:
        return {}
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open video for frame extraction: {video_path}")
    selected_frames: dict[int, np.ndarray] = {}
    ordered_indices = sorted(frame_indices)
    target_iter = iter(ordered_indices)
    next_target = next(target_iter, None)
    frame_index = 0
    try:
        while next_target is not None:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            if frame_index == next_target:
                selected_frames[frame_index] = frame.copy()
                next_target = next(target_iter, None)
            frame_index += 1
    finally:
        capture.release()
    missing = sorted(frame_indices.difference(selected_frames))
    if missing:
        raise RuntimeError(f"Failed to extract required anchor frames from {video_path}: {missing}")
    return selected_frames


def _init_facefusion_landmark_runtime(facefusion_root: Path) -> dict[str, object]:
    from core.driver_face_swap import apply_facefusion_runtime_env, default_facefusion_execution_providers

    apply_facefusion_runtime_env(facefusion_root)
    root_str = str(facefusion_root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from facefusion import face_classifier, face_detector, face_landmarker, face_masker, face_recognizer, state_manager
    from facefusion.face_analyser import get_many_faces, get_one_face
    from facefusion.face_selector import sort_faces_by_order

    state_manager.init_item("execution_device_ids", [0])
    state_manager.init_item("execution_providers", default_facefusion_execution_providers())
    state_manager.init_item("execution_thread_count", 4)
    state_manager.init_item("download_providers", ["github", "huggingface"])
    state_manager.init_item("face_detector_model", "yunet")
    state_manager.init_item("face_detector_size", "640x640")
    state_manager.init_item("face_detector_margin", [0, 0, 0, 0])
    state_manager.init_item("face_detector_score", 0.35)
    state_manager.init_item("face_detector_angles", [0])
    state_manager.init_item("face_landmarker_model", "2dfan4")
    state_manager.init_item("face_landmarker_score", 0.5)
    state_manager.init_item("face_selector_mode", "one")
    state_manager.init_item("face_selector_order", "large-small")
    state_manager.init_item("face_selector_gender", None)
    state_manager.init_item("face_selector_race", None)
    state_manager.init_item("face_selector_age_start", None)
    state_manager.init_item("face_selector_age_end", None)
    state_manager.init_item("reference_face_position", 0)
    state_manager.init_item("reference_face_distance", 0.3)
    state_manager.init_item("face_mask_types", ["box"])
    state_manager.init_item("face_mask_blur", 0.1)
    state_manager.init_item("face_mask_padding", [8, 8, 8, 8])
    state_manager.init_item("face_mask_areas", [])
    state_manager.init_item("face_mask_regions", [])
    state_manager.init_item("face_occluder_model", "xseg_1")
    state_manager.init_item("face_parser_model", "bisenet_resnet_34")
    state_manager.init_item("video_memory_strategy", "tolerant")
    state_manager.init_item("system_memory_limit", 0)

    face_detector.pre_check()
    face_recognizer.pre_check()
    face_classifier.pre_check()
    face_landmarker.pre_check()
    face_masker.pre_check()

    return {
        "state_manager": state_manager,
        "get_many_faces": get_many_faces,
        "get_one_face": get_one_face,
        "sort_faces_by_order": sort_faces_by_order,
    }


def _extract_primary_face(runtime: dict[str, object], frame: np.ndarray):
    faces = runtime["get_many_faces"]([frame])
    faces = runtime["sort_faces_by_order"](faces, "large-small")
    return runtime["get_one_face"](faces)


def _face_points(face, key: str) -> np.ndarray | None:
    if face is None:
        return None
    points = face.landmark_set.get(key)
    if points is None:
        return None
    array = np.asarray(points, dtype=np.float32)
    if array.ndim != 2 or array.shape[1] != 2 or array.size == 0:
        return None
    return array


def _eye_angle_degrees(points: np.ndarray | None) -> float | None:
    if points is None or len(points) < 2:
        return None
    delta = points[1] - points[0]
    magnitude = float(np.linalg.norm(delta))
    if magnitude <= 0.0:
        return None
    return float(np.degrees(np.arctan2(delta[1], delta[0])))


def _landmark_jump(previous_points: np.ndarray | None, current_points: np.ndarray | None) -> float | None:
    if previous_points is None or current_points is None or previous_points.shape != current_points.shape:
        return None
    distances = np.linalg.norm(previous_points - current_points, axis=1)
    if distances.size == 0:
        return None
    return float(np.mean(distances))


def _landmark_fallback(face) -> bool:
    points_5 = _face_points(face, "5")
    points_5_68 = _face_points(face, "5/68")
    if points_5 is None or points_5_68 is None:
        return False
    return bool(np.array_equal(points_5, points_5_68))


def _box_metrics(face) -> tuple[float, float, float, float] | None:
    if face is None:
        return None
    box = np.asarray(face.bounding_box, dtype=np.float32)
    if box.size != 4:
        return None
    x1, y1, x2, y2 = box.tolist()
    width = float(max(0.0, x2 - x1))
    height = float(max(0.0, y2 - y1))
    if width <= 0.0 or height <= 0.0:
        return None
    center_x = float(x1 + (width / 2.0))
    center_y = float(y1 + (height / 2.0))
    area = float(width * height)
    return center_x, center_y, width, height


def _bridge_flags_from_metrics(metric_rows: list[dict[str, object]]) -> tuple[list[bool], dict[str, int]]:
    flags: list[bool] = []
    fallback_frames = 0
    jump_frames = 0
    pose_gap_frames = 0
    target_missing_frames = 0
    swapped_missing_frames = 0
    geometry_mismatch_frames = 0
    for row in metric_rows:
        target_missing = bool(row.get("target_missing", False))
        swapped_missing = bool(row.get("swapped_missing", False))
        fallback = bool(row.get("target_fallback", False))
        swapped_jump = row.get("swapped_landmark_jump")
        target_jump = row.get("target_landmark_jump")
        pose_gap = row.get("pose_gap")
        swapped_delta_mean = float(row.get("swapped_delta_mean", 0.0) or 0.0)
        area_ratio = row.get("swapped_target_area_ratio")
        center_offset_ratio = row.get("swapped_target_center_offset_ratio")
        jumpy_swap = (
            swapped_jump is not None
            and float(swapped_jump) >= 24.0
            and (
                target_jump is None
                or float(swapped_jump) >= (float(target_jump) * 1.8)
                or (float(swapped_jump) - float(target_jump)) >= 8.0
            )
        )
        stable_target_jump = (
            swapped_jump is not None
            and target_jump is not None
            and float(swapped_jump) >= 9.0
            and float(target_jump) <= 3.5
            and (float(swapped_jump) - float(target_jump)) >= 5.5
            and swapped_delta_mean >= 1.2
        )
        visible_swap_trail = swapped_jump is not None and float(swapped_jump) >= 5.0 and swapped_delta_mean >= 1.2
        pose_jump = pose_gap is not None and abs(float(pose_gap)) >= 6.0 and swapped_delta_mean >= 1.2
        tiny_face = (
            area_ratio is not None
            and float(area_ratio) <= 0.80
            and swapped_delta_mean >= 1.0
            and (target_jump is None or float(target_jump) <= 4.0)
        )
        displaced_face = (
            center_offset_ratio is not None
            and float(center_offset_ratio) >= 0.18
            and swapped_delta_mean >= 1.0
        )
        geometry_mismatch = tiny_face or displaced_face
        is_bad = (
            target_missing
            or swapped_missing
            or fallback
            or jumpy_swap
            or stable_target_jump
            or visible_swap_trail
            or pose_jump
            or geometry_mismatch
        )
        if target_missing:
            target_missing_frames += 1
        if swapped_missing:
            swapped_missing_frames += 1
        if fallback:
            fallback_frames += 1
        if jumpy_swap or stable_target_jump or visible_swap_trail:
            jump_frames += 1
        if pose_jump:
            pose_gap_frames += 1
        if geometry_mismatch:
            geometry_mismatch_frames += 1
        flags.append(is_bad)
    return flags, {
        "fallback_frames": fallback_frames,
        "jump_frames": jump_frames,
        "pose_gap_frames": pose_gap_frames,
        "target_missing_frames": target_missing_frames,
        "swapped_missing_frames": swapped_missing_frames,
        "geometry_mismatch_frames": geometry_mismatch_frames,
    }


def _extend_prefail_flags(metric_rows: list[dict[str, object]], flags: list[bool]) -> tuple[list[bool], int]:
    if not metric_rows or not flags:
        return flags, 0
    extended = list(flags)
    prefail_frames = 0
    for frame_index in range(len(metric_rows) - 1):
        if extended[frame_index]:
            continue
        current_row = metric_rows[frame_index]
        next_row = metric_rows[frame_index + 1]
        next_missing = bool(next_row.get("target_missing", False) or next_row.get("swapped_missing", False))
        if not next_missing:
            continue
        target_jump = current_row.get("target_landmark_jump")
        swapped_delta_mean = float(current_row.get("swapped_delta_mean", 0.0) or 0.0)
        if swapped_delta_mean < 1.4:
            continue
        if target_jump is not None and float(target_jump) > 2.0:
            continue
        extended[frame_index] = True
        metric_rows[frame_index]["prefail_extended"] = True
        prefail_frames += 1
    return extended, prefail_frames


def _detect_bridge_metrics(
    target_crop_path: Path,
    swapped_crop_path: Path,
    *,
    facefusion_root: Path,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    runtime = _init_facefusion_landmark_runtime(facefusion_root)
    target_capture = cv2.VideoCapture(str(target_crop_path))
    swapped_capture = cv2.VideoCapture(str(swapped_crop_path))
    if not target_capture.isOpened():
        raise RuntimeError(f"Failed to open target crop video: {target_crop_path}")
    if not swapped_capture.isOpened():
        raise RuntimeError(f"Failed to open swapped crop video: {swapped_crop_path}")

    rows: list[dict[str, object]] = []
    total_faces = 0
    missing_faces = 0
    previous_target_points: np.ndarray | None = None
    previous_swapped_points: np.ndarray | None = None
    previous_swapped_frame: np.ndarray | None = None
    try:
        while True:
            ok_target, target_frame = target_capture.read()
            ok_swapped, swapped_frame = swapped_capture.read()
            if not ok_target and not ok_swapped:
                break
            if not ok_target or not ok_swapped or target_frame is None or swapped_frame is None:
                raise RuntimeError("Target and swapped crop videos must have matching frame counts")
            target_face = _extract_primary_face(runtime, target_frame)
            swapped_face = _extract_primary_face(runtime, swapped_frame)
            if target_face is None:
                missing_faces += 1
            else:
                total_faces += 1
            target_points = _face_points(target_face, "5/68")
            swapped_points = _face_points(swapped_face, "5/68")
            target_angle = _eye_angle_degrees(target_points)
            swapped_angle = _eye_angle_degrees(swapped_points)
            pose_gap = None
            if target_angle is not None and swapped_angle is not None:
                pose_gap = float(swapped_angle - target_angle)
            swapped_delta_mean = 0.0
            if previous_swapped_frame is not None:
                swapped_delta_mean = float(
                    np.mean(cv2.cvtColor(cv2.absdiff(swapped_frame, previous_swapped_frame), cv2.COLOR_BGR2GRAY))
                )
            target_box = _box_metrics(target_face)
            swapped_box = _box_metrics(swapped_face)
            area_ratio = None
            center_offset_ratio = None
            if target_box is not None and swapped_box is not None:
                target_center_x, target_center_y, target_width, target_height = target_box
                swapped_center_x, swapped_center_y, swapped_width, swapped_height = swapped_box
                target_area = target_width * target_height
                swapped_area = swapped_width * swapped_height
                if target_area > 0.0:
                    area_ratio = float(swapped_area / target_area)
                normalizer = max(1.0, float(np.hypot(target_width, target_height)))
                center_distance = float(np.hypot(swapped_center_x - target_center_x, swapped_center_y - target_center_y))
                center_offset_ratio = center_distance / normalizer
            rows.append(
                {
                    "target_missing": target_face is None,
                    "swapped_missing": swapped_face is None,
                    "target_fallback": _landmark_fallback(target_face),
                    "target_landmark_jump": _landmark_jump(previous_target_points, target_points),
                    "swapped_landmark_jump": _landmark_jump(previous_swapped_points, swapped_points),
                    "target_eye_angle": target_angle,
                    "swapped_eye_angle": swapped_angle,
                    "pose_gap": pose_gap,
                    "swapped_delta_mean": swapped_delta_mean,
                    "swapped_target_area_ratio": area_ratio,
                    "swapped_target_center_offset_ratio": center_offset_ratio,
                }
            )
            previous_target_points = target_points.copy() if target_points is not None else None
            previous_swapped_points = swapped_points.copy() if swapped_points is not None else None
            previous_swapped_frame = swapped_frame.copy()
    finally:
        target_capture.release()
        swapped_capture.release()

    return rows, {
        "frames_analyzed": len(rows),
        "faces_detected": total_faces,
        "missing_faces": missing_faces,
    }


def _prepare_landmark_fallback_bridge(
    *,
    target_crop_path: Path,
    swapped_crop_path: Path,
    facefusion_root: Path,
    max_gap: int,
    preroll_frames: int,
) -> tuple[dict[int, tuple[int, int]], dict[int, np.ndarray], dict[str, object]]:
    metric_rows, metrics = _detect_bridge_metrics(
        target_crop_path,
        swapped_crop_path,
        facefusion_root=facefusion_root,
    )
    flags, classified_counts = _bridge_flags_from_metrics(metric_rows)
    flags, prefail_frames = _extend_prefail_flags(metric_rows, flags)
    spans = _adaptive_bridge_spans(flags, metric_rows, max_gap=max_gap)
    bridge_entries = _collect_bridge_entries(spans)
    bridge_entries, preroll_report = _apply_preroll_entries(
        bridge_entries,
        flags,
        preroll_frames=preroll_frames,
    )
    anchor_indices = {anchor for anchors in bridge_entries.values() for anchor in anchors if anchor is not None}
    anchor_frames = _extract_selected_frames(swapped_crop_path, anchor_indices)
    report: dict[str, object] = {
        "enabled": True,
        "max_gap": max(1, int(max_gap)),
        "frames_analyzed": metrics["frames_analyzed"],
        "faces_detected": metrics["faces_detected"],
        "missing_faces": metrics["missing_faces"],
        "fallback_frames": classified_counts["fallback_frames"],
        "jump_frames": classified_counts["jump_frames"],
        "pose_gap_frames": classified_counts["pose_gap_frames"],
        "target_missing_frames": classified_counts["target_missing_frames"],
        "swapped_missing_frames": classified_counts["swapped_missing_frames"],
        "geometry_mismatch_frames": classified_counts["geometry_mismatch_frames"],
        "prefail_extension_frames": prefail_frames,
        "bridged_frames": len(bridge_entries),
        "bridged_spans": spans,
        "bridge_metrics": metric_rows,
        "preroll_frames_requested": preroll_report["requested_frames"],
        "preroll_frames_applied": preroll_report["applied_frames"],
        "preroll_anchor_frame": preroll_report["anchor_frame"],
    }
    return bridge_entries, anchor_frames, report


def composite_sample(
    *,
    sample_dir: Path,
    source_video_path: Path | None,
    track_metadata_path: Path | None,
    target_crop_path: Path | None,
    swapped_crop_path: Path,
    output_path: Path,
    mask_box: str,
    mask_expand: float,
    feather_ratio: float,
    banner_text: str,
    bridge_landmark_fallback: bool,
    facefusion_root: Path | None,
    bridge_max_gap: int,
    bridge_preroll_frames: int,
    bridge_report_path: Path | None,
) -> Path:
    track_path = track_metadata_path if track_metadata_path is not None else sample_dir / "face-track.json"
    source_path = source_video_path if source_video_path is not None else sample_dir / "driver-source.mp4"
    manifest = json.loads(track_path.read_text())
    frame_rows = list(manifest["frames"])
    bridge_entries: dict[int, tuple[int | None, int | None]] = {}
    bridge_anchor_frames: dict[int, np.ndarray] = {}
    bridge_report: dict[str, object] = {"enabled": False}
    if bridge_landmark_fallback:
        if target_crop_path is None:
            raise ValueError("--target-crop is required when --bridge-landmark-fallback is enabled")
        if facefusion_root is None:
            raise ValueError("--facefusion-root is required when --bridge-landmark-fallback is enabled")
        bridge_entries, bridge_anchor_frames, bridge_report = _prepare_landmark_fallback_bridge(
            target_crop_path=target_crop_path,
            swapped_crop_path=swapped_crop_path,
            facefusion_root=facefusion_root,
            max_gap=bridge_max_gap,
            preroll_frames=bridge_preroll_frames,
        )
    if bridge_report_path is not None:
        bridge_report_path.parent.mkdir(parents=True, exist_ok=True)
        bridge_report_path.write_text(json.dumps(bridge_report, indent=2, sort_keys=True) + "\n")

    source_capture = cv2.VideoCapture(str(source_path))
    swapped_capture = cv2.VideoCapture(str(swapped_crop_path))
    if not source_capture.isOpened():
        raise RuntimeError(f"Failed to open source clip: {source_path}")
    if not swapped_capture.isOpened():
        raise RuntimeError(f"Failed to open swapped crop clip: {swapped_crop_path}")

    width = int(source_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(source_capture.get(cv2.CAP_PROP_FPS) or manifest.get("framerate") or 20.0)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Failed to create output clip: {output_path}")

    try:
        for frame_index, row in enumerate(frame_rows):
            ok_source, source_frame = source_capture.read()
            ok_swap, swap_frame = swapped_capture.read()
            if not ok_source or not ok_swap:
                raise RuntimeError("Source and swapped crop videos must have matching frame counts")
            bridge_pair = bridge_entries.get(frame_index)
            if bridge_pair is not None:
                previous_good, next_good = bridge_pair
                if previous_good is None and next_good is not None:
                    swap_frame = bridge_anchor_frames[next_good].copy()
                elif next_good is None and previous_good is not None:
                    swap_frame = bridge_anchor_frames[previous_good].copy()
                elif previous_good is not None and next_good is not None:
                    previous_frame = bridge_anchor_frames[previous_good]
                    next_frame = bridge_anchor_frames[next_good]
                    weight = (frame_index - previous_good) / float(next_good - previous_good)
                    swap_frame = _interpolate_frame(previous_frame, next_frame, weight=weight)

            crop_rect = _box(row, "crop_rect")
            if crop_rect is None:
                _draw_banner(source_frame, banner_text)
                writer.write(source_frame)
                continue

            crop_x, crop_y, crop_w, crop_h = crop_rect
            if crop_w <= 0 or crop_h <= 0:
                _draw_banner(source_frame, banner_text)
                writer.write(source_frame)
                continue

            resized_swap = cv2.resize(swap_frame, (crop_w, crop_h), interpolation=cv2.INTER_LANCZOS4)
            mask_rect = _pick_mask_box(row, mask_box)
            alpha = _mask_for_crop(
                (crop_w, crop_h),
                crop_rect,
                mask_rect,
                mask_expand=mask_expand,
                feather_ratio=feather_ratio,
            )
            alpha = alpha[:, :, None]
            source_roi = source_frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w].astype(np.float32)
            swap_roi = resized_swap.astype(np.float32)
            blended = (alpha * swap_roi) + ((1.0 - alpha) * source_roi)
            source_frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w] = np.clip(blended, 0, 255).astype(np.uint8)
            _draw_banner(source_frame, banner_text)
            writer.write(source_frame)
    finally:
        source_capture.release()
        swapped_capture.release()
        writer.release()

    return output_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    composite_sample(
        sample_dir=Path(args.sample_dir).resolve(),
        source_video_path=Path(args.source_video).resolve() if args.source_video else None,
        track_metadata_path=Path(args.track_metadata).resolve() if args.track_metadata else None,
        target_crop_path=Path(args.target_crop).resolve() if args.target_crop else None,
        swapped_crop_path=Path(args.swapped_crop).resolve(),
        output_path=Path(args.output_path).resolve(),
        mask_box=args.mask_box,
        mask_expand=args.mask_expand,
        feather_ratio=args.feather_ratio,
        banner_text=args.banner_text,
        bridge_landmark_fallback=bool(args.bridge_landmark_fallback),
        facefusion_root=Path(args.facefusion_root).resolve() if args.facefusion_root else None,
        bridge_max_gap=args.bridge_max_gap,
        bridge_preroll_frames=args.bridge_preroll_frames,
        bridge_report_path=Path(args.bridge_report).resolve() if args.bridge_report else None,
    )
    print(Path(args.output_path).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
