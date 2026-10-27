# Validator reports and scoring

Validators fetch signed measurements from:

```
https://api.danilabs.ai/v1/validator/reports/latest
```

The validator verifies the signature using its configured public-key pin, checks
freshness and the schema/network/genesis, and independently checks each miner's
UID, hotkey and registration block at one finalized chain hash. Report rollback,
changes within an immutable window, duplicate identities and inconsistent
measurements are rejected. There is no SSH export or file-input scoring path.

## Run

Copy `config/reports.example.json` to `/etc/danilabs/validator-reports.json`.
It contains the production URL and the report public key distributed with this
repository. The API's `/v1/validator/key` endpoint exposes the same public key
for inspection; the validator never automatically trusts a key from the network.

```sh
git pull --ff-only origin main
python -m danilabs_validator --config /etc/danilabs/finney-validator.json \
  score --reports-config /etc/danilabs/validator-reports.json
```

The PM2 `burn-watch` worker loads that report configuration and polls every
60 seconds. It logs `report_scoring` alongside its existing burn evidence.
Endpoint/signature failures log unavailable candidate weights and leave the
fixed burn worker running. Existing operators must install the reports
configuration; a Git pull does not create their local configuration or signers.

## Policy: performance v2

| Component | Weight | Factor |
| --- | ---: | --- |
| Decode TPS | 50% | TPS / (TPS + model target) |
| TTFT | 35% | target TTFT / (target TTFT + measured TTFT) |
| Completion reliability | 10% | valid completions / (completed + failed requests) |
| Gateway-to-miner RTT | 5% | 250 ms / (250 ms + measured RTT) |

Initial `openai/gpt-oss-20b` targets are 300 TPS and 500 ms TTFT. Missing ping
measurements remain null and contribute zero to the ping component. Client
cancellations are excluded from the reliability denominator. Unknown native
usage and inconsistent measurements never become estimated completed work.
Observed readiness and sample counts are logged as additional diagnostics.

Scores compare the same model and prompt/output-length buckets. Configured
model budgets are divided between workload buckets by observed output volume;
miner scores determine shares within each bucket. The initial policy has one
model budget. New models require an explicit policy update. Largest-remainder
rounding produces deterministic u16 candidate weights summing to 65,535 when
eligible work exists; an empty window produces an empty candidate vector.

## Measurements and trust

Reports cover the preceding 24 hours of terminal accounting received, using a
half-open UTC window. A new immutable snapshot is published per minute with a
30-second closing grace. Every validator can retrieve the exact snapshot at
`/v1/validator/reports/{report_id}`. Reports contain aggregate operational metrics,
without customer account IDs, API keys, prompts, responses or device credentials.

TPS is a gateway-observed decode estimate:
`(output_tokens - 1) * 1000 / (duration_ms - ttft_ms)`. The JSON stores TPS in
integer milli-tokens/second; divide `decode_tps_milli` by 1,000. TTFT starts before
gateway admission and ends at the first nonempty content/reasoning delta. It
includes admission and miner-path latency, and excludes the customer's initial
connection/authentication time. It is not an engine-only benchmark.

RTT is measured with unpredictable WebSocket Ping payloads and matching Pong
responses on the gateway's monotonic clock. It includes transport and runtime
response delay, not the customer-to-gateway link. JSON stores it in microseconds.
Readiness samples describe observed minutes; missing observation periods are
not assumed available.

The service signs the exact HTTP response bytes using a separate sr25519 report
key. Verify `X-Dani-Report-Signature` (base64) and `X-Dani-Report-Key-ID` before
parsing JSON. This uses Bittensor's existing signature library and no validator
wallet key. The service remains the measurement authority; the signature proves
origin and integrity, not independent semantic correctness of generated output.

## Burn stays at 100%

Scores and candidate weights are logged only. They are never passed to the burn
signer. Its fixed owner-destination policy and commit/reveal behavior remain
unchanged. Enabling miner weight submission requires a separately reviewed
signer policy and explicit operator approval; no setting in this report enables it.
