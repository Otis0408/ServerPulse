#!/usr/bin/env python3
"""
ServerPulse - Server-side monitoring agent.
Collects system metrics and exposes them via a lightweight HTTP API.
"""

import http.server
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import base64
import hashlib
import signal

# ─── Config ───
DEFAULT_PORT = 9730
TOKEN_FILE = os.path.expanduser("~/.serverpulse_token")

# ─── Metrics Collector ───

class MetricsCollector:
    def __init__(self):
        self._prev_net = None
        self._prev_time = None

    def collect(self):
        m = {}
        m["ts"] = time.time()
        m["hostname"] = socket.gethostname()
        m["cpu"] = self._cpu()
        m["mem"] = self._mem()
        m["disk"] = self._disk()
        m["net"] = self._net()
        m["load"] = self._load()
        m["uptime"] = self._uptime()
        return m

    def _cpu(self):
        try:
            out = subprocess.check_output(
                ["top", "-bn1"], stderr=subprocess.DEVNULL, timeout=5
            ).decode()
            for line in out.splitlines():
                if "%Cpu" in line:
                    for part in line.split(","):
                        if "id" in part:
                            idle = float(part.split()[0])
                            return {"usage": round(100.0 - idle, 1)}
        except Exception:
            pass
        return {"usage": 0.0}

    def _mem(self):
        try:
            out = subprocess.check_output(["free", "-b"], timeout=5).decode()
            for line in out.splitlines():
                if line.startswith("Mem:"):
                    p = line.split()
                    total, used, available = int(p[1]), int(p[2]), int(p[6])
                    return {
                        "total": total, "used": used, "available": available,
                        "usage": round((total - available) / total * 100, 1) if total else 0,
                    }
        except Exception:
            pass
        return {"total": 0, "used": 0, "available": 0, "usage": 0}

    def _disk(self):
        try:
            out = subprocess.check_output(["df", "-B1", "/"], timeout=5).decode()
            line = out.strip().splitlines()[-1]
            p = line.split()
            total, used, avail = int(p[1]), int(p[2]), int(p[3])
            return {
                "total": total, "used": used, "avail": avail,
                "usage": round(used / total * 100, 1) if total else 0,
            }
        except Exception:
            pass
        return {"total": 0, "used": 0, "avail": 0, "usage": 0}

    def _net(self):
        now = time.time()
        rx_bytes = tx_bytes = 0
        iface = "?"
        try:
            with open("/proc/net/dev") as f:
                for line in f:
                    line = line.strip()
                    if any(line.startswith(prefix) for prefix in ("eth", "ens", "enp")):
                        parts = line.split()
                        iface = parts[0].rstrip(":")
                        rx_bytes = int(parts[1])
                        tx_bytes = int(parts[9])
                        break
        except Exception:
            pass

        rx_speed = tx_speed = 0.0
        if self._prev_net and self._prev_time:
            dt = now - self._prev_time
            if dt > 0:
                rx_speed = max(0, (rx_bytes - self._prev_net[0]) / dt)
                tx_speed = max(0, (tx_bytes - self._prev_net[1]) / dt)
        self._prev_net = (rx_bytes, tx_bytes)
        self._prev_time = now

        return {
            "iface": iface,
            "rx_bytes": rx_bytes, "tx_bytes": tx_bytes,
            "rx_speed": round(rx_speed, 1), "tx_speed": round(tx_speed, 1),
        }

    def _load(self):
        try:
            with open("/proc/loadavg") as f:
                p = f.read().split()
                return {"1m": p[0], "5m": p[1], "15m": p[2]}
        except Exception:
            return {"1m": "0", "5m": "0", "15m": "0"}

    def _uptime(self):
        try:
            out = subprocess.check_output(["uptime", "-p"], timeout=5).decode().strip()
            return out
        except Exception:
            return "N/A"


# ─── HTTP Handler ───

collector = MetricsCollector()

class MetricsHandler(http.server.BaseHTTPRequestHandler):
    auth_token = None

    def log_message(self, fmt, *args):
        pass  # Suppress request logs

    def do_GET(self):
        # Auth check
        token = self.headers.get("Authorization", "").replace("Bearer ", "")
        if token != self.auth_token:
            self.send_error(401, "Unauthorized")
            return

        if self.path == "/metrics":
            data = collector.collect()
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"pong")
        else:
            self.send_error(404)


# ─── Main ───

def get_public_ip():
    """Try to detect the public IP."""
    for url in ["https://ifconfig.me", "https://api.ipify.org", "https://icanhazip.com"]:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
            return urllib.request.urlopen(req, timeout=5).read().decode().strip()
        except Exception:
            continue
    return "YOUR_SERVER_IP"


def generate_connection_code(host, port, token):
    payload = json.dumps({"h": host, "p": port, "t": token}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def load_or_create_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    token = secrets.token_urlsafe(24)
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    os.chmod(TOKEN_FILE, 0o600)
    return token


def main():
    port = DEFAULT_PORT
    print_code_only = False
    for arg in sys.argv[1:]:
        if arg == "--print-code":
            print_code_only = True
        else:
            try:
                port = int(arg)
            except ValueError:
                pass

    token = load_or_create_token()
    MetricsHandler.auth_token = token

    ip = get_public_ip()
    code = generate_connection_code(ip, port, token)

    if print_code_only:
        print(code)
        sys.exit(0)

    # Warm up collector (first reading has no speed delta)
    collector.collect()

    server = http.server.HTTPServer(("0.0.0.0", port), MetricsHandler)

    print("=" * 56)
    print("  ServerPulse Agent - Running")
    print("=" * 56)
    print(f"  Server:  {ip}:{port}")
    print(f"  Status:  ✓ Listening")
    print()
    print("  ┌─ Connection Code (paste into Mac app) ─┐")
    print(f"  │ {code}")
    print("  └─────────────────────────────────────────┘")
    print()
    print("  Press Ctrl+C to stop")
    print("=" * 56)
    sys.stdout.flush()

    def handle_signal(sig, frame):
        print("\n  Shutting down...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    server.serve_forever()


if __name__ == "__main__":
    main()
