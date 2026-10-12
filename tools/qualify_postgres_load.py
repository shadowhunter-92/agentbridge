"""Bounded multi-batch PostgreSQL load qualification, not a production SLO.

Requires disposable AGENTBRIDGE_TEST_PG. Measures real SQL, audit and budget
accounting over consecutive independent batches, plus process resource usage.
Targets are intentionally synthetic; remote destinations and HA are not tested.
"""
import argparse
import json
import os
import resource
import time

from tools.benchmark_postgres_governance import benchmark


def qualify(dsn, *, batches=3, count=250, workers=8,
            max_p99_ms=10000.0, max_rss_mb=700.0, min_throughput=1.0):
    if not dsn or not 2 <= batches <= 10:
        raise ValueError("disposable PostgreSQL DSN and at least two batches required")
    collected=[]
    start=time.monotonic()
    for i in range(batches):
        sample=benchmark(dsn,count=count,workers=workers)
        collected.append(sample)
    elapsed=time.monotonic()-start
    rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Runner is Linux; ru_maxrss is KiB there.
    rss_mb=round(rss_kib/1024,2)
    worst_p99=max(x["p99_ms"] for x in collected)
    minimum_throughput=min(x["throughput_ops_s"] for x in collected)
    accepted=(worst_p99<=max_p99_ms and rss_mb<=max_rss_mb
              and minimum_throughput>=min_throughput)
    return {
        "kind":"disposable-postgres-multibatch-sql-governance",
        "batches":batches,"operations_per_batch":count,"workers":workers,
        "total_operations":batches*count,"wall_seconds":round(elapsed,3),
        "worst_p99_ms":worst_p99,"peak_process_rss_mb":rss_mb,
        "minimum_throughput_ops_s":minimum_throughput,
        "smoke_thresholds":{"max_p99_ms":max_p99_ms,
                            "max_peak_rss_mb":max_rss_mb,
                            "min_throughput_ops_s":min_throughput},
        "passed_smoke_thresholds":accepted,
        "observations":collected,
        "limitations":"CI single-node database, synthetic target and short multibatch run; not production SLO",
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--batches",type=int,default=3)
    ap.add_argument("--count",type=int,default=250)
    ap.add_argument("--workers",type=int,default=8)
    args=ap.parse_args()
    dsn=os.getenv("AGENTBRIDGE_TEST_PG")
    if not dsn:
        ap.error("AGENTBRIDGE_TEST_PG disposable database required")
    report=qualify(dsn,batches=args.batches,count=args.count,workers=args.workers)
    print(json.dumps(report,sort_keys=True,indent=2))
    if not report["passed_smoke_thresholds"]:
        raise SystemExit("disposable SQL smoke-resource/latency thresholds exceeded")


if __name__=="__main__":
    main()
