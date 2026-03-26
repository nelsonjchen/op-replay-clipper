from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from core.openpilot_config import default_image_openpilot_root
from core.openpilot_integration import (
    patch_openpilot_augmented_road_view_fill,
    build_openpilot_compatible_data_dir,
    patch_openpilot_framereader_compat,
    patch_openpilot_ui_record_skip,
)
from core.render_runtime import configure_ui_environment, temporary_headless_display


UI_STARTUP_WARMUP_SECONDS = 1
UI_FRAMERATE = 20

@dataclass(frozen=True)
class UIRenderOptions:
    route: str
    start_seconds: int
    length_seconds: int
    smear_seconds: int
    target_mb: int
    file_format: str
    metric: bool
    output_path: str
    data_dir: str | None = None
    jwt_token: str | None = None
    openpilot_dir: str = field(default_factory=default_image_openpilot_root)
    headless: bool = True


@dataclass(frozen=True)
class UIRenderResult:
    output_path: Path


def _has_nvidia() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    return subprocess.run([nvidia_smi, "-L"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def _configure_ui_recording_encoder(env: dict[str, str], file_format: str) -> str:
    if _has_nvidia():
        env["RECORD_CODEC"] = "h264_nvenc" if file_format == "h264" else "hevc_nvenc"
        env["RECORD_PRESET"] = "p4"
        if file_format == "hevc":
            env["RECORD_TAG"] = "hvc1"
        else:
            env.pop("RECORD_TAG", None)
        return "nvidia"

    env["RECORD_CODEC"] = "libx264" if file_format == "h264" else "libx265"
    env["RECORD_PRESET"] = "veryfast" if file_format == "h264" else "medium"
    if file_format == "hevc":
        env["RECORD_TAG"] = "hvc1"
    else:
        env.pop("RECORD_TAG", None)
    return "cpu"


def _run(cmd: list[str], cwd: str | Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    run_env = None if env is None else dict(env)
    if cwd:
        run_env = dict(run_env or {})
        run_env["PWD"] = str(cwd)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=run_env, check=True)


def _has_modern_openpilot(openpilot_dir: Path) -> bool:
    return (openpilot_dir / "tools/clip/run.py").exists()


def _openpilot_python_cmd(openpilot_dir: Path) -> list[str]:
    venv_python = openpilot_dir / ".venv/bin/python"
    if venv_python.exists():
        return [str(venv_python)]
    return ["uv", "run", "python"]


def _ensure_fonts(openpilot_dir: Path) -> None:
    fonts_dir = None
    for candidate in (
        openpilot_dir / "selfdrive/assets/fonts",
        openpilot_dir / "openpilot/selfdrive/assets/fonts",
    ):
        if candidate.exists():
            fonts_dir = candidate
            break
    if fonts_dir is None:
        return

    needed = (
        "Inter-Light.fnt",
        "Inter-Medium.fnt",
        "Inter-Bold.fnt",
        "Inter-SemiBold.fnt",
        "Inter-Regular.fnt",
        "unifont.fnt",
    )
    if all((fonts_dir / filename).exists() for filename in needed):
        return
    _run([*_openpilot_python_cmd(openpilot_dir), "selfdrive/assets/fonts/process.py"], cwd=openpilot_dir)


def _trim_mp4_in_place(path: Path, trim_start_seconds: int) -> None:
    if trim_start_seconds <= 0:
        return
    tmp = path.with_suffix(".tmp.mp4")
    _run(["ffmpeg", "-y", "-ss", str(trim_start_seconds), "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(tmp)])
    tmp.replace(path)


def render_ui_clip(opts: UIRenderOptions) -> UIRenderResult:
    openpilot_dir = Path(opts.openpilot_dir).resolve()
    if not _has_modern_openpilot(openpilot_dir):
        raise FileNotFoundError(f"Modern clip tool not found at {openpilot_dir}/tools/clip/run.py")

    patch_openpilot_framereader_compat(openpilot_dir)
    patch_openpilot_ui_record_skip(openpilot_dir)
    patch_openpilot_augmented_road_view_fill(openpilot_dir)
    _ensure_fonts(openpilot_dir)

    env = configure_ui_environment()
    recording_acceleration = _configure_ui_recording_encoder(env, opts.file_format)
    print(f"UI recording encoder: {env['RECORD_CODEC']} ({recording_acceleration})")
    smear_seconds = max(0, opts.smear_seconds)
    warmup_seconds = min(UI_STARTUP_WARMUP_SECONDS, max(0, opts.start_seconds - smear_seconds))
    render_start = max(0, opts.start_seconds - smear_seconds - warmup_seconds)
    render_end = opts.start_seconds + opts.length_seconds
    trim_front = smear_seconds
    if warmup_seconds > 0:
        env["RECORD_SKIP_FRAMES"] = str(warmup_seconds * UI_FRAMERATE)

    clip_cmd = [
        *_openpilot_python_cmd(openpilot_dir),
        str((Path(__file__).resolve().parent / "big_ui_engine.py").resolve()),
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
        "--big",
    ]
    if opts.data_dir:
        compat_root = build_openpilot_compatible_data_dir(opts.route, Path(opts.data_dir))
        clip_cmd += ["-d", str(compat_root)]
    if not opts.headless:
        clip_cmd.append("--windowed")
    if opts.metric:
        print("warning: modern BIG UI render does not expose a metric toggle; ignoring")

    use_headless_display = opts.headless and os.name != "nt" and "DISPLAY" not in env
    with temporary_headless_display(env, enabled=use_headless_display) as render_env:
        _run(clip_cmd, cwd=openpilot_dir, env=render_env)

    output_path = Path(opts.output_path).resolve()
    _trim_mp4_in_place(output_path, trim_front)
    return UIRenderResult(output_path=output_path)
