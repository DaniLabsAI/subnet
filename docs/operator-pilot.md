# Validator observer pilot

The observer commands in this guide read finalized state for an explicitly
configured subnet. They open no wallet and do not maintain burn weights. Keep
the existing Finney burn process running while the observer is tested. The
separate [localnet burn pilot](localnet-validator.md) has its own signer and
deployment controls; installing source alone does not activate it.

## Host

Use a Linux CPU host with **4 vCPUs, 8 GB RAM and 50 GB SSD** as a practical
starting allocation; **8 vCPUs and 16 GB RAM** leaves room for later report
processing. These are DaniLabs planning estimates, not Bittensor protocol
minimums or a measured capacity guarantee. This observer does not run inference
and needs no GPU. GPU requirements for future verification are undecided.

Use Python 3.11 or 3.12 in an isolated environment. The chain adapter follows the
existing SDK 9.12.2 storage-query interface and pins that dependency. Verify its
native dependencies on the selected Linux architecture during host acceptance;
do not assume newer SDK APIs are drop-in replacements. The official generic
[compute template](https://github.com/RaoFoundation/bittensor-subnet-template/blob/main/min_compute.yml)
is a subnet-authoring example, not a universal GPU requirement for validators.

The process needs outbound HTTPS/WSS access to a trusted Finney RPC, DNS and
correct host time. Historical state is needed for settlement evidence. There is
no inbound server, public axon or local chain node in this observer. A future
challenge protocol may introduce additional network requirements. Keep private
keys and wallet directories inaccessible to the observer user.

## Local setup

Run from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp config/observer.example.json config/observer.local.json
```

Set `netuid` to the subnet you operate before running the commands below. There
is no default subnet identifier. The local configuration is ignored by Git.

```sh
.venv/bin/dani-validator --config config/observer.local.json status
.venv/bin/dani-validator --config config/observer.local.json shadow
.venv/bin/dani-validator --config config/observer.local.json watch --count 3
```

The commands above query public chain data. Only `watch` writes local observer
state. Keep local configurations outside Git if they contain operational paths.
If the Python installation lacks a working default CA bundle, point
`SSL_CERT_FILE` to the installed certifi CA file; TLS verification stays enabled.
The example deliberately leaves public identity pins empty. A missing pin blocks
the burn guard; it does not silently trust the first owner or assume UID 0.

After independently confirming the identities, fill `expected_owner_hotkey`,
`expected_owner_coldkey`, `expected_owner_registration_block`,
`validator_hotkey`, and `expected_validator_registration_block`. These are public
addresses and registration blocks, never seeds or private keys. The chain's
`Uids` and `Keys` mappings must agree at one finalized hash. The observer records
the current owner UID, validator UID, permit, raw stake fields, weight row and
source block/hash. `stake_weight_raw` is the chain's normalized u16 consensus
weight, not a TAO balance; the separately named raw stake fields remain raw.

`shadow` currently reports `pending_authenticated_reports` and emits no scores.
There is no signed validator-report contract or approved scoring formula yet.
An account token, miner telemetry or local JSON file is not accepted as trusted
reward evidence. This is an executable observer, not a completed validator.

## Reading the burn evidence

Keep three questions separate:

1. Does this validator's finalized weight row assign exactly 65,535 to the
   current owner UID and nothing else?
2. Was the latest epoch's withheld miner incentive destroyed under `Burn`, or
   returned under `Recycle`?
3. What proportion of the whole subnet's miner incentive was withheld?

A validator controls its own row. Other validators and consensus affect the
network result. Neither a fresh `LastUpdate` nor a submitted row proves that
the subnet burned 100% of its miner incentive. Owner cut, validator dividends and
liquidity injections are separate from miner incentive.

The runtime's `MinerBurned` counter includes both burning and recycling. The
observer keeps its raw encoding and source block. It queries the settlement's
parent-state `RecycleOrBurn`, because epoch settlement occurs before that
block's extrinsics. Missing archive data yields unavailable evidence.

`miner_burned_semantics` is null by default: the field's metadata name alone does
not establish its fixed-point scale. Only after reviewing the deployed runtime,
configure an object with `spec_version`, `fractional_bits: 32`, and a `source`
URL pinned to the exact 40-character Subtensor commit containing
`pallets/subtensor/src/coinbase/run_coinbase.rs`. This acknowledges the reviewed
U96F32 encoding; the observer cannot verify that review on your behalf. A runtime
version mismatch, upgrade at settlement, malformed value, absent source,
unverified registration or burn mode leaves full-burn verification unavailable.
There is no automatic fallback to 100%.

The guard also blocks unverified commit/reveal compatibility, extra mechanisms,
identity changes and regressing finalized state. Passing its checks authorizes
no transaction and is not a complete weight-writer preflight.

## Process supervision

The uninstalled template is in `deploy/danilabs-validator-observer.service`.
For a later reviewed host deployment, use a dedicated `dani-validator` user,
read-only source/virtualenv under `/opt/danilabs/subnet`, configuration under
`/etc/danilabs/validator-observer.json`, and set `state_file` to
`/var/lib/danilabs-validator/observer.json`. The systemd sandbox permits writes
only to its state directory. It requires no wallet mounts or public ports.
Observe JSON output in the journal; alerts for stalled polling and RPC failures
remain an operator responsibility. Do not replace an existing burn service with
this unit.

## Before enabling a production burn writer

Preserve and audit the existing writer first. Confirm the deployed runtime,
owner/validator registration, effective stake, permit, mechanism count,
commit/reveal path, version key, weight limits and rate limit at finalized state.
Read all relevant validator rows and pending commits. Test any future writer on
localnet or testnet, isolate the hotkey signer, and wait for finalization before
reading back the exact row. Never load a coldkey private key into this process.

Burn maintenance must run independently of inference reports so no GPU or
missing report can stall it. Never disable commit/reveal or change network
hyperparameters merely to fit an older writer. Do not set the newer subnet
emission-vector burn slot to 100%: that slot is currently reserved at zero and
is distinct from directing miner incentive to owner-associated burn UIDs.

Only after stable observation and burn verification should a separate real
miner be registered, served, challenged and scored in shadow. Check its owner
association: miner incentive sent to owner-associated hotkeys is withheld. Live
score weights and other validators require authenticated report/challenge
evidence, documented scoring, replay protection, identity-at-epoch validation,
and an explicit activation step in a later release.

## Verification

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests use an injected fake substrate and never touch a wallet or chain. They
cover finalized source hashes, network pins, recycled UIDs, changed owners,
unknown burn evidence, archive failures and settlement-time mode. Native SDK
installation and live RPC compatibility still need host acceptance.

## Primary references

- [Validating and permit rules](https://www.bittensor.com/docs/guides/validating)
- [Mining and owner-associated hotkeys](https://www.bittensor.com/docs/guides/mining)
- [Runtime miner-incentive settlement](https://github.com/RaoFoundation/subtensor/blob/main/pallets/subtensor/src/coinbase/run_coinbase.rs)
- [Runtime weight checks](https://github.com/RaoFoundation/subtensor/blob/main/pallets/subtensor/src/subnets/weights.rs)
- [Storage fields and MinerBurned semantics](https://guides.learnbittensor.org/subtensor-api/storage)
- [Subnet emission-vector constraints](https://www.bittensor.com/docs/guides/etao)
