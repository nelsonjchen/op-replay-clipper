#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." >/dev/null 2>&1 && pwd -P)"
DIST_DIR="${DIST_DIR:-${SCRIPT_DIR}/dist}"
MODEL="${MODEL:-r8.im/nelsonjchen/op-replay-clipper-beta}"
COG_BIN="${COG_BIN:-cog}"

find_one() {
  local pattern="$1"
  local match
  match="$(find "${DIST_DIR}" -maxdepth 1 -type f -name "${pattern}" | sort | tail -n 1)"
  if [[ -z "${match}" ]]; then
    echo "Missing artifact matching ${pattern} in ${DIST_DIR}" >&2
    exit 1
  fi
  printf '%s\n' "${match}"
}

COG_SDK_WHEEL="${COG_SDK_WHEEL:-$(find_one 'cog-*.whl')}"
COGLET_WHEEL="${COGLET_WHEEL:-$(find_one 'coglet-*-linux*.whl')}"

echo "Using Cog CLI: ${COG_BIN}"
echo "Using SDK wheel: ${COG_SDK_WHEEL}"
echo "Using coglet wheel: ${COGLET_WHEEL}"

cd "${ROOT_DIR}"
./cog/render_artifacts.sh
env \
  COG_SDK_WHEEL="${COG_SDK_WHEEL}" \
  COGLET_WHEEL="${COGLET_WHEEL}" \
  "${COG_BIN}" push "${MODEL}"
