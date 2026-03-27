#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"
ARTIFACT_DIR="${1:-${ROOT_DIR}/shared/ci-e2e}"
OUTPUT_MP4="${ARTIFACT_DIR}/mici-ui-smoke.mp4"
OUTPUT_PNG="${ARTIFACT_DIR}/mici-ui-smoke.png"
OUTPUT_JSON="${ARTIFACT_DIR}/mici-ui-smoke.json"
DATA_ROOT="${ARTIFACT_DIR}/data"
OPENPILOT_DIR="${ARTIFACT_DIR}/openpilot-local"

rm -rf "${ARTIFACT_DIR}"
mkdir -p "${ARTIFACT_DIR}"

uv run python "${ROOT_DIR}/clip.py" \
  ui \
  --demo \
  --qcam \
  --length-seconds 2 \
  --smear-seconds 0 \
  --accel cpu \
  --openpilot-dir "${OPENPILOT_DIR}" \
  --output "${OUTPUT_MP4}" \
  --data-root "${DATA_ROOT}"

if [[ ! -s "${OUTPUT_MP4}" ]]; then
  echo "Expected non-empty MP4 output at ${OUTPUT_MP4}" >&2
  exit 1
fi

ffprobe \
  -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,width,height \
  -show_entries format=duration \
  -of json \
  "${OUTPUT_MP4}" > "${OUTPUT_JSON}"

ffmpeg -y -i "${OUTPUT_MP4}" -frames:v 1 -update 1 "${OUTPUT_PNG}"

if [[ ! -s "${OUTPUT_PNG}" ]]; then
  echo "Expected non-empty PNG output at ${OUTPUT_PNG}" >&2
  exit 1
fi

uv run python - "${OUTPUT_JSON}" <<'PY'
import json
import sys
from pathlib import Path

metadata_path = Path(sys.argv[1])
metadata = json.loads(metadata_path.read_text())
streams = metadata.get("streams", [])
if not streams:
    raise SystemExit("ffprobe did not report a video stream")

stream = streams[0]
width = int(stream["width"])
height = int(stream["height"])
duration = float(metadata["format"]["duration"])

if width <= 0 or height <= 0:
    raise SystemExit(f"Invalid output dimensions: {width}x{height}")
if duration <= 0:
    raise SystemExit(f"Invalid output duration: {duration}")

print(f"Rendered clip dimensions: {width}x{height}")
print(f"Rendered clip duration: {duration:.3f}s")
PY
