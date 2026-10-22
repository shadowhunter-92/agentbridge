"""SQL audit bounds retain evidence and participate in existing transactions."""
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.audit import AuditLog
from src.governance.audit_capacity import AuditCapacityDenied, AuditLimits
from src.governance.audit_trust import AuditTrustStore
from src.governance.operation_ledger import OperationLedger
from src.governance.store import PostgresStore, SqliteStore, sql_atomic
from src.governance.tenant_store import TenantSqliteStore
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.protocols.task_lifecycle import TaskLifecycle, TaskState


def record(log, reason=""):
    return log.record(actor="worker", action="test", source_protocol="mcp", target_protocol="a2a",
                      capability="read", decision="allow", reason=reason)


def execute(store, query, values=()):
    return store._db.execute(query.replace("?", "%s") if isinstance(store, PostgresStore) else query, values)


def actual_usage(store):
    records = store.load_audit()
    return len(records), sum(len(json.dumps(row).encode()) for row in records)


def test_durable_capacity_and_counts_survive_other_worker_restart(network_sql_stores):
    first, second = network_sql_stores(), network_sql_stores()
    config, observed = AuditTrustStore(first), AuditTrustStore(second)
    config.set_capacity(max_records=2, max_bytes=4096, max_entry_bytes=2048)
    writer = AuditLog(first)
    record(writer)
    record(AuditLog(second))
    snapshot = first.load_audit()
    with pytest.raises(Exception, match="audit capacity"):
        record(writer)
    assert first.load_audit() == snapshot
    state = AuditTrustStore(network_sql_stores()).capacity()
    assert state == observed.capacity()
    assert (state["used_records"], state["used_bytes"]) == actual_usage(first)
    assert (state["max_records"], state["max_bytes"], state["max_entry_bytes"]) == (2, 4096, 2048)
    assert writer.verify_durable()


@pytest.mark.parametrize("limit", ["bytes", "entry"])
def test_exact_serialized_byte_limit_and_one_byte_excess(network_sql_stores, limit):
    store = network_sql_stores()
    # Direct JSON text includes multibyte UTF-8; capacity counts stored bytes,
    # not Python characters or a second serialization of the stored document.
    raw = json.dumps({"seq": 0, "payload": "é漢"}, ensure_ascii=False)
    size = len(raw.encode())
    cap = AuditTrustStore(store)
    cap.set_capacity(max_records=5, max_bytes=size if limit == "bytes" else 4096,
                     max_entry_bytes=size)
    execute(store, "INSERT INTO audit(seq,entry) VALUES(?,?)", (0, raw))
    state = cap.capacity()
    assert state["used_bytes"] == size
    assert state["used_records"] == 1
    if limit == "entry":
        raw = raw.replace('"seq": 0', '"seq": 1') + " "
    with pytest.raises(Exception, match="audit capacity"):
        execute(store, "INSERT INTO audit(seq,entry) VALUES(?,?)", (1, raw))
    assert cap.capacity() == state
    assert store.audit_count() == 1


def test_direct_store_and_raw_sql_cannot_bypass_row_limit(network_sql_stores):
    store = network_sql_stores()
    cap = AuditTrustStore(store)
    cap.set_capacity(max_records=1, max_bytes=4096, max_entry_bytes=4096)
    store.append_audit({"seq": 0})
    for write in (lambda: store.append_audit({"seq": 1}),
                  lambda: execute(store, "INSERT INTO audit(seq,entry) VALUES(?,?)", (1, '{"seq":1}'))):
        with pytest.raises(Exception, match="audit capacity"):
            write()
        assert cap.capacity()["used_records"] == 1
        assert store.load_audit() == [{"seq": 0}]


def test_capacity_failure_rolls_back_operation_budget_approval_and_audit(network_sql_stores):
    store = network_sql_stores()
    cap = AuditTrustStore(store)
    cap.set_capacity(max_records=1, max_bytes=4096, max_entry_bytes=4096)
    log = AuditLog(store)
    record(log)
    ledger = OperationLedger(store)
    store.upsert_budget("agent", {"spent": 0, "reserved": {}})
    store.insert_approval(dict(id="approval", agent_id="agent", capability="read", cost=1, status="approved"))
    before = cap.capacity()
    with pytest.raises(Exception, match="audit capacity"):
        with sql_atomic(store):
            ledger.claim("agent", "operation", "fingerprint")
            store.upsert_budget("agent", {"spent": 0, "reserved": {"token": 1}})
            assert store.consume_approval("approval")
            record(log)
    assert ledger.get("agent", "operation") is None
    assert store.get_budget("agent")["reserved"] == {}
    assert store.get_approval("approval")["status"] == "approved"
    assert cap.capacity() == before
    assert log.verify_durable()


def test_after_effect_failure_preserves_unknown_and_held_budget(network_sql_stores):
    store = network_sql_stores()
    ledger = OperationLedger(store)
    ledger.claim("agent", "operation", "fingerprint", reservation_token="token")
    store.upsert_budget("agent", {"spent": 0, "reserved": {"token": 1}})
    cap = AuditTrustStore(store)
    cap.set_capacity(max_records=1, max_bytes=4096, max_entry_bytes=4096)
    log = AuditLog(store)
    record(log)
    # Model a real effect followed by failure to persist its final accounting.
    # Capacity must never turn uncertainty into a refund or replay permission.
    with pytest.raises(Exception, match="audit capacity"):
        with sql_atomic(store):
            ledger.finish("agent", "operation", "succeeded")
            store.upsert_budget("agent", {"spent": 1, "reserved": {}})
            record(log)
    assert ledger.get("agent", "operation")["state"] == "unknown"
    assert store.get_budget("agent")["reserved"] == {"token": 1}
    assert store.get_budget("agent")["spent"] == 0


def test_concurrent_independent_workers_observe_exact_shared_capacity(network_sql_stores):
    first, second = network_sql_stores(), network_sql_stores()
    cap = AuditTrustStore(first)
    cap.set_capacity(max_records=7, max_bytes=10000, max_entry_bytes=2000)
    def append(store):
        try:
            record(AuditLog(store))
            return "accepted"
        except Exception as error:
            assert "audit capacity" in str(error)
            return "full"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append, [first, second] * 6))
    assert outcomes.count("accepted") == 7
    assert outcomes.count("full") == 5
    assert cap.capacity()["used_records"] == 7
    assert (cap.capacity()["used_records"], cap.capacity()["used_bytes"]) == actual_usage(first)
    assert AuditLog(first).verify_durable()


def test_lowering_capacity_preserves_history_and_expansion_is_auditable(network_sql_stores):
    store = network_sql_stores()
    log, cap = AuditLog(store), AuditTrustStore(store)
    for _ in range(3):
        record(log)
    before = store.load_audit()
    cap.set_capacity(max_records=1, max_bytes=4096, max_entry_bytes=2048)
    assert store.load_audit() == before
    with pytest.raises(Exception, match="audit capacity"):
        record(log)
    cap.set_capacity(max_records=4, max_bytes=8192, max_entry_bytes=2048, audit=lambda: record(log, "operator increase"))
    assert cap.capacity()["used_records"] == 4
    old = cap.capacity()
    with pytest.raises(Exception, match="audit capacity"):
        cap.set_capacity(max_records=4, max_bytes=8192, max_entry_bytes=2048, audit=lambda: record(log))
    assert cap.capacity() == old


def test_nested_capacity_failure_preserves_outer_transaction(network_sql_stores):
    store = network_sql_stores()
    cap = AuditTrustStore(store)
    cap.set_capacity(max_records=1, max_bytes=4096, max_entry_bytes=2048)
    record(AuditLog(store))
    with sql_atomic(store):
        store.upsert_budget("before", {"spent": 1})
        with pytest.raises(Exception, match="audit capacity"):
            record(AuditLog(store))
        store.upsert_budget("after", {"spent": 2})
    assert store.get_budget("before")["spent"] == 1
    assert store.get_budget("after")["spent"] == 2
    assert cap.capacity()["used_records"] == 1


@pytest.mark.parametrize("fields", [{"max_records": True}, {"max_records": 0}, {"max_bytes": 1024**3 + 1},
                                   {"max_entry_bytes": 65537}, {"max_bytes": 1}, {"max_records": 1.5}])
def test_invalid_capacity_rejected(fields):
    with pytest.raises(AuditCapacityDenied):
        AuditLimits(**fields)


def test_existing_history_is_accounted_without_rewrite_or_eviction(tmp_path):
    path = str(tmp_path / "old.sqlite")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE audit(seq INTEGER PRIMARY KEY, entry TEXT NOT NULL)")
    row = json.dumps({"seq": 0, "payload": "x" * 20000})
    old.execute("INSERT INTO audit VALUES(0,?)", (row,))
    old.commit()
    old.close()
    store = SqliteStore(path)
    try:
        assert store._db.execute("SELECT count(*) AS n FROM audit_capacity_policy_v1").fetchone()["n"] == 0
        cap = AuditTrustStore(store)
        state = cap.capacity()
        assert state["used_bytes"] == len(row.encode())
        assert state["used_records"] == 1
        assert store._db.execute("SELECT entry FROM audit").fetchone()["entry"] == row
        # Historical oversized records are preserved; new oversized records fail.
        with pytest.raises(Exception, match="audit capacity"):
            store.append_audit({"seq": 1, "payload": "x" * 20000})
        assert cap.capacity() == state
    finally:
        store.close()


def test_tenant_scope_binds_before_capacity_is_materialized(tmp_path):
    store = TenantSqliteStore(str(tmp_path / "tenant.sqlite"), tenant_id="tenant-a")
    try:
        cap = AuditTrustStore(store)
        cap.set_capacity(max_records=1, max_bytes=4096, max_entry_bytes=2048)
        record(AuditLog(store))
        store.assert_scope()
        assert cap.capacity()["used_records"] == 1
    finally:
        store.close()


def test_duplicate_raw_insert_does_not_charge_capacity(network_sql_stores):
    store = network_sql_stores()
    cap = AuditTrustStore(store)
    cap.set_capacity(max_records=1, max_bytes=4096, max_entry_bytes=2048)
    store.append_audit({"seq": 0})
    before = cap.capacity()
    query = ("INSERT INTO audit VALUES(?,?) ON CONFLICT(seq) DO NOTHING" if isinstance(store, PostgresStore)
             else "INSERT OR IGNORE INTO audit VALUES(?,?)")
    if isinstance(store, PostgresStore):
        execute(store, query, (0, '{"seq":0}'))
    else:
        with pytest.raises(Exception, match="replacement forbidden"):
            execute(store, query, (0, '{"seq":0}'))
    assert cap.capacity() == before


@pytest.mark.parametrize("state", ["unknown", "succeeded", "failed"])
def test_any_retained_operation_protects_audit_even_terminal_task(network_sql_stores, monkeypatch, state):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    store = network_sql_stores()
    log = AuditLog(store)
    for _ in range(3):
        record(log)
    ledger = OperationLedger(store)
    ledger.claim("agent", "operation", "fingerprint")
    ledger.finish("agent", "operation", state)
    tasks = DurableTaskLifecycle(store)
    tasks.create("owner", TaskLifecycle("task", "context", "agentbridge"))
    tasks.transition("owner", "task", TaskState.CANCELED, expected_sequence=0)
    with pytest.raises(PermissionError, match="operation evidence"):
        store.truncate_audit_before(2)
    assert store.audit_count() == 3
    assert log.verify_durable()


@pytest.mark.parametrize("blocker", ["hold", "active-task", "reservation"])
def test_hold_active_task_and_pending_budget_protect_audit(network_sql_stores, monkeypatch, blocker):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    store = network_sql_stores()
    for _ in range(3):
        record(AuditLog(store))
    if blocker == "hold":
        AuditTrustStore(store).set_hold("case", True)
    elif blocker == "active-task":
        DurableTaskLifecycle(store).create("owner", TaskLifecycle("task", "context", "agentbridge"))
    else:
        store.upsert_budget("agent", {"reserved": {"token": 1}})
    with pytest.raises(PermissionError, match="evidence|hold"):
        network_sql_stores().truncate_audit_before(2)
    assert store.audit_count() == 3


def test_eligible_nonproduction_prefix_retention_updates_usage_preserves_head(network_sql_stores, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    store = network_sql_stores()
    cap, log = AuditTrustStore(store), AuditLog(store)
    for _ in range(3):
        record(log)
    head = log.head_hash()
    before = cap.capacity()
    assert store.truncate_audit_before(2) == 2
    assert cap.capacity()["used_records"] == 1
    assert cap.capacity()["used_bytes"] < before["used_bytes"]
    assert log.head_hash() == head
    assert log.verify_durable()
    with pytest.raises(PermissionError, match="preserve.*head"):
        store.truncate_audit_before(3)
    next_entry = record(log)
    assert next_entry.seq == 3
    assert next_entry.prev_hash == head


@pytest.mark.parametrize("environment", ["prod", "production"])
def test_production_retention_remains_disabled_under_capacity(network_sql_stores, monkeypatch, environment):
    store = network_sql_stores()
    record(AuditLog(store))
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    with pytest.raises(PermissionError, match="production audit retention"):
        store.truncate_audit_before(1)
    assert AuditTrustStore(store).capacity()["used_records"] == 1


def test_bootstrap_refuses_nullable_capacity_metadata(network_sql_stores):
    store = network_sql_stores()
    execute(store, "DROP TABLE audit_capacity_policy_v1")
    execute(store, "CREATE TABLE audit_capacity_policy_v1 (singleton INTEGER PRIMARY KEY,version INTEGER,"
            "max_records BIGINT,max_bytes BIGINT,max_entry_bytes BIGINT,used_records BIGINT,used_bytes BIGINT)")
    with pytest.raises(AuditCapacityDenied, match="schema"):
        network_sql_stores()


def test_old_unaccounted_row_update_still_obeys_entry_bound(tmp_path):
    path = str(tmp_path / "unaccounted-update.sqlite")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE audit(seq INTEGER PRIMARY KEY,entry TEXT NOT NULL)")
    old.execute("INSERT INTO audit VALUES(0,'{}')")
    old.commit()
    old.close()
    store = SqliteStore(path)
    try:
        with pytest.raises(Exception, match="audit capacity"):
            execute(store, "UPDATE audit SET entry=? WHERE seq=0", ('{"payload":"' + "x" * 20000 + '"}',))
        assert execute(store, "SELECT entry FROM audit").fetchone()["entry"] == '{}'
    finally:
        store.close()


def test_raw_update_exact_byte_accounting_and_overflow_rollback(network_sql_stores):
    store = network_sql_stores()
    cap = AuditTrustStore(store)
    cap.set_capacity(max_records=10, max_bytes=100, max_entry_bytes=100)
    execute(store, "INSERT INTO audit VALUES(0,?)", ('{"p":"é"}',))
    raw = '{"p":"漢字"}'
    execute(store, "UPDATE audit SET entry=? WHERE seq=0", (raw,))
    assert cap.capacity()["used_bytes"] == len(raw.encode())
    before = cap.capacity()
    with pytest.raises(Exception, match="audit capacity"):
        execute(store, "UPDATE audit SET entry=? WHERE seq=0", ("x" * 101,))
    assert execute(store, "SELECT entry FROM audit").fetchone()["entry"] == raw
    assert cap.capacity() == before


def test_raw_concurrent_direct_writers_cannot_overrun_capacity(network_sql_stores):
    stores = network_sql_stores(), network_sql_stores()
    cap = AuditTrustStore(stores[0])
    cap.set_capacity(max_records=9, max_bytes=4096, max_entry_bytes=1024)
    def insert_many(store, offset):
        outcomes = []
        # Each worker owns one independent connection and commits its own
        # transaction. Arbitrary threadpool jobs must not concurrently use the
        # same raw sqlite connection or mistake execute replies for commits.
        for seq in range(offset, 16, 2):
            try:
                with sql_atomic(store):
                    execute(store, "INSERT INTO audit VALUES(?,?)", (seq, '{"test":true}'))
                outcomes.append(True)
            except Exception as error:
                assert "audit capacity" in str(error)
                outcomes.append(False)
        return outcomes
    with ThreadPoolExecutor(max_workers=2) as pool:
        workers = [pool.submit(insert_many, store, offset) for offset, store in enumerate(stores)]
        outcomes = [outcome for worker in workers for outcome in worker.result(timeout=30)]
    assert sum(outcomes) == 9
    assert stores[0].audit_count() == 9
    assert cap.capacity()["used_records"] == 9
    assert cap.capacity()["used_bytes"] == 9 * len('{"test":true}'.encode())


def test_worker_connection_opened_before_upgrade_still_obeys_sql_capacity(tmp_path):
    path = str(tmp_path / "old-worker.sqlite")
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("CREATE TABLE audit(seq INTEGER PRIMARY KEY,entry TEXT NOT NULL)")
    old.execute("INSERT INTO audit VALUES(0,'{}')")
    store = SqliteStore(path)
    try:
        cap = AuditTrustStore(store)
        cap.set_capacity(max_records=2, max_bytes=4096, max_entry_bytes=1024)
        old.execute("INSERT INTO audit VALUES(1,'{}')")
        with pytest.raises(Exception, match="audit capacity"):
            old.execute("INSERT INTO audit VALUES(2,'{}')")
        assert cap.capacity()["used_records"] == 2
        assert cap.capacity()["used_bytes"] == 4
    finally:
        old.close()
        store.close()


def test_capacity_policy_cannot_be_deleted_or_reset_on_restart(network_sql_stores):
    store = network_sql_stores()
    cap = AuditTrustStore(store)
    cap.set_capacity(max_records=3, max_bytes=4096, max_entry_bytes=1024)
    with pytest.raises(Exception, match="cannot be deleted"):
        execute(store, "DELETE FROM audit_capacity_policy_v1")
    assert AuditTrustStore(network_sql_stores()).capacity() == cap.capacity()


def test_unsupported_policy_version_cannot_append_or_be_silently_replaced(network_sql_stores):
    store = network_sql_stores()
    cap = AuditTrustStore(store)
    cap.capacity()
    execute(store, "UPDATE audit_capacity_policy_v1 SET version=2")
    with pytest.raises(Exception, match="audit capacity policy"):
        store.append_audit({"seq": 0})
    with pytest.raises(AuditCapacityDenied, match="unsupported"):
        cap.set_capacity(max_records=5, max_bytes=4096, max_entry_bytes=1024)
    assert execute(store, "SELECT version FROM audit_capacity_policy_v1").fetchone()["version"] == 2
    assert store.audit_count() == 0


def test_postgres_raw_insert_fences_before_unique_sequence_ownership(network_sql_stores):
    first, raw, observer = network_sql_stores(), network_sql_stores(), network_sql_stores()
    if not isinstance(first, PostgresStore):
        pytest.skip("PostgreSQL index/advisory lock ordering only")
    def insert():
        try:
            with sql_atomic(raw):
                execute(raw, "INSERT INTO audit VALUES(0,?)", ('{"seq":0}',))
            return "inserted"
        except Exception as error:
            return type(error).__name__
    raw_pid = execute(raw, "SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    first_pid = execute(first, "SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with sql_atomic(first):
            execute(first, "SELECT pg_advisory_xact_lock(?)", (911001,))
            future = pool.submit(insert)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                blocked = execute(observer, "SELECT pg_blocking_pids(?) AS pids", (raw_pid,)).fetchone()["pids"]
                if first_pid in blocked:
                    break
                time.sleep(.01)
            else:
                pytest.fail("raw worker was not proven waiting for managed audit owner")
            # The raw worker must not already own seq=0's unique index entry.
            # No automatic replay is used to hide a deadlock victim.
            record(AuditLog(first))
        assert future.result(timeout=10) == "UniqueViolation"
    assert first.audit_count() == 1
    assert AuditLog(first).verify_durable()


def test_privileged_raw_delete_is_an_explicit_retention_boundary(network_sql_stores, monkeypatch):
    """The capacity trigger is not a raw-SQL retention authorization engine."""
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    store = network_sql_stores()
    cap = AuditTrustStore(store)
    log = AuditLog(store)
    for _ in range(3):
        record(log)
    ledger = OperationLedger(store)
    ledger.claim("agent", "operation", "fingerprint")
    with pytest.raises(PermissionError, match="operation evidence"):
        store.truncate_audit_before(1)
    execute(store, "DELETE FROM audit WHERE seq=0")
    assert ledger.get("agent", "operation")["state"] == "unknown"
    assert cap.capacity()["used_records"] == 2
    # This deliberately records the limitation, not production acceptance.
    assert not AuditLog.verify_chain(store.load_audit(), require_genesis=True)


def test_older_sqlite_replace_worker_cannot_evict_or_drift_capacity(tmp_path):
    path = str(tmp_path / "old-replace-worker.sqlite")
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("CREATE TABLE audit(seq INTEGER PRIMARY KEY,entry TEXT NOT NULL)")
    old.execute("INSERT INTO audit VALUES(0,'{}')")
    store = SqliteStore(path)
    try:
        cap = AuditTrustStore(store)
        before = cap.capacity()
        assert old.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
        with pytest.raises(Exception, match="replacement forbidden"):
            old.execute("INSERT OR REPLACE INTO audit VALUES(0,'{\"overwrite\":true}')")
        assert old.execute("SELECT entry FROM audit").fetchone()[0] == '{}'
        assert cap.capacity() == before
    finally:
        old.close()
        store.close()


@pytest.mark.parametrize("change", ["extra-nullable", "missing-key", "wrong-key", "extra-unique"])
def test_postgres_bootstrap_refuses_unsupported_capacity_key_or_columns(network_sql_stores, change):
    store = network_sql_stores()
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL exact metadata key qualification only")
    if change == "extra-nullable":
        execute(store, "ALTER TABLE audit_capacity_policy_v1 ADD COLUMN unexpected TEXT")
    elif change == "extra-unique":
        execute(store, "CREATE UNIQUE INDEX audit_capacity_extra_unique ON audit_capacity_policy_v1(version)")
    else:
        execute(store, "ALTER TABLE audit_capacity_policy_v1 DROP CONSTRAINT audit_capacity_policy_v1_pkey")
        if change == "wrong-key":
            execute(store, "ALTER TABLE audit_capacity_policy_v1 ADD PRIMARY KEY(version)")
    with pytest.raises(AuditCapacityDenied, match="schema"):
        network_sql_stores()


@pytest.mark.parametrize("counter", ["used_records", "used_bytes"])
def test_restart_refuses_inconsistent_persisted_counter_without_reset(network_sql_stores, counter):
    store = network_sql_stores()
    record(AuditLog(store))
    execute(store, "UPDATE audit_capacity_policy_v1 SET " + counter + "=0")
    before = dict(execute(store, "SELECT * FROM audit_capacity_policy_v1").fetchone())
    with pytest.raises(AuditCapacityDenied, match="counters.*history"):
        network_sql_stores()
    assert dict(execute(store, "SELECT * FROM audit_capacity_policy_v1").fetchone()) == before
    assert store.audit_count() == 1
