"""Tenant authority guards compose with durable signing policy coordination."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from examples.qualify_trust_evidence import public, signed_registry
from src.governance.signing_trust_journal import SigningTrustJournal, TrustJournalDenied
from src.governance.store import PostgresStore, sql_atomic
from tests.test_authority import authority as authority
from tests.test_tenant_store import namespaces as namespaces


def journal(store):
    controllers = {domain: Ed25519PrivateKey.generate() for domain in ("destination", "readback")}
    pinned = {domain: public(key) for domain, key in controllers.items()}
    trust = SigningTrustJournal(store, controller_keys=pinned)
    envelopes = {}
    for domain in controllers:
        envelopes[domain] = signed_registry(
            controllers[domain], domain, 1, None,
            [dict(key_id="old", public_key_hex=public(Ed25519PrivateKey.generate()), state="active")],
        )
        trust.publish(envelopes[domain])
    return trust, controllers, pinned, envelopes


@pytest.mark.parametrize("operation", ["publish", "settlement"])
def test_signing_policy_composes_with_current_authority_guard(authority, namespaces, operation):
    directory, owner = authority[:2]
    store = namespaces("alpha")
    trust, controllers, _, envelopes = journal(store)
    if isinstance(store, PostgresStore):
        store._db.execute("SET lock_timeout='500ms'")
    with directory.guard(owner):
        if operation == "publish":
            proposal = signed_registry(controllers["readback"], "readback", 2, envelopes["readback"], envelopes["readback"]["keys"])
            assert trust.publish(proposal)
        else:
            with sql_atomic(store):
                cur = store._db.cursor()
                try:
                    keys = trust.settlement_keys(cur, destination_key_id="old", observer_key_id="old")
                finally:
                    cur.close()
            assert keys["readback_revision"] == keys["destination_revision"] == 1


def test_new_signing_tables_reject_unscoped_legacy_writes(authority, namespaces):
    store = namespaces("alpha")
    trust, _, _, _ = journal(store)
    legacy = namespaces("alpha", legacy=True)
    with pytest.raises(Exception, match="tenant write scope|agentbridge_current_tenant"):
        legacy._db.execute("DELETE FROM signing_trust_revisions")
    with trust._transaction() as cur:
        assert trust.settlement_keys(cur, destination_key_id="old", observer_key_id="old")["readback_revision"] == 1


@pytest.mark.parametrize("damage", ["missing-row", "unknown-version"])
def test_signing_coordination_state_never_silently_resets(authority, namespaces, damage):
    store = namespaces("alpha")
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL coordination row; SQLite uses its transaction writer lock")
    trust, _, pinned, _ = journal(store)
    if damage == "missing-row":
        store._db.execute("DELETE FROM signing_trust_lock_v1")
    else:
        store._db.execute("UPDATE signing_trust_lock_v1 SET version=2")
    with pytest.raises(TrustJournalDenied, match="coordination"):
        SigningTrustJournal(store, controller_keys=pinned)
    with pytest.raises(TrustJournalDenied, match="coordination"):
        with sql_atomic(store):
            with store._db.cursor() as cur:
                trust.settlement_keys(cur, destination_key_id="old", observer_key_id="old")


@pytest.mark.parametrize("barrier", ["legacy-exclusive", "new-settlement"])
def test_rotation_respects_old_worker_and_current_settlement_barriers(authority, namespaces, barrier):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import nullcontext

    store = namespaces("alpha")
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL cross-connection lock compatibility")
    trust, controllers, pinned, envelopes = journal(store)
    other = namespaces("alpha")
    second = SigningTrustJournal(other, controller_keys=pinned)
    proposal = signed_registry(controllers["readback"], "readback", 2, envelopes["readback"], envelopes["readback"]["keys"])
    directory, owner = authority[:2]
    guard = nullcontext() if barrier == "legacy-exclusive" else directory.guard(owner)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = None
        try:
            with guard, sql_atomic(store):
                with store._db.cursor() as cur:
                    if barrier == "legacy-exclusive":
                        cur.execute("SELECT pg_advisory_xact_lock(%s)", (SigningTrustJournal._LOCK,))
                    else:
                        trust.settlement_keys(cur, destination_key_id="old", observer_key_id="old")
                    future = pool.submit(second.publish, proposal)
                    deadline = time.monotonic() + 10
                    while True:
                        row = cur.execute(
                            "SELECT %s=ANY(pg_blocking_pids(%s)) AS blocked",
                            (store._db.info.backend_pid, other._db.info.backend_pid),
                        ).fetchone()
                        if row["blocked"]:
                            break
                        if future.done():
                            future.result()
                            pytest.fail("rotation bypassed the held policy barrier")
                        assert time.monotonic() < deadline, "expected database blocking edge not observed"
                        time.sleep(.02)
        finally:
            # Release the SQL blocker before waiting for the publisher thread.
            if future is not None:
                assert future.result(timeout=20)
    with trust._transaction(write=False) as cur:
        assert trust.settlement_keys(cur, destination_key_id="old", observer_key_id="old")["readback_revision"] == 2


def test_signing_policy_rejects_autocommit_cursor(authority, namespaces):
    store = namespaces("alpha")
    trust, _, _, _ = journal(store)
    cur = store._db.cursor()
    try:
        with pytest.raises(TrustJournalDenied, match="active transaction"):
            trust.settlement_keys(cur, destination_key_id="old", observer_key_id="old")
    finally:
        cur.close()


def test_signing_policy_rejects_another_connection_cursor(authority, namespaces):
    store = namespaces("alpha")
    trust, _, _, _ = journal(store)
    other = namespaces("alpha")
    with sql_atomic(other):
        cur = other._db.cursor()
        try:
            with pytest.raises(TrustJournalDenied, match="own store"):
                trust.settlement_keys(cur, destination_key_id="old", observer_key_id="old")
        finally:
            cur.close()
