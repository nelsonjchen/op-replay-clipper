#!/bin/sh

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
    git-lfs \
    git

# Setup git lfs
git lfs install

# Blow away existing openpilot folder if it exists
rm -rf /home/batman/openpilot || true

git clone --depth 1 --recurse-submodules https://github.com/commaai/openpilot /home/batman/openpilot

cd /home/batman/openpilot || exit

# Compile openpilot UI and replay
export POETRY_VIRTUALENVS_CREATE=false
export PYENV_VERSION=3.11.4
export PYENV_ROOT="/root/.pyenv_openpilot"
export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"

# Install python dependencies
./tools/ubuntu_setup.sh

 rm -rf /tmp/* && \
    rm -rf /root/.cache && \
    pip uninstall -y poetry && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /tmp/*

# Replicate.com unfortunately has a very small /dev/shm, so we need to use /var/tmp instead
find . -type f -exec sed -i 's/\/dev\/shm/\/var\/tmp/g' {} \;

# Replace default segment size to a smaller size
find . -type f -exec sed -i 's/#define DEFAULT_SEGMENT_SIZE (10 \* 1024 \* 1024)/#define DEFAULT_SEGMENT_SIZE (3 \* 1024 \* 1024)/g' {} \;

# Replace "constexpr int MIN_SEGMENTS_CACHE = 5;" smaller amount
# in tools/replay/replay.h as for some reason the argument does not appear to be working
sed -i 's/constexpr int MIN_SEGMENTS_CACHE = 5;/constexpr int MIN_SEGMENTS_CACHE = 3;/g' tools/replay/replay.h

scons -j8 tools/replay/replay selfdrive/ui/_ui

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

# Blow away pyenv used to build openpilot
rm -rf /root/.pyenv_openpilot

# Compile libstrangle for FPS cap tool, install it, and then remove the source
cd / || exit
rm -rf /home/robin/libstrangle || true
git clone --depth 1 https://gitlab.com/torkel104/libstrangle /home/robin/libstrangle
cd /home/robin/libstrangle
make install-common install-native install-ld
cd / || exit
rm -rf /home/robin/libstrangle
