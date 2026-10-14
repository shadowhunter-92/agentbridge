"""Reproducible SYNTHETIC translation benchmark, not a production load test.

Usage: python tools/benchmark_synthetic.py --count 3000 --workers 8
Only uses in-process translation of inert structured arguments.
"""
import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.protocols import default_registry
from src.protocols.canonical import CanonicalCall


def _percentile(samples, fraction):
    ordered=sorted(samples)
    index=min(len(ordered)-1, max(0,int((len(ordered)-1)*fraction)))
    return ordered[index]


def benchmark(count=1000, workers=4):
    if count <= 0 or workers <= 0:
        raise ValueError("count and workers must be positive")
    wire=default_registry.get("openai").from_canonical_call(
        CanonicalCall("read", {"resource":"staging-demo-only","id":1}))
    def call(_):
        started=time.perf_counter_ns()
        default_registry.translate_call(wire,"openai","mcp")
        return (time.perf_counter_ns()-started)/1_000_000
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        latencies=list(pool.map(call, range(count)))
    elapsed=time.perf_counter()-started
    return {"kind":"synthetic-local-translation-only","count":count,
            "workers":workers,"throughput_ops_per_sec":round(count/elapsed,2),
            "p50_ms":round(_percentile(latencies,.50),4),
            "p95_ms":round(_percentile(latencies,.95),4),
            "p99_ms":round(_percentile(latencies,.99),4),
            "max_ms":round(max(latencies),4)}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--count",type=int,default=1000)
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    print(json.dumps(benchmark(args.count,args.workers),sort_keys=True,indent=2))
