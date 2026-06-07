"""
Measure AgentBridge's own in-process overhead — honestly.

Reviewers reasonably ask "how much latency does an inline governed proxy add?".
This measures the parts AgentBridge actually adds (it does NOT include the network
round-trip to the target agent, which dominates real calls and is not ours to own):

  1. translate-only : registry.translate_call(wire, src, dst)  (canonical hop)
  2. governed-noop   : gateway.route_call(...) with a no-op target
                       (identity check + budget reserve/commit + translate + audit append)

Run: .venv/Scripts/python tools/benchmark.py
"""

import asyncio
import statistics
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.protocols import default_registry as reg
from src.protocols.canonical import CanonicalCall
from src.governance import (AgentIdentity, IdentityRegistry, BudgetManager, Budget,
                            GovernanceGateway)

N_TRANSLATE = 50_000
N_GOVERNED = 20_000


def pct(values, p):
    return statistics.quantiles(values, n=100)[p - 1]


def summarize(name, samples_s):
    us = [s * 1_000_000 for s in samples_s]  # seconds -> microseconds
    print(f"  {name:<26} n={len(us):>6}  "
          f"mean={statistics.mean(us):7.1f}us  "
          f"p50={pct(us,50):7.1f}us  p99={pct(us,99):7.1f}us")


def bench_translate():
    wire = reg.get("openai").from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
    samples = []
    for _ in range(N_TRANSLATE):
        t0 = time.perf_counter()
        reg.translate_call(wire, "openai", "mcp")
        samples.append(time.perf_counter() - t0)
    summarize("translate openai->mcp", samples)


async def bench_governed():
    ids = IdentityRegistry()
    ids.register(AgentIdentity.generate("bench-agent"))
    buds = BudgetManager()
    # Realistic steady state: a bounded rate window so the recent-calls working set
    # stays small (as it would in production), rather than growing unbounded.
    buds.set_budget("bench-agent", Budget(spend_limit=float("inf"), rate_limit=10**9,
                                          window_seconds=1))
    gw = GovernanceGateway(identities=ids, budgets=buds)

    async def noop_invoke(_dst_wire):
        return {"raw": ["5"]}

    wire = reg.get("openai").from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
    samples = []
    for _ in range(N_GOVERNED):
        t0 = time.perf_counter()
        await gw.route_call(agent_id="bench-agent", src_proto="openai", dst_proto="mcp",
                            src_wire=wire, invoke=noop_invoke, cost=1.0)
        samples.append(time.perf_counter() - t0)
    summarize("governed route (no-op tgt)", samples)
    print(f"\n  (audit entries written: {len(gw.audit.entries())}, "
          f"integrity_ok={gw.audit.verify_integrity()})")


def main():
    print("\nAgentBridge in-process overhead (excludes the target agent's network call)\n")
    print(f"  Python {sys.version.split()[0]}  |  in-memory governance store\n")
    bench_translate()
    asyncio.run(bench_governed())
    print("\n  Note: durable stores (SQLite/Postgres) add disk/network I/O to the audit")
    print("  append; numbers above isolate AgentBridge's compute overhead.\n")


if __name__ == "__main__":
    main()
