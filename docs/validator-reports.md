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

The PM2 `burn-watch` worker observes finalized chain state every 60 seconds. It
fetches and scores a report once per completed chain epoch, then reuses that
verified snapshot and score until the chain advances. It still rechecks current
UID registration each cycle so a recycled UID cannot inherit an old score.
`poll_seconds` controls retry spacing during a report outage, not report cadence.
It logs `report_scoring` alongside its existing burn evidence.
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

The endpoint is public: miners and validators read the same signed bytes without
an account or API key. `/latest` is the last completed finalized subnet epoch,
currently 360 blocks (roughly 72 minutes). It excludes the in-progress epoch.
The half-open timestamp window follows actual chain epoch boundaries, so a fixed
wall-clock cron does not drift relative to the subnet. The validator independently
checks epoch index, boundary hashes/timestamps and tempo against finalized RPC.
Allow roughly 30–60 seconds for accounting grace and publication after finality.

History is available to everyone:

```
https://api.danilabs.ai/v1/validator/reports/latest?offset=1
https://api.danilabs.ai/v1/validator/reports/latest?offset=2
https://api.danilabs.ai/v1/validator/reports/sn2-v2-<epoch-end-block>
```

The publisher saves each report once as signed JSON files. Latest is served from
memory and supports ETag revalidation; historical reports are read from disk and
are not cached. HTTP never queries the accounting DB. Files are retained for 30
days. Miners can inspect old reports; automated scoring only accepts the latest
completed epoch and never falls back to an old report after an outage. Reports
contain no customer account IDs, API keys, prompts, responses or device credentials.

The logged `submission_preview` checks minimum count, normalized maximum weight,
validator permit/stake and current rate-limit readiness. When candidate limits
pass it encodes the runtime's unsigned `set_weights`, or both `commit_weights`
and `reveal_weights`, and logs their byte lengths and hashes. This never creates
a signed extrinsic or submits one. An encoding test is not a successful chain
transaction: reveal timing, fees, future runtime state and explicit policy still
apply. Commit/reveal delays also mean a one-epoch report lag is not a guarantee
of a one-epoch payout lag.

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
