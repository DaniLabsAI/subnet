# Install the DaniLabs SN2 validator

## Requirements

Use an Ubuntu 24.04 LTS CPU host (x86-64 or ARM64) with systemd. The recommended
minimum is **4 vCPUs, 8 GB RAM, and 50 GB SSD**. Have `sudo` and `curl` available.
Allow outbound HTTPS to GitHub, Python package repositories, and DaniLabs, plus
outbound WSS to the Finney archive RPC.

## Install

```sh
curl -fsSLo install-danilabs-validator.sh https://raw.githubusercontent.com/DaniLabsAI/subnet/main/deploy/install-validator.sh && sudo bash install-danilabs-validator.sh
```

The installer provisions Python, starts the worker under systemd, and verifies
its first signed report against finalized Finney state. It enables automatic
updates after verification. Rerun the same command to resume an interrupted
installation.

## Verify

The installer prints the release commit and verified report ID. Check that the
worker service and update timer are active.

```sh
sudo systemctl status danilabs-sn2-validator.service danilabs-sn2-update.timer
sudo journalctl -u danilabs-sn2-validator.service -n 20 --no-pager
```

## Troubleshoot

If report verification fails, check the worker journal and outbound HTTPS and
WSS connectivity. The [update guide](worker-updates.md) covers update failures
and recovery. For help, share your public SN2 UID, Git commit, report ID, and
sanitized error in [DaniLabs #validators](https://discord.com/channels/1555079929148866610/1564448334322602177).
