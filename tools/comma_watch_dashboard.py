#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_STATE_PATH = "/tmp/comma-watch-state.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local dashboard for the Comma watcher.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the local dashboard server.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind the local dashboard server.")
    parser.add_argument("--state-path", default=DEFAULT_STATE_PATH, help="Watcher JSON state snapshot path.")
    return parser.parse_args()


def load_html() -> bytes:
    html_path = Path(__file__).with_name("comma_watch_dashboard.html")
    return html_path.read_bytes()


def load_state(state_path: Path) -> bytes:
    if not state_path.exists():
        return json.dumps(
            {
                "generated_at": None,
                "window_start": None,
                "devices": [],
                "message": "Waiting for watcher state...",
            }
        ).encode("utf-8")
    return state_path.read_bytes()


def make_handler(*, html: bytes, state_path: Path) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/", "/index.html"}:
                self._send_bytes(HTTPStatus.OK, html, "text/html; charset=utf-8")
                return
            if self.path.startswith("/state"):
                self._send_bytes(HTTPStatus.OK, load_state(state_path), "application/json; charset=utf-8")
                return
            if self.path == "/health":
                self._send_bytes(HTTPStatus.OK, b"ok\n", "text/plain; charset=utf-8")
                return
            self._send_bytes(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def main() -> int:
    args = parse_args()
    html = load_html()
    state_path = Path(args.state_path)
    handler = make_handler(html=html, state_path=state_path)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Watcher dashboard: http://{args.host}:{args.port}")
    print(f"Reading watcher state from {state_path}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
