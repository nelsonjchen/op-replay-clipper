from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import cv2
import numpy as np

from renderers.big_ui_engine import (
    CameraFrameRef,
    RenderStep,
    _configure_gui_app_canvas,
    build_camera_frame_refs,
    patch_shader_polygon_gradient_coordinates,
    seed_future_backfill_state,
    _match_camera_ref,
    _patch_pyray_headless_window_flags,
    _reapply_hidden_window_flag,
)
from renderers.video_renderer import (
    VideoAcceleration,
    _encoder_output_args,
)


FRAMERATE = 20
WIDE_CAMERA_SERVICE = "wideRoadEncodeIdx"
MODEL_SERVICE = "modelV2"
CONTEXT_SERVICES = ("liveCalibration", "roadCameraState", "deviceState")
PATH_HALF_WIDTH_METERS = 0.9
MIN_DRAW_DISTANCE = 10.0
MAX_DRAW_DISTANCE = 100.0
DEFAULT_REUSE_FRAMES = 5
DEFAULT_HEIGHT_METERS = 1.22


@dataclass(frozen=True)
class PathOverlayFrame:
    frame_index: int
    route_seconds: float
    polygon: np.ndarray


@dataclass(frozen=True)
class OverlayGenerationResult:
    pattern: str
    frame_count: int
    rendered_count: int
    reused_count: int


@dataclass(frozen=True)
class FloatRect:
    x: float
    y: float
    width: float
    height: float


def add_openpilot_to_sys_path(openpilot_dir: str | Path) -> None:
    resolved = Path(openpilot_dir).expanduser().resolve()
    path_entries = [resolved]
    if (resolved / "__init__.py").exists() and resolved.name == "openpilot":
        path_entries.insert(0, resolved.parent)
    for entry in reversed(path_entries):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    existing = os.environ.get("PYTHONPATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    prepend = [str(entry) for entry in path_entries if str(entry) not in parts]
    if prepend:
        os.environ["PYTHONPATH"] = os.pathsep.join([*prepend, *parts]) if parts else os.pathsep.join(prepend)


def route_date(route: str) -> str:
    return route.split("|", 1)[1]


def segment_numbers(start_seconds: int, length_seconds: int) -> list[int]:
    return list(range(start_seconds // 60, (start_seconds + length_seconds) // 60 + 1))


def segment_file_path(data_dir: str | Path, route: str, segment: int, filename: str) -> Path:
    return Path(data_dir) / f"{route_date(route)}--{segment}" / filename


def concat_string(data_dir: str | Path, route: str, segments: list[int], filename: str) -> str:
    inputs = [str(segment_file_path(data_dir, route, segment, filename)) for segment in segments]
    return f"concat:{'|'.join(inputs)}"


def find_log_path(data_dir: str | Path, route: str, segment: int) -> Path:
    segment_dir = Path(data_dir) / f"{route_date(route)}--{segment}"
    for filename in ("rlog", "rlog.zst", "rlog.bz2", "qlog", "qlog.zst", "qlog.bz2"):
        candidate = segment_dir / filename
        if candidate.exists():
            return candidate
    raise RuntimeError(f"No log file found in {segment_dir}")


def load_segment_messages(data_dir: str | Path, route: str, segments: list[int]) -> list[list[object]]:
    from openpilot.selfdrive.test.process_replay.migration import migrate_all
    from openpilot.tools.lib.logreader import LogReader

    messages_by_segment: list[list[object]] = []
    for segment in segments:
        log_path = find_log_path(data_dir, route, segment)
        messages_by_segment.append(migrate_all(list(LogReader(str(log_path)))))
    return messages_by_segment


def seed_context_state(ordered_messages: list[object]) -> dict[str, object]:
    state: dict[str, object] = {}
    for msg in ordered_messages:
        which = msg.which()
        if which in CONTEXT_SERVICES and which not in state:
            state[which] = msg
            if len(state) == len(CONTEXT_SERVICES):
                break
    return state


def _payload(msg: object | None, which: str) -> object | None:
    return getattr(msg, which, None) if msg is not None else None


def _message_has_context(state: Mapping[str, object]) -> bool:
    return all(service in state for service in CONTEXT_SERVICES)


def _device_camera_config(state: Mapping[str, object]):
    from openpilot.common.transformations.camera import DEVICE_CAMERAS

    device_state = _payload(state.get("deviceState"), "deviceState")
    road_camera_state = _payload(state.get("roadCameraState"), "roadCameraState")
    if device_state is None:
        raise RuntimeError("Missing deviceState; cannot select camera intrinsics")
    if road_camera_state is None:
        raise RuntimeError("Missing roadCameraState; cannot select camera intrinsics")

    device_type = str(getattr(device_state, "deviceType", "unknown"))
    sensor = str(getattr(road_camera_state, "sensor", "unknown"))
    try:
        return DEVICE_CAMERAS[(device_type, sensor)]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported camera config for deviceType={device_type!r}, sensor={sensor!r}") from exc


def wide_camera_projection_matrix(state: Mapping[str, object]) -> np.ndarray:
    from openpilot.common.transformations.camera import view_frame_from_device_frame
    from openpilot.common.transformations.orientation import rot_from_euler

    live_calibration = _payload(state.get("liveCalibration"), "liveCalibration")
    if live_calibration is None:
        raise RuntimeError("Missing liveCalibration; cannot project model path")

    rpy_calib = list(getattr(live_calibration, "rpyCalib", []) or [])
    if len(rpy_calib) != 3:
        raise RuntimeError("liveCalibration.rpyCalib must contain 3 values")

    wide_from_device_euler = list(getattr(live_calibration, "wideFromDeviceEuler", []) or [])
    if len(wide_from_device_euler) != 3:
        raise RuntimeError("liveCalibration.wideFromDeviceEuler must contain 3 values")

    device_camera = _device_camera_config(state)
    device_from_calib = rot_from_euler(rpy_calib)
    wide_from_device = rot_from_euler(wide_from_device_euler)
    view_from_calib = view_frame_from_device_frame @ wide_from_device @ device_from_calib
    return device_camera.ecam.intrinsics @ view_from_calib


def _path_height_meters(state: Mapping[str, object]) -> float:
    live_calibration = _payload(state.get("liveCalibration"), "liveCalibration")
    if live_calibration is None:
        return DEFAULT_HEIGHT_METERS
    height = list(getattr(live_calibration, "height", []) or [])
    if not height:
        return DEFAULT_HEIGHT_METERS
    return float(height[0])


def _path_length_idx(pos_x_array: np.ndarray, path_distance: float) -> int:
    if len(pos_x_array) == 0:
        return 0
    indices = np.where(pos_x_array <= path_distance)[0]
    return int(indices[-1]) if indices.size > 0 else 0


def prepare_path_points(raw_points: np.ndarray, max_distance: float) -> np.ndarray:
    if raw_points.shape[0] == 0:
        return np.empty((0, 3), dtype=np.float32)

    max_idx = _path_length_idx(raw_points[:, 0], max_distance)
    points = raw_points[: max_idx + 1]
    if 0 < max_idx < raw_points.shape[0] - 1:
        p0 = raw_points[max_idx]
        p1 = raw_points[max_idx + 1]
        interp_point = np.array(
            [
                max_distance,
                np.interp(max_distance, [p0[0], p1[0]], [p0[1], p1[1]]),
                np.interp(max_distance, [p0[0], p1[0]], [p0[2], p1[2]]),
            ],
            dtype=raw_points.dtype,
        )
        points = np.concatenate((points, interp_point[None, :]), axis=0)
    return points[points[:, 0] >= 0]


def project_path_polygon(
    raw_points: np.ndarray,
    projection_matrix: np.ndarray,
    *,
    frame_width: int,
    frame_height: int,
    z_offset: float,
    half_width: float = PATH_HALF_WIDTH_METERS,
) -> np.ndarray:
    if raw_points.shape[0] == 0:
        return np.empty((0, 2), dtype=np.float32)

    max_distance = float(np.clip(raw_points[-1, 0], MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE))
    points = prepare_path_points(raw_points, max_distance)
    if points.shape[0] < 2:
        return np.empty((0, 2), dtype=np.float32)

    offsets = np.array([[0.0, -half_width, z_offset], [0.0, half_width, z_offset]], dtype=np.float32)
    points_3d = (points[None, :, :] + offsets[:, None, :]).reshape(2 * len(points), 3)
    projected = projection_matrix @ points_3d.T
    projected = projected.reshape(3, 2, len(points))
    left_proj = projected[:, 0, :]
    right_proj = projected[:, 1, :]

    valid = (np.abs(left_proj[2]) >= 1e-6) & (np.abs(right_proj[2]) >= 1e-6)
    if not np.any(valid):
        return np.empty((0, 2), dtype=np.float32)

    left = left_proj[:2, valid] / left_proj[2, valid][None, :]
    right = right_proj[:2, valid] / right_proj[2, valid][None, :]
    in_frame = (
        (left[0] >= 0)
        & (left[0] <= frame_width)
        & (left[1] >= 0)
        & (left[1] <= frame_height)
        & (right[0] >= 0)
        & (right[0] <= frame_width)
        & (right[1] >= 0)
        & (right[1] <= frame_height)
    )
    if not np.any(in_frame):
        return np.empty((0, 2), dtype=np.float32)

    left = left[:, in_frame]
    right = right[:, in_frame]
    if left.shape[1] > 1:
        keep = left[1, :] == np.minimum.accumulate(left[1, :])
        left = left[:, keep]
        right = right[:, keep]
    if left.shape[1] < 2:
        return np.empty((0, 2), dtype=np.float32)
    return np.vstack((left.T, right[:, ::-1].T)).astype(np.float32)


def render_path_overlay_frame(frame_width: int, frame_height: int, polygon: np.ndarray) -> np.ndarray:
    frame = np.zeros((frame_height, frame_width, 4), dtype=np.uint8)
    if polygon.shape[0] < 4:
        return frame

    half = polygon.shape[0] // 2
    left = polygon[:half]
    right = polygon[half:][::-1]
    max_segments = min(len(left), len(right)) - 1
    for idx in range(max_segments):
        segment = np.array([left[idx], left[idx + 1], right[idx + 1], right[idx]], dtype=np.int32)
        t = idx / max(1, max_segments - 1)
        alpha = int(np.interp(t, [0.0, 1.0], [120, 8]))
        color = (
            int(np.interp(t, [0.0, 1.0], [255, 80])),
            255,
            int(np.interp(t, [0.0, 1.0], [210, 60])),
            alpha,
        )
        cv2.fillConvexPoly(frame, segment, color, lineType=cv2.LINE_AA)

    outline = polygon.astype(np.int32)
    cv2.polylines(frame, [outline], isClosed=True, color=(255, 255, 255, 72), thickness=2, lineType=cv2.LINE_AA)
    return frame


def _write_overlay_png(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Failed to write overlay frame: {path}")


def build_path_overlay_frames(
    messages_by_segment: list[list[object]],
    *,
    start_seconds: int,
    length_seconds: int,
    frame_width: int,
    frame_height: int,
) -> dict[int, PathOverlayFrame]:
    _, wide_refs_by_timestamp = build_camera_frame_refs(
        messages_by_segment,
        encode_service=WIDE_CAMERA_SERVICE,
        required=True,
    )
    wide_refs_by_frame_id, _ = build_camera_frame_refs(
        messages_by_segment,
        encode_service=WIDE_CAMERA_SERVICE,
        required=True,
    )
    ordered_messages = [msg for segment in messages_by_segment for msg in segment]
    state = seed_context_state(ordered_messages)

    overlays: dict[int, PathOverlayFrame] = {}
    saw_model = False
    saw_context = _message_has_context(state)
    for msg in ordered_messages:
        which = msg.which()
        state[which] = msg
        if which in CONTEXT_SERVICES and _message_has_context(state):
            saw_context = True
        if which != MODEL_SERVICE:
            continue

        saw_model = True
        if not _message_has_context(state):
            continue
        model = getattr(msg, MODEL_SERVICE)
        wide_ref: CameraFrameRef | None = _match_camera_ref(model, wide_refs_by_frame_id, wide_refs_by_timestamp)
        if wide_ref is None:
            continue

        route_seconds = wide_ref.route_frame_id / FRAMERATE
        if route_seconds < start_seconds or route_seconds >= start_seconds + length_seconds:
            continue

        raw_points = np.array([model.position.x, model.position.y, model.position.z], dtype=np.float32).T
        projection_matrix = wide_camera_projection_matrix(state)
        polygon = project_path_polygon(
            raw_points,
            projection_matrix,
            frame_width=frame_width,
            frame_height=frame_height,
            z_offset=_path_height_meters(state),
        )
        if polygon.size == 0:
            continue

        frame_index = int(round((route_seconds - start_seconds) * FRAMERATE))
        if 0 <= frame_index < length_seconds * FRAMERATE:
            overlays[frame_index] = PathOverlayFrame(frame_index=frame_index, route_seconds=route_seconds, polygon=polygon)

    if not saw_model:
        raise RuntimeError("No modelV2 messages found; cannot render path overlay")
    if not saw_context:
        raise RuntimeError("Missing liveCalibration, roadCameraState, or deviceState; cannot render path overlay")
    if not overlays:
        raise RuntimeError("No renderable path overlays were produced for the requested window")
    return overlays


def build_openpilot_ui_overlay_steps(
    messages_by_segment: list[list[object]],
    *,
    start_seconds: int,
    length_seconds: int,
) -> dict[int, RenderStep]:
    wide_refs_by_frame_id, wide_refs_by_timestamp = build_camera_frame_refs(
        messages_by_segment,
        encode_service=WIDE_CAMERA_SERVICE,
        required=True,
    )
    ordered_messages = [msg for segment in messages_by_segment for msg in segment]
    state: dict[str, object] = seed_future_backfill_state(ordered_messages)

    steps: dict[int, RenderStep] = {}
    saw_model = False
    saw_context = _message_has_context(state)
    for msg in ordered_messages:
        which = msg.which()
        state[which] = msg
        if which in CONTEXT_SERVICES and _message_has_context(state):
            saw_context = True
        if which != MODEL_SERVICE:
            continue

        saw_model = True
        if not _message_has_context(state):
            continue

        model = getattr(msg, MODEL_SERVICE)
        wide_ref: CameraFrameRef | None = _match_camera_ref(model, wide_refs_by_frame_id, wide_refs_by_timestamp)
        if wide_ref is None:
            continue

        route_seconds = wide_ref.route_frame_id / FRAMERATE
        if route_seconds < start_seconds or route_seconds >= start_seconds + length_seconds:
            continue

        frame_index = int(round((route_seconds - start_seconds) * FRAMERATE))
        if 0 <= frame_index < length_seconds * FRAMERATE:
            steps[frame_index] = RenderStep(
                route_seconds=route_seconds,
                route_frame_id=int(getattr(model, "frameId", wide_ref.route_frame_id)),
                camera_ref=wide_ref,
                wide_camera_ref=wide_ref,
                state=dict(state),
            )

    if not saw_model:
        raise RuntimeError("No modelV2 messages found; cannot render openpilot UI overlay")
    if not saw_context:
        raise RuntimeError("Missing liveCalibration, roadCameraState, or deviceState; cannot render openpilot UI overlay")
    if not steps:
        raise RuntimeError("No renderable openpilot UI overlay steps were produced for the requested window")
    return steps


def generate_overlay_png_sequence(
    output_dir: str | Path,
    overlays: Mapping[int, PathOverlayFrame],
    *,
    frame_width: int,
    frame_height: int,
    frame_count: int,
    reuse_frames: int = DEFAULT_REUSE_FRAMES,
) -> OverlayGenerationResult:
    output_path = Path(output_dir)
    last_overlay: PathOverlayFrame | None = None
    last_overlay_idx = -10**9
    rendered_count = 0
    reused_count = 0

    for frame_index in range(frame_count):
        overlay = overlays.get(frame_index)
        if overlay is not None:
            last_overlay = overlay
            last_overlay_idx = frame_index
            rendered_count += 1
        elif last_overlay is not None and frame_index - last_overlay_idx <= reuse_frames:
            overlay = last_overlay
            reused_count += 1

        frame = (
            render_path_overlay_frame(frame_width, frame_height, overlay.polygon)
            if overlay is not None
            else np.zeros((frame_height, frame_width, 4), dtype=np.uint8)
        )
        _write_overlay_png(output_path / f"overlay-{frame_index:05d}.png", frame)

    return OverlayGenerationResult(
        pattern=str((output_path / "overlay-%05d.png").resolve()),
        frame_count=frame_count,
        rendered_count=rendered_count,
        reused_count=reused_count,
    )


def _write_blank_overlay_png(path: Path, *, frame_width: int, frame_height: int) -> None:
    _write_overlay_png(path, np.zeros((frame_height, frame_width, 4), dtype=np.uint8))


def _apply_ui_overlay_state(ui_state, state: Mapping[str, object], *, frame_index: int) -> None:
    import time

    sm = ui_state.sm
    now = time.monotonic()
    sm.updated = dict.fromkeys(sm.services, False)
    for service, msg in state.items():
        if service not in sm.data or not hasattr(msg, "as_builder"):
            continue
        sm.seen[service] = True
        sm.updated[service] = True
        sm.alive[service] = True
        sm.valid[service] = True
        sm.data[service] = getattr(msg.as_builder(), service)
        sm.logMonoTime[service] = getattr(msg, "logMonoTime", 0)
        sm.recv_time[service] = now
        sm.recv_frame[service] = frame_index
    sm.frame = frame_index + 1

    # The prototype bypasses SubMaster.update so we apply the small piece of UIState
    # lifecycle needed for HUD speed, border color, and onroad renderer gates.
    ui_state.started_frame = 0
    ui_state.started_time = ui_state.started_time or now
    ui_state._update_state()
    if not ui_state.started and getattr(sm["deviceState"], "started", False):
        ui_state.started = True
    ui_state._update_status()


def _silence_raylib_logging(rl) -> None:
    @rl.ffi.callback("void(int, char *, void *)")
    def _noop_trace_log_callback(log_level, text, args):
        return None

    rl._clipper_noop_trace_log_callback = _noop_trace_log_callback
    rl.set_trace_log_callback(_noop_trace_log_callback)


def _init_gui_window_without_atexit_close(gui_app, *, title: str, fps: int) -> None:
    import atexit

    original_register = atexit.register

    def _register_except_gui_close(func, *args, **kwargs):
        if getattr(func, "__self__", None) is gui_app and getattr(func, "__name__", "") == "close":
            return func
        return original_register(func, *args, **kwargs)

    atexit.register = _register_except_gui_close
    try:
        gui_app.init_window(title, fps=fps)
    finally:
        atexit.register = original_register


def _intersect_rect(a: FloatRect, b: FloatRect) -> FloatRect | None:
    x0 = max(a.x, b.x)
    y0 = max(a.y, b.y)
    x1 = min(a.x + a.width, b.x + b.width)
    y1 = min(a.y + a.height, b.y + b.height)
    if x1 <= x0 or y1 <= y0:
        return None
    return FloatRect(x0, y0, x1 - x0, y1 - y0)


def compute_ui_camera_source_crop(
    *,
    frame_width: int,
    frame_height: int,
    content_rect: FloatRect,
    camera_transform: np.ndarray,
) -> FloatRect:
    scale_x = content_rect.width * float(camera_transform[0, 0])
    scale_y = content_rect.height * float(camera_transform[1, 1])
    if abs(scale_x) < 1e-6 or abs(scale_y) < 1e-6:
        raise RuntimeError("Invalid UI camera transform; cannot compute source crop")

    dst_rect = FloatRect(
        x=content_rect.x + (content_rect.width - scale_x) / 2.0 + (float(camera_transform[0, 2]) * content_rect.width / 2.0),
        y=content_rect.y + (content_rect.height - scale_y) / 2.0 + (float(camera_transform[1, 2]) * content_rect.height / 2.0),
        width=scale_x,
        height=scale_y,
    )
    visible_rect = _intersect_rect(content_rect, dst_rect)
    if visible_rect is None:
        raise RuntimeError("UI camera crop does not intersect the content rect")

    src_x0 = (visible_rect.x - dst_rect.x) * frame_width / dst_rect.width
    src_y0 = (visible_rect.y - dst_rect.y) * frame_height / dst_rect.height
    src_x1 = (visible_rect.x + visible_rect.width - dst_rect.x) * frame_width / dst_rect.width
    src_y1 = (visible_rect.y + visible_rect.height - dst_rect.y) * frame_height / dst_rect.height

    x0 = max(0.0, min(float(frame_width), src_x0))
    y0 = max(0.0, min(float(frame_height), src_y0))
    x1 = max(0.0, min(float(frame_width), src_x1))
    y1 = max(0.0, min(float(frame_height), src_y1))
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError("UI camera source crop is outside the wide frame")
    return FloatRect(x0, y0, x1 - x0, y1 - y0)


def compute_ui_panel_footprint(
    *,
    panel_width: int,
    panel_height: int,
    content_rect: FloatRect,
    source_crop: FloatRect,
) -> FloatRect:
    if content_rect.width <= 0 or content_rect.height <= 0:
        raise RuntimeError("Invalid UI content rect; cannot compute panel footprint")
    scale_x = source_crop.width / content_rect.width
    scale_y = source_crop.height / content_rect.height
    return FloatRect(
        x=source_crop.x - (content_rect.x * scale_x),
        y=source_crop.y - (content_rect.y * scale_y),
        width=panel_width * scale_x,
        height=panel_height * scale_y,
    )


def _raylib_image_to_bgra(rl, image) -> np.ndarray:
    data_size = image.width * image.height * 4
    rgba = np.frombuffer(bytes(rl.ffi.buffer(image.data, data_size)), dtype=np.uint8)
    rgba = rgba.reshape((image.height, image.width, 4))
    return rgba[:, :, [2, 1, 0, 3]].copy()


def _place_panel_on_wide_frame(panel_bgra: np.ndarray, *, frame_width: int, frame_height: int, footprint: FloatRect) -> np.ndarray:
    frame = np.zeros((frame_height, frame_width, 4), dtype=np.uint8)
    scaled_width = max(1, int(round(footprint.width)))
    scaled_height = max(1, int(round(footprint.height)))
    interpolation = cv2.INTER_AREA if scaled_width < panel_bgra.shape[1] or scaled_height < panel_bgra.shape[0] else cv2.INTER_LINEAR
    scaled_panel = cv2.resize(panel_bgra, (scaled_width, scaled_height), interpolation=interpolation)

    dst_x0 = int(round(footprint.x))
    dst_y0 = int(round(footprint.y))
    dst_x1 = dst_x0 + scaled_width
    dst_y1 = dst_y0 + scaled_height

    frame_x0 = max(0, dst_x0)
    frame_y0 = max(0, dst_y0)
    frame_x1 = min(frame_width, dst_x1)
    frame_y1 = min(frame_height, dst_y1)
    if frame_x1 <= frame_x0 or frame_y1 <= frame_y0:
        return frame

    src_x0 = frame_x0 - dst_x0
    src_y0 = frame_y0 - dst_y0
    src_x1 = src_x0 + (frame_x1 - frame_x0)
    src_y1 = src_y0 + (frame_y1 - frame_y0)
    frame[frame_y0:frame_y1, frame_x0:frame_x1] = scaled_panel[src_y0:src_y1, src_x0:src_x1]
    return frame


def _render_openpilot_ui_overlay_png(
    path: Path,
    step: RenderStep,
    *,
    frame_index: int,
    frame_width: int,
    frame_height: int,
    ui_state,
    view,
    rl,
) -> None:
    from openpilot.selfdrive.ui import UI_BORDER_SIZE

    _apply_ui_overlay_state(ui_state, step.state, frame_index=frame_index)

    panel_rect = rl.Rectangle(0, 0, frame_width, frame_height)
    content_rect = rl.Rectangle(
        UI_BORDER_SIZE,
        UI_BORDER_SIZE,
        frame_width - (2 * UI_BORDER_SIZE),
        frame_height - (2 * UI_BORDER_SIZE),
    )
    content_float = FloatRect(content_rect.x, content_rect.y, content_rect.width, content_rect.height)
    view._content_rect = content_rect
    view._update_calibration()
    camera_transform = view._calc_frame_matrix(content_rect)
    source_crop = compute_ui_camera_source_crop(
        frame_width=frame_width,
        frame_height=frame_height,
        content_rect=content_float,
        camera_transform=camera_transform,
    )
    panel_footprint = compute_ui_panel_footprint(
        panel_width=frame_width,
        panel_height=frame_height,
        content_rect=content_float,
        source_crop=source_crop,
    )

    render_texture = rl.load_render_texture(frame_width, frame_height)
    try:
        rl.begin_texture_mode(render_texture)
        rl.clear_background(rl.BLANK)
        rl.begin_scissor_mode(
            int(content_rect.x),
            int(content_rect.y),
            int(content_rect.width),
            int(content_rect.height),
        )
        view.model_renderer.render(content_rect)
        view._hud_renderer.render(content_rect)
        view.alert_renderer.render(content_rect)
        rl.end_scissor_mode()
        view._draw_border(panel_rect)
        rl.end_texture_mode()

        image = rl.load_image_from_texture(render_texture.texture)
        try:
            rl.image_flip_vertical(image)
            panel_bgra = _raylib_image_to_bgra(rl, image)
            _write_overlay_png(
                path,
                _place_panel_on_wide_frame(
                    panel_bgra,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    footprint=panel_footprint,
                ),
            )
        finally:
            rl.unload_image(image)
    finally:
        rl.unload_render_texture(render_texture)


def generate_openpilot_ui_overlay_png_sequence(
    output_dir: str | Path,
    steps: Mapping[int, RenderStep],
    *,
    frame_width: int,
    frame_height: int,
    frame_count: int,
    reuse_frames: int = DEFAULT_REUSE_FRAMES,
) -> OverlayGenerationResult:
    import pyray as rl
    from msgq.visionipc import VisionStreamType
    from openpilot.common.prefix import OpenpilotPrefix
    from openpilot.selfdrive.ui.onroad.augmented_road_view import AugmentedRoadView
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.system.ui.lib.application import gui_app

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for existing in output_path.glob("overlay-*.png"):
        existing.unlink()

    timeline: list[RenderStep | None] = []
    last_step: RenderStep | None = None
    last_step_idx = -10**9
    rendered_count = 0
    reused_count = 0
    for frame_index in range(frame_count):
        step = steps.get(frame_index)
        if step is not None:
            last_step = step
            last_step_idx = frame_index
            rendered_count += 1
        elif last_step is not None and frame_index - last_step_idx <= reuse_frames:
            step = last_step
            reused_count += 1
        timeline.append(step)

    patch_shader_polygon_gradient_coordinates()
    _patch_pyray_headless_window_flags(headless=True)
    with OpenpilotPrefix(shared_download_cache=True):
        _configure_gui_app_canvas(gui_app, width=frame_width, height=frame_height)
        _init_gui_window_without_atexit_close(gui_app, title="360 openpilot UI overlay prototype", fps=FRAMERATE)
        _silence_raylib_logging(rl)
        _reapply_hidden_window_flag(headless=True)
        view = AugmentedRoadView(stream_type=VisionStreamType.VISION_STREAM_WIDE_ROAD)
        view._switch_stream_if_needed = lambda sm: None
        view._pm.send = lambda *args, **kwargs: None
        view.set_rect(rl.Rectangle(0, 0, frame_width, frame_height))
        try:
            for frame_index, step in enumerate(timeline):
                frame_path = output_path / f"overlay-{frame_index:05d}.png"
                if step is None:
                    _write_blank_overlay_png(frame_path, frame_width=frame_width, frame_height=frame_height)
                    continue
                _render_openpilot_ui_overlay_png(
                    frame_path,
                    step,
                    frame_index=frame_index,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    ui_state=ui_state,
                    view=view,
                    rl=rl,
                )
        finally:
            _silence_raylib_logging(rl)
            view.close()
            gui_app.close()

    return OverlayGenerationResult(
        pattern=str((output_path / "overlay-%05d.png").resolve()),
        frame_count=frame_count,
        rendered_count=rendered_count,
        reused_count=reused_count,
    )


def build_360_path_filter_complex(*, start_seconds: int, length_seconds: int, wide_height: int) -> str:
    start_offset = start_seconds % 60
    return (
        f"[0:v]trim=start={start_offset}:duration={length_seconds},setpts=PTS-STARTPTS,"
        f"pad=iw:ih+290:0:290:color=#160000,crop=iw:{wide_height}[driver];"
        f"[1:v]trim=start={start_offset}:duration={length_seconds},setpts=PTS-STARTPTS[wide];"
        "[2:v]format=rgba,setpts=PTS-STARTPTS[path];"
        "[wide][path]overlay=0:0:format=auto[wide_path];"
        "[driver][wide_path]hstack=inputs=2[v];"
        "[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]"
    )


def build_360_path_ffmpeg_command(
    *,
    driver_input: str,
    wide_input: str,
    overlay_pattern: str,
    filter_complex: str,
    accel: VideoAcceleration,
    target_mb: int,
    length_seconds: int,
    output_path: str,
) -> list[str]:
    target_bps = target_mb * 8 * 1024 * 1024 // length_seconds
    return [
        "ffmpeg",
        "-y",
        *accel.decoder_args,
        "-probesize",
        "100M",
        "-r",
        str(FRAMERATE),
        "-i",
        driver_input,
        *accel.decoder_args,
        "-probesize",
        "100M",
        "-r",
        str(FRAMERATE),
        "-i",
        wide_input,
        "-framerate",
        str(FRAMERATE),
        "-i",
        overlay_pattern,
        "-t",
        str(length_seconds),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        *_encoder_output_args(accel, target_bps, output_path),
    ]


def run_logged(command: list[str]) -> None:
    print(f"+ {' '.join(command)}")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        print(line.rstrip())
    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)
