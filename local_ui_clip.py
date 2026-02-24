#!/usr/bin/env python3
"""
Render a local openpilot UI clip MP4 using upstream openpilot's modern tools/clip/run.py.

This keeps the repo's route parsing + segment downloading flow, but replaces the older
tmux/x11grab replay wrapper with the current openpilot clip renderer.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
from pathlib import Path

MIN_LENGTH_SECONDS = 1
MAX_LENGTH_SECONDS = 300
DEMO_ROUTE = "a2a0ccea32023010|2023-07-27--13-01-19"
DEMO_START_SECONDS = 90
DEMO_END_SECONDS = 105


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def ensure_openpilot_checkout(openpilot_dir: Path, branch: str = "master") -> None:
    if not openpilot_dir.exists():
        openpilot_dir.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--recurse-submodules",
                "--branch",
                branch,
                "https://github.com/commaai/openpilot.git",
                str(openpilot_dir),
            ]
        )
        return

    run(["git", "fetch", "origin", branch, "--depth", "1"], cwd=openpilot_dir)
    run(["git", "checkout", branch], cwd=openpilot_dir)
    run(["git", "pull", "--ff-only", "--recurse-submodules", "origin", branch], cwd=openpilot_dir)
    run(["git", "submodule", "update", "--init", "--recursive"], cwd=openpilot_dir)


def ensure_macos_env_fix(openpilot_dir: Path) -> None:
    if platform.system() != "Darwin":
        return

    env_file = openpilot_dir / ".env"
    line = "export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES"
    existing = env_file.read_text() if env_file.exists() else ""
    if line not in existing:
        with env_file.open("a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"{line}\n")


def bootstrap_openpilot(openpilot_dir: Path) -> None:
    # Matches upstream tools/install_python_dependencies.sh behavior more closely than plain `uv sync`.
    run(["uv", "sync", "--frozen", "--all-extras"], cwd=openpilot_dir)
    ensure_macos_env_fix(openpilot_dir)

    # Native modules required by tools/clip/run.py on desktop environments.
    scons_targets = [
        "msgq_repo/msgq/ipc_pyx.so",
        "msgq_repo/msgq/visionipc/visionipc_pyx.so",
        "common/params_pyx.so",
        "selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so",
        "selfdrive/controls/lib/lateral_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so",
    ]
    run(["uv", "run", "scons", "-j8", *scons_targets], cwd=openpilot_dir)


def ensure_openpilot_ui_fonts(openpilot_dir: Path) -> None:
    fonts_dir = openpilot_dir / "openpilot/selfdrive/assets/fonts"
    needed = [
        "Inter-Light.fnt",
        "Inter-Medium.fnt",
        "Inter-Bold.fnt",
        "Inter-SemiBold.fnt",
        "Inter-Regular.fnt",
        "unifont.fnt",
    ]
    if all((fonts_dir / f).exists() for f in needed):
        return
    run(["uv", "run", "python", "selfdrive/assets/fonts/process.py"], cwd=openpilot_dir)


def patch_openpilot_local_ffprobe(openpilot_dir: Path) -> None:
    """
    Work around upstream ffprobe sniffing only 4KB via stdin.

    Some local fcamera.hevc files are valid (system ffprobe can read them) but fail the 4KB
    stdin probe path. For local files, let ffprobe open the path directly.
    """
    framereader = openpilot_dir / "openpilot/tools/lib/framereader.py"
    if not framereader.exists():
        return

    src = framereader.read_text()
    modified = False

    if "import os" not in src:
        src = src.replace("import json\n", "import json\nimport os\n", 1)
        modified = True

    if "os.path.exists(fn)" not in src:
        old = """  cmd += ["-i", "-"]\n\n  try:\n    with FileReader(fn) as f:\n      ffprobe_output = subprocess.check_output(cmd, input=f.read(4096))\n"""
        new = """  local_cmd = list(cmd)\n  local_cmd += ["-i", fn]\n  cmd += ["-i", "-"]\n\n  try:\n    if os.path.exists(fn):\n      ffprobe_output = subprocess.check_output(local_cmd)\n    else:\n      with FileReader(fn) as f:\n        ffprobe_output = subprocess.check_output(cmd, input=f.read(4096))\n"""
        if old in src:
            src = src.replace(old, new, 1)
            modified = True
        else:
            print("warning: framereader.py layout changed, skipping local ffprobe compatibility patch")

    hw_old = 'def decompress_video_data(rawdat, w, h, pix_fmt="rgb24", vid_fmt=\'hevc\', hwaccel="auto", loglevel="info") -> np.ndarray:\n  threads = os.getenv("FFMPEG_THREADS", "0")\n'
    hw_new = 'def decompress_video_data(rawdat, w, h, pix_fmt="rgb24", vid_fmt=\'hevc\', hwaccel="auto", loglevel="info") -> np.ndarray:\n  threads = os.getenv("FFMPEG_THREADS", "0")\n  hwaccel = os.getenv("FFMPEG_HWACCEL", hwaccel)\n'
    if 'os.getenv("FFMPEG_HWACCEL"' not in src and hw_old in src:
        src = src.replace(hw_old, hw_new, 1)
        modified = True

    if '"-i", "-",' in src:
        src = src.replace('"-i", "-",', '"-i", "pipe:0",')
        modified = True
    if 'cmd += ["-i", "-"]' in src:
        src = src.replace('cmd += ["-i", "-"]', 'cmd += ["-i", "pipe:0"]')
        modified = True

    if modified:
        framereader.write_text(src)


def patch_openpilot_clip_qcam_local_decode(openpilot_dir: Path) -> None:
    clip_run = openpilot_dir / "tools/clip/run.py"
    if not clip_run.exists():
        return

    src = clip_run.read_text()
    if 'if os.path.exists(path):\n          result = subprocess.run(["ffmpeg", "-v", "quiet", "-i", path' in src:
        return

    old = """        with FileReader(path) as f:\n          result = subprocess.run([\"ffmpeg\", \"-v\", \"quiet\", \"-i\", \"-\", \"-f\", \"rawvideo\", \"-pix_fmt\", \"nv12\", \"-\"],\n                                  input=f.read(), capture_output=True)\n"""
    new = """        if os.path.exists(path):\n          result = subprocess.run([\"ffmpeg\", \"-v\", \"quiet\", \"-i\", path, \"-f\", \"rawvideo\", \"-pix_fmt\", \"nv12\", \"-\"],\n                                  capture_output=True)\n        else:\n          with FileReader(path) as f:\n            result = subprocess.run([\"ffmpeg\", \"-v\", \"quiet\", \"-i\", \"-\", \"-f\", \"rawvideo\", \"-pix_fmt\", \"nv12\", \"-\"],\n                                    input=f.read(), capture_output=True)\n"""
    if old not in src:
        print("warning: tools/clip/run.py layout changed, skipping qcam local decode compatibility patch")
        return
    clip_run.write_text(src.replace(old, new, 1))


def build_openpilot_compatible_data_dir(route: str, downloader_data_dir: Path) -> Path:
    """
    Create a small symlink view that matches openpilot.tools.lib.route local directory layouts.

    Downloader layout here is: <dongle>/<route-date>--<seg>/...
    openpilot expects either:
      - <data_dir>/<dongle|route>/<seg>/...
      - or <data_dir>/<dongle|route--seg>/...
    """
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a local UI clip MP4 using modern upstream openpilot clip tooling."
    )
    parser.add_argument(
        "route",
        nargs="?",
        help=(
            "Comma Connect URL or route id "
            '(e.g. "dongle|route" or "https://connect.comma.ai/...")'
        ),
    )
    parser.add_argument("--demo", action="store_true", help="Use a known public demo route (download locally)")
    parser.add_argument("--start-seconds", type=int, default=50, help="Used only for route-id input")
    parser.add_argument("--length-seconds", type=int, default=20, help="Used only for route-id input")
    parser.add_argument("--jwt-token", default="", help="Optional JWT token for private routes")
    parser.add_argument("--output", default="./shared/local-ui-clip.mp4", help="Output MP4 path")
    parser.add_argument("--openpilot-dir", default="./.cache/openpilot-local", help="Local openpilot checkout path")
    parser.add_argument("--openpilot-branch", default="master", help="openpilot branch to use")
    parser.add_argument("--file-size-mb", type=float, default=9.0, help="Target output size in MB")
    parser.add_argument("--speed", type=int, default=1, help="Render speed multiplier")
    parser.add_argument("--title", default="", help="Optional overlay title")
    parser.add_argument("--big", action="store_true", help="Use big UI render")
    parser.add_argument("--qcam", action="store_true", help="Use qcamera")
    parser.add_argument("--windowed", action="store_true", help="Show render window")
    parser.add_argument("--no-metadata", action="store_true", help="Disable metadata overlay")
    parser.add_argument("--no-time-overlay", action="store_true", help="Disable time overlay")
    parser.add_argument("--skip-openpilot-update", action="store_true", help="Skip clone/update of openpilot")
    parser.add_argument("--skip-openpilot-bootstrap", action="store_true", help="Skip uv sync + native builds")
    parser.add_argument("--skip-download", action="store_true", help="Skip downloading route files")
    args = parser.parse_args()
    if not args.demo and not args.route:
        parser.error("route is required unless --demo is used")
    return args


def main() -> None:
    args = parse_args()
    route = None
    start_seconds = args.start_seconds
    length_seconds = args.length_seconds

    if args.demo:
        route = DEMO_ROUTE
        start_seconds = DEMO_START_SECONDS
        # Allow caller to shorten, but keep default aligned to upstream clip demo.
        if args.length_seconds == 20:
            length_seconds = DEMO_END_SECONDS - DEMO_START_SECONDS
    else:
        import downloader
        import route_or_url

        parsed = route_or_url.parseRouteOrUrl(
            route_or_url=args.route,
            start_seconds=args.start_seconds,
            length_seconds=args.length_seconds,
            jwt_token=args.jwt_token,
        )
        route = parsed.route
        start_seconds = parsed.start_seconds
        length_seconds = parsed.length_seconds

    if length_seconds < MIN_LENGTH_SECONDS or length_seconds > MAX_LENGTH_SECONDS:
        raise ValueError(
            f"length_seconds must be between {MIN_LENGTH_SECONDS} and {MAX_LENGTH_SECONDS}, got {length_seconds}"
        )

    data_dir: Path | None = None
    if route is not None:
        dongle_id = route.split("|")[0]
        data_dir = Path("./shared/data_dir") / dongle_id
    output_path = Path(args.output).expanduser().resolve()
    openpilot_dir = Path(args.openpilot_dir).expanduser().resolve()

    if route is not None and not args.skip_download:
        import downloader

        downloader.downloadSegments(
            data_dir=data_dir,
            route_or_segment=route,
            smear_seconds=0,
            start_seconds=start_seconds,
            length=length_seconds,
            file_types=["qcameras", "logs"] if args.qcam else ["cameras", "logs"],
            jwt_token=args.jwt_token or None,
            decompress_logs=False,
        )

    if not args.skip_openpilot_update:
        ensure_openpilot_checkout(openpilot_dir, branch=args.openpilot_branch)
    if not args.skip_openpilot_bootstrap:
        bootstrap_openpilot(openpilot_dir)
    patch_openpilot_local_ffprobe(openpilot_dir)
    patch_openpilot_clip_qcam_local_decode(openpilot_dir)
    ensure_openpilot_ui_fonts(openpilot_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    clip_cmd = [
        "uv",
        "run",
        "python",
        "tools/clip/run.py",
        "-o",
        str(output_path),
        "-f",
        str(args.file_size_mb),
        "-x",
        str(args.speed),
    ]
    compat_data_dir: Path | None = None
    if not args.demo:
        route_slash = route.replace("|", "/")
    else:
        route_slash = route.replace("|", "/")
    if data_dir is not None:
        compat_data_dir = build_openpilot_compatible_data_dir(route, data_dir)
    clip_cmd += [
        route_slash,
        "-s",
        str(start_seconds),
        "-e",
        str(start_seconds + length_seconds),
        "-d",
        str(compat_data_dir.resolve()),
    ]
    if args.title:
        clip_cmd += ["-t", args.title]
    if args.big:
        clip_cmd.append("--big")
    if args.qcam:
        clip_cmd.append("--qcam")
    if args.windowed:
        clip_cmd.append("--windowed")
    if args.no_metadata:
        clip_cmd.append("--no-metadata")
    if args.no_time_overlay:
        clip_cmd.append("--no-time-overlay")

    env = os.environ.copy()
    if platform.system() == "Darwin":
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        env.setdefault("FFMPEG_HWACCEL", "none")

    run(clip_cmd, cwd=openpilot_dir, env=env)
    print(f"\nWrote clip: {output_path}")


if __name__ == "__main__":
    main()
