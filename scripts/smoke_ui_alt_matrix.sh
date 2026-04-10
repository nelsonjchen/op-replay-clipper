#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

OUTPUT_DIR="${SMOKE_OUTPUT_DIR:-${REPO_ROOT}/shared/ui-alt-matrix-smoke}"
ACCEL="${SMOKE_ACCEL:-auto}"
SYNC_REPO="${SMOKE_SYNC_REPO:-1}"
OPENPILOT_DIR="${SMOKE_OPENPILOT_DIR:-${REPO_ROOT}/.cache/openpilot-local}"
SKIP_DOWNLOAD="${SMOKE_SKIP_DOWNLOAD:-0}"
WINDOWED="${SMOKE_WINDOWED:-0}"

usage() {
  cat <<'EOF'
Render a local UI smoke matrix across the seeded public mici and tici routes.

Usage:
  smoke_ui_alt_matrix.sh [options]

Environment:
  SMOKE_OUTPUT_DIR       Output directory for artifacts
  SMOKE_ACCEL            Local accel mode: auto, cpu, videotoolbox, nvidia
  SMOKE_SYNC_REPO        1 to run uv sync first. Default: 1
  SMOKE_OPENPILOT_DIR    Openpilot checkout to reuse
  SMOKE_SKIP_DOWNLOAD    1 to reuse existing route data only
  SMOKE_WINDOWED         1 to render with a visible window

Options:
  --output-dir <dir>         Output directory for artifacts
  --accel <mode>             Local accel mode: auto, cpu, videotoolbox, nvidia
  --openpilot-dir <dir>      Openpilot checkout to reuse
  --skip-sync-repo           Skip the initial uv sync
  --skip-download            Reuse existing route data only
  --windowed                 Render with a visible window
  -h, --help                 Show this help text
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

run_ffprobe() {
  local output_path="$1"
  ffprobe \
    -v error \
    -select_streams v:0 \
    -show_entries stream=codec_name,width,height,pix_fmt \
    -show_entries format=duration,size \
    -of json \
    "${output_path}" > "${output_path}.ffprobe.json"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --accel)
      ACCEL="$2"
      shift 2
      ;;
    --openpilot-dir)
      OPENPILOT_DIR="$2"
      shift 2
      ;;
    --skip-sync-repo)
      SYNC_REPO="0"
      shift
      ;;
    --skip-download)
      SKIP_DOWNLOAD="1"
      shift
      ;;
    --windowed)
      WINDOWED="1"
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

mkdir -p "${OUTPUT_DIR}"

if [[ "${SYNC_REPO}" != "0" ]]; then
  log "Syncing repo environment with uv"
  uv sync
fi

openpilot_args=(
  --openpilot-dir "${OPENPILOT_DIR}"
)
if [[ -x "${OPENPILOT_DIR}/.venv/bin/python" ]]; then
  openpilot_args+=(--skip-openpilot-update --skip-openpilot-bootstrap)
fi

common_args=(
  --file-format h264
  --accel "${ACCEL}"
)
if [[ "${SKIP_DOWNLOAD}" != "0" ]]; then
  common_args+=(--skip-download)
fi
if [[ "${WINDOWED}" != "0" ]]; then
  common_args+=(--windowed)
fi

routes=(
  "mici-baseline|5beb9b58bd12b691|0000010a--a51155e496|90|2"
  "tici-baseline|a2a0ccea32023010|2023-07-27--13-01-19|110|2"
)

cases=(
  "ui||ui"
  "ui-alt|device|ui-alt-device"
  "ui-alt|stacked_forward_over_wide|ui-alt-stacked-forward-over-wide"
  "ui-alt|stacked_wide_over_forward|ui-alt-stacked-wide-over-forward"
)

manifest_path="${OUTPUT_DIR}/manifest.txt"
{
  echo "UI smoke matrix"
  echo "output_dir=${OUTPUT_DIR}"
  echo
} > "${manifest_path}"

for route_spec in "${routes[@]}"; do
  IFS='|' read -r route_label dongle_id route_slug start_seconds length_seconds <<< "${route_spec}"
  route_id="${dongle_id}|${route_slug}"

  log "Rendering route set ${route_label} (${route_id})"
  {
    echo "[${route_label}]"
    echo "route=${route_id}"
    echo "start_seconds=${start_seconds}"
    echo "length_seconds=${length_seconds}"
  } >> "${manifest_path}"

  for case_spec in "${cases[@]}"; do
    IFS='|' read -r render_type ui_alt_variant output_stub <<< "${case_spec}"
    output_path="${OUTPUT_DIR}/${route_label}-${output_stub}.mp4"
    cmd=(
      uv run python "${REPO_ROOT}/clip.py"
      "${render_type}"
      "${route_id}"
      --start-seconds "${start_seconds}"
      --length-seconds "${length_seconds}"
      "${common_args[@]}"
      "${openpilot_args[@]}"
      --output "${output_path}"
    )
    if [[ -n "${ui_alt_variant}" ]]; then
      cmd+=(--ui-alt-variant "${ui_alt_variant}")
    fi

    log "  ${output_stub} -> ${output_path}"
    "${cmd[@]}"
    run_ffprobe "${output_path}"
    {
      echo "${output_stub}=${output_path}"
      echo "${output_stub}.ffprobe=${output_path}.ffprobe.json"
    } >> "${manifest_path}"
  done

  echo >> "${manifest_path}"
done

log "Smoke artifacts written to ${OUTPUT_DIR}"
log "Manifest written to ${manifest_path}"
