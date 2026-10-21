# DaniLabs Subnet

**DaniLabs — Distributed Accelerated Neural Intelligence**

The validator repository for DaniLabs, an inference subnet on Bittensor focused on
no data retention, speed, and low cost.

This repository is the subnet's chain-identity source:
**https://github.com/DaniLabsAI/subnet**.

> **Status: initial documentation.** Validator implementation, tests, operator
> commands, and release artifacts will be added as development progresses. The
> responsibilities below describe the intended architecture, not working code.

## Repository responsibilities

This repository contains the validator side of the subnet:

- **Chain integration:** network configuration, metagraph synchronization, and
  validation of miner UID/hotkey mappings against chain state.
- **Report validation:** consume authenticated performance reports and validate
  their signer, reporting period, freshness, identity bindings, and schema.
- **Miner evaluation:** evaluate eligibility and performance using documented
  measurements of latency, throughput, successful work, and availability.
- **Scoring and weights:** calculate reproducible scores, normalize eligible
  miner weights, and submit them through the validator's Bittensor wallet.
- **Validator operations:** configuration, durable report/epoch processing,
  recovery, diagnostics, tests, and operator documentation.

The scoring formula, integrity checks, reporting contract, and weight activation
policy will be specified and tested before live weight submission is enabled.
Duplicate, stale, or invalid reports must not produce duplicate or unauthorized
weight updates. Reports will describe operational metadata rather than customer
prompts or responses.

## Miners use the miner kit

**Miners do not need to clone or run this repository.** All miner software belongs
in the separate **ManagedVNetIR miner kit**: Managed Virtual Network, Integrated
Runtime.

The miner kit is intended to handle installation, local hotkey signing,
onboarding, hardware assessment, runtime supervision, model loading, and the
outbound authenticated WebSocket connection to DaniLabs. The service backend
selects eligible hardware and assigns the model/runtime configuration. Miner
wallet secrets remain local to the miner.

The kit's Rust agent will manage a pinned GPU inference engine and stream output
as it is generated. Multi-GPU placement and any execution spanning multiple miner
machines require separate implementation and benchmarks.

Validator-facing report and scoring interfaces are documented here as they are
defined; that does not introduce a second miner executable into this repository.

## How the components fit together

1. A customer authenticates to the DaniLabs API with an API key.
2. The service backend authorizes the request and routes it to a ready miner over
   the miner kit's established connection.
3. The managed runtime executes inference and streams results through the backend
   to the customer.
4. The backend produces operational reports containing the metadata needed for
   validator evaluation, without retaining inference content in those reports.
5. Validators validate the reports, evaluate miners under the published policy,
   and submit the resulting chain weights when live submission is enabled.

The backend's reports are an explicit trust boundary. Their authenticity,
measurement accuracy, and the need for independent validator checks must be
resolved before the incentive mechanism is activated. A signed report identifies
its issuer; it does not by itself prove that every reported computation occurred.

## Project boundaries

| Project | Responsibility |
| --- | --- |
| [`DaniLabsAI/subnet`](https://github.com/DaniLabsAI/subnet) | Validator code, chain integration, report validation, scoring, and weight submission |
| ManagedVNetIR miner kit | Miner installation, onboarding, hardware assessment, managed inference runtime, and streaming transport |
| Server / service backend | Customer accounts, API keys, orchestration, request routing, usage accounting, report production, and later payments |
| [`DaniLabsAI/Platform`](https://github.com/DaniLabsAI/Platform) | Website and customer application frontend |

Links to the remaining repositories will be added when they are available.
Customer login, billing, API serving, and GPU inference execution are maintained
in their respective projects.

## Relationship to InstantSubnet

InstantSubnet is a reference for the separation between validators, the service
backend, and the miner kit. DaniLabs will selectively adapt reviewed interfaces
and implementation patterns rather than copy the entire Instant workspace.

DaniLabs is being designed around ManagedVNetIR instead of TOPLOC. Instant's
TOPLOC proof/evidence persistence, scoring formula, model restrictions, and
single-GPU assumptions are not DaniLabs defaults. Any reused source will retain
its applicable license and attribution notices.

## Development priorities

- A Rust core for the gateway, transport, and miner agent, integrated with an
  established GPU inference engine in the appropriate repositories.
- Low latency, real-time output streaming, and measured per-request performance.
- Operational ZDR for inference content, with account and usage metadata handled
  separately.
- Explicit, tested validator policies and safe chain weight submission.

Runtime integrity and confidentiality against a miner's host administrator remain
design requirements to resolve. Encryption in transit and a managed Rust runtime
alone do not establish those guarantees. Model support, context limits, and
throughput claims will be published with validated configurations and evidence.

## Follow the build

- Website: [danilabs.ai](https://danilabs.ai/)
- X: [@danilabsai](https://x.com/danilabsai)
- Organization: [DaniLabsAI](https://github.com/DaniLabsAI)
