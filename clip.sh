#!/bin/bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "warning: clip.sh is deprecated and now forwards to local_clip.py ui" >&2
if command -v uv >/dev/null 2>&1; then
  exec uv run python "$script_dir/local_clip.py" ui "$@"
fi

python_bin="$script_dir/.venv/bin/python"
if [[ -x "$python_bin" ]]; then
  exec "$python_bin" "$script_dir/local_clip.py" ui "$@"
fi

exec "${PYTHON:-python3}" "$script_dir/local_clip.py" ui "$@"
