#!/usr/bin/env python3
"""OP Replay Clipper — Native Window Launcher (pywebview)

Starts the Docker-based web server and opens the UI in a native OS window.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests
import webview

SERVER_URL = "http://localhost:7860"
HEALTH_URL = f"{SERVER_URL}/api/health"
COMPOSE_DIR = os.environ.get(
    "CLIPPER_REPO_DIR",
    str(Path(__file__).resolve().parent.parent / "op-replay-clipper"),
)
STARTUP_TIMEOUT = 120  # seconds


def find_compose_dir() -> str:
    """Locate the op-replay-clipper repo with docker-compose.yml."""
    candidates = [
        COMPOSE_DIR,
        str(Path.home() / "op-replay-clipper"),
        str(Path.home() / "Desktop" / "op-replay-clipper"),
    ]
    for path in candidates:
        if (Path(path) / "docker-compose.yml").exists():
            return path
    print("ERROR: Cannot find op-replay-clipper repo with docker-compose.yml")
    print("Set CLIPPER_REPO_DIR environment variable to the repo path.")
    sys.exit(1)


def start_docker(compose_dir: str) -> subprocess.Popen:
    """Start docker compose in the background."""
    print(f"Starting Docker services from {compose_dir}...")
    proc = subprocess.Popen(
        ["docker", "compose", "up", "web"],
        cwd=compose_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc


def wait_for_server() -> bool:
    """Wait for the web server to become healthy."""
    print("Waiting for server to start...", end="", flush=True)
    for _ in range(STARTUP_TIMEOUT):
        try:
            resp = requests.get(HEALTH_URL, timeout=1)
            if resp.ok:
                print(" ready!")
                return True
        except (requests.ConnectionError, requests.Timeout):
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    print("\nERROR: Server did not start within timeout.")
    return False


def stop_docker(proc: subprocess.Popen, compose_dir: str) -> None:
    """Stop the Docker services."""
    print("Shutting down Docker services...")
    subprocess.run(
        ["docker", "compose", "down"],
        cwd=compose_dir,
        capture_output=True,
    )
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main() -> None:
    compose_dir = find_compose_dir()
    docker_proc = start_docker(compose_dir)

    # Ensure cleanup on exit
    atexit.register(stop_docker, docker_proc, compose_dir)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    if not wait_for_server():
        sys.exit(1)

    # Open native window
    window = webview.create_window(
        "OP Replay Clipper",
        SERVER_URL,
        width=820,
        height=920,
        min_size=(600, 700),
    )
    webview.start()


if __name__ == "__main__":
    main()
