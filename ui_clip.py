from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from openpilot_defaults import default_image_openpilot_root
from openpilot_compat import (
    build_openpilot_compatible_data_dir,
    patch_openpilot_framereader_compat,
)
from runtime_env import configure_ui_environment, temporary_headless_display

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
    _ensure_fonts(openpilot_dir)

    env = configure_ui_environment()
    render_start = max(0, opts.start_seconds - max(0, opts.smear_seconds))
    render_end = opts.start_seconds + opts.length_seconds
    trim_front = opts.start_seconds - render_start

    clip_cmd = [
        *_openpilot_python_cmd(openpilot_dir),
        str((Path(__file__).resolve().parent / "forked_openpilot_clip.py").resolve()),
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

    use_headless_display = opts.headless and os.name != "nt" and "DISPLAY" not in env and shutil.which("Xtigervnc") is not None
    with temporary_headless_display(env, enabled=use_headless_display) as render_env:
        _run(clip_cmd, cwd=openpilot_dir, env=render_env)

    output_path = Path(opts.output_path).resolve()
    _trim_mp4_in_place(output_path, trim_front)
    return UIRenderResult(output_path=output_path)
