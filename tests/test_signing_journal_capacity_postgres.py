"""Actual PostgreSQL capacity, writer ordering and durable schema qualification."""

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from examples.qualify_trust_evidence import public, signed_registry
from src.governance.audit_trust import AuditTrustStore
from src.governance.budget import Budget, BudgetManager
from src.governance.operation_ledger import OperationLedger
from src.governance.signing_journal_capacity import (
    TABLE,
    SigningJournalCapacityDenied,
    lock_postgres_writer,
    verify_if_installed,
)
from src.governance.signing_trust_journal import SigningTrustJournal, TrustJournalDenied
from src.governance.store import PostgresStore, sql_atomic


@pytest.fixture
def pg_journal():
    dsn = os.getenv("AGENTBRIDGE_TEST_PG")
    if not dsn:
        pytest.skip("explicit disposable PostgreSQL required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "ab_signcap_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        store = PostgresStore(make_conninfo(dsn, options="-csearch_path=" + schema))
        controllers = {domain: Ed25519PrivateKey.generate() for domain in ("destination", "readback")}
        pinned = {domain: public(key) for domain, key in controllers.items()}
        trust = SigningTrustJournal(store, controller_keys=pinned)
        keys = [dict(key_id="old", public_key_hex=public(Ed25519PrivateKey.generate()), state="active")]

        def proposal(domain="readback", previous=None, entries=None):
            return signed_registry(controllers[domain], domain, 1 if previous is None else previous["revision"] + 1,
                                   previous, keys if entries is None else entries)

        try:
            yield store, trust, proposal, pinned, schema
        finally:
            store.close()
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def reopen(store):
    from psycopg.conninfo import make_conninfo

    return PostgresStore(make_conninfo(os.environ["AGENTBRIDGE_TEST_PG"], options=store._db.info.options))


def rows(store):
    return [dict(row) for row in store._db.execute("SELECT * FROM signing_trust_revisions ORDER BY domain,revision")]


def encoded(envelope):
    return json.dumps(envelope, sort_keys=True)


def size(envelope):
    return len(encoded(envelope).encode("utf-8"))


def test_postgres_lazy_policy_namespace_count_restart_shrink_and_idempotency(pg_journal):
    store, trust, proposal, pinned, _ = pg_journal
    assert store._db.execute("SELECT count(*) AS n FROM " + TABLE).fetchone()["n"] == 0
    assert store._db.execute("SELECT count(*) AS n FROM signing_trust_lock_v1").fetchone()["n"] == 1
    trust.set_capacity(max_records=2, max_bytes=10000, max_entry_bytes=10000)
    heads = {domain: proposal(domain) for domain in ("destination", "readback")}
    for head in heads.values():
        trust.publish(head)
    before, floors = rows(store), dict(trust._floors)
    with pytest.raises(TrustJournalDenied, match="capacity"):
        trust.publish(proposal(previous=heads["readback"]))
    assert rows(store) == before and trust._floors == floors
    trust.set_capacity(max_records=1, max_bytes=1, max_entry_bytes=1)
    again = SigningTrustJournal(store, controller_keys=pinned, minimum_revisions=floors)
    for head in heads.values():
        assert again.publish(head)
    assert again.capacity()["used_bytes"] == sum(size(head) for head in heads.values())
    assert rows(store) == before


@pytest.mark.parametrize("boundary", ["entry", "aggregate"])
def test_postgres_exact_unicode_entry_and_aggregate_bounds(pg_journal, boundary):
    store, trust, proposal, _, _ = pg_journal
    entries = [dict(key_id=chr(0x10000 + n) * 128, public_key_hex=public(Ed25519PrivateKey.generate()), state="active")
               for n in range(128)]
    first = proposal("destination", entries=entries)
    second = proposal("readback", entries=entries)
    total = size(first) + size(second)
    if boundary == "entry":
        trust.set_capacity(max_records=10, max_bytes=total, max_entry_bytes=size(first) - 1)
        with pytest.raises(TrustJournalDenied, match="capacity"):
            trust.publish(first)
        assert rows(store) == []
    trust.set_capacity(max_records=10, max_bytes=total, max_entry_bytes=size(first))
    trust.publish(first)
    trust.publish(second)
    assert trust.capacity()["used_bytes"] == total
    with pytest.raises(TrustJournalDenied, match="capacity"):
        trust.publish(proposal("readback", second, entries))
    assert len(rows(store)) == 2


def test_postgres_old_sql_writer_actual_utf8_and_atomic_multirow(pg_journal):
    import psycopg

    store, trust, proposal, _, _ = pg_journal
    entry = dict(key_id="\U00010000" * 128, public_key_hex=public(Ed25519PrivateKey.generate()), state="active")
    envelope = proposal(entries=[entry])
    literal = json.dumps(envelope, sort_keys=True, ensure_ascii=False)
    actual = len(literal.encode("utf-8"))
    assert actual > len(literal)
    trust.set_capacity(max_records=1, max_bytes=actual, max_entry_bytes=actual)
    older = reopen(store)
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="capacity"):
            older._db.execute("INSERT INTO signing_trust_revisions VALUES(%s,%s,%s),(%s,%s,%s)",
                              ("readback", 1, literal, "destination", 1, literal))
        assert rows(store) == []
        older._db.execute("INSERT INTO signing_trust_revisions VALUES(%s,%s,%s)", ("readback", 1, literal))
        assert trust.capacity()["used_bytes"] == actual
        assert trust.publish(envelope)
    finally:
        older.close()


def wait_blocked(observer, blocker, blocked):
    deadline = time.monotonic() + 10
    while not observer.execute("SELECT %s=ANY(pg_blocking_pids(%s)) AS blocked", (blocker, blocked)).fetchone()["blocked"]:
        assert time.monotonic() < deadline, "expected signing row blocking edge was not observed"
        time.sleep(.01)


def test_postgres_direct_writer_fences_before_unique_ownership(pg_journal):
    import psycopg

    store, trust, proposal, _, _ = pg_journal
    trust.set_capacity(max_records=1, max_bytes=10000, max_entry_bytes=10000)
    other = reopen(store)
    candidate = proposal()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with store._db.transaction():
                with store._db.cursor() as cur:
                    lock_postgres_writer(cur)
                    future = pool.submit(other._db.execute, "INSERT INTO signing_trust_revisions VALUES(%s,%s,%s)",
                                         ("readback", 1, encoded(candidate)))
                    try:
                        wait_blocked(cur, store._db.info.backend_pid, other._db.info.backend_pid)
                        cur.execute("SET LOCAL lock_timeout='1000ms'")
                        # If the waiter had already owned the same unique key,
                        # this insert would time out/deadlock behind that waiter.
                        cur.execute("INSERT INTO signing_trust_revisions VALUES(%s,%s,%s)", ("readback", 1, encoded(candidate)))
                    except BaseException:
                        store._db.cancel()
                        other._db.cancel()
                        raise
            with pytest.raises(psycopg.errors.UniqueViolation):
                future.result(timeout=10)
        assert trust.capacity()["used_records"] == 1
    finally:
        other.close()


def test_postgres_direct_rc_writers_cannot_overrun_count_after_wait(pg_journal):
    import psycopg

    store, trust, proposal, _, _ = pg_journal
    trust.set_capacity(max_records=1, max_bytes=10000, max_entry_bytes=10000)
    other = reopen(store)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with store._db.transaction():
                store._db.execute("INSERT INTO signing_trust_revisions VALUES(%s,%s,%s)", ("readback", 1, encoded(proposal())))
                future = pool.submit(other._db.execute, "INSERT INTO signing_trust_revisions VALUES(%s,%s,%s)",
                                     ("destination", 1, encoded(proposal("destination"))))
                wait_blocked(store._db, store._db.info.backend_pid, other._db.info.backend_pid)
            with pytest.raises(psycopg.errors.RaiseException, match="capacity"):
                future.result(timeout=10)
        assert len(rows(store)) == 1
    finally:
        other.close()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
@pytest.mark.parametrize("writer", ["managed", "direct", "policy"])
def test_postgres_old_snapshot_writes_fail_closed(pg_journal, isolation, writer):
    import psycopg

    store, trust, proposal, _, _ = pg_journal
    trust.set_capacity(max_records=1, max_bytes=10000, max_entry_bytes=10000)
    other = reopen(store)
    try:
        with store._db.transaction():
            store._db.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
            assert store._db.execute("SELECT count(*) AS n FROM signing_trust_revisions").fetchone()["n"] == 0
            other._db.execute("INSERT INTO signing_trust_revisions VALUES(%s,%s,%s)", ("readback", 1, encoded(proposal())))
            with pytest.raises((TrustJournalDenied, SigningJournalCapacityDenied, psycopg.errors.RaiseException), match="READ COMMITTED"):
                # The savepoint lets the outer read-only snapshot roll back
                # normally after a direct trigger exception.
                with store._db.transaction():
                    if writer == "managed":
                        trust.publish(proposal("destination"))
                    elif writer == "policy":
                        trust.set_capacity(max_records=2, max_bytes=10000, max_entry_bytes=10000)
                    else:
                        store._db.execute("INSERT INTO signing_trust_revisions VALUES(%s,%s,%s)",
                                          ("destination", 1, encoded(proposal("destination"))))
        assert len(rows(store)) == 1 and trust.capacity()["max_records"] == 1
    finally:
        other.close()


@pytest.mark.parametrize("table", [TABLE, "signing_trust_revisions", "signing_trust_lock_v1"])
def test_postgres_unlogged_relations_refused_without_rewrite(pg_journal, table):
    store, _, _, pinned, _ = pg_journal
    store._db.execute("ALTER TABLE " + table + " SET UNLOGGED")
    with pytest.raises(SigningJournalCapacityDenied, match="ordinary permanent"):
        SigningTrustJournal(store, controller_keys=pinned)
    with pytest.raises(SigningJournalCapacityDenied, match="ordinary permanent"):
        verify_if_installed(store._db, postgres=True)
    assert store._db.execute("SELECT relpersistence FROM pg_class WHERE oid=%s::regclass", (table,)).fetchone()["relpersistence"] == "u"


@pytest.mark.parametrize("table", [TABLE, "signing_trust_revisions", "signing_trust_lock_v1"])
@pytest.mark.parametrize("forced", [False, True], ids=["enabled", "forced"])
def test_postgres_row_security_catalog_is_refused_without_repair(pg_journal, table, forced):
    store, _, _, pinned, _ = pg_journal
    store._db.execute("ALTER TABLE " + table + " ENABLE ROW LEVEL SECURITY")
    if forced:
        store._db.execute("ALTER TABLE " + table + " FORCE ROW LEVEL SECURITY")
    flags = dict(store._db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (table,)).fetchone())
    before = {name: [dict(row) for row in store._db.execute("SELECT * FROM " + name)]
              for name in (TABLE, "signing_trust_revisions", "signing_trust_lock_v1")}
    with pytest.raises(SigningJournalCapacityDenied, match="does not support PostgreSQL row security"):
        SigningTrustJournal(store, controller_keys=pinned)
    with pytest.raises(SigningJournalCapacityDenied, match="does not support PostgreSQL row security"):
        verify_if_installed(store._db, postgres=True)
    assert dict(store._db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (table,)).fetchone()) == flags
    assert {name: [dict(row) for row in store._db.execute("SELECT * FROM " + name)]
            for name in (TABLE, "signing_trust_revisions", "signing_trust_lock_v1")} == before


@pytest.mark.parametrize("name", [TABLE, "signing_trust_revisions", "signing_trust_lock_v1", "tenant_store_binding"])
def test_postgres_reserved_temp_names_refuse_managed_work(pg_journal, name):
    from psycopg import sql

    store, trust, proposal, pinned, schema = pg_journal
    store._db.execute("CREATE TEMP TABLE " + name + "(fake INTEGER)")
    for call in (lambda: SigningTrustJournal(store, controller_keys=pinned), lambda: trust.publish(proposal()), trust.capacity,
                 lambda: verify_if_installed(store._db, postgres=True)):
        with pytest.raises(SigningJournalCapacityDenied, match="TEMP"):
            call()
        for table in (TABLE, "signing_trust_revisions"):
            assert store._db.execute(sql.SQL("SELECT count(*) AS n FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))).fetchone()["n"] == 0


@pytest.mark.parametrize("damage", ["body", "security-definer", "stable", "search-path", "strict", "parallel", "overload", "missing"])
def test_postgres_modified_routine_refused_without_repair(pg_journal, damage):
    store, _, _, pinned, _ = pg_journal
    name = "agentbridge_signing_capacity_fence_v1"
    commands = {
        "body": "CREATE OR REPLACE FUNCTION " + name + "() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RETURN NULL; END $$",
        "security-definer": "ALTER FUNCTION " + name + "() SECURITY DEFINER",
        "stable": "ALTER FUNCTION " + name + "() STABLE", "search-path": "ALTER FUNCTION " + name + "() SET search_path=public",
        "strict": "ALTER FUNCTION " + name + "() STRICT", "parallel": "ALTER FUNCTION " + name + "() PARALLEL SAFE",
        "overload": "CREATE FUNCTION " + name + "(integer) RETURNS integer LANGUAGE sql AS 'SELECT $1'",
        "missing": "DROP FUNCTION " + name + "() CASCADE",
    }
    store._db.execute(commands[damage])
    before = [dict(row) for row in store._db.execute("SELECT p.proname,p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proisstrict,p.proparallel "
                                                    "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                                                    "WHERE n.nspname=current_schema() AND p.proname=%s ORDER BY p.pronargs", (name,))]
    with pytest.raises(SigningJournalCapacityDenied, match="routine"):
        SigningTrustJournal(store, controller_keys=pinned)
    with pytest.raises(SigningJournalCapacityDenied, match="routine"):
        verify_if_installed(store._db, postgres=True)
    assert [dict(row) for row in store._db.execute("SELECT p.proname,p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proisstrict,p.proparallel "
                                                  "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                                                  "WHERE n.nspname=current_schema() AND p.proname=%s ORDER BY p.pronargs", (name,))] == before


@pytest.mark.parametrize("damage", ["missing", "disabled", "wrong-function", "statement-instead-row", "condition"])
def test_postgres_modified_trigger_refused_without_repair(pg_journal, damage):
    store, _, _, pinned, _ = pg_journal
    if damage == "disabled":
        store._db.execute("ALTER TABLE signing_trust_revisions DISABLE TRIGGER signing_capacity_insert_v1")
    else:
        store._db.execute("DROP TRIGGER signing_capacity_insert_v1 ON signing_trust_revisions")
        if damage != "missing":
            suffix = " FOR EACH ROW EXECUTE FUNCTION agentbridge_signing_capacity_insert_v1()"
            if damage == "wrong-function":
                suffix = " FOR EACH ROW EXECUTE FUNCTION agentbridge_signing_immutable_v1()"
            elif damage == "statement-instead-row":
                suffix = " FOR EACH STATEMENT EXECUTE FUNCTION agentbridge_signing_capacity_insert_v1()"
            elif damage == "condition":
                suffix = " FOR EACH ROW WHEN (NEW.revision>1) EXECUTE FUNCTION agentbridge_signing_capacity_insert_v1()"
            store._db.execute("CREATE TRIGGER signing_capacity_insert_v1 AFTER INSERT ON signing_trust_revisions" + suffix)
    with pytest.raises(SigningJournalCapacityDenied, match="trigger"):
        SigningTrustJournal(store, controller_keys=pinned)
    with pytest.raises(SigningJournalCapacityDenied, match="trigger"):
        verify_if_installed(store._db, postgres=True)


@pytest.mark.parametrize("command", ["UPDATE signing_trust_revisions SET envelope='{}'", "DELETE FROM signing_trust_revisions",
                                    "TRUNCATE signing_trust_revisions", "DELETE FROM " + TABLE, "TRUNCATE " + TABLE,
                                    "INSERT INTO signing_trust_revisions SELECT * FROM signing_trust_revisions ON CONFLICT(domain,revision) DO UPDATE SET envelope='{}'"])
def test_postgres_history_and_policy_cannot_be_erased(pg_journal, command):
    import psycopg

    store, trust, proposal, _, _ = pg_journal
    trust.publish(proposal())
    before, capacity = rows(store), trust.capacity()
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be removed or replaced"):
        store._db.execute(command)
    assert rows(store) == before and trust.capacity() == capacity


def test_postgres_policy_audit_outer_rollback_and_existing_floor_limitation(pg_journal):
    store, trust, proposal, _, _ = pg_journal
    store._db.execute("CREATE TABLE policy_test_audit(message TEXT NOT NULL)")
    with pytest.raises(RuntimeError, match="outer abort"):
        with sql_atomic(store):
            trust.set_capacity(max_records=3, max_bytes=10000, max_entry_bytes=10000,
                               audit=lambda: store._db.execute("INSERT INTO policy_test_audit VALUES('changed')"))
            raise RuntimeError("outer abort")
    assert store._db.execute("SELECT count(*) AS n FROM " + TABLE).fetchone()["n"] == 0
    assert store._db.execute("SELECT count(*) AS n FROM policy_test_audit").fetchone()["n"] == 0
    first = proposal()
    trust.publish(first)
    with pytest.raises(RuntimeError, match="outer publish abort"):
        with sql_atomic(store):
            trust.publish(proposal(previous=first))
            assert trust._floors["readback"] == 2
            raise RuntimeError("outer publish abort")
    assert [row["revision"] for row in rows(store)] == [1]
    # This is the preserved existing composition limitation, not new safety:
    # the journal instance refuses the older persisted head after outer abort.
    with pytest.raises(TrustJournalDenied, match="minimum revision"):
        with trust._transaction(write=False) as cur:
            trust._load(cur, "readback")


def test_postgres_saturation_preserves_unknown_budget_hold_and_audit(pg_journal):
    store, trust, proposal, _, _ = pg_journal
    budgets = BudgetManager(store)
    budgets.set_budget("agent", Budget(spend_limit=10))
    reservation, _ = budgets.reserve("agent", 2)
    OperationLedger(store).claim("agent", "held-unknown-12345", "fingerprint", reservation_token=reservation)
    AuditTrustStore(store).set_hold("retained-case", True)
    head = proposal()
    trust.publish(head)
    trust.set_capacity(max_records=1, max_bytes=10000, max_entry_bytes=10000)
    before = (rows(store), store.get_budget("agent"), store.load_audit())
    with pytest.raises(TrustJournalDenied, match="capacity"):
        trust.publish(proposal(previous=head))
    assert (rows(store), store.get_budget("agent"), store.load_audit()) == before
    assert OperationLedger(store).get("agent", "held-unknown-12345")["state"] == "unknown"
    assert AuditTrustStore(store).holds() == ["retained-case"]
