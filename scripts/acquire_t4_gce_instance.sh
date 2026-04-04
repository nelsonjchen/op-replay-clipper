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

PROJECT="${GCE_PROJECT:-${GCLOUD_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}}"
RETRY_SECONDS="${GCE_RETRY_SECONDS:-600}"
STATUS_POLL_SECONDS="${GCE_STATUS_POLL_SECONDS:-20}"
TIMEOUT_SECONDS="${GCE_TIMEOUT_SECONDS:-$((6 * 60 * 60))}"
BASE_NAME="${GCE_T4_BASE_NAME:-op-clipper-t4-cog}"
MACHINE_TYPE="${GCE_T4_MACHINE_TYPE:-n1-standard-4}"
GPU_TYPE="${GCE_T4_GPU_TYPE:-nvidia-tesla-t4}"
GPU_COUNT="${GCE_T4_GPU_COUNT:-1}"
BOOT_DISK_GB="${GCE_T4_BOOT_DISK_GB:-200}"
IMAGE_PROJECT="${GCE_T4_IMAGE_PROJECT:-ubuntu-os-accelerator-images}"
IMAGE_FAMILY="${GCE_T4_IMAGE_FAMILY:-ubuntu-accelerator-2204-amd64-with-nvidia-580}"
ZONE_LIST_RAW="${GCE_T4_ZONES:-us-central1-b,us-central1-a,us-central1-c,us-central1-f,us-east1-c,us-west1-b}"
STATE_DIR="${GCE_T4_STATE_DIR:-/tmp/op-clipper-t4-gce}"
SPOT_FIRST="${GCE_T4_SPOT_FIRST:-1}"
SPOT_FULL_CYCLES="${GCE_T4_SPOT_FULL_CYCLES:-1}"

usage() {
  cat <<'EOF'
Acquire a Linux/NVIDIA T4 VM, retrying through GPU stockouts until creation succeeds.

Usage:
  acquire_t4_gce_instance.sh [options]

Environment:
  GCE_PROJECT                     GCP project id.
  GCE_RETRY_SECONDS               Delay between full retry rounds after stockout.
  GCE_STATUS_POLL_SECONDS         Poll interval while waiting for RUNNING.
  GCE_TIMEOUT_SECONDS             Total time budget before giving up.
  GCE_T4_BASE_NAME                Instance name prefix. Default: op-clipper-t4-cog
  GCE_T4_MACHINE_TYPE             Machine type. Default: n1-standard-4
  GCE_T4_GPU_TYPE                 GPU type. Default: nvidia-tesla-t4
  GCE_T4_GPU_COUNT                GPU count. Default: 1
  GCE_T4_BOOT_DISK_GB             Boot disk size. Default: 200
  GCE_T4_IMAGE_PROJECT            Image project. Default: ubuntu-os-accelerator-images
  GCE_T4_IMAGE_FAMILY             Image family. Default: ubuntu-accelerator-2204-amd64-with-nvidia-580
  GCE_T4_ZONES                    Comma-separated ordered zone list.
  GCE_T4_STATE_DIR                Temp state dir. Default: /tmp/op-clipper-t4-gce
  GCE_T4_SPOT_FIRST               1 to try spot first. Default: 1
  GCE_T4_SPOT_FULL_CYCLES         Full spot rounds before switching to non-spot. Default: 1

Options:
  --project <project>
  --retry-seconds <seconds>
  --status-poll-seconds <seconds>
  --timeout-seconds <seconds>
  --base-name <name>
  --machine-type <type>
  --gpu-type <type>
  --gpu-count <count>
  --boot-disk-gb <gigabytes>
  --image-project <project>
  --image-family <family>
  --zones <z1,z2,...>
  --state-dir <dir>
  --standard-only                 Skip the initial spot attempts.
  -h, --help
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "Missing required configuration for ${name}. Set it in .env or pass a flag." >&2
    exit 2
  fi
}

is_stockout_error() {
  local output="$1"
  [[ "$output" == *"ZONE_RESOURCE_POOL_EXHAUSTED"* ]] \
    || [[ "$output" == *"ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS"* ]] \
    || [[ "$output" == *"resource_availability"* ]] \
    || [[ "$output" == *"STOCKOUT"* ]]
}

instance_exists() {
  local name="$1"
  local zone="$2"
  gcloud compute instances describe "$name" \
    --project "$PROJECT" \
    --zone "$zone" \
    --format='get(name)' >/dev/null 2>&1
}

instance_status() {
  local name="$1"
  local zone="$2"
  gcloud compute instances describe "$name" \
    --project "$PROJECT" \
    --zone "$zone" \
    --format='get(status)'
}

wait_for_running() {
  local name="$1"
  local zone="$2"
  local deadline="$3"

  while true; do
    if (( "$(date +%s)" >= deadline )); then
      log "Timed out waiting for ${name} in ${zone} to reach RUNNING"
      return 1
    fi
    local status
    status="$(instance_status "$name" "$zone" 2>/dev/null || true)"
    if [[ "$status" == "RUNNING" ]]; then
      log "${name} is RUNNING in ${zone}"
      return 0
    fi
    log "${name} in ${zone} is ${status:-UNKNOWN}; polling again in ${STATUS_POLL_SECONDS}s"
    sleep "$STATUS_POLL_SECONDS"
  done
}

start_existing() {
  local name="$1"
  local zone="$2"
  local deadline="$3"
  local status
  status="$(instance_status "$name" "$zone" 2>/dev/null || true)"
  if [[ "$status" == "RUNNING" ]]; then
    log "Reusing existing RUNNING instance ${name} in ${zone}"
    return 0
  fi
  log "Starting existing instance ${name} in ${zone} from status ${status:-UNKNOWN}"
  gcloud compute instances start "$name" \
    --project "$PROJECT" \
    --zone "$zone" >/dev/null
  wait_for_running "$name" "$zone" "$deadline"
}

persist_state() {
  local name="$1"
  local zone="$2"
  mkdir -p "$STATE_DIR"
  printf '%s\n' "$name" > "${STATE_DIR}/instance-name"
  printf '%s\n' "$zone" > "${STATE_DIR}/zone"
}

create_instance() {
  local name="$1"
  local zone="$2"
  local use_spot="$3"
  local -a create_args=(
    compute instances create "$name"
    --project "$PROJECT"
    --zone "$zone"
    --machine-type "$MACHINE_TYPE"
    --accelerator "count=${GPU_COUNT},type=${GPU_TYPE}"
    --maintenance-policy TERMINATE
    --boot-disk-size "${BOOT_DISK_GB}GB"
    --image-project "$IMAGE_PROJECT"
    --image-family "$IMAGE_FAMILY"
  )
  if [[ "$use_spot" == "1" ]]; then
    create_args+=(--provisioning-model SPOT)
  fi
  gcloud "${create_args[@]}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT="$2"
      shift 2
      ;;
    --retry-seconds)
      RETRY_SECONDS="$2"
      shift 2
      ;;
    --status-poll-seconds)
      STATUS_POLL_SECONDS="$2"
      shift 2
      ;;
    --timeout-seconds)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --base-name)
      BASE_NAME="$2"
      shift 2
      ;;
    --machine-type)
      MACHINE_TYPE="$2"
      shift 2
      ;;
    --gpu-type)
      GPU_TYPE="$2"
      shift 2
      ;;
    --gpu-count)
      GPU_COUNT="$2"
      shift 2
      ;;
    --boot-disk-gb)
      BOOT_DISK_GB="$2"
      shift 2
      ;;
    --image-project)
      IMAGE_PROJECT="$2"
      shift 2
      ;;
    --image-family)
      IMAGE_FAMILY="$2"
      shift 2
      ;;
    --zones)
      ZONE_LIST_RAW="$2"
      shift 2
      ;;
    --state-dir)
      STATE_DIR="$2"
      shift 2
      ;;
    --standard-only)
      SPOT_FIRST="0"
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

if [[ -z "${PROJECT}" ]]; then
  PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
fi

require_value "GCE_PROJECT/--project" "$PROJECT"
IFS=',' read -r -a ZONES <<< "$ZONE_LIST_RAW"
if [[ "${#ZONES[@]}" -eq 0 ]]; then
  echo "Zone list is empty." >&2
  exit 2
fi

mkdir -p "$STATE_DIR"
INSTANCE_STATE_FILE="${STATE_DIR}/instance-name"
ZONE_STATE_FILE="${STATE_DIR}/zone"
deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))

if [[ -f "${INSTANCE_STATE_FILE}" && -f "${ZONE_STATE_FILE}" ]]; then
  EXISTING_INSTANCE="$(<"${INSTANCE_STATE_FILE}")"
  EXISTING_ZONE="$(<"${ZONE_STATE_FILE}")"
  if [[ -n "${EXISTING_INSTANCE}" && -n "${EXISTING_ZONE}" ]] && instance_exists "${EXISTING_INSTANCE}" "${EXISTING_ZONE}"; then
    start_existing "${EXISTING_INSTANCE}" "${EXISTING_ZONE}" "$deadline"
    printf '{"instance":"%s","zone":"%s","provisioning":"existing"}\n' "${EXISTING_INSTANCE}" "${EXISTING_ZONE}"
    exit 0
  fi
fi

spot_cycles_completed=0
attempt_round=0

while true; do
  if (( "$(date +%s)" >= deadline )); then
    log "Timed out waiting for T4 capacity"
    exit 1
  fi

  attempt_round=$((attempt_round + 1))
  use_spot="0"
  if [[ "$SPOT_FIRST" == "1" && "$spot_cycles_completed" -lt "$SPOT_FULL_CYCLES" ]]; then
    use_spot="1"
  fi
  provisioning_label="standard"
  if [[ "$use_spot" == "1" ]]; then
    provisioning_label="spot"
  fi

  log "Starting ${provisioning_label} acquisition round ${attempt_round} across zones: ${ZONE_LIST_RAW}"
  for zone in "${ZONES[@]}"; do
    instance_name="${BASE_NAME}-$(date '+%m%d%H%M%S')"
    log "Trying ${instance_name} in ${zone} (${provisioning_label})"
    set +e
    create_output="$(
      create_instance "${instance_name}" "${zone}" "${use_spot}" 2>&1
    )"
    create_rc=$?
    set -e

    if (( create_rc == 0 )); then
      persist_state "${instance_name}" "${zone}"
      wait_for_running "${instance_name}" "${zone}" "$deadline"
      printf '{"instance":"%s","zone":"%s","provisioning":"%s"}\n' "${instance_name}" "${zone}" "${provisioning_label}"
      exit 0
    fi

    if is_stockout_error "${create_output}"; then
      log "Capacity unavailable in ${zone} (${provisioning_label}); trying next zone"
      continue
    fi

    echo "${create_output}" >&2
    log "Create failed with a non-retryable error in ${zone}"
    exit "${create_rc}"
  done

  if [[ "$use_spot" == "1" ]]; then
    spot_cycles_completed=$((spot_cycles_completed + 1))
  fi
  log "No ${provisioning_label} T4 capacity available; sleeping ${RETRY_SECONDS}s before retrying"
  sleep "${RETRY_SECONDS}"
done
