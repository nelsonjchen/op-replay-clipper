from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re

ABSOLUTE_PATH_RE = re.compile(r'"(/[^"\n]+)"')


def classify_path(raw_path: str) -> str:
    path = raw_path.strip()
    if not path.startswith("/"):
        return "other"
    if path.startswith(("/proc/", "/sys/", "/dev/")):
        return "kernel-or-device"
    if path.startswith("/src/.cache/rfdetr/"):
        return "rfdetr-weights"
    if path.startswith("/.cache/facefusion/.assets/"):
        rel = path.removeprefix("/.cache/facefusion/.assets/")
        head = rel.split("/", 1)[0]
        return f"facefusion-assets:{head}"
    if path.startswith("/.cache/facefusion/.venv/lib/python3.12/site-packages/"):
        rel = path.removeprefix("/.cache/facefusion/.venv/lib/python3.12/site-packages/")
        head = rel.split("/", 1)[0]
        return f"facefusion-venv:{head}"
    if path.startswith("/root/.pyenv/versions/3.12.11/lib/python3.12/site-packages/"):
        rel = path.removeprefix("/root/.pyenv/versions/3.12.11/lib/python3.12/site-packages/")
        head = rel.split("/", 1)[0]
        return f"main-site-packages:{head}"
    if path.startswith("/home/batman/openpilot/.venv/lib/python3.12/site-packages/"):
        rel = path.removeprefix("/home/batman/openpilot/.venv/lib/python3.12/site-packages/")
        head = rel.split("/", 1)[0]
        return f"openpilot-venv:{head}"
    if path.startswith("/home/batman/openpilot/"):
        rel = path.removeprefix("/home/batman/openpilot/")
        head = rel.split("/", 1)[0]
        return f"openpilot-tree:{head}"
    if path.startswith("/src/"):
        rel = path.removeprefix("/src/")
        head = rel.split("/", 1)[0]
        return f"src:{head}"
    if path.startswith("/usr/lib/x86_64-linux-gnu/"):
        rel = path.removeprefix("/usr/lib/x86_64-linux-gnu/")
        head = rel.split("/", 1)[0]
        return f"usr-lib:{head}"
    if path.startswith("/usr/local/cuda/"):
        rel = path.removeprefix("/usr/local/cuda/")
        head = rel.split("/", 1)[0]
        return f"cuda:{head}"
    return path.split("/", 2)[1] if path.count("/") >= 2 else path


def extract_paths(trace_dir: Path) -> list[str]:
    paths: list[str] = []
    for trace_file in sorted(trace_dir.glob("trace*")):
        if trace_file.is_dir():
            continue
        for line in trace_file.read_text(errors="ignore").splitlines():
            for match in ABSOLUTE_PATH_RE.findall(line):
                paths.append(match)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize traced file accesses from strace output.")
    parser.add_argument("trace_dir", type=Path, help="Directory containing strace trace.* output files.")
    args = parser.parse_args()

    paths = extract_paths(args.trace_dir)
    unique_paths = sorted(set(paths))
    buckets = Counter(classify_path(path) for path in unique_paths)

    print(f"trace_dir: {args.trace_dir}")
    print(f"unique_paths: {len(unique_paths)}")
    print("\nTop buckets:")
    for bucket, count in buckets.most_common(80):
        print(f"{count:5d}  {bucket}")

    print("\nSample touched paths:")
    for path in unique_paths[:120]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
