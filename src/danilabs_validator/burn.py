"""Localnet burn signer. Fixed policy, no general-purpose signing interface."""
from __future__ import annotations

import json
from pathlib import Path
import secrets

from .chain import FinalizedChain, unsigned_newtype, value
from .config import LOCALNET_GENESIS, Settings
from .monitor import assess, load_state, save_state


class BurnBlocked(RuntimeError):
    pass


def commitment_hex(raw):
    """SDK9 decodes H256 newtypes as ((byte, ...),), not always as hex."""
    if isinstance(raw, str) and len(raw) == 66 and raw.startswith('0x'):
        try:
            return '0x' + bytes.fromhex(raw[2:]).hex()
        except ValueError:
            return None
    if isinstance(raw, (list, tuple)) and len(raw) == 1:
        return commitment_hex(raw[0])
    if isinstance(raw, (bytes, list, tuple)) and len(raw) == 32:
        if all(type(x) is int and 0 <= x <= 255 for x in raw):
            return '0x' + bytes(raw).hex()
    return None


def preflight(snapshot, settings, previous=None):
    if settings.network != "localnet" or settings.expected_genesis != LOCALNET_GENESIS:
        raise BurnBlocked("This writer cannot sign on Finney or any other chain")
    report = assess(snapshot, settings, previous, require_burn_row=False)
    reasons = list(report["burn_guard"]["blocked_reasons"])
    if snapshot.get("runtime_spec_version") != 482:
        reasons.append("Unreviewed runtime; localnet writer is pinned to spec 482")
    if snapshot.get("weights_version") != 0:
        reasons.append("Unreviewed weight version; expected localnet version 0")
    if snapshot.get("min_allowed_weights") not in (0, 1):
        reasons.append("Single burn destination is incompatible with minimum weight count")
    if snapshot.get("max_weight_limit") != 65535:
        reasons.append("Single burn destination is incompatible with maximum weight limit")
    if type(snapshot.get("weights_rate_limit")) is not int or snapshot["weights_rate_limit"] < 0:
        reasons.append("Weight rate limit is unavailable")
    if type(snapshot.get("activity_cutoff")) is not int or snapshot["activity_cutoff"] < 8:
        reasons.append("Activity cutoff is unavailable or too short")
    if settings.weight_submission_mode == "legacy-commit-reveal":
        for field in ("epoch_index", "reveal_period_epochs"):
            if type(snapshot.get(field)) is not int or snapshot[field] < 0:
                reasons.append(f"Commit/reveal timing unavailable: {field}")
    validator = snapshot.get("validator") or {}
    if validator.get("hotkey") != settings.validator_hotkey:
        reasons.append("Validator key differs from its configured public pin")
    if type(validator.get("stake_weight_raw")) is not int or validator["stake_weight_raw"] <= 0:
        reasons.append("Validator has no effective consensus stake")
    if type(validator.get("last_update")) is not int:
        reasons.append("Validator last update is unavailable")
    if reasons:
        raise BurnBlocked("; ".join(reasons))
    return report


class BurnSigner:
    def __init__(self, settings: Settings, state_file: str, substrate=None):
        settings.validate()
        if settings.network != "localnet" or settings.expected_genesis != LOCALNET_GENESIS:
            raise BurnBlocked("Signer is restricted to the pinned development chain")
        self.settings = settings
        self.chain = FinalizedChain(settings, substrate)
        self.state_file = state_file
        self.state = load_state(state_file) or {}
        self.previous = self.state.get("snapshot")

    def persist(self, snapshot):
        self.state["snapshot"] = snapshot
        save_state(self.state_file, self.state)
        self.previous = snapshot

    def submit(self, function, params, snapshot):
        # Repeat the network gate immediately before constructing ANY private key.
        s = self.chain.substrate
        if s.get_block_hash(0) != LOCALNET_GENESIS:
            raise BurnBlocked("Genesis changed before signing")
        from bittensor_wallet import Keypair
        keypair = Keypair.create_from_uri("//Bob")  # Publicly known DEVELOPMENT key only.
        if keypair.ss58_address != self.settings.validator_hotkey:
            raise BurnBlocked("This build signs only with the public Bob development key")
        call = s.compose_call(call_module="SubtensorModule", call_function=function, call_params=params)
        extrinsic = s.create_signed_extrinsic(call=call, keypair=keypair, era={"period": 32})
        receipt = s.submit_extrinsic(extrinsic, wait_for_inclusion=True, wait_for_finalization=True)
        if not receipt.is_success:
            raise BurnBlocked(f"Development extrinsic rejected: {receipt.error_message}")
        result = {"function": function, "extrinsic_hash": receipt.extrinsic_hash,
                  "finalized_inclusion_hash": receipt.block_hash,
                  "source_block": snapshot["source_block"]}
        self.state["last_transaction"] = result
        save_state(self.state_file, self.state)
        return result

    def maintain(self):
        snapshot = self.chain.snapshot()
        report = preflight(snapshot, self.settings, self.previous)
        self.persist(snapshot)
        owner = snapshot["owner"]
        validator = snapshot["validator"]
        n = self.settings.netuid
        row_ok = report["burn_guard"]["validator_row_100_percent_to_owner"] is True
        common = {"network": "localnet", "genesis": LOCALNET_GENESIS, "netuid": n,
                  "owner_uid": owner["uid"], "validator_uid": validator["uid"],
                  "finalized_source_block": snapshot["source_block"],
                  "row_100_percent_to_owner": row_ok,
                  "last_transaction": self.state.get("last_transaction")}
        pending = self.state.get("pending")
        if pending:
            expected = [n, owner["hotkey"], owner["uid"], owner["registration_block"],
                        validator["hotkey"], validator["registration_block"]]
            if pending["identity"] != expected:
                raise BurnBlocked("Pending commit belongs to a different registration")
            commits = value(self.chain.substrate.query(
                "SubtensorModule", "WeightCommits", [n, validator["hotkey"]],
                block_hash=snapshot["source_hash"])) or []
            matches = [x for x in commits if commitment_hex(x[0]) == pending["commit_hash"]]
            match = next((x for x in matches
                          if x[1] + snapshot['reveal_period_epochs'] >= snapshot['epoch_index']),
                         matches[-1] if matches else None)
            if match:
                target_epoch = match[1] + snapshot["reveal_period_epochs"]
                epoch = snapshot["epoch_index"]
                if epoch < target_epoch:
                    return {**common, "status": "pending", "reveal_epoch": target_epoch,
                            "current_epoch": epoch}
                if epoch > target_epoch:
                    self.state.pop("pending")
                    self.persist(snapshot)
                    return {**common, "status": "expired_commit", "retry_next_poll": True}
                transaction = self.submit("reveal_weights", {
                    "netuid": n, "uids": [owner["uid"]], "values": [65535],
                    "salt": pending["salt"], "version_key": 0}, snapshot)
                self.state.pop("pending")
                self.persist(snapshot)
                return {**common, "status": "revealed", "transaction": transaction}
            # A finalized row plus advanced last_update can resolve a reveal whose
            # final receipt was lost during a restart, without changing identity.
            if row_ok and validator["last_update"] > pending["prepared_block"]:
                self.state.pop("pending")
                self.persist(snapshot)
                return {**common, "status": "maintained", "recovered_after_restart": True}
            if snapshot["source_block"] - pending["last_attempt_block"] < 4:
                return {**common, "status": "pending", "reason": "awaiting commit finality"}
            pending["last_attempt_block"] = snapshot["source_block"]
            self.persist(snapshot)
            transaction = self.submit("commit_weights", {
                "netuid": n, "commit_hash": pending["commit_hash"]}, snapshot)
            return {**common, "status": "committed", "transaction": transaction}

        age = snapshot["source_block"] - validator["last_update"]
        refresh = min(20, max(4, snapshot["activity_cutoff"] // 2))
        if row_ok and age < refresh:
            return {**common, "status": "maintained"}
        if age <= snapshot["weights_rate_limit"]:
            return {**common, "status": "rate_limited"}
        if self.settings.weight_submission_mode == "plain":
            transaction = self.submit("set_weights", {"netuid": n, "dests": [owner["uid"]],
                                      "weights": [65535], "version_key": 0}, snapshot)
            return {**common, "status": "submitted", "transaction": transaction}

        from bittensor.utils.weight_utils import generate_weight_hash
        salt = [secrets.randbelow(65536) for _ in range(32)]
        commit_hash = generate_weight_hash(address=validator["hotkey"], netuid=n,
            uids=[owner["uid"]], values=[65535], salt=salt, version_key=0)
        self.state["pending"] = {"identity": [n, owner["hotkey"], owner["uid"],
            owner["registration_block"], validator["hotkey"], validator["registration_block"]],
            "salt": salt, "commit_hash": commit_hash,
            "prepared_block": snapshot["source_block"], "last_attempt_block": snapshot["source_block"]}
        # Persist the salt BEFORE broadcast; worker updates cannot lose it.
        self.persist(snapshot)
        transaction = self.submit("commit_weights", {"netuid": n, "commit_hash": commit_hash}, snapshot)
        return {**common, "status": "committed", "transaction": transaction}
