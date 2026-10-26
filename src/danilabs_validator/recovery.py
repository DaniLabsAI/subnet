"""Root-only automatic unlock using OCI instance identity and a pinned secret."""
from dataclasses import dataclass, fields
import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import struct

from .config import load_settings
from .custody import CustodyError, load_policy, trusted_config
from .monitor import load_state, save_state
from .recovery_guard import Inhibit, control_lock, directory

DEFAULT_CONFIG = '/etc/danilabs/signer-recovery.json'


@dataclass(frozen=True)
class RecoveryConfig:
    enabled: bool = False
    region: str = 'us-ashburn-1'
    secret_id: str = ''
    secret_version: int = 1
    settings_file: str = '/etc/danilabs/localnet-validator.json'
    policy_file: str = '/etc/danilabs/localnet-signer-policy.json'
    socket_file: str = '/run/danilabs-signer/burn.sock'
    disabled_file: str = '/var/lib/danilabs-recovery/disabled'
    lock_file: str = '/run/danilabs-recovery/control.lock'
    status_file: str = '/run/danilabs-recovery/status.json'
    signer_user: str = 'dani-signer'

    def validate(self):
        if type(self.enabled) is not bool or not re.fullmatch(r'[a-z]+(?:-[a-z0-9]+)+-\d+', self.region):
            raise CustodyError('Invalid recovery enable/region configuration')
        if self.enabled and not re.fullmatch(r'ocid1\.vaultsecret\.[a-z0-9.]+', self.secret_id):
            raise CustodyError('An explicit secret OCID is required')
        if type(self.secret_version) is not int or not 1 <= self.secret_version < 2**31:
            raise CustodyError('An explicit positive secret version is required')
        if self.signer_user != 'dani-signer':
            raise CustodyError('Unsupported signer OS identity')
        for name in ('settings_file','policy_file','socket_file','disabled_file','lock_file','status_file'):
            path = Path(getattr(self,name))
            if not path.is_absolute() or '..' in path.parts:
                raise CustodyError('Recovery paths must be absolute')


def load_recovery(path=DEFAULT_CONFIG):
    doc = trusted_config(path)
    if not isinstance(doc,dict) or set(doc) - {f.name for f in fields(RecoveryConfig)}:
        raise CustodyError('Unknown recovery configuration fields')
    result = RecoveryConfig(**doc)
    result.validate()
    return result


def signer_request(config, message):
    """Authenticate the socket server before sending an unlock password."""
    path = Path(config.socket_file)
    uid = pwd.getpwnam(config.signer_user).pw_uid
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid or path.is_symlink():
        raise CustodyError('Signer socket ownership is not trusted')
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(40)
        client.connect(str(path))
        _, peer_uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if peer_uid != uid:
            raise CustodyError('Signer socket peer is not trusted')
        client.sendall((json.dumps(message)+'\n').encode())
        with client.makefile('rb') as stream:
            raw = stream.readline(65537)
        if len(raw) > 65536:
            raise CustodyError('Signer response is too large')
        return json.loads(raw)


def oci_secret(config):
    # OCI lives in a separately reviewed helper environment, not the worker SDK.
    import oci
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner(
        federation_client_retry_strategy=oci.retry.NoneRetryStrategy(),
        retry_strategy=oci.retry.NoneRetryStrategy(), log_requests=False)
    client = oci.secrets.SecretsClient({'region':config.region}, signer=signer,
        timeout=(3,7), retry_strategy=oci.retry.NoneRetryStrategy())
    response = client.get_secret_bundle(config.secret_id, version_number=config.secret_version,
        retry_strategy=oci.retry.NoneRetryStrategy()).data
    content = response.secret_bundle_content
    if (response.secret_id != config.secret_id or response.version_number != config.secret_version
            or content.content_type != 'BASE64' or len(content.content) > 8192):
        raise CustodyError('Secret bundle identity, version or encoding differs')
    password = base64.b64decode(content.content, validate=True).decode('utf-8')
    if not password or len(password) > 1024 or '\x00' in password:
        raise CustodyError('Secret content is not a valid unlock password')
    return password


def recover(config, settings, policy, *, fetch=oci_secret, ipc=signer_request, inhibit=None):
    """Caller holds the root control lock. Results contain only public metadata."""
    config.validate()
    policy.validate(settings)
    common = {'network':settings.network, 'public_hotkey':settings.validator_hotkey,
              'secret_fetch_attempted':False}
    if not config.enabled or not policy.enabled:
        return {**common,'status':'disabled'}
    inhibit = inhibit or Inhibit(config.disabled_file)
    if inhibit.active():
        return {**common,'status':'emergency_locked'}
    current = ipc(config, {'action':'status'})
    if (current.get('network') != settings.network
            or current.get('public_hotkey') != settings.validator_hotkey
            or current.get('signing_enabled') is not True
            or current.get('emergency_lock_file') != config.disabled_file):
        raise CustodyError('Live signer identity, policy or emergency control differs')
    if current.get('emergency_locked'):
        return {**common,'status':'emergency_locked'}
    if current.get('key_locked') is False:
        return {**common,'status':'unlocked'}
    if current.get('key_locked') is not True:
        raise CustodyError('Signer lock state is unavailable')
    common['secret_fetch_attempted'] = True
    password = None
    message = None
    try:
        password = fetch(config)
        if inhibit.active():
            return {**common,'status':'emergency_locked'}
        message = {'action':'unlock','password':password}
        result = ipc(config, message)
        if (result.get('status') != 'unlocked' or result.get('key_locked') is not False
                or result.get('public_hotkey') != settings.validator_hotkey
                or result.get('network') != settings.network):
            return {**common,'status':'blocked','reason':'Signer refused automatic unlock'}
        return {**common,'status':'unlocked','recovered':True}
    except Exception as exc:
        # Never log native exception text, request bodies or SDK response objects.
        return {**common,'status':'retrying','error_type':type(exc).__name__,
                'reason':'Secret retrieval or signer unlock unavailable'}
    finally:
        if message is not None:
            message.pop('password',None)
        password = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=DEFAULT_CONFIG)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise CustodyError('Automatic recovery is restricted to root')
    config = load_recovery(args.config)
    with control_lock(config.lock_file):
        settings = load_settings(config.settings_file)
        policy = load_policy(config.policy_file,settings,settings_path=config.settings_file)
        try:
            result = recover(config,settings,policy)
        except Exception as exc:
            result = {'status':'blocked','error_type':type(exc).__name__,
                      'reason':'Recovery configuration, control or signer unavailable'}
        directory(Path(config.status_file).parent)
        previous = load_state(config.status_file) or {}
        result['checked_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        result['secret_fetch_attempts'] = previous.get('secret_fetch_attempts',0) + int(result.get('secret_fetch_attempted',False))
        result['last_recovered_at'] = result['checked_at'] if result.get('recovered') else previous.get('last_recovered_at')
        save_state(config.status_file,result)
        if result['status'] != previous.get('status') or result.get('recovered'):
            print(json.dumps(result,sort_keys=True),flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status':'blocked','error_type':type(exc).__name__,
                          'reason':'Recovery service unavailable'}),flush=True)
        raise SystemExit(1)
