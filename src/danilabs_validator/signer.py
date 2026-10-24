"""Run the localnet-only signer as a different OS user from the PM2 worker."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import socket
import socketserver
import struct
import threading
import time
import datetime as dt

from .burn import BurnBlocked, BurnSigner
from .config import load_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    signer = BurnSigner(load_settings(args.config), args.state)
    allowed_uid = pwd.getpwnam("dani-validator").pw_uid
    latest = {"status": "starting"}
    lock = threading.Lock()

    def maintain_forever():
        nonlocal latest
        while True:
            try:
                result = signer.maintain()
            except Exception as exc:
                result = {"status": "blocked", "error_type": type(exc).__name__,
                          "reason": str(exc) if isinstance(exc, BurnBlocked) else "Signer/RPC unavailable"}
            result['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
            with lock:
                latest = result
            print(json.dumps(result, sort_keys=True), flush=True)
            time.sleep(signer.settings.poll_seconds)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                _, uid, _ = struct.unpack("3i", self.request.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
                if uid not in (0, allowed_uid):
                    raise BurnBlocked("Peer UID is not authorized")
                self.request.settimeout(10)
                raw = self.rfile.readline(4097)
                if len(raw) > 4096 or json.loads(raw) != {"action": "maintain"}:
                    raise BurnBlocked("Only the fixed maintain action is supported")
                with lock:
                    result = dict(latest)
                if result.get('updated_at'):
                    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(result['updated_at'])).total_seconds()
                    if age > 180:
                        result = {"status": "blocked", "reason": "Signer heartbeat is stale"}
            except Exception as exc:
                result = {"status": "blocked", "error_type": type(exc).__name__,
                          "reason": str(exc) if isinstance(exc, BurnBlocked) else "Signer/RPC unavailable"}
            self.wfile.write((json.dumps(result) + "\n").encode())

    path = Path(args.socket)
    if path.exists():
        with socket.socket(socket.AF_UNIX) as probe:
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()
            else:
                raise RuntimeError("Another signer already owns the socket")
    with socketserver.UnixStreamServer(str(path), Handler) as server:
        path.chmod(0o660)
        threading.Thread(target=maintain_forever, daemon=True).start()
        print(json.dumps({"status": "ready", "network": "localnet", "production_keys_loaded": False}), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
