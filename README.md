# DaniLabs SN2 validator

DaniLabs runs distributed AI inference on Bittensor Finney subnet 2. This
repository contains the validator worker, signed-report verifier, miner scoring
code, and isolated burn signer.

**Existing SN2 validators can join the scoring pilot now.** Run the verifier
alongside your current validator and compare results from the same finalized
epoch. The pilot uses a CPU host and public signed reports. It requires no API
account or wallet access.

- [Start the validator scoring pilot](docs/validator-onboarding.md)
- [Signed reports, score calculation, and evidence requirements](docs/validator-reports.md)
- [Cron updates for the managed worker](docs/worker-updates.md)
- [Finney signer custody and activation](docs/production-signer.md)
- [Finalized chain observer](docs/operator-pilot.md) and [localnet testing](docs/localnet-validator.md)

The DaniLabs production signer assigns 100% of its weight to the verified
subnet owner for miner-incentive burn. Scoring runs in shadow mode. Candidate
weights are logged for comparison and are ineligible for miner rewards pending
independent token and correctness verification. A validator’s weight row and
the subnet’s actual burn settlement are checked separately.

For setup and coordination, use [DaniLabs #validators](https://discord.com/channels/1555079929148866610/1564448334322602177).
[Join the DaniLabs Discord](https://discord.gg/df3TYnaX4f) if you need access.
