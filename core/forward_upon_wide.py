from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ForwardUponWideHInput = float | Literal["auto"]

DEFAULT_FORWARD_UPON_WIDE_H = 2.2
DEFAULT_FORWARD_UPON_WIDE_SCALE = 1.0 / 4.5


@dataclass(frozen=True)
class CameraConfig:
    width: int
    height: int
    focal_length: float


@dataclass(frozen=True)
class DeviceCameraConfig:
    fcam: CameraConfig
    ecam: CameraConfig


@dataclass(frozen=True)
class LoggedCameraAlignment:
    device_type: str
    road_sensor: str
    wide_sensor: str
    wide_from_device_euler: tuple[float, float, float] | None


@dataclass(frozen=True)
class ForwardUponWideLayout:
    overlay_width: int
    overlay_height: int
    x: int
    y: int
    source: str


@dataclass(frozen=True)
class ForwardUponWideWarp:
    canvas_width: int
    canvas_height: int
    x0: float
    y0: float
    x1: float
    y1: float
    x2: float
    y2: float
    x3: float
    y3: float
    source: str


_AR_OX_CONFIG = DeviceCameraConfig(
    fcam=CameraConfig(1928, 1208, 2648.0),
    ecam=CameraConfig(1928, 1208, 567.0),
)
_OS_CONFIG = DeviceCameraConfig(
    fcam=CameraConfig(2688 // 2, 1520 // 2, 1522.0 * 3 / 4),
    ecam=CameraConfig(2688 // 2, 1520 // 2, 567.0 / 4 * 3),
)

DEVICE_CAMERAS: dict[tuple[str, str], DeviceCameraConfig] = {
    ("unknown", "ar0231"): _AR_OX_CONFIG,
    ("unknown", "ox03c10"): _AR_OX_CONFIG,
    ("pc", "unknown"): _AR_OX_CONFIG,
    ("tici", "unknown"): _AR_OX_CONFIG,
    ("tici", "ar0231"): _AR_OX_CONFIG,
    ("tici", "ox03c10"): _AR_OX_CONFIG,
    ("tizi", "ar0231"): _AR_OX_CONFIG,
    ("tizi", "ox03c10"): _AR_OX_CONFIG,
    ("mici", "ar0231"): _AR_OX_CONFIG,
    ("mici", "ox03c10"): _AR_OX_CONFIG,
    ("tici", "os04c10"): _OS_CONFIG,
    ("tizi", "os04c10"): _OS_CONFIG,
    ("mici", "os04c10"): _OS_CONFIG,
}


def is_auto_forward_upon_wide(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == "auto"


def parse_forward_upon_wide_h(value: str) -> ForwardUponWideHInput:
    if is_auto_forward_upon_wide(value):
        return "auto"
    return float(value)


def _segment_suffix_key(path: Path) -> int:
    try:
        return int(path.name.rsplit("--", 1)[1])
    except (IndexError, ValueError):
        return sys.maxsize


def _route_log_candidates(route: str, data_dir: str | Path | None) -> list[Path]:
    if not data_dir:
        return []

    route_suffix = route.split("|", 1)[1]
    route_root = Path(data_dir)
    candidates: list[Path] = []
    segment_dirs = sorted(route_root.glob(f"{route_suffix}--*"), key=_segment_suffix_key)
    for segment_dir in segment_dirs:
        for candidate in ("qlog.zst", "qlog.bz2", "qlog", "rlog.zst", "rlog.bz2", "rlog"):
            log_path = segment_dir / candidate
            if log_path.exists():
                candidates.append(log_path)
    return candidates


def find_route_log(route: str, data_dir: str | Path | None) -> Path | None:
    candidates = _route_log_candidates(route, data_dir)
    return candidates[0] if candidates else None


def _openpilot_python_cmd(openpilot_dir: Path) -> list[str]:
    venv_python = openpilot_dir / ".venv/bin/python"
    if venv_python.exists():
        return [str(venv_python)]
    return ["uv", "run", "python"]


def inspect_logged_camera_alignment(route: str, *, data_dir: str | Path | None, openpilot_dir: str | Path) -> LoggedCameraAlignment | None:
    log_paths = _route_log_candidates(route, data_dir)
    if not log_paths:
        print("Forward-upon-wide auto: no downloaded rlog found; falling back to manual layout")
        return None

    openpilot_root = Path(openpilot_dir).expanduser().resolve()
    if not openpilot_root.exists():
        print(f"Forward-upon-wide auto: openpilot checkout not found at {openpilot_root}; falling back to manual layout")
        return None

    inspect_script = """
from openpilot.tools.lib.logreader import LogReader
import json
import sys

found = {
    "initData": None,
    "roadCameraState": None,
    "wideRoadCameraState": None,
    "liveCalibration": None,
}

for msg in LogReader(sys.argv[1]):
    which = msg.which()
    if which not in found or found[which] is not None:
        continue
    found[which] = msg.to_dict(verbose=True)[which]
    if all(value is not None for value in found.values()):
        break

init_data = found["initData"] or {}
road_camera = found["roadCameraState"] or {}
wide_camera = found["wideRoadCameraState"] or {}
live_calibration = found["liveCalibration"] or {}

print(json.dumps({
    "device_type": init_data.get("deviceType", "unknown"),
    "road_sensor": road_camera.get("sensor", "unknown"),
    "wide_sensor": wide_camera.get("sensor", "unknown"),
    "wide_from_device_euler": live_calibration.get("wideFromDeviceEuler"),
}))
"""
    for log_path in log_paths:
        proc = subprocess.run(
            [*_openpilot_python_cmd(openpilot_root), "-c", inspect_script, str(log_path)],
            cwd=openpilot_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            print(f"Forward-upon-wide auto: failed to inspect {log_path.name} ({detail}); trying next log source")
            continue

        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as error:
            print(f"Forward-upon-wide auto: malformed inspection output for {log_path.name} ({error}); trying next log source")
            continue

        wide_from_device_euler_raw = payload.get("wide_from_device_euler")
        wide_from_device_euler = None
        if isinstance(wide_from_device_euler_raw, list) and len(wide_from_device_euler_raw) == 3:
            wide_from_device_euler = tuple(float(value) for value in wide_from_device_euler_raw)

        return LoggedCameraAlignment(
            device_type=str(payload.get("device_type") or "unknown"),
            road_sensor=str(payload.get("road_sensor") or "unknown"),
            wide_sensor=str(payload.get("wide_sensor") or "unknown"),
            wide_from_device_euler=wide_from_device_euler,
        )

    print("Forward-upon-wide auto: no usable qlog/rlog source was found; falling back to manual layout")
    return None


def resolve_auto_forward_upon_wide_warp(
    route: str,
    *,
    data_dir: str | Path,
    openpilot_dir: str | Path,
    forward_dimensions: tuple[int, int],
    wide_dimensions: tuple[int, int],
    output_scale: int = 1,
) -> ForwardUponWideWarp | None:
    log_paths = _route_log_candidates(route, data_dir)
    if not log_paths:
        print("Forward-upon-wide auto warp: no downloaded rlog found; falling back to layout mode")
        return None

    openpilot_root = Path(openpilot_dir).expanduser().resolve()
    if not openpilot_root.exists():
        print(f"Forward-upon-wide auto warp: openpilot checkout not found at {openpilot_root}; falling back to layout mode")
        return None

    forward_width = int(forward_dimensions[0] * output_scale)
    forward_height = int(forward_dimensions[1] * output_scale)
    wide_width = int(wide_dimensions[0] * output_scale)
    wide_height = int(wide_dimensions[1] * output_scale)

    inspect_script = """
from openpilot.tools.lib.logreader import LogReader
from openpilot.common.transformations.camera import DEVICE_CAMERAS, view_frame_from_device_frame
from openpilot.common.transformations.orientation import rot_from_euler
import json
import math
import numpy as np
import sys

log_path = sys.argv[1]
forward_width = int(sys.argv[2])
forward_height = int(sys.argv[3])
wide_width = int(sys.argv[4])
wide_height = int(sys.argv[5])

init_data = None
road_camera = None
wide_camera = None
live_calibration = None

for msg in LogReader(log_path):
    which = msg.which()
    if which == "initData" and init_data is None:
        init_data = msg.initData
    elif which == "roadCameraState" and road_camera is None:
        road_camera = msg.roadCameraState
    elif which == "wideRoadCameraState" and wide_camera is None:
        wide_camera = msg.wideRoadCameraState
    elif which == "liveCalibration" and live_calibration is None:
        live_calibration = msg.liveCalibration
    if init_data is not None and road_camera is not None and wide_camera is not None and live_calibration is not None:
        break

if init_data is None or road_camera is None or wide_camera is None or live_calibration is None:
    raise SystemExit("missing required log messages")

if not hasattr(live_calibration, "wideFromDeviceEuler") or len(live_calibration.wideFromDeviceEuler) != 3:
    raise SystemExit("missing wideFromDeviceEuler")

device_type = str(getattr(init_data, "deviceType", "unknown") or "unknown")
road_sensor = str(getattr(road_camera, "sensor", "unknown") or "unknown")
wide_sensor = str(getattr(wide_camera, "sensor", "unknown") or "unknown")
sensor = wide_sensor if wide_sensor != "unknown" else road_sensor
device_camera = DEVICE_CAMERAS.get((device_type, sensor)) or DEVICE_CAMERAS.get(("unknown", sensor))
if device_camera is None:
    raise SystemExit(f"unsupported device/sensor {device_type}/{sensor}")

wide_from_device = rot_from_euler(live_calibration.wideFromDeviceEuler)
device_from_view = view_frame_from_device_frame.T
wide_view_from_forward_view = view_frame_from_device_frame @ wide_from_device @ device_from_view

def scaled_intrinsics(camera_config, width, height):
    fx = camera_config.focal_length * (width / camera_config.width)
    fy = camera_config.focal_length * (height / camera_config.height)
    return np.array([
        [fx, 0.0, width / 2.0],
        [0.0, fy, height / 2.0],
        [0.0, 0.0, 1.0],
    ])

forward_intrinsics = scaled_intrinsics(device_camera.fcam, forward_width, forward_height)
wide_intrinsics = scaled_intrinsics(device_camera.ecam, wide_width, wide_height)
homography = wide_intrinsics @ wide_view_from_forward_view @ np.linalg.inv(forward_intrinsics)

corners = np.array([
    [0.0, 0.0, 1.0],
    [forward_width - 1.0, 0.0, 1.0],
    [0.0, forward_height - 1.0, 1.0],
    [forward_width - 1.0, forward_height - 1.0, 1.0],
], dtype=float).T
projected = homography @ corners

if np.any(np.abs(projected[2]) < 1e-6):
    raise SystemExit("degenerate homography")

projected_xy = (projected[:2] / projected[2]).T
if not np.isfinite(projected_xy).all():
    raise SystemExit("non-finite projected points")

print(json.dumps({
    "device_type": device_type,
    "sensor": sensor,
    "quad": projected_xy.tolist(),
    "pitch": float(live_calibration.wideFromDeviceEuler[1]),
    "yaw": float(live_calibration.wideFromDeviceEuler[2]),
    "roll": float(live_calibration.wideFromDeviceEuler[0]),
}))
"""

    for log_path in log_paths:
        proc = subprocess.run(
            [
                *_openpilot_python_cmd(openpilot_root),
                "-c",
                inspect_script,
                str(log_path),
                str(forward_width),
                str(forward_height),
                str(wide_width),
                str(wide_height),
            ],
            cwd=openpilot_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            print(f"Forward-upon-wide auto warp: failed to inspect {log_path.name} ({detail}); trying next log source")
            continue

        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as error:
            print(f"Forward-upon-wide auto warp: malformed inspection output for {log_path.name} ({error}); trying next log source")
            continue

        quad = payload.get("quad")
        if not isinstance(quad, list) or len(quad) != 4:
            print(f"Forward-upon-wide auto warp: missing projected quad in {log_path.name}; trying next log source")
            continue

        flattened: list[float] = []
        malformed = False
        for point in quad:
            if not isinstance(point, list) or len(point) != 2:
                malformed = True
                break
            flattened.extend((float(point[0]), float(point[1])))
        if malformed:
            print(f"Forward-upon-wide auto warp: malformed projected quad in {log_path.name}; trying next log source")
            continue

        print(
            "Forward-upon-wide auto warp: "
            f"device={payload.get('device_type', 'unknown')} "
            f"sensor={payload.get('sensor', 'unknown')} "
            f"roll={float(payload.get('roll', 0.0)):.4f}rad "
            f"pitch={float(payload.get('pitch', 0.0)):.4f}rad "
            f"yaw={float(payload.get('yaw', 0.0)):.4f}rad "
            f"quad={quad}"
        )

        return ForwardUponWideWarp(
            canvas_width=wide_width,
            canvas_height=wide_height,
            x0=flattened[0],
            y0=flattened[1],
            x1=flattened[2],
            y1=flattened[3],
            x2=flattened[4],
            y2=flattened[5],
            x3=flattened[6],
            y3=flattened[7],
            source=f"{payload.get('device_type', 'unknown')}/{payload.get('sensor', 'unknown')}",
        )

    print("Forward-upon-wide auto warp: no usable qlog/rlog source was found; falling back to layout mode")
    return None


def _camera_config_for_alignment(alignment: LoggedCameraAlignment) -> DeviceCameraConfig | None:
    sensor = alignment.wide_sensor if alignment.wide_sensor != "unknown" else alignment.road_sensor
    return DEVICE_CAMERAS.get((alignment.device_type, sensor)) or DEVICE_CAMERAS.get(("unknown", sensor))


def _scaled_focal_length(config: CameraConfig, frame_width: int) -> float:
    if config.width <= 0:
        raise ValueError("camera config width must be positive")
    return config.focal_length * (frame_width / config.width)


def resolve_auto_forward_upon_wide_layout(
    route: str,
    *,
    data_dir: str | Path,
    openpilot_dir: str | Path,
    forward_dimensions: tuple[int, int],
    wide_dimensions: tuple[int, int],
    output_scale: int = 1,
) -> ForwardUponWideLayout | None:
    alignment = inspect_logged_camera_alignment(route, data_dir=data_dir, openpilot_dir=openpilot_dir)
    if alignment is None:
        return None

    camera_config = _camera_config_for_alignment(alignment)
    if camera_config is None:
        print(
            "Forward-upon-wide auto: unsupported device/sensor combination "
            f"{alignment.device_type}/{alignment.wide_sensor}; falling back to manual layout"
        )
        return None

    wide_width = wide_dimensions[0] * output_scale
    wide_height = wide_dimensions[1] * output_scale
    forward_width = forward_dimensions[0] * output_scale
    forward_height = forward_dimensions[1] * output_scale

    forward_focal = _scaled_focal_length(camera_config.fcam, forward_width)
    wide_focal = _scaled_focal_length(camera_config.ecam, wide_width)
    overlay_scale = wide_focal / forward_focal

    overlay_width = max(1, int(round(forward_width * overlay_scale)))
    overlay_height = max(1, int(round(forward_height * overlay_scale)))

    relative_pitch = 0.0
    if alignment.wide_from_device_euler is not None:
        relative_pitch = float(alignment.wide_from_device_euler[1])

    # Positive pitch tilts the wide camera downward relative to the forward
    # camera, which visually moves the narrower forward view upward inside the
    # wide frame.
    y_offset = -wide_focal * math.tan(relative_pitch)

    x = max(0, min(wide_width - overlay_width, int(round((wide_width - overlay_width) / 2))))
    y = max(0, min(wide_height - overlay_height, int(round((wide_height - overlay_height) / 2 + y_offset))))

    print(
        "Forward-upon-wide auto: "
        f"device={alignment.device_type} "
        f"sensor={alignment.wide_sensor if alignment.wide_sensor != 'unknown' else alignment.road_sensor} "
        f"pitch={relative_pitch:.4f}rad "
        f"scale={overlay_scale:.4f} "
        f"overlay={overlay_width}x{overlay_height} "
        f"pos=({x},{y})"
    )

    return ForwardUponWideLayout(
        overlay_width=overlay_width,
        overlay_height=overlay_height,
        x=x,
        y=y,
        source=f"{alignment.device_type}/{alignment.wide_sensor if alignment.wide_sensor != 'unknown' else alignment.road_sensor}",
    )
