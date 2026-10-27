"""Actual retained bundle SQL bounds; synthetic local databases, no effects."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import threading
import time

import pytest

from src.governance.evidence_journal_capacity import (
    DEFAULTS, HISTORY, TABLE, EvidenceCapacityDenied, EvidenceLimits,
    install_postgres, install_sqlite, policy, verify_if_installed,
    verify_snapshot,
)
from src.governance.store import PostgresStore, SqliteStore, sql_atomic


DDL = ("CREATE TABLE reconciliation_evidence(agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,"
       "bundle TEXT NOT NULL,PRIMARY KEY(agent_id,operation_id))")


def execute(store, query, args=()):
    return store._db.execute(query.replace("?", "%s") if isinstance(store, PostgresStore) else query, args)


def error(store):
    if isinstance(store, SqliteStore):
        return sqlite3.DatabaseError
    import psycopg
    return psycopg.Error


def bootstrap(store):
    with sql_atomic(store), closing(store._db.cursor()) as cur:
        if isinstance(store, PostgresStore):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (911001,))
        cur.execute(DDL)
        (install_postgres if isinstance(store, PostgresStore) else install_sqlite)(cur)


def install_again(store):
    with sql_atomic(store), closing(store._db.cursor()) as cur:
        (install_postgres if isinstance(store, PostgresStore) else install_sqlite)(cur)


def rows(store):
    return [dict(r) for r in store._db.execute("SELECT * FROM " + HISTORY + " ORDER BY agent_id,operation_id").fetchall()]


def policies(store):
    return [dict(r) for r in store._db.execute("SELECT * FROM " + TABLE).fetchall()]


def snapshot(store):
    with closing(store._db.cursor()) as cur:
        return verify_snapshot(cur, postgres=isinstance(store, PostgresStore))


def insert(store, operation, bundle, *, agent="agent"):
    execute(store, "INSERT INTO " + HISTORY + "(agent_id,operation_id,bundle) VALUES(?,?,?)", (agent, operation, bundle))


@pytest.fixture
def evidence(network_sql_stores):
    store = network_sql_stores()
    bootstrap(store)
    return store, network_sql_stores


@pytest.mark.parametrize("fields", [
    {"max_records": 0}, {"max_records": True}, {"max_records": 1.0}, {"max_records": 1000001},
    {"max_bytes": 0}, {"max_bytes": 1073741825}, {"max_entry_bytes": 0}, {"max_entry_bytes": 1048577},
    {"max_bytes": 1, "max_entry_bytes": 2},
])
def test_invalid_bounded_limits(fields):
    with pytest.raises(EvidenceCapacityDenied):
        replace(DEFAULTS, **fields)


def test_bootstrap_is_lazy_and_restart_preserves_actual_policy_and_bytes(evidence):
    store, factory = evidence
    assert policies(store) == []
    assert snapshot(store) == {"records": 0, "bytes": 0, "largest_entry_bytes": 0}
    first = json.dumps({"receipt": "é漢🚀"}, ensure_ascii=False)
    insert(store, "first", first)
    usage = policy(store)
    assert usage["used_records"] == 1 and usage["used_bytes"] == len(first.encode())
    assert usage["largest_entry_bytes"] == len(first.encode())
    policy(store, limits=EvidenceLimits(7, 8000, 2000))
    reconnected = factory()
    install_again(reconnected)
    assert policy(reconnected) == policy(store)
    assert rows(reconnected) == rows(store)


@pytest.mark.parametrize("charset", ["ascii", "unicode"])
@pytest.mark.parametrize("boundary", ["count", "aggregate", "entry"])
def test_exact_direct_sql_bounds_and_one_excess_rollback(evidence, charset, boundary):
    store, _ = evidence
    raw = json.dumps({"payload": "ASCII" if charset == "ascii" else "é漢🚀"}, ensure_ascii=False)
    size = len(raw.encode("utf-8"))
    limits = {"count": EvidenceLimits(1, size * 3, size * 3),
              "aggregate": EvidenceLimits(3, size, size),
              "entry": EvidenceLimits(3, size * 3, size)}[boundary]
    policy(store, limits=limits)
    insert(store, "first", raw)
    before, capacity = rows(store), policy(store)
    with pytest.raises(error(store), match="evidence capacity"):
        insert(store, "second", raw + " " if boundary == "entry" else " ")
    assert rows(store) == before and policy(store) == capacity


def test_multirow_overflow_is_one_atomic_statement(evidence):
    store, _ = evidence
    policy(store, limits=EvidenceLimits(1, 1000, 1000))
    before = policies(store)
    with pytest.raises(error(store), match="evidence capacity"):
        execute(store, "INSERT INTO " + HISTORY + " VALUES(?,?,?),(?,?,?)", ("a", "one", "{}", "b", "two", "{}"))
    assert rows(store) == [] and policies(store) == before


@pytest.mark.parametrize("command", [
    "INSERT INTO reconciliation_evidence VALUES('agent','first','changed')",
    "INSERT INTO reconciliation_evidence VALUES('agent','first','changed') ON CONFLICT(agent_id,operation_id) DO NOTHING",
    "INSERT INTO reconciliation_evidence VALUES('agent','first','changed') ON CONFLICT(agent_id,operation_id) DO UPDATE SET bundle=excluded.bundle",
    "UPDATE reconciliation_evidence SET bundle='changed'",
    "DELETE FROM reconciliation_evidence",
    "DELETE FROM evidence_capacity_policy_v1",
])
def test_duplicate_upsert_and_history_policy_removal_are_refused(evidence, command):
    store, _ = evidence
    insert(store, "first", "original")
    policy(store, limits=EvidenceLimits(1, 1000, 1000))
    before = rows(store), policies(store)
    with pytest.raises(error(store), match="already exists|cannot be removed or replaced"):
        store._db.execute(command)
    assert (rows(store), policies(store)) == before


@pytest.mark.parametrize("table", [HISTORY, TABLE])
def test_sqlite_replace_and_ignore_cannot_evict_retained_rows(tmp_path, table):
    with closing(SqliteStore(str(tmp_path / "replace.sqlite"))) as store:
        bootstrap(store)
        store._db.execute("PRAGMA recursive_triggers=OFF")
        insert(store, "first", "original")
        before = rows(store), policies(store)
        values = "('agent','first','changed')" if table == HISTORY else "(1,1,7,8000,1000)"
        for mode in ("REPLACE", "IGNORE"):
            with pytest.raises(sqlite3.DatabaseError, match="already exists"):
                store._db.execute("INSERT OR " + mode + " INTO " + table + " VALUES" + values)
            assert (rows(store), policies(store)) == before


def test_legacy_oversized_history_is_preserved_and_blocks_all_growth(network_sql_stores):
    store = network_sql_stores()
    store._db.execute(DDL)
    old = "é" * 150000
    insert(store, "legacy", old)
    with sql_atomic(store), closing(store._db.cursor()) as cur:
        (install_postgres if isinstance(store, PostgresStore) else install_sqlite)(cur)
    assert policies(store) == []
    assert snapshot(store)["largest_entry_bytes"] == len(old.encode()) > DEFAULTS.max_entry_bytes
    before = rows(store)
    with pytest.raises(error(store), match="evidence capacity"):
        insert(store, "small", "{}")
    assert rows(store) == before and policies(store) == []
    inspection = policy(store)
    assert inspection["used_bytes"] == len(old.encode()) and inspection["max_records"] > 1
    policy(store, limits=EvidenceLimits(3, 400000, 400000))
    insert(store, "small", "{}")
    assert rows(store)[0]["bundle"] == old


@pytest.mark.parametrize("boundary", ["count", "aggregate", "entry"])
def test_lowered_policy_keeps_history_and_blocks_growth_until_raise(evidence, boundary):
    store, _ = evidence
    insert(store, "first", "漢" * 10)
    old = rows(store)
    limits = {"count": EvidenceLimits(1, 1000, 1000), "aggregate": EvidenceLimits(10, 2, 2),
              "entry": EvidenceLimits(10, 1000, 1)}[boundary]
    lowered = policy(store, limits=limits)
    assert rows(store) == old
    assert lowered["used_bytes"] == 30 and lowered["largest_entry_bytes"] == 30
    with pytest.raises(error(store), match="evidence capacity"):
        insert(store, "small", "x")
    assert rows(store) == old and policy(store) == lowered
    policy(store, limits=EvidenceLimits(10, 1000, 1000))
    insert(store, "small", "x")
    assert len(rows(store)) == 2


def test_policy_callback_and_outer_rollback_preserve_owned_transaction(evidence):
    store, _ = evidence
    original = policy(store)
    store._db.execute("CREATE TABLE capacity_callback(value TEXT NOT NULL)")
    def fail():
        store._db.execute("INSERT INTO capacity_callback VALUES('tentative')")
        raise RuntimeError("audit callback denied")
    with pytest.raises(RuntimeError, match="audit callback denied"):
        policy(store, limits=EvidenceLimits(7, 8000, 1000), audit=fail)
    assert policy(store) == original
    assert store._db.execute("SELECT count(*) AS n FROM capacity_callback").fetchone()["n"] == 0
    with pytest.raises(RuntimeError, match="outer abort"):
        with sql_atomic(store):
            policy(store, limits=EvidenceLimits(9, 9000, 1000), audit=lambda: store._db.execute("INSERT INTO capacity_callback VALUES('outer')"))
            raise RuntimeError("outer abort")
    assert policy(store) == original
    assert store._db.execute("SELECT count(*) AS n FROM capacity_callback").fetchone()["n"] == 0


def test_callback_temp_schema_drift_is_refused_and_rolled_back(evidence):
    store, _ = evidence
    original = policy(store)
    with pytest.raises(EvidenceCapacityDenied, match="TEMP"):
        policy(store, limits=EvidenceLimits(7, 8000, 1000),
               audit=lambda: store._db.execute("CREATE TEMP TABLE reconciliation_evidence(value TEXT)"))
    assert policy(store) == original and rows(store) == []


def test_independent_direct_workers_cannot_overrun_last_slot(evidence):
    store, factory = evidence
    policy(store, limits=EvidenceLimits(1, 1000, 1000))
    start = threading.Barrier(3)
    def worker(number):
        connection = factory()
        start.wait(timeout=10)
        try:
            with sql_atomic(connection):
                insert(connection, str(number), "{}")
            return "committed"
        except error(connection) as exc:
            assert "evidence capacity" in str(exc)
            return "capacity-denied"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, n) for n in range(2)]
        start.wait(timeout=10)
        results = [future.result(timeout=15) for future in futures]
    assert sorted(results) == ["capacity-denied", "committed"]
    assert len(rows(store)) == 1 and policy(store)["used_records"] == 1


@pytest.mark.parametrize("shape", ["extra-column", "missing-primary", "wrong-primary", "extra-unique"])
def test_unsupported_existing_composite_schema_is_not_repaired(network_sql_stores, shape):
    store = network_sql_stores()
    ddl = {
        "extra-column": "CREATE TABLE reconciliation_evidence(agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,bundle TEXT NOT NULL,extra TEXT,PRIMARY KEY(agent_id,operation_id))",
        "missing-primary": "CREATE TABLE reconciliation_evidence(agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,bundle TEXT NOT NULL)",
        "wrong-primary": "CREATE TABLE reconciliation_evidence(agent_id TEXT PRIMARY KEY,operation_id TEXT NOT NULL,bundle TEXT NOT NULL)",
        "extra-unique": "CREATE TABLE reconciliation_evidence(agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,bundle TEXT NOT NULL,PRIMARY KEY(agent_id,operation_id),UNIQUE(bundle))",
    }[shape]
    store._db.execute(ddl)
    insert(store, "history", "original")
    before = rows(store)
    with pytest.raises(EvidenceCapacityDenied, match="schema|constraints"):
        install_again(store)
    assert rows(store) == before
    if isinstance(store, SqliteStore):
        assert store._db.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None
    else:
        assert store._db.execute("SELECT to_regclass(%s) AS name", (TABLE,)).fetchone()["name"] is None


@pytest.mark.parametrize("damage", ["missing", "body"])
def test_installed_trigger_drift_refuses_policy_and_bootstrap_without_repair(evidence, damage):
    store, _ = evidence
    insert(store, "first", "original")
    before = rows(store), policies(store)
    if isinstance(store, SqliteStore):
        store._db.execute("DROP TRIGGER evidence_capacity_insert_v1")
        if damage == "body":
            store._db.execute("CREATE TRIGGER evidence_capacity_insert_v1 AFTER INSERT ON reconciliation_evidence BEGIN SELECT 1; END")
        def definition():
            return [dict(r) for r in store._db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name='evidence_capacity_insert_v1'")]
    else:
        store._db.execute("DROP TRIGGER evidence_capacity_insert_v1 ON reconciliation_evidence")
        if damage == "body":
            store._db.execute("CREATE TRIGGER evidence_capacity_insert_v1 BEFORE INSERT ON reconciliation_evidence FOR EACH ROW EXECUTE FUNCTION agentbridge_evidence_capacity_v1()")
        def definition():
            return [dict(r) for r in store._db.execute("SELECT tgname,pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE tgrelid='reconciliation_evidence'::regclass AND tgname='evidence_capacity_insert_v1'")]
    broken = definition()
    for call in (lambda: policy(store), lambda: install_again(store), lambda: snapshot(store)):
        with pytest.raises(EvidenceCapacityDenied, match="trigger"):
            call()
        assert (rows(store), policies(store)) == before and definition() == broken


@pytest.mark.parametrize("name", [HISTORY, TABLE, "audit", "tenant_store_binding"])
@pytest.mark.parametrize("spelling", [str.lower, str.upper, str.title], ids=["lower", "upper", "mixed"])
def test_sqlite_reserved_temp_names_cannot_redirect_policy_or_snapshot(tmp_path, name, spelling):
    with closing(SqliteStore(str(tmp_path / "temp.sqlite"))) as store:
        bootstrap(store)
        insert(store, "first", "original")
        before = rows(store), policies(store)
        store._db.execute('CREATE TEMP TABLE "' + spelling(name) + '"(value TEXT)')
        for call in (lambda: policy(store), lambda: snapshot(store), lambda: install_again(store)):
            with pytest.raises(EvidenceCapacityDenied, match="TEMP"):
                call()
        assert [dict(r) for r in store._db.execute("SELECT * FROM main.reconciliation_evidence")] == before[0]
        assert [dict(r) for r in store._db.execute("SELECT * FROM main." + TABLE)] == before[1]


@pytest.mark.parametrize("table", [HISTORY, TABLE])
@pytest.mark.parametrize("spelling", [str.upper, str.title], ids=["upper", "mixed"])
def test_sqlite_noncanonical_main_names_are_refused(tmp_path, table, spelling):
    with closing(SqliteStore(str(tmp_path / "case.sqlite"))) as store:
        bootstrap(store)
        insert(store, "first", "original")
        store._db.execute('ALTER TABLE "' + table + '" RENAME TO "temporary_owned_name"')
        store._db.execute('ALTER TABLE temporary_owned_name RENAME TO "' + spelling(table) + '"')
        with pytest.raises(EvidenceCapacityDenied, match="noncanonical"):
            install_again(store)
        assert store._db.execute('SELECT count(*) AS n FROM "' + spelling(HISTORY if table == HISTORY else TABLE) + '"').fetchone()["n"] == 1


@pytest.mark.parametrize("spelling", [str.upper, str.title], ids=["upper", "mixed"])
def test_sqlite_preexisting_noncanonical_owned_trigger_is_not_silently_installed(tmp_path, spelling):
    with closing(SqliteStore(str(tmp_path / "trigger-case.sqlite"))) as store:
        store._db.execute(DDL)
        name = spelling("evidence_capacity_insert_v1")
        store._db.execute('CREATE TRIGGER "' + name + '" AFTER INSERT ON reconciliation_evidence BEGIN SELECT 1; END')
        with pytest.raises(EvidenceCapacityDenied, match="noncanonical"):
            install_again(store)
        assert store._db.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None
        assert store._db.execute("SELECT name FROM sqlite_master WHERE name=?", (name,)).fetchone()["name"] == name


@pytest.mark.parametrize("command", ["UPDATE evidence_capacity_policy_v1 SET version=2",
                                    "UPDATE evidence_capacity_policy_v1 SET max_records=0",
                                    "UPDATE evidence_capacity_policy_v1 SET max_entry_bytes=max_bytes+1"])
def test_invalid_sql_policy_updates_leave_policy_and_history_unchanged(evidence, command):
    store, _ = evidence
    insert(store, "first", "original")
    before = rows(store), policies(store)
    with pytest.raises(error(store)):
        store._db.execute(command)
    assert (rows(store), policies(store)) == before


def test_missing_policy_among_installed_artifacts_is_refused_without_recreation(evidence):
    store, _ = evidence
    insert(store, "first", "original")
    before = rows(store)
    store._db.execute("DROP TABLE " + TABLE + (" CASCADE" if isinstance(store, PostgresStore) else ""))
    with closing(store._db.cursor()) as cur:
        with pytest.raises(EvidenceCapacityDenied, match="metadata missing"):
            verify_if_installed(cur, postgres=isinstance(store, PostgresStore))
    with pytest.raises(EvidenceCapacityDenied, match="metadata missing"):
        install_again(store)
    assert rows(store) == before
    if isinstance(store, PostgresStore):
        assert store._db.execute("SELECT to_regclass(%s) AS name", (TABLE,)).fetchone()["name"] is None
    else:
        assert store._db.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None


def test_sqlite_utf16_is_preserved_but_not_miscounted(tmp_path):
    path = tmp_path / "utf16.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA encoding='UTF-16le'")
        connection.execute(DDL)
        connection.execute("INSERT INTO reconciliation_evidence VALUES('agent','legacy','漢字')")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        with pytest.raises(EvidenceCapacityDenied, match="UTF-8"):
            install_sqlite(connection)
        assert connection.execute("SELECT bundle FROM reconciliation_evidence").fetchone()["bundle"] == "漢字"
        assert connection.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None
    finally:
        connection.close()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
@pytest.mark.parametrize("surface", ["direct", "policy"])
def test_postgres_stale_transaction_growth_refused_without_changes(evidence, isolation, surface):
    store, _ = evidence
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL transaction snapshot contract")
    original = policy(store)
    with pytest.raises((error(store), EvidenceCapacityDenied), match="READ COMMITTED"):
        with store._db.transaction():
            store._db.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
            store._db.execute("SELECT count(*) FROM reconciliation_evidence")
            if surface == "direct":
                insert(store, "denied", "{}")
            else:
                policy(store, limits=EvidenceLimits(7, 8000, 1000))
    assert rows(store) == [] and policy(store) == original
    insert(store, "explicit-RC", "{}")
    assert len(rows(store)) == 1


@pytest.mark.parametrize("table", [HISTORY, TABLE])
@pytest.mark.parametrize("change", ["unlogged", "RLS", "forced-RLS"])
def test_postgres_unsupported_relation_catalog_is_refused_without_repair(evidence, table, change):
    store, _ = evidence
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL relation catalog contract")
    insert(store, "first", "original")
    before = rows(store), policies(store)
    command = {"unlogged": " SET UNLOGGED", "RLS": " ENABLE ROW LEVEL SECURITY", "forced-RLS": " FORCE ROW LEVEL SECURITY"}[change]
    store._db.execute("ALTER TABLE " + table + command)
    def flags():
        return dict(store._db.execute("SELECT relpersistence,relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (table,)).fetchone())
    altered = flags()
    for call in (lambda: policy(store), lambda: snapshot(store), lambda: install_again(store)):
        with pytest.raises(EvidenceCapacityDenied, match="permanent unfiltered"):
            call()
    assert flags() == altered and (rows(store), policies(store)) == before


@pytest.mark.parametrize("change", ["body", "security-definer", "stable", "search-path", "missing"])
def test_postgres_modified_or_missing_routine_is_not_repaired(evidence, change):
    store, _ = evidence
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL exact routine contract")
    original = policy(store)
    function = "agentbridge_evidence_capacity_v1"
    commands = {
        "body": "CREATE OR REPLACE FUNCTION " + function + "() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RETURN NULL; END $$",
        "security-definer": "ALTER FUNCTION " + function + "() SECURITY DEFINER",
        "stable": "ALTER FUNCTION " + function + "() STABLE",
        "search-path": "ALTER FUNCTION " + function + "() SET search_path=public",
        "missing": "DROP FUNCTION " + function + "() CASCADE",
    }
    store._db.execute(commands[change])
    def observed():
        return [dict(r) for r in store._db.execute("SELECT p.proname,p.prosrc,p.prosecdef,p.provolatile,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname=%s", (function,))]
    altered = observed()
    for call in (lambda: policy(store), lambda: install_again(store)):
        with pytest.raises(EvidenceCapacityDenied, match="routine"):
            call()
    assert observed() == altered and rows(store) == []
    assert policies(store)[0]["max_records"] == original["max_records"]


def test_postgres_callback_namespace_drift_aborts_configuration(evidence):
    store, _ = evidence
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL fixed namespace contract")
    original = policy(store)
    schema = store._db.execute("SELECT current_schema() AS name").fetchone()["name"]
    with pytest.raises(EvidenceCapacityDenied, match="namespace changed"):
        policy(store, limits=EvidenceLimits(7, 8000, 1000),
               audit=lambda: store._db.execute("SET LOCAL search_path=public"))
    assert store._db.execute("SELECT current_schema() AS name").fetchone()["name"] == schema
    assert policy(store) == original


@pytest.mark.parametrize("table", [HISTORY, TABLE])
def test_postgres_truncate_cannot_remove_evidence_or_policy(evidence, table):
    store, _ = evidence
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL TRUNCATE contract")
    insert(store, "first", "original")
    before = rows(store), policies(store)
    with pytest.raises(error(store), match="cannot be removed or replaced"):
        store._db.execute("TRUNCATE " + table)
    assert (rows(store), policies(store)) == before


def test_postgres_repeatable_read_read_only_snapshot_does_not_initialize_or_mutate(evidence):
    store, _ = evidence
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL read-only snapshot contract")
    before = rows(store), policies(store)
    with store._db.transaction():
        store._db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        store._db.execute("SET TRANSACTION READ ONLY")
        assert snapshot(store) == {"records": 0, "bytes": 0, "largest_entry_bytes": 0}
    assert (rows(store), policies(store)) == before == ([], [])
    insert(store, "first", "original")
    before = rows(store), policies(store)
    with store._db.transaction():
        store._db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        store._db.execute("SET TRANSACTION READ ONLY")
        assert snapshot(store) == {"records": 1, "bytes": 8, "largest_entry_bytes": 8}
    assert (rows(store), policies(store)) == before


@pytest.mark.parametrize("name", [HISTORY, TABLE])
def test_postgres_reserved_temp_table_refuses_policy_snapshot_and_bootstrap(evidence, name):
    store, _ = evidence
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL TEMP namespace contract")
    insert(store, "first", "original")
    original = rows(store), policies(store)
    schema = store._db.execute("SELECT current_schema() AS name").fetchone()["name"]
    store._db.execute("CREATE TEMP TABLE " + name + "(value TEXT)")
    for call in (lambda: policy(store), lambda: snapshot(store), lambda: install_again(store)):
        with pytest.raises(EvidenceCapacityDenied, match="TEMP"):
            call()
    qualified = '"' + schema.replace('"', '""') + '".'
    assert [dict(r) for r in store._db.execute("SELECT * FROM " + qualified + HISTORY + " ORDER BY agent_id,operation_id")] == original[0]
    assert [dict(r) for r in store._db.execute("SELECT * FROM " + qualified + TABLE)] == original[1]


def test_postgres_direct_writer_waits_before_unique_identity_ownership(evidence):
    first, factory = evidence
    if not isinstance(first, PostgresStore):
        pytest.skip("PostgreSQL statement fence visibility")
    policy(first, limits=EvidenceLimits(1, 1000, 1000))
    raw, observer = factory(), factory()
    raw_pid = raw._db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    started = threading.Event()
    def worker():
        started.set()
        try:
            insert(raw, "same", "raw")
            return "unexpected"
        except error(raw) as exc:
            assert "already exists" in str(exc)
            return "duplicate-denied"
    with ThreadPoolExecutor(max_workers=1) as pool:
        with sql_atomic(first):
            first._db.execute("SELECT pg_advisory_xact_lock(911001)")
            future = pool.submit(worker)
            assert started.wait(5)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                waiting = observer._db.execute("SELECT pg_blocking_pids(%s) AS pids", (raw_pid,)).fetchone()["pids"]
                if waiting:
                    break
                time.sleep(0.01)
            else:
                pytest.fail("raw worker was not proven waiting for the managed audit fence")
            first._db.execute("SET LOCAL lock_timeout='2s'")
            insert(first, "same", "managed")
        assert future.result(timeout=8) == "duplicate-denied"
    assert [r["bundle"] for r in rows(first)] == ["managed"]
