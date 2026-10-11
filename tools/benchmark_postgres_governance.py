"""Disposable PostgreSQL governance concurrency benchmark (not a production SLO).

Uses real PostgreSQL transactions with multiple independent client connections,
but a simulated target. Does not make remote-agent latency claims.
"""
import argparse
import asyncio
import json
import os
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.governance.audit import AuditLog
from src.governance.budget import Budget, BudgetManager
from src.governance.gateway import GovernanceGateway
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.store import PostgresStore
from src.protocols.canonical import CanonicalCall

_local = threading.local()


def benchmark(dsn: str, count: int = 100, workers: int = 4):
    if not dsn or not 1 <= count <= 10000 or not 1 <= workers <= 32:
        raise ValueError("disposable PostgreSQL DSN and bounded load parameters required")
    agent = "pg-load-" + uuid.uuid4().hex
    seed = PostgresStore(dsn)
    try:
        IdentityRegistry(seed).register(AgentIdentity.generate(agent))
        BudgetManager(seed).set_budget(agent, Budget(spend_limit=count + 1, rate_limit=count + 1))
    finally:
        seed.close()

    stores = []
    lock = threading.Lock()

    def one(index):
        if not hasattr(_local, "gateway"):
            store = PostgresStore(dsn)
            with lock:
                stores.append(store)
            _local.gateway = GovernanceGateway(
                identities=IdentityRegistry(store),
                budgets=BudgetManager(store),
                audit=AuditLog(store))
        gateway = _local.gateway
        src_wire = gateway.registry.get("openai").from_canonical_call(
            CanonicalCall("read", {"id": index}))

        async def inert_target(_wire):
            return {"ok": True}

        started = time.perf_counter_ns()
        result = asyncio.run(gateway.route_call(
            agent_id=agent, src_proto="openai", dst_proto="mcp",
            src_wire=src_wire, invoke=inert_target,
            operation_id=f"pg-load-{index:016d}", cost=1))
        assert result["ok"]
        return (time.perf_counter_ns() - started) / 1e6

    start = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            samples = list(pool.map(one, range(count)))
    finally:
        for store in stores:
            store.close()

    verifier = PostgresStore(dsn)
    try:
        budget = verifier.get_budget(agent)
        assert budget is not None and budget["spent"] == count, "budget accounting mismatch"
        assert not budget.get("reserved"), "orphaned budget reservations"
        matching = [record for record in verifier.load_audit()
                    if record.get("actor") == agent and record.get("action") == "route_call"]
        assert len(matching) == count, "missing audit events"
    finally:
        verifier.close()

    ordered = sorted(samples)
    at = lambda quantile: round(ordered[int((len(ordered) - 1) * quantile)], 4)
    elapsed = time.perf_counter() - start
    return {"kind": "disposable-postgres-real-sql-synthetic-target",
            "count": count, "workers": workers,
            "p50_ms": at(0.50), "p95_ms": at(0.95), "p99_ms": at(0.99),
            "throughput_ops_s": round(count / elapsed, 3),
            "total_seconds": round(elapsed, 3),
            "limitations": "Mock target; local CI PostgreSQL, not remote HA or production"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    dsn = os.getenv("AGENTBRIDGE_TEST_PG")
    if not dsn:
        parser.error("AGENTBRIDGE_TEST_PG must point to a disposable PostgreSQL database")
    print(json.dumps(benchmark(dsn, args.count, args.workers), sort_keys=True, indent=2))
