"""Encrypted hotkey custody and separately approved, root-owned signing policy."""
from __future__ import annotations

from dataclasses import dataclass, fields
import json
import os
from pathlib import Path
import re
import secrets
import stat

from .config import FINNEY_GENESIS, LOCALNET_GENESIS, Settings

RUNTIME_REVIEWS = {
    482: '8cf229f8ef969389d054a4c161b53ffd164a041f',
    484: '5749dbfbe4a78ccd3938d46ffae45e059488feb7',
}


class CustodyError(RuntimeError):
    """A deliberately public error; never carries passwords or native key errors."""


@dataclass(frozen=True)
class SignerPolicy:
    enabled: bool = False
    network: str = 'localnet'
    expected_genesis: str = LOCALNET_GENESIS
    netuid: int | None = None
    runtime_spec: int = 482
    runtime_source_commit: str = RUNTIME_REVIEWS[482]
    version_key: int = 0
    keyfile: str = '/var/lib/dani-signer/keys/localnet-validator'
    refresh_blocks: int = 20

    def validate(self, settings):
        settings.validate()
        if type(self.enabled) is not bool:
            raise CustodyError('Policy enabled must be a boolean')
        if (self.network, self.expected_genesis, self.netuid) != (
                settings.network, settings.expected_genesis, settings.netuid):
            raise CustodyError('Signing policy does not match the configured chain/subnet')
        expected = {'finney': FINNEY_GENESIS, 'localnet': LOCALNET_GENESIS}
        if self.expected_genesis != expected.get(self.network):
            raise CustodyError('Unknown signing network/genesis')
        if RUNTIME_REVIEWS.get(self.runtime_spec) != self.runtime_source_commit:
            raise CustodyError('Runtime requires a separate source review')
        if type(self.version_key) is not int or not 0 <= self.version_key < 2**64:
            raise CustodyError('Invalid policy weight version')
        if type(self.refresh_blocks) is not int or not 1 <= self.refresh_blocks <= 10000:
            raise CustodyError('Invalid refresh interval')
        if not Path(self.keyfile).is_absolute():
            raise CustodyError('The encrypted hotkey path must be absolute')
        if self.enabled:
            names = ('expected_owner_hotkey', 'expected_owner_coldkey',
                     'expected_owner_registration_block', 'validator_hotkey',
                     'expected_validator_registration_block', 'expected_validator_coldkey')
            if any(getattr(settings, name) is None for name in names):
                raise CustodyError('Activation requires every registration and coldkey pin')


def trusted_config(path):
    """Only the root-owned deployment configuration can authorize real signing."""
    target = Path(path)
    if not target.is_absolute() or target.resolve() != target:
        raise CustodyError('Configuration must use an absolute path without symlinks')
    for candidate in (target, *target.parents):
        info = candidate.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            raise CustodyError('Signing configuration and parents must be root-owned and not writable by others')
    return json.loads(target.read_text())


def load_policy(path, settings, *, settings_path):
    trusted_config(settings_path)
    doc = trusted_config(path)
    if not isinstance(doc, dict) or set(doc) - {x.name for x in fields(SignerPolicy)}:
        raise CustodyError('Unknown signer policy fields')
    result = SignerPolicy(**doc)
    result.validate(settings)
    return result


class EncryptedHotkey:
    """Never writes decrypted keys or saves a password in argv/environment/state."""
    def __init__(self, path, public_ss58):
        self.path = Path(path)
        self.public_ss58 = public_ss58
        self._pair = None

    @property
    def is_unlocked(self):
        return self._pair is not None

    def _encrypted_bytes(self):
        if not self.path.is_absolute():
            raise CustodyError('Hotkey path must be absolute')
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384):
                raise CustodyError('Hotkey must be a signer-owned regular file with mode 600')
            # Parent directories must not let another OS user replace the file.
            for parent in self.path.parents:
                meta = parent.stat()
                mode = stat.S_IMODE(meta.st_mode)
                sticky_root = meta.st_uid == 0 and bool(mode & stat.S_ISVTX)
                if meta.st_uid not in (0, os.geteuid()) or (mode & 0o022 and not sticky_root):
                    raise CustodyError('Hotkey parents must not be writable by another user')
            data = os.read(fd, 16385)
        finally:
            os.close(fd)
        from bittensor_wallet.keyfile import keyfile_data_is_encrypted
        if not keyfile_data_is_encrypted(data):
            raise CustodyError('Plaintext hotkey files are refused')
        return data

    def unlock(self, password):
        self.lock()
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise CustodyError('Unlock failed')
        data = self._encrypted_bytes()
        try:
            from bittensor_wallet import Keypair
            from bittensor_wallet.keyfile import decrypt_keyfile_data, deserialize_keypair_from_keyfile_data
            pair = deserialize_keypair_from_keyfile_data(decrypt_keyfile_data(data, password=password))
            if (pair.ss58_address != self.public_ss58 or pair.crypto_type != 1
                    or pair.ss58_format != 42):
                raise CustodyError('Encrypted key does not match the pinned SR25519 identity')
            challenge = b'DaniLabs signer unlock verification v1:' + secrets.token_bytes(32)
            if not Keypair(ss58_address=self.public_ss58).verify(challenge, pair.sign(challenge)):
                raise CustodyError('Encrypted key failed its local signing check')
        except CustodyError:
            raise
        except Exception:
            raise CustodyError('Unlock failed') from None
        self._pair = pair

    def lock(self):
        self._pair = None

    def signing_key(self):
        if self._pair is None:
            raise CustodyError('Signer is locked')
        return self._pair
