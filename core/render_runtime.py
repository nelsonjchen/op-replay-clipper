from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _ffmpeg_hwaccels() -> frozenset[str]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-hwaccels"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return frozenset()
    hwaccels: set[str] = set()
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if stripped and stripped != "Hardware acceleration methods:":
            hwaccels.add(stripped)
    return frozenset(hwaccels)


def configure_ui_environment(
    base_env: dict[str, str] | None = None,
    *,
    acceleration: str = "auto",
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    if platform.system() == "Darwin":
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        if acceleration == "cpu":
            env.setdefault("FFMPEG_HWACCEL", "none")
        elif "videotoolbox" in _ffmpeg_hwaccels():
            env.setdefault("FFMPEG_HWACCEL", "videotoolbox")
        else:
            env.setdefault("FFMPEG_HWACCEL", "auto")
    env.setdefault("SCALE", "1")
    if platform.system() == "Linux" and "DISPLAY" not in env:
        env.setdefault("OPENPILOT_UI_NULL_EGL", "1")
    return env


def _can_use_xorg() -> bool:
    return platform.system() == "Linux" and shutil.which("Xorg") is not None


def _has_nvidia_egl() -> bool:
    if platform.system() != "Linux":
        return False
    return shutil.which("nvidia-smi") is not None


def _xorg_command(display: str, log_path: Path) -> list[str]:
    cmd = [
        "Xorg",
        display,
        "-noreset",
        "-logfile",
        str(log_path),
    ]
    if os.geteuid() == 0:
        return cmd
    if shutil.which("sudo") is not None:
        return ["sudo", *cmd]
    raise RuntimeError("Headless NVIDIA rendering requires Xorg and root access")


def _log_gl_renderer(env: dict[str, str]) -> None:
    if shutil.which("glxinfo") is None:
        print("GL probe skipped: glxinfo not installed", file=sys.stderr, flush=True)
        return

    result = subprocess.run(
        ["glxinfo", "-B"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        print(f"GL probe failed: {detail}", file=sys.stderr, flush=True)
        return

    wanted_prefixes = (
        "OpenGL vendor string:",
        "OpenGL renderer string:",
        "OpenGL core profile version string:",
        "direct rendering:",
    )
    summary = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith(wanted_prefixes)
    ]
    if summary:
        print("GL probe:", file=sys.stderr, flush=True)
        for line in summary:
            print(f"  {line}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def _temporary_null_egl_environment(env: dict[str, str]):
    render_env = env.copy()
    runtime_dir = Path(tempfile.mkdtemp(prefix="null-egl-runtime-"))
    vendor_json = runtime_dir / "10_nvidia.json"
    vendor_json.write_text(
        '{\n  "file_format_version": "1.0.0",\n  "ICD": {"library_path": "libEGL_nvidia.so.0"}\n}\n'
    )
    render_env["OPENPILOT_UI_NULL_EGL"] = "1"
    render_env["EGL_PLATFORM"] = "surfaceless"
    render_env["__EGL_VENDOR_LIBRARY_FILENAMES"] = str(vendor_json)
    render_env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    render_env.pop("DISPLAY", None)
    try:
        yield render_env
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)


@contextlib.contextmanager
def _temporary_xorg_display(env: dict[str, str]):
    render_env = env.copy()
    render_env.setdefault("DISPLAY", ":0")
    render_env.setdefault("SCALE", "1")

    display_num = render_env["DISPLAY"].lstrip(":")
    socket_path = Path(f"/tmp/.X11-unix/X{display_num}")
    lock_path = Path(f"/tmp/.X{display_num}-lock")

    with tempfile.NamedTemporaryFile(prefix="xorg-", suffix=".log", delete=False) as log_file:
        log_path = Path(log_file.name)

    subprocess.run(["rm", "-f", str(lock_path), str(socket_path)], check=False)

    log_handle = Path(f"{log_path}.stdout").open("wb")
    proc = subprocess.Popen(
        _xorg_command(render_env["DISPLAY"], log_path),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=render_env,
    )
    try:
        for _ in range(80):
            if proc.poll() is not None:
                log_tail = log_path.read_text(errors="replace") if log_path.exists() else ""
                raise RuntimeError(f"Xorg exited before startup:\n{log_tail}")
            if socket_path.exists():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f"Xorg did not create {render_env['DISPLAY']} in time")
        _log_gl_renderer(render_env)
        yield render_env
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log_handle.close()
        for cleanup_path in (log_path, Path(f"{log_path}.stdout")):
            try:
                cleanup_path.unlink(missing_ok=True)
            except PermissionError:
                pass


@contextlib.contextmanager
def temporary_headless_display(env: dict[str, str], enabled: bool):
    if not enabled:
        yield env
        return

    if env.get("OPENPILOT_UI_NULL_EGL") == "1" and _has_nvidia_egl():
        with _temporary_null_egl_environment(env) as render_env:
            yield render_env
        return

    if _can_use_xorg():
        with _temporary_xorg_display(env) as render_env:
            yield render_env
        return
    raise RuntimeError("Headless UI rendering on Linux requires Xorg")
