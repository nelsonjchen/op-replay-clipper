#!/usr/bin/env bash

set -euo pipefail

export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

apt-get update -y
apt-get install -y ffmpeg
rm -rf /var/lib/apt/lists/*

python - <<'PY'
from __future__ import annotations

import pathlib
import site

system_lib_dir = pathlib.Path("/usr/lib/x86_64-linux-gnu")
if not system_lib_dir.exists():
    raise SystemExit(0)

for root in site.getsitepackages():
    nvidia_root = pathlib.Path(root) / "nvidia"
    if not nvidia_root.exists():
        continue
    for lib_dir in sorted(path for path in nvidia_root.iterdir() if (path / "lib").exists()):
        for lib_file in sorted((lib_dir / "lib").glob("lib*.so*")):
            if lib_file.is_dir():
                continue
            target = system_lib_dir / lib_file.name
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(lib_file)
            print(f"linked {target} -> {lib_file}", flush=True)
PY
