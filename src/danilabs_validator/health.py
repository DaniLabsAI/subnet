"""Updater acceptance: a new release must produce its OWN fresh healthy poll."""
import argparse
import datetime as dt
import json
import sys

from .monitor import load_state


def healthy(state, release, max_age=90):
    try:
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(state['heartbeat_at'])).total_seconds()
        return bool(state['release_commit'] == release and state['status'] == 'healthy'
                and state['network'] == 'localnet' and 0 <= age < max_age
                and state['burn_guard']['checks_passed'] is True
                and state['snapshot']['source_hash'])
    except (KeyError, TypeError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    ok = bool(healthy(load_state(args.state), args.release))
    print(json.dumps({'healthy': ok, 'release': args.release}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
