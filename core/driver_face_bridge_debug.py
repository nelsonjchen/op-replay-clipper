from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a full-frame bridge geometry debug clip.")
    parser.add_argument("--source-video", required=True)
    parser.add_argument("--track-metadata", required=True)
    parser.add_argument("--bridge-report", required=True)
    parser.add_argument("--target-crop")
    parser.add_argument("--swapped-crop")
    parser.add_argument("--facefusion-root")
    parser.add_argument("--output-path", required=True)
    return parser


def _box(frame_row: dict[str, object], key: str) -> tuple[int, int, int, int] | None:
    value = frame_row.get(key)
    if not isinstance(value, dict):
        return None
    return int(round(float(value["x"]))), int(round(float(value["y"]))), int(round(float(value["width"]))), int(round(float(value["height"])))


def _draw_labeled_box(
    frame: np.ndarray,
    rect: tuple[int, int, int, int] | None,
    *,
    color: tuple[int, int, int],
    label: str,
    thickness: int = 2,
) -> None:
    if rect is None:
        return
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, thickness)
    cv2.putText(frame, label, (x + 6, max(26, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.72, color, 2, cv2.LINE_AA)


def _draw_header(frame: np.ndarray, lines: list[str]) -> None:
    line_height = 34
    panel_height = 24 + (line_height * len(lines))
    cv2.rectangle(frame, (18, 18), (760, 18 + panel_height), (0, 0, 0), -1)
    y = 52
    for line in lines:
        cv2.putText(frame, line, (34, y), cv2.FONT_HERSHEY_SIMPLEX, 0.84, (255, 255, 255), 2, cv2.LINE_AA)
        y += line_height


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
    state_manager.init_item("reference_face_position", 0)
    state_manager.init_item("reference_face_distance", 0.3)
    state_manager.init_item("face_mask_types", ["box"])
    state_manager.init_item("face_mask_blur", 0.1)
    state_manager.init_item("face_mask_padding", [8, 8, 8, 8])
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


def _project_points_to_full_frame(
    points: np.ndarray | None,
    crop_rect: tuple[int, int, int, int] | None,
    crop_size: tuple[int, int],
) -> np.ndarray | None:
    if points is None or crop_rect is None:
        return None
    crop_x, crop_y, crop_w, crop_h = crop_rect
    crop_width, crop_height = crop_size
    if crop_w <= 0 or crop_h <= 0 or crop_width <= 0 or crop_height <= 0:
        return None
    scale_x = crop_w / float(crop_width)
    scale_y = crop_h / float(crop_height)
    projected = points.copy().astype(np.float32)
    projected[:, 0] = crop_x + (projected[:, 0] * scale_x)
    projected[:, 1] = crop_y + (projected[:, 1] * scale_y)
    return projected


def _draw_points(
    frame: np.ndarray,
    points: np.ndarray | None,
    *,
    color: tuple[int, int, int],
    radius: int,
) -> None:
    if points is None:
        return
    for point in points.astype(np.int32):
        cv2.circle(frame, tuple(point), radius, color, -1, lineType=cv2.LINE_AA)


def render_bridge_geometry_debug(
    *,
    source_video_path: Path,
    track_metadata_path: Path,
    bridge_report_path: Path,
    target_crop_path: Path | None,
    swapped_crop_path: Path | None,
    facefusion_root: Path | None,
    output_path: Path,
) -> Path:
    manifest = json.loads(track_metadata_path.read_text())
    report = json.loads(bridge_report_path.read_text())
    frame_rows = list(manifest["frames"])
    bridge_metrics = list(report.get("bridge_metrics", []))
    span_by_frame: dict[int, dict[str, int | None]] = {}
    for span in report.get("bridged_spans", []):
        for frame_index in range(int(span["start"]), int(span["end"]) + 1):
            span_by_frame[frame_index] = span

    capture = cv2.VideoCapture(str(source_video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open source video: {source_video_path}")
    target_capture: cv2.VideoCapture | None = None
    swapped_capture: cv2.VideoCapture | None = None
    runtime: dict[str, Any] | None = None
    crop_size: tuple[int, int] | None = None
    if target_crop_path is not None and swapped_crop_path is not None and facefusion_root is not None:
        runtime = _init_facefusion_runtime(facefusion_root)
        target_capture = cv2.VideoCapture(str(target_crop_path))
        swapped_capture = cv2.VideoCapture(str(swapped_crop_path))
        if not target_capture.isOpened() or not swapped_capture.isOpened():
            raise RuntimeError("Failed to open crop videos for bridge geometry debug")
        crop_width = int(target_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        crop_height = int(target_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        crop_size = (crop_width, crop_height)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or manifest.get("framerate") or 20.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Failed to create bridge debug clip: {output_path}")

    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            ok_target = True
            ok_swapped = True
            target_crop_frame = None
            swapped_crop_frame = None
            if target_capture is not None and swapped_capture is not None:
                ok_target, target_crop_frame = target_capture.read()
                ok_swapped, swapped_crop_frame = swapped_capture.read()
            if not ok or frame is None:
                break
            if not ok_target or not ok_swapped:
                raise RuntimeError("Crop debug inputs must have matching frame counts")
            row = frame_rows[frame_index]
            metric_row = bridge_metrics[frame_index] if frame_index < len(bridge_metrics) else {}
            span = span_by_frame.get(frame_index)

            crop_rect = _box(row, "crop_rect")
            padded_box = _box(row, "padded_box")
            raw_box = _box(row, "raw_box")
            bridged = span is not None

            overlay = frame.copy()
            if crop_rect is not None:
                x, y, w, h = crop_rect
                fill_color = (0, 80, 220) if bridged else (0, 140, 0)
                cv2.rectangle(overlay, (x, y), (x + w, y + h), fill_color, -1)
            frame = cv2.addWeighted(overlay, 0.14 if bridged else 0.08, frame, 0.92 if not bridged else 0.86, 0.0)

            _draw_labeled_box(frame, crop_rect, color=(60, 255, 80) if not bridged else (0, 180, 255), label="crop rect", thickness=3)
            _draw_labeled_box(frame, padded_box, color=(255, 255, 0), label="padded box")
            _draw_labeled_box(frame, raw_box, color=(255, 120, 80), label="raw box")
            if runtime is not None and crop_rect is not None and crop_size is not None:
                target_face = _extract_primary_face(runtime, target_crop_frame)
                swapped_face = _extract_primary_face(runtime, swapped_crop_frame)
                target_points = _project_points_to_full_frame(_face_points(target_face, "5/68"), crop_rect, crop_size)
                swapped_points = _project_points_to_full_frame(_face_points(swapped_face, "5/68"), crop_rect, crop_size)
                _draw_points(frame, target_points, color=(255, 255, 255), radius=4)
                _draw_points(frame, swapped_points, color=(0, 200, 255), radius=3)

            lines = [
                f"Geometry debug   frame {frame_index}   t={frame_index / fps:0.2f}s",
                "bridged: yes" if bridged else "bridged: no",
            ]
            if span is not None:
                lines.append(
                    f"span {int(span['start'])}-{int(span['end'])}   anchors {span['previous_good']} -> {span['next_good']}"
                )
            else:
                lines.append("span: none")
            area_ratio = metric_row.get("swapped_target_area_ratio")
            center_offset = metric_row.get("swapped_target_center_offset_ratio")
            if area_ratio is not None or center_offset is not None:
                lines.append(
                    f"area ratio={area_ratio:0.3f}   center offset={center_offset:0.3f}"
                    if area_ratio is not None and center_offset is not None
                    else f"area ratio={area_ratio!s}   center offset={center_offset!s}"
                )
            else:
                lines.append("area ratio=n/a   center offset=n/a")
            if runtime is not None:
                lines.append("markers: white=target 5/68   cyan=swapped 5/68")
            _draw_header(frame, lines)
            writer.write(frame)
            frame_index += 1
    finally:
        capture.release()
        if target_capture is not None:
            target_capture.release()
        if swapped_capture is not None:
            swapped_capture.release()
        writer.release()

    return output_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    render_bridge_geometry_debug(
        source_video_path=Path(args.source_video).resolve(),
        track_metadata_path=Path(args.track_metadata).resolve(),
        bridge_report_path=Path(args.bridge_report).resolve(),
        target_crop_path=Path(args.target_crop).resolve() if args.target_crop else None,
        swapped_crop_path=Path(args.swapped_crop).resolve() if args.swapped_crop else None,
        facefusion_root=Path(args.facefusion_root).resolve() if args.facefusion_root else None,
        output_path=Path(args.output_path).resolve(),
    )
    print(Path(args.output_path).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
