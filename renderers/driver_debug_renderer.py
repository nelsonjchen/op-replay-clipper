from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

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
    if not opts.headless:
        clip_cmd.append("--windowed")

    use_headless_display = opts.headless and os.name != "nt" and "DISPLAY" not in env
    with tempfile.TemporaryDirectory(prefix="driver-debug-params-") as params_root:
        env["PARAMS_ROOT"] = params_root
        with temporary_headless_display(env, enabled=use_headless_display) as render_env:
            _run(clip_cmd, cwd=openpilot_dir, env=render_env)

    output_path = Path(opts.output_path).resolve()
    return DriverDebugRenderResult(output_path=output_path)
