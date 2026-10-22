from __future__ import annotations

from dataclasses import dataclass, fields
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

FINNEY_GENESIS = "0x2f0555cc76fc2840a25a6ea3b9637146806f1f44b090c175ffde2a7e5ab36c03"


@dataclass(frozen=True)
class Settings:
    chain_endpoint: str = "wss://entrypoint-finney.opentensor.ai:443"
    expected_genesis: str = FINNEY_GENESIS
    netuid: int | None = None
    expected_owner_hotkey: str | None = None
    expected_owner_coldkey: str | None = None
    expected_owner_registration_block: int | None = None
    validator_hotkey: str | None = None
    expected_validator_registration_block: int | None = None
    state_file: str = ".state/observer.json"
    poll_seconds: int = 60
    miner_burned_semantics: dict | None = None

    def validate(self) -> None:
        endpoint = urlsplit(self.chain_endpoint)
        if endpoint.scheme != "wss" or not endpoint.hostname or endpoint.username or endpoint.password:
            raise ValueError("A credential-free wss chain endpoint is required")
        if self.expected_genesis != FINNEY_GENESIS:
            raise ValueError("This pilot is pinned to the verified Finney genesis")
        if type(self.netuid) is not int or not 1 <= self.netuid <= 65535:
            raise ValueError("A non-root netuid must be explicitly configured")
        if type(self.poll_seconds) is not int or self.poll_seconds < 15:
            raise ValueError("poll_seconds must be an integer >= 15")
        if not isinstance(self.state_file, str) or not self.state_file.strip():
            raise ValueError("state_file must be a local filename")
        for name in ("expected_owner_hotkey", "expected_owner_coldkey", "validator_hotkey"):
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
