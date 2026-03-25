#!/usr/bin/env bash

set -euo pipefail

# Shared bootstrap for Docker/Cog images that need a working openpilot clip environment.

OPENPILOT_ROOT="${OPENPILOT_ROOT:-/home/batman/openpilot}"
OPENPILOT_REPO_URL="${OPENPILOT_REPO_URL:-https://github.com/commaai/openpilot.git}"
OPENPILOT_BRANCH="${OPENPILOT_BRANCH:-master}"
OPENPILOT_CLONE_DEPTH="${OPENPILOT_CLONE_DEPTH:-1}"
SCONS_JOBS="${SCONS_JOBS:-$(command -v nproc >/dev/null 2>&1 && nproc || echo 8)}"
export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

APT_PACKAGES=(
  jq
  tigervnc-standalone-server
  ffmpeg
  faketime
  eatmydata
  htop
  mesa-utils
  xserver-xorg-video-nvidia-525
  bc
  net-tools
  sudo
  wget
  curl
  capnproto
  git-lfs
  tzdata
  zstd
  git
)

log_step() {
  printf '\n==> %s\n' "$1"
}

install_system_packages() {
  log_step "Installing system packages"
  apt-get update -y
  apt-get install -y "${APT_PACKAGES[@]}"
}

configure_git_lfs() {
  log_step "Configuring git-lfs"
  git lfs install
}

clone_openpilot_checkout() {
  log_step "Cloning openpilot into ${OPENPILOT_ROOT}"
  rm -rf "${OPENPILOT_ROOT}"
  git clone \
    --branch "${OPENPILOT_BRANCH}" \
    --depth "${OPENPILOT_CLONE_DEPTH}" \
    --filter=blob:none \
    --recurse-submodules \
    --shallow-submodules \
    --single-branch \
    "${OPENPILOT_REPO_URL}" \
    "${OPENPILOT_ROOT}"
}

install_openpilot_dependencies() {
  log_step "Installing openpilot dependencies"
  cd "${OPENPILOT_ROOT}"

  if [[ -x ./tools/setup_dependencies.sh ]]; then
    ./tools/setup_dependencies.sh
    return
  fi

  if [[ -x ./tools/ubuntu_setup.sh ]]; then
    INSTALL_EXTRA_PACKAGES=yes ./tools/ubuntu_setup.sh
    ./tools/install_python_dependencies.sh
    return
  fi

  echo "No supported openpilot dependency setup scripts found" >&2
  exit 1
}

ensure_uv_on_path() {
  if [[ -x /root/.local/bin/uv ]]; then
    ln -sf /root/.local/bin/uv /usr/local/bin/uv
  fi
  export PATH="/root/.local/bin:${PATH}"
}

fix_vendored_tool_permissions() {
  if [[ ! -d "${OPENPILOT_ROOT}/.venv/lib" ]]; then
    return
  fi

  log_step "Fixing vendored tool permissions"
  find "${OPENPILOT_ROOT}/.venv/lib" -type f \
    \( -name 'arm-none-eabi-*' -o -name 'capnp' -o -name 'capnpc*' -o -name 'ffmpeg' -o -name 'ffprobe' \) \
    -exec chmod +x {} + || true
}

build_openpilot_clip_dependencies() {
  log_step "Building native openpilot clip dependencies"
  cd "${OPENPILOT_ROOT}"
  uv run scons -j"${SCONS_JOBS}" \
    msgq_repo/msgq/ipc_pyx.so \
    msgq_repo/msgq/visionipc/visionipc_pyx.so \
    common/params_pyx.so \
    selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so \
    selfdrive/controls/lib/lateral_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so
}

generate_ui_fonts() {
  log_step "Generating UI font atlases"
  cd "${OPENPILOT_ROOT}"
  uv run python selfdrive/assets/fonts/process.py
}

record_checkout_commit() {
  log_step "Recording openpilot commit"
  cd "${OPENPILOT_ROOT}"
  git rev-parse HEAD > "${OPENPILOT_ROOT}/COMMIT"
}

clean_image_artifacts() {
  log_step "Cleaning bootstrap caches"
  rm -rf /tmp/*
  rm -rf /root/.cache
  rm -rf /var/lib/apt/lists/*
}

main() {
  install_system_packages
  configure_git_lfs
  clone_openpilot_checkout
  install_openpilot_dependencies
  ensure_uv_on_path
  fix_vendored_tool_permissions
  build_openpilot_clip_dependencies
  generate_ui_fonts
  record_checkout_commit
  clean_image_artifacts
}

main "$@"
