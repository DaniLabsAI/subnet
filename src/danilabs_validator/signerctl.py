"""Local custodian client. Password input is hidden, never an argument or env var."""
import argparse
import getpass
import json
import socket
import sys
import warnings
import os
from pathlib import Path

from .recovery import DEFAULT_CONFIG, load_recovery, signer_request
from .recovery_guard import Inhibit, control_lock


def request(path, message):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(180)
        client.connect(path)
        client.sendall((json.dumps(message)+'\n').encode())
        with client.makefile('rb') as stream:
            response=stream.readline(65537)
        if len(response)>65536:
            raise ValueError('Signer response too large')
        return json.loads(response)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket',default='/run/danilabs-signer/burn.sock')
    parser.add_argument('--recovery-config',default=DEFAULT_CONFIG)
    parser.add_argument('action',choices=('status','unlock','lock','resume','recovery-status'))
    args, unknown=parser.parse_known_args()
    if unknown:
        parser.error('Unsupported arguments; passwords belong only in the hidden prompt')
    configured = Path(args.recovery_config).exists()
    if args.action in ('lock','resume','recovery-status') and configured:
        if os.geteuid() != 0:
            parser.error('Recovery controls require root')
        config = load_recovery(args.recovery_config)
        if args.socket != config.socket_file:
            parser.error('Socket differs from the recovery configuration')
        inhibit = Inhibit(config.disabled_file)
        if args.action == 'lock':
            # Inhibit immediately, including while an automatic unlock holds its lock.
            inhibit.disable()
            with control_lock(config.lock_file):
                result = signer_request(config,{'action':'lock'})
                result['automatic_recovery_disabled'] = True
            print(json.dumps(result,indent=2))
            return 0 if result.get('key_locked') is True else 1
        if args.action == 'resume':
            with control_lock(config.lock_file):
                inhibit.resume()
            print(json.dumps({'status':'recovery_enabled','automatic_retry':True}))
            return 0
        print(json.dumps({'status':'emergency_locked' if inhibit.active() else 'armed',
                          'enabled':config.enabled},indent=2))
        return 0
    if args.action in ('resume','recovery-status'):
        parser.error('Automatic recovery is not configured')
    message={'action':args.action}
    if args.action=='unlock':
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            parser.error('Unlock from your own Terminal using the hidden prompt')
        warnings.simplefilter('error',getpass.GetPassWarning)
        message['password']=getpass.getpass('Hotkey password (hidden): ')
    try:
        result=signer_request(load_recovery(args.recovery_config),message) if configured and os.geteuid()==0 else request(args.socket,message)
    finally:
        message.pop('password',None)
    print(json.dumps(result,indent=2))
    return 1 if result.get('status')=='blocked' else 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(json.dumps({'status':'unavailable','error_type':type(exc).__name__}))
        sys.exit(1)
