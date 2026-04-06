from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import os
import sys
import time
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from renderers.big_ui_engine import (
    FRAMERATE,
    CameraFrameRef,
    IndexedFrameQueue,
    RenderStep,
    UI_ALT_FOOTER_CTA_URL_DISPLAY,
    _configure_gui_app_canvas,
    _add_openpilot_to_sys_path,
    _reapply_hidden_window_flag,
    build_camera_frame_refs,
    draw_model_input_overlay,
    draw_text_box,
    emit_runtime_log,
    format_route_timer_text,
    load_route_metadata,
    load_segment_messages,
    patch_submaster,
    render_overlays,
    setup_env,
)
from renderers.styled_text import StyledTextFonts, StyledTextPaint, StyledTextRun, StyledTextState, draw_styled_text_line, measure_styled_text_line, parse_inline_text


logger = logging.getLogger("driver_debug_engine")
DRIVER_CAMERA_SERVICE = "driverEncodeIdx"
DRIVER_CAMERA_STATE_SERVICE = "driverCameraState"
DRIVER_DEBUG_WIDTH = 1920
DRIVER_DEBUG_VIDEO_HEIGHT = 1080
DRIVER_DEBUG_FOOTER_HEIGHT = 640
DRIVER_DEBUG_HEIGHT = DRIVER_DEBUG_VIDEO_HEIGHT + DRIVER_DEBUG_FOOTER_HEIGHT
DRIVER_DEBUG_CTA_HEIGHT = 70
DRIVER_DEBUG_CTA_PAD_Y = 10.0
DRIVER_DEBUG_BOTTOM_SAFE_PAD = 76
DRIVER_DEBUG_CTA_LINE = "Make your own `driver-debug` clips with"
DM_INPUT_SIZE = (1440.0, 960.0)
AR_OX_DRIVER_FRAME = (1928.0, 1208.0)
OS_DRIVER_FRAME = (1344.0, 760.0)
AR_OX_DRIVER_FOCAL = 567.0
OS_DRIVER_FOCAL = AR_OX_DRIVER_FOCAL * 0.75
DM_INTRINSIC_CX = DM_INPUT_SIZE[0] / 2.0
DM_INTRINSIC_CY = (DM_INPUT_SIZE[1] / 2.0) - ((AR_OX_DRIVER_FRAME[1] - DM_INPUT_SIZE[1]) / 2.0)


@dataclass(frozen=True)
class DriverDebugTelemetry:
    alert_name: str | None = None
    face_detected: bool = False
    is_distracted: bool = False
    distracted_type: int = 0
    awareness_status: float | None = None
    awareness_active: float | None = None
    awareness_passive: float | None = None
    step_change: float | None = None
    hi_std_count: int = 0
    uncertain_count: int = 0
    is_low_std: bool = False
    is_active_mode: bool = False
    is_rhd: bool = False
    wheel_on_right_prob: float | None = None
    selected_side: str = "left"
    other_side: str = "right"
    face_prob: float | None = None
    other_face_prob: float | None = None
    left_eye_prob: float | None = None
    right_eye_prob: float | None = None
    left_blink_prob: float | None = None
    right_blink_prob: float | None = None
    sunglasses_prob: float | None = None
    phone_prob: float | None = None
    face_orientation: tuple[float | None, float | None, float | None] = (None, None, None)
    face_position: tuple[float | None, float | None] = (None, None)
    face_orientation_std: tuple[float | None, float | None, float | None] = (None, None, None)
    face_position_std: tuple[float | None, float | None] = (None, None)
    pitch_offset: float | None = None
    pitch_valid_count: int = 0
    yaw_offset: float | None = None
    yaw_valid_count: int = 0
    model_execution_time: float | None = None
    gpu_execution_time: float | None = None
    engaged: bool = False
    steering_pressed: bool = False
    gas_pressed: bool = False
    standstill: bool = False
    v_ego: float | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repo-owned driver debug clip renderer")
    parser.add_argument("route", help="Route ID as dongle/route")
    parser.add_argument("--openpilot-dir", required=True, help="Path to the openpilot checkout")
    parser.add_argument("-s", "--start", type=int, required=True, help="Start time in seconds")
    parser.add_argument("-e", "--end", type=int, required=True, help="End time in seconds")
    parser.add_argument("-o", "--output", required=True, help="Output file path")
    parser.add_argument("-d", "--data-dir", help="Local directory with route data")
    parser.add_argument("--backing-video", help="Optional pre-rendered driver backing video to feed into the driver camera view")
    parser.add_argument("-t", "--title", help="Title overlay text")
    parser.add_argument("-f", "--file-size", type=float, default=9.0, help="Target file size in MB")
    parser.add_argument("--windowed", action="store_true", help="Show window")
    parser.add_argument("--no-metadata", action="store_true", help="Disable metadata overlay")
    parser.add_argument("--no-time-overlay", action="store_true", help="Disable time overlay")
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error(f"end ({args.end}) must be greater than start ({args.start})")
    return args


def _normalize_cli_paths(args: argparse.Namespace, *, cwd: Path) -> argparse.Namespace:
    normalized = argparse.Namespace(**vars(args))
    normalized.openpilot_dir = str((cwd / normalized.openpilot_dir).resolve()) if not Path(normalized.openpilot_dir).is_absolute() else str(Path(normalized.openpilot_dir).resolve())
    normalized.output = str((cwd / normalized.output).resolve()) if not Path(normalized.output).is_absolute() else str(Path(normalized.output).resolve())
    if normalized.data_dir:
        data_dir_path = Path(normalized.data_dir)
        normalized.data_dir = str((cwd / data_dir_path).resolve()) if not data_dir_path.is_absolute() else str(data_dir_path.resolve())
    if getattr(normalized, "backing_video", None):
        backing_video_path = Path(normalized.backing_video)
        normalized.backing_video = (
            str((cwd / backing_video_path).resolve()) if not backing_video_path.is_absolute() else str(backing_video_path.resolve())
        )
    return normalized


def _bgr_frame_to_nv12_bytes(frame) -> bytes:
    import cv2
    import numpy as np

    frame_height, frame_width = frame.shape[:2]
    if frame_width % 2 or frame_height % 2:
        raise ValueError(f"Backing video frame must be even-sized for NV12 conversion. Got {frame_width}x{frame_height}")
    yuv_i420 = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420).reshape(-1)
    y_plane_size = frame_width * frame_height
    uv_plane_size = y_plane_size // 4
    y_plane = yuv_i420[:y_plane_size]
    u_plane = yuv_i420[y_plane_size:y_plane_size + uv_plane_size].reshape(frame_height // 2, frame_width // 2)
    v_plane = yuv_i420[y_plane_size + uv_plane_size:y_plane_size + (uv_plane_size * 2)].reshape(
        frame_height // 2, frame_width // 2
    )
    uv_plane = np.empty((frame_height // 2, frame_width), dtype=np.uint8)
    uv_plane[:, 0::2] = u_plane
    uv_plane[:, 1::2] = v_plane
    return y_plane.tobytes() + uv_plane.tobytes()


class DecodedBackingVideoFrameSource:
    def __init__(self, video_path: Path) -> None:
        import cv2

        self.video_path = video_path
        self._capture = cv2.VideoCapture(str(video_path))
        if not self._capture.isOpened():
            raise RuntimeError(f"Failed to open backing video: {video_path}")
        self.frame_w = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.frame_h = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self._frame_count = int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def get(self, camera_ref: CameraFrameRef) -> tuple[CameraFrameRef, bytes]:
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"Backing video ended before render completed: {self.video_path}")
        return camera_ref, _bgr_frame_to_nv12_bytes(frame)

    def stop(self) -> None:
        self._capture.release()


def _match_driver_camera_ref(
    camera_state: object,
    refs_by_frame_id: dict[int, CameraFrameRef],
    refs_by_timestamp: dict[int, CameraFrameRef],
) -> CameraFrameRef | None:
    frame_id = getattr(camera_state, "frameId", None)
    if frame_id is not None:
        match = refs_by_frame_id.get(int(frame_id))
        if match is not None:
            return match
    timestamp_eof = getattr(camera_state, "timestampEof", None)
    if timestamp_eof is not None:
        return refs_by_timestamp.get(int(timestamp_eof))
    return None


def build_driver_render_steps(messages_by_segment: list[list], *, start: int, end: int) -> list[RenderStep]:
    refs_by_frame_id, refs_by_timestamp = build_camera_frame_refs(
        messages_by_segment,
        encode_service=DRIVER_CAMERA_SERVICE,
    )
    ordered_messages = [msg for segment in messages_by_segment for msg in segment]

    current_state: dict = {}
    render_steps: list[RenderStep] = []
    for msg in ordered_messages:
        which = msg.which()
        current_state[which] = msg

        if which != DRIVER_CAMERA_STATE_SERVICE:
            continue

        camera_state = msg.driverCameraState
        camera_ref = _match_driver_camera_ref(camera_state, refs_by_frame_id, refs_by_timestamp)
        if camera_ref is None:
            logger.warning("Skipping driver frame because no matching driver encode frame was found")
            continue

        route_seconds = camera_ref.route_frame_id / FRAMERATE
        if route_seconds < start or route_seconds >= end:
            continue

        render_steps.append(
            RenderStep(
                route_seconds=route_seconds,
                route_frame_id=int(camera_ref.route_frame_id),
                camera_ref=camera_ref,
                wide_camera_ref=None,
                state=dict(current_state),
            )
        )

    if not render_steps:
        raise RuntimeError("No driver render steps were built for the requested time window")
    return render_steps


def _as_tuple(value: object, *, length: int) -> tuple[float | None, ...]:
    if value is None:
        return tuple(None for _ in range(length))
    try:
        seq = list(value)
    except TypeError:
        return tuple(None for _ in range(length))
    padded = [float(item) for item in seq[:length]]
    while len(padded) < length:
        padded.append(None)
    return tuple(padded)


def _select_driver_sides(
    *,
    dm_state,
    driver_state,
) -> tuple[object | None, object | None, bool, float | None, str, str]:
    is_rhd = bool(getattr(dm_state, "isRHD", False))
    wheel_on_right_prob = getattr(driver_state, "wheelOnRightProb", None)
    if dm_state is None and wheel_on_right_prob is not None:
        is_rhd = float(wheel_on_right_prob) > 0.5

    left_driver = getattr(driver_state, "leftDriverData", None) if driver_state is not None else None
    right_driver = getattr(driver_state, "rightDriverData", None) if driver_state is not None else None
    if is_rhd:
        return (
            right_driver,
            left_driver,
            is_rhd,
            float(wheel_on_right_prob) if wheel_on_right_prob is not None else None,
            "right",
            "left",
        )
    return (
        left_driver,
        right_driver,
        is_rhd,
        float(wheel_on_right_prob) if wheel_on_right_prob is not None else None,
        "left",
        "right",
    )


def extract_driver_debug_telemetry(state: dict[str, object]) -> DriverDebugTelemetry:
    dm_state_msg = state.get("driverMonitoringState")
    driver_state_msg = state.get("driverStateV2")
    car_state_msg = state.get("carState")
    selfdrive_state_msg = state.get("selfdriveState")

    dm_state = getattr(dm_state_msg, "driverMonitoringState", None) if dm_state_msg is not None else None
    driver_state = getattr(driver_state_msg, "driverStateV2", None) if driver_state_msg is not None else None
    car_state = getattr(car_state_msg, "carState", None) if car_state_msg is not None else None
    selfdrive_state = getattr(selfdrive_state_msg, "selfdriveState", None) if selfdrive_state_msg is not None else None

    driver_data, other_driver_data, is_rhd, wheel_on_right_prob, selected_side, other_side = _select_driver_sides(
        dm_state=dm_state,
        driver_state=driver_state,
    )

    events = list(getattr(dm_state, "events", []) or [])
    alert_name = None
    if events:
        alert_name = str(getattr(events[0], "name", "")).split(".")[-1] or None

    return DriverDebugTelemetry(
        alert_name=alert_name,
        face_detected=bool(getattr(dm_state, "faceDetected", False)),
        is_distracted=bool(getattr(dm_state, "isDistracted", False)),
        distracted_type=int(getattr(dm_state, "distractedType", 0) or 0),
        awareness_status=float(getattr(dm_state, "awarenessStatus", 0.0)) if dm_state is not None else None,
        awareness_active=float(getattr(dm_state, "awarenessActive", 0.0)) if dm_state is not None else None,
        awareness_passive=float(getattr(dm_state, "awarenessPassive", 0.0)) if dm_state is not None else None,
        step_change=float(getattr(dm_state, "stepChange", 0.0)) if dm_state is not None else None,
        hi_std_count=int(getattr(dm_state, "hiStdCount", 0) or 0),
        uncertain_count=int(getattr(dm_state, "uncertainCount", 0) or 0),
        is_low_std=bool(getattr(dm_state, "isLowStd", False)),
        is_active_mode=bool(getattr(dm_state, "isActiveMode", False)),
        is_rhd=is_rhd,
        wheel_on_right_prob=wheel_on_right_prob,
        selected_side=selected_side,
        other_side=other_side,
        face_prob=float(getattr(driver_data, "faceProb", 0.0)) if driver_data is not None else None,
        other_face_prob=float(getattr(other_driver_data, "faceProb", 0.0)) if other_driver_data is not None else None,
        left_eye_prob=float(getattr(driver_data, "leftEyeProb", 0.0)) if driver_data is not None else None,
        right_eye_prob=float(getattr(driver_data, "rightEyeProb", 0.0)) if driver_data is not None else None,
        left_blink_prob=float(getattr(driver_data, "leftBlinkProb", 0.0)) if driver_data is not None else None,
        right_blink_prob=float(getattr(driver_data, "rightBlinkProb", 0.0)) if driver_data is not None else None,
        sunglasses_prob=float(getattr(driver_data, "sunglassesProb", 0.0)) if driver_data is not None else None,
        phone_prob=float(getattr(driver_data, "phoneProb", 0.0)) if driver_data is not None else None,
        face_orientation=_as_tuple(getattr(driver_data, "faceOrientation", None), length=3),
        face_position=_as_tuple(getattr(driver_data, "facePosition", None), length=2),
        face_orientation_std=_as_tuple(getattr(driver_data, "faceOrientationStd", None), length=3),
        face_position_std=_as_tuple(getattr(driver_data, "facePositionStd", None), length=2),
        pitch_offset=float(getattr(dm_state, "posePitchOffset", 0.0)) if dm_state is not None else None,
        pitch_valid_count=int(getattr(dm_state, "posePitchValidCount", 0) or 0),
        yaw_offset=float(getattr(dm_state, "poseYawOffset", 0.0)) if dm_state is not None else None,
        yaw_valid_count=int(getattr(dm_state, "poseYawValidCount", 0) or 0),
        model_execution_time=float(getattr(driver_state, "modelExecutionTime", 0.0)) if driver_state is not None else None,
        gpu_execution_time=float(getattr(driver_state, "gpuExecutionTime", 0.0)) if driver_state is not None else None,
        engaged=bool(getattr(selfdrive_state, "enabled", False)),
        steering_pressed=bool(getattr(car_state, "steeringPressed", False)),
        gas_pressed=bool(getattr(car_state, "gasPressed", False)),
        standstill=bool(getattr(car_state, "standstill", False)),
        v_ego=float(getattr(car_state, "vEgo", 0.0)) if car_state is not None else None,
    )


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value * 100:.0f}%"


def _fmt_float(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}{suffix}"


def _fmt_vec(values: tuple[float | None, ...], digits: int = 2) -> str:
    parts = []
    for value in values:
        if value is None:
            parts.append("--")
        else:
            parts.append(f"{value:.{digits}f}")
    return ", ".join(parts)


def _humanize_platform(value: str | None) -> str:
    if not value:
        return "unknown"
    text = str(value).strip()
    if not text:
        return "unknown"
    return text


def _humanize_git_remote(value: str | None) -> str:
    if not value:
        return "unknown"
    text = str(value).strip()
    if not text:
        return "unknown"
    if text.endswith(".git"):
        text = text[:-4]
    if text.startswith("git@") and ":" in text:
        text = text.split(":", 1)[1]
    elif "github.com/" in text:
        text = text.split("github.com/", 1)[1]
    return text.rsplit("/", 2)[-2] + "/" + text.rsplit("/", 1)[-1] if "/" in text else text


def _git_metadata_text(metadata: dict[str, str] | None) -> str:
    if not metadata:
        return ""
    remote = _humanize_git_remote(metadata.get("remote", ""))
    branch = str(metadata.get("branch", "") or "unknown")
    commit = str(metadata.get("commit", "") or "unknown")
    dirty = str(metadata.get("dirty", "") or "unknown")
    return f"{remote}  •  {branch}  •  {commit}  •  dirty {dirty}"


def _driver_face_anchor(rect, *, face_x: float, face_y: float, device_type: str) -> tuple[float, float]:
    # The DM pose output is not in raw displayed-pixel coordinates.
    # Openpilot's UI uses an approximate back-projection for the driver box;
    # keep that shape here and adapt it to our unmirrored raw-like view.
    base_x = 1080.0 - (1714.0 * face_x)
    base_y = -135.0 + (504.0 + abs(face_x) * 112.0) + (1205.0 - abs(face_x) * 724.0) * face_y
    normalized = (device_type or "").strip().lower()

    if normalized == "mici":
        offset_x = (base_x - 1080.0) * 1.25
        offset_y = (base_y - 540.0) * 1.25
        scale_x = rect.width / 2160.0
        scale_y = rect.height / 1080.0
        anchor_x = rect.x + (rect.width / 2) + (offset_x * scale_x)
        anchor_y = rect.y + (rect.height / 2) + (offset_y * scale_y)
        return rect.x + rect.width - (anchor_x - rect.x), anchor_y

    scale_x = rect.width / 2160.0
    scale_y = rect.height / 1080.0
    anchor_x = rect.x + (base_x * scale_x)
    anchor_y = rect.y + (base_y * scale_y)
    return rect.x + rect.width - (anchor_x - rect.x), anchor_y


def compute_driver_monitoring_input_quad(
    rect,
    *,
    frame_width: float,
    frame_height: float,
) -> tuple[tuple[float, float], ...] | None:
    frame_width = float(frame_width or 0.0)
    frame_height = float(frame_height or 0.0)
    rect_width = float(getattr(rect, "width", 0.0) or 0.0)
    rect_height = float(getattr(rect, "height", 0.0) or 0.0)
    if frame_width <= 0.0 or frame_height <= 0.0 or rect_width <= 0.0 or rect_height <= 0.0:
        return None

    if int(round(frame_width)) == int(OS_DRIVER_FRAME[0]) and int(round(frame_height)) == int(OS_DRIVER_FRAME[1]):
        focal_length = OS_DRIVER_FOCAL
    else:
        focal_length = AR_OX_DRIVER_FOCAL

    cam_cx = frame_width / 2.0
    cam_cy = frame_height / 2.0
    scale = focal_length / AR_OX_DRIVER_FOCAL
    translate_x = cam_cx - (DM_INTRINSIC_CX * scale)
    translate_y = cam_cy - (DM_INTRINSIC_CY * scale)

    corners = (
        (0.0, 0.0),
        (DM_INPUT_SIZE[0] - 1.0, 0.0),
        (DM_INPUT_SIZE[0] - 1.0, DM_INPUT_SIZE[1] - 1.0),
        (0.0, DM_INPUT_SIZE[1] - 1.0),
    )
    projected_xy: list[tuple[float, float]] = []
    for dm_x, dm_y in corners:
        camera_x = translate_x + (scale * dm_x)
        camera_y = translate_y + (scale * dm_y)
        screen_x = rect.x + ((camera_x / frame_width) * rect_width)
        screen_y = rect.y + ((camera_y / frame_height) * rect_height)
        projected_xy.append((float(screen_x), float(screen_y)))
    return tuple(projected_xy)


def _draw_driver_monitoring_input_overlay(content_rect, *, frame_width: float, frame_height: float) -> None:
    quad = compute_driver_monitoring_input_quad(
        content_rect,
        frame_width=frame_width,
        frame_height=frame_height,
    )
    draw_model_input_overlay(quad, clip_rect=content_rect)


def compute_driver_face_box_rect(
    rect,
    *,
    driver_data,
    device_type: str,
):
    normalized_device_type = (device_type or "").strip().lower()
    face_position = list(getattr(driver_data, "facePosition", []) or [])
    face_position_std = list(getattr(driver_data, "facePositionStd", []) or [])
    face_orientation = list(getattr(driver_data, "faceOrientation", []) or [])
    face_orientation_std = list(getattr(driver_data, "faceOrientationStd", []) or [])
    if len(face_position) < 2:
        return None

    face_x = float(face_position[0])
    face_y = float(face_position[1])
    center_x, center_y = _driver_face_anchor(rect, face_x=face_x, face_y=face_y, device_type=device_type)

    pitch = float(face_orientation[0]) if len(face_orientation) > 0 else 0.0
    yaw = float(face_orientation[1]) if len(face_orientation) > 1 else 0.0
    pos_std_x = float(face_position_std[0]) if len(face_position_std) > 0 else 0.0
    pos_std_y = float(face_position_std[1]) if len(face_position_std) > 1 else 0.0
    orient_std = max((float(value) for value in face_orientation_std[:2]), default=0.0)

    # The DM model provides a coarse face anchor, not a real detected face bounds box.
    # Keep position close to the upstream anchor, but bias the center slightly in the
    # yaw direction so the box stays over the visible face instead of the ear/cheek.
    center_x += yaw * rect.width * (0.055 if normalized_device_type == "mici" else 0.045)
    center_y += pitch * rect.height * 0.04

    base_width = rect.width * (0.06 if normalized_device_type == "mici" else 0.08)
    width = (
        base_width
        + (abs(yaw) * rect.width * 0.04)
        + (pos_std_x * rect.width * 4.0)
        + (orient_std * rect.width * 0.04)
    )
    width = max(base_width * 0.95, min(width, rect.width * 0.18))
    height = (width * 1.16) + (pos_std_y * rect.height * 2.0)
    height = max(width, min(height, rect.height * 0.28))

    box_x = max(rect.x, min(center_x - (width / 2), rect.x + rect.width - width))
    box_y = max(rect.y, min(center_y - (height / 2), rect.y + rect.height - height))
    return box_x, box_y, width, height


def _driver_box_style(*, role: str):
    import pyray as rl

    if role == "other":
        return {
            "outline": rl.Color(255, 188, 92, 255),
            "fill": rl.Color(255, 188, 92, 22),
            "shadow": rl.Color(0, 0, 0, 165),
            "label": "OTHER SEAT",
        }
    return {
        "outline": rl.Color(94, 214, 135, 255),
        "fill": rl.Color(94, 214, 135, 22),
        "shadow": rl.Color(0, 0, 0, 190),
        "label": "DRIVER SEAT",
    }


def _draw_driver_debug_face_box(rect, *, driver_data, device_type: str, role: str):
    import pyray as rl

    box_values = compute_driver_face_box_rect(rect, driver_data=driver_data, device_type=device_type)
    if box_values is None:
        return None
    box = rl.Rectangle(*box_values)
    style = _driver_box_style(role=role)

    face_orientation_std = list(getattr(driver_data, "faceOrientationStd", []) or [])
    face_prob = float(getattr(driver_data, "faceProb", 0.0) or 0.0)
    face_std = max((float(value) for value in face_orientation_std[:2]), default=0.0)
    alpha = 0.88 if face_prob > 0.85 else 0.72
    if face_std > 0.15:
        alpha *= max(0.45, 1.0 - ((face_std - 0.15) * 1.6))

    outline = rl.Color(style["outline"].r, style["outline"].g, style["outline"].b, int(255 * alpha))
    shadow = rl.Color(style["shadow"].r, style["shadow"].g, style["shadow"].b, int(style["shadow"].a * alpha))
    fill = rl.Color(style["fill"].r, style["fill"].g, style["fill"].b, int(style["fill"].a * alpha))

    rl.draw_rectangle_rounded(box, 0.12, 12, fill)
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(box.x + 2, box.y + 2, box.width, box.height), 0.12, 12, 6, shadow)
    rl.draw_rectangle_rounded_lines_ex(box, 0.12, 12, 3, outline)
    return style["outline"]


class DriverDebugOverlayRenderer:
    def __init__(self, *, label_font, value_font) -> None:
        self._label_font = label_font
        self._value_font = value_font
        self._styled_fonts = StyledTextFonts(regular=value_font, bold=value_font, italic=value_font, bold_italic=value_font)

    def _draw_kv_row(
        self,
        x: float,
        y: float,
        label: str,
        value: str,
        *,
        width: float,
        value_color,
        value_size: int = 22,
        value_x: float | None = None,
    ) -> None:
        import pyray as rl

        label_size = 15
        dim = rl.Color(255, 255, 255, 145)
        rl.draw_text_ex(self._label_font, label, rl.Vector2(x, y), label_size, 0, dim)
        value_draw_x = value_x if value_x is not None else x + (width * 0.58)
        rl.draw_text_ex(
            self._value_font,
            value,
            rl.Vector2(value_draw_x, y - 1),
            value_size,
            0,
            value_color,
        )

    def _draw_badge(self, x: float, y: float, label: str, *, color) -> float:
        import pyray as rl

        font_size = 17
        padding_x = 22
        height = 42
        text_size = rl.measure_text_ex(self._label_font, label, font_size, 0)
        width = text_size.x + (padding_x * 2) + 12
        rl.draw_rectangle_rounded(rl.Rectangle(x, y, width, height), 0.35, 10, rl.Color(0, 0, 0, 135))
        rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x, y, width, height), 0.35, 10, 2, color)
        text_y = y + ((height - text_size.y) / 2) - 1
        rl.draw_text_ex(self._label_font, label, rl.Vector2(x + padding_x, text_y), font_size, 0, color)
        return width

    def _draw_badges_flow(self, x: float, y: float, max_x: float, badges: list[tuple[str, object]]) -> float:
        import pyray as rl

        cursor_x = x
        cursor_y = y
        line_height = 0.0
        gap_x = 10.0
        gap_y = 10.0

        for label, color in badges:
            font_size = 17
            padding_x = 22
            height = 42
            text_size = rl.measure_text_ex(self._label_font, label, font_size, 0)
            width = text_size.x + (padding_x * 2) + 12
            if cursor_x + width > max_x and cursor_x > x:
                cursor_x = x
                cursor_y += line_height + gap_y
                line_height = 0.0
            self._draw_badge(cursor_x, cursor_y, label, color=color)
            cursor_x += width + gap_x
            line_height = max(line_height, height)

        return cursor_y + line_height

    def _draw_section_title(self, x: float, y: float, title: str) -> None:
        import pyray as rl

        rl.draw_text_ex(self._label_font, title, rl.Vector2(x, y), 21, 0, rl.Color(255, 255, 255, 145))

    def _draw_box_legend(self, x: float, y: float, items: list[tuple[str, object]]) -> None:
        import pyray as rl

        if not items:
            return

        line_height = 24
        panel_width = 184
        panel_height = 14 + (line_height * len(items))
        panel = rl.Rectangle(x, y, panel_width, panel_height)
        rl.draw_rectangle_rounded(panel, 0.28, 10, rl.Color(3, 10, 14, 150))
        rl.draw_rectangle_rounded_lines_ex(panel, 0.28, 10, 2, rl.Color(255, 255, 255, 34))
        for idx, (label, color) in enumerate(items):
            row_y = y + 8 + (idx * line_height)
            rl.draw_rectangle_rounded(rl.Rectangle(x + 12, row_y + 5, 18, 12), 0.4, 8, color)
            rl.draw_text_ex(self._label_font, label, rl.Vector2(x + 40, row_y), 17, 0, rl.Color(255, 255, 255, 228))

    def _draw_card(self, rect, *, accent) -> None:
        import pyray as rl

        fill = rl.Color(7, 17, 25, 198)
        border = rl.Color(255, 255, 255, 28)
        glow = rl.Color(accent.r, accent.g, accent.b, 22)
        rl.draw_rectangle_rounded(rect, 0.05, 12, fill)
        rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y, rect.width, 6), 0.4, 8, glow)
        rl.draw_rectangle_rounded_lines_ex(rect, 0.05, 12, 2, border)

    def _draw_micro_stat(self, x: float, y: float, label: str, value: str, *, color) -> None:
        import pyray as rl

        rl.draw_text_ex(self._label_font, label, rl.Vector2(x, y), 14, 0, rl.Color(255, 255, 255, 120))
        rl.draw_text_ex(self._value_font, value, rl.Vector2(x, y + 18), 28, 0, color)

    def _draw_footer_cta(self, rect) -> None:
        import pyray as rl

        lead_text = DRIVER_DEBUG_CTA_LINE
        url = UI_ALT_FOOTER_CTA_URL_DISPLAY
        font_size = 28
        lead_color = rl.Color(255, 255, 255, 195)
        url_color = rl.Color(118, 210, 255, 255)
        code_fill = rl.Color(255, 255, 255, 18)
        code_border = rl.Color(255, 255, 255, 45)
        panel_fill = rl.Color(255, 255, 255, 8)
        panel_border = rl.Color(118, 210, 255, 60)

        panel_rect = rl.Rectangle(
            rect.x,
            rect.y + DRIVER_DEBUG_CTA_PAD_Y,
            rect.width,
            max(0.0, rect.height - (2 * DRIVER_DEBUG_CTA_PAD_Y)),
        )
        cta_runs = parse_inline_text(f"{lead_text} ")
        cta_runs.append(StyledTextRun(url, StyledTextState(), color=url_color))
        line_metrics = measure_styled_text_line(
            fonts=self._styled_fonts,
            text=cta_runs,
            font_size=font_size,
            spacing=0,
            code_padding_x=10.0,
            code_padding_y=4.0,
        )
        target_width = panel_rect.width - 72.0
        if line_metrics.width > target_width and line_metrics.width > 0:
            font_size = max(18, int(font_size * (target_width / line_metrics.width)))
            line_metrics = measure_styled_text_line(
                fonts=self._styled_fonts,
                text=cta_runs,
                font_size=font_size,
                spacing=0,
                code_padding_x=9.0,
                code_padding_y=4.0,
            )

        line_top_y = float(int(round(panel_rect.y + ((panel_rect.height - line_metrics.height) / 2))))
        start_x = float(int(round(panel_rect.x + max(0.0, (panel_rect.width - line_metrics.width) / 2))))

        rl.draw_rectangle_rounded(panel_rect, 0.16, 16, panel_fill)
        rl.draw_rectangle_rounded_lines_ex(panel_rect, 0.16, 16, 2, panel_border)
        draw_styled_text_line(
            fonts=self._styled_fonts,
            text=cta_runs,
            position=rl.Vector2(start_x, line_top_y),
            font_size=font_size,
            spacing=0,
            paint=StyledTextPaint(
                color=lead_color,
                code_text_color=rl.WHITE,
                code_fill_color=code_fill,
                code_border_color=code_border,
            ),
            code_padding_x=9.0,
            code_padding_y=4.0,
        )

    def _draw_right_aligned_text(
        self,
        *,
        right_x: float,
        y: float,
        text: str,
        font,
        font_size: int,
        color,
    ) -> None:
        import pyray as rl

        if not text:
            return
        text_size = rl.measure_text_ex(font, text, font_size, 0)
        rl.draw_text_ex(font, text, rl.Vector2(right_x - text_size.x, y), font_size, 0, color)

    def render(self, rect, *, telemetry: DriverDebugTelemetry, route_seconds: float, metadata: dict[str, str] | None) -> None:
        import pyray as rl

        panel_bg = rl.Color(5, 12, 18, 255)
        panel_bg_bottom = rl.Color(11, 26, 37, 255)
        white = rl.Color(255, 255, 255, 245)
        dim = rl.Color(255, 255, 255, 160)
        green = rl.Color(94, 214, 135, 255)
        orange = rl.Color(255, 176, 87, 255)
        red = rl.Color(255, 103, 103, 255)
        blue = rl.Color(125, 196, 255, 255)
        outer_pad_x = 34
        outer_pad_y = 28
        bottom_safe_pad = DRIVER_DEBUG_BOTTOM_SAFE_PAD

        rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), int(rect.height), rl.Color(0, 0, 0, 255))
        rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y), int(rect.width), int(rect.height), panel_bg, panel_bg_bottom)
        rl.draw_line(int(rect.x), int(rect.y), int(rect.x + rect.width), int(rect.y), rl.Color(255, 255, 255, 24))

        title_x = rect.x + outer_pad_x
        title_y = rect.y + outer_pad_y
        header_right_x = rect.x + rect.width - (outer_pad_x * 2)
        time_text = format_route_timer_text(route_seconds, prefix="T+")
        rl.draw_text_ex(self._label_font, "DRIVER DEBUG", rl.Vector2(title_x, title_y), 24, 0, blue)
        rl.draw_text_ex(self._value_font, time_text, rl.Vector2(title_x, title_y + 28), 34, 0, white)

        platform_text = ""
        route_label = ""
        device_label = ""
        git_text = ""
        if metadata:
            platform_text = _humanize_platform(metadata.get("platform", ""))
            route_label = metadata.get("route", "")
            device_label = str(metadata.get("device_type", "") or "").strip()
            git_text = _git_metadata_text(metadata)
        meta_text = "  •  ".join(part for part in [device_label, platform_text] if part)
        if meta_text:
            self._draw_right_aligned_text(
                right_x=header_right_x,
                y=title_y + 4,
                text=meta_text,
                font=self._value_font,
                font_size=22,
                color=white,
            )
        if route_label:
            self._draw_right_aligned_text(
                right_x=header_right_x,
                y=title_y + 34,
                text=route_label,
                font=self._label_font,
                font_size=17,
                color=dim,
            )
        if git_text:
            self._draw_right_aligned_text(
                right_x=header_right_x,
                y=title_y + 56,
                text=git_text,
                font=self._label_font,
                font_size=16,
                color=dim,
            )

        subtitle_parts = [
            f"side {telemetry.selected_side}",
            f"low std {'yes' if telemetry.is_low_std else 'no'}",
            f"engaged {'yes' if telemetry.engaged else 'no'}",
        ]
        rl.draw_text_ex(
            self._label_font,
            "  •  ".join(subtitle_parts),
            rl.Vector2(title_x, title_y + 92),
            17,
            0,
            dim,
        )

        badges = [
            (f"Mode {'Active' if telemetry.is_active_mode else 'Passive'}", green if telemetry.is_active_mode else orange),
            (f"Distracted {'Yes' if telemetry.is_distracted else 'No'}", red if telemetry.is_distracted else green),
            (f"Face {'Yes' if telemetry.face_detected else 'No'}", green if telemetry.face_detected else red),
        ]
        if telemetry.alert_name:
            badges.append((telemetry.alert_name, orange if telemetry.is_distracted else blue))
        badge_bottom = self._draw_badges_flow(title_x, title_y + 126, rect.x + rect.width - outer_pad_x, badges)

        section_top = max(title_y + 174, badge_bottom + 20)
        section_height = rect.height - (section_top - rect.y) - outer_pad_y - bottom_safe_pad
        col_gap = 36
        col_width = (rect.width - (2 * outer_pad_x) - (2 * col_gap)) / 3
        col1_x = rect.x + outer_pad_x
        col2_x = col1_x + col_width + col_gap
        col3_x = col2_x + col_width + col_gap
        card_rects = [
            rl.Rectangle(col1_x, section_top, col_width, section_height),
            rl.Rectangle(col2_x, section_top, col_width, section_height),
            rl.Rectangle(col3_x, section_top, col_width, section_height),
        ]

        self._draw_card(card_rects[0], accent=blue)
        self._draw_card(card_rects[1], accent=green)
        self._draw_card(card_rects[2], accent=orange)

        card_pad_x = 24
        card_pad_y = 22

        left_x = card_rects[0].x + card_pad_x
        left_y = card_rects[0].y + card_pad_y
        self._draw_section_title(left_x, left_y, "DM STATE")
        awareness_text = _fmt_percent(telemetry.awareness_status)
        rl.draw_text_ex(self._value_font, awareness_text, rl.Vector2(left_x, left_y + 28), 64, 0, white)
        rl.draw_text_ex(
            self._label_font,
            f"ACTIVE {_fmt_percent(telemetry.awareness_active)}   PASSIVE {_fmt_percent(telemetry.awareness_passive)}",
            rl.Vector2(left_x, left_y + 90),
            17,
            0,
            dim,
        )
        micro_y = left_y + 126
        self._draw_micro_stat(left_x, micro_y, "uncertain", str(telemetry.uncertain_count), color=orange if telemetry.uncertain_count else white)
        self._draw_micro_stat(left_x + 180, micro_y, "hi std", str(telemetry.hi_std_count), color=white)
        self._draw_micro_stat(left_x, micro_y + 60, "step", _fmt_float(telemetry.step_change, 3), color=white)
        self._draw_micro_stat(left_x + 180, micro_y + 60, "speed", _fmt_float(telemetry.v_ego, 1, " m/s"), color=white)
        status_text = f"{'ENGAGED' if telemetry.engaged else 'OFF'} / {'HANDS ON' if telemetry.steering_pressed else 'HANDS OFF'}"
        status_size = 17
        status_width = rl.measure_text_ex(self._value_font, status_text, status_size, 0).x
        rl.draw_text_ex(
            self._value_font,
            status_text,
            rl.Vector2(
                card_rects[0].x + card_rects[0].width - card_pad_x - 28 - status_width,
                card_rects[0].y + card_rects[0].height - 82,
            ),
            status_size,
            0,
            green if telemetry.engaged else dim,
        )

        mid_x = card_rects[1].x + card_pad_x
        mid_y = card_rects[1].y + card_pad_y
        mid_value_x = mid_x + 250
        self._draw_section_title(mid_x, mid_y, "MODEL")
        middle_rows = [
            (
                "sel / other / RHD",
                f"{_fmt_percent(telemetry.face_prob)} / {_fmt_percent(telemetry.other_face_prob)} / {_fmt_percent(telemetry.wheel_on_right_prob)}",
                white,
            ),
            ("eyes L / R", f"{_fmt_percent(telemetry.left_eye_prob)} / {_fmt_percent(telemetry.right_eye_prob)}", white),
            ("blink L / R", f"{_fmt_percent(telemetry.left_blink_prob)} / {_fmt_percent(telemetry.right_blink_prob)}", orange),
            ("sunglasses / phone", f"{_fmt_percent(telemetry.sunglasses_prob)} / {_fmt_percent(telemetry.phone_prob)}", white),
            ("model / gpu", f"{_fmt_float(telemetry.model_execution_time, 3, 's')} / {_fmt_float(telemetry.gpu_execution_time, 3, 's')}", white),
            ("distracted type", str(telemetry.distracted_type), red if telemetry.distracted_type else green),
        ]
        middle_rows_y = mid_y + 34
        middle_row_gap = 34
        for idx, (label, value, color) in enumerate(middle_rows):
            self._draw_kv_row(
                mid_x,
                middle_rows_y + (idx * middle_row_gap),
                label,
                value,
                width=card_rects[1].width - (2 * card_pad_x),
                value_color=color,
                value_x=mid_value_x,
            )

        right_x = card_rects[2].x + card_pad_x
        right_y = card_rects[2].y + card_pad_y
        right_value_x = right_x + 250
        self._draw_section_title(right_x, right_y, "POSE")
        right_rows = [
            ("orientation", _fmt_vec(telemetry.face_orientation), white),
            ("position", _fmt_vec(telemetry.face_position), white),
            ("orient std", _fmt_vec(telemetry.face_orientation_std), white),
            ("pos std", _fmt_vec(telemetry.face_position_std), white),
            ("pitch off / count", f"{_fmt_float(telemetry.pitch_offset, 3)} / {telemetry.pitch_valid_count}", white),
            ("yaw off / count", f"{_fmt_float(telemetry.yaw_offset, 3)} / {telemetry.yaw_valid_count}", white),
        ]
        right_rows_y = right_y + 34
        right_row_gap = 34
        for idx, (label, value, color) in enumerate(right_rows):
            self._draw_kv_row(
                right_x,
                right_rows_y + (idx * right_row_gap),
                label,
                value,
                width=card_rects[2].width - (2 * card_pad_x),
                value_color=color,
                value_x=right_value_x,
            )

        self._draw_footer_cta(
            rl.Rectangle(
                rect.x + outer_pad_x,
                rect.y + rect.height - DRIVER_DEBUG_CTA_HEIGHT,
                rect.width - (2 * outer_pad_x),
                DRIVER_DEBUG_CTA_HEIGHT,
            )
        )


def _driver_camera_dialog_module(*, device_type: str) -> str:
    normalized = (device_type or "").strip().lower()
    if normalized == "mici":
        return "openpilot.selfdrive.ui.mici.onroad.driver_camera_dialog"
    return "openpilot.selfdrive.ui.onroad.driver_camera_dialog"


def _select_driver_camera_dialog(*, device_type: str):
    module_name = _driver_camera_dialog_module(device_type=device_type)
    module = __import__(module_name, fromlist=["DriverCameraDialog"])
    return module.DriverCameraDialog


def _driver_camera_view_base_class(*, device_type: str):
    normalized = (device_type or "").strip().lower()
    module_name = (
        "openpilot.selfdrive.ui.mici.onroad.cameraview"
        if normalized == "mici"
        else "openpilot.selfdrive.ui.onroad.cameraview"
    )
    module = __import__(module_name, fromlist=["CameraView"])
    return module.CameraView


def _camera_destination_rect(camera_view, rect):
    import pyray as rl

    transform = camera_view._calc_frame_matrix(rect)
    scale_x = rect.width * transform[0, 0]
    scale_y = rect.height * transform[1, 1]

    x_offset = rect.x + (rect.width - scale_x) / 2
    y_offset = rect.y + (rect.height - scale_y) / 2
    x_offset += transform[0, 2] * rect.width / 2
    y_offset += transform[1, 2] * rect.height / 2
    return rl.Rectangle(x_offset, y_offset, scale_x, scale_y)


def _install_driver_debug_face_box(driver_view, *, device_type: str) -> None:
    def _draw_face_detection_override(self, rect):
        from openpilot.selfdrive.ui.ui_state import ui_state

        dm_state = ui_state.sm["driverMonitoringState"]
        driver_state = ui_state.sm["driverStateV2"]
        driver_data, other_driver_data, _is_rhd, _wheel_on_right_prob, _selected_side, _other_side = _select_driver_sides(
            dm_state=dm_state,
            driver_state=driver_state,
        )
        if driver_data is None and other_driver_data is None:
            return None

        camera_view = getattr(self, "_camera_view", self)
        content_rect = _camera_destination_rect(camera_view, rect) if getattr(camera_view, "frame", None) is not None else rect
        frame = getattr(camera_view, "frame", None)
        if frame is not None:
            _draw_driver_monitoring_input_overlay(
                content_rect,
                frame_width=float(getattr(frame, "width", 0.0) or 0.0),
                frame_height=float(getattr(frame, "height", 0.0) or 0.0),
            )
        legend_items: list[tuple[str, object]] = []

        selected_face_prob = float(getattr(driver_data, "faceProb", 0.0) or 0.0) if driver_data is not None else 0.0
        other_face_prob = float(getattr(other_driver_data, "faceProb", 0.0) or 0.0) if other_driver_data is not None else 0.0

        if driver_data is not None and (selected_face_prob >= 0.5 or bool(getattr(dm_state, "faceDetected", False))):
            selected_color = _draw_driver_debug_face_box(
                content_rect,
                driver_data=driver_data,
                device_type=device_type,
                role="selected",
            )
            if selected_color is not None:
                legend_items.append(("driver seat", selected_color))
        if other_driver_data is not None and other_face_prob >= 0.35:
            other_color = _draw_driver_debug_face_box(
                content_rect,
                driver_data=other_driver_data,
                device_type=device_type,
                role="other",
            )
            if other_color is not None:
                legend_items.append(("other seat", other_color))
        if legend_items and hasattr(self, "_overlay_renderer") and self._overlay_renderer is not None:
            self._overlay_renderer._draw_box_legend(content_rect.x + 18, content_rect.y + 18, legend_items)
        return driver_data

    driver_view._draw_face_detection = types.MethodType(_draw_face_detection_override, driver_view)

    def _draw_eyes_override(self, rect, driver_data):
        return None

    driver_view._draw_eyes = types.MethodType(_draw_eyes_override, driver_view)

    def _render_dm_alerts_override(self, rect):
        return None

    if hasattr(driver_view, "_render_dm_alerts"):
        driver_view._render_dm_alerts = types.MethodType(_render_dm_alerts_override, driver_view)

    if hasattr(driver_view, "driver_state_renderer"):
        def _render_driver_state_override(*args, **kwargs):
            return None

        driver_view.driver_state_renderer.render = _render_driver_state_override


def _install_unmirrored_driver_camera(driver_view, *, device_type: str) -> None:
    camera_view = getattr(driver_view, "_camera_view", driver_view)
    patches_nested_camera_view = camera_view is not driver_view

    try:
        base_camera_view = _driver_camera_view_base_class(device_type=device_type)
    except ModuleNotFoundError:
        base_camera_view = None

    if base_camera_view is not None:
        def _calc_frame_matrix_unzoomed(self, rect):
            return base_camera_view._calc_frame_matrix(self, rect)

        camera_view._calc_frame_matrix = types.MethodType(_calc_frame_matrix_unzoomed, camera_view)

    def _render_unmirrored(self, rect):
        import pyray as rl

        if self._switching:
            self._handle_switch()

        if not self._ensure_connection():
            self._draw_placeholder(rect)
            return

        buffer = self.client.recv(timeout_ms=0)
        if buffer:
            self._texture_needs_update = True
            self.frame = buffer
        elif not self.client.is_connected():
            self.frame = None

        if not self.frame:
            self._draw_placeholder(rect)
            return

        transform = self._calc_frame_matrix(rect)
        src_rect = rl.Rectangle(0, 0, float(self.frame.width), float(self.frame.height))

        scale_x = rect.width * transform[0, 0]
        scale_y = rect.height * transform[1, 1]

        x_offset = rect.x + (rect.width - scale_x) / 2
        y_offset = rect.y + (rect.height - scale_y) / 2
        x_offset += transform[0, 2] * rect.width / 2
        y_offset += transform[1, 2] * rect.height / 2

        dst_rect = rl.Rectangle(x_offset, y_offset, scale_x, scale_y)
        self._content_rect = dst_rect

        if self.egl_texture is not None:
            self._render_egl(src_rect, dst_rect)
        else:
            self._render_textures(src_rect, dst_rect)

        if not patches_nested_camera_view:
            self._draw_face_detection(rect)
            if hasattr(self, "driver_state_renderer"):
                self.driver_state_renderer.render(rect)
            return -1

    camera_view._render = types.MethodType(_render_unmirrored, camera_view)


def clip(
    route,
    output: str,
    *,
    start: int,
    end: int,
    headless: bool,
    title: str | None,
    show_metadata: bool,
    show_time: bool,
    backing_video: str | None,
) -> None:
    import pyray as rl
    import tqdm
    from msgq.visionipc import VisionIpcServer, VisionStreamType
    from openpilot.common.prefix import OpenpilotPrefix
    from openpilot.common.utils import Timer
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.system.ui.lib.application import FontWeight, gui_app

    timer = Timer()
    duration = end - start
    timer.lap("import")

    logger.info("Clipping %s, %ss-%ss (%ss) with driver replay", route.name.canonical_name, start, end, duration)
    seg_start, seg_end = start // 60, (end - 1) // 60 + 1
    messages_by_segment = load_segment_messages(route, seg_start=seg_start, seg_end=seg_end)
    render_steps = build_driver_render_steps(messages_by_segment, start=start, end=end)
    timer.lap("logs")

    if headless:
        rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)

    with OpenpilotPrefix(shared_download_cache=True):
        route_metadata = load_route_metadata(route)
        metadata = route_metadata if show_metadata else None
        driver_paths = route.dcamera_paths()
        if backing_video:
            driver_frame_queue = DecodedBackingVideoFrameSource(Path(backing_video).resolve())
            if driver_frame_queue.frame_count and driver_frame_queue.frame_count < len(render_steps):
                raise RuntimeError(
                    f"Backing video has only {driver_frame_queue.frame_count} frames but render needs {len(render_steps)}."
                )
        else:
            driver_frame_queue = IndexedFrameQueue(
                driver_paths[seg_start:seg_end],
                [step.camera_ref for step in render_steps],
                use_qcam=False,
            )

        vipc = VisionIpcServer("camerad")
        vipc.create_buffers(
            VisionStreamType.VISION_STREAM_DRIVER,
            4,
            driver_frame_queue.frame_w,
            driver_frame_queue.frame_h,
        )
        vipc.start_listener()

        patch_submaster(render_steps, ui_state)
        _configure_gui_app_canvas(gui_app, width=DRIVER_DEBUG_WIDTH, height=DRIVER_DEBUG_HEIGHT)
        gui_app.init_window("driver debug clip", fps=FRAMERATE)
        _reapply_hidden_window_flag(headless=headless)

        DriverCameraDialog = _select_driver_camera_dialog(device_type=route_metadata.get("device_type", "unknown"))
        driver_view = DriverCameraDialog()
        _install_unmirrored_driver_camera(driver_view, device_type=route_metadata.get("device_type", "unknown"))
        _install_driver_debug_face_box(driver_view, device_type=route_metadata.get("device_type", "unknown"))
        driver_view.set_rect(rl.Rectangle(0, 0, gui_app.width, DRIVER_DEBUG_VIDEO_HEIGHT))
        font = gui_app.font(FontWeight.NORMAL)
        debug_overlay = DriverDebugOverlayRenderer(
            label_font=gui_app.font(FontWeight.MEDIUM),
            value_font=gui_app.font(FontWeight.BOLD),
        )
        timer.lap("setup")

        frame_idx = 0
        render_started_at = time.perf_counter()
        last_log_at = render_started_at
        last_log_frame_idx = 0
        with tqdm.tqdm(total=len(render_steps), desc="Rendering", unit="frame") as progress:
            for should_render in gui_app.render():
                if frame_idx >= len(render_steps):
                    break

                step = render_steps[frame_idx]
                if backing_video:
                    camera_ref, frame_bytes = driver_frame_queue.get(step.camera_ref)
                else:
                    camera_ref, frame_bytes = driver_frame_queue.get()
                    if camera_ref != step.camera_ref:
                        raise RuntimeError(
                            f"Driver camera frame order mismatch: expected {step.camera_ref}, got {camera_ref}"
                        )
                vipc.send(
                    VisionStreamType.VISION_STREAM_DRIVER,
                    frame_bytes,
                    camera_ref.route_frame_id,
                    camera_ref.timestamp_sof,
                    camera_ref.timestamp_eof,
                )
                ui_state.update()

                if should_render:
                    driver_view.render()
                    debug_overlay.render(
                        rl.Rectangle(18, DRIVER_DEBUG_VIDEO_HEIGHT + 18, gui_app.width - 36, DRIVER_DEBUG_FOOTER_HEIGHT - 36),
                        telemetry=extract_driver_debug_telemetry(step.state),
                        route_seconds=step.route_seconds,
                        metadata=metadata,
                    )
                    if title:
                        draw_text_box(title, 18, DRIVER_DEBUG_VIDEO_HEIGHT + 24, 22, gui_app, font)

                frame_idx += 1
                progress.update(1)
                now = time.perf_counter()
                if frame_idx == len(render_steps) or now - last_log_at >= 5.0:
                    total_elapsed = max(now - render_started_at, 1e-6)
                    interval_elapsed = max(now - last_log_at, 1e-6)
                    avg_fps = frame_idx / total_elapsed
                    interval_fps = (frame_idx - last_log_frame_idx) / interval_elapsed
                    emit_runtime_log(
                        f"Driver debug render progress: {frame_idx}/{len(render_steps)} frames, "
                        f"avg {avg_fps:.2f} fps, recent {interval_fps:.2f} fps, "
                        f"route {step.route_seconds:.2f}s"
                    )
                    last_log_at = now
                    last_log_frame_idx = frame_idx
        timer.lap("render")

        driver_frame_queue.stop()
        driver_view.close()
        gui_app.close()
        timer.lap("ffmpeg")

    logger.info("Clip saved to: %s", Path(output).resolve())
    if frame_idx:
        render_seconds = max(getattr(timer, "_sections", {}).get("render", 0.0), 1e-6)
        emit_runtime_log(
            "Driver debug render stats: "
            f"frames={frame_idx}, render_seconds={render_seconds:.2f}, avg_fps={frame_idx / render_seconds:.2f}"
        )
    logger.info("Generated %s", timer.fmt(duration))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s\t%(message)s", force=True)
    original_cwd = Path.cwd()
    args = _normalize_cli_paths(parse_args(), cwd=original_cwd)
    openpilot_dir = Path(args.openpilot_dir).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    os.chdir(openpilot_dir)
    _add_openpilot_to_sys_path(openpilot_dir)

    headless = not args.windowed
    setup_env(str(output_path), big=False, target_mb=args.file_size, duration=args.end - args.start, headless=headless)

    from openpilot.tools.lib.route import Route

    clip(
        Route(args.route, data_dir=args.data_dir),
        str(output_path),
        start=args.start,
        end=args.end,
        headless=headless,
        title=args.title,
        show_metadata=not args.no_metadata,
        show_time=not args.no_time_overlay,
        backing_video=args.backing_video,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
