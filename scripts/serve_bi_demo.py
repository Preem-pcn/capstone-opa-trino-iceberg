"""Loopback-only QAR demo server. Issues short-lived tokens for one dashboard.

The demo has one shared, read-only Trino identity (safety_analyst), not per-user SSO.
No Metabase admin credentials, embedding secret, or arbitrary file access is
exposed by this server. Keep it bound to loopback for the local demonstration.
"""

import argparse
import base64
import hashlib
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".secrets/metabase-embed.json"
PAGE = ROOT / "bi/web/qar-flight-analytics-capstone-metabase.html"


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def embed_info():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    now = int(time.time())
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64url(json.dumps({"resource": {"dashboard": int(config["dashboard_id"])},
                                "params": {}, "iat": now, "exp": now + 600}, separators=(",", ":")).encode())
    unsigned = header + "." + payload
    signature = b64url(hmac.new(config["secret"].encode(), unsigned.encode(), hashlib.sha256).digest())
    token = unsigned + "." + signature
    return {"embed_url": config["metabase_url"].rstrip("/") + "/embed/dashboard/" + token + "#bordered=false&titled=false",
            "refresh_after_seconds": 480, "dashboard_id": int(config["dashboard_id"]),
            "query_identity": "safety_analyst"}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data, content_type="application/json; charset=utf-8", headers=None):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if self.headers.get("Host") not in {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}:
            self.reply(403, {"error": "Use the loopback demo URL."})
            return
        try:
            if path == "/api/bi/health":
                self.reply(200, {"service": "qar-capstone-metabase-demo", "configured": CONFIG.is_file(),
                                 "page_ready": PAGE.is_file()})
            elif path == "/api/bi/embed":
                self.reply(200, embed_info())
            elif path == "/metabase":
                self.reply(302, b"", headers={"Location": embed_info()["embed_url"]})
            elif path in {"/", "/" + PAGE.name}:
                self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/favicon.ico":
                self.reply(204, b"", "image/x-icon")
            else:
                self.reply(404, {"error": "Not found"})
        except (FileNotFoundError, KeyError, ValueError):
            self.reply(503, {"error": "Run setup_bi_demo.py to configure the local embedded dashboard."})

    def log_message(self, fmt, *args):
        # Do not log URLs containing tokens or arbitrary client-supplied strings.
        print(f"{self.command} {urlsplit(self.path).path.split('?')[0]}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"QAR Gold Reports: http://localhost:{args.port}/#gold", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
