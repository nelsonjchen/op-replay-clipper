#!/usr/bin/env bash
set -euo pipefail

# OP Replay Clipper — Local Docker Setup
# Checks prerequisites, builds Docker images, and prepares the launcher.

REPO_URL="https://github.com/mhayden123/op-replay-clipper.git"
BRANCH="claude/local-docker-rendering-Cb1Is"
RENDER_IMAGE="op-replay-clipper-render"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m    %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL]\033[0m  %s\n' "$*"; exit 1; }

check_command() {
    if ! command -v "$1" &>/dev/null; then
        fail "$1 is not installed. $2"
    fi
    ok "$1 found"
}

# ---------------------------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------------------------

info "Checking prerequisites..."

check_command docker \
    "Install Docker Engine: https://docs.docker.com/engine/install/"

docker compose version &>/dev/null \
    || fail "Docker Compose V2 not available. Update Docker or install the compose plugin."
ok "Docker Compose V2 available"

docker info &>/dev/null \
    || fail "Docker daemon is not running. Start it with: sudo systemctl start docker"
ok "Docker daemon is running"

# Check docker permissions (can current user talk to Docker?)
if ! docker ps &>/dev/null 2>&1; then
    warn "Current user cannot access Docker. You may need to:"
    warn "  sudo usermod -aG docker \$USER"
    warn "  Then log out and back in."
    warn ""
    warn "Trying with sudo for now..."
    DOCKER_PREFIX="sudo"
else
    DOCKER_PREFIX=""
fi

# NVIDIA GPU
if ! command -v nvidia-smi &>/dev/null; then
    fail "nvidia-smi not found. Install NVIDIA GPU drivers first."
fi
nvidia-smi --query-gpu=name --format=csv,noheader &>/dev/null \
    || fail "nvidia-smi cannot detect a GPU. Check your NVIDIA drivers."
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
ok "NVIDIA GPU detected: $GPU_NAME"

# NVIDIA Container Toolkit
if command -v nvidia-ctk &>/dev/null; then
    ok "NVIDIA Container Toolkit installed"
else
    warn "nvidia-ctk not found. The NVIDIA Container Toolkit may not be installed."
    warn "Install it: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
    warn "Continuing anyway — Docker GPU access may still work if configured manually."
fi

# Quick Docker GPU test
info "Testing Docker GPU access..."
if $DOCKER_PREFIX docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi &>/dev/null; then
    ok "Docker can access the GPU"
else
    fail "Docker cannot access the GPU. Install NVIDIA Container Toolkit:\n  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
fi

# ---------------------------------------------------------------------------
# 2. Ensure we're in the repo
# ---------------------------------------------------------------------------

if [ -f "docker-compose.yml" ] && [ -f "Dockerfile" ]; then
    info "Already inside the project directory"
    PROJECT_DIR="$(pwd)"
else
    info "Cloning repository..."
    CLONE_DIR="${HOME}/op-replay-clipper"
    if [ -d "$CLONE_DIR" ]; then
        info "Directory $CLONE_DIR already exists, pulling latest..."
        cd "$CLONE_DIR"
        git pull origin "$BRANCH" || true
    else
        git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$CLONE_DIR"
        cd "$CLONE_DIR"
    fi
    PROJECT_DIR="$CLONE_DIR"
fi

cd "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# 3. Build Docker images
# ---------------------------------------------------------------------------

info "Building Docker images (this may take 15-30 minutes on first run)..."
$DOCKER_PREFIX docker compose build

# Verify render image exists
if $DOCKER_PREFIX docker image inspect "$RENDER_IMAGE" &>/dev/null; then
    ok "Render image built: $RENDER_IMAGE"
else
    fail "Render image '$RENDER_IMAGE' was not created. Check build output above."
fi

ok "Web server image built"

# ---------------------------------------------------------------------------
# 4. Create shared directory
# ---------------------------------------------------------------------------

mkdir -p "$PROJECT_DIR/shared"

# ---------------------------------------------------------------------------
# 5. Done
# ---------------------------------------------------------------------------

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "=========================================="
echo ""
echo "  To start the web UI:"
echo "    cd $PROJECT_DIR"
echo "    ./start.sh"
echo ""
echo "  Then open http://localhost:7860"
echo ""
echo "=========================================="
