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
