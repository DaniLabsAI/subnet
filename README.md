# DaniLabs SN2 validator

DaniLabs runs distributed AI inference on Bittensor Finney subnet 2. This
repository contains the validator worker, signed-report verifier, miner scoring
code, and isolated burn signer.

**Existing SN2 validators can join the scoring pilot now.** Run the verifier
alongside your current validator and compare results from the same finalized
epoch. Use an Ubuntu 24.04 LTS CPU host (x86-64 or ARM64) with at least
**4 vCPUs, 8 GB RAM, and 50 GB SSD** as the recommended starting spec. The host
needs `sudo`, `curl`, and outbound HTTPS and WSS.

```sh
curl -fsSLo install-danilabs-validator.sh https://raw.githubusercontent.com/DaniLabsAI/subnet/main/deploy/install-validator.sh && sudo bash install-danilabs-validator.sh
```

The installer sets up the systemd worker and its auto-updater. Every five
minutes the updater checks `main`. It stages and tests a new commit, checks its
live report verification, and rolls back if the new worker fails that check.

- [Start the validator scoring pilot](docs/validator-onboarding.md)
- [Signed reports, score calculation, and evidence requirements](docs/validator-reports.md)
- [Worker updates and rollback](docs/worker-updates.md)
- [Finney signer custody and activation](docs/production-signer.md)
- [Finalized chain observer](docs/operator-pilot.md) and [localnet testing](docs/localnet-validator.md)

The DaniLabs production signer assigns 100% of its weight to the verified
subnet owner for miner-incentive burn. Scoring runs in shadow mode. Candidate
weights are logged for comparison and are ineligible for miner rewards pending
independent token and correctness verification. A validator’s weight row and
the subnet’s actual burn settlement are checked separately.

For setup and coordination, use [DaniLabs #validators](https://discord.com/channels/1555079929148866610/1564448334322602177).
[Join the DaniLabs Discord](https://discord.gg/df3TYnaX4f) if you need access.
The [DaniLabs operator guide](https://danilabs.ai/docs/validators/) has the same setup steps.
