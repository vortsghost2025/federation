"""
_mock_server.py — Static file server with /map/data fixture interception.

Replaces the bare `python -m http.server` so the Galaxy Map can be tested
against synthetic data without involving the real Federation backend.

Usage:
    python _mock_server.py [port]
    default port: 8888

Endpoints:
    GET /<file>            → serve from federation-game/frontend/ (static)
    GET /map/data          → return synthetic JSON from _mock_map_data.py
    GET /mock/stop         → stop the server
    GET /mock/status       → 200 if running, JSON status payload
"""

import http.server
import socketserver
import sys
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "federation-game" / "frontend"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8888

# Import the fixture (path may differ)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _mock_map_data


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):
        # Quieter logging
        sys.stderr.write("[mock_server] %s %s\n" % (self.address_string(),
                                                    format % args))

    def do_GET(self):
        path = self.path.split("?")[0]

        # Mock /map/data
        if path == "/map/data":
            body = json.dumps(_mock_map_data.build_response()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Mock-Server", "true")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/mock/status":
            payload = json.dumps({
                "running": True,
                "fixture": "galaxy-map-integration-v1",
                "served_from": str(ROOT),
                "endpoints": ["GET /map/data (synthetic)",
                              "GET /<file> (static)",
                              "GET /mock/status"]
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/mock/stop":
            payload = b'{"stopped":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            # Schedule server shutdown after response is flushed
            threading.Thread(target=self.server.shutdown).start()
            return

        # Fall through to static file serving
        return super().do_GET()


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    if not ROOT.exists():
        print(f"ERROR: static root not found: {ROOT}", file=sys.stderr)
        sys.exit(1)

    with ThreadedTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"[mock_server] listening on http://127.0.0.1:{PORT}")
        print(f"[mock_server] serving static from {ROOT}")
        print(f"[mock_server] /map/data -> synthetic fixture")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
            print("[mock_server] stopped")


if __name__ == "__main__":
    main()
