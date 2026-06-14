"""
Multi-worker concurrency harness — proves the two "enterprise-killer" bugs are FIXED.

Background (the bugs an external staff-engineer review found):
  1. AUDIT-CHAIN FORK: with per-process in-memory state, two workers read the same
     `prev_hash` and append concurrently -> two entries claim the same seq / chain off the
     same parent -> `verify_chain()` fails (tamper-evidence silently broken).
  2. BUDGET DOUBLE-SPEND: two workers both pass `can_afford()` on their own in-memory copy
     of the budget and both reserve -> the spend cap is overrun.

How we simulate "multiple workers" in one test process: each worker gets its OWN store
object pointing at the SAME shared SQLite file. Separate store objects == separate
connections + separate in-process locks == a faithful stand-in for separate OS processes.
The only thing they share is the durable DB — exactly the production multi-worker topology.

The fix under test: store.append_audit_chained() and store.mutate_budget() do the
read-modify-write inside an atomic DB transaction (SQLite BEGIN IMMEDIATE / Postgres
advisory lock), so the chain head and the budget ledger are serialized across workers.
"""

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.governance.store import SqliteStore, InMemoryStore  # noqa: E402
from src.governance.audit import AuditLog                     # noqa: E402
from src.governance.budget import BudgetManager, Budget       # noqa: E402


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _cleanup(path, stores):
    # Close every connection so Windows releases the file lock, then remove the db
    # plus the WAL side files. Best-effort — never fail a passing test on cleanup.
    for s in stores:
        try:
            s.close()
        except Exception:
            pass
    for p in (path, path + "-wal", path + "-shm"):
        try:
            os.remove(p)
        except OSError:
            pass


def _run(workers):
    threads = [threading.Thread(target=w) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# --------------------------------------------------------------------------------------
# BUG 1 — audit-chain fork
# --------------------------------------------------------------------------------------
def test_shared_audit_chain_does_not_fork_across_workers():
    """Many 'workers' (separate stores, same DB file) append concurrently; the durable
    chain must still be a single intact, gap-free hash chain."""
    path = _tmp_db()
    stores = []
    slock = threading.Lock()
    try:
        n_workers, per_worker = 8, 25
        barrier = threading.Barrier(n_workers)

        def worker():
            store = SqliteStore(path)              # this worker's own connection
            with slock:
                stores.append(store)
            log = AuditLog(store)
            barrier.wait()                          # maximize contention
            for i in range(per_worker):
                log.record(actor=f"a{i}", action="route_call",
                           source_protocol="mcp", target_protocol="a2a",
                           capability="search", decision="allow", cost=1.0)

        _run([worker] * n_workers)

        verifier = AuditLog(SqliteStore(path))
        stores.append(verifier.store)
        records = verifier.store.load_audit()
        total = n_workers * per_worker

        assert len(records) == total, f"lost/duplicated entries: {len(records)} != {total}"
        seqs = sorted(r["seq"] for r in records)
        assert seqs == list(range(total)), "seqs are not a contiguous 0..N-1 range (fork!)"
        assert verifier.verify_chain(records), "hash chain failed verification (fork!)"
    finally:
        _cleanup(path, stores)


def test_inmemory_per_worker_would_fork_proving_the_harness_detects_it():
    """Sanity check that the harness actually CATCHES a fork: give each worker its own
    InMemoryStore (the old broken topology) and confirm the merged chain is detected as
    forked. This guards against the test passing for the wrong reason."""
    n_workers, per_worker = 4, 10
    merged = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_workers)

    def worker():
        log = AuditLog(InMemoryStore())            # NOT shared -> each starts at GENESIS
        barrier.wait()
        for _ in range(per_worker):
            log.record(actor="a", action="route_call", source_protocol="mcp",
                       target_protocol="a2a", capability="search", decision="allow")
        with lock:
            merged.extend(log.store.load_audit())

    _run([worker] * n_workers)
    # Each worker independently produced seq 0..per_worker-1 -> duplicate seqs -> not a chain.
    assert not AuditLog.verify_chain(merged), "expected a fork from per-worker in-memory state"


# --------------------------------------------------------------------------------------
# BUG 2 — budget double-spend
# --------------------------------------------------------------------------------------
def test_shared_budget_never_overspends_across_workers():
    """50 concurrent reserve+commit attempts across 5 'workers' (separate managers, same DB
    file) against a cap of 10 -> at most 10 commit, and durable spent never exceeds the cap."""
    path = _tmp_db()
    stores = []
    slock = threading.Lock()
    try:
        # Seed the budget once in the shared store.
        seed = BudgetManager(SqliteStore(path))
        stores.append(seed.store)
        seed.set_budget("agent-X", Budget(spend_limit=10.0, rate_limit=10_000))

        n_workers, attempts_each = 5, 10
        committed = []
        clock = [1000.0]
        clock_lock = threading.Lock()
        barrier = threading.Barrier(n_workers)

        def worker():
            mgr = BudgetManager(SqliteStore(path))   # this worker's own connection
            with slock:
                stores.append(mgr.store)
            barrier.wait()
            local = 0
            for _ in range(attempts_each):
                with clock_lock:
                    clock[0] += 1
                    now = clock[0]
                token, _why = mgr.reserve("agent-X", 1.0, now=now)
                if token is not None and mgr.commit("agent-X", token, now=now):
                    local += 1
            committed.append(local)

        _run([worker] * n_workers)

        final = BudgetManager(SqliteStore(path))
        stores.append(final.store)
        state = final.store.get_budget("agent-X")
        assert state["spent"] <= 10.0, f"OVERSPENT: durable spent={state['spent']} > 10"
        assert sum(committed) == 10, f"expected exactly 10 commits, got {sum(committed)}"
        assert state["spent"] == 10.0
        assert not state.get("reserved"), "dangling reservations after commit"
    finally:
        _cleanup(path, stores)


def test_shared_budget_reservations_block_overcommit_then_release_frees():
    """Reservations held in the durable store (not in one process's memory) must count
    against the cap for every worker, and releasing must return capacity globally."""
    path = _tmp_db()
    stores = []
    try:
        seed = BudgetManager(SqliteStore(path))
        seed.set_budget("agent-Y", Budget(spend_limit=2.0, rate_limit=10_000))

        w1 = BudgetManager(SqliteStore(path))
        w2 = BudgetManager(SqliteStore(path))
        stores.extend([seed.store, w1.store, w2.store])

        t1, _ = w1.reserve("agent-Y", 1.0)
        t2, _ = w2.reserve("agent-Y", 1.0)          # second worker sees w1's reservation
        assert t1 and t2
        # Cap is full across workers even though neither has committed yet.
        assert w1.reserve("agent-Y", 1.0)[0] is None
        assert w2.reserve("agent-Y", 1.0)[0] is None
        # Releasing on one worker frees capacity visible to the other.
        w1.release("agent-Y", t1)
        assert w2.reserve("agent-Y", 1.0)[0] is not None
    finally:
        _cleanup(path, stores)
