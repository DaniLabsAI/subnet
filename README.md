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

This repository currently contains documentation only. The validator
implementation, tests, configuration, and operator setup instructions will be
added as development progresses.
