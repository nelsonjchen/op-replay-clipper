#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOTENV_PATH="${REPO_ROOT}/.env"

if [[ -f "${DOTENV_PATH}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${DOTENV_PATH}"
  set +a
fi

BACKEND="${RF_DETR_REPRO_BACKEND:-local-cli}"
INPUT_SOURCE="${RF_DETR_REPRO_SOURCE_CLIP:-${REPO_ROOT}/shared/driver-face-eval/passenger-blackout-289-315/driver-source-hq-hevc.mp4}"
INPUT_DIR="${RF_DETR_REPRO_INPUT_DIR:-${REPO_ROOT}/shared/rf-detr-repro-inputs}"
OUTPUT_DIR="${RF_DETR_REPRO_OUTPUT_DIR:-${REPO_ROOT}/shared/rf-detr-repro-smoke/${BACKEND}}"
MODEL="${RF_DETR_REPRO_MODEL:-nelsonjchen/op-replay-clipper-rfdetr-repro-beta}"
DEVICE="${RF_DETR_REPRO_DEVICE:-auto}"
COG_GPUS="${RF_DETR_REPRO_COG_GPUS:-}"
SYNC_REPO="${RF_DETR_REPRO_SYNC_REPO:-1}"
REQUIRE_ACTUAL_DEVICE="${RF_DETR_REPRO_REQUIRE_ACTUAL_DEVICE:-}"

usage() {
  cat <<'EOF'
Run the tiny RF-DETR repro through plain Python, local Cog, or hosted Replicate.

Usage:
  smoke_rf_detr_repro.sh [options]

Options:
  --backend <local-cli|local-cog|hosted>
  --source-clip <path>
  --input-dir <dir>
  --output-dir <dir>
  --model <model>
  --device <auto|cpu|cuda|mps>
  --require-actual-device <cpu|cuda|mps>
  --cog-gpus <value>
  --skip-sync-repo
  -h, --help
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)
      BACKEND="$2"
      shift 2
      ;;
    --source-clip)
      INPUT_SOURCE="$2"
      shift 2
      ;;
    --input-dir)
      INPUT_DIR="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --device)
      DEVICE="$2"
      shift 2
      ;;
    --require-actual-device)
      REQUIRE_ACTUAL_DEVICE="$2"
      shift 2
      ;;
    --cog-gpus)
      COG_GPUS="$2"
      shift 2
      ;;
    --skip-sync-repo)
      SYNC_REPO="0"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "${INPUT_DIR}" "${OUTPUT_DIR}"

if [[ "${SYNC_REPO}" != "0" ]]; then
  log "Syncing repo environment with uv"
  uv sync
fi

STILL_INPUT="${INPUT_DIR}/still.png"
CLIP_INPUT="${INPUT_DIR}/tiny-clip.mp4"

if [[ ! -s "${STILL_INPUT}" ]]; then
  log "Preparing still input from ${INPUT_SOURCE}"
  ffmpeg -y -ss 0.6 -i "${INPUT_SOURCE}" -frames:v 1 "${STILL_INPUT}" >/dev/null 2>&1
fi

if [[ ! -s "${CLIP_INPUT}" ]]; then
  log "Preparing tiny clip input from ${INPUT_SOURCE}"
  ffmpeg -y -ss 0.5 -i "${INPUT_SOURCE}" -t 1.5 -an -c:v libx264 -preset veryfast -pix_fmt yuv420p "${CLIP_INPUT}" >/dev/null 2>&1
fi

run_local_cli_case() {
  local input_path="$1"
  local output_path="$2"
  uv run python "${REPO_ROOT}/scripts/rf_detr_repro.py" \
    --input "${input_path}" \
    --output-dir "${output_path}" \
    --device "${DEVICE}" \
    --write-overlay-video
}

run_local_cog_case() {
  local input_path="$1"
  local output_path="$2"
  local bundle_path="${output_path}.zip"
  local -a cog_args=(predict --file "cog-rfdetr-repro.yaml" -i "media=@${input_path}" -i "device=${DEVICE}" -i writeOverlayVideo=true -o "${bundle_path}")
  if [[ -n "${COG_GPUS}" ]]; then
    cog_args+=(--gpus "${COG_GPUS}")
  fi
  (
    cd "${REPO_ROOT}"
    ./cog/render_artifacts.sh
    cog "${cog_args[@]}"
  )
}

run_hosted_case() {
  local input_path="$1"
  local output_path="$2"
  uv run python "${REPO_ROOT}/rf_detr_repro_run.py" \
    --model "${MODEL}" \
    --input "${input_path}" \
    --output "${output_path}.zip" \
    --device "${DEVICE}" \
    --write-overlay-video
}

assert_actual_device() {
  local output_path="$1"
  local actual_device=""
  if [[ -d "${output_path}" ]]; then
    actual_device="$(python - "${output_path}/report.json" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
print(report.get("actual_model_device", ""))
PY
)"
  else
    actual_device="$(python - "${output_path}.zip" <<'PY'
import json
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    with archive.open("report.json") as handle:
        report = json.load(handle)
print(report.get("actual_model_device", ""))
PY
)"
  fi

  if [[ -z "${actual_device}" ]]; then
    echo "Could not determine actual_model_device for ${output_path}" >&2
    exit 1
  fi
  log "actual_model_device=${actual_device} for ${output_path}"
  if [[ -n "${REQUIRE_ACTUAL_DEVICE}" && "${actual_device}" != "${REQUIRE_ACTUAL_DEVICE}" ]]; then
    echo "Expected actual_model_device=${REQUIRE_ACTUAL_DEVICE}, got ${actual_device}" >&2
    exit 1
  fi
}

run_case() {
  local case_name="$1"
  local input_path="$2"
  local output_path="${OUTPUT_DIR}/${case_name}"

  log "Running ${case_name} via ${BACKEND}"
  case "${BACKEND}" in
    local-cli)
      run_local_cli_case "${input_path}" "${output_path}"
      ;;
    local-cog)
      run_local_cog_case "${input_path}" "${output_path}"
      ;;
    hosted)
      run_hosted_case "${input_path}" "${output_path}"
      ;;
    *)
      echo "Unsupported backend: ${BACKEND}" >&2
      exit 2
      ;;
  esac
  assert_actual_device "${output_path}"
}

run_case "still" "${STILL_INPUT}"
run_case "tiny-clip" "${CLIP_INPUT}"

log "Artifacts written to ${OUTPUT_DIR}"
