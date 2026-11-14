#!/usr/bin/env python3
"""Farmers Helpers web server (Python standard library only, nothing to install).

    python3 server.py              # then open http://localhost:8000
    PORT=8080 python3 server.py

GET /api/analyze?address=...   full report for an address
GET /api/health                checks the server is up and the SerpAPI key is set
Everything else is served from public/.
"""

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from farmhelper.analyze import analyze
from farmhelper.net import load_env
from farmhelper.serp import SerpError

PUBLIC = Path(__file__).resolve().parent / "public"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/health":
            return self.send_json({"ok": True, "serpapi_key": bool(os.environ.get("SERPAPI_API_KEY"))})
        if url.path == "/api/analyze":
            address = (parse_qs(url.query).get("address") or [""])[0].strip()
            if not address or len(address) > 200:
                return self.send_json({"error": "Type an address (up to 200 characters)."}, 400)
            try:
                report = analyze(address)
            except SerpError as e:
                return self.send_json({"error": f"Search failed: {e}"}, 502)
            return self.send_json(report, 422 if "error" in report else 200)
        return super().do_GET()

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Keep logs short and never print query strings (addresses are personal)
        sys.stderr.write(f"{self.command} {urlparse(self.path).path} {args[1] if len(args) > 1 else ''}\n")


def main():
    load_env()
    port = int(os.environ.get("PORT", 8000))
    if not os.environ.get("SERPAPI_API_KEY"):
        print("Warning: SERPAPI_API_KEY not set (add it to .env); address search won't work.")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Farmers Helpers running at http://localhost:{port}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
