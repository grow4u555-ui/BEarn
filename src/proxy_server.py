#!/usr/bin/env python3
"""
BEarn HTTP Proxy Server
Forwarding proxy that tracks traffic and credits earnings per user.
"""

import os
import sys
import time
import hashlib
import json
import http.server
import urllib.request
import urllib.error
import threading

# ── Add parent to path ─────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import (
    init_db, start_batch_worker, enqueue_log, enqueue_earn,
    get_user_by_token, calculate_earnings, get_user_balance, DB_PATH
)

PROXY_PORT = int(os.getenv("PROXY_PORT", "8080"))
AUTH_HEADER = "X-BEarn-Token"

class BEarnProxyHandler(http.server.BaseHTTPRequestHandler):
    """Handles HTTP CONNECT and regular proxy requests."""

    def do_CONNECT(self):
        """Handle HTTPS tunneling."""
        host, port = self.path.split(":")
        token = self.headers.get(AUTH_HEADER, "")
        user = self._authenticate(token)
        if not user:
            self.send_response(407)
            self.end_headers()
            return

        try:
            self.send_response(200)
            self.end_headers()
            # Tunnel established — traffic passes through
            # In production, read bytes and log them here
        except Exception as e:
            self.send_error(502, f"Tunnel failed: {e}")

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

   def do_PUT(self):
        self._handle_request("PUT")

    def do_DELETE(self):
        self._handle_request("DELETE")

    def do_PATCH(self):
        self._handle_request("PATCH")

    def do_HEAD(self):
        self._handle_request("HEAD")

    def _handle_request(self, method):
        """Handle a proxied HTTP request with earnings tracking."""
        token = self.headers.get(AUTH_HEADER, "")
        user = self._authenticate(token)
        if not user:
            self.send_response(407)
            self.send_header("Proxy-Authenticate", "Bearer realm=\"BEarn\"")
            self.end_headers()
            return

        start_time = time.time()
        body_bytes = 0
        status = 502
        resp_headers = {}

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        request_body = self.rfile.read(content_length) if content_length > 0 else b""

        # Build upstream URL
        path = self.path
        if not path.startswith("http"):
            path = f"http://{self.headers.get('Host', 'localhost')}{path}"

        try:
            req = urllib.request.Request(
                path,
                data=request_body if method in ("POST", "PUT", "PATCH") else None,
                headers={k: v for k, v in self.headers.items()
                         if k.lower() not in ("host", "proxy-connection", AUTH_HEADER.lower())},
                method=method
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                resp_body = resp.read()
                body_bytes = len(resp_body)
                resp_headers = dict(resp.headers)

                # Send response back to client
                self.send_response(status)
                for k, v in resp_headers.items():
                    if k.lower() not in ("transfer-encoding",):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(body_bytes))
                self.end_headers()
                self.wfile.write(resp_body)

        except urllib.error.HTTPError as e:
            status = e.code
            body_bytes = len(e.read())
            self.send_response(status)
            self.end_headers()
        except Exception as e:
            self.send_error(502, f"Proxy error: {e}")
            return

        duration_ms = int((time.time() - start_time) * 1000)
        host = self.headers.get("Host", "unknown")
        client_ip = self.client_address[0]
        ua = self.headers.get("User-Agent", "")

        # Calculate earnings
        rate = user["earning_rate"]
        earnings_amount = calculate_earnings(body_bytes, 0, rate)

        # Enqueue for batch insert
        enqueue_log(
            user_id=user["id"],
            method=method,
            host=host,
            path=path,
            status_code=status,
            bytes_sent=body_bytes,      # bytes sent to client
            bytes_recv=content_length,   # bytes received from client
            duration_ms=duration_ms,
            ip=client_ip,
            ua=ua
        )

        if earnings_amount > 0:
            enqueue_earn(
                user_id=user["id"],
                amount=earnings_amount,
                rate_used=rate,
                source="proxy",
                ref_id=None  # could link to log id with a 2-phase insert
            )

    def _authenticate(self, token):
        """Validate token and return user dict."""
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return get_user_by_token(token_hash)

    def log_message(self, format, *args):
        """Suppress default HTTP server logs; we track via DB."""
        if os.getenv("DEBUG"):
            print(f"[Proxy] {args}")


def run_proxy():
    """Start the BEarn proxy server."""
    init_db()
    start_batch_worker()

    server = http.server.HTTPServer(("0.0.0.0", PROXY_PORT), BEarnProxyHandler)
    print(f"[BEarn] Proxy server running on 0.0.0.0:{PROXY_PORT}")
    print(f"[BEarn] Database: {DB_PATH}")
    print(f"[BEarn] Clients must send X-BEarn-Token header")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[BEarn] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    run_proxy()
