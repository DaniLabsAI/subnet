# Burn signer custody and activation

The signer has one transaction policy: weight 65,535 to the verified subnet owner
UID. The worker and updater cannot supply a different destination, weight, subnet,
version, or arbitrary payload. Registration/coldkey pins, network genesis, runtime
review, validator permit, effective stake, weight limits and rate limits are
checked before signing, and identities are checked again before each signature.

## Policy and custody

The service requires two absolute root-owned configuration files: observer
settings (`--config`) and signing policy (`--policy`). Neither file nor its parents
may be writable by other users, and symlinks are refused. Policy fields are:

```json
{
  "enabled": false,
  "network": "finney",
  "expected_genesis": "0x2f0555cc76fc2840a25a6ea3b9637146806f1f44b090c175ffde2a7e5ab36c03",
  "netuid": null,
  "runtime_spec": 484,
  "runtime_source_commit": "5749dbfbe4a78ccd3938d46ffae45e059488feb7",
  "version_key": 0,
  "keyfile": "/var/lib/dani-signer/keys/finney-validator",
  "refresh_blocks": 200
}
```

This is an inactive template: fill the intended subnet, actual weight version and
all observer registration/coldkey pins from independently verified finalized
state. An enabled policy with missing pins or an unreviewed runtime is refused.
Changing an endpoint or a network label alone cannot authorize another chain.
Do not enable a production policy as part of localnet acceptance.

The hotkey must be a standard encrypted Bittensor keyfile, a regular file owned
by `dani-signer` with mode 600. Its parent directories must prevent replacement
by other users. Plaintext files, symlinks, wrong passwords, wrong identities and
non-SR25519 keys are rejected. No coldkey private key is needed or loaded.

Every daemon start is **locked**. The private key exists in memory only after a
custodian unlock. The password is not placed in PM2, arguments, environment
variables, logs, state or a decrypted file. `MemorySwapMax=0` and `LimitCORE=0`
belong in the service sandbox. This is OS/process isolation, not protection from
the host administrator.

## Custodian controls

On the configured host:

```sh
sudo danilabs-signerctl status
sudo danilabs-signerctl unlock
sudo danilabs-signerctl lock
```

Unlock requires the custodian's own Terminal and hidden password prompt. It first
checks the live chain and signing policy. The daemon accepts unlock/lock only from
root or its own OS user over a local Unix socket. The PM2 worker may read public
status; the updater is denied access. There is no general-purpose signing API.

Lock prevents new signatures and drops the key reference. Restart the daemon for
a fresh locked process. Previously broadcast transactions may still finalize;
saved weights remain on-chain. After a host reboot, services recover but signing
requires a new manual unlock. Private state retains unfinished commitments so a
valid reveal can resume without guessing or changing its salt.

## Commit/reveal

This release implements the manual `commit_weights` / `reveal_weights` protocol
supported by reviewed runtimes 482 and 484. It uses `SubnetEpochIndex` and
`RevealPeriodEpochs`, rather than inferring epochs from block modulo. These calls
remain separate from the Drand timelocked protocol whose global version is 4.
No timelock-ciphertext compatibility or automatic fallback is claimed here.
The selected submission mode must match the chain's commit/reveal flag; the
signer never disables that flag to fit its implementation.

The salt, identity, network and weight version are persisted and synced before
broadcast. Account nonces come from the pending transaction pool. A changed
identity, chain, runtime or weight version blocks stale work. Transaction receipts
and finalized rows are checked separately from actual miner-burn settlement.

## Acceptance before activation

Use encrypted test keys on localnet to exercise hidden/local unlock, wrong
password and key rejection, worker/updater access denial, commit/reveal and saved
commit recovery, lock/restart/reboot, RPC reconnection, fixed-weight enforcement,
and final epoch burn evidence. Keep the production key off that test host.

Production activation is a separate operator step after final chain identity and
policy review. It is not performed by publishing source or restarting the updater.
