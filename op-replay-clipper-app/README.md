# OP Replay Clipper — Native Window App

A lightweight Python app that opens the [op-replay-clipper](https://github.com/mhayden123/op-replay-clipper) web UI in a native OS window using [pywebview](https://pywebview.flowrl.com/). No browser tab needed.

## How it works

1. Starts the Docker-based web server (`docker compose up web`) in the background
2. Waits for the server to be ready
3. Opens `http://localhost:7860` in a native window (GTK/WebKitGTK on Linux)
4. When you close the window, Docker services are automatically stopped

## Prerequisites

- The [op-replay-clipper](https://github.com/mhayden123/op-replay-clipper) repo cloned and Docker images built (see its README)
- Python 3.10+
- On Linux: GTK3 and WebKitGTK (`python3-gi`, `gir1.2-webkit2-4.1`)

## Quick start

```bash
# Install dependencies
./install.sh

# Launch the app
python3 app.py
```

## Configuration

Set `CLIPPER_REPO_DIR` to point to your op-replay-clipper checkout if it's not in the default location:

```bash
CLIPPER_REPO_DIR=~/path/to/op-replay-clipper python3 app.py
```

The app searches these locations by default:
- `../op-replay-clipper` (sibling directory)
- `~/op-replay-clipper`
- `~/Desktop/op-replay-clipper`
