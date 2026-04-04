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
STATE_DIR="${GCE_T4_STATE_DIR:-/tmp/op-clipper-t4-gce}"
COG_VERSION="${GCE_T4_COG_VERSION:-0.17.2}"

usage() {
  cat <<'EOF'
Prepare a T4 GCE VM for local Cog and RF-DETR CUDA debugging.

Usage:
  bootstrap_t4_gce_vm.sh [options]

Environment:
  GCE_PROJECT                     GCP project id.
  GCE_ZONE                        GCP zone.
  GCE_INSTANCE                    Instance name.
  GCE_T4_STATE_DIR                Temp state dir written by acquire_t4_gce_instance.sh.
  GCE_T4_COG_VERSION              Cog release to install. Default: 0.17.2

Options:
  --project <project>
  --zone <zone>
  --instance <name>
  --state-dir <dir>
  --cog-version <version>
  -h, --help
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
    --state-dir)
      STATE_DIR="$2"
      shift 2
      ;;
    --cog-version)
      COG_VERSION="$2"
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

require_value "GCE_PROJECT/--project" "${PROJECT}"
require_value "GCE_ZONE/--zone" "${ZONE}"
require_value "GCE_INSTANCE/--instance" "${INSTANCE}"

REMOTE_BOOTSTRAP="/tmp/bootstrap_t4_vm.sh"
LOCAL_BOOTSTRAP="$(mktemp "${TMPDIR:-/tmp}/bootstrap-t4-vm.XXXXXX.sh")"

cleanup() {
  rm -f "${LOCAL_BOOTSTRAP}"
}
trap cleanup EXIT

cat >"${LOCAL_BOOTSTRAP}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update -y
sudo apt-get install -y \
  docker.io \
  ffmpeg \
  git \
  git-lfs \
  build-essential \
  cmake \
  curl \
  rsync \
  unzip \
  python3-pip \
  python3-venv \
  jq \
  libnvidia-encode-580-server \
  libnvidia-decode-580-server

distribution=\$(. /etc/os-release; echo \$ID\$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL "https://nvidia.github.io/libnvidia-container/\${distribution}/libnvidia-container.list" | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

sudo apt-get update -y
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
sudo usermod -aG docker "\$USER"

if [[ ! -x "\$HOME/.local/bin/uv" ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

sudo curl -L --fail \
  "https://github.com/replicate/cog/releases/download/v${COG_VERSION}/cog_Linux_x86_64" \
  -o /usr/local/bin/cog
sudo chmod +x /usr/local/bin/cog

nvidia-smi
sudo docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
EOF

chmod +x "${LOCAL_BOOTSTRAP}"

gcloud compute scp \
  --project "${PROJECT}" \
  --zone "${ZONE}" \
  "${LOCAL_BOOTSTRAP}" \
  "${INSTANCE}:${REMOTE_BOOTSTRAP}" >/dev/null

gcloud compute ssh \
  --project "${PROJECT}" \
  --zone "${ZONE}" \
  "${INSTANCE}" \
  --command="bash ${REMOTE_BOOTSTRAP}"
