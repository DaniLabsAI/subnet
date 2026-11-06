#!/bin/sh
set -eu

depot=/var/lib/danilabs-sn2-deploy
releases=$depot/releases
current=$depot/current

case "$1" in
  activate)
    test "$#" -eq 2
    commit=$2
    printf '%s\n' "$commit" | grep -Eq '^[0-9a-f]{40}$'
    test -f "$releases/$commit/.dani-tested.json"
    ln -sfn "$releases/$commit" "$current.next"
    mv -Tf "$current.next" "$current"
    exec /usr/bin/sudo -n /usr/bin/systemctl restart danilabs-sn2-validator.service
    ;;
  worker)
    test "$#" -eq 1
    release=$(readlink -f "$current")
    commit=${release##*/}
    printf '%s\n' "$commit" | grep -Eq '^[0-9a-f]{40}$'
    test "$release" = "$releases/$commit"
    export DANI_RELEASE_SHA="$commit" PYTHONPATH="$release/src"
    exec "$depot/venv/bin/python" -m danilabs_validator \
      --config /etc/danilabs-sn2/validator.json score-watch \
      --reports-config /etc/danilabs-sn2/reports.json
    ;;
  *) exit 2 ;;
esac
