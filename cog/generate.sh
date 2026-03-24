#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"

uv export \
  --frozen \
  --format requirements.txt \
  --no-hashes \
  --no-emit-project \
  --no-group test \
  --output-file "${ROOT_DIR}/requirements-cog.txt"

python3 "${SCRIPT_DIR}/render_cog_yaml.py" \
  --template "${SCRIPT_DIR}/cog.template.yaml" \
  --setup-script "${ROOT_DIR}/common/setup.sh" \
  --output "${ROOT_DIR}/cog.yaml"
