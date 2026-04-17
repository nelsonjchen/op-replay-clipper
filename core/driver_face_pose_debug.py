from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a crop-level pose instability debug clip for FaceFusion swaps."
    )
    parser.add_argument("--target-crop", required=True)
    parser.add_argument("--swapped-crop", required=True)
    parser.add_argument("--facefusion-root", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--report-path")
    return parser


def _init_facefusion_runtime(facefusion_root: Path) -> dict[str, Any]:
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
        "get_many_faces": get_many_faces,
        "get_one_face": get_one_face,
        "sort_faces_by_order": sort_faces_by_order,
    }


def _extract_primary_face(runtime: dict[str, Any], frame: np.ndarray) -> Any | None:
    faces = runtime["get_many_faces"]([frame])
    faces = runtime["sort_faces_by_order"](faces, "large-small")
    return runtime["get_one_face"](faces)


def _face_points(face: Any | None, key: str) -> np.ndarray | None:
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
    if float(np.linalg.norm(delta)) <= 0.0:
        return None
    return math.degrees(math.atan2(float(delta[1]), float(delta[0])))


def _landmark_jump(previous_points: np.ndarray | None, current_points: np.ndarray | None) -> float | None:
    if previous_points is None or current_points is None or previous_points.shape != current_points.shape:
        return None
    deltas = previous_points - current_points
    distances = np.linalg.norm(deltas, axis=1)
    if distances.size == 0:
        return None
    return float(np.mean(distances))


def _landmark_fallback(face: Any | None) -> bool:
    if face is None:
        return False
    points_5 = _face_points(face, "5")
    points_5_68 = _face_points(face, "5/68")
    if points_5 is None or points_5_68 is None:
        return False
    return bool(np.array_equal(points_5, points_5_68))


def _draw_points(frame: np.ndarray, points: np.ndarray | None, *, color: tuple[int, int, int], radius: int) -> None:
    if points is None:
        return
    for point in points.astype(np.int32):
        cv2.circle(frame, tuple(point), radius, color, -1, lineType=cv2.LINE_AA)


def _draw_panel_title(frame: np.ndarray, title: str, subtitle: str | None = None) -> np.ndarray:
    output = frame.copy()
    panel_bottom = 78 if subtitle else 52
    cv2.rectangle(output, (10, 10), (output.shape[1] - 10, panel_bottom), (0, 0, 0), thickness=-1)
    cv2.putText(output, title, (22, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (255, 255, 255), 2, cv2.LINE_AA)
    if subtitle:
        cv2.putText(output, subtitle, (22, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.54, (210, 210, 210), 1, cv2.LINE_AA)
    return output


def _draw_face_overlay(
    frame: np.ndarray,
    face: Any | None,
    *,
    previous_points: np.ndarray | None = None,
    label: str,
) -> np.ndarray:
    output = frame.copy()
    border_color = (40, 220, 40)
    if _landmark_fallback(face):
        border_color = (0, 220, 255)
    if face is None:
        cv2.rectangle(output, (2, 2), (output.shape[1] - 3, output.shape[0] - 3), (0, 0, 255), 3)
        cv2.putText(output, f"{label}: no face", (14, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        return output

    box = np.asarray(face.bounding_box, dtype=np.int32)
    x1, y1, x2, y2 = box.tolist()
    cv2.rectangle(output, (x1, y1), (x2, y2), border_color, 2)
    points_68 = _face_points(face, "68")
    points_5 = _face_points(face, "5/68")
    _draw_points(output, points_68, color=(60, 255, 100), radius=1)
    _draw_points(output, previous_points, color=(0, 140, 255), radius=3)
    _draw_points(output, points_5, color=(255, 255, 255), radius=4)

    landmarker_score = float(face.score_set.get("landmarker", 0.0) or 0.0)
    eye_angle = _eye_angle_degrees(points_5)
    text = f"{label}: score={landmarker_score:.2f} angle={eye_angle:.1f}" if eye_angle is not None else f"{label}: score={landmarker_score:.2f}"
    cv2.putText(output, text, (14, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    if _landmark_fallback(face):
        cv2.putText(output, "fallback 5-point", (14, 136), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 220, 255), 2, cv2.LINE_AA)
    return output


def _delta_heatmap(previous_frame: np.ndarray | None, frame: np.ndarray) -> tuple[np.ndarray, float]:
    if previous_frame is None:
        return np.zeros_like(frame), 0.0
    diff = cv2.absdiff(frame, previous_frame)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    mean_delta = float(np.mean(gray))
    colored = cv2.applyColorMap(gray, cv2.COLORMAP_TURBO)
    blended = cv2.addWeighted(frame, 0.35, colored, 0.65, 0.0)
    return blended, mean_delta


def _metrics_panel(
    *,
    size: tuple[int, int],
    frame_index: int,
    fps: float,
    target_face: Any | None,
    swapped_face: Any | None,
    previous_swapped_points: np.ndarray | None,
    previous_target_points: np.ndarray | None,
    swapped_delta_mean: float,
) -> np.ndarray:
    width, height = size
    panel = np.zeros((height, width, 3), dtype=np.uint8)
    target_points = _face_points(target_face, "5/68")
    swapped_points = _face_points(swapped_face, "5/68")
    target_angle = _eye_angle_degrees(target_points)
    swapped_angle = _eye_angle_degrees(swapped_points)
    target_jump = _landmark_jump(previous_target_points, target_points)
    swapped_jump = _landmark_jump(previous_swapped_points, swapped_points)
    pose_gap = None
    if target_angle is not None and swapped_angle is not None:
        pose_gap = swapped_angle - target_angle

    lines = [
        "Legend: green=68pt, white=5/68, orange=prev swap",
        f"frame {frame_index}  t={frame_index / fps:0.2f}s",
        f"target fallback: {_landmark_fallback(target_face)}",
        f"swap fallback: {_landmark_fallback(swapped_face)}",
        f"target angle: {target_angle:0.2f}" if target_angle is not None else "target angle: n/a",
        f"swap angle: {swapped_angle:0.2f}" if swapped_angle is not None else "swap angle: n/a",
        f"pose gap: {pose_gap:0.2f}" if pose_gap is not None else "pose gap: n/a",
        f"target jump: {target_jump:0.2f}" if target_jump is not None else "target jump: n/a",
        f"swap jump: {swapped_jump:0.2f}" if swapped_jump is not None else "swap jump: n/a",
        f"swap delta mean: {swapped_delta_mean:0.2f}",
        f"target landmarker: {float(target_face.score_set.get('landmarker', 0.0) or 0.0):0.2f}" if target_face is not None else "target landmarker: n/a",
        f"swap landmarker: {float(swapped_face.score_set.get('landmarker', 0.0) or 0.0):0.2f}" if swapped_face is not None else "swap landmarker: n/a",
    ]
    y = 70
    for line in lines:
        cv2.putText(panel, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (255, 255, 255), 2, cv2.LINE_AA)
        y += 38
    return panel


def render_pose_debug(
    *,
    target_crop_path: Path,
    swapped_crop_path: Path,
    facefusion_root: Path,
    output_path: Path,
    report_path: Path | None,
) -> Path:
    runtime = _init_facefusion_runtime(facefusion_root)
    target_capture = cv2.VideoCapture(str(target_crop_path))
    swapped_capture = cv2.VideoCapture(str(swapped_crop_path))
    if not target_capture.isOpened():
        raise RuntimeError(f"Failed to open target crop clip: {target_crop_path}")
    if not swapped_capture.isOpened():
        raise RuntimeError(f"Failed to open swapped crop clip: {swapped_crop_path}")

    width = int(target_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(target_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(target_capture.get(cv2.CAP_PROP_FPS) or 20.0)
    output_size = (width * 2, height * 2)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, output_size)
    if not writer.isOpened():
        raise RuntimeError(f"Failed to create pose debug clip: {output_path}")

    previous_target_points: np.ndarray | None = None
    previous_swapped_points: np.ndarray | None = None
    previous_swapped_frame: np.ndarray | None = None
    report_rows: list[dict[str, Any]] = []
    frame_index = 0
    try:
        while True:
            ok_target, target_frame = target_capture.read()
            ok_swapped, swapped_frame = swapped_capture.read()
            if not ok_target and not ok_swapped:
                break
            if not ok_target or not ok_swapped or target_frame is None or swapped_frame is None:
                raise RuntimeError("Target and swapped crop clips must have matching frame counts")

            target_face = _extract_primary_face(runtime, target_frame)
            swapped_face = _extract_primary_face(runtime, swapped_frame)
            target_points = _face_points(target_face, "5/68")
            swapped_points = _face_points(swapped_face, "5/68")

            target_panel = _draw_panel_title(
                _draw_face_overlay(
                    target_frame,
                    target_face,
                    previous_points=previous_target_points,
                    label="target",
                ),
                "Target crop",
                "Original crop with current driver landmarks",
            )
            swapped_panel = _draw_panel_title(
                _draw_face_overlay(
                    swapped_frame,
                    swapped_face,
                    previous_points=previous_swapped_points,
                    label="swapped",
                ),
                "Swapped crop",
                "FaceFusion output with previous swap landmarks",
            )
            heatmap_panel, swapped_delta_mean = _delta_heatmap(previous_swapped_frame, swapped_frame)
            heatmap_panel = _draw_panel_title(
                heatmap_panel,
                "Swap delta heatmap",
                "Bright areas changed most vs previous swapped frame",
            )
            metrics_panel = _metrics_panel(
                size=(width, height),
                frame_index=frame_index,
                fps=fps,
                target_face=target_face,
                swapped_face=swapped_face,
                previous_swapped_points=previous_swapped_points,
                previous_target_points=previous_target_points,
                swapped_delta_mean=swapped_delta_mean,
            )
            metrics_panel = _draw_panel_title(
                metrics_panel,
                "Frame metrics",
                "Fallbacks, pose gap, landmark jumps, and scores",
            )
            debug_frame = np.vstack(
                (
                    np.hstack((target_panel, swapped_panel)),
                    np.hstack((heatmap_panel, metrics_panel)),
                )
            )
            writer.write(debug_frame)

            report_rows.append(
                {
                    "frame": frame_index,
                    "time_seconds": frame_index / fps,
                    "target_fallback": _landmark_fallback(target_face),
                    "swapped_fallback": _landmark_fallback(swapped_face),
                    "target_eye_angle": _eye_angle_degrees(target_points),
                    "swapped_eye_angle": _eye_angle_degrees(swapped_points),
                    "target_landmark_jump": _landmark_jump(previous_target_points, target_points),
                    "swapped_landmark_jump": _landmark_jump(previous_swapped_points, swapped_points),
                    "swapped_delta_mean": swapped_delta_mean,
                    "target_landmarker_score": float(target_face.score_set.get("landmarker", 0.0) or 0.0) if target_face is not None else None,
                    "swapped_landmarker_score": float(swapped_face.score_set.get("landmarker", 0.0) or 0.0) if swapped_face is not None else None,
                }
            )

            previous_target_points = target_points.copy() if target_points is not None else None
            previous_swapped_points = swapped_points.copy() if swapped_points is not None else None
            previous_swapped_frame = swapped_frame.copy()
            frame_index += 1
    finally:
        target_capture.release()
        swapped_capture.release()
        writer.release()

    if report_path is not None:
        report_path.write_text(json.dumps({"frames": report_rows}, indent=2, sort_keys=True) + "\n")
    return output_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    render_pose_debug(
        target_crop_path=Path(args.target_crop).resolve(),
        swapped_crop_path=Path(args.swapped_crop).resolve(),
        facefusion_root=Path(args.facefusion_root).resolve(),
        output_path=Path(args.output_path).resolve(),
        report_path=Path(args.report_path).resolve() if args.report_path else None,
    )
    print(Path(args.output_path).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
