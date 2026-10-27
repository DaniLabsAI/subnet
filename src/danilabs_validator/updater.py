"""Fetch main, test a staged worker, activate, and roll back on failed health.

Run as dani-deploy. This process has no signer key or signer source permissions.
The root-owned activation helper accepts only an exact commit ID and controls
one fixed PM2 worker. The signer is never updated or restarted here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time
import tomllib

from .health import healthy
from .monitor import load_state, save_state

DEPENDENCIES = ['async-substrate-interface==1.6.4', 'bittensor-wallet==4.1.1', 'certifi==2026.10.23', 'aiohttp==3.14.5']


class UpdateRejected(RuntimeError):
    pass


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=120, **kwargs)


def require_commit(sha):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise UpdateRejected('Expected an exact 40-character commit ID')


class Updater:
    def __init__(self, config):
        self.config = config
        self.cache = Path(config['cache'])
        self.releases = Path(config['releases'])
        self.state_path = config['state_file']
        self.state = load_state(self.state_path) or {'accepted': config['initial_commit'], 'rejected': []}
        require_commit(self.state['accepted'])

    def prepare(self, sha):
        require_commit(sha)
        target = self.releases / sha
        if target.is_symlink():
            raise UpdateRejected('Refusing a symlinked candidate')
        marker = target / '.dani-tested.json'
        if marker.exists():
            if json.loads(marker.read_text()).get('commit') != sha:
                raise UpdateRejected('Candidate marker does not match the release')
            return target
        if target.exists():
            raise UpdateRejected('An incomplete candidate already exists; inspect it before retrying')
        archive = command(['git', '--git-dir', str(self.cache), 'archive', '--format=tar', sha]).stdout
        if len(archive) > 10 * 1024 * 1024:
            raise UpdateRejected('Candidate source exceeds the reviewed size limit')
        target.mkdir(mode=0o755)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            if any(not (member.isfile() or member.isdir()) for member in bundle.getmembers()):
                raise UpdateRejected('Candidate archive must contain regular files/directories only')
            bundle.extractall(target, filter='data')
        for path in (target, *target.rglob('*')):
            path.chmod(0o755 if path.is_dir() else 0o644)
        metadata = tomllib.loads((target / 'pyproject.toml').read_text())
        if metadata['project']['dependencies'] != DEPENDENCIES:
            raise UpdateRejected('Dependency changes require a separately reviewed base environment')
        env = {**os.environ, 'PYTHONPATH': str(target / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([self.config['python'], '-m', 'unittest', 'discover',
            '-s', str(target / 'tests'), '-v'], cwd=target, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        (target / '.dani-test.log').write_bytes(result.stdout)
        if result.returncode:
            raise UpdateRejected('Candidate unit tests failed')
        marker.write_text(json.dumps({'commit':sha, 'tested_at':datetime.now(timezone.utc).isoformat()}))
        return target

    def activate(self, sha):
        require_commit(sha)
        command(self.config['activate_command'] + [sha])

    def await_health(self, sha):
        deadline = time.monotonic() + self.config.get('health_timeout_seconds', 120)
        while time.monotonic() < deadline:
            try:
                state = load_state(self.config['worker_state'])
            except (OSError, ValueError):
                state = None
            if healthy(state, sha):
                return True
            time.sleep(2)
        return False

    def record(self, result):
        self.state['last_check'] = {**result, 'at': datetime.now(timezone.utc).isoformat()}
        save_state(self.state_path, self.state)
        print(json.dumps(self.state['last_check'], sort_keys=True), flush=True)
        return result

    def once(self):
        # The config fixes this URL/ref; candidate code cannot supply fetch targets.
        if self.config.get('branch') != 'main':
            raise UpdateRejected('Only the explicitly configured main branch is supported')
        if not self.cache.exists():
            command(['git', 'init', '--bare', str(self.cache)])
        try:
            command(['git', '--git-dir', str(self.cache), 'fetch', '--no-tags',
                     self.config['repository'], 'refs/heads/main:refs/remotes/origin/main'])
            sha = command(['git', '--git-dir', str(self.cache), 'rev-parse',
                           'refs/remotes/origin/main']).stdout.decode().strip()
            require_commit(sha)
        except Exception as exc:
            return self.record({'status':'fetch_failed', 'error_type':type(exc).__name__,
                                'running_release_preserved':self.state['accepted']})
        previous = self.state['accepted']
        if sha == previous:
            return self.record({'status':'up_to_date','commit':sha})
        if sha in self.state['rejected']:
            return self.record({'status':'quarantined','commit':sha,'running_release_preserved':previous})
        activated = False
        try:
            command(['git', '--git-dir', str(self.cache), 'merge-base', '--is-ancestor', previous, sha])
            self.prepare(sha)
            # Mark the intent durably before activation. Recover even if updater dies.
            self.state['pending'] = sha
            save_state(self.state_path, self.state)
            activated = True
            self.activate(sha)
            if not self.await_health(sha):
                raise UpdateRejected('New release did not produce a fresh healthy poll')
        except Exception as exc:
            self.state['rejected'].append(sha)
            self.state.pop('pending', None)
            if activated:
                self.activate(previous)
                if not self.await_health(previous):
                    return self.record({'status':'rollback_needs_attention','failed_commit':sha,
                                        'restored_commit':previous})
            return self.record({'status':'rolled_back' if activated else 'rejected',
                'failed_commit':sha,'running_release_preserved':previous,'error_type':type(exc).__name__})
        self.state['accepted'] = sha
        self.state.pop('pending', None)
        return self.record({'status':'updated','previous':previous,'commit':sha})

    def recover_interrupted(self):
        if self.state.get('pending'):
            failed = self.state.pop('pending')
            self.activate(self.state['accepted'])
            self.state['rejected'].append(failed)
            self.record({'status':'recovered_interrupted_update','restored_commit':self.state['accepted']})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    Path(config['lock_file']).parent.mkdir(parents=True, exist_ok=True)
    with open(config['lock_file'], 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        updater = Updater(config)
        updater.recover_interrupted()
        while True:
            try:
                updater.once()
            except Exception as exc:
                updater.record({'status':'error','error_type':type(exc).__name__})
            if args.once:
                return
            time.sleep(config.get('interval_seconds',300))


if __name__ == '__main__':
    main()
