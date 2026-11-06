#!/bin/bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 022
cd /

if [[ $EUID != 0 ]]; then
  echo 'Run this installer with sudo.' >&2
  exit 2
fi
. /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 24.04 ]] || [[ ! -d /run/systemd/system ]]; then
  echo 'The SN2 validator installer requires Ubuntu 24.04 with systemd.' >&2
  exit 2
fi
case $(uname -m) in x86_64|aarch64) ;; *) echo 'Use an x86-64 or ARM64 CPU host.' >&2; exit 2 ;; esac

exec 9>/run/lock/danilabs-sn2-install.lock
flock -n 9 || { echo 'An SN2 validator installation is already running.' >&2; exit 1; }
repo=https://github.com/DaniLabsAI/subnet.git
base=/opt/danilabs-sn2
config=/etc/danilabs-sn2
depot=/var/lib/danilabs-sn2-deploy
state=/var/lib/danilabs-sn2/worker.json
worker=danilabs-sn2-validator.service
timer=danilabs-sn2-update.timer
export GIT_TERMINAL_PROMPT=0

as_deploy() {
  runuser -u danilabs-sn2-deploy -- env HOME="$depot" PYTHONPATH="$base/control" \
    PYTHONDONTWRITEBYTECODE=1 "$@"
}

if [[ ! -f $config/updater.json ]]; then
  echo 'Installing DaniLabs SN2 validator prerequisites.'
  missing=()
  for package in ca-certificates git python3-venv sudo; do
    if [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true) != 'install ok installed' ]]; then
      missing+=("$package")
    fi
  done
  if ((${#missing[@]})); then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
  fi
  getent group danilabs-sn2 >/dev/null || groupadd --system danilabs-sn2
  id danilabs-sn2 >/dev/null 2>&1 || useradd --system --gid danilabs-sn2 \
    --home-dir /var/lib/danilabs-sn2 --shell /usr/sbin/nologin danilabs-sn2
  id danilabs-sn2-deploy >/dev/null 2>&1 || useradd --system --gid danilabs-sn2 \
    --home-dir "$depot" --shell /usr/sbin/nologin danilabs-sn2-deploy
  install -d -m 0750 -o danilabs-sn2-deploy -g danilabs-sn2 "$depot" "$depot/releases"
  install -d -m 0750 -o danilabs-sn2 -g danilabs-sn2 /var/lib/danilabs-sn2
  install -d -m 0755 "$base/control/danilabs_validator" "$config"

  stage=$(mktemp -d)
  trap 'rm -rf -- "$stage"' EXIT
  git clone --quiet --branch main --single-branch "$repo" "$stage/subnet"
  source=$stage/subnet
  release=$(git -C "$source" rev-parse HEAD)
  install -m 0644 "$source"/src/danilabs_validator/{__init__,config,health,monitor,updater}.py \
    "$base/control/danilabs_validator/"
  install -m 0755 "$source/deploy/sn2/launch.sh" "$base/launch.sh"
  install -m 0644 "$source"/deploy/sn2/{danilabs-sn2-validator.service,danilabs-sn2-update.service,danilabs-sn2-update.timer} \
    /etc/systemd/system/
  printf '%s\n' 'danilabs-sn2-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart danilabs-sn2-validator.service' >"$stage/sudoers"
  visudo -cf "$stage/sudoers" >/dev/null
  install -m 0440 "$stage/sudoers" /etc/sudoers.d/danilabs-sn2-update

  install -m 0644 "$source/requirements.lock" "$base/requirements.lock"
  as_deploy /usr/bin/python3 -m venv "$depot/venv"
  as_deploy "$depot/venv/bin/python" -m pip --disable-pip-version-check install \
    --require-hashes -r "$base/requirements.lock"

  # Preserve operator configuration when resuming a partially completed install.
  if [[ ! -f $config/reports.json ]]; then
    install -m 0644 "$source/config/reports.example.json" "$config/reports.json"
  fi
  /usr/bin/python3 - "$source" "$release" "$repo" "$base" "$depot" "$config" "$state" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

source, release, repo, base, depot, config, state = sys.argv[1:]
config = Path(config)

def write(name, content):
    path = config / name
    if not path.exists():
        staged = path.with_suffix('.next')
        staged.write_text(json.dumps(content, indent=2) + '\n')
        staged.replace(path)

settings = json.loads((Path(source) / 'config/observer.example.json').read_text())
settings.update(netuid=2, chain_endpoint='wss://archive.chain.opentensor.ai:443',
                weight_submission_mode='legacy-commit-reveal', state_file=state)
write('validator.json', settings)
write('updater.json', {
    'repository': repo, 'branch': 'main', 'initial_commit': release,
    'cache': depot + '/repo.git', 'releases': depot + '/releases',
    'state_file': depot + '/updater.json', 'lock_file': depot + '/update.lock',
    'worker_state': state, 'python': depot + '/venv/bin/python',
    'activate_command': [base + '/launch.sh', 'activate'], 'health_mode': 'score',
    'health_timeout_seconds': 180,
    'requirements_sha256': hashlib.sha256((Path(base) / 'requirements.lock').read_bytes()).hexdigest(),
})
PY
fi

systemctl daemon-reload
systemctl enable "$worker"
if [[ ! -L $depot/current ]]; then
  as_deploy /usr/bin/python3 - "$config/updater.json" <<'PY'
import json
from pathlib import Path
import sys
import time

from danilabs_validator.updater import Updater, command

config = json.loads(Path(sys.argv[1]).read_text())
updater = Updater(config)
if not updater.cache.exists():
    command(['git', 'init', '--bare', str(updater.cache)])
command(['git', '--git-dir', str(updater.cache), 'fetch', '--no-tags',
         config['repository'], 'refs/heads/main:refs/remotes/origin/main'])
release = updater.state['accepted']
staged = updater.releases / release
if staged.is_dir() and not staged.is_symlink() and not (staged / '.dani-tested.json').exists():
    staged.rename(staged.with_name(f'.incomplete-{release}-{time.time_ns()}'))
updater.prepare(release)
updater.activate(release)
PY
else
  systemctl start "$worker"
fi

echo 'Waiting for the validator to verify the latest finalized SN2 report.'
as_deploy /usr/bin/python3 - "$config/updater.json" "$depot/current" <<'PY'
import json
from pathlib import Path
import sys

from danilabs_validator.updater import Updater

config = json.loads(Path(sys.argv[1]).read_text())
updater = Updater(config)
release = Path(sys.argv[2]).resolve(strict=True).name
if not updater.await_health(release):
    raise SystemExit('Initial report verification did not complete. Check journalctl -u danilabs-sn2-validator and rerun the installer.')
scoring = json.loads(Path(config['worker_state']).read_text())['report_scoring']
print(f"Verified {scoring['report_id']} on release {release}.")
PY
systemctl enable --now "$timer"
systemctl is-active "$worker" "$timer"
echo 'DaniLabs SN2 validator and automatic updates are running.'
