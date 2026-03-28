from __future__ import annotations

import argparse
from collections.abc import Mapping
import logging
import math
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


FRAMERATE = 20
CAMERA_SERVICE = "roadEncodeIdx"
WIDE_CAMERA_SERVICE = "wideRoadEncodeIdx"
MODEL_SERVICE = "modelV2"
TEXT_BOX_PADDING_X = 8
TEXT_BOX_PADDING_Y = 4
TIME_OVERLAY_EDGE_MARGIN_BIG = 24
TIME_OVERLAY_EDGE_MARGIN_SMALL = 14
UI_ALT_FOOTER_MIN_HEIGHT = 220
UI_ALT_FOOTER_MAX_HEIGHT = 320
UI_ALT_FOOTER_HEIGHT_RATIO = 0.25
UI_ALT_PANEL_LABEL_INSET_X = 32
UI_ALT_PANEL_LABEL_INSET_Y = 28
UI_ALT_FOOTER_OUTER_PAD_X = 34.0
UI_ALT_FOOTER_OUTER_PAD_Y = 24.0
UI_ALT_FOOTER_COLUMN_GAP = 36.0
UI_ALT_CONFIDENCE_RAIL_WIDTH = 84.0
UI_ALT_CONFIDENCE_RAIL_GAP = 24.0
UI_ALT_CONFIDENCE_LABEL_NUDGE_X = -4.0
UI_ALT_BLINKER_CORNER_INSET_Y = 20
UI_ALT_STEERING_DISPLAY_RING_PAD = 52
TORQUE_RING_MAX_SPAN_DEG = 112.0
TORQUE_RING_NEUTRAL_DEG = 270.0
MODEL_INPUT_OVERLAY_COLOR = (0, 255, 204, 255)
MODEL_INPUT_OVERLAY_SHADOW = (0, 0, 0, 180)
MODEL_INPUT_OVERLAY_LINE_WIDTH = 2.0
MODEL_INPUT_OVERLAY_SHADOW_WIDTH = 6.0
INF_POINT = (1000.0, 0.0, 0.0)
FUTURE_BACKFILL_SERVICES = ("carParams",)
logger = logging.getLogger("big_ui_engine")


def emit_runtime_log(message: str) -> None:
    print(message, flush=True)


def _configure_gui_app_canvas(gui_app, *, width: int, height: int) -> None:
    gui_app._width = width
    gui_app._height = height
    gui_app._scaled_width = int(width * gui_app._scale)
    gui_app._scaled_height = int(height * gui_app._scale)
    gui_app._scaled_width += gui_app._scaled_width % 2
    gui_app._scaled_height += gui_app._scaled_height % 2


def compute_ui_alt_footer_height(height: int) -> int:
    footer_height = int(height * UI_ALT_FOOTER_HEIGHT_RATIO)
    footer_height = max(UI_ALT_FOOTER_MIN_HEIGHT, min(UI_ALT_FOOTER_MAX_HEIGHT, footer_height))
    return min(footer_height, max(1, height - 1))


def compute_ui_alt_dual_canvas_height(base_height: int) -> int:
    return (base_height * 2) + compute_ui_alt_footer_height(base_height)


def _add_openpilot_to_sys_path(openpilot_dir: Path) -> None:
    resolved = openpilot_dir.resolve()
    if str(resolved) not in sys.path:
        sys.path.insert(0, str(resolved))
    existing = os.environ.get("PYTHONPATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    if str(resolved) not in parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([str(resolved), *parts]) if parts else str(resolved)


@dataclass(frozen=True)
class CameraFrameRef:
    route_frame_id: int
    timestamp_sof: int
    timestamp_eof: int
    segment_index: int
    local_index: int


@dataclass(frozen=True)
class RenderStep:
    route_seconds: float
    route_frame_id: int
    camera_ref: CameraFrameRef
    wide_camera_ref: CameraFrameRef | None
    state: dict


@dataclass(frozen=True)
class LayoutRects:
    road_rect: tuple[int, int, int, int]
    wide_rect: tuple[int, int, int, int] | None = None
    footer_rect: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class FooterTelemetry:
    steering_angle_deg: float = 0.0
    steering_target_deg: float | None = None
    steering_applied_deg: float | None = None
    steering_target_torque: float | None = None
    steering_applied_torque: float | None = None
    steering_control_kind: str = "angle"
    steering_saturated: bool = False
    steering_pressed: bool = False
    left_blinker: bool = False
    right_blinker: bool = False
    driver_gas: float = 0.0
    driver_brake: float = 0.0
    driver_gas_pressed: bool = False
    driver_brake_pressed: bool = False
    op_gas: float = 0.0
    op_brake: float = 0.0
    accel_cmd: float = 0.0
    accel_out: float | None = None
    a_ego: float | None = None
    a_target: float | None = None
    confidence: float = 0.0
    ui_status: str = "disengaged"


@dataclass(frozen=True)
class FooterPanelLayout:
    wheel_col_w: float
    right_x: float
    right_w: float
    driver_col_x: float
    op_col_x: float
    meter_w: float
    confidence_rect: tuple[float, float, float, float]
    accel_rect: tuple[float, float, float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repo-owned BIG UI clip renderer")
    parser.add_argument("route", help="Route ID as dongle/route")
    parser.add_argument("--openpilot-dir", required=True, help="Path to the openpilot checkout")
    parser.add_argument("-s", "--start", type=int, required=True, help="Start time in seconds")
    parser.add_argument("-e", "--end", type=int, required=True, help="End time in seconds")
    parser.add_argument("-o", "--output", required=True, help="Output file path")
    parser.add_argument("-d", "--data-dir", help="Local directory with route data")
    parser.add_argument("-t", "--title", help="Title overlay text")
    parser.add_argument("-f", "--file-size", type=float, default=9.0, help="Target file size in MB")
    parser.add_argument("--big", action="store_true", help="Use big UI")
    parser.add_argument("--qcam", action="store_true", help="Use qcamera instead of fcamera")
    parser.add_argument("--windowed", action="store_true", help="Show window")
    parser.add_argument("--no-metadata", action="store_true", help="Disable metadata overlay")
    parser.add_argument("--no-time-overlay", action="store_true", help="Disable time overlay")
    parser.add_argument(
        "--layout-mode",
        choices=["default", "alt"],
        default="default",
        help="UI layout mode. alt reserves a footer below the road view for a rotating steering wheel.",
    )
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error(f"end ({args.end}) must be greater than start ({args.start})")
    return args


def build_layout_rects(
    *,
    width: int,
    height: int,
    layout_mode: str,
    show_wide_panel: bool = False,
    footer_height_override: int | None = None,
) -> LayoutRects:
    if layout_mode == "default":
        return LayoutRects(road_rect=(0, 0, width, height))
    if layout_mode != "alt":
        raise ValueError(f"Unknown layout mode: {layout_mode}")

    footer_height = footer_height_override if footer_height_override is not None else compute_ui_alt_footer_height(height)
    road_height = height - footer_height
    if show_wide_panel:
        top_height = road_height - (road_height // 2)
        bottom_height = road_height - top_height
        return LayoutRects(
            road_rect=(0, 0, width, top_height),
            wide_rect=(0, top_height, width, bottom_height),
            footer_rect=(0, road_height, width, footer_height),
        )
    return LayoutRects(
        road_rect=(0, 0, width, road_height),
        footer_rect=(0, road_height, width, footer_height),
    )


def extract_steering_angle_deg(state: Mapping[str, object]) -> float:
    car_state_msg = state.get("carState")
    if car_state_msg is None:
        return 0.0
    car_state = getattr(car_state_msg, "carState", None)
    if car_state is None:
        return 0.0
    return float(getattr(car_state, "steeringAngleDeg", 0.0))


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _footer_ui_status(*, enabled: bool, state: object) -> str:
    if state is None:
        return "disengaged"

    state_name = getattr(state, "name", None)
    if state_name is None:
        state_name = str(state).split(".")[-1]
    if state_name in ("preEnabled", "overriding"):
        return "override"
    return "engaged" if enabled else "disengaged"


def footer_confidence_target_value(*, status: str, confidence: float) -> float:
    if status == "disengaged":
        return -0.5
    return _clip01(confidence)


def footer_confidence_colors(*, status: str, confidence_value: float) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    if status == "engaged":
        if confidence_value > 0.5:
            return (0, 255, 204, 255), (0, 255, 38, 255)
        if confidence_value > 0.2:
            return (255, 200, 0, 255), (255, 115, 0, 255)
        return (255, 0, 21, 255), (255, 0, 89, 255)
    if status == "override":
        return (255, 255, 255, 255), (82, 82, 82, 255)
    return (50, 50, 50, 255), (13, 13, 13, 255)


def compute_confidence_dot_center_y(*, rail_y: float, rail_height: float, dot_radius: float, confidence_value: float) -> float:
    return rail_y + ((1 - confidence_value) * max(0.0, rail_height - (2 * dot_radius))) + dot_radius


def build_footer_panel_layout(rect) -> FooterPanelLayout:
    wheel_col_w = rect.width * 0.38
    right_x = rect.x + wheel_col_w + UI_ALT_FOOTER_OUTER_PAD_X
    right_w = rect.width - wheel_col_w - (2 * UI_ALT_FOOTER_OUTER_PAD_X)
    confidence_rect = (
        rect.x + rect.width - UI_ALT_FOOTER_OUTER_PAD_X - UI_ALT_CONFIDENCE_RAIL_WIDTH,
        rect.y + UI_ALT_FOOTER_OUTER_PAD_Y,
        UI_ALT_CONFIDENCE_RAIL_WIDTH,
        rect.height - (2 * UI_ALT_FOOTER_OUTER_PAD_Y),
    )
    meters_right = confidence_rect[0] - UI_ALT_CONFIDENCE_RAIL_GAP
    main_panel_w = max(0.0, meters_right - right_x)
    meter_w = max(120.0, (main_panel_w - UI_ALT_FOOTER_COLUMN_GAP) / 2)
    accel_summary_y = rect.y + UI_ALT_FOOTER_OUTER_PAD_Y + 34 + 74 + 82
    return FooterPanelLayout(
        wheel_col_w=wheel_col_w,
        right_x=right_x,
        right_w=right_w,
        driver_col_x=right_x,
        op_col_x=right_x + meter_w + UI_ALT_FOOTER_COLUMN_GAP,
        meter_w=meter_w,
        confidence_rect=confidence_rect,
        accel_rect=(right_x, accel_summary_y, main_panel_w, 54),
    )


def compute_ui_alt_panel_label_position(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    return (
        int(rect[0] + UI_ALT_PANEL_LABEL_INSET_X),
        int(rect[1] + UI_ALT_PANEL_LABEL_INSET_Y),
    )


def compute_time_overlay_position(*, gui_width: int, time_width: int, big: bool) -> tuple[int, int]:
    edge_margin = TIME_OVERLAY_EDGE_MARGIN_BIG if big else TIME_OVERLAY_EDGE_MARGIN_SMALL
    return (
        gui_width - time_width - TEXT_BOX_PADDING_X - edge_margin,
        TEXT_BOX_PADDING_Y + edge_margin,
    )


def _extract_nested_attr(obj: object, path: tuple[str, ...]) -> object | None:
    current = obj
    for name in path:
        current = getattr(current, name, None)
        if current is None:
            return None
    return current


def _lateral_control_state_branch(controls_state: object) -> tuple[str | None, object | None]:
    lateral_control_state = getattr(controls_state, "lateralControlState", None)
    if lateral_control_state is None:
        return None, None
    if hasattr(lateral_control_state, "which"):
        branch_name = lateral_control_state.which()
    else:
        branch_name = next(
            (
                candidate
                for candidate in (
                    "torqueState",
                    "angleState",
                    "pidState",
                    "indiStateDEPRECATED",
                    "lqrStateDEPRECATED",
                    "debugState",
                )
                if getattr(lateral_control_state, candidate, None) is not None
            ),
            None,
        )
    if branch_name is None:
        return None, None
    return branch_name, getattr(lateral_control_state, branch_name, None)


def torque_ring_endpoint_angle(value: float, *, max_span_deg: float = TORQUE_RING_MAX_SPAN_DEG) -> float:
    clamped = max(-1.0, min(1.0, float(value)))
    return TORQUE_RING_NEUTRAL_DEG + (clamped * max_span_deg)


def extract_footer_telemetry(state: Mapping[str, object]) -> FooterTelemetry:
    car_state_msg = state.get("carState")
    car_control_msg = state.get("carControl")
    car_output_msg = state.get("carOutput")
    controls_state_msg = state.get("controlsState")
    longitudinal_plan_msg = state.get("longitudinalPlan")
    model_msg = state.get("modelV2")
    selfdrive_state_msg = state.get("selfdriveState")

    car_state = getattr(car_state_msg, "carState", None) if car_state_msg is not None else None
    car_control = getattr(car_control_msg, "carControl", None) if car_control_msg is not None else None
    car_output = getattr(car_output_msg, "carOutput", None) if car_output_msg is not None else None
    controls_state = getattr(controls_state_msg, "controlsState", None) if controls_state_msg is not None else None
    model = getattr(model_msg, "modelV2", None) if model_msg is not None else None
    selfdrive_state = getattr(selfdrive_state_msg, "selfdriveState", None) if selfdrive_state_msg is not None else None
    longitudinal_plan = (
        getattr(longitudinal_plan_msg, "longitudinalPlan", None) if longitudinal_plan_msg is not None else None
    )

    accel_cmd = float(getattr(getattr(car_control, "actuators", None), "accel", 0.0) or 0.0)
    accel_out_attr = getattr(getattr(car_output, "actuatorsOutput", None), "accel", None)
    accel_out = float(accel_out_attr) if accel_out_attr is not None else None
    lateral_control_branch_name, lateral_control_branch = _lateral_control_state_branch(controls_state)
    uses_torque_control = lateral_control_branch_name == "torqueState"

    steering_target_attr = None if uses_torque_control else getattr(getattr(car_control, "actuators", None), "steeringAngleDeg", None)
    if steering_target_attr is None and not uses_torque_control:
        steering_target_attr = getattr(lateral_control_branch, "steeringAngleDesiredDeg", None)
    steering_applied_attr = None if uses_torque_control else getattr(getattr(car_output, "actuatorsOutput", None), "steeringAngleDeg", None)
    steering_target_torque_attr = getattr(getattr(car_control, "actuators", None), "torque", None)
    steering_applied_torque_attr = getattr(getattr(car_output, "actuatorsOutput", None), "torque", None)

    a_target_attr = getattr(longitudinal_plan, "aTarget", None)
    if a_target_attr is None and longitudinal_plan is not None and len(getattr(longitudinal_plan, "accels", [])):
        a_target_attr = longitudinal_plan.accels[0]

    steering_angle_deg = float(getattr(car_state, "steeringAngleDeg", 0.0) or 0.0)
    steering_target_deg = float(steering_target_attr) if steering_target_attr is not None else None
    steering_applied_deg = float(steering_applied_attr) if steering_applied_attr is not None else None
    steering_target_torque = float(steering_target_torque_attr) if uses_torque_control and steering_target_torque_attr is not None else None
    steering_applied_torque = float(steering_applied_torque_attr) if uses_torque_control and steering_applied_torque_attr is not None else None
    steering_saturated = bool(getattr(lateral_control_branch, "saturated", False))
    disengage_predictions = getattr(getattr(model, "meta", None), "disengagePredictions", None)
    brake_probs = list(getattr(disengage_predictions, "brakeDisengageProbs", []) or [1])
    steer_probs = list(getattr(disengage_predictions, "steerOverrideProbs", []) or [1])
    confidence = _clip01((1 - max(brake_probs)) * (1 - max(steer_probs)))
    ui_status = _footer_ui_status(
        enabled=bool(getattr(selfdrive_state, "enabled", False)),
        state=getattr(selfdrive_state, "state", None),
    )

    return FooterTelemetry(
        steering_angle_deg=steering_angle_deg,
        steering_target_deg=steering_target_deg,
        steering_applied_deg=steering_applied_deg,
        steering_target_torque=steering_target_torque,
        steering_applied_torque=steering_applied_torque,
        steering_control_kind="torque" if uses_torque_control else "angle",
        steering_saturated=steering_saturated,
        steering_pressed=bool(getattr(car_state, "steeringPressed", False)),
        left_blinker=bool(getattr(car_state, "leftBlinker", False)),
        right_blinker=bool(getattr(car_state, "rightBlinker", False)),
        driver_gas=_clip01(float(getattr(car_state, "gasDEPRECATED", 0.0) or 0.0)),
        driver_brake=_clip01(float(getattr(car_state, "brake", 0.0) or 0.0)),
        driver_gas_pressed=bool(getattr(car_state, "gasPressed", False)),
        driver_brake_pressed=bool(getattr(car_state, "brakePressed", False)),
        op_gas=_clip01(accel_cmd / 4.0),
        op_brake=_clip01(-accel_cmd / 4.0),
        accel_cmd=accel_cmd,
        accel_out=accel_out,
        a_ego=float(getattr(car_state, "aEgo", 0.0)) if car_state is not None else None,
        a_target=float(a_target_attr) if a_target_attr is not None else None,
        confidence=confidence,
        ui_status=ui_status,
    )


def setup_env(output_path: str, *, big: bool, target_mb: float, duration: int, headless: bool) -> None:
    os.environ.update({"RECORD": "1", "RECORD_OUTPUT": str(Path(output_path).with_suffix(".mp4"))})
    if headless:
        os.environ["OFFSCREEN"] = "1"
    if target_mb > 0 and duration > 0:
        os.environ["RECORD_BITRATE"] = f"{int(target_mb * 8 * 1024 / duration)}k"
    if big:
        os.environ["BIG"] = "1"
    os.environ.setdefault("SCALE", "1")


def _mat3_mul(left, right) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    rows = []
    for row in range(3):
        rows.append(
            tuple(
                float(sum(float(left[row][idx]) * float(right[idx][col]) for idx in range(3)))
                for col in range(3)
            )
        )
    return tuple(rows)


def _mat3_vec_mul(matrix, vector) -> tuple[float, float, float]:
    return tuple(
        float(sum(float(matrix[row][idx]) * float(vector[idx]) for idx in range(3)))
        for row in range(3)
    )


def project_model_input_quad(
    *,
    model_size: tuple[int, int],
    warp_matrix,
    video_transform,
) -> tuple[tuple[float, float], ...] | None:
    model_width, model_height = model_size
    if model_width <= 0 or model_height <= 0:
        return None

    corners = (
        (0.0, 0.0, 1.0),
        (model_width - 1.0, 0.0, 1.0),
        (model_width - 1.0, model_height - 1.0, 1.0),
        (0.0, model_height - 1.0, 1.0),
    )
    projected_xy: list[tuple[float, float]] = []
    for corner in corners:
        camera_point = _mat3_vec_mul(warp_matrix, corner)
        screen_point = _mat3_vec_mul(video_transform, camera_point)
        if abs(screen_point[2]) < 1e-6:
            return None
        x = screen_point[0] / screen_point[2]
        y = screen_point[1] / screen_point[2]
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        projected_xy.append((float(x), float(y)))
    return tuple(projected_xy)


def compute_camera_view_video_transform(view, *, use_wide_camera: bool) -> tuple[tuple[float, float, float], ...] | None:
    content_rect = getattr(view, "_content_rect", None)
    device_camera = getattr(view, "device_camera", None)
    if content_rect is None or device_camera is None:
        return None

    width = float(getattr(content_rect, "width", 0.0) or 0.0)
    height = float(getattr(content_rect, "height", 0.0) or 0.0)
    if width <= 0.0 or height <= 0.0:
        return None

    intrinsic = device_camera.ecam.intrinsics if use_wide_camera else device_camera.fcam.intrinsics
    calibration = getattr(view, "view_from_wide_calib", None) if use_wide_camera else getattr(view, "view_from_calib", None)
    if calibration is None:
        return None

    zoom = 2.0 if use_wide_camera else 1.1
    calib_transform = _mat3_mul(intrinsic, calibration)
    kep = _mat3_vec_mul(calib_transform, INF_POINT)

    x = float(content_rect.x)
    y = float(content_rect.y)
    cx = float(intrinsic[0, 2])
    cy = float(intrinsic[1, 2])
    zoom = max(zoom, width / (2 * cx), height / (2 * cy))

    margin = 5.0
    max_x_offset = max(0.0, cx * zoom - width / 2 - margin)
    max_y_offset = max(0.0, cy * zoom - height / 2 - margin)

    try:
        if abs(float(kep[2])) > 1e-6:
            x_offset = max(-max_x_offset, min(max_x_offset, (float(kep[0]) / float(kep[2]) - cx) * zoom))
            y_offset = max(-max_y_offset, min(max_y_offset, (float(kep[1]) / float(kep[2]) - cy) * zoom))
        else:
            x_offset, y_offset = 0.0, 0.0
    except (ZeroDivisionError, OverflowError):
        x_offset, y_offset = 0.0, 0.0

    return (
        (zoom, 0.0, (width / 2 + x - x_offset) - (cx * zoom)),
        (0.0, zoom, (height / 2 + y - y_offset) - (cy * zoom)),
        (0.0, 0.0, 1.0),
    )


def compute_model_input_overlay_quad(
    view,
    state: Mapping[str, object],
    *,
    use_wide_camera: bool,
    bigmodel_frame: bool,
) -> tuple[tuple[float, float], ...] | None:
    live_calibration_msg = state.get("liveCalibration")
    live_calibration = getattr(live_calibration_msg, "liveCalibration", None) if live_calibration_msg is not None else None
    if live_calibration is None:
        return None

    rpy_calib = list(getattr(live_calibration, "rpyCalib", []) or [])
    if len(rpy_calib) != 3:
        return None

    video_transform = compute_camera_view_video_transform(view, use_wide_camera=use_wide_camera)
    if video_transform is None:
        return None

    device_camera = getattr(view, "device_camera", None)
    if device_camera is None:
        return None

    from openpilot.common.transformations.model import MEDMODEL_INPUT_SIZE, SBIGMODEL_INPUT_SIZE, get_warp_matrix

    intrinsics = device_camera.ecam.intrinsics if use_wide_camera else device_camera.fcam.intrinsics
    model_size = SBIGMODEL_INPUT_SIZE if bigmodel_frame else MEDMODEL_INPUT_SIZE
    warp_matrix = get_warp_matrix(rpy_calib, intrinsics, bigmodel_frame=bigmodel_frame)
    return project_model_input_quad(model_size=model_size, warp_matrix=warp_matrix, video_transform=video_transform)


def draw_model_input_overlay(quad: tuple[tuple[float, float], ...] | None, *, clip_rect=None) -> None:
    import pyray as rl

    if quad is None or len(quad) != 4:
        return

    shadow = rl.Color(*MODEL_INPUT_OVERLAY_SHADOW)
    outline = rl.Color(*MODEL_INPUT_OVERLAY_COLOR)
    points = [rl.Vector2(float(x), float(y)) for x, y in quad]
    if clip_rect is not None:
        rl.begin_scissor_mode(
            int(clip_rect.x),
            int(clip_rect.y),
            int(clip_rect.width),
            int(clip_rect.height),
        )
    try:
        for start, end in zip(points, points[1:] + points[:1], strict=False):
            rl.draw_line_ex(start, end, MODEL_INPUT_OVERLAY_SHADOW_WIDTH, shadow)
            rl.draw_line_ex(start, end, MODEL_INPUT_OVERLAY_LINE_WIDTH, outline)
    finally:
        if clip_rect is not None:
            rl.end_scissor_mode()


def draw_ui_alt_model_input_overlays(road_view, wide_view, state: Mapping[str, object]) -> None:
    road_quad = compute_model_input_overlay_quad(
        road_view,
        state,
        use_wide_camera=False,
        bigmodel_frame=False,
    )
    if road_quad is not None:
        draw_model_input_overlay(road_quad, clip_rect=getattr(road_view, "_content_rect", None))

    if wide_view is None:
        return

    wide_quad = compute_model_input_overlay_quad(
        wide_view,
        state,
        use_wide_camera=True,
        bigmodel_frame=True,
    )
    if wide_quad is not None:
        draw_model_input_overlay(wide_quad, clip_rect=getattr(wide_view, "_content_rect", None))


def redraw_ui_alt_dual_view_overlays(road_view, wide_view, state: Mapping[str, object]) -> None:
    draw_ui_alt_model_input_overlays(road_view, wide_view, state)
    redraw_hud_overlay(road_view)
    if wide_view is not None:
        redraw_hud_overlay(wide_view)
        draw_current_speed_overlay(wide_view)


def redraw_ui_alt_dual_view_borders(road_view, wide_view, layout_rects: LayoutRects) -> None:
    import pyray as rl

    road_draw_border = getattr(road_view, "_draw_border", None)
    if callable(road_draw_border):
        road_draw_border(rl.Rectangle(*layout_rects.road_rect))

    if wide_view is None or layout_rects.wide_rect is None:
        return

    wide_draw_border = getattr(wide_view, "_draw_border", None)
    if callable(wide_draw_border):
        wide_draw_border(rl.Rectangle(*layout_rects.wide_rect))


def load_segment_messages(route, *, seg_start: int, seg_end: int) -> list[list]:
    from openpilot.selfdrive.test.process_replay.migration import migrate_all
    from openpilot.tools.lib.logreader import LogReader

    paths = route.log_paths()[seg_start:seg_end]
    segments: list[list] = []
    for rel_idx, path in enumerate(paths):
        if not path:
            raise RuntimeError(f"No log file for segment {seg_start + rel_idx}")
        logger.info("Loading log segment %s", seg_start + rel_idx)
        segments.append(migrate_all(list(LogReader(path))))
    return segments


def build_camera_frame_refs(
    messages_by_segment: list[list], *, encode_service: str = CAMERA_SERVICE, required: bool = True
) -> tuple[dict[int, CameraFrameRef], dict[int, CameraFrameRef]]:
    refs_by_frame_id: dict[int, CameraFrameRef] = {}
    refs_by_timestamp: dict[int, CameraFrameRef] = {}

    for segment_index, messages in enumerate(messages_by_segment):
        local_index = 0
        for msg in messages:
            if msg.which() != encode_service:
                continue
            encode_idx = getattr(msg, encode_service)
            ref = CameraFrameRef(
                route_frame_id=int(encode_idx.frameId),
                timestamp_sof=int(encode_idx.timestampSof),
                timestamp_eof=int(encode_idx.timestampEof),
                segment_index=segment_index,
                local_index=local_index,
            )
            refs_by_frame_id[ref.route_frame_id] = ref
            refs_by_timestamp[ref.timestamp_eof] = ref
            local_index += 1

    if not refs_by_frame_id and required:
        raise RuntimeError(f"No {encode_service} messages were found for the requested route window")
    return refs_by_frame_id, refs_by_timestamp


def _route_seconds_for_frame(frame_id: int) -> float:
    return frame_id / FRAMERATE


def _match_camera_ref(model, refs_by_frame_id: Mapping[int, CameraFrameRef], refs_by_timestamp: Mapping[int, CameraFrameRef]) -> CameraFrameRef | None:
    camera_ref = refs_by_frame_id.get(int(model.frameId))
    if camera_ref is None and hasattr(model, "timestampEof"):
        camera_ref = refs_by_timestamp.get(int(model.timestampEof))
    return camera_ref


def seed_future_backfill_state(ordered_messages: list[object]) -> dict[str, object]:
    seeded_state: dict[str, object] = {}
    for msg in ordered_messages:
        which = msg.which()
        if which not in FUTURE_BACKFILL_SERVICES or which in seeded_state:
            continue
        seeded_state[which] = msg
        if len(seeded_state) == len(FUTURE_BACKFILL_SERVICES):
            break
    return seeded_state


def build_render_steps(messages_by_segment: list[list], *, seg_start: int, start: int, end: int) -> list[RenderStep]:
    refs_by_frame_id, refs_by_timestamp = build_camera_frame_refs(messages_by_segment, encode_service=CAMERA_SERVICE)
    wide_refs_by_frame_id, wide_refs_by_timestamp = build_camera_frame_refs(
        messages_by_segment,
        encode_service=WIDE_CAMERA_SERVICE,
        required=False,
    )
    ordered_messages = [msg for segment in messages_by_segment for msg in segment]

    current_state: dict[str, object] = seed_future_backfill_state(ordered_messages)
    render_steps: list[RenderStep] = []
    for msg in ordered_messages:
        which = msg.which()
        current_state[which] = msg

        if which != MODEL_SERVICE:
            continue

        model = msg.modelV2
        camera_ref = _match_camera_ref(model, refs_by_frame_id, refs_by_timestamp)
        if camera_ref is None:
            logger.warning("Skipping model frame %s because no matching camera frame was found", model.frameId)
            continue
        wide_camera_ref = _match_camera_ref(model, wide_refs_by_frame_id, wide_refs_by_timestamp)
        route_seconds = _route_seconds_for_frame(camera_ref.route_frame_id)
        if route_seconds < start or route_seconds >= end:
            continue

        render_steps.append(
            RenderStep(
                route_seconds=route_seconds,
                route_frame_id=int(model.frameId),
                camera_ref=camera_ref,
                wide_camera_ref=wide_camera_ref,
                state=dict(current_state),
            )
        )

    if not render_steps:
        raise RuntimeError("No render steps were built for the requested time window")
    return render_steps


def patch_submaster(render_steps: list[RenderStep], ui_state) -> None:
    ui_state.started_frame = 0
    ui_state.started_time = time.monotonic()

    def mock_update(timeout=None):
        sm, now = ui_state.sm, time.monotonic()
        sm.updated = dict.fromkeys(sm.services, False)
        if sm.frame < len(render_steps):
            state = render_steps[sm.frame].state
            for svc, msg in state.items():
                if svc in sm.data:
                    sm.seen[svc] = sm.updated[svc] = sm.alive[svc] = sm.valid[svc] = True
                    sm.data[svc] = getattr(msg.as_builder(), svc)
                    sm.logMonoTime[svc], sm.recv_time[svc], sm.recv_frame[svc] = msg.logMonoTime, now, sm.frame
        sm.frame += 1

    ui_state.sm.update = mock_update


def get_frame_dimensions(camera_path: str) -> tuple[int, int]:
    from openpilot.tools.lib.framereader import ffprobe

    probe = ffprobe(camera_path)
    stream = probe["streams"][0]
    return stream["width"], stream["height"]


def load_qcam_segment_frames(path: str, *, width: int, height: int):
    import numpy as np
    from openpilot.tools.lib.filereader import FileReader

    if os.path.exists(path):
        proc = subprocess.run(
            ["ffmpeg", "-v", "quiet", "-i", path, "-f", "rawvideo", "-pix_fmt", "nv12", "-"],
            capture_output=True,
            check=True,
        )
        result = proc.stdout
    else:
        with FileReader(path) as handle:
            proc = subprocess.run(
                ["ffmpeg", "-v", "quiet", "-i", "-", "-f", "rawvideo", "-pix_fmt", "nv12", "-"],
                input=handle.read(),
                capture_output=True,
                check=True,
            )
            result = proc.stdout
    return np.frombuffer(result, dtype=np.uint8).reshape(-1, width * height * 3 // 2)


class IndexedFrameQueue:
    def __init__(self, camera_paths: list[str], frame_refs: list[CameraFrameRef], *, use_qcam: bool) -> None:
        self.frame_refs = frame_refs
        first_path = next((path for path in camera_paths if path), None)
        if not first_path:
            raise RuntimeError("No valid camera paths")
        self.frame_w, self.frame_h = get_frame_dimensions(first_path)
        self._queue: queue.Queue[tuple[CameraFrameRef, bytes] | None] = queue.Queue(maxsize=60)
        self._stop = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(
            target=self._worker,
            args=(camera_paths, frame_refs, use_qcam),
            daemon=True,
        )
        self._thread.start()

    def _worker(self, camera_paths: list[str], frame_refs: list[CameraFrameRef], use_qcam: bool) -> None:
        import numpy as np
        from openpilot.tools.lib.framereader import FrameReader

        current_segment = -1
        segment_frames = None
        try:
            for ref in frame_refs:
                if self._stop.is_set():
                    break
                if ref.segment_index != current_segment:
                    current_segment = ref.segment_index
                    path = camera_paths[current_segment] if current_segment < len(camera_paths) else None
                    if not path:
                        raise RuntimeError(f"No camera file for segment {current_segment}")
                    if use_qcam:
                        width, height = get_frame_dimensions(path)
                        segment_frames = load_qcam_segment_frames(path, width=width, height=height)
                    else:
                        segment_frames = FrameReader(path, pix_fmt="nv12")

                assert segment_frames is not None
                frame = segment_frames[ref.local_index] if use_qcam else segment_frames.get(ref.local_index)
                self._queue.put((ref, frame.tobytes()))
        except Exception as error:  # pragma: no cover - exercised via render smoke tests
            logger.exception("Decode error")
            self._error = error
        finally:
            self._queue.put(None)

    def get(self, timeout: float = 60.0) -> tuple[CameraFrameRef, bytes]:
        if self._error:
            raise self._error
        result = self._queue.get(timeout=timeout)
        if result is None:
            raise StopIteration("No more frames")
        return result

    def stop(self) -> None:
        self._stop.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._thread.join(timeout=2.0)


def load_route_metadata(route) -> dict[str, str]:
    from openpilot.tools.lib.logreader import LogReader
    from openpilot.tools.lib.route import Segment

    path = next((item for item in route.log_paths() if item), None)
    if not path:
        raise RuntimeError("error getting route metadata: cannot find any uploaded logs")
    lr = LogReader(path)
    init_data = lr.first("initData")

    route_info = {}
    try:
        route_info = Segment._get_route_metadata(route.name.canonical_name)
    except Exception:
        route_info = {}

    return {
        "route": route.name.canonical_name,
        "device_type": str(getattr(init_data, "deviceType", None) or "unknown"),
        "platform": route_info.get("platform") or "unknown",
        "remote": init_data.gitRemote or route_info.get("git_remote") or "unknown",
        "branch": init_data.gitBranch or route_info.get("git_branch") or "unknown",
        "commit": (init_data.gitCommit or route_info.get("git_commit") or "unknown")[:8],
        "dirty": str(init_data.dirty).lower(),
    }


def _reapply_hidden_window_flag(*, headless: bool) -> None:
    if not headless:
        return

    import pyray as rl

    set_window_state = getattr(getattr(rl, "rl", None), "SetWindowState", None)
    if set_window_state is None:
        return
    set_window_state(int(rl.ConfigFlags.FLAG_WINDOW_HIDDEN))


def draw_text_box(text, x, y, size, gui_app, font, color=None, center=False) -> None:
    import pyray as rl
    from openpilot.system.ui.lib.text_measure import measure_text_cached

    box_color = rl.Color(0, 0, 0, 85)
    text_color = color or rl.WHITE
    text_size = measure_text_cached(font, text, size)
    text_width, text_height = int(text_size.x), int(text_size.y)
    if center:
        x = (gui_app.width - text_width) // 2
    rl.draw_rectangle(
        x - TEXT_BOX_PADDING_X,
        y - TEXT_BOX_PADDING_Y,
        text_width + (2 * TEXT_BOX_PADDING_X),
        text_height + (2 * TEXT_BOX_PADDING_Y),
        box_color,
    )
    rl.draw_text_ex(font, text, rl.Vector2(x, y), size, 0, text_color)


def draw_current_speed_overlay(road_view) -> None:
    hud_renderer = getattr(road_view, "_hud_renderer", None)
    content_rect = getattr(road_view, "_content_rect", None)
    if hud_renderer is None or content_rect is None:
        return
    speed = getattr(hud_renderer, "speed", None)
    font_bold = getattr(hud_renderer, "_font_bold", None)
    font_medium = getattr(hud_renderer, "_font_medium", None)
    if speed is None or font_bold is None or font_medium is None:
        return

    import pyray as rl
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.system.ui.lib.multilang import tr
    from openpilot.system.ui.lib.text_measure import measure_text_cached

    speed_text = str(round(float(speed)))
    speed_size = measure_text_cached(font_bold, speed_text, 176)
    speed_pos = rl.Vector2(
        content_rect.x + content_rect.width / 2 - speed_size.x / 2,
        content_rect.y + 180 - speed_size.y / 2,
    )
    rl.draw_text_ex(font_bold, speed_text, speed_pos, 176, 0, rl.WHITE)

    unit_text = tr("km/h") if ui_state.is_metric else tr("mph")
    unit_size = measure_text_cached(font_medium, unit_text, 66)
    unit_pos = rl.Vector2(
        content_rect.x + content_rect.width / 2 - unit_size.x / 2,
        content_rect.y + 290 - unit_size.y / 2,
    )
    rl.draw_text_ex(font_medium, unit_text, unit_pos, 66, 0, rl.Color(255, 255, 255, 200))


def redraw_hud_overlay(view) -> None:
    hud_renderer = getattr(view, "_hud_renderer", None)
    content_rect = getattr(view, "_content_rect", None)
    if hud_renderer is None or content_rect is None:
        return
    hud_renderer.render(content_rect)


def compute_shader_gradient_vectors(origin_rect, gradient, *, screen_height: float) -> tuple[tuple[float, float], tuple[float, float]]:
    # openpilot gradients are specified in top-left UI coordinates, but the shader samples gl_FragCoord,
    # which uses a bottom-left origin. Convert to shader space and swap start/end so t=0 stays at the path bottom.
    start_x = origin_rect.x + gradient.end[0] * origin_rect.width
    start_y = screen_height - (origin_rect.y + gradient.end[1] * origin_rect.height)
    end_x = origin_rect.x + gradient.start[0] * origin_rect.width
    end_y = screen_height - (origin_rect.y + gradient.start[1] * origin_rect.height)
    return (start_x, start_y), (end_x, end_y)


def patch_shader_polygon_gradient_coordinates() -> None:
    from openpilot.system.ui.lib import shader_polygon

    if getattr(shader_polygon, "_clipper_gradient_patch", False):
        return

    def _configure_shader_color_patched(state, color, gradient, origin_rect):
        assert (color is not None) != (gradient is not None), "Either color or gradient must be provided"

        use_gradient = 1 if (gradient is not None and len(gradient.colors) >= 1) else 0
        state.use_gradient_ptr[0] = use_gradient
        shader_polygon.rl.set_shader_value(state.shader, state.locations['useGradient'], state.use_gradient_ptr, shader_polygon.UNIFORM_INT)

        if use_gradient:
            gradient = shader_polygon.cast(shader_polygon.Gradient, gradient)
            state.color_count_ptr[0] = len(gradient.colors)
            for i in range(len(gradient.colors)):
                c = gradient.colors[i]
                base = i * 4
                state.gradient_colors_ptr[base:base + 4] = [c.r / 255.0, c.g / 255.0, c.b / 255.0, c.a / 255.0]
            shader_polygon.rl.set_shader_value_v(
                state.shader,
                state.locations['gradientColors'],
                state.gradient_colors_ptr,
                shader_polygon.UNIFORM_VEC4,
                len(gradient.colors),
            )

            for i in range(len(gradient.stops)):
                s = float(gradient.stops[i])
                state.gradient_stops_ptr[i] = 0.0 if s < 0.0 else 1.0 if s > 1.0 else s
            shader_polygon.rl.set_shader_value_v(
                state.shader,
                state.locations['gradientStops'],
                state.gradient_stops_ptr,
                shader_polygon.UNIFORM_FLOAT,
                len(gradient.stops),
            )
            shader_polygon.rl.set_shader_value(
                state.shader,
                state.locations['gradientColorCount'],
                state.color_count_ptr,
                shader_polygon.UNIFORM_INT,
            )

            start_xy, end_xy = compute_shader_gradient_vectors(origin_rect, gradient, screen_height=shader_polygon.gui_app.height)
            start_vec = shader_polygon.rl.Vector2(*start_xy)
            end_vec = shader_polygon.rl.Vector2(*end_xy)
            shader_polygon.rl.set_shader_value(state.shader, state.locations['gradientStart'], start_vec, shader_polygon.UNIFORM_VEC2)
            shader_polygon.rl.set_shader_value(state.shader, state.locations['gradientEnd'], end_vec, shader_polygon.UNIFORM_VEC2)
        else:
            color = color or shader_polygon.rl.WHITE
            state.fill_color_ptr[0:4] = [color.r / 255.0, color.g / 255.0, color.b / 255.0, color.a / 255.0]
            shader_polygon.rl.set_shader_value(state.shader, state.locations['fillColor'], state.fill_color_ptr, shader_polygon.UNIFORM_VEC4)

    shader_polygon._configure_shader_color = _configure_shader_color_patched
    shader_polygon._clipper_gradient_patch = True


def render_overlays(gui_app, font, big, metadata, title, route_seconds, show_metadata, show_time) -> None:
    from openpilot.system.ui.lib.text_measure import measure_text_cached
    from openpilot.system.ui.lib.wrap_text import wrap_text

    metadata_size = 16 if big else 12
    title_size = 32 if big else 24
    time_size = 24 if big else 16
    time_edge_margin = TIME_OVERLAY_EDGE_MARGIN_BIG if big else TIME_OVERLAY_EDGE_MARGIN_SMALL

    time_width = 0
    if show_time:
        time_text = f"{int(route_seconds) // 60:02d}:{int(route_seconds) % 60:02d}"
        time_width = int(measure_text_cached(font, time_text, time_size).x)
        time_x, time_y = compute_time_overlay_position(gui_width=gui_app.width, time_width=time_width, big=big)
        draw_text_box(
            time_text,
            time_x,
            time_y,
            time_size,
            gui_app,
            font,
        )

    if show_metadata and metadata:
        text = ", ".join(
            [
                f"route: {metadata['route']}",
                metadata["device_type"],
                metadata["platform"],
                metadata["remote"],
                metadata["branch"],
                metadata["commit"],
                f"Dirty: {metadata['dirty']}",
            ]
        )
        margin = 2 * (time_width + (2 * TEXT_BOX_PADDING_X) + time_edge_margin if show_time else 20)
        max_width = gui_app.width - margin
        lines = wrap_text(font, text, metadata_size, max_width)
        y_offset = 6
        for line in lines:
            draw_text_box(line, 0, y_offset, metadata_size, gui_app, font, center=True)
            line_height = int(measure_text_cached(font, line, metadata_size).y) + 4
            y_offset += line_height

    if title:
        draw_text_box(title, 0, 60, title_size, gui_app, font, center=True)


class SteeringFooterRenderer:
    def __init__(self, *, gui_app, label_font, value_font) -> None:
        from openpilot.common.filter_simple import FirstOrderFilter

        self._label_font = label_font
        self._value_font = value_font
        self._wheel_texture = gui_app.texture("icons_mici/wheel.png", 220, 220)
        self._confidence_filter = FirstOrderFilter(-0.5, 0.5, 1 / gui_app.target_fps)

    def _draw_meter(self, rect, *, label: str, value: float, color, value_text: str, active: bool) -> None:
        import pyray as rl

        label_color = rl.Color(255, 255, 255, 150)
        value_color = rl.WHITE if active or value > 0 else rl.Color(255, 255, 255, 200)
        track = rl.Color(255, 255, 255, 22)
        fill_alpha = 255 if active else 220
        fill_color = rl.Color(color.r, color.g, color.b, fill_alpha)
        label_size = 20
        value_size = 24
        bar_height = 16
        bar_y = rect.y + 34

        rl.draw_text_ex(self._label_font, label, rl.Vector2(rect.x, rect.y), label_size, 0, label_color)
        value_width = rl.measure_text_ex(self._value_font, value_text, value_size, 0).x
        rl.draw_text_ex(
            self._value_font,
            value_text,
            rl.Vector2(rect.x + rect.width - value_width, rect.y + 1),
            value_size,
            0,
            value_color,
        )
        rl.draw_rectangle_rounded(rl.Rectangle(rect.x, bar_y, rect.width, bar_height), 0.45, 10, track)

        fill_value = value
        if active and fill_value < 0.06:
            fill_value = 0.06
        fill_width = max(0.0, rect.width * _clip01(fill_value))
        if fill_width > 0:
            rl.draw_rectangle_rounded(rl.Rectangle(rect.x, bar_y, fill_width, bar_height), 0.45, 10, fill_color)

    def _draw_accel_summary(self, rect, *, telemetry: FooterTelemetry) -> None:
        import pyray as rl

        label_color = rl.Color(255, 255, 255, 150)
        value_color = rl.WHITE
        label_size = 18
        value_size = 24
        sections = []
        if telemetry.a_ego is not None:
            sections.append(("A EGO", f"{telemetry.a_ego:+.2f}"))
        if telemetry.a_target is not None:
            sections.append(("A TARGET", f"{telemetry.a_target:+.2f}"))
        sections.append(("CMD", f"{telemetry.accel_cmd:+.2f}"))
        if telemetry.accel_out is not None:
            sections.append(("OUT", f"{telemetry.accel_out:+.2f}"))

        section_width = rect.width / max(1, len(sections))
        for idx, (label, value) in enumerate(sections):
            x = rect.x + idx * section_width
            rl.draw_text_ex(self._label_font, label, rl.Vector2(x, rect.y), label_size, 0, label_color)
            rl.draw_text_ex(self._value_font, value, rl.Vector2(x, rect.y + 24), value_size, 0, value_color)

    def _draw_steering_dots(self, *, center_x: float, center_y: float, wheel_size: int, telemetry: FooterTelemetry) -> None:
        import pyray as rl

        actual_color = rl.WHITE
        target_color = rl.Color(125, 196, 255, 255)
        applied_color = rl.Color(255, 176, 87, 255)
        orbit_color = rl.Color(255, 255, 255, 36)
        base_radius = (wheel_size / 2) + 16

        center = rl.Vector2(center_x, center_y)
        rl.draw_ring(center, base_radius - 2, base_radius + 2, 0, 360, 64, orbit_color)

        def draw_dot(angle_deg: float | None, color, radius: float) -> None:
            if angle_deg is None:
                return
            theta = math.radians(-angle_deg - 90.0)
            x = center_x + math.cos(theta) * radius
            y = center_y + math.sin(theta) * radius
            rl.draw_circle(int(x), int(y), 9, rl.Color(0, 0, 0, 210))
            rl.draw_circle(int(x), int(y), 6, color)

        def draw_torque_arc(value: float | None, color, *, inner_radius: float, outer_radius: float) -> float | None:
            if value is None or abs(value) < 1e-3:
                return None
            endpoint = torque_ring_endpoint_angle(value)
            start_angle = min(TORQUE_RING_NEUTRAL_DEG, endpoint)
            end_angle = max(TORQUE_RING_NEUTRAL_DEG, endpoint)
            rl.draw_ring(center, inner_radius, outer_radius, start_angle, end_angle, 40, color)
            tip_radius = (inner_radius + outer_radius) / 2
            tip_theta = math.radians(endpoint)
            tip_x = center_x + (math.cos(tip_theta) * tip_radius)
            tip_y = center_y + (math.sin(tip_theta) * tip_radius)
            rl.draw_circle(int(tip_x), int(tip_y), 6, rl.Color(0, 0, 0, 220))
            rl.draw_circle(int(tip_x), int(tip_y), 4, color)
            return endpoint

        if telemetry.steering_control_kind == "torque":
            track_start = TORQUE_RING_NEUTRAL_DEG - TORQUE_RING_MAX_SPAN_DEG
            track_end = TORQUE_RING_NEUTRAL_DEG + TORQUE_RING_MAX_SPAN_DEG
            rl.draw_ring(center, base_radius + 18, base_radius + 28, track_start, track_end, 48, rl.Color(255, 255, 255, 22))
            rl.draw_ring(center, base_radius + 4, base_radius + 14, track_start, track_end, 48, rl.Color(255, 255, 255, 18))

            target_endpoint = draw_torque_arc(
                telemetry.steering_target_torque,
                target_color,
                inner_radius=base_radius + 18,
                outer_radius=base_radius + 28,
            )
            applied_endpoint = draw_torque_arc(
                telemetry.steering_applied_torque,
                applied_color,
                inner_radius=base_radius + 4,
                outer_radius=base_radius + 14,
            )

            if target_endpoint is not None and applied_endpoint is not None:
                delta = abs((telemetry.steering_target_torque or 0.0) - (telemetry.steering_applied_torque or 0.0))
                mismatch_alpha = int(80 + (175 * _clip01(delta)))
                mismatch_color = rl.Color(255, 82, 82, mismatch_alpha)
                rl.draw_ring(
                    center,
                    base_radius + 31,
                    base_radius + 35,
                    min(target_endpoint, applied_endpoint),
                    max(target_endpoint, applied_endpoint),
                    40,
                    mismatch_color,
                )

            if telemetry.steering_saturated:
                saturation_value = telemetry.steering_target_torque
                if saturation_value is None or abs(saturation_value) < 1e-3:
                    saturation_value = telemetry.steering_applied_torque
                saturation_angle = track_end if (saturation_value or 0.0) >= 0 else track_start
                saturation_span = 8.0
                rl.draw_ring(
                    center,
                    base_radius + 38,
                    base_radius + 45,
                    saturation_angle - saturation_span,
                    saturation_angle + saturation_span,
                    24,
                    rl.Color(255, 82, 82, 240),
                )
        else:
            draw_dot(telemetry.steering_target_deg, target_color, base_radius + 14)
            draw_dot(telemetry.steering_applied_deg, applied_color, base_radius + 2)
        draw_dot(telemetry.steering_angle_deg, actual_color, base_radius - 10)

    def _draw_blinker_arrows(self, *, center_x: float, center_y: float, wheel_size: int, telemetry: FooterTelemetry) -> None:
        import pyray as rl

        inactive_color = rl.Color(255, 255, 255, 60)
        active_color = rl.Color(94, 214, 135, 255)
        hazard_color = rl.Color(255, 176, 87, 255)
        shadow_color = rl.Color(0, 0, 0, 210)
        display_half_extent = (wheel_size / 2) + UI_ALT_STEERING_DISPLAY_RING_PAD
        box_left = center_x - display_half_extent
        box_right = center_x + display_half_extent
        box_top = center_y - display_half_extent
        arrow_center_y = box_top + UI_ALT_BLINKER_CORNER_INSET_Y

        def draw_chevron(*, tip_x: float, direction: int, color) -> None:
            arm_len = 18
            arm_rise = 14
            line_width = 7

            apex_x = tip_x
            outer_x = tip_x - (direction * (arm_len + 8))

            for dx, dy, draw_color in ((2, 2, shadow_color), (0, 0, color)):
                rl.draw_line_ex(
                    rl.Vector2(outer_x + dx, arrow_center_y - arm_rise + dy),
                    rl.Vector2(apex_x + dx, arrow_center_y + dy),
                    line_width,
                    draw_color,
                )
                rl.draw_line_ex(
                    rl.Vector2(outer_x + dx, arrow_center_y + arm_rise + dy),
                    rl.Vector2(apex_x + dx, arrow_center_y + dy),
                    line_width,
                    draw_color,
                )

        left_color = hazard_color if telemetry.left_blinker and telemetry.right_blinker else (
            active_color if telemetry.left_blinker else inactive_color
        )
        right_color = hazard_color if telemetry.left_blinker and telemetry.right_blinker else (
            active_color if telemetry.right_blinker else inactive_color
        )

        draw_chevron(tip_x=box_left, direction=-1, color=left_color)
        draw_chevron(tip_x=box_right, direction=1, color=right_color)

    def _draw_steering_summary(self, rect, *, telemetry: FooterTelemetry) -> None:
        import pyray as rl

        label_color = rl.Color(255, 255, 255, 150)
        value_color = rl.WHITE
        accent = rl.Color(125, 196, 255, 255)
        applied = rl.Color(255, 176, 87, 255)
        label_size = 18
        value_size = 28
        row_gap = 36
        value_x = rect.x + 130

        rows = [("ACTUAL", f"{telemetry.steering_angle_deg:+.1f} deg", value_color)]
        if telemetry.steering_control_kind == "torque":
            rows.extend(
                [
                    (
                        "TARGET",
                        f"{telemetry.steering_target_torque:+.2f} tq"
                        if telemetry.steering_target_torque is not None
                        else "--",
                        accent,
                    ),
                    (
                        "APPLIED",
                        f"{telemetry.steering_applied_torque:+.2f} tq"
                        if telemetry.steering_applied_torque is not None
                        else "--",
                        applied,
                    ),
                ]
            )
            torque_delta = None
            if telemetry.steering_target_torque is not None and telemetry.steering_applied_torque is not None:
                torque_delta = telemetry.steering_target_torque - telemetry.steering_applied_torque
            rows.append(("DELTA", f"{torque_delta:+.2f} tq" if torque_delta is not None else "--", accent))
        else:
            rows.extend(
                [
                    (
                        "TARGET",
                        f"{telemetry.steering_target_deg:+.1f} deg" if telemetry.steering_target_deg is not None else "--",
                        accent,
                    ),
                    (
                        "APPLIED",
                        f"{telemetry.steering_applied_deg:+.1f} deg" if telemetry.steering_applied_deg is not None else "--",
                        applied,
                    ),
                ]
            )
            delta = None
            if telemetry.steering_target_deg is not None:
                delta = telemetry.steering_target_deg - telemetry.steering_angle_deg
            rows.append(("DELTA", f"{delta:+.1f} deg" if delta is not None else "--", accent))
        rows.append(
            (
                "HANDS",
                "ON WHEEL" if telemetry.steering_pressed else "OFF WHEEL",
                value_color if telemetry.steering_pressed else label_color,
            )
        )

        for idx, (label, value, color) in enumerate(rows):
            y = rect.y + idx * row_gap
            rl.draw_text_ex(self._label_font, label, rl.Vector2(rect.x, y + 8), label_size, 0, label_color)
            rl.draw_text_ex(self._value_font, value, rl.Vector2(value_x, y), value_size, 0, color)

    def _draw_confidence_rail(self, rect, *, telemetry: FooterTelemetry) -> None:
        import pyray as rl

        label_color = rl.Color(255, 255, 255, 150)
        track_color = rl.Color(255, 255, 255, 22)
        divider = rl.Color(255, 255, 255, 28)
        dot_radius = 24
        label_size = 14
        label_y = rect.y + 4
        label_text = "CONFIDENCE"
        label_width = rl.measure_text_ex(self._label_font, label_text, label_size, 0).x
        rail_center_x = rect.x + (rect.width / 2)
        track_y = rect.y + 28
        track_height = max(0.0, rect.height - 36)

        confidence_target = footer_confidence_target_value(status=telemetry.ui_status, confidence=telemetry.confidence)
        confidence_value = self._confidence_filter.update(confidence_target)
        top_rgba, bottom_rgba = footer_confidence_colors(status=telemetry.ui_status, confidence_value=confidence_value)

        rl.draw_text_ex(
            self._label_font,
            label_text,
            rl.Vector2((rail_center_x - (label_width / 2)) + UI_ALT_CONFIDENCE_LABEL_NUDGE_X, label_y),
            label_size,
            0,
            label_color,
        )
        rl.draw_line(
            int(rect.x - (UI_ALT_CONFIDENCE_RAIL_GAP / 2)),
            int(rect.y),
            int(rect.x - (UI_ALT_CONFIDENCE_RAIL_GAP / 2)),
            int(rect.y + rect.height),
            divider,
        )
        rl.draw_rectangle_rounded(
            rl.Rectangle(rail_center_x - 4, track_y, 8, track_height),
            0.95,
            12,
            track_color,
        )

        dot_y = compute_confidence_dot_center_y(
            rail_y=track_y,
            rail_height=track_height,
            dot_radius=dot_radius,
            confidence_value=confidence_value,
        )
        top_color = rl.Color(*top_rgba)
        bottom_color = rl.Color(*bottom_rgba)
        rl.draw_rectangle_gradient_v(
            int(rail_center_x - dot_radius),
            int(dot_y - dot_radius),
            dot_radius * 2,
            dot_radius * 2,
            top_color,
            bottom_color,
        )
        outer_radius = math.ceil(dot_radius * math.sqrt(2)) + 1
        rl.draw_ring(
            rl.Vector2(int(rail_center_x), int(dot_y)),
            dot_radius,
            outer_radius,
            0.0,
            360.0,
            20,
            rl.BLACK,
        )

    def render(self, rect, *, telemetry: FooterTelemetry) -> None:
        import pyray as rl

        panel_bg = rl.Color(5, 12, 18, 255)
        panel_bg_bottom = rl.Color(11, 26, 37, 255)
        divider = rl.Color(255, 255, 255, 28)
        text_dim = rl.Color(255, 255, 255, 150)
        green = rl.Color(94, 214, 135, 255)
        orange = rl.Color(255, 176, 87, 255)
        layout = build_footer_panel_layout(rect)

        rl.draw_rectangle_gradient_v(
            int(rect.x),
            int(rect.y),
            int(rect.width),
            int(rect.height),
            panel_bg,
            panel_bg_bottom,
        )
        rl.draw_line(
            int(rect.x),
            int(rect.y),
            int(rect.x + rect.width),
            int(rect.y),
            divider,
        )

        wheel_size = min(int(rect.height * 0.68), int(rect.width * 0.14))
        wheel_size = max(124, wheel_size)
        wheel_center_x = rect.x + layout.wheel_col_w * 0.76
        wheel_center_y = rect.y + rect.height / 2 + 14
        src_rect = rl.Rectangle(0, 0, self._wheel_texture.width, self._wheel_texture.height)
        dest_rect = rl.Rectangle(wheel_center_x, wheel_center_y, wheel_size, wheel_size)
        origin = (wheel_size / 2, wheel_size / 2)

        rl.draw_texture_pro(self._wheel_texture, src_rect, dest_rect, origin, -telemetry.steering_angle_deg, rl.WHITE)
        self._draw_steering_dots(
            center_x=wheel_center_x,
            center_y=wheel_center_y,
            wheel_size=wheel_size,
            telemetry=telemetry,
        )
        self._draw_blinker_arrows(
            center_x=wheel_center_x,
            center_y=wheel_center_y,
            wheel_size=wheel_size,
            telemetry=telemetry,
        )

        rl.draw_text_ex(
            self._label_font,
            "STEERING",
            rl.Vector2(rect.x + UI_ALT_FOOTER_OUTER_PAD_X, rect.y + UI_ALT_FOOTER_OUTER_PAD_Y),
            22,
            0,
            text_dim,
        )
        self._draw_steering_summary(
            rl.Rectangle(
                rect.x + UI_ALT_FOOTER_OUTER_PAD_X,
                rect.y + UI_ALT_FOOTER_OUTER_PAD_Y + 28,
                layout.wheel_col_w - 90,
                rect.height - (2 * UI_ALT_FOOTER_OUTER_PAD_Y),
            ),
            telemetry=telemetry,
        )
        rl.draw_line(
            int(rect.x + layout.wheel_col_w),
            int(rect.y + UI_ALT_FOOTER_OUTER_PAD_Y),
            int(rect.x + layout.wheel_col_w),
            int(rect.y + rect.height - UI_ALT_FOOTER_OUTER_PAD_Y),
            divider,
        )

        section_title_y = rect.y + UI_ALT_FOOTER_OUTER_PAD_Y
        first_meter_y = section_title_y + 34
        second_meter_y = first_meter_y + 74

        rl.draw_text_ex(self._label_font, "DRIVER", rl.Vector2(layout.driver_col_x, section_title_y), 22, 0, text_dim)
        rl.draw_text_ex(self._label_font, "OPENPILOT", rl.Vector2(layout.op_col_x, section_title_y), 22, 0, text_dim)

        self._draw_meter(
            rl.Rectangle(layout.driver_col_x, first_meter_y, layout.meter_w, 56),
            label="GAS",
            value=telemetry.driver_gas,
            color=green,
            value_text="ON" if telemetry.driver_gas_pressed else "OFF",
            active=telemetry.driver_gas_pressed,
        )
        self._draw_meter(
            rl.Rectangle(layout.driver_col_x, second_meter_y, layout.meter_w, 56),
            label="BRAKE",
            value=telemetry.driver_brake,
            color=orange,
            value_text="ON" if telemetry.driver_brake_pressed else "OFF",
            active=telemetry.driver_brake_pressed,
        )
        self._draw_meter(
            rl.Rectangle(layout.op_col_x, first_meter_y, layout.meter_w, 56),
            label="THROTTLE",
            value=telemetry.op_gas,
            color=green,
            value_text=f"{telemetry.op_gas * 100:.0f}%",
            active=telemetry.op_gas > 0,
        )
        self._draw_meter(
            rl.Rectangle(layout.op_col_x, second_meter_y, layout.meter_w, 56),
            label="BRAKE",
            value=telemetry.op_brake,
            color=orange,
            value_text=f"{telemetry.op_brake * 100:.0f}%",
            active=telemetry.op_brake > 0,
        )
        self._draw_accel_summary(
            rl.Rectangle(*layout.accel_rect),
            telemetry=telemetry,
        )
        self._draw_confidence_rail(
            rl.Rectangle(*layout.confidence_rect),
            telemetry=telemetry,
        )


def clip(
    route,
    output: str,
    *,
    start: int,
    end: int,
    headless: bool,
    big: bool,
    title: str | None,
    show_metadata: bool,
    show_time: bool,
    use_qcam: bool,
    layout_mode: str,
) -> None:
    import tqdm
    import pyray as rl
    from msgq.visionipc import VisionIpcServer, VisionStreamType
    from openpilot.common.prefix import OpenpilotPrefix
    from openpilot.common.utils import Timer
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.system.ui.lib.application import FontWeight, gui_app

    patch_shader_polygon_gradient_coordinates()

    if big:
        from openpilot.selfdrive.ui.onroad.augmented_road_view import AugmentedRoadView
    else:
        from openpilot.selfdrive.ui.mici.onroad.augmented_road_view import AugmentedRoadView

    timer = Timer()
    duration = end - start
    timer.lap("import")

    logger.info("Clipping %s, %ss-%ss (%ss) with exact frame replay", route.name.canonical_name, start, end, duration)
    seg_start, seg_end = start // 60, (end - 1) // 60 + 1
    messages_by_segment = load_segment_messages(route, seg_start=seg_start, seg_end=seg_end)
    render_steps = build_render_steps(messages_by_segment, seg_start=seg_start, start=start, end=end)
    timer.lap("logs")

    if headless:
        rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)

    with OpenpilotPrefix(shared_download_cache=True):
        metadata = load_route_metadata(route) if show_metadata else None
        camera_paths = route.qcamera_paths() if use_qcam else route.camera_paths()
        wide_camera_paths = [] if use_qcam else route.ecamera_paths()
        wide_paths = wide_camera_paths[seg_start:seg_end] if wide_camera_paths else []
        road_frame_queue = IndexedFrameQueue(
            camera_paths[seg_start:seg_end],
            [step.camera_ref for step in render_steps],
            use_qcam=use_qcam,
        )
        has_wide_stream = bool(wide_paths) and any(step.wide_camera_ref is not None for step in render_steps)
        wide_frame_queue = None
        if has_wide_stream:
            wide_frame_queue = IndexedFrameQueue(
                wide_paths,
                [step.wide_camera_ref for step in render_steps if step.wide_camera_ref is not None],
                use_qcam=False,
            )

        vipc = VisionIpcServer("camerad")
        vipc.create_buffers(VisionStreamType.VISION_STREAM_ROAD, 4, road_frame_queue.frame_w, road_frame_queue.frame_h)
        if wide_frame_queue is not None:
            vipc.create_buffers(VisionStreamType.VISION_STREAM_WIDE_ROAD, 4, wide_frame_queue.frame_w, wide_frame_queue.frame_h)
        vipc.start_listener()

        patch_submaster(render_steps, ui_state)
        footer_height_override = None
        if layout_mode == "alt" and has_wide_stream:
            footer_height_override = compute_ui_alt_footer_height(gui_app.height)
            _configure_gui_app_canvas(
                gui_app,
                width=gui_app.width,
                height=compute_ui_alt_dual_canvas_height(gui_app.height),
            )
        gui_app.init_window("repo-owned clip", fps=FRAMERATE)
        _reapply_hidden_window_flag(headless=headless)

        layout_rects = build_layout_rects(
            width=gui_app.width,
            height=gui_app.height,
            layout_mode=layout_mode,
            show_wide_panel=layout_mode == "alt" and has_wide_stream,
            footer_height_override=footer_height_override,
        )
        road_view = AugmentedRoadView()
        wide_view = None
        if layout_rects.wide_rect is not None:
            road_view = AugmentedRoadView(stream_type=VisionStreamType.VISION_STREAM_ROAD)
            road_view._switch_stream_if_needed = lambda sm: None
            road_view._pm.send = lambda *args, **kwargs: None
            wide_view = AugmentedRoadView(stream_type=VisionStreamType.VISION_STREAM_WIDE_ROAD)
            wide_view._switch_stream_if_needed = lambda sm: None
            wide_view._pm.send = lambda *args, **kwargs: None
        road_view.set_rect(rl.Rectangle(*layout_rects.road_rect))
        if wide_view is not None and layout_rects.wide_rect is not None:
            wide_view.set_rect(rl.Rectangle(*layout_rects.wide_rect))
        font = gui_app.font(FontWeight.NORMAL)
        steering_footer = None
        if layout_rects.footer_rect is not None:
            steering_footer = SteeringFooterRenderer(
                gui_app=gui_app,
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
                camera_ref, frame_bytes = road_frame_queue.get()
                if camera_ref != step.camera_ref:
                    raise RuntimeError(f"Camera frame order mismatch: expected {step.camera_ref}, got {camera_ref}")
                vipc.send(
                    VisionStreamType.VISION_STREAM_ROAD,
                    frame_bytes,
                    camera_ref.route_frame_id,
                    camera_ref.timestamp_sof,
                    camera_ref.timestamp_eof,
                )
                if wide_frame_queue is not None and step.wide_camera_ref is not None:
                    wide_camera_ref, wide_frame_bytes = wide_frame_queue.get()
                    if wide_camera_ref != step.wide_camera_ref:
                        raise RuntimeError(
                            f"Wide camera frame order mismatch: expected {step.wide_camera_ref}, got {wide_camera_ref}"
                        )
                    vipc.send(
                        VisionStreamType.VISION_STREAM_WIDE_ROAD,
                        wide_frame_bytes,
                        wide_camera_ref.route_frame_id,
                        wide_camera_ref.timestamp_sof,
                        wide_camera_ref.timestamp_eof,
                    )
                ui_state.update()
                if should_render:
                    road_view.render()
                    if wide_view is not None:
                        wide_view.render()
                        redraw_ui_alt_dual_view_overlays(road_view, wide_view, step.state)
                        redraw_ui_alt_dual_view_borders(road_view, wide_view, layout_rects)
                        road_label_x, road_label_y = compute_ui_alt_panel_label_position(layout_rects.road_rect)
                        draw_text_box("ROAD", road_label_x, road_label_y, 22, gui_app, font)
                        assert layout_rects.wide_rect is not None
                        wide_label_x, wide_label_y = compute_ui_alt_panel_label_position(layout_rects.wide_rect)
                        draw_text_box("WIDE", wide_label_x, wide_label_y, 22, gui_app, font)
                        rl.draw_line(
                            int(layout_rects.wide_rect[0]),
                            int(layout_rects.wide_rect[1]),
                            int(layout_rects.wide_rect[0] + layout_rects.wide_rect[2]),
                            int(layout_rects.wide_rect[1]),
                            rl.Color(255, 255, 255, 24),
                        )
                    if layout_rects.footer_rect is not None and steering_footer is not None:
                        steering_footer.render(
                            rl.Rectangle(*layout_rects.footer_rect),
                            telemetry=extract_footer_telemetry(step.state),
                        )
                    render_overlays(
                        gui_app,
                        font,
                        big,
                        metadata,
                        title,
                        step.route_seconds,
                        show_metadata,
                        show_time,
                    )
                frame_idx += 1
                progress.update(1)
                now = time.perf_counter()
                if frame_idx == len(render_steps) or now - last_log_at >= 5.0:
                    total_elapsed = max(now - render_started_at, 1e-6)
                    interval_elapsed = max(now - last_log_at, 1e-6)
                    avg_fps = frame_idx / total_elapsed
                    interval_fps = (frame_idx - last_log_frame_idx) / interval_elapsed
                    emit_runtime_log(
                        f"Render progress: {frame_idx}/{len(render_steps)} frames, "
                        f"avg {avg_fps:.2f} fps, recent {interval_fps:.2f} fps, "
                        f"route {step.route_seconds:.2f}s"
                    )
                    last_log_at = now
                    last_log_frame_idx = frame_idx
        timer.lap("render")

        road_frame_queue.stop()
        if wide_frame_queue is not None:
            wide_frame_queue.stop()
        gui_app.close()
        timer.lap("ffmpeg")

    logger.info("Clip saved to: %s", Path(output).resolve())
    if frame_idx:
        render_seconds = max(getattr(timer, "_sections", {}).get("render", 0.0), 1e-6)
        emit_runtime_log(
            "Render stats: "
            f"frames={frame_idx}, render_seconds={render_seconds:.2f}, avg_fps={frame_idx / render_seconds:.2f}"
        )
    logger.info("Generated %s", timer.fmt(duration))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s\t%(message)s", force=True)
    args = parse_args()
    openpilot_dir = Path(args.openpilot_dir).resolve()
    os.chdir(openpilot_dir)
    _add_openpilot_to_sys_path(openpilot_dir)

    headless = not args.windowed
    setup_env(args.output, big=args.big, target_mb=args.file_size, duration=args.end - args.start, headless=headless)

    from openpilot.tools.lib.route import Route

    clip(
        Route(args.route, data_dir=args.data_dir),
        args.output,
        start=args.start,
        end=args.end,
        headless=headless,
        big=args.big,
        title=args.title,
        show_metadata=not args.no_metadata,
        show_time=not args.no_time_overlay,
        use_qcam=args.qcam,
        layout_mode=args.layout_mode,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
