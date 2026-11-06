# Validator reports and scoring

The validator evaluates miners using signed performance reports for finalized
Finney SN2 epochs. Each report includes its ID, content digest, and epoch
boundaries. Compare results from the same report ID and digest.

## Reports

- [Latest finalized report](https://api.danilabs.ai/v1/validator/reports/latest)
- [Previous finalized report](https://api.danilabs.ai/v1/validator/reports/latest?offset=1)
- [Report verification key](https://api.danilabs.ai/v1/validator/key)

To fetch a report by ID, append the ID to
`https://api.danilabs.ai/v1/validator/reports/`. Report contents are immutable
after publication. Each report includes its measurement version so validators
can interpret historical data under the corresponding scoring rules.

## Verification

The worker verifies the sr25519 signature over the exact response bytes using
the public key pinned in its report configuration. The HTTP headers are
`X-Dani-Report-Signature` and `X-Dani-Report-Key-ID`.

The worker checks epoch boundaries and miner registrations against finalized
Finney state. It rejects reports with invalid signatures, mismatched network
or epoch metadata, duplicate miner identities, and inconsistent measurements.
It rechecks miner registrations as the chain advances so a reassigned UID
cannot inherit a prior miner's results.

## Performance scoring

| Component | Weight | Normalized factor |
| --- | ---: | --- |
| Decode throughput | 50% | TPS / (TPS + target TPS) |
| Time to first token | 35% | Target TTFT / (target TTFT + measured TTFT) |
| Completion reliability | 10% | Successful completions / (successful completions + failures) |
| Gateway-to-miner latency | 5% | 250 ms / (250 ms + measured round-trip time) |

Completion reliability also multiplies the weighted sum. Client cancellations
are excluded from the reliability denominator. A successful response without
valid decode timing counts toward reliability and stays outside throughput
cohorts. Missing round-trip measurements contribute zero to that component.

Miners are compared within the same model and input/output-length cohort.
Model budgets are allocated across workload cohorts by observed output volume.
Scores determine shares within each cohort. The resulting weight vector uses
deterministic largest-remainder rounding. A window with no eligible
measurements produces an empty vector.

## Measurement definitions

- **Decode TPS** divides output tokens after the first token by the interval
  from the first token to completion. `decode_tps_milli` is thousandths of a
  token per second.
- **Time to first token (TTFT)** measures from gateway admission through the
  first nonempty content or reasoning delta, including queue time.
- **Gateway-to-miner RTT** uses WebSocket Ping/Pong measured at the gateway.
  Reports store it in microseconds.

Reports contain aggregate measurements. Gateway timing is observed at the
gateway, and token counts come from the serving runtime. The report signature
authenticates the published measurements. Independent token and correctness
checks provide separate evidence about execution.
