from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


UIBackend = Literal["auto", "modern", "legacy"]
UIMode = Literal["auto", "c3", "c3x", "big", "c4"]


@dataclass
class UIRenderOptions:
    route: str
    start_seconds: int
    length_seconds: int
    smear_seconds: int
    target_mb: int
    file_format: str
    speedhack_ratio: float
    metric: bool
    output_path: str
    data_dir: str | None = None
    jwt_token: str | None = None
    openpilot_dir: str = "/home/batman/openpilot"
    backend: UIBackend = "auto"
    ui_mode: UIMode = "auto"
    headless: bool = True


def _run(cmd: list[str], cwd: str | Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def _has_modern_openpilot(openpilot_dir: Path) -> bool:
    return (openpilot_dir / "tools/clip/run.py").exists()


def _has_legacy_clip_script() -> bool:
    return Path("./clip.sh").exists()


def _choose_backend(opts: UIRenderOptions) -> UIBackend:
    if opts.backend != "auto":
        return opts.backend
    if _has_modern_openpilot(Path(opts.openpilot_dir)):
        return "modern"
    return "legacy"


def _ui_mode_to_modern_flags(ui_mode: UIMode) -> list[str]:
    # openpilot tools/clip/run.py exposes only --big; default path is the current "mici"/C4 style.
    if ui_mode in ("c3", "c3x", "big"):
        return ["--big"]
    return []


def _openpilot_python_cmd(openpilot_dir: Path) -> list[str]:
    venv_python = openpilot_dir / ".venv/bin/python"
    if venv_python.exists():
        return [str(venv_python)]
    return ["uv", "run", "python"]


def _build_openpilot_compatible_data_dir(route: str, downloader_data_dir: Path) -> Path:
    route_date = route.split("|", 1)[1]
    compat_root = Path("./shared/openpilot_data_dir").resolve()
    route_root = compat_root / route
    route_root.mkdir(parents=True, exist_ok=True)

    seg_pattern = re.compile(rf"^{re.escape(route_date)}--(\d+)$")
    for entry in downloader_data_dir.iterdir():
        if not entry.is_dir():
            continue
        m = seg_pattern.match(entry.name)
        if not m:
            continue
        seg_dir = route_root / m.group(1)
        if seg_dir.exists() or seg_dir.is_symlink():
            if seg_dir.is_symlink() and seg_dir.resolve() == entry.resolve():
                continue
            if seg_dir.is_symlink() or seg_dir.is_file():
                seg_dir.unlink()
            else:
                continue
        seg_dir.symlink_to(entry.resolve(), target_is_directory=True)
    return compat_root


def _patch_openpilot_framereader_compat(openpilot_dir: Path) -> None:
    framereader = openpilot_dir / "tools/lib/framereader.py"
    if not framereader.exists():
        framereader = openpilot_dir / "openpilot/tools/lib/framereader.py"
    if not framereader.exists():
        return

    src = framereader.read_text()
    modified = False

    if '"-i", "-",' in src:
        src = src.replace('"-i", "-",', '"-i", "pipe:0",')
        modified = True
    if 'cmd += ["-i", "-"]' in src:
        src = src.replace('cmd += ["-i", "-"]', 'cmd += ["-i", "pipe:0"]')
        modified = True
    if 'os.getenv("FFMPEG_HWACCEL"' not in src:
        old = '  threads = os.getenv("FFMPEG_THREADS", "0")\n'
        new = '  threads = os.getenv("FFMPEG_THREADS", "0")\n  hwaccel = os.getenv("FFMPEG_HWACCEL", hwaccel)\n'
        if old in src:
            src = src.replace(old, new, 1)
            modified = True
    if "os.path.exists(fn)" not in src and "def ffprobe(fn, fmt=None):" in src:
        old = """  if fmt:\n    cmd += ["-f", fmt]\n  cmd += ["-i", "pipe:0"]\n\n  try:\n    with FileReader(fn) as f:\n      ffprobe_output = subprocess.check_output(cmd, input=f.read(4096))\n"""
        new = """  if fmt:\n    cmd += ["-f", fmt]\n  local_cmd = list(cmd)\n  local_cmd += ["-i", fn]\n  cmd += ["-i", "pipe:0"]\n\n  try:\n    if os.path.exists(fn):\n      ffprobe_output = subprocess.check_output(local_cmd)\n    else:\n      with FileReader(fn) as f:\n        ffprobe_output = subprocess.check_output(cmd, input=f.read(4096))\n"""
        if old in src:
            src = src.replace(old, new, 1)
            modified = True

    if modified:
        framereader.write_text(src)


def _patch_openpilot_qcam_local_decode(openpilot_dir: Path) -> None:
    clip_run = openpilot_dir / "tools/clip/run.py"
    if not clip_run.exists():
        return
    src = clip_run.read_text()
    needle = 'result = subprocess.run(["ffmpeg", "-v", "quiet", "-i", "-", "-f", "rawvideo", "-pix_fmt", "nv12", "-"],'
    if needle not in src or "if os.path.exists(path):" in src:
        return
    old = """        with FileReader(path) as f:\n          result = subprocess.run(["ffmpeg", "-v", "quiet", "-i", "-", "-f", "rawvideo", "-pix_fmt", "nv12", "-"],\n                                  input=f.read(), capture_output=True)\n"""
    new = """        if os.path.exists(path):\n          result = subprocess.run(["ffmpeg", "-v", "quiet", "-i", path, "-f", "rawvideo", "-pix_fmt", "nv12", "-"],\n                                  capture_output=True)\n        else:\n          with FileReader(path) as f:\n            result = subprocess.run(["ffmpeg", "-v", "quiet", "-i", "-", "-f", "rawvideo", "-pix_fmt", "nv12", "-"],\n                                    input=f.read(), capture_output=True)\n"""
    if old in src:
        clip_run.write_text(src.replace(old, new, 1))


def _ensure_fonts(openpilot_dir: Path) -> None:
    fonts_dir = None
    for p in [
        openpilot_dir / "selfdrive/assets/fonts",
        openpilot_dir / "openpilot/selfdrive/assets/fonts",
    ]:
        if p.exists():
            fonts_dir = p
            break
    if fonts_dir is None:
        return
    needed = ["Inter-Light.fnt", "Inter-Medium.fnt", "Inter-Bold.fnt", "Inter-SemiBold.fnt", "Inter-Regular.fnt", "unifont.fnt"]
    if all((fonts_dir / f).exists() for f in needed):
        return
    _run([*_openpilot_python_cmd(openpilot_dir), "selfdrive/assets/fonts/process.py"], cwd=openpilot_dir)


def _trim_mp4_in_place(path: Path, trim_start_seconds: int) -> None:
    if trim_start_seconds <= 0:
        return
    tmp = path.with_suffix(".tmp.mp4")
    _run(["ffmpeg", "-y", "-ss", str(trim_start_seconds), "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(tmp)])
    tmp.replace(path)


def _render_modern(opts: UIRenderOptions) -> None:
    openpilot_dir = Path(opts.openpilot_dir).resolve()
    if not _has_modern_openpilot(openpilot_dir):
        raise FileNotFoundError(f"Modern clip tool not found at {openpilot_dir}/tools/clip/run.py")

    _patch_openpilot_framereader_compat(openpilot_dir)
    _patch_openpilot_qcam_local_decode(openpilot_dir)
    _ensure_fonts(openpilot_dir)

    env = os.environ.copy()
    if platform.system() == "Darwin":
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        env.setdefault("FFMPEG_HWACCEL", "none")

    render_start = max(0, opts.start_seconds - max(0, opts.smear_seconds))
    render_end = opts.start_seconds + opts.length_seconds
    trim_front = opts.start_seconds - render_start

    clip_cmd = [
        *_openpilot_python_cmd(openpilot_dir), "tools/clip/run.py",
        opts.route.replace("|", "/"),
        "-s", str(render_start),
        "-e", str(render_end),
        "-o", str(Path(opts.output_path).resolve()),
        "-f", str(opts.target_mb),
        # Upstream tool expects integer speed. Preserve speedhack by clamping.
        "-x", str(max(1, int(round(opts.speedhack_ratio)))),
    ]
    if opts.data_dir:
        compat_root = _build_openpilot_compatible_data_dir(opts.route, Path(opts.data_dir))
        clip_cmd += ["-d", str(compat_root)]
    clip_cmd += _ui_mode_to_modern_flags(opts.ui_mode)
    if not opts.headless:
        clip_cmd.append("--windowed")
    if opts.metric:
        # No direct flag in upstream clip tool currently.
        print("warning: modern backend does not expose metric toggle; ignoring")

    _run(clip_cmd, cwd=openpilot_dir, env=env)
    _trim_mp4_in_place(Path(opts.output_path), trim_front)


def _render_legacy(opts: UIRenderOptions) -> None:
    command = [
        "./clip.sh",
        opts.route,
        f"--start-seconds={opts.start_seconds}",
        f"--length-seconds={opts.length_seconds}",
        f"--smear-amount={opts.smear_seconds}",
        f"--speedhack-ratio={opts.speedhack_ratio}",
        f"--target-mb={opts.target_mb}",
        f"--format={opts.file_format}",
        f"--data-dir={os.path.abspath(opts.data_dir)}" if opts.data_dir else "",
        f"--output={Path(opts.output_path).name}",
    ]
    command = [c for c in command if c]
    if opts.metric:
        command.append("--metric")
    if opts.jwt_token:
        command.append(f"--jwt-token={opts.jwt_token}")
    env = os.environ.copy()
    env.update({"DISPLAY": ":0", "SCALE": "1"})
    if opts.ui_mode in ("c3", "c3x", "big"):
        env["BIG"] = "1"
    elif opts.ui_mode == "c4":
        env.pop("BIG", None)
    _run(command, env=env)

    # clip.sh writes into ./shared by basename; move to requested path if needed
    desired = Path(opts.output_path).resolve()
    default_out = Path("./shared") / Path(opts.output_path).name
    if default_out.resolve() != desired and default_out.exists():
        desired.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(default_out), str(desired))


def render_ui_clip(opts: UIRenderOptions) -> None:
    backend = _choose_backend(opts)
    if backend == "modern":
        try:
            _render_modern(opts)
            return
        except Exception as e:
            if opts.backend == "modern":
                raise
            print(f"warning: modern UI render backend failed, falling back to legacy: {e}")
    if not _has_legacy_clip_script():
        raise RuntimeError("Legacy backend unavailable (missing ./clip.sh) and modern backend failed/unavailable")
    _render_legacy(opts)
