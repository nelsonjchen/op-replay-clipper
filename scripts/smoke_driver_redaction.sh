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

BACKEND="${SMOKE_BACKEND:-local}"
ROUTE_URL="${SMOKE_ROUTE_URL:-${ROUTE_URL:-}}"
MODEL="${SMOKE_MODEL:-${STAGING_MODEL:-}}"
JWT_TOKEN="${SMOKE_JWT_TOKEN:-${JWT_TOKEN:-${COMMA_JWT:-}}}"
OUTPUT_DIR="${SMOKE_OUTPUT_DIR:-${REPO_ROOT}/shared/driver-redaction-smoke}"
ACCEL="${SMOKE_ACCEL:-auto}"
DRIVER_MODE="${SMOKE_DRIVER_MODE:-}"
SYNC_REPO="${SMOKE_SYNC_REPO:-1}"
OPENPILOT_DIR="${SMOKE_OPENPILOT_DIR:-${REPO_ROOT}/.cache/openpilot-local}"
RF_DETR_DEVICE="${SMOKE_RF_DETR_DEVICE:-}"
REQUIRE_RF_DETR_DEVICE="${SMOKE_REQUIRE_RF_DETR_DEVICE:-}"
REQUIRE_OUTPUT_ENCODER="${SMOKE_REQUIRE_OUTPUT_ENCODER:-}"

usage() {
  cat <<'EOF'
Run the three product-facing passenger-redaction smoke checks.

Usage:
  smoke_driver_redaction.sh [options]

Environment:
  SMOKE_BACKEND                    local or hosted. Default: local
  SMOKE_ROUTE_URL                  connect.comma.ai clip URL
  SMOKE_MODEL                      Hosted Replicate model ref when backend=hosted
  SMOKE_JWT_TOKEN                  Optional JWT token
  SMOKE_OUTPUT_DIR                 Output directory for artifacts
  SMOKE_ACCEL                      Local acceleration mode. Default: auto
  SMOKE_DRIVER_MODE                unchanged or swap. Defaults to unchanged for local and swap for hosted.
  SMOKE_SYNC_REPO                  1 to run uv sync before local smokes. Default: 1
  SMOKE_OPENPILOT_DIR              Openpilot checkout to reuse for local smokes.

Options:
  --backend <local|hosted>         Smoke backend. Default: local
  --route <url>                    connect.comma.ai clip URL
  --model <model>                  Hosted Replicate model ref
  --jwt-token <token>              Optional JWT token
  --output-dir <dir>               Output directory for artifacts
  --accel <mode>                   Local accel mode: auto, cpu, videotoolbox, nvidia
  --driver-mode <unchanged|swap>   Driver seat mode for the smoke. Default: unchanged on local, swap on hosted
  --rf-detr-device <auto|cpu|cuda|mps>
  --require-rf-detr-device <device>
  --require-output-encoder <name>
  --skip-sync-repo                 Skip the initial uv sync step for local smokes
  -h, --help                       Show this help text
EOF
}

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    echo "Missing required configuration for ${name}." >&2
    exit 2
  fi
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
    --route)
      ROUTE_URL="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --jwt-token)
      JWT_TOKEN="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --accel)
      ACCEL="$2"
      shift 2
      ;;
    --driver-mode)
      DRIVER_MODE="$2"
      shift 2
      ;;
    --rf-detr-device)
      RF_DETR_DEVICE="$2"
      shift 2
      ;;
    --require-rf-detr-device)
      REQUIRE_RF_DETR_DEVICE="$2"
      shift 2
      ;;
    --require-output-encoder)
      REQUIRE_OUTPUT_ENCODER="$2"
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

if [[ "${BACKEND}" != "local" && "${BACKEND}" != "hosted" ]]; then
  echo "Unsupported backend: ${BACKEND}" >&2
  exit 2
fi

if [[ -z "${DRIVER_MODE}" ]]; then
  if [[ "${BACKEND}" == "hosted" ]]; then
    DRIVER_MODE="swap"
  else
    DRIVER_MODE="unchanged"
  fi
fi

if [[ "${DRIVER_MODE}" != "unchanged" && "${DRIVER_MODE}" != "swap" ]]; then
  echo "Unsupported driver mode: ${DRIVER_MODE}" >&2
  exit 2
fi

require_value "SMOKE_ROUTE_URL/--route" "${ROUTE_URL}"
if [[ "${BACKEND}" == "hosted" ]]; then
  require_value "SMOKE_MODEL/--model" "${MODEL}"
fi

mkdir -p "${OUTPUT_DIR}"

if [[ "${BACKEND}" == "local" && "${SYNC_REPO}" != "0" ]]; then
  log "Syncing repo environment with uv"
  uv sync
fi

run_ffprobe() {
  local output_path="$1"
  ffprobe \
    -v error \
    -select_streams v:0 \
    -show_entries stream=codec_name,codec_tag_string,width,height,pix_fmt \
    -show_entries format=duration,size \
    -of json \
    "${output_path}" > "${output_path}.ffprobe.json"
}

run_local_case() {
  local render_type="$1"
  local profile="$2"
  local style="$3"
  local output_path="$4"
  local -a jwt_args=()
  local -a openpilot_args=(
    --openpilot-dir "${OPENPILOT_DIR}"
  )

  if [[ -n "${JWT_TOKEN}" ]]; then
    jwt_args+=(--jwt-token "${JWT_TOKEN}")
  fi

  if [[ -x "${OPENPILOT_DIR}/.venv/bin/python" ]]; then
    openpilot_args+=(--skip-openpilot-update --skip-openpilot-bootstrap)
  fi

  if [[ -n "${RF_DETR_DEVICE}" ]]; then
    export DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE="${RF_DETR_DEVICE}"
  fi

  uv run python "${REPO_ROOT}/clip.py" \
    "${render_type}" \
    "${ROUTE_URL}" \
    --file-format h264 \
    --accel "${ACCEL}" \
    --driver-face-anonymization facefusion \
    --driver-face-profile "${profile}" \
    --passenger-redaction-style "${style}" \
    --driver-face-selection auto_best_match \
    "${openpilot_args[@]}" \
    "${jwt_args[@]}" \
    --output "${output_path}"
}

run_hosted_case() {
  local render_type="$1"
  local profile_label="$2"
  local style="$3"
  local output_path="$4"
  local -a jwt_args=()

  if [[ -n "${JWT_TOKEN}" ]]; then
    jwt_args+=(--jwt-token "${JWT_TOKEN}")
  fi

  uv run python "${REPO_ROOT}/replicate_run.py" \
    --model "${MODEL}" \
    --url "${ROUTE_URL}" \
    --render-type "${render_type}" \
    --file-format h264 \
    --anonymization-profile "${profile_label}" \
    --passenger-redaction-style "${style}" \
    "${jwt_args[@]}" \
    --output "${output_path}"
}

run_case() {
  local case_name="$1"
  local render_type="$2"
  local profile_slug="$3"
  local profile_label="$4"
  local style="$5"
  local output_path="${OUTPUT_DIR}/${case_name}.mp4"

  log "Running ${case_name} via ${BACKEND}"
  if [[ "${BACKEND}" == "local" ]]; then
    run_local_case "${render_type}" "${profile_slug}" "${style}" "${output_path}"
  else
    run_hosted_case "${render_type}" "${profile_label}" "${style}" "${output_path}"
  fi

  if [[ ! -s "${output_path}" ]]; then
    echo "Expected non-empty output at ${output_path}" >&2
    exit 1
  fi
  if [[ -n "${REQUIRE_RF_DETR_DEVICE}" || -n "${REQUIRE_OUTPUT_ENCODER}" ]]; then
    local selection_report="${output_path%.mp4}.driver-face-selection.json"
    if [[ ! -s "${selection_report}" ]]; then
      echo "Expected selection report at ${selection_report}" >&2
      exit 1
    fi
    python - "${selection_report}" "${REQUIRE_RF_DETR_DEVICE}" "${REQUIRE_OUTPUT_ENCODER}" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
required_device = sys.argv[2]
required_encoder = sys.argv[3]
hidden = None
for seat_report in report.get("seat_reports", []):
    hidden = seat_report.get("hidden_redaction")
    if hidden:
        break
if hidden is None:
    raise SystemExit("Could not find hidden_redaction in selection report")
actual_device = hidden.get("rf_detr_device")
actual_encoder = hidden.get("output_video_encoder")
print(f"hidden_redaction.rf_detr_device={actual_device}")
print(f"hidden_redaction.output_video_encoder={actual_encoder}")
if required_device and actual_device != required_device:
    raise SystemExit(f"Expected rf_detr_device={required_device}, got {actual_device}")
if required_encoder and actual_encoder != required_encoder:
    raise SystemExit(f"Expected output_video_encoder={required_encoder}, got {actual_encoder}")
PY
  fi
  run_ffprobe "${output_path}"
}

driver_profile_slug() {
  if [[ "${DRIVER_MODE}" == "swap" ]]; then
    printf '%s' "driver_face_swap_passenger_hidden"
  else
    printf '%s' "driver_unchanged_passenger_hidden"
  fi
}

driver_profile_label() {
  if [[ "${DRIVER_MODE}" == "swap" ]]; then
    printf '%s' "driver face swap, passenger hidden"
  else
    printf '%s' "driver unchanged, passenger hidden"
  fi
}

run_case \
  "driver-hidden-blur" \
  "driver" \
  "$(driver_profile_slug)" \
  "$(driver_profile_label)" \
  "blur"

run_case \
  "driver-hidden-silhouette" \
  "driver" \
  "$(driver_profile_slug)" \
  "$(driver_profile_label)" \
  "silhouette"

run_case \
  "driver-debug-hidden-blur" \
  "driver-debug" \
  "driver_unchanged_passenger_hidden" \
  "driver unchanged, passenger hidden" \
  "blur"

log "Smoke artifacts written to ${OUTPUT_DIR}"
