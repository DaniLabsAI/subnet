from __future__ import annotations

import argparse
import json
import time

from .chain import ChainUnavailable, FinalizedChain
from .config import load_settings
from .monitor import assess, load_state, save_state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only DaniLabs finalized-chain observer; never signs transactions")
    parser.add_argument("--config", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Inspect one finalized snapshot")
    sub.add_parser("shadow", help="Inspect identity; scoring is pending authenticated reports")
    watch = sub.add_parser("watch", help="Poll and persist local observer state")
    watch.add_argument("--count", type=int, default=0, help="Number of polls; 0 watches continuously")
    burn = sub.add_parser("burn-watch", help="Localnet worker; requests fixed policy actions from an isolated signer")
    burn.add_argument("--signer-socket", required=True)
    burn.add_argument("--count", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command in ("watch", "burn-watch") and args.count < 0:
        parser.error("--count must be non-negative")
    try:
        settings = load_settings(args.config)
        if args.command == "burn-watch":
            from .worker import run
            return run(settings, args.signer_socket, args.count)
        chain = FinalizedChain(settings)
        previous = load_state(settings.state_file)
        count = 0
        while True:
            try:
                snapshot = chain.snapshot()
                result = assess(snapshot, settings, previous)
                if args.command == "shadow":
                    result["shadow"] = {"status": "pending", "reason": "No authenticated validator report contract or approved scoring formula exists yet", "scores": None, "weights_submitted": False}
                print(json.dumps(result, sort_keys=True), flush=True)
                if args.command == "watch":
                    save_state(settings.state_file, snapshot)
                previous = snapshot
            except ChainUnavailable as exc:
                print(json.dumps({"status": "unavailable", "error": str(exc), "chain_writes": False, "burn_guard": {"checks_passed": False}, "last_epoch_100_percent_miner_burn_verified": None}), flush=True)
                if args.command != "watch":
                    return 2
            count += 1
            if args.command != "watch" or (args.count > 0 and count >= args.count):
                return 0
            time.sleep(settings.poll_seconds)
    except (OSError, ValueError, ImportError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc), "chain_writes": False}), flush=True)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
