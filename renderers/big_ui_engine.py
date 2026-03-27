from __future__ import annotations

import argparse
from collections.abc import Mapping
import logging
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
MODEL_SERVICE = "modelV2"
TEXT_BOX_PADDING_X = 8
TEXT_BOX_PADDING_Y = 4
UI_ALT_FOOTER_MIN_HEIGHT = 220
UI_ALT_FOOTER_MAX_HEIGHT = 320
UI_ALT_FOOTER_HEIGHT_RATIO = 0.25
logger = logging.getLogger("big_ui_engine")


def emit_runtime_log(message: str) -> None:
    print(message, flush=True)


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
    state: dict


@dataclass(frozen=True)
class LayoutRects:
    road_rect: tuple[int, int, int, int]
    footer_rect: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class FooterTelemetry:
    steering_angle_deg: float = 0.0
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


def build_layout_rects(*, width: int, height: int, layout_mode: str) -> LayoutRects:
    if layout_mode == "default":
        return LayoutRects(road_rect=(0, 0, width, height))
    if layout_mode != "alt":
        raise ValueError(f"Unknown layout mode: {layout_mode}")

    footer_height = int(height * UI_ALT_FOOTER_HEIGHT_RATIO)
    footer_height = max(UI_ALT_FOOTER_MIN_HEIGHT, min(UI_ALT_FOOTER_MAX_HEIGHT, footer_height))
    footer_height = min(footer_height, max(1, height - 1))
    road_height = height - footer_height
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


def extract_footer_telemetry(state: Mapping[str, object]) -> FooterTelemetry:
    car_state_msg = state.get("carState")
    car_control_msg = state.get("carControl")
    car_output_msg = state.get("carOutput")
    longitudinal_plan_msg = state.get("longitudinalPlan")

    car_state = getattr(car_state_msg, "carState", None) if car_state_msg is not None else None
    car_control = getattr(car_control_msg, "carControl", None) if car_control_msg is not None else None
    car_output = getattr(car_output_msg, "carOutput", None) if car_output_msg is not None else None
    longitudinal_plan = (
        getattr(longitudinal_plan_msg, "longitudinalPlan", None) if longitudinal_plan_msg is not None else None
    )

    accel_cmd = float(getattr(getattr(car_control, "actuators", None), "accel", 0.0) or 0.0)
    accel_out_attr = getattr(getattr(car_output, "actuatorsOutput", None), "accel", None)
    accel_out = float(accel_out_attr) if accel_out_attr is not None else None

    a_target_attr = getattr(longitudinal_plan, "aTarget", None)
    if a_target_attr is None and longitudinal_plan is not None and len(getattr(longitudinal_plan, "accels", [])):
        a_target_attr = longitudinal_plan.accels[0]

    return FooterTelemetry(
        steering_angle_deg=float(getattr(car_state, "steeringAngleDeg", 0.0) or 0.0),
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


def build_camera_frame_refs(messages_by_segment: list[list]) -> tuple[dict[int, CameraFrameRef], dict[int, CameraFrameRef]]:
    refs_by_frame_id: dict[int, CameraFrameRef] = {}
    refs_by_timestamp: dict[int, CameraFrameRef] = {}

    for segment_index, messages in enumerate(messages_by_segment):
        local_index = 0
        for msg in messages:
            if msg.which() != CAMERA_SERVICE:
                continue
            encode_idx = msg.roadEncodeIdx
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

    if not refs_by_frame_id:
        raise RuntimeError("No roadEncodeIdx messages were found for the requested route window")
    return refs_by_frame_id, refs_by_timestamp


def _route_seconds_for_frame(frame_id: int) -> float:
    return frame_id / FRAMERATE


def build_render_steps(messages_by_segment: list[list], *, seg_start: int, start: int, end: int) -> list[RenderStep]:
    refs_by_frame_id, refs_by_timestamp = build_camera_frame_refs(messages_by_segment)
    ordered_messages = [msg for segment in messages_by_segment for msg in segment]

    current_state: dict = {}
    render_steps: list[RenderStep] = []
    for msg in ordered_messages:
        which = msg.which()
        current_state[which] = msg

        if which != MODEL_SERVICE:
            continue

        model = msg.modelV2
        camera_ref = refs_by_frame_id.get(int(model.frameId))
        if camera_ref is None and hasattr(model, "timestampEof"):
            camera_ref = refs_by_timestamp.get(int(model.timestampEof))
        if camera_ref is None:
            logger.warning("Skipping model frame %s because no matching camera frame was found", model.frameId)
            continue
        route_seconds = _route_seconds_for_frame(camera_ref.route_frame_id)
        if route_seconds < start or route_seconds >= end:
            continue

        render_steps.append(
            RenderStep(
                route_seconds=route_seconds,
                route_frame_id=int(model.frameId),
                camera_ref=camera_ref,
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
        from openpilot.tools.lib.filereader import FileReader
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
                        if os.path.exists(path):
                            result = os.popen(f"ffmpeg -v quiet -i {path!s} -f rawvideo -pix_fmt nv12 -").buffer.read()
                        else:
                            with FileReader(path) as handle:
                                proc = subprocess.run(
                                    ["ffmpeg", "-v", "quiet", "-i", "-", "-f", "rawvideo", "-pix_fmt", "nv12", "-"],
                                    input=handle.read(),
                                    capture_output=True,
                                    check=True,
                                )
                                result = proc.stdout
                        segment_frames = np.frombuffer(result, dtype=np.uint8).reshape(-1, width * height * 3 // 2)
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


def render_overlays(gui_app, font, big, metadata, title, route_seconds, show_metadata, show_time) -> None:
    from openpilot.system.ui.lib.text_measure import measure_text_cached
    from openpilot.system.ui.lib.wrap_text import wrap_text

    metadata_size = 16 if big else 12
    title_size = 32 if big else 24
    time_size = 24 if big else 16
    time_edge_margin = 10 if big else 6

    time_width = 0
    if show_time:
        time_text = f"{int(route_seconds) // 60:02d}:{int(route_seconds) % 60:02d}"
        time_width = int(measure_text_cached(font, time_text, time_size).x)
        draw_text_box(
            time_text,
            gui_app.width - time_width - TEXT_BOX_PADDING_X - time_edge_margin,
            TEXT_BOX_PADDING_Y + time_edge_margin,
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
        self._label_font = label_font
        self._value_font = value_font
        self._wheel_texture = gui_app.texture("icons_mici/wheel.png", 220, 220)

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

    def render(self, rect, *, telemetry: FooterTelemetry) -> None:
        import pyray as rl

        panel_bg = rl.Color(5, 12, 18, 255)
        panel_bg_bottom = rl.Color(11, 26, 37, 255)
        divider = rl.Color(255, 255, 255, 28)
        text_dim = rl.Color(255, 255, 255, 150)
        green = rl.Color(94, 214, 135, 255)
        orange = rl.Color(255, 176, 87, 255)
        outer_pad_x = 34
        outer_pad_y = 24
        wheel_col_w = rect.width * 0.34
        right_x = rect.x + wheel_col_w + outer_pad_x
        right_w = rect.width - wheel_col_w - (2 * outer_pad_x)
        col_gap = 36
        meter_w = max(120.0, (right_w - col_gap) / 2)
        driver_col_x = right_x
        op_col_x = right_x + meter_w + col_gap

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

        wheel_size = min(int(rect.height * 0.72), int(rect.width * 0.17))
        wheel_size = max(124, wheel_size)
        wheel_center_x = rect.x + wheel_col_w * 0.5
        wheel_center_y = rect.y + rect.height / 2 + 8
        src_rect = rl.Rectangle(0, 0, self._wheel_texture.width, self._wheel_texture.height)
        dest_rect = rl.Rectangle(wheel_center_x, wheel_center_y, wheel_size, wheel_size)
        origin = (wheel_size / 2, wheel_size / 2)

        rl.draw_texture_pro(
            self._wheel_texture,
            src_rect,
            dest_rect,
            origin,
            -telemetry.steering_angle_deg,
            rl.WHITE,
        )

        rl.draw_text_ex(
            self._label_font,
            "STEERING",
            rl.Vector2(rect.x + outer_pad_x, rect.y + outer_pad_y),
            22,
            0,
            text_dim,
        )
        rl.draw_text_ex(
            self._value_font,
            f"{telemetry.steering_angle_deg:+.1f} deg",
            rl.Vector2(rect.x + outer_pad_x, rect.y + rect.height - 70),
            34,
            0,
            rl.WHITE,
        )
        rl.draw_line(
            int(rect.x + wheel_col_w),
            int(rect.y + outer_pad_y),
            int(rect.x + wheel_col_w),
            int(rect.y + rect.height - outer_pad_y),
            divider,
        )

        section_title_y = rect.y + outer_pad_y
        first_meter_y = section_title_y + 34
        second_meter_y = first_meter_y + 74
        accel_summary_y = second_meter_y + 82

        rl.draw_text_ex(self._label_font, "DRIVER", rl.Vector2(driver_col_x, section_title_y), 22, 0, text_dim)
        rl.draw_text_ex(self._label_font, "OPENPILOT", rl.Vector2(op_col_x, section_title_y), 22, 0, text_dim)

        self._draw_meter(
            rl.Rectangle(driver_col_x, first_meter_y, meter_w, 56),
            label="GAS",
            value=telemetry.driver_gas,
            color=green,
            value_text="ON" if telemetry.driver_gas_pressed else "OFF",
            active=telemetry.driver_gas_pressed,
        )
        self._draw_meter(
            rl.Rectangle(driver_col_x, second_meter_y, meter_w, 56),
            label="BRAKE",
            value=telemetry.driver_brake,
            color=orange,
            value_text="ON" if telemetry.driver_brake_pressed else "OFF",
            active=telemetry.driver_brake_pressed,
        )
        self._draw_meter(
            rl.Rectangle(op_col_x, first_meter_y, meter_w, 56),
            label="THROTTLE",
            value=telemetry.op_gas,
            color=green,
            value_text=f"{telemetry.op_gas * 100:.0f}%",
            active=telemetry.op_gas > 0,
        )
        self._draw_meter(
            rl.Rectangle(op_col_x, second_meter_y, meter_w, 56),
            label="BRAKE",
            value=telemetry.op_brake,
            color=orange,
            value_text=f"{telemetry.op_brake * 100:.0f}%",
            active=telemetry.op_brake > 0,
        )
        self._draw_accel_summary(
            rl.Rectangle(right_x, accel_summary_y, right_w, 54),
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
        frame_queue = IndexedFrameQueue(camera_paths[seg_start:seg_end], [step.camera_ref for step in render_steps], use_qcam=use_qcam)

        vipc = VisionIpcServer("camerad")
        vipc.create_buffers(VisionStreamType.VISION_STREAM_ROAD, 4, frame_queue.frame_w, frame_queue.frame_h)
        vipc.start_listener()

        patch_submaster(render_steps, ui_state)
        gui_app.init_window("repo-owned clip", fps=FRAMERATE)

        road_view = AugmentedRoadView()
        layout_rects = build_layout_rects(width=gui_app.width, height=gui_app.height, layout_mode=layout_mode)
        road_view.set_rect(rl.Rectangle(*layout_rects.road_rect))
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
                camera_ref, frame_bytes = frame_queue.get()
                if camera_ref != step.camera_ref:
                    raise RuntimeError(f"Camera frame order mismatch: expected {step.camera_ref}, got {camera_ref}")
                vipc.send(
                    VisionStreamType.VISION_STREAM_ROAD,
                    frame_bytes,
                    camera_ref.route_frame_id,
                    camera_ref.timestamp_sof,
                    camera_ref.timestamp_eof,
                )
                ui_state.update()
                if should_render:
                    road_view.render()
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

        frame_queue.stop()
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
