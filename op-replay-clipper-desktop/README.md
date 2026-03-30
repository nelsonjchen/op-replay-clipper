# OP Replay Clipper — Desktop App

A native desktop application for [op-replay-clipper](https://github.com/mhayden123/op-replay-clipper), built with [Tauri](https://tauri.app/). Uses the system webview (WebKitGTK on Linux) for a lightweight ~10 MB binary instead of bundling Chromium.

## How it works

1. On launch, starts the Docker-based web server (`docker compose up web`)
2. Waits for the server health check to pass
3. Opens `http://localhost:7860` in a native app window
4. When you close the window, Docker services are automatically stopped

## Prerequisites

- The [op-replay-clipper](https://github.com/mhayden123/op-replay-clipper) repo with Docker images built
- Rust (installed automatically by `install.sh`)
- Node.js 18+
- Linux: WebKitGTK 4.1 dev libraries

## Quick start

```bash
# Full setup: installs deps, builds clipper Docker images, builds the native binary
./install.sh

# Run in development mode
npm run tauri dev

# Or run the built binary directly
./src-tauri/target/release/op-replay-clipper-desktop
```

## Configuration

Set `CLIPPER_REPO_DIR` to point to your op-replay-clipper checkout:

```bash
CLIPPER_REPO_DIR=~/path/to/op-replay-clipper ./src-tauri/target/release/op-replay-clipper-desktop
```

## Building distributable packages

After `./install.sh`, find packages in:
- `src-tauri/target/release/bundle/deb/` — `.deb` for Debian/Ubuntu
- `src-tauri/target/release/bundle/rpm/` — `.rpm` for Fedora/RHEL
- `src-tauri/target/release/bundle/appimage/` — `.AppImage` (portable)
