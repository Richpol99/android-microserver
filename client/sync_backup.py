#!/usr/bin/env python3
"""
MotoServer Sync & Backup Utility
Downloads an updated backup snapshot from MotoServer or pushes local modifications.
"""

import http.server
import socketserver
import threading
import urllib.request
import json
import ssl
import os
import tarfile
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
ARCHIVE_PATH = os.path.join(BASE_DIR, "motoserver_snapshot.tar.gz")

MOTOSERVER_URL = os.environ.get("MOTOSERVER_HOST", "https://your-domain.com")
PC_IP = os.environ.get("PC_LAN_IP", "192.168.1.50")
DEFAULT_AGENT_KEY = os.environ.get("MOTOSERVER_AGENT_KEY", "YOUR_AGENT_API_KEY")
PORT = 8099
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def pull_backup():
    print(f"Starting receiver on {PC_IP}:{PORT}...")
    received_event = threading.Event()

    class ReceiverHandler(http.server.BaseHTTPRequestHandler):
        def do_PUT(self):
            length = int(self.headers.get("Content-Length", 0))
            data = self.rfile.read(length)
            with open(ARCHIVE_PATH, "wb") as f:
                f.write(data)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            received_event.set()

        def log_message(self, format, *args):
            return

    server = socketserver.TCPServer(("0.0.0.0", PORT), ReceiverHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    remote_cmd = (
        "cd /root && "
        "tar --exclude='dashboard/temp_music_cache' --exclude='dashboard/downloads' "
        "--exclude='dashboard/*.log' --exclude='dashboard/__pycache__' "
        "-czf /tmp/motoserver_snapshot.tar.gz dashboard && "
        f"curl -s -X PUT --upload-file /tmp/motoserver_snapshot.tar.gz http://{PC_IP}:{PORT}/backup.tar.gz && "
        "rm -f /tmp/motoserver_snapshot.tar.gz && echo SNAPSHOT_SENT"
    )

    payload = json.dumps({
        "prompt": f"Por favor ejecuta en bash con run_command: {remote_cmd}",
        "conversation_id": "",
        "workspace": "/root/dashboard",
        "effort": "low"
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{MOTOSERVER_URL}/api/agent/stream",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_UA,
            "Authorization": f"Bearer {DEFAULT_AGENT_KEY}"
        }
    )

    print("Requesting snapshot from MotoServer...")
    with urllib.request.urlopen(req, context=ctx, timeout=40) as resp:
        for line in resp:
            t_line = line.decode("utf-8", errors="replace").strip()
            if "SNAPSHOT_SENT" in t_line or "result" in t_line:
                break

    received = received_event.wait(timeout=25)
    server.shutdown()

    if received and os.path.exists(ARCHIVE_PATH):
        mb = os.path.getsize(ARCHIVE_PATH) / (1024 * 1024)
        print(f"Snapshot received: {mb:.2f} MB. Updating server/ directory...")
        with tarfile.open(ARCHIVE_PATH, "r:gz") as tar:
            tar.extractall(path=BASE_DIR)
        dash = os.path.join(BASE_DIR, "dashboard")
        if os.path.exists(dash):
            if os.path.exists(SERVER_DIR):
                import shutil
                shutil.rmtree(SERVER_DIR)
            os.rename(dash, SERVER_DIR)
        os.remove(ARCHIVE_PATH)
        print("Backup pull completed successfully!")
    else:
        print("Failed to receive snapshot from MotoServer.")


if __name__ == "__main__":
    pull_backup()
