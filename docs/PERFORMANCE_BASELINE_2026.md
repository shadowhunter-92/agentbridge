# Performance baseline — isolated GitHub CI, October 11, 2026

**Source:** GitHub Actions run 38137390625; Python 3.12 job; source commit `735e92479427bc12a8b9f04d2454b7a7ec1a6776`.
**Scope:** Synthetic code-path observation, **NOT** real customer load, an enterprise SLA, or a production throughput guarantee. Individual job measurements are variable on shared runners.

## In-process translation, 1,000 calls, four threads

| Metric | Measured |
|---|---:|
| p50 | 0.0073 ms |
| p95 | 0.0096 ms |
| p99 | 0.0325 ms |
| Maximum | 3.1322 ms |
| Throughput | 47,082.08 operations/sec |

Only translates an inert OpenAI-shaped read tool call into MCP-shaped wire. No HTTP, authentication, target network, persistence, database failover or remote agent.

## Concurrent governed SQLite route, 50 calls, four threads/connections

| Metric | Measured |
|---|---:|
| p50 | 3.5345 ms |
| p95 | 42.2469 ms |
| p99 | 182.9522 ms |
| Throughput | 224.774 operations/sec |
| Wall time | 0.2224 sec |

This test invokes mock targets and real SQLite budget, operation and audit operations. It verifies no audit-chain fork and settled budget count. Network authentication, production PostgreSQL, remote targets, long-tail saturation, and fault chaos are excluded.

**Interpretation:** the multi-connection governance path is much slower and has a wide tail, as expected with serialized SQLite writes. This one small sample is not sufficient to establish scaling capacity or production SLOs. A dedicated PostgreSQL service/load environment and representative external target workloads are the next required performance evidence. Do not extrapolate throughput linearly to global infrastructure.

## Required performance-gate methodology before deployment

1. Use dedicated repeatable staging hardware, image digest, release commit, precise client concurrency, budget/approval/target mix and independent tester.
2. Measure p50/p95/p99/max, throughput, error/timeout rate, CPU/memory, DB lock waits, client-visible latencies, queue age, unknown outcomes, and recovery times.
3. Test 1, 8, 32, 128 concurrent clients and 30/60-minute sustained operation plus burst/failover cases; adjust concurrency to expected pilots.
4. Establish **customer-derived** SLO limits and reject a release when measured p95/p99 or error rate breach them. No invented latency SLO is claimed here.
5. Compare verified Postgres numbers against these synthetic measurements only when clearly labeled non-comparable workloads.
