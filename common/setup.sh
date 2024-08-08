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

# # Install dependencies
INSTALL_EXTRA_PACKAGES=yes ./tools/ubuntu_setup.sh

rm -rf /tmp/* && \
    rm -rf /root/.cache && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /tmp/*

source /home/batman/openpilot/.venv/bin/activate

# # Compile openpilot UI and replay
scons -j8 tools/replay/replay selfdrive/ui/ui

# Only copy the folders we need from the build repo to /home/batman/openpilot_min
mkdir -p /home/batman/openpilot_min
mv /home/batman/openpilot/selfdrive /home/batman/openpilot_min
mv /home/batman/openpilot/tools /home/batman/openpilot_min
mv /home/batman/openpilot/third_party /home/batman/openpilot_min

# Get the commit used to build openpilot and save it to /home/batman/openpilot/COMMIT
git rev-parse HEAD > /home/batman/openpilot_min/COMMIT

# Blow away openpilot folder that was used to build openpilot_min
rm -rf /home/batman/openpilot
# Rename openpilot_min to openpilot
mv /home/batman/openpilot_min /home/batman/openpilot

