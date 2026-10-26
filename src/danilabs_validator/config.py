from __future__ import annotations

from dataclasses import dataclass, fields
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

FINNEY_GENESIS = "0x2f0555cc76fc2840a25a6ea3b9637146806f1f44b090c175ffde2a7e5ab36c03"
LOCALNET_GENESIS = "0xea6ec824e61841ae3324cee5de0a98d27d4b83a9c423119aa6addf531b024de4"


@dataclass(frozen=True)
class Settings:
    network: str = "finney"
    chain_endpoint: str = "wss://entrypoint-finney.opentensor.ai:443"
    expected_genesis: str = FINNEY_GENESIS
    netuid: int | None = None
    expected_owner_hotkey: str | None = None
    expected_owner_coldkey: str | None = None
    expected_owner_registration_block: int | None = None
    validator_hotkey: str | None = None
    expected_validator_registration_block: int | None = None
    expected_validator_coldkey: str | None = None
    state_file: str = ".state/observer.json"
    poll_seconds: int = 60
    miner_burned_semantics: dict | None = None
    weight_submission_mode: str = "plain"

    def validate(self) -> None:
        endpoint = urlsplit(self.chain_endpoint)
        if not endpoint.hostname or endpoint.username or endpoint.password:
            raise ValueError("A credential-free chain endpoint is required")
        if self.network == "finney":
            if endpoint.scheme != "wss" or self.expected_genesis != FINNEY_GENESIS:
                raise ValueError("Finney requires WSS and its verified genesis")
        elif self.network == "localnet":
            if (endpoint.scheme != "ws" or endpoint.hostname != "127.0.0.1"
                    or self.expected_genesis != LOCALNET_GENESIS):
                raise ValueError("Localnet requires loopback WS and the pinned development genesis")
        else:
            raise ValueError("network must be finney or localnet")
        if self.weight_submission_mode not in ("plain", "legacy-commit-reveal"):
            raise ValueError("Unsupported weight_submission_mode")
        if type(self.netuid) is not int or not 1 <= self.netuid <= 65535:
            raise ValueError("A non-root netuid must be explicitly configured")
        if type(self.poll_seconds) is not int or self.poll_seconds < 15:
            raise ValueError("poll_seconds must be an integer >= 15")
        if not isinstance(self.state_file, str) or not self.state_file.strip():
            raise ValueError("state_file must be a local filename")
        for name in ("expected_owner_hotkey", "expected_owner_coldkey", "validator_hotkey", "expected_validator_coldkey"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a public hotkey address or null")
        for name in ("expected_owner_registration_block", "expected_validator_registration_block"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or null")
        semantics = self.miner_burned_semantics
        if semantics is not None:
            if not isinstance(semantics, dict) or set(semantics) != {"spec_version", "fractional_bits", "source"}:
                raise ValueError("miner_burned_semantics requires spec_version, fractional_bits and source")
            if type(semantics["spec_version"]) is not int or semantics["fractional_bits"] != 32:
                raise ValueError("Only explicitly reviewed U96F32 semantics are supported")
            source = semantics["source"]
            if not isinstance(source, str) or not re.fullmatch(r"https://github\.com/RaoFoundation/subtensor/blob/[0-9a-f]{40}/pallets/subtensor/src/coinbase/run_coinbase\.rs", source):
                raise ValueError("Pin semantics to a reviewed Subtensor commit URL, not a moving branch")


def load_settings(path: str) -> Settings:
    doc = json.loads(Path(path).read_text())
    if not isinstance(doc, dict):
        raise ValueError("Config must be an object")
    unknown = set(doc) - {field.name for field in fields(Settings)}
    if unknown:
        raise ValueError(f"Unknown config fields: {', '.join(sorted(unknown))}")
    result = Settings(**doc)
    result.validate()
    return result
