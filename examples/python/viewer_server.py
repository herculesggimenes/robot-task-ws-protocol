#!/usr/bin/env python3
"""Serve the robot-task-ws status viewer."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2] / "web"

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                self.path = "/viewer.html"
            return super().do_GET()

        def __init__(self, *handler_args, **handler_kwargs):
            super().__init__(*handler_args, directory=str(root), **handler_kwargs)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"viewer listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
