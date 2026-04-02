from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from core.driver_face_swap import DriverFaceSwapOptions, has_driver_face_anonymization, render_anonymized_driver_backing_video
from core.openpilot_config import default_image_openpilot_root
from core.openpilot_integration import (
    apply_openpilot_runtime_patches,
    build_openpilot_compatible_data_dir,
)
from core.render_runtime import configure_ui_environment, temporary_headless_display
from renderers.ui_renderer import (
    UI_FRAMERATE,
    UIRecordingAcceleration,
    _compute_ui_render_window,
    _configure_ui_recording_encoder,
    _ensure_fonts,
    _has_modern_openpilot,
    _openpilot_python_cmd,
    _run,
)


@dataclass(frozen=True)
class DriverDebugRenderOptions:
    route: str
    route_or_url: str
    start_seconds: int
    length_seconds: int
    smear_seconds: int
    target_mb: int
    file_format: str
    output_path: str
    data_dir: str | None = None
    jwt_token: str | None = None
    openpilot_dir: str = field(default_factory=default_image_openpilot_root)
    headless: bool = True
    acceleration: UIRecordingAcceleration = "auto"
    driver_face_swap: DriverFaceSwapOptions = field(default_factory=DriverFaceSwapOptions)


@dataclass(frozen=True)
class DriverDebugRenderResult:
    output_path: Path


def _driver_debug_recording_skip_seconds(*, start_seconds: int, render_start: int) -> int:
    return max(0, start_seconds - render_start)


def render_driver_debug_clip(opts: DriverDebugRenderOptions) -> DriverDebugRenderResult:
    openpilot_dir = Path(opts.openpilot_dir).resolve()
    if not _has_modern_openpilot(openpilot_dir):
        raise FileNotFoundError(f"Modern clip tool not found at {openpilot_dir}/tools/clip/run.py")

    patch_report = apply_openpilot_runtime_patches(openpilot_dir)
    if patch_report.changed:
        print(f"Applied openpilot runtime patches: {patch_report}")
    _ensure_fonts(openpilot_dir)

    env = configure_ui_environment(acceleration=opts.acceleration)
    recording_acceleration = _configure_ui_recording_encoder(env, opts.file_format, opts.acceleration)
    print(f"Driver debug recording encoder: {env['RECORD_CODEC']} ({recording_acceleration})")

    smear_seconds = max(0, opts.smear_seconds)
    render_start, render_end, _warmup_seconds, _trim_front = _compute_ui_render_window(
        start_seconds=opts.start_seconds,
        length_seconds=opts.length_seconds,
        smear_seconds=smear_seconds,
    )
    recording_skip_seconds = _driver_debug_recording_skip_seconds(
        start_seconds=opts.start_seconds,
        render_start=render_start,
    )
    if recording_skip_seconds > 0:
        env["RECORD_SKIP_FRAMES"] = str(recording_skip_seconds * UI_FRAMERATE)

    use_headless_display = opts.headless and os.name != "nt" and "DISPLAY" not in env
    with tempfile.TemporaryDirectory(prefix="driver-debug-params-") as params_root, tempfile.TemporaryDirectory(
        prefix="driver-debug-backing-"
    ) as backing_root:
        env["PARAMS_ROOT"] = params_root
        backing_video_path: Path | None = None
        backing_selection_report_path: Path | None = None
        if has_driver_face_anonymization(opts.driver_face_swap):
            if not opts.data_dir:
                raise ValueError("Driver face anonymization for driver-debug requires a local data_dir.")
            backing_output_path = Path(backing_root) / "driver-debug-backing.mp4"
            backing_video_path = render_anonymized_driver_backing_video(
                route=opts.route,
                route_or_url=opts.route_or_url,
                start_seconds=render_start,
                length_seconds=render_end - render_start,
                data_dir=opts.data_dir,
                openpilot_dir=str(openpilot_dir),
                acceleration=opts.acceleration,
                output_path=str(backing_output_path),
                options=opts.driver_face_swap,
                jwt_token=opts.jwt_token,
            )
            candidate_selection_report_path = backing_output_path.with_name(
                f"{backing_output_path.stem}.driver-face-selection.json"
            )
            if candidate_selection_report_path.exists():
                backing_selection_report_path = candidate_selection_report_path

        clip_cmd = [
            *_openpilot_python_cmd(openpilot_dir),
            str((Path(__file__).resolve().parent / "driver_debug_engine.py").resolve()),
            opts.route.replace("|", "/"),
            "--openpilot-dir",
            str(openpilot_dir),
            "-s",
            str(render_start),
            "-e",
            str(render_end),
            "-o",
            str(Path(opts.output_path).resolve()),
            "-f",
            str(opts.target_mb),
        ]
        if opts.data_dir:
            compat_root = build_openpilot_compatible_data_dir(opts.route, Path(opts.data_dir))
            clip_cmd += ["-d", str(compat_root)]
        if backing_video_path is not None:
            clip_cmd += ["--backing-video", str(backing_video_path)]
        if not opts.headless:
            clip_cmd.append("--windowed")

        with temporary_headless_display(env, enabled=use_headless_display) as render_env:
            _run(clip_cmd, cwd=openpilot_dir, env=render_env)

        output_path = Path(opts.output_path).resolve()
        if backing_selection_report_path is not None and backing_selection_report_path.exists():
            final_selection_report_path = output_path.with_name(f"{output_path.stem}.driver-face-selection.json")
            shutil.copy2(backing_selection_report_path, final_selection_report_path)

    output_path = Path(opts.output_path).resolve()
    return DriverDebugRenderResult(output_path=output_path)
