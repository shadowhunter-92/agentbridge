"""
Integration test for PostgresStore.

SKIPPED unless AGENTBRIDGE_TEST_PG is set to a *throwaway* Postgres DSN, e.g.:
    AGENTBRIDGE_TEST_PG=postgresql://user:pass@localhost:5432/agentbridge_test

It creates the schema, exercises every interface method, and verifies the same
behaviour SqliteStore guarantees. Run a disposable Postgres first, e.g.:
    docker run --rm -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16
"""

import os
import pytest

PG_DSN = os.getenv("AGENTBRIDGE_TEST_PG")
pytestmark = pytest.mark.skipif(
    not PG_DSN, reason="set AGENTBRIDGE_TEST_PG to a throwaway Postgres DSN to run")


@pytest.fixture()
def store():
    from src.governance.store import PostgresStore
    s = PostgresStore(PG_DSN)
    # clean slate
    with s._lock, s._db.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS identities, budgets, audit")
    s._init_schema()
    yield s
    s.close()


def test_identity_roundtrip_and_revoke(store):
    store.upsert_identity("a1", "deadbeef", revoked=False)
    got = store.get_identity("a1")
    assert got == {"agent_id": "a1", "public_key_hex": "deadbeef", "revoked": False}
    store.upsert_identity("a1", "deadbeef", revoked=True)
    assert store.get_identity("a1")["revoked"] is True
    assert {i["agent_id"] for i in store.list_identities()} == {"a1"}


def test_budget_roundtrip(store):
    store.upsert_budget("a1", {"spent": 1.5, "spend_limit": 10})
    assert store.get_budget("a1") == {"spent": 1.5, "spend_limit": 10}
    assert store.get_budget("missing") is None


def test_audit_is_append_only_and_ordered(store):
    for i in range(3):
        store.append_audit({"seq": i, "decision": "allow", "n": i})
    store.append_audit({"seq": 0, "decision": "tamper"})  # ON CONFLICT DO NOTHING
    rows = store.load_audit()
    assert [r["seq"] for r in rows] == [0, 1, 2]
    assert rows[0]["decision"] == "allow"  # original preserved, not overwritten


def test_make_store_selects_postgres():
    from src.governance.store import make_store, PostgresStore
    s = make_store(PG_DSN)
    assert isinstance(s, PostgresStore)
    s.close()


# --- multi-worker concurrency on REAL Postgres (the pg_advisory_xact_lock path) ---------
# These mirror tests/test_concurrency.py but exercise PostgresStore so the advisory-lock
# atomic ops (append_audit_chained / mutate_budget) are proven on the actual multi-instance
# backend, not just SQLite. Each "worker" gets its OWN PostgresStore connection (== a faithful
# stand-in for a separate replica) all pointing at the same database.
import threading  # noqa: E402


def _reset_schema():
    from src.governance.store import PostgresStore
    s = PostgresStore(PG_DSN)
    with s._lock, s._db.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS identities, budgets, audit")
    s._init_schema()
    s.close()


def _run(workers):
    threads = [threading.Thread(target=w) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_pg_audit_chain_does_not_fork_across_connections():
    from src.governance.store import PostgresStore
    from src.governance.audit import AuditLog
    _reset_schema()
    stores, slock = [], threading.Lock()
    n_workers, per_worker = 6, 20
    barrier = threading.Barrier(n_workers)

    def worker():
        store = PostgresStore(PG_DSN)
        with slock:
            stores.append(store)
        log = AuditLog(store)
        barrier.wait()
        for _ in range(per_worker):
            log.record(actor="a", action="route_call", source_protocol="mcp",
                       target_protocol="a2a", capability="search", decision="allow", cost=1.0)

    try:
        _run([worker] * n_workers)
        verifier = PostgresStore(PG_DSN)
        stores.append(verifier)
        records = verifier.load_audit()
        total = n_workers * per_worker
        assert len(records) == total
        assert sorted(r["seq"] for r in records) == list(range(total)), "chain forked!"
        assert AuditLog.verify_chain(records), "hash chain failed verification (fork!)"
    finally:
        for s in stores:
            s.close()


def test_pg_budget_never_overspends_across_connections():
    from src.governance.store import PostgresStore
    from src.governance.budget import BudgetManager, Budget
    _reset_schema()
    seed = BudgetManager(PostgresStore(PG_DSN))
    seed.set_budget("agent-X", Budget(spend_limit=10.0, rate_limit=10_000))
    stores, slock = [seed.store], threading.Lock()
    committed = []
    clock, clock_lock = [1000.0], threading.Lock()
    n_workers, attempts_each = 5, 10
    barrier = threading.Barrier(n_workers)

    def worker():
        mgr = BudgetManager(PostgresStore(PG_DSN))
        with slock:
            stores.append(mgr.store)
        barrier.wait()
        local = 0
        for _ in range(attempts_each):
            with clock_lock:
                clock[0] += 1
                now = clock[0]
            token, _ = mgr.reserve("agent-X", 1.0, now=now)
            if token is not None and mgr.commit("agent-X", token, now=now):
                local += 1
        committed.append(local)

    try:
        _run([worker] * n_workers)
        final = PostgresStore(PG_DSN)
        stores.append(final)
        state = final.get_budget("agent-X")
        assert state["spent"] <= 10.0, f"OVERSPENT on Postgres: {state['spent']}"
        assert sum(committed) == 10
        assert state["spent"] == 10.0
        assert not state.get("reserved"), "dangling reservations"
    finally:
        for s in stores:
            s.close()
