# Managed validator worker updates

## Operator installations

The [operator installer](validator-onboarding.md) enables
`danilabs-sn2-update.timer`, which checks `main` every five minutes. It stages
and tests the commit, then restarts the dedicated scoring worker and waits for
that commit to verify the latest finalized SN2 report. A failed release is
quarantined after the last healthy release is restored. Interrupted rollbacks
are retried before another candidate can start. Changes to the dependency lock
require an operator-reviewed environment update.

```sh
sudo systemctl list-timers danilabs-sn2-update.timer
sudo journalctl -u danilabs-sn2-update.service -n 30 --no-pager
```

## DaniLabs production host

The DaniLabs host checks its configured upstream branch every five minutes
with [the cron entry](../deploy/danilabs-validator-updater.cron). It tracks
`main` on `https://github.com/DaniLabsAI/subnet.git`. An installation using
`master` can select that branch explicitly in its local configuration.

1. `dani-deploy` fetches the configured ref into a bare Git cache. The updater
   accepts only descendants of the last accepted commit.
2. It stages the exact commit, checks its dependency pins against the approved
   Python environment, and runs the candidate's unit tests.
3. A root-owned, restricted helper activates only the validator worker. The
   updater waits for a healthy heartbeat from that exact commit and restores
   the last accepted release if the check fails. A failed candidate stays
   quarantined, and an interrupted rollback is retried before another update.

Run one scheduler per host. On the managed host, the cron entry is installed
as `/etc/cron.d/danilabs-validator-updater`, the scheduler code is pinned under
`/opt/danilabs/validator-updater/current`, and the root-owned configuration is
`/etc/danilabs/updater.json`. The `dani-deploy` account owns its Git cache,
release staging directory, and update state. Treat writes to the configured
upstream branch as worker release authority. Use a reviewed merge process for
code changes and review dependency changes before updating the base environment.

```sh
sudo journalctl -t danilabs-validator-updater -n 30
sudo cat /var/lib/dani-deploy/updater-state.json
readlink -f /opt/danilabs/worker-current
```

`updated` and `up_to_date` are successful runs. `check_in_progress` means the
previous invocation still holds the update lock. For a rejected candidate,
read its `.dani-test.log` in the staged release directory. For
`rollback_needs_attention`, check the worker heartbeat and the activation
helper before clearing or retrying anything manually.

The signer runs under a separate user and root-owned policy. The cron job
updates worker code only. It cannot approve a Finney runtime, access wallet
material, change the weight policy, or restart the signer. A Finney runtime
upgrade requires review of the finalized code and a separately deployed signer
policy. [Signer custody and activation](production-signer.md)
