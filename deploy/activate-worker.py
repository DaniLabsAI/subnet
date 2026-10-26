#!/usr/bin/python3 -I
"""Root-owned restricted sudo helper. Runs candidate Python only as worker user."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if os.geteuid() != 0 or os.uname().nodename != 'danilabs-validator':
    raise SystemExit('This helper is restricted to root on danilabs-validator')
if len(sys.argv) != 2 or not re.fullmatch('[0-9a-f]{40}',sys.argv[1]):
    raise SystemExit('Pass exactly one full commit ID')
sha = sys.argv[1]
release = Path('/opt/danilabs/worker-releases') / sha
if release.is_symlink() or not release.is_dir():
    raise SystemExit('Candidate is missing or symlinked')
if json.loads((release/'.dani-tested.json').read_text()).get('commit') != sha:
    raise SystemExit('Candidate has not passed staged tests')
config = json.loads(Path('/etc/danilabs/worker-launch.json').read_text())
if config['network'] not in ('localnet','finney'):
    raise SystemExit('Unsupported worker network')
settings_file=config.get('settings_file','/etc/danilabs/localnet-validator.json')
if settings_file not in ('/etc/danilabs/localnet-validator.json','/etc/danilabs/finney-validator.json'):
    raise SystemExit('Unsupported worker configuration path')
if json.loads(Path(settings_file).read_text())['network'] != config['network']:
    raise SystemExit('Worker network does not match the root-owned launch configuration')
ecosystem = {'apps':[{'name':'danilabs-validator','script':config['python'],
    'args':['-m','danilabs_validator','--config',settings_file,
            'burn-watch','--signer-socket','/run/danilabs-signer/burn.sock'],
    'cwd':str(release),'interpreter':'none','autorestart':True,'restart_delay':3000,
    'min_uptime':'10s','max_restarts':15,'max_memory_restart':'1G',
    'time':True,'merge_logs':True,'kill_timeout':5000,
    'env':{'PYTHONPATH':str(release/'src'),'PYTHONDONTWRITEBYTECODE':'1',
           'DANI_RELEASE_SHA':sha}}]}
path=Path('/etc/danilabs/worker-runtime.json')
if path.is_symlink():
    raise SystemExit('Unexpected symlink for launch configuration')
path.write_text(json.dumps(ecosystem))
path.chmod(0o644)
prefix=['runuser','-u','dani-validator','--','env','PM2_HOME=/var/lib/dani-validator/.pm2']
subprocess.run(prefix+['/usr/local/bin/pm2','startOrReload',str(path),'--only','danilabs-validator','--update-env'],check=True,cwd='/var/lib/dani-validator')
subprocess.run(prefix+['/usr/local/bin/pm2','save','--force'],check=True,cwd='/var/lib/dani-validator')
link=Path('/opt/danilabs/worker-current')
temporary=link.with_name('worker-current.next')
if temporary.exists() or temporary.is_symlink():
    temporary.unlink()
temporary.symlink_to(release)
temporary.replace(link)
print(json.dumps({'activated_worker_commit':sha,'signer_restarted':False}))
