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

Validators fetch signed aggregate reports over HTTPS, verify registered miner
identities against finalized chain state, and calculate candidate weights.
The current policy weights TPS at 50%, TTFT at 35%, completion reliability at
10%, and gateway-to-miner RTT at 5%. Reports exclude customer prompts and
responses. See [report setup and scoring](docs/validator-reports.md).

Performance reports are not execution proofs. Gateway timing is observed by the
gateway, while token usage is still miner-reported. Candidate scores remain
explicitly ineligible for miner rewards pending independent token and correctness
verification. Current live signing remains constrained to **100% burn**.

## Current status

The validator includes a finalized-chain observer and a **100% burn mode**.
It runs an isolated signer, a PM2 worker, and a staged worker
updater with health checks and rollback. It targets the subnet owner's registered
UID and verifies the resulting weight row and miner-burn settlement separately.

The signer supports encrypted hotkey custody, an explicit operator policy, and
optional automatic recovery through OCI Secret Management.
The production validator runs on Finney with 100% miner-incentive burn. Miner
scores and candidate weights are logged without changing the burn signer.
Changes are tested on localnet before deployment.

See the [observer guide](docs/operator-pilot.md) for chain monitoring and the
[localnet guide](docs/localnet-validator.md) for burn testing, PM2 controls and
updates. The [signer guide](docs/production-signer.md) covers key custody and
production activation requirements.
