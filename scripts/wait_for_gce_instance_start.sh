#!/usr/bin/env bash

set -euo pipefail

PROJECT="cowboy-471001"
ZONE="us-central1-a"
INSTANCE="op-clipper-nvidia-probe-17802-1"
RETRY_SECONDS=600
STATUS_POLL_SECONDS=20
TIMEOUT_SECONDS=$((6 * 60 * 60))

usage() {
  cat <<'EOF'
Wait for a GCE VM to start, retrying through temporary GPU stockouts.

Usage:
  wait_for_gce_instance_start.sh [options]

Options:
  --project <project>              GCP project id. Default: cowboy-471001
  --zone <zone>                    GCE zone. Default: us-central1-a
  --instance <name>                Instance name. Default: op-clipper-nvidia-probe-17802-1
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
