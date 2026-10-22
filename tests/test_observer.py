from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import tempfile
import unittest

from danilabs_validator.chain import ChainUnavailable, FinalizedChain, unsigned_newtype
from danilabs_validator.config import FINNEY_GENESIS, Settings
from danilabs_validator.monitor import assess, load_state, normalized_miner_burned, registration_identity, save_state

SEMANTICS = {"spec_version": 481, "fractional_bits": 32, "source": "https://github.com/RaoFoundation/subtensor/blob/" + "1" * 40 + "/pallets/subtensor/src/coinbase/run_coinbase.rs"}
SETTINGS = Settings(netuid=73, expected_owner_hotkey="owner-hotkey", expected_owner_coldkey="owner-coldkey", expected_owner_registration_block=10, validator_hotkey="validator-hotkey", expected_validator_registration_block=20, miner_burned_semantics=SEMANTICS)


class FakeSubstrate:
    def __init__(self):
        self.reads = []
        self.genesis = FINNEY_GENESIS
        self.recycled = False
        self.archive_available = True

    def get_block_hash(self, block):
        return self.genesis if block == 0 else f"hash-{block}"

    def rpc_request(self, method, params):
        if method == "chain_getFinalizedHead":
            return {"result": "hash-100"}
        if method == "chain_getHeader":
            assert params == ["hash-100"]
            return {"result": {"number": "0x64"}}
        if method == "state_getRuntimeVersion":
            assert params in (["hash-100"], ["hash-90"], ["hash-89"])
            return {"result": {"specVersion": 481}}
        raise AssertionError(f"Unexpected RPC: {method}")

    def query(self, module, name, params, *, block_hash):
        self.reads.append((name, params, block_hash))
        assert module == "SubtensorModule"
        assert block_hash in ("hash-100", "hash-90", "hash-89")
        if block_hash in ("hash-90", "hash-89") and not self.archive_available:
            raise RuntimeError("No archive")
        values = {
            "NetworksAdded": True, "SubnetOwnerHotkey": "owner-hotkey", "SubnetOwner": "owner-coldkey",
            "ValidatorPermit": [False, False, True], "StakeWeight": [0, 0, 50000],
            "LastUpdate": [0, 0, 80], "Weights": [(1, 65535)],
            "RecycleOrBurn": {"Burn": ()}, "MinerBurned": {"bits": 1 << 32},
            "LastEpochBlock": 90, "LastMechansimStepBlock": 90, "Tempo": 360,
            "CommitRevealWeightsEnabled": False, "MechanismCountCurrent": [1],
            "WeightsVersionKey": 1, "WeightsSetRateLimit": 10, "MinAllowedWeights": 1,
            "MaxWeightsLimit": 65535, "StakeThreshold": 1000,
            "TotalHotkeyAlpha": [10_000_000_000],
        }
        if name == "Uids":
            return {"owner-hotkey": 1, "validator-hotkey": 2}.get(params[1])
        if name == "Keys":
            return {1: "owner-hotkey", 2: "replacement-hotkey" if self.recycled else "validator-hotkey"}[params[1]]
        if name == "BlockAtRegistration":
            return {1: 10, 2: 20}[params[1]]
        if name == "Owner":
            return "owner-coldkey" if params[0] == "owner-hotkey" else "validator-coldkey"
        if name not in values:
            raise AssertionError(f"Unexpected storage: {name}")
        return deepcopy(values[name])


class ObserverTests(unittest.TestCase):
    def snapshot(self):
        substrate = FakeSubstrate()
        return FinalizedChain(SETTINGS, substrate).snapshot(), substrate

    def test_all_reads_use_explicit_finalized_or_settlement_hash(self):
        snapshot, substrate = self.snapshot()
        self.assertEqual(snapshot["owner"]["uid"], 1)  # Never assumes UID 0.
        self.assertEqual(snapshot["validator"]["uid"], 2)
        self.assertEqual(snapshot["source_block"], 100)
        self.assertEqual(snapshot["last_epoch_evidence"]["source_block"], 90)
        self.assertTrue(all(block_hash for _, _, block_hash in substrate.reads))
        result = assess(snapshot, SETTINGS)
        self.assertTrue(result["burn_guard"]["checks_passed"])
        self.assertTrue(result["last_epoch_100_percent_miner_burn_verified"])
        self.assertFalse(result["observer"]["chain_writes"])

    def test_genesis_and_netuid_pins(self):
        fake = FakeSubstrate()
        fake.genesis = "wrong-chain"
        with self.assertRaises(ChainUnavailable):
            FinalizedChain(SETTINGS, fake).snapshot()
        self.assertEqual(fake.reads, [])
        with self.assertRaises(ValueError):
            replace(SETTINGS, netuid=None).validate()
        with self.assertRaises(ValueError):
            replace(SETTINGS, netuid=0).validate()
        snapshot, _ = self.snapshot()
        self.assertEqual(snapshot["netuid"], 73)
        self.assertFalse(assess(snapshot, replace(SETTINGS, netuid=74))["burn_guard"]["checks_passed"])

    def test_sdk_unsigned_newtype_is_not_a_sum_or_boolean(self):
        self.assertEqual(unsigned_newtype([1]), 1)
        self.assertEqual(unsigned_newtype(1), 1)
        for value in ([1, 2], True, [-1], [1.0], None):
            self.assertIsNone(unsigned_newtype(value))

    def test_recycled_uid_cannot_inherit_validator_row(self):
        fake = FakeSubstrate()
        fake.recycled = True
        snapshot = FinalizedChain(SETTINGS, fake).snapshot()
        result = assess(snapshot, SETTINGS)
        self.assertFalse(snapshot["validator"]["registered"])
        self.assertFalse(result["burn_guard"]["checks_passed"])
        self.assertIsNone(result["burn_guard"]["validator_row_100_percent_to_owner"])
        self.assertIsNone(result["last_epoch_100_percent_miner_burn_verified"])

    def test_owner_or_registration_change_blocks_guard(self):
        snapshot, _ = self.snapshot()
        previous = deepcopy(snapshot)
        snapshot["owner"]["registration_block"] = 99
        result = assess(snapshot, SETTINGS, previous)
        self.assertFalse(result["burn_guard"]["checks_passed"])
        self.assertIsNone(result["last_epoch_100_percent_miner_burn_verified"])
        snapshot, _ = self.snapshot()
        snapshot["subnet_owner_coldkey"] = "new-owner"
        self.assertFalse(assess(snapshot, SETTINGS)["burn_guard"]["checks_passed"])

    def test_unavailable_or_unreviewed_burn_is_not_one_hundred_percent(self):
        snapshot, _ = self.snapshot()
        for field in ("miner_burned_raw", "recycle_or_burn_raw"):
            damaged = deepcopy(snapshot)
            damaged["last_epoch_evidence"][field] = None
            self.assertIsNone(assess(damaged, SETTINGS)["last_epoch_100_percent_miner_burn_verified"])
        self.assertIsNone(assess(snapshot, replace(SETTINGS, miner_burned_semantics=None))["miner_burned"]["fraction"])
        self.assertIsNone(normalized_miner_burned(1 << 32, 480, SEMANTICS))
        self.assertIsNone(normalized_miner_burned(1.0, 481, SEMANTICS))
        self.assertIsNone(normalized_miner_burned(1 << 33, 481, SEMANTICS))

    def test_archive_failure_and_recycle_at_settlement_are_not_burn(self):
        fake = FakeSubstrate()
        fake.archive_available = False
        result = assess(FinalizedChain(SETTINGS, fake).snapshot(), SETTINGS)
        self.assertIsNone(result["last_epoch_100_percent_miner_burn_verified"])
        snapshot, _ = self.snapshot()
        snapshot["last_epoch_evidence"]["recycle_or_burn_raw"] = {"Recycle": ()}
        self.assertIsNone(assess(snapshot, SETTINGS)["last_epoch_100_percent_miner_burn_verified"])

    def test_runtime_upgrade_at_settlement_requires_new_review(self):
        snapshot, _ = self.snapshot()
        snapshot["last_epoch_evidence"]["mode_runtime_spec_version"] = 480
        result = assess(snapshot, SETTINGS)
        self.assertIsNone(result["miner_burned"]["fraction"])
        self.assertIsNone(result["last_epoch_100_percent_miner_burn_verified"])

    def test_fresh_last_update_does_not_prove_burn_row(self):
        snapshot, _ = self.snapshot()
        snapshot["validator"]["last_update"] = 100
        snapshot["validator"]["weights_raw"] = [(0, 65535)]
        result = assess(snapshot, SETTINGS)
        self.assertFalse(result["burn_guard"]["validator_row_100_percent_to_owner"])
        self.assertIsNone(result["last_epoch_100_percent_miner_burn_verified"])

    def test_finalized_regression_and_missing_pins_block(self):
        snapshot, _ = self.snapshot()
        previous = deepcopy(snapshot)
        previous["source_block"] = 101
        self.assertFalse(assess(snapshot, SETTINGS, previous)["burn_guard"]["checks_passed"])
        self.assertFalse(assess(snapshot, Settings())["burn_guard"]["checks_passed"])

    def test_local_state_roundtrip_preserves_mapping(self):
        snapshot, _ = self.snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = directory + "/state.json"
            self.assertIsNone(load_state(path))
            save_state(path, snapshot)
            loaded = load_state(path)
            self.assertEqual(registration_identity(loaded["owner"]), registration_identity(snapshot["owner"]))
            self.assertEqual(loaded["source_hash"], snapshot["source_hash"])


if __name__ == "__main__":
    unittest.main()
