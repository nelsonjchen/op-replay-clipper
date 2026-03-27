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
    _compute_ui_render_window,
    _configure_ui_recording_encoder,
    _ensure_fonts,
    _has_modern_openpilot,
    _openpilot_python_cmd,
    _run,
    _trim_mp4_in_place,
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


@dataclass(frozen=True)
class DriverDebugRenderResult:
    output_path: Path


def render_driver_debug_clip(opts: DriverDebugRenderOptions) -> DriverDebugRenderResult:
    openpilot_dir = Path(opts.openpilot_dir).resolve()
    if not _has_modern_openpilot(openpilot_dir):
        raise FileNotFoundError(f"Modern clip tool not found at {openpilot_dir}/tools/clip/run.py")

    patch_report = apply_openpilot_runtime_patches(openpilot_dir)
    if patch_report.changed:
        print(f"Applied openpilot runtime patches: {patch_report}")
    _ensure_fonts(openpilot_dir)

    env = configure_ui_environment()
    recording_acceleration = _configure_ui_recording_encoder(env, opts.file_format)
    print(f"Driver debug recording encoder: {env['RECORD_CODEC']} ({recording_acceleration})")

    smear_seconds = max(0, opts.smear_seconds)
    render_start, render_end, warmup_seconds, trim_front = _compute_ui_render_window(
        start_seconds=opts.start_seconds,
        length_seconds=opts.length_seconds,
        smear_seconds=smear_seconds,
    )
    if warmup_seconds > 0:
        env["RECORD_SKIP_FRAMES"] = str(warmup_seconds * UI_FRAMERATE)

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
    _trim_mp4_in_place(output_path, trim_front)
    return DriverDebugRenderResult(output_path=output_path)
