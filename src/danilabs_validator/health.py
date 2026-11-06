"""Updater acceptance: a new release must produce its OWN fresh healthy poll."""
import argparse
import datetime as dt
import json
import sys

from .monitor import load_state
from .config import FINNEY_GENESIS, LOCALNET_GENESIS


def healthy(state, release, max_age=90, *, mode='burn', since=None):
    try:
        heartbeat = dt.datetime.fromisoformat(state['heartbeat_at'])
        age = (dt.datetime.now(dt.timezone.utc) - heartbeat).total_seconds()
        snapshot = state['snapshot']
        if not (state['release_commit'] == release and state['status'] == 'healthy'
                and 0 <= age < max_age and (since is None or heartbeat >= since)
                and snapshot['genesis'] == {'localnet':LOCALNET_GENESIS,'finney':FINNEY_GENESIS}[state['network']]
                and snapshot['source_hash']):
            return False
        if mode == 'score':
            scoring = state['report_scoring']
            return (state['network'] == 'finney' and snapshot['netuid'] == 2
                    and scoring['status'] == 'ready' and bool(scoring['report_id'])
                    and scoring['epoch_end_block'] == snapshot['last_epoch_block']
                    and scoring['weights_submitted'] is False)
        return mode == 'burn' and state['burn_guard']['checks_passed'] is True
    except (KeyError, TypeError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--mode', choices=('burn', 'score'), default='burn')
    args = parser.parse_args()
    ok = bool(healthy(load_state(args.state), args.release, mode=args.mode))
    print(json.dumps({'healthy': ok, 'release': args.release}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
