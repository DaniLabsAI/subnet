"""Read every snapshot at a single finalized block. No wallet or extrinsic API."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from .config import Settings


class ChainUnavailable(RuntimeError):
    pass


def value(item: Any) -> Any:
    return getattr(item, "value", item)


def unsigned_newtype(raw):
    """SDK9 decodes some unsigned newtypes as singleton lists."""
    candidate = raw[0] if isinstance(raw, (list, tuple)) and len(raw) == 1 else raw
    return candidate if type(candidate) is int and candidate >= 0 else None


def create_subtensor(endpoint: str):
    import bittensor as bt
    parser = argparse.ArgumentParser(add_help=False)
    bt.Subtensor.add_args(parser)
    config = bt.Config(parser=parser, args=["--subtensor.chain_endpoint", endpoint])
    return bt.Subtensor(network=endpoint, config=config)


class FinalizedChain:
    def __init__(self, settings: Settings, substrate=None):
        self.settings = settings
        self.settings.validate()
        self.substrate = substrate

    def snapshot(self) -> dict:
        try:
            if self.substrate is None:
                self.substrate = create_subtensor(self.settings.chain_endpoint).substrate
            s = self.substrate
            genesis = s.get_block_hash(0)
            if genesis != self.settings.expected_genesis:
                raise ChainUnavailable("Chain genesis does not match the configured network pin")
            block_hash = s.rpc_request("chain_getFinalizedHead", [])["result"]
            header = s.rpc_request("chain_getHeader", [block_hash])["result"]
            block = int(header["number"], 16)
            runtime = s.rpc_request("state_getRuntimeVersion", [block_hash])["result"]
            errors = {}

            def query(name, params, *, required=False, at_hash=None):
                try:
                    return value(s.query("SubtensorModule", name, params, block_hash=at_hash or block_hash))
                except Exception:
                    if required:
                        raise ChainUnavailable(f"Required finalized field unavailable: {name}")
                    errors[f"{name}@{at_hash or block_hash}"] = "unavailable"
                    return None

            n = self.settings.netuid
            if query("NetworksAdded", [n], required=True) is not True:
                raise ChainUnavailable("Pinned subnet is not active")

            def registration(hotkey):
                if not hotkey:
                    return None
                uid = query("Uids", [n, hotkey])
                if type(uid) is not int or uid < 0:
                    return {"hotkey": hotkey, "registered": False}
                mapped = query("Keys", [n, uid])
                registered = query("BlockAtRegistration", [n, uid])
                if mapped != hotkey or type(registered) is not int or not 0 <= registered <= block:
                    return {"hotkey": hotkey, "uid": uid, "registered": False, "reason": "Finalized UID mapping is inconsistent"}
                return {"hotkey": hotkey, "uid": uid, "registered": True, "registration_block": registered, "coldkey": query("Owner", [hotkey])}

            owner_hotkey = query("SubnetOwnerHotkey", [n], required=True)
            if not isinstance(owner_hotkey, str) or not owner_hotkey:
                raise ChainUnavailable("Subnet owner hotkey is unavailable")
            owner = registration(owner_hotkey)
            validator = registration(self.settings.validator_hotkey)
            owner_coldkey = query("SubnetOwner", [n], required=True)
            permits = query("ValidatorPermit", [n])
            stakes = query("StakeWeight", [n])
            last_updates = query("LastUpdate", [n])
            def validator_fields(registration):
                if not registration or not registration.get("registered"):
                    return
                uid = registration["uid"]
                for key, vector in (("validator_permit", permits), ("stake_weight_raw", stakes), ("last_update", last_updates)):
                    registration[key] = vector[uid] if isinstance(vector, (list, tuple)) and uid < len(vector) else None
                # Mechanism 0 uses the subnet's base storage index. Extra mechanisms
                # are surfaced below and keep the burn guard blocked until supported.
                registration["weights_raw"] = query("Weights", [n, uid])
                registration["alpha_stake_rao_raw"] = query("TotalHotkeyAlpha", [registration["hotkey"], n])
                registration["root_tao_stake_rao_raw"] = query("TotalHotkeyAlpha", [registration["hotkey"], 0])
            # Inspect the owner's public row for operational reference without
            # treating it as the configured validator or loading its wallet.
            validator_fields(owner)
            validator_fields(validator)
            last_epoch = query("LastEpochBlock", [n])
            epoch_source = "LastEpochBlock"
            if type(last_epoch) is not int or last_epoch <= 0:
                last_epoch = query("LastMechansimStepBlock", [n])
                epoch_source = "LastMechansimStepBlock"
            epoch_evidence = None
            if type(last_epoch) is int and 0 < last_epoch <= block:
                try:
                    epoch_hash = s.get_block_hash(last_epoch)
                    parent_hash = s.get_block_hash(last_epoch - 1)
                    epoch_runtime = s.rpc_request("state_getRuntimeVersion", [epoch_hash])["result"]
                    parent_runtime = s.rpc_request("state_getRuntimeVersion", [parent_hash])["result"]
                    epoch_evidence = {
                        "source_block": last_epoch, "source_hash": epoch_hash,
                        "runtime_spec_version": epoch_runtime.get("specVersion"),
                        # Settlement runs in on_initialize, before this block's
                        # extrinsics. The prior block's mode governed that payout.
                        "mode_source_block": last_epoch - 1, "mode_source_hash": parent_hash,
                        "mode_runtime_spec_version": parent_runtime.get("specVersion"),
                        "recycle_or_burn_raw": query("RecycleOrBurn", [n], at_hash=parent_hash),
                        "miner_burned_raw": query("MinerBurned", [n], at_hash=epoch_hash),
                    }
                except Exception:
                    errors["last_epoch_evidence"] = "unavailable; historical RPC may be required"
            mechanism_count = query("MechanismCountCurrent", [n])
            return {
                "network": self.settings.network, "genesis": genesis, "netuid": n,
                "source_block": block, "source_hash": block_hash,
                "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                "runtime_spec_version": runtime.get("specVersion"),
                "owner": owner, "subnet_owner_coldkey": owner_coldkey,
                "owner_coldkey_matches": bool(owner and owner.get("registered") and isinstance(owner_coldkey, str) and owner.get("coldkey") == owner_coldkey),
                "validator": validator,
                "recycle_or_burn_raw": query("RecycleOrBurn", [n]),
                "miner_burned_raw": query("MinerBurned", [n]),
                "last_epoch_block": last_epoch, "last_epoch_source": epoch_source,
                "last_epoch_evidence": epoch_evidence,
                "tempo": query("Tempo", [n]),
                "commit_reveal_enabled": query("CommitRevealWeightsEnabled", [n]),
                "mechanism_count": unsigned_newtype(mechanism_count),
                "mechanism_count_raw": mechanism_count,
                "weights_version": query("WeightsVersionKey", [n]),
                "weights_rate_limit": query("WeightsSetRateLimit", [n]),
                "min_allowed_weights": query("MinAllowedWeights", [n]),
                "max_weight_limit": query("MaxWeightsLimit", [n]),
                "stake_threshold_raw": query("StakeThreshold", []),
                "epoch_index": query("SubnetEpochIndex", [n]),
                "reveal_period_epochs": query("RevealPeriodEpochs", [n]),
                "activity_cutoff": query("ActivityCutoff", [n]),
                "unavailable_fields": errors,
            }
        except ChainUnavailable:
            raise
        except Exception as exc:
            self.substrate = None
            raise ChainUnavailable("Finalized chain snapshot unavailable") from exc
