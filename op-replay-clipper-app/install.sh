#!/usr/bin/env bash
set -euo pipefail

# OP Replay Clipper App — Installer
# Sets up the pywebview native-window launcher.

info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m    %s\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL]\033[0m  %s\n' "$*"; exit 1; }

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="${CLIPPER_REPO_DIR:-$(dirname "$APP_DIR")/op-replay-clipper}"

# Check Python
command -v python3 &>/dev/null || fail "Python 3 is required. Install it first."
ok "Python 3 found"

# Install Python dependencies
info "Installing Python dependencies..."
pip install --user -r "$APP_DIR/requirements.txt" || pip install -r "$APP_DIR/requirements.txt"
ok "Python dependencies installed"

# Check for pywebview GTK dependency on Linux
if [[ "$(uname)" == "Linux" ]]; then
    python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null || {
        info "Installing GTK3 dependencies for pywebview..."
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y python3-gobject gtk3 webkit2gtk4.1
        else
            fail "Cannot auto-install GTK3. Install PyGObject and WebKitGTK manually."
        fi
    }
    ok "GTK3/WebKitGTK available"
fi

# Check that the main clipper repo exists and has Docker images
if [ ! -f "$REPO_DIR/docker-compose.yml" ]; then
    info "Main clipper repo not found at $REPO_DIR"
    info "Cloning..."
    git clone --depth 1 https://github.com/mhayden123/op-replay-clipper.git "$REPO_DIR"
fi

if ! docker image inspect op-replay-clipper-render &>/dev/null 2>&1; then
    info "Docker images not built. Running clipper install..."
    cd "$REPO_DIR" && bash install.sh
fi

ok "Setup complete!"
echo ""
echo "  Run:  python3 $APP_DIR/app.py"
echo ""
