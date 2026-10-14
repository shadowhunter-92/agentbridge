"""Concurrency/load observation using isolated SQLite and mock target.

This benchmarks governance route, budget reservation, operation ledger and audit
persistence. It is NOT a test of distributed PostgreSQL or real external agents.
"""
import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.governance.store import SqliteStore
from src.governance.identity import IdentityRegistry,AgentIdentity
from src.governance.budget import BudgetManager,Budget
from src.governance.audit import AuditLog
from src.governance.gateway import GovernanceGateway
from src.protocols.canonical import CanonicalCall


def run_load(count=100, workers=4):
    if not 1<=count<=10000 or not 1<=workers<=32:
        raise ValueError("invalid staging load parameters")
    with tempfile.TemporaryDirectory() as d:
        path=str(Path(d)/"load.db")
        seed=SqliteStore(path)
        ids=IdentityRegistry(seed)
        ids.register(AgentIdentity.generate("synthetic-agent"))
        budgets=BudgetManager(seed)
        budgets.set_budget("synthetic-agent",Budget(spend_limit=count+1,rate_limit=count+1))
        seed.close()
        def one(i):
            start=time.perf_counter_ns()
            store=SqliteStore(path)
            try:
                gateway=GovernanceGateway(
                    identities=IdentityRegistry(store),budgets=BudgetManager(store),
                    audit=AuditLog(store))
                wire=gateway.registry.get("openai").from_canonical_call(
                    CanonicalCall("read",{"id":i}))
                async def safe_mock(_):
                    return {"ok":True}
                answer=asyncio.run(gateway.route_call(
                    agent_id="synthetic-agent",src_proto="openai",
                    dst_proto="mcp",src_wire=wire,invoke=safe_mock,
                    operation_id=f"staging-load-{i:016d}",cost=1))
                assert answer["ok"]
                return (time.perf_counter_ns()-start)/1e6
            finally:
                store.close()
        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            latencies=list(executor.map(one,range(count)))
        elapsed=time.perf_counter()-started
        verify=SqliteStore(path)
        try:
            assert AuditLog(verify).verify_integrity(), "audit fork under load"
            assert verify.get_budget("synthetic-agent")["spent"]==count
        finally:
            verify.close()
        ordered=sorted(latencies)
        at=lambda q:round(ordered[min(len(ordered)-1,int((len(ordered)-1)*q))],4)
        return {"kind":"synthetic-multi-connection-sqlite-governance",
                "requests":count,"workers":workers,
                "total_seconds":round(elapsed,4),
                "throughput_ops_s":round(count/elapsed,3),
                "p50_ms":at(.50),"p95_ms":at(.95),"p99_ms":at(.99)}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--count",type=int,default=100)
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    print(json.dumps(run_load(args.count,args.workers),indent=2,sort_keys=True))
