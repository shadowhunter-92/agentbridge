"""Bounded synthetic Trust/Evidence full-path timings, not production SLOs.

Usage: python -m tools.benchmark_trust_evidence --count 20
Every iteration includes authorization, destination write, lost ACK, readback,
signature verification, reconciliation and audit-chain checkpoint.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from examples.trust_evidence_end_to_end import run_synthetic_flow


def measure(count: int) -> dict:
    if type(count) is not int or count < 1 or count > 200:
        raise ValueError("synthetic benchmark must use 1..200 bounded runs")
    elapsed = []
    failures = 0
    for index in range(count):
        with tempfile.TemporaryDirectory(prefix="agentbridge-performance-") as root:
            started = time.perf_counter()
            try:
                report = run_synthetic_flow(Path(root))
                if report["reconciled_state"] != "succeeded":
                    raise RuntimeError("synthetic evidence did not reconcile")
            except Exception:
                failures += 1
                raise
            finally:
                elapsed.append((time.perf_counter() - started) * 1000)
    ordered = sorted(elapsed)
    def percentile(p):
        return round(ordered[max(0, min(len(ordered) - 1, int((p / 100) * (len(ordered) - 1))))], 2)
    return {
        "scope": "single-process disposable SQLite, synthetic, not a production SLO",
        "iterations": count,
        "failures": failures,
        "p50_ms": percentile(50),
        "p95_ms": percentile(95),
        "p99_ms": percentile(99),
        "max_ms": round(max(elapsed), 2),
        "avg_ms": round(statistics.mean(elapsed), 2),
        "includes": ["approval", "durable_claim", "fenced_destination", "lost_ack",
                     "signed_readback", "reconciliation", "audit_checkpoint"],
        "not_measured": ["external_network", "multi_tenant", "mTLS", "load_shedding",
                         "production_resource_utilization", "real_failover"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(measure(args.count), indent=2, sort_keys=True))
