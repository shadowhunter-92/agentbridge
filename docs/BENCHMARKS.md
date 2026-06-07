# Benchmarks — what AgentBridge actually costs

A fair question for any inline governed proxy: *how much latency does it add?* These are
real measured numbers, reproducible with `tools/benchmark.py`. We measure **only the
overhead AgentBridge adds in-process** — not the network round-trip to the target agent,
which dominates real calls and isn't ours to own.

## Method

- `python tools/benchmark.py`
- Single machine, single thread, Python 3.12, **in-memory** governance store.
- Two paths:
  1. **translate-only** — `registry.translate_call(wire, src, dst)` (the canonical hop).
  2. **governed route (no-op target)** — a full `GovernanceGateway.route_call`: identity
     check → budget reserve → translate → invoke (no-op) → budget commit → audit append.

## Results (indicative)

| Path | p50 | p99 | What it includes |
|------|-----|-----|------------------|
| Translate (any→any canonical hop) | **~5–30 µs** | <~200 µs | Pure protocol translation |
| Full governed + audited call | **~0.4 ms** | **~1.4 ms** | Identity + budget + translate + hash-chained audit |

Numbers vary with machine load (the translate path is tens of microseconds either way).

## What this means

- **Translation is effectively free** — tens of microseconds.
- **Full governance + tamper-evident audit costs sub-millisecond** in-process.
- A real agent tool call over the network is typically **50–500 ms+**. So AgentBridge's
  governance overhead is normally **well under 1%** of end-to-end latency — you're paying
  microseconds-to-a-millisecond for identity, budget enforcement, and a provable audit
  trail.

## Honest caveats

- **Durable stores add I/O.** With SQLite or Postgres, the audit append and budget persist
  do disk/network I/O on top of the compute above. Benchmark those against your own
  hardware before committing to a latency SLA.
- **A real bug this benchmark caught.** The rate-limiter used to rebuild its entire
  recent-calls list on every call (O(n) per call → O(n²) under load). Fixed by switching to
  a deque with left-pop (amortized O(1)); it roughly halved the governed-path p50/p99.
- **One known remaining micro-cost.** Persisting a budget copies its recent-calls window
  (bounded by `rate_limit`); a candidate future optimization, not a bottleneck at normal
  rate limits.
- These are micro-benchmarks of the happy path. Throughput under real concurrency, durable
  stores, and signature verification on every request will differ — measure your scenario.
