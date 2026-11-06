# Set up a DaniLabs SN2 validator

Use an Ubuntu 24.04 LTS CPU host (x86-64 or ARM64) with **4 vCPUs, 8 GB RAM,
and 50 GB SSD** as the recommended minimum. The install command needs `sudo`
and `curl`. Allow outbound HTTPS to GitHub, Python package repositories and
DaniLabs, plus outbound WSS to the public Finney archive RPC.

## Install and run

```sh
curl -fsSLo install-danilabs-validator.sh https://raw.githubusercontent.com/DaniLabsAI/subnet/main/deploy/install-validator.sh && sudo bash install-danilabs-validator.sh
```

The installer provisions the Python environment, starts the SN2 worker under
systemd, and verifies its first signed report against finalized Finney state.
It then enables the five-minute update timer. The worker can run alongside your
existing validator. Run the same command again to resume an interrupted setup.

## Check the worker

```sh
sudo systemctl status danilabs-sn2-validator.service danilabs-sn2-update.timer
sudo journalctl -u danilabs-sn2-validator.service -n 20 --no-pager
sudo journalctl -u danilabs-sn2-update.service -n 20 --no-pager
```

The installation prints the active Git commit and verified report ID. The
worker logs its latest finalized epoch and candidate scores. Share your public
SN2 UID if registered, the Git commit, and the report ID in [DaniLabs #validators](https://discord.com/channels/1555079929148866610/1564448334322602177).
If setup fails, include the sanitized error and operating system version.

The updater stages and tests new commits from `main` before activating them.
It accepts a release after it verifies a fresh signed report and restores the
last accepted release if the new one fails. DaniLabs will use this update path
to ship miner rewards support and coordinate the signing policy activation
with operators. [Updater details](worker-updates.md) · [Signer requirements](production-signer.md)
