# DaniLabs Subnet

DaniLabs is a Bittensor subnet for distributed AI inference. This repository is
home to its validator software: the code that evaluates miner performance,
calculates scores, and submits weights to Bittensor.

The validator's role is to determine how miners are rewarded for the inference
work they contribute. This repo is intended for validator operators and
contributors developing the subnet's evaluation and incentive rules.

## Validator responsibilities

The validator is being developed to:

- Track subnet state and associate registered miners with their on-chain
  identities.
- Check the source, format, and freshness of performance reports, rejecting
  invalid or duplicate submissions.
- Evaluate inference performance using latency, token throughput, completed
  requests, and availability.
- Calculate miner scores using consistent, documented evaluation rules.
- Convert eligible miner scores into weights and submit them to Bittensor.

## Scoring

The goal is to reward useful, fast, reliable inference. Scoring needs to account
for both performance and successful completion, so generation speed alone does
not determine a miner's score.

The scoring formula, eligibility requirements, and measurement definitions are
still being developed. They will be documented and tested here before live
weight submission is enabled. Validator reports should contain operational
measurements, without customer prompts or generated responses.

## Current status

The validator includes a read-only finalized-chain observer and a **localnet
burn pilot**. The pilot runs an isolated signer, a PM2 worker, and a staged worker
updater with health checks and rollback. It targets the subnet owner's registered
UID and verifies the resulting weight row and miner-burn settlement separately.

The signer supports encrypted hotkey custody, an explicit operator policy, and
optional automatic recovery through OCI Secret Management.
The deployed pilot uses a development key on localnet; Finney signing is disabled.
Miner scoring and production activation are still pending.

See the [observer guide](docs/operator-pilot.md) for chain monitoring and the
[localnet guide](docs/localnet-validator.md) for burn testing, PM2 controls and
updates. The [signer guide](docs/production-signer.md) covers key custody and
production activation requirements.
