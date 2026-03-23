from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def configure_ui_environment(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    if platform.system() == "Darwin":
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        env.setdefault("FFMPEG_HWACCEL", "none")
    return env


@contextlib.contextmanager
def temporary_headless_display(env: dict[str, str], enabled: bool):
    if not enabled:
        yield env
        return

    render_env = env.copy()
    render_env.setdefault("DISPLAY", ":0")
    render_env.setdefault("SCALE", "1")

    if shutil.which("Xtigervnc") is None:
        raise RuntimeError("Headless UI rendering requires Xtigervnc in the runtime environment")

    with tempfile.NamedTemporaryFile(prefix="xtigervnc-", suffix=".log", delete=False) as log_file:
        log_path = Path(log_file.name)

    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        [
            "Xtigervnc",
            render_env["DISPLAY"],
            "-geometry",
            "1920x1080",
            "-depth",
            "24",
            "-SecurityTypes",
            "None",
            "-rfbport",
            "-1",
        ],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=render_env,
    )
    try:
        for _ in range(50):
            if proc.poll() is not None:
                log_tail = log_path.read_text(errors="replace")
                raise RuntimeError(f"Xtigervnc exited before startup:\n{log_tail}")
            if Path("/tmp/.X11-unix/X0").exists():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f"Xtigervnc did not create {render_env['DISPLAY']} in time")
        yield render_env
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log_handle.close()
        log_path.unlink(missing_ok=True)
