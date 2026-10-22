from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path

from .config import Settings

BURN_SOURCE = "https://github.com/RaoFoundation/subtensor/blob/main/pallets/subtensor/src/coinbase/run_coinbase.rs"


def normalized_miner_burned(raw, spec_version, semantics):
    """Return a decimal only for an operator-reviewed runtime encoding.

    FixedU128 is not enough to infer the denominator. Keep the raw value when
    the deployed runtime has not been reviewed, rather than guessing a percent.
    """
    if not semantics or semantics["spec_version"] != spec_version:
        return None
    bits = raw.get("bits") if isinstance(raw, dict) and set(raw) == {"bits"} else raw
    if type(bits) is not int or not 0 <= bits <= 1 << 32:
        return None
    return str(Decimal(bits) / Decimal(1 << 32))


def registration_identity(registration):
    if not registration or not registration.get("registered"):
        return None
    return [registration["hotkey"], registration["uid"], registration["registration_block"]]


def assess(snapshot: dict, settings: Settings, previous: dict | None = None) -> dict:
    reasons = []
    if snapshot.get("genesis") != settings.expected_genesis or snapshot.get("netuid") != settings.netuid:
        reasons.append("Snapshot does not match the configured chain/subnet pin")
    owner = snapshot.get("owner") or {}
    validator = snapshot.get("validator") or {}
    if not settings.expected_owner_hotkey or owner.get("hotkey") != settings.expected_owner_hotkey:
        reasons.append("Subnet owner hotkey is unpinned or changed")
    if not owner.get("registered") or owner.get("registration_block") != settings.expected_owner_registration_block:
        reasons.append("Owner registration is unpinned, unavailable or changed")
    if snapshot.get("owner_coldkey_matches") is not True:
        reasons.append("Owner hotkey/coldkey association is not verified")
    if not settings.expected_owner_coldkey or snapshot.get("subnet_owner_coldkey") != settings.expected_owner_coldkey:
        reasons.append("Subnet owner coldkey is unpinned or changed")
    if not validator.get("registered"):
        reasons.append("Validator public hotkey is unconfigured or unregistered")
    if validator.get("registration_block") != settings.expected_validator_registration_block or settings.expected_validator_registration_block is None:
        reasons.append("Validator registration is unpinned or changed")
    if validator.get("validator_permit") is not True:
        reasons.append("Validator permit is absent or unavailable")
    if snapshot.get("recycle_or_burn_raw") not in ({"Burn": ()}, {"Burn": []}, "Burn"):
        reasons.append("RecycleOrBurn is not verified as Burn")
    if snapshot.get("commit_reveal_enabled") is not False:
        reasons.append("Plain-weight burn writer compatibility not established: commit/reveal is enabled or unavailable")
    if snapshot.get("mechanism_count") != 1:
        reasons.append("Single-mechanism scope is unverified")
    if previous:
        if previous.get("genesis") != snapshot.get("genesis") or previous.get("netuid") != snapshot.get("netuid"):
            reasons.append("Prior snapshot belongs to another chain or subnet")
        if previous.get("source_block", -1) > snapshot["source_block"]:
            reasons.append("Finalized source block regressed")
        if previous.get("source_block") == snapshot["source_block"] and previous.get("source_hash") != snapshot.get("source_hash"):
            reasons.append("Finalized block hash changed at the same height")
        for role in ("owner", "validator"):
            if registration_identity(previous.get(role)) != registration_identity(snapshot.get(role)):
                reasons.append(f"{role.title()} registration changed since previous snapshot")
    row = validator.get("weights_raw")
    row_burn = None
    if isinstance(row, (list, tuple)) and owner.get("registered"):
        try:
            entries = [(uid, weight) for uid, weight in row]
            if any(type(uid) is not int or type(weight) is not int for uid, weight in entries):
                raise ValueError("Weights must be raw integers")
            if any(uid < 0 or not 0 <= weight <= 65535 for uid, weight in entries) or len({uid for uid, _ in entries}) != len(entries):
                raise ValueError("Invalid weight row")
            nonzero = [(uid, weight) for uid, weight in entries if weight > 0]
            row_burn = bool(nonzero and len(nonzero) == 1 and nonzero[0] == (owner["uid"], 65535))
        except (ValueError, TypeError):
            row_burn = None
    if row_burn is not True:
        reasons.append("Finalized validator row is not verified as 100% to the current owner UID")
    evidence = snapshot.get("last_epoch_evidence") or {}
    same_runtime = evidence.get("runtime_spec_version") == evidence.get("mode_runtime_spec_version")
    fraction = normalized_miner_burned(evidence.get("miner_burned_raw"), evidence.get("runtime_spec_version"), settings.miner_burned_semantics) if same_runtime else None
    epoch = snapshot.get("last_epoch_block")
    epoch_valid = type(epoch) is int and 0 < epoch <= snapshot["source_block"] and evidence.get("source_block") == epoch and bool(evidence.get("source_hash")) and evidence.get("mode_source_block") == epoch - 1 and bool(evidence.get("mode_source_hash"))
    epoch_burn = evidence.get("recycle_or_burn_raw") in ({"Burn": ()}, {"Burn": []}, "Burn")
    observed_full = None if fraction is None or not epoch_valid or not epoch_burn or reasons else fraction == "1"
    return {
        **snapshot,
        "observer": {"chain_writes": False, "wallet_loaded": False, "scoring": "pending_authenticated_reports"},
        "burn_guard": {"checks_passed": not reasons, "blocked_reasons": reasons, "validator_row_100_percent_to_owner": row_burn},
        "miner_burned": {"fraction": fraction, "raw": snapshot.get("miner_burned_raw"), "settlement_evidence": evidence or None, "semantics": "Latest epoch miner incentive withheld from owner-associated hotkeys; includes burn and recycle", "encoding_review": settings.miner_burned_semantics, "source": BURN_SOURCE},
        "last_epoch_100_percent_miner_burn_verified": observed_full,
        "scope": "Miner incentive only. Validator dividends, owner cut and pool injections are separate. This observer maintains no burn process.",
    }


def load_state(path: str) -> dict | None:
    try:
        value = json.loads(Path(path).read_text())
        if not isinstance(value, dict):
            raise ValueError("Observer state must be an object")
        return value
    except FileNotFoundError:
        return None


def save_state(path: str, snapshot: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(snapshot, stream, sort_keys=True)
        stream.write("\n")
    temporary.replace(target)
