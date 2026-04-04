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
STATE_DIR="${GCE_T4_STATE_DIR:-/tmp/op-clipper-t4-gce}"
INSTANCE="${GCE_INSTANCE:-}"
ZONE="${GCE_ZONE:-}"

usage() {
  cat <<'EOF'
Delete the temp T4 VM recorded in the local state dir or passed explicitly.

Usage:
  delete_t4_gce_instance.sh [options]

Options:
  --project <project>
  --state-dir <dir>
  --instance <name>
  --zone <zone>
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT="$2"
      shift 2
      ;;
    --state-dir)
      STATE_DIR="$2"
      shift 2
      ;;
    --instance)
      INSTANCE="$2"
      shift 2
      ;;
    --zone)
      ZONE="$2"
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

if [[ -z "${INSTANCE}" && -f "${STATE_DIR}/instance-name" ]]; then
  INSTANCE="$(<"${STATE_DIR}/instance-name")"
fi
if [[ -z "${ZONE}" && -f "${STATE_DIR}/zone" ]]; then
  ZONE="$(<"${STATE_DIR}/zone")"
fi

if [[ -z "${PROJECT}" || -z "${INSTANCE}" || -z "${ZONE}" ]]; then
  echo "Need project, instance, and zone. Set them in .env, state, or flags." >&2
  exit 2
fi

if ! gcloud compute instances describe "${INSTANCE}" --project "${PROJECT}" --zone "${ZONE}" --format='get(name)' >/dev/null 2>&1; then
  echo "Instance ${INSTANCE} not found in ${PROJECT}/${ZONE}; clearing local state." >&2
  rm -f "${STATE_DIR}/instance-name" "${STATE_DIR}/zone"
  exit 0
fi

gcloud compute instances delete "${INSTANCE}" \
  --project "${PROJECT}" \
  --zone "${ZONE}" \
  --quiet

rm -f "${STATE_DIR}/instance-name" "${STATE_DIR}/zone"
printf '{"instance":"%s","zone":"%s","status":"deleted"}\n' "${INSTANCE}" "${ZONE}"
