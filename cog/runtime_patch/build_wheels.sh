#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
OUTPUT_DIR="${OUTPUT_DIR:-${SCRIPT_DIR}/dist}"
COG_REF="${COG_REF:-v0.17.0}"
PLATFORM="${PLATFORM:-linux/amd64}"

mkdir -p "${OUTPUT_DIR}"

docker buildx build \
  --platform "${PLATFORM}" \
  --build-arg "COG_REF=${COG_REF}" \
  --target dist \
  --output "type=local,dest=${OUTPUT_DIR}" \
  "${SCRIPT_DIR}"

echo "Patched Cog runtime wheels written to ${OUTPUT_DIR}"
ls -1 "${OUTPUT_DIR}"
