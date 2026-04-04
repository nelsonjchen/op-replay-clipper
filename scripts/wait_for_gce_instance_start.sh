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
ZONE="${GCE_ZONE:-}"
INSTANCE="${GCE_INSTANCE:-}"
RETRY_SECONDS="${GCE_RETRY_SECONDS:-600}"
STATUS_POLL_SECONDS="${GCE_STATUS_POLL_SECONDS:-20}"
TIMEOUT_SECONDS="${GCE_TIMEOUT_SECONDS:-$((6 * 60 * 60))}"

usage() {
  cat <<'EOF'
Wait for a GCE VM to start, retrying through temporary GPU stockouts.

Usage:
  wait_for_gce_instance_start.sh [options]

Environment:
  GCE_PROJECT                     GCP project id.
  GCE_ZONE                        GCE zone.
  GCE_INSTANCE                    Instance name.
  GCE_RETRY_SECONDS               Delay between retry attempts after stockout.
  GCE_STATUS_POLL_SECONDS         Poll interval while waiting for RUNNING.
  GCE_TIMEOUT_SECONDS             Total time budget before giving up.
  GCLOUD_PROJECT                  Fallback project id if GCE_PROJECT is unset.
  GOOGLE_CLOUD_PROJECT            Fallback project id if GCE_PROJECT is unset.

Options:
  --project <project>              GCP project id.
  --zone <zone>                    GCE zone.
  --instance <name>                Instance name.
  --retry-seconds <seconds>        Delay between retry attempts after stockout. Default: 600
  --status-poll-seconds <seconds>  Poll interval while waiting for RUNNING after a successful start call. Default: 20
  --timeout-seconds <seconds>      Total time budget before giving up. Default: 21600
  -h, --help                       Show this help text.
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

is_stockout_error() {
  local output="$1"
  [[ "$output" == *"ZONE_RESOURCE_POOL_EXHAUSTED"* ]] \
    || [[ "$output" == *"ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS"* ]] \
    || [[ "$output" == *"resource_availability"* ]] \
    || [[ "$output" == *"STOCKOUT"* ]]
}

instance_status() {
  gcloud compute instances describe "$INSTANCE" \
    --project "$PROJECT" \
    --zone "$ZONE" \
    --format='get(status)'
}

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "Missing required configuration for ${name}. Set it in .env or pass a flag." >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT="$2"
      shift 2
      ;;
    --zone)
      ZONE="$2"
      shift 2
      ;;
    --instance)
      INSTANCE="$2"
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
require_value "GCE_ZONE/--zone" "$ZONE"
require_value "GCE_INSTANCE/--instance" "$INSTANCE"

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))

log "Watching ${PROJECT}/${ZONE}/${INSTANCE} for RUNNING state"

while true; do
  now=$(date +%s)
  if (( now >= deadline )); then
    log "Timed out waiting for ${INSTANCE} to reach RUNNING"
    exit 1
  fi

  status="$(instance_status 2>/dev/null || true)"
  if [[ "$status" == "RUNNING" ]]; then
    log "${INSTANCE} is already RUNNING"
    exit 0
  fi

  if [[ "$status" == "PROVISIONING" || "$status" == "STAGING" ]]; then
    log "${INSTANCE} is ${status}; polling every ${STATUS_POLL_SECONDS}s"
    sleep "$STATUS_POLL_SECONDS"
    continue
  fi

  log "Attempting to start ${INSTANCE} from status '${status:-UNKNOWN}'"
  set +e
  start_output="$(
    gcloud compute instances start "$INSTANCE" \
      --project "$PROJECT" \
      --zone "$ZONE" \
      2>&1
  )"
  start_rc=$?
  set -e

  if (( start_rc == 0 )); then
    log "Start request accepted; waiting for RUNNING"
    while true; do
      now=$(date +%s)
      if (( now >= deadline )); then
        log "Timed out waiting for ${INSTANCE} to become RUNNING after start request"
        exit 1
      fi
      status="$(instance_status 2>/dev/null || true)"
      if [[ "$status" == "RUNNING" ]]; then
        log "${INSTANCE} is RUNNING"
        exit 0
      fi
      log "Current status: ${status:-UNKNOWN}; polling again in ${STATUS_POLL_SECONDS}s"
      sleep "$STATUS_POLL_SECONDS"
    done
  fi

  if is_stockout_error "$start_output"; then
    log "GPU capacity unavailable right now; retrying in ${RETRY_SECONDS}s"
    sleep "$RETRY_SECONDS"
    continue
  fi

  echo "$start_output" >&2
  log "Start failed with a non-retryable error"
  exit "$start_rc"
done
