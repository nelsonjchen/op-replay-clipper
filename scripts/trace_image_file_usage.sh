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

IMAGE="${TRACE_IMAGE:-r8.im/nelsonjchen/op-replay-clipper-beta}"
SCENARIO="${TRACE_SCENARIO:-ui-public}"
OUTPUT_DIR="${TRACE_OUTPUT_DIR:-${REPO_ROOT}/shared/image-trace/${SCENARIO}}"

usage() {
  cat <<'EOF'
Trace file accesses inside the built beta image for one smoke-like scenario.

Usage:
  trace_image_file_usage.sh [--image IMAGE] [--scenario NAME] [--output-dir DIR]

Scenarios:
  ui-public
  driver-hidden-public
  driver-hidden-private
  driver-debug-hidden-private
  driver-debug-swap-hidden-private
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --scenario)
      SCENARIO="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
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

mkdir -p "${OUTPUT_DIR}"

PUBLIC_URL="https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105"
PRIVATE_URL="https://connect.comma.ai/fde53c3c109fb4c0/0000026f--c5469f881d/289/315"

case "${SCENARIO}" in
  ui-public)
    TRACE_ROUTE_URL="${PUBLIC_URL}"
    TRACE_RENDER_TYPE="ui"
    TRACE_PROFILE=""
    TRACE_STYLE="blur"
    TRACE_OUTPUT_FILE="/trace-output/ui-public.mp4"
    ;;
  driver-hidden-public)
    TRACE_ROUTE_URL="${PUBLIC_URL}"
    TRACE_RENDER_TYPE="driver"
    TRACE_PROFILE="driver_unchanged_passenger_hidden"
    TRACE_STYLE="blur"
    TRACE_OUTPUT_FILE="/trace-output/driver-hidden-public.mp4"
    ;;
  driver-hidden-private)
    TRACE_ROUTE_URL="${PRIVATE_URL}"
    TRACE_RENDER_TYPE="driver"
    TRACE_PROFILE="driver_unchanged_passenger_hidden"
    TRACE_STYLE="blur"
    TRACE_OUTPUT_FILE="/trace-output/driver-hidden-private.mp4"
    ;;
  driver-debug-hidden-private)
    TRACE_ROUTE_URL="${PRIVATE_URL}"
    TRACE_RENDER_TYPE="driver-debug"
    TRACE_PROFILE="driver_unchanged_passenger_hidden"
    TRACE_STYLE="blur"
    TRACE_OUTPUT_FILE="/trace-output/driver-debug-hidden-private.mp4"
    ;;
  driver-debug-swap-hidden-private)
    TRACE_ROUTE_URL="${PRIVATE_URL}"
    TRACE_RENDER_TYPE="driver-debug"
    TRACE_PROFILE="driver_face_swap_passenger_hidden"
    TRACE_STYLE="blur"
    TRACE_OUTPUT_FILE="/trace-output/driver-debug-swap-hidden-private.mp4"
    ;;
  *)
    echo "Unsupported scenario: ${SCENARIO}" >&2
    exit 2
    ;;
esac

if [[ "${TRACE_ROUTE_URL}" == "${PRIVATE_URL}" && -z "${COMMA_JWT:-}" ]]; then
  echo "COMMA_JWT is required for private trace scenarios." >&2
  exit 2
fi

docker run --rm --gpus all \
  -e COMMA_JWT="${COMMA_JWT:-}" \
  -e REPLICATE_API_TOKEN="${REPLICATE_API_TOKEN:-}" \
  -e FACEFUSION_ROOT="/.cache/facefusion" \
  -e TRACE_ROUTE_URL="${TRACE_ROUTE_URL}" \
  -e TRACE_RENDER_TYPE="${TRACE_RENDER_TYPE}" \
  -e TRACE_PROFILE="${TRACE_PROFILE}" \
  -e TRACE_STYLE="${TRACE_STYLE}" \
  -e TRACE_OUTPUT_FILE="${TRACE_OUTPUT_FILE}" \
  -v "${OUTPUT_DIR}:/trace-output" \
  --entrypoint bash \
  "${IMAGE}" -lc '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
apt-get install -y strace >/dev/null
mkdir -p /trace-output/trace-raw
python - <<'"'"'PY'"'"'
from core.rf_detr_runtime import ensure_python_nvidia_libs_preferred, sync_python_nvidia_runtime_libs_to_system

ensure_python_nvidia_libs_preferred()
sync_python_nvidia_runtime_libs_to_system()
PY
clip_args=(
  python /src/clip.py
  "${TRACE_RENDER_TYPE}"
  "${TRACE_ROUTE_URL}"
  --file-format h264
  --accel nvidia
  --openpilot-dir /home/batman/openpilot
  --skip-openpilot-update
  --skip-openpilot-bootstrap
  --output "${TRACE_OUTPUT_FILE}"
)
if [[ "${TRACE_RENDER_TYPE}" == driver* ]]; then
  clip_args+=(
    --driver-face-anonymization facefusion
    --driver-face-profile "${TRACE_PROFILE}"
    --passenger-redaction-style "${TRACE_STYLE}"
    --driver-face-selection auto_best_match
    --facefusion-root /.cache/facefusion
  )
fi
if [[ -n "${COMMA_JWT:-}" ]]; then
  clip_args+=(--jwt-token "${COMMA_JWT}")
fi
strace -ff -yy -e trace=file -o /trace-output/trace-raw/trace \
  "${clip_args[@]}"
'

python3 "${SCRIPT_DIR}/summarize_trace_usage.py" "${OUTPUT_DIR}/trace-raw" > "${OUTPUT_DIR}/summary.txt"
