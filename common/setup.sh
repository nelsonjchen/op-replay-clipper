#!/bin/bash

set -xe

# Shared script to setup OP environment for DevContainers and Cog

# Set Debian noninteractive mode
export DEBIAN_FRONTEND=noninteractive

apt-get update -y && apt-get install -y \
    `# For Replay` \
    jq \
    tigervnc-standalone-server \
    ffmpeg \
    faketime \
    eatmydata \
    tmux \
    `# For Debugging stuff` \
    htop \
    mesa-utils \
    `# For hardware accelerated rendering` \
    xserver-xorg-video-nvidia-525 \
    `# For script calcuation` \
    bc \
    `# For network monitoring` \
    net-tools \
    `# Missing in the base cog image` \
    sudo \
    wget \
    curl \
    capnproto \
    git-lfs \
    tzdata \
    zstd \
    git

# # Setup git lfs
git lfs install

# # Blow away existing openpilot folder if it exists
rm -rf /home/batman/openpilot || true

git clone --depth 1 --recurse-submodules https://github.com/commaai/openpilot /home/batman/openpilot

cd /home/batman/openpilot || exit

# # Install dependencies (upstream script names changed)
if [ -x ./tools/setup_dependencies.sh ]; then
  ./tools/setup_dependencies.sh
elif [ -x ./tools/ubuntu_setup.sh ]; then
  INSTALL_EXTRA_PACKAGES=yes ./tools/ubuntu_setup.sh
  ./tools/install_python_dependencies.sh
else
  echo "No supported openpilot dependency setup scripts found" >&2
  exit 1
fi
if [ -x /root/.local/bin/uv ]; then
  ln -sf /root/.local/bin/uv /usr/local/bin/uv
fi
export PATH="/root/.local/bin:$PATH"

# Some dependency tarballs in the Linux container land without exec bits on vendored tools.
find .venv/lib -type f \( -name 'arm-none-eabi-*' -o -name 'capnp' -o -name 'capnpc*' -o -name 'ffmpeg' -o -name 'ffprobe' \) -exec chmod +x {} + || true

# Build native modules and generated solver bindings used by tools/clip/run.py
uv run scons -j8 \
    msgq_repo/msgq/ipc_pyx.so \
    msgq_repo/msgq/visionipc/visionipc_pyx.so \
    common/params_pyx.so \
    selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so \
    selfdrive/controls/lib/lateral_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so

# Generate bitmap font atlases so recorded UI text uses proper fonts
uv run python selfdrive/assets/fonts/process.py

rm -rf /tmp/* && \
    rm -rf /root/.cache && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /tmp/*

# Record checkout commit for debugging
git rev-parse HEAD > /home/batman/openpilot/COMMIT
