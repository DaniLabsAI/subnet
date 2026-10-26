# Automatic signer recovery on OCI

The signer starts locked. A separate root-owned systemd service can retrieve one
pinned secret version using the instance's OCI identity and unlock the signer
over its local socket. This covers host reboots and signer crashes without a
manual password prompt. The worker and its updater never receive the password.

## Deployment

Use a standard OCI vault, an AES software-protected encryption key, and a secret
containing the encrypted hotkey's password. Give a dynamic group matching only
the intended instance permission to read secret bundles for only that secret.
Use a separate secret for each environment. Do not put a production password in
the localnet secret or enable Finney as part of localnet testing.

Install the OCI SDK in a separate root-owned environment. The accepted helper
runtime uses `oci==2.189.0`; it does not change the worker's pinned dependencies.
Install the reviewed signer/helper source and wrappers in root-owned locations.
The supplied systemd units expect these wrappers:

- `/usr/local/sbin/danilabs-signerctl`: custodian controls.
- `/usr/local/sbin/danilabs-signer-recovery`: recovery helper using its OCI environment.
- `/usr/local/sbin/danilabs-instance-metadata-guard`: the supplied metadata guard.

Create root-owned recovery configuration at `/etc/danilabs/signer-recovery.json`:

```json
{
  "enabled": false,
  "region": "us-ashburn-1",
  "secret_id": "ocid1.vaultsecret.oc1.iad.REPLACE",
  "secret_version": 1,
  "settings_file": "/etc/danilabs/localnet-validator.json",
  "policy_file": "/etc/danilabs/localnet-signer-policy.json"
}
```

Replace the placeholder and validate the settings/policy before enabling it.
Both the signing policy and recovery configuration must be enabled. Disabled
signing policy prevents secret retrieval. The helper verifies the live signer's
public hotkey, network, enabled policy, emergency-control path and socket peer
UID before transmitting a password.

The persistent control directory `/var/lib/danilabs-recovery` must be owned by
root, group `dani-validator`, mode 750. The runtime directory
`/run/danilabs-recovery` must be root-owned, mode 700; recreate it at boot with
systemd-tmpfiles. Start the signer with
`--recovery-inhibit /var/lib/danilabs-recovery/disabled`.
The service and timer templates are in `deploy/`.

Apply the metadata guard before granting instance-principal access. It restricts
both OCI metadata addresses on TCP 80 to root, preserving DNS and other link-local
services. Make worker/updater startup require the guard. A root administrator
still has access to the unlocked hotkey; this is process isolation on a trusted
host.

## Recovery and emergency controls

```sh
sudo danilabs-signerctl status
sudo danilabs-signerctl recovery-status
sudo danilabs-signerctl lock
sudo danilabs-signerctl resume
sudo journalctl -u danilabs-signer-recovery -n 30
```

`lock` first creates and syncs a persistent emergency flag, then locks the signer.
The signer checks that flag before unlock, maintenance and signing. Recovery
cannot remove it, and it survives crashes and OS reboots. Already-broadcast
transactions may still finalize. `resume` removes the flag; the timer retries
automatic unlock without a password prompt. Manual `unlock` remains available
when automatic recovery is not configured.

The timer checks every ten seconds after each completed attempt. An already
unlocked signer does not fetch the secret again. A secret-service outage leaves
a restarted signer locked and retrying; restoring connectivity permits automatic
recovery. A running, unlocked signer can continue while the secret service is
unavailable. Passwords are never saved in arguments, environment, logs, recovery
status or decrypted files. Each helper process exits after its attempt.

Private signer state, including pending commitments, remains outside release
directories. Do not rotate the secret independently of the encrypted keyfile:
coordinate the keyfile and pinned version as one deployment.

## Updates

The worker continues its tested main-branch update and rollback process. It
cannot update the signer, recovery helper, cloud permissions or signing policy.
Those use separately reviewed, pinned deployments. Restarting the signer after
such a deployment triggers automatic recovery when it is armed. A runtime or
registration mismatch continues to block signing.

Before activation, test automatic reboot/crash recovery, the unavailable-secret
path, emergency inhibition across reboot, explicit resume, worker access denial,
and finalized burn settlement on localnet. Keep the Finney policy disabled until
its finalized registration and operator activation are ready.
