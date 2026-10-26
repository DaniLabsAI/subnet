"""Isolated, manually unlocked burn signer. The worker never receives a key."""
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
from .custody import CustodyError, load_policy


def control(signer, request, peer_uid, worker_uid, operation_lock):
    if peer_uid not in (0, os.geteuid(), worker_uid):
        raise BurnBlocked('Peer UID is not authorized')
    action = request.get('action') if isinstance(request,dict) else None
    if action in ('maintain','status') and request == {'action':action}:
        return None
    if peer_uid not in (0, os.geteuid()):
        raise BurnBlocked('Only the signer custodian can unlock or lock')
    if action == 'unlock' and set(request) == {'action','password'}:
        with operation_lock:
            signer.unlock(request['password'])
        return {'status':'unlocked', **signer.key_status()}
    if action == 'lock' and request == {'action':'lock'}:
        with operation_lock:
            signer.lock()
        return {'status':'locked', **signer.key_status()}
    raise BurnBlocked('Unsupported signer request')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    settings = load_settings(args.config)
    policy = load_policy(args.policy, settings, settings_path=args.config)
    signer = BurnSigner(settings, args.state, policy=policy)
    allowed_uid = pwd.getpwnam("dani-validator").pw_uid
    latest = {"status": "starting"}
    lock = threading.Lock()
    operation_lock = threading.RLock()

    def maintain_forever():
        nonlocal latest
        while True:
            try:
                with operation_lock:
                    result = signer.maintain()
            except Exception as exc:
                result = {"status": "blocked", "error_type": type(exc).__name__,
                          "reason": str(exc) if isinstance(exc, (BurnBlocked,CustodyError)) else "Signer/RPC unavailable"}
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
                if uid not in (0, os.geteuid(), allowed_uid):
                    raise BurnBlocked("Peer UID is not authorized")
                self.request.settimeout(10)
                raw = self.rfile.readline(8193)
                if len(raw) > 8192:
                    raise BurnBlocked('Request too large')
                result = control(signer,json.loads(raw),uid,allowed_uid,operation_lock)
                public_status = result is None
                if public_status:
                    with lock:
                        result = dict(latest)
                    result.update(signer.key_status())
                    if not signer.policy.enabled:result['status']='disabled'
                    elif not signer.keys.is_unlocked:result['status']='locked'
                if public_status and result.get('updated_at'):
                    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(result['updated_at'])).total_seconds()
                    if age > 180:
                        result = {"status": "blocked", "reason": "Signer heartbeat is stale"}
            except Exception as exc:
                result = {"status": "blocked", "error_type": type(exc).__name__,
                          "reason": str(exc) if isinstance(exc, (BurnBlocked,CustodyError)) else "Signer request failed"}
            self.wfile.write((json.dumps(result) + "\n").encode())

    path = Path(args.socket)
    if path.exists():
        if not path.is_socket() or path.is_symlink():
            raise RuntimeError('Unexpected non-socket at signer endpoint')
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
        print(json.dumps({"status": "ready", **signer.key_status()}), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
