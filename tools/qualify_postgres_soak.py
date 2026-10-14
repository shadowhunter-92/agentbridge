"""Bounded disposable PostgreSQL SQL-governance soak and resource gate.

This is a sustained CI SQL workload, not an end-to-end remote action SLO.
Does not dispatch to customer systems. Caps runtime and refuses missing DB.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import resource
import time

from tools.benchmark_postgres_governance import benchmark


def soak(dsn: str, *, duration_seconds: int=90, count: int=250, workers: int=8,
         max_p99_ms: float=10000, max_rss_mb: float=700,
         min_throughput_ops_s: float=1):
    if (not isinstance(dsn,str) or "agentbridge_test" not in dsn
            or not 30 <= duration_seconds <= 900
            or not 10 <= count <= 1000 or not 1 <= workers <= 32):
        raise ValueError("bounded disposable PostgreSQL test configuration required")
    beginning=time.monotonic()
    starting_cpu=resource.getrusage(resource.RUSAGE_SELF)
    rows=[]
    total_ops=0
    while time.monotonic()-beginning < duration_seconds:
        sample=benchmark(dsn,count=count,workers=workers)
        if sample["count"]!=count or sample["workers"]!=workers:
            raise AssertionError("benchmark silently dropped operations")
        total_ops+=count
        rows.append(sample)
        if len(rows)>20000:
            raise AssertionError("unexpected unbounded soak sample cardinality")
    elapsed=time.monotonic()-beginning
    usage=resource.getrusage(resource.RUSAGE_SELF)
    p99=max(x["p99_ms"] for x in rows)
    throughput=total_ops/elapsed
    rss=usage.ru_maxrss/1024  # Linux runner ru_maxrss is KiB
    cpu=(usage.ru_utime-starting_cpu.ru_utime+
         usage.ru_stime-starting_cpu.ru_stime)
    ok=(math.isfinite(p99) and p99<=max_p99_ms
        and rss<=max_rss_mb and throughput>=min_throughput_ops_s)
    return {
        "kind":"disposable-postgres-sustained-sql-governance",
        "elapsed_seconds":round(elapsed,2),"samples":len(rows),
        "total_operations":total_ops,"workers":workers,
        "worst_sample_p99_ms":round(p99,2),
        "throughput_ops_per_second":round(throughput,2),
        "peak_process_rss_mb":round(rss,2),
        "process_cpu_seconds":round(cpu,2),
        "accepted":ok,
        "thresholds":{"max_sample_p99_ms":max_p99_ms,
                      "max_process_rss_mb":max_rss_mb,
                      "min_throughput_ops_per_second":min_throughput_ops_s},
        "limitations":"Disposable single-node SQL-only workload, no external target, production failure mix, CPU/container quotas or SLO contract",
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--duration",type=int,default=90)
    parser.add_argument("--workers",type=int,default=8)
    parser.add_argument("--count",type=int,default=250)
    args=parser.parse_args()
    if os.getenv("AGENTBRIDGE_SUSTAINED_CI_SOAK")!="1":
        parser.error("explicit disposable soak opt-in required")
    report=soak(os.environ.get("AGENTBRIDGE_TEST_PG",""),
                duration_seconds=args.duration,workers=args.workers,count=args.count)
    print(json.dumps(report,indent=2,sort_keys=True))
    if not report["accepted"]:
        raise SystemExit("SQL soak breached a stated disposable smoke threshold")


if __name__=="__main__":
    main()
