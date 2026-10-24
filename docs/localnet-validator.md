# Localnet validator pilot

This pilot tests validator operation before production deployment. It signs
only on the pinned private development chain, using the publicly known `//Bob`
development identity. It cannot load the new production hotkey or write to Finney.

## Processes

The **signer** runs as `dani-signer` under `danilabs-localnet-signer.service`.
It checks finalized chain identity and maintains the burn independently of the
PM2 worker. Its source is pinned in a root-owned release. It can connect only
to loopback addresses under its systemd network policy.

The **worker** runs as `dani-validator` under PM2, named `danilabs-validator`.
It reads finalized state and reports the signer status. It holds no private key.

The **updater** runs as `dani-deploy` under a separate PM2 supervisor, named
`danilabs-auto-updater`. It can update the worker through a restricted activation
helper. It cannot read the signer home, use its socket API, or update its source.
The worker health file contains public chain evidence and is readable by the
updater; signer state and commit salts remain private to the signer.

## Chain and burn checks

The localnet genesis is:

```text
0xea6ec824e61841ae3324cee5de0a98d27d4b83a9c423119aa6addf531b024de4
```

The writer is restricted to runtime 482 and weight version 0. It checks owner
hotkey/coldkey association, both UID mappings and registration blocks, validator
permit and effective stake, weight limits, burn mode, mechanism count and
finalized-state continuity. An unknown runtime or changed identity stops signing.

The test subnet keeps commit/reveal enabled. The pilot uses the runtime's manual
commit/reveal calls and persists its salt and commitment before broadcast. It
reads the runtime's epoch counter to reveal within the permitted epoch. Restarting
the signer resumes the same saved commitment. Plain weights are also supported
when explicitly selected and matched to a chain with commit/reveal disabled.
This does not claim acceptance of the Drand timelock path on Finney.

Every weight submission has one destination: the verified owner UID, with raw
weight 65,535. A finalized row is checked separately from actual settlement.
`last_epoch_100_percent_miner_burn_verified` requires the reviewed U96F32 encoding,
the settlement block and its parent's Burn mode, matching runtime versions and
the verified registration pins. Zero emission or missing evidence is not proof
of 100% burn. Validator dividends, owner cut and liquidity are separate.

## Operator controls

On the deployed host, define these helpers in your shell:

```sh
pm2v() { sudo -u dani-validator -H env PM2_HOME=/var/lib/dani-validator/.pm2 pm2 "$@"; }
pm2u() { sudo -u dani-deploy -H env PM2_HOME=/var/lib/dani-deploy/.pm2 pm2 "$@"; }
```

Then use:

```sh
pm2v status
pm2v logs danilabs-validator --lines 30
pm2v stop danilabs-validator
pm2v start danilabs-validator
pm2v restart danilabs-validator --update-env
pm2u status
pm2u logs danilabs-auto-updater --lines 30
```

Stopping the PM2 worker **does not stop burn maintenance**. To stop signing:

```sh
sudo systemctl stop danilabs-localnet-signer
sudo systemctl start danilabs-localnet-signer
sudo journalctl -u danilabs-localnet-signer -f
```

PM2 lists are saved for both users. The `pm2-dani-validator` and
`pm2-dani-deploy` systemd services restore them when those supervisors restart.

The public worker state is `/var/lib/dani-validator/localnet-worker-state.json`.
Signer recovery state is `/var/lib/dani-signer/localnet-state.json`. Localnet
configuration is root-owned at `/etc/danilabs/localnet-validator.json`.

## Worker updates

The updater checks `DaniLabsAI/subnet`'s `main` branch every five minutes. It:

1. Fetches an exact commit and requires forward ancestry from the accepted release.
2. Extracts a separate release, rejects dependency changes and runs its unit tests.
3. Activates the worker through the restricted helper. Candidate code runs as the
   worker user; installation and tests do not run candidate code as root.
4. Requires a fresh healthy heartbeat carrying the candidate's own commit ID.
5. Restores the previous worker if live health fails and quarantines the bad commit.

Fetch failures leave the current worker running. An interrupted activation is
recovered from the updater's saved pending/accepted state. Signer upgrades require
a separate reviewed deployment; the updater never restarts it.

The base SDK environment is pinned to `bittensor==9.12.2` and
`async-substrate-interface==1.6.4`. Changing dependencies requires reviewing and
installing a new base environment; worker updates cannot silently replace it.

## Network and production boundary

The current private test RPC reaches the validator at `ws://127.0.0.1:19944`
through SSH forwards on the operator's Mac. The Mac and forwards must remain
running for this pilot. Loss of that connection blocks signing and marks worker
health unavailable; it never switches to another network. A direct host link or
restricted RPC gateway is needed before removing that Mac dependency.

Finney activation requires live-chain policy review, signing-path acceptance
and an explicit production deployment. The encrypted
encrypted production hotkey remains off this test host.
