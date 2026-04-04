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

Options:
  --backend <local|hosted>         Smoke backend. Default: local
  --route <url>                    connect.comma.ai clip URL
  --model <model>                  Hosted Replicate model ref
  --jwt-token <token>              Optional JWT token
  --output-dir <dir>               Output directory for artifacts
  --accel <mode>                   Local accel mode: auto, cpu, videotoolbox, nvidia
  --driver-mode <unchanged|swap>   Driver seat mode for the smoke. Default: unchanged on local, swap on hosted
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

  if [[ -n "${JWT_TOKEN}" ]]; then
    jwt_args+=(--jwt-token "${JWT_TOKEN}")
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
