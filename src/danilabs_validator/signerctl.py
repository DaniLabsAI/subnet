"""Local custodian client. Password input is hidden, never an argument or env var."""
import argparse
import getpass
import json
import socket
import sys
import warnings


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
    parser.add_argument('action',choices=('status','unlock','lock'))
    args, unknown=parser.parse_known_args()
    if unknown:
        parser.error('Unsupported arguments; passwords belong only in the hidden prompt')
    message={'action':args.action}
    if args.action=='unlock':
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            parser.error('Unlock from your own Terminal using the hidden prompt')
        warnings.simplefilter('error',getpass.GetPassWarning)
        message['password']=getpass.getpass('Hotkey password (hidden): ')
    try:
        result=request(args.socket,message)
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
