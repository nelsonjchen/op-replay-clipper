#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIREMENTS_COPY_PATTERN = re.compile(
    r"^COPY (?P<path>\.cog/tmp/build[^ ]+/requirements\.txt) /tmp/requirements\.txt$",
    re.MULTILINE,
)
REQUIREMENTS_MARKER = "Generated requirements.txt:\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize Cog debug temp files referenced by a generated Dockerfile."
    )
    parser.add_argument("--dockerfile", type=Path, required=True)
    parser.add_argument("--debug-log", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser.parse_args()


def requirements_relpath(dockerfile_text: str) -> Path:
    match = REQUIREMENTS_COPY_PATTERN.search(dockerfile_text)
    if match is None:
        raise ValueError("Could not find generated requirements.txt COPY line in Dockerfile")
    return Path(match.group("path"))


def requirements_text(debug_log_text: str) -> str:
    marker_index = debug_log_text.find(REQUIREMENTS_MARKER)
    if marker_index == -1:
        raise ValueError("Could not find generated requirements.txt marker in Cog debug log")
    text = debug_log_text[marker_index + len(REQUIREMENTS_MARKER) :].strip()
    if not text:
        raise ValueError("Cog debug log did not contain any generated requirements lines")
    return text + "\n"


def main() -> int:
    args = parse_args()
    dockerfile_text = args.dockerfile.read_text()
    debug_log_text = args.debug_log.read_text()

    relpath = requirements_relpath(dockerfile_text)
    output_path = (args.repo_root / relpath).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = requirements_text(debug_log_text)
    output_path.write_text(output_text)

    print(f"Materialized {relpath} with {len(output_text.splitlines())} requirement lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
