from __future__ import annotations

import argparse
import json
import time

from .chain import ChainUnavailable, FinalizedChain
from .config import load_settings
from .monitor import assess, load_state, save_state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DaniLabs finalized-chain observer, signed-report scorer, and fixed-burn worker")
    parser.add_argument("--config", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Inspect one finalized snapshot")
    score = sub.add_parser("score", help="Fetch the signed validator endpoint and log scores and candidate weights")
    score.add_argument("--reports-config", required=True)
    watch = sub.add_parser("watch", help="Poll and persist local observer state")
    watch.add_argument("--count", type=int, default=0, help="Number of polls; 0 watches continuously")
    burn = sub.add_parser("burn-watch", help="Maintain fixed burn policy and log signed-report candidate scores")
    burn.add_argument("--signer-socket", required=True)
    burn.add_argument("--count", type=int, default=0)
    burn.add_argument("--reports-config", default="/etc/danilabs/validator-reports.json")
    args = parser.parse_args(argv)
    if args.command in ("watch", "burn-watch") and args.count < 0:
        parser.error("--count must be non-negative")
    chain = None
    try:
        settings = load_settings(args.config)
        if args.command == "score":
            from .reports import ReportClient, ReportSettings
            chain=FinalizedChain(settings);snapshot=chain.snapshot()
            client=ReportClient(ReportSettings.load(args.reports_config,settings.network),settings)
            print(json.dumps(client.poll(chain,snapshot),sort_keys=True),flush=True)
            return 0
        if args.command == "burn-watch":
            from .worker import run
            return run(settings, args.signer_socket, args.count, args.reports_config)
        chain = FinalizedChain(settings)
        previous = load_state(settings.state_file)
        count = 0
        while True:
            try:
                snapshot = chain.snapshot()
                result = assess(snapshot, settings, previous)
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
    finally:
        if chain is not None:
            chain.close()


if __name__ == "__main__":
    raise SystemExit(main())
