"""PM2 worker: observes state and requests a fixed burn action; holds no keys."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import socket
import time

from .chain import FinalizedChain
from .monitor import assess, load_state, save_state


def request_burn(path):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(180)
        client.connect(path)
        client.sendall(b'{"action":"maintain"}\n')
        with client.makefile('rb') as stream:
            raw = stream.readline(65537)
        if len(raw) > 65536:
            raise ValueError("Signer response too large")
        return json.loads(raw)


def run(settings, socket_path, count=0):
    if settings.network != 'localnet':
        raise ValueError('The burn worker is restricted to localnet acceptance')
    chain = FinalizedChain(settings)
    saved = load_state(settings.state_file) or {}
    previous = saved.get('snapshot')
    i = 0
    while True:
        result = {'worker_pid': os.getpid(), 'release_commit': os.environ.get('DANI_RELEASE_SHA', 'development'),
                  'network': settings.network}
        try:
            snapshot = chain.snapshot()
            report = assess(snapshot, settings, previous)
            # Signer independently reads finalized state and checks its immutable policy.
            signer = request_burn(socket_path)
            result.update(status='healthy' if report['burn_guard']['checks_passed']
                          and signer.get('status') in ('maintained','submitted','committed','revealed','pending','rate_limited') else 'waiting',
                          snapshot=snapshot, burn_guard=report['burn_guard'], signer=signer,
                          last_epoch_100_percent_miner_burn_verified=report['last_epoch_100_percent_miner_burn_verified'])
            previous = snapshot
        except Exception as exc:
            result.update(status='unavailable', error_type=type(exc).__name__)
        result['heartbeat_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        save_state(settings.state_file, result)
        # This contains public chain evidence only, never key material or salts.
        Path(settings.state_file).chmod(0o640)
        print(json.dumps(result, sort_keys=True), flush=True)
        i += 1
        if count and i >= count:
            return 0
        time.sleep(settings.poll_seconds)
