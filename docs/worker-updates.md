# Validator updates

The [installer](validator-onboarding.md) enables `danilabs-sn2-update.timer`,
which checks the DaniLabs GitHub `main` branch every five minutes.

1. The updater stages a commit and runs the validator test suite.
2. It starts the staged worker and waits for that commit to verify a fresh
   signed report against the latest finalized SN2 epoch.
3. It accepts the release after verification. If verification fails, it
   restores the last accepted release and quarantines the failed commit.

If an update is interrupted, the updater restores the last accepted release
before considering another commit. A change to the dependency lock requires
an operator-reviewed environment update.

## Check or run an update

```sh
sudo systemctl list-timers danilabs-sn2-update.timer
sudo journalctl -u danilabs-sn2-update.service -n 30 --no-pager
sudo systemctl start danilabs-sn2-update.service
```

`updated` means the new commit passed verification. `up_to_date` means the
accepted commit matches `main`. If an update is rejected during testing, read
`.dani-test.log` in the corresponding commit directory under
`/var/lib/danilabs-sn2-deploy/releases/`. For `rollback_needs_attention`, check
the worker status and journal before retrying.
