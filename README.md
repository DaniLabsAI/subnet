# DaniLabs SN2 validator

Validator software for Bittensor Finney subnet 2. The worker verifies signed
performance reports against finalized chain state and scores miners by workload.

## Requirements

Use an Ubuntu 24.04 LTS CPU host (x86-64 or ARM64) with systemd. The recommended
minimum is **4 vCPUs, 8 GB RAM, and 50 GB SSD**. Have `sudo` and `curl` available
and allow outbound HTTPS and WSS connections.

## Install

```sh
curl -fsSLo install-danilabs-validator.sh https://raw.githubusercontent.com/DaniLabsAI/subnet/main/deploy/install-validator.sh && sudo bash install-danilabs-validator.sh
```

Installation starts the worker, verifies a finalized report, and enables
automatic updates. A successful install prints the Git commit and report ID.

## Operate

```sh
sudo systemctl status danilabs-sn2-validator.service danilabs-sn2-update.timer
```

- [Installation, verification, and troubleshooting](docs/validator-onboarding.md)
- [Automatic updates and rollback](docs/worker-updates.md)
- [Report verification and scoring](docs/validator-reports.md)
- [DaniLabs validator documentation](https://danilabs.ai/docs/validators/)

For operator support, share your SN2 UID, Git commit, and report ID in
[DaniLabs #validators](https://discord.com/channels/1555079929148866610/1564448334322602177).
[Join the DaniLabs Discord](https://discord.gg/df3TYnaX4f) for access.
