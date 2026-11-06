"""Poll finalized state and signed reports, with optional fixed-burn status."""
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


def run(settings, socket_path, count=0, reports_config='/etc/danilabs/validator-reports.json'):
    settings.validate()
    chain = FinalizedChain(settings)
    saved = load_state(settings.state_file) or {}
    previous = saved.get('snapshot')
    i = 0
    report_client=None
    while True:
        result = {'worker_pid': os.getpid(), 'release_commit': os.environ.get('DANI_RELEASE_SHA', 'development'),
                  'network': settings.network}
        try:
            snapshot = chain.snapshot()
            result.update(snapshot=snapshot, status='waiting')
            if socket_path is not None:
                report = assess(snapshot, settings, previous)
                # The signer reads finalized state and checks its own policy.
                signer = request_burn(socket_path)
                result.update(status='healthy' if report['burn_guard']['checks_passed']
                              and signer.get('status') in ('maintained','submitted','committed','revealed','pending','rate_limited') else 'waiting',
                              burn_guard=report['burn_guard'], signer=signer,
                              last_epoch_100_percent_miner_burn_verified=report['last_epoch_100_percent_miner_burn_verified'])
            try:
                from .reports import ReportClient, ReportSettings
                if report_client is None:
                    report_client=ReportClient(ReportSettings.load(reports_config,settings.network),settings)
                result['report_scoring']=report_client.poll(chain,snapshot)
                if socket_path is None and result['report_scoring']['status']=='ready':
                    result['status']='healthy'
            except Exception as exc:
                result['report_scoring']={'status':'unavailable','error_type':type(exc).__name__,
                    'candidate_weights':None,'weights_submitted':False,'burn_policy_unchanged':True}
            previous = snapshot
        except Exception as exc:
            result.update(status='unavailable', error_type=type(exc).__name__)
        result['heartbeat_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        save_state(settings.state_file, result)
        # This contains public chain evidence only, never key material or salts.
        Path(settings.state_file).chmod(0o640)
        event = result
        if socket_path is None:
            event = {key: result[key] for key in ('status', 'network', 'release_commit', 'heartbeat_at', 'error_type') if key in result}
            if snapshot := result.get('snapshot'):
                event['finalized_block'] = snapshot['source_block']
            if scoring := result.get('report_scoring'):
                event['report'] = {key: scoring[key] for key in ('status', 'report_id', 'report_sha256', 'epoch_end_block', 'error_type') if key in scoring}
        print(json.dumps(event, sort_keys=True), flush=True)
        i += 1
        if count and i >= count:
            chain.close()
            return 0
        time.sleep(settings.poll_seconds)
