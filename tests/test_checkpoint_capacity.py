"""Actual checkpoint SQL bounds; no external custody or production acceptance."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.audit import AuditLog
from src.governance.audit_trust import AuditTrustError, AuditTrustStore
from src.governance.checkpoint_capacity import CheckpointCapacityDenied, CheckpointLimits
from src.governance.identity import AgentIdentity
from src.governance.store import PostgresStore, SqliteStore, sql_atomic


def error(store):
    if isinstance(store, SqliteStore):
        return sqlite3.DatabaseError
    import psycopg
    return psycopg.Error


def execute(store, sql, args=()):
    return store._db.execute(sql.replace("?", "%s") if isinstance(store, PostgresStore) else sql, args)


def checkpoints(store, n=3):
    log = AuditLog(store)
    signer = AgentIdentity.generate("checkpoint-fixture")
    result = [log.checkpoint(signer.sign, signer.public_key_hex)]
    for _ in range(n):
        log.record(actor="fixture", action="record", source_protocol="test", target_protocol="test", capability="read", decision="allow")
        result.append(log.checkpoint(signer.sign, signer.public_key_hex))
    return result, signer


def rows(store):
    return [dict(row) for row in store._db.execute("SELECT seq,data FROM audit_checkpoints ORDER BY seq").fetchall()]


def test_large_signed_extension_rejected_without_partial_policy(network_sql_stores):
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    values, signer = checkpoints(store)
    value = {**values[1], "extension": "\u00e9" * 10_000}
    assert AuditLog.verify_checkpoint(value)
    assert len(json.dumps(value, sort_keys=True).encode()) > 8192
    with pytest.raises(error(store), match="checkpoint capacity"):
        trust.save_checkpoint(value, signer.public_key_hex)
    assert rows(store) == []
    assert store._db.execute("SELECT count(*) AS n FROM checkpoint_capacity_policy_v1").fetchone()["n"] == 0
    assert trust.save_checkpoint(values[1], signer.public_key_hex) == 1
    assert trust.checkpoint_capacity()["used_records"] == 1


def test_existing_signature_genesis_head_and_duplicate_contract(network_sql_stores):
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    values, signer = checkpoints(store)
    with pytest.raises(AuditTrustError, match="pinned"):
        trust.save_checkpoint(values[1], "00" * 32)
    with pytest.raises(AuditTrustError, match="signature"):
        trust.save_checkpoint({**values[1], "head_hash": "00" * 32}, signer.public_key_hex)
    # A valid signature for another history is still insufficient.
    forged = {**values[1], "head_hash": "11" * 32}
    forged["signature_hex"] = signer.sign(AuditLog._checkpoint_payload(1, forged["head_hash"])).hex()
    with pytest.raises(AuditTrustError, match="stored audit history"):
        trust.save_checkpoint(forged, signer.public_key_hex)
    assert trust.save_checkpoint(values[0], signer.public_key_hex) == 0
    assert trust.save_checkpoint(values[1], signer.public_key_hex) == 1
    before = rows(store)
    with pytest.raises(error(store)):
        trust.save_checkpoint(values[1], signer.public_key_hex)
    assert rows(store) == before


@pytest.mark.parametrize("limits", [
    dict(max_records=0), dict(max_records=True), dict(max_records=1.0), dict(max_records=100001),
    dict(max_bytes=0), dict(max_bytes=134217729), dict(max_entry_bytes=65537),
    dict(max_bytes=1, max_entry_bytes=2),
])
def test_invalid_configuration(limits):
    with pytest.raises(CheckpointCapacityDenied):
        CheckpointLimits(**limits)


@pytest.mark.parametrize("boundary", ["count", "bytes", "entry"])
def test_direct_sql_exact_utf8_bounds(network_sql_stores, boundary):
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    trust.set_checkpoint_capacity(max_records=2, max_bytes=20, max_entry_bytes=10)
    execute(store, "INSERT INTO audit_checkpoints VALUES(?,?)", (0, "\u00e9" * 5))
    if boundary == "entry":
        candidate = "\u00e9" * 5 + "x"
    elif boundary == "bytes":
        execute(store, "INSERT INTO audit_checkpoints VALUES(?,?)", (1, "\u00e9" * 5))
        # Raise row allowance so this failure isolates byte saturation.
        trust.set_checkpoint_capacity(max_records=3, max_bytes=20, max_entry_bytes=10)
        candidate = "x"
    else:
        execute(store, "INSERT INTO audit_checkpoints VALUES(?,?)", (1, "x"))
        candidate = "x"
    before = trust.checkpoint_capacity()
    with pytest.raises(error(store), match="checkpoint capacity"):
        execute(store, "INSERT INTO audit_checkpoints VALUES(?,?)", (2, candidate))
    assert trust.checkpoint_capacity() == before
    assert before["used_bytes"] == sum(len(row["data"].encode()) for row in rows(store))


@pytest.mark.parametrize("operation", ["update", "delete", "replace"])
def test_registry_is_append_only_at_sql_boundary(network_sql_stores, operation):
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    execute(store, "INSERT INTO audit_checkpoints VALUES(?,?)", (0, "original"))
    before = trust.checkpoint_capacity()
    sql = {"update": "UPDATE audit_checkpoints SET data='changed' WHERE seq=0",
           "delete": "DELETE FROM audit_checkpoints WHERE seq=0"}[operation] if operation != "replace" else (
        "INSERT OR REPLACE INTO audit_checkpoints VALUES(0,'changed')" if isinstance(store, SqliteStore)
        else "INSERT INTO audit_checkpoints VALUES(0,'changed') ON CONFLICT(seq) DO UPDATE SET data=excluded.data")
    with pytest.raises(error(store)):
        execute(store, sql)
    assert rows(store) == [{"seq": 0, "data": "original"}]
    assert trust.checkpoint_capacity() == before


def test_cold_old_writer_and_history_above_new_limits(tmp_path):
    path = str(tmp_path / "cold.sqlite")
    old = SqliteStore(path)
    old._db.execute("CREATE TABLE audit_checkpoints (seq INTEGER PRIMARY KEY,data TEXT NOT NULL)")
    old._db.execute("INSERT INTO audit_checkpoints VALUES(0,?)", ("x" * 10000,))
    current = SqliteStore(path)
    try:
        trust = AuditTrustStore(current)
        assert current._db.execute("SELECT count(*) AS n FROM checkpoint_capacity_policy_v1").fetchone()["n"] == 0
        with pytest.raises(sqlite3.DatabaseError):
            old._db.execute("UPDATE audit_checkpoints SET data=?", ("y" * 20000,))
        with pytest.raises(sqlite3.DatabaseError):
            old._db.execute("INSERT INTO audit_checkpoints VALUES(1,?)", ("y" * 20000,))
        assert current._db.execute("SELECT count(*) AS n FROM checkpoint_capacity_policy_v1").fetchone()["n"] == 0
        before = rows(current)
        result = trust.set_checkpoint_capacity(max_records=1, max_bytes=100, max_entry_bytes=50)
        assert result["used_records"] == 1 and result["used_bytes"] == 10000
        with pytest.raises(sqlite3.DatabaseError, match="capacity"):
            old._db.execute("INSERT INTO audit_checkpoints VALUES(1,'small')")
        assert rows(current) == before
    finally:
        current.close()
        old.close()


def test_outer_transaction_and_policy_audit_failure_rollback(network_sql_stores):
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    values, signer = checkpoints(store)
    before = trust.checkpoint_capacity()
    with pytest.raises(RuntimeError, match="boundary"):
        with sql_atomic(store):
            trust.save_checkpoint(values[1], signer.public_key_hex)
            raise RuntimeError("boundary")
    assert rows(store) == [] and trust.checkpoint_capacity() == before
    def fail():
        raise RuntimeError("audit callback failed")
    with pytest.raises(RuntimeError, match="audit callback"):
        trust.set_checkpoint_capacity(max_records=1, max_bytes=5000, max_entry_bytes=500, audit=fail)
    assert trust.checkpoint_capacity() == before
    assert len(store.load_audit()) == 3


def test_concurrent_independent_workers_cannot_overrun(network_sql_stores):
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    values, signer = checkpoints(store, n=12)
    trust.set_checkpoint_capacity(max_records=9, max_bytes=20000, max_entry_bytes=1000)
    barrier = threading.Barrier(12)
    def worker(value):
        own = network_sql_stores()
        authority = AuditTrustStore(own)
        barrier.wait(timeout=15)
        try:
            authority.save_checkpoint(value, signer.public_key_hex)
            return True
        except error(own) as exc:
            assert "capacity" in str(exc)
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(worker, values[:12]))
    assert results.count(True) == 9 and results.count(False) == 3
    actual = rows(store)
    usage = trust.checkpoint_capacity()
    assert len(actual) == usage["used_records"] == 9
    assert usage["used_bytes"] == sum(len(row["data"].encode()) for row in actual)
    assert len({row["seq"] for row in actual}) == 9


def test_sqlite_validation_and_insert_share_write_transaction(tmp_path, monkeypatch):
    path = str(tmp_path / "linear.sqlite")
    a, b = SqliteStore(path), SqliteStore(path)
    try:
        trust = AuditTrustStore(a)
        values, signer = checkpoints(a)
        original = a.load_audit
        b._db.execute("PRAGMA busy_timeout=0")
        def observed():
            assert a._db.in_transaction
            result = original()
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                b._db.execute("BEGIN IMMEDIATE")
            return result
        monkeypatch.setattr(a, "load_audit", observed)
        trust.save_checkpoint(values[1], signer.public_key_hex)
        b._db.execute("BEGIN IMMEDIATE")
        b._db.execute("ROLLBACK")
        assert len(rows(a)) == 1
    finally:
        b.close()
        a.close()


@pytest.mark.parametrize("kind", ["extra_nullable", "missing_primary", "wrong_primary", "extra_unique"])
def test_sqlite_unsupported_schema_is_preserved_and_rejected(tmp_path, kind):
    store = SqliteStore(str(tmp_path / (kind + ".sqlite")))
    definitions = {
        "extra_nullable": "seq INTEGER PRIMARY KEY,data TEXT NOT NULL,extra TEXT",
        "missing_primary": "seq INTEGER,data TEXT NOT NULL",
        "wrong_primary": "seq INTEGER NOT NULL,data TEXT PRIMARY KEY",
        "extra_unique": "seq INTEGER PRIMARY KEY,data TEXT NOT NULL UNIQUE",
    }
    try:
        store._db.execute("CREATE TABLE audit_checkpoints (" + definitions[kind] + ")")
        store._db.execute("INSERT INTO audit_checkpoints(seq,data) VALUES(0,'preserve')")
        with pytest.raises(CheckpointCapacityDenied):
            AuditTrustStore(store)
        assert rows(store) == [{"seq": 0, "data": "preserve"}]
        assert store._db.execute("SELECT name FROM sqlite_master WHERE name='checkpoint_capacity_policy_v1'").fetchone() is None
    finally:
        store.close()


def test_complete_sqlite_restore_keeps_policy_history_and_holds(tmp_path):
    source = SqliteStore(str(tmp_path / "source.sqlite"))
    target_path = str(tmp_path / "restore.sqlite")
    try:
        trust = AuditTrustStore(source)
        values, signer = checkpoints(source)
        trust.save_checkpoint(values[1], signer.public_key_hex)
        trust.set_hold("preserved-hold", True)
        trust.set_checkpoint_capacity(max_records=1, max_bytes=4000, max_entry_bytes=1000)
        before_rows, before_policy = rows(source), trust.checkpoint_capacity()
        with sqlite3.connect(target_path) as restored:
            source._db.backup(restored)
    finally:
        source.close()
    restored = SqliteStore(target_path)
    try:
        trust = AuditTrustStore(restored)
        assert rows(restored) == before_rows
        assert trust.checkpoint_capacity() == before_policy
        assert trust.holds() == ["preserved-hold"]
        with pytest.raises(sqlite3.DatabaseError, match="capacity"):
            trust.save_checkpoint(values[2], signer.public_key_hex)
        assert rows(restored) == before_rows
    finally:
        restored.close()


def test_sqlite_modified_trigger_fails_closed_without_repair(tmp_path):
    store = SqliteStore(str(tmp_path / "modified.sqlite"))
    try:
        AuditTrustStore(store)
        store._db.execute("DROP TRIGGER checkpoint_capacity_insert_v1")
        bad = "CREATE TRIGGER checkpoint_capacity_insert_v1 AFTER INSERT ON audit_checkpoints BEGIN SELECT 1; END"
        store._db.execute(bad)
        with pytest.raises(CheckpointCapacityDenied, match="modified"):
            AuditTrustStore(store)
        assert store._db.execute("SELECT sql FROM sqlite_master WHERE name='checkpoint_capacity_insert_v1'").fetchone()["sql"] == bad
    finally:
        store.close()


def test_sqlite_generated_columns_and_missing_constraints_are_rejected(tmp_path):
    for kind in ("generated", "constraints"):
        store = SqliteStore(str(tmp_path / (kind + ".sqlite")))
        try:
            if kind == "generated":
                store._db.execute("CREATE TABLE audit_checkpoints(seq INTEGER PRIMARY KEY,data TEXT NOT NULL,extra TEXT GENERATED ALWAYS AS (data) VIRTUAL)")
            else:
                store._db.execute("CREATE TABLE checkpoint_capacity_policy_v1(singleton INTEGER PRIMARY KEY,version INTEGER NOT NULL,max_records BIGINT NOT NULL,max_bytes BIGINT NOT NULL,max_entry_bytes BIGINT NOT NULL)")
            with pytest.raises(CheckpointCapacityDenied):
                AuditTrustStore(store)
        finally:
            store.close()


def test_sqlite_utf16_storage_is_preserved_but_not_miscounted(tmp_path):
    path = str(tmp_path / "utf16.sqlite")
    with sqlite3.connect(path) as seed:
        seed.execute("PRAGMA encoding='UTF-16'")
        seed.execute("CREATE TABLE audit_checkpoints(seq INTEGER PRIMARY KEY,data TEXT NOT NULL)")
        seed.execute("INSERT INTO audit_checkpoints VALUES(0,'retain')")
    store = SqliteStore(path)
    try:
        with pytest.raises(CheckpointCapacityDenied, match="UTF-8"):
            AuditTrustStore(store)
        assert rows(store) == [{"seq": 0, "data": "retain"}]
    finally:
        store.close()


def test_sqlite_policy_replace_is_rejected_and_restart_preserves_limits(tmp_path):
    path = str(tmp_path / "policy.sqlite")
    store = SqliteStore(path)
    try:
        trust = AuditTrustStore(store)
        before = trust.set_checkpoint_capacity(max_records=7, max_bytes=2000, max_entry_bytes=500)
        with pytest.raises(sqlite3.DatabaseError):
            store._db.execute("INSERT OR REPLACE INTO checkpoint_capacity_policy_v1 VALUES(1,1,10000,16777216,8192)")
        assert trust.checkpoint_capacity() == before
    finally:
        store.close()
    store = SqliteStore(path)
    try:
        assert AuditTrustStore(store).checkpoint_capacity() == before
    finally:
        store.close()


def test_tenant_binding_covers_new_registry_and_policy(tmp_path):
    from src.governance.tenant_store import TenantSqliteStore
    path = str(tmp_path / "tenant.sqlite")
    current = TenantSqliteStore(path, tenant_id="alpha")
    old = SqliteStore(path)
    try:
        trust = AuditTrustStore(current)
        values, signer = checkpoints(current)
        assert trust.save_checkpoint(values[1], signer.public_key_hex) == 1
        before = rows(current), trust.checkpoint_capacity()
        with pytest.raises(sqlite3.DatabaseError, match="tenant"):
            old._db.execute("INSERT INTO audit_checkpoints VALUES(99,'old')")
        with pytest.raises(sqlite3.DatabaseError, match="tenant"):
            old._db.execute("UPDATE checkpoint_capacity_policy_v1 SET max_records=1")
        assert (rows(current), trust.checkpoint_capacity()) == before
        assert current.tenant_id == "alpha"
    finally:
        old.close()
        current.close()


def test_saturation_preserves_unknown_reservation_hold_and_audit(network_sql_stores):
    from src.governance.operation_ledger import OperationLedger
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    values, signer = checkpoints(store)
    operations = OperationLedger(store)
    operations.claim("agent", "operation", "fingerprint", reservation_token="held")
    store.upsert_budget("agent", {"spent": 0, "reserved": {"held": 2}})
    trust.set_hold("preserve-uncertainty", True)
    trust.set_checkpoint_capacity(max_records=1, max_bytes=4000, max_entry_bytes=1000)
    trust.save_checkpoint(values[0], signer.public_key_hex)
    before = (operations.get("agent", "operation"), store.get_budget("agent"),
              trust.holds(), store.load_audit(), rows(store), trust.checkpoint_capacity())
    with pytest.raises(error(store), match="capacity"):
        trust.save_checkpoint(values[1], signer.public_key_hex)
    after = (operations.get("agent", "operation"), store.get_budget("agent"),
             trust.holds(), store.load_audit(), rows(store), trust.checkpoint_capacity())
    assert before == after
    assert after[0]["state"] == "unknown" and after[1]["reserved"] == {"held": 2}
    with pytest.raises(PermissionError, match="hold"):
        store.truncate_audit_before(1)


def test_real_audit_saturation_rolls_back_checkpoint_policy(network_sql_stores):
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    checkpoints(store)
    cap = trust.capacity()
    trust.set_capacity(max_records=3, max_bytes=cap["max_bytes"], max_entry_bytes=cap["max_entry_bytes"])
    before = trust.checkpoint_capacity(), store.load_audit()
    audit = AuditLog(store)
    def record():
        audit.record(actor="operator", action="set_checkpoint_capacity", source_protocol="control", target_protocol="control", capability="audit.capacity", decision="allow")
    with pytest.raises(error(store), match="audit capacity"):
        trust.set_checkpoint_capacity(max_records=1, max_bytes=2000, max_entry_bytes=500, audit=record)
    assert (trust.checkpoint_capacity(), store.load_audit()) == before
    assert len(audit.entries()) == 3


@pytest.mark.parametrize("payload", [None, b"not-text"])
def test_sqlite_invalid_direct_payload_cannot_materialize_policy(tmp_path, payload):
    store = SqliteStore(str(tmp_path / "types.sqlite"))
    try:
        AuditTrustStore(store)
        with pytest.raises(sqlite3.DatabaseError):
            store._db.execute("INSERT INTO audit_checkpoints VALUES(0,?)", (payload,))
        assert rows(store) == []
        assert store._db.execute("SELECT count(*) AS n FROM checkpoint_capacity_policy_v1").fetchone()["n"] == 0
    finally:
        store.close()


@pytest.mark.parametrize("shape", ["extra_nullable", "missing_primary", "wrong_primary", "extra_unique", "missing_checks", "column_default"])
def test_postgres_unsupported_policy_schema_is_refused(network_sql_stores, shape):
    store = network_sql_stores()
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL metadata schema contract")
    from src.governance.checkpoint_capacity import DDL
    sql = DDL
    if shape == "extra_nullable":
        sql = sql[:-1] + ",extra TEXT)"
    elif shape == "missing_primary":
        sql = sql.replace("singleton INTEGER PRIMARY KEY", "singleton INTEGER NOT NULL")
    elif shape == "wrong_primary":
        sql = sql.replace("singleton INTEGER PRIMARY KEY", "singleton INTEGER NOT NULL").replace("version INTEGER NOT NULL", "version INTEGER PRIMARY KEY")
    elif shape == "extra_unique":
        sql = sql.replace("max_records BIGINT NOT NULL", "max_records BIGINT NOT NULL UNIQUE")
    elif shape == "column_default":
        sql = sql.replace("version INTEGER NOT NULL", "version INTEGER NOT NULL DEFAULT 1")
    else:
        sql = sql.replace(" CHECK(version=1)", "")
    store._db.execute(sql)
    with pytest.raises(CheckpointCapacityDenied, match="schema|constraints|unique"):
        AuditTrustStore(store)
    assert store._db.execute("SELECT count(*) AS n FROM checkpoint_capacity_policy_v1").fetchone()["n"] == 0


@pytest.mark.parametrize("name", ["audit_checkpoints", "checkpoint_capacity_policy_v1"])
@pytest.mark.parametrize("surface", ["bootstrap", "save", "inspect", "configure"])
def test_sqlite_reserved_temp_names_cannot_redirect_durable_work(tmp_path, name, surface):
    store = SqliteStore(str(tmp_path / "shadow.sqlite"))
    try:
        values, signer = checkpoints(store)
        trust = None if surface == "bootstrap" else AuditTrustStore(store)
        def durable():
            result = {}
            for table in ("audit", "audit_holds", "audit_checkpoints", "checkpoint_capacity_policy_v1"):
                if store._db.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    result[table] = [tuple(row) for row in store._db.execute("SELECT * FROM main." + table).fetchall()]
            return result
        before = durable()
        store._db.execute("CREATE TEMP TABLE " + name + "(synthetic TEXT)")
        with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
            if surface == "bootstrap":
                AuditTrustStore(store)
            elif surface == "save":
                trust.save_checkpoint(values[1], signer.public_key_hex)
            elif surface == "inspect":
                trust.checkpoint_capacity()
            else:
                trust.set_checkpoint_capacity(max_records=1, max_bytes=4000, max_entry_bytes=1000)
        assert durable() == before
        assert store._db.execute("SELECT count(*) AS n FROM temp." + name).fetchone()["n"] == 0
    finally:
        store.close()


def test_sqlite_temp_audit_or_hold_dependency_is_refused(tmp_path):
    store = SqliteStore(str(tmp_path / "dependency.sqlite"))
    try:
        trust = AuditTrustStore(store)
        values, signer = checkpoints(store)
        store._db.execute("CREATE TEMP TABLE audit(entry TEXT)")
        with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
            trust.save_checkpoint(values[1], signer.public_key_hex)
        store._db.execute("DROP TABLE temp.audit")
        trust.set_hold("keep", True)
        store._db.execute("CREATE TEMP TABLE audit_holds(name TEXT,enabled INTEGER)")
        with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
            trust.holds()
        with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
            trust.set_hold("keep", False)
        assert [tuple(row) for row in store._db.execute("SELECT * FROM main.audit_holds")] == [("keep", 1)]
    finally:
        store.close()


@pytest.mark.parametrize("drift", ["body", "security-definer", "stable", "trigger-disabled", "trigger-missing", "trigger-timing"])
def test_postgres_restart_refuses_installed_drift_without_repair(network_sql_stores, drift):
    store = network_sql_stores()
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL installed routine/trigger drift")
    trust = AuditTrustStore(store)
    execute(store, "INSERT INTO audit_checkpoints VALUES(0,'retain')")
    commands = {
        "body": "CREATE OR REPLACE FUNCTION agentbridge_checkpoint_capacity_v1() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RETURN NULL; END $$",
        "security-definer": "ALTER FUNCTION agentbridge_checkpoint_capacity_v1() SECURITY DEFINER",
        "stable": "ALTER FUNCTION agentbridge_checkpoint_capacity_v1() STABLE",
        "trigger-disabled": "ALTER TABLE audit_checkpoints DISABLE TRIGGER checkpoint_capacity_insert_v1",
        "trigger-missing": "DROP TRIGGER checkpoint_capacity_insert_v1 ON audit_checkpoints",
    }
    if drift == "trigger-timing":
        store._db.execute("DROP TRIGGER checkpoint_capacity_insert_v1 ON audit_checkpoints")
        store._db.execute("CREATE TRIGGER checkpoint_capacity_insert_v1 BEFORE INSERT ON audit_checkpoints FOR EACH ROW EXECUTE FUNCTION agentbridge_checkpoint_capacity_v1()")
    else:
        store._db.execute(commands[drift])
    def definitions():
        functions = store._db.execute("SELECT p.proname,pg_get_functiondef(p.oid) AS definition FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname LIKE 'agentbridge_checkpoint_%' ORDER BY p.proname").fetchall()
        triggers = store._db.execute("SELECT g.tgname,g.tgenabled,pg_get_triggerdef(g.oid) AS definition FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=current_schema() AND t.relname='audit_checkpoints' ORDER BY g.tgname").fetchall()
        return [dict(row) for row in functions], [dict(row) for row in triggers]
    before = definitions(), rows(store), trust.checkpoint_capacity()
    restarted = network_sql_stores()
    with pytest.raises(CheckpointCapacityDenied):
        AuditTrustStore(restarted)
    assert (definitions(), rows(store), trust.checkpoint_capacity()) == before


def test_postgres_temp_checkpoint_cannot_redirect_durable_work(network_sql_stores):
    store = network_sql_stores()
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL TEMP embedding boundary")
    from psycopg import sql
    trust = AuditTrustStore(store)
    values, signer = checkpoints(store)
    schema = store._db.execute("SELECT current_schema() AS schema").fetchone()["schema"]
    store._db.execute("CREATE TEMP TABLE audit_checkpoints(seq BIGINT PRIMARY KEY,data TEXT NOT NULL)")
    denied, returned = False, None
    try:
        returned = trust.save_checkpoint(values[1], signer.public_key_hex)
    except CheckpointCapacityDenied:
        denied = True
    durable = store._db.execute(sql.SQL("SELECT count(*) AS n FROM {}.audit_checkpoints").format(sql.Identifier(schema))).fetchone()["n"]
    temporary = store._db.execute("SELECT count(*) AS n FROM pg_temp.audit_checkpoints").fetchone()["n"]
    assert denied, {"returned": returned, "durable_rows": durable, "temporary_rows": temporary}
    assert durable == temporary == 0


@pytest.mark.parametrize("name", ["audit_checkpoints", "checkpoint_capacity_policy_v1"])
@pytest.mark.parametrize("surface", ["bootstrap", "inspect", "configure"])
def test_postgres_reserved_temp_names_fail_before_changes(network_sql_stores, name, surface):
    store = network_sql_stores()
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL TEMP embedding boundary")
    from psycopg import sql
    checkpoints(store)
    trust = None if surface == "bootstrap" else AuditTrustStore(store)
    schema = store._db.execute("SELECT current_schema() AS schema").fetchone()["schema"]
    def durable():
        names = store._db.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=%s ORDER BY tablename", (schema,)).fetchall()
        return {row["tablename"]: [tuple(value.values()) for value in store._db.execute(sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(row["tablename"]))).fetchall()] for row in names}
    before = durable()
    store._db.execute(sql.SQL("CREATE TEMP TABLE {}(synthetic TEXT)").format(sql.Identifier(name)))
    with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
        if surface == "bootstrap":
            AuditTrustStore(store)
        elif surface == "inspect":
            trust.checkpoint_capacity()
        else:
            trust.set_checkpoint_capacity(max_records=1, max_bytes=4000, max_entry_bytes=1000)
    assert durable() == before


def test_policy_callback_temp_shadow_aborts_whole_configuration(network_sql_stores):
    store = network_sql_stores()
    trust = AuditTrustStore(store)
    before = trust.checkpoint_capacity()
    def callback():
        store._db.execute("CREATE TEMP TABLE checkpoint_capacity_policy_v1(synthetic TEXT)")
    with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
        trust.set_checkpoint_capacity(max_records=1, max_bytes=4000, max_entry_bytes=1000, audit=callback)
    assert trust.checkpoint_capacity() == before


@pytest.mark.parametrize("relation", ["ordinary", "audit_checkpoints", "checkpoint_capacity_policy_v1"])
def test_postgres_checkpoint_tables_require_ordinary_permanent_relations(network_sql_stores, relation):
    store = network_sql_stores()
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL relation durability catalog contract")
    from psycopg import sql

    from src.governance.operation_ledger import OperationLedger

    trust = AuditTrustStore(store)
    values, signer = checkpoints(store)
    trust.save_checkpoint(values[1], signer.public_key_hex)
    operations = OperationLedger(store)
    operations.claim("durability-agent", "durability-operation", "fingerprint", reservation_token="held-durability")
    store.upsert_budget("durability-agent", {"spent": 0, "reserved": {"held-durability": 2}})
    trust.set_hold("preserve-durability", True)

    def catalog():
        return [dict(row) for row in store._db.execute(
            "SELECT c.relname,c.relkind,c.relpersistence FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() AND c.relname=ANY(%s) ORDER BY c.relname",
            (["audit_checkpoints", "checkpoint_capacity_policy_v1"],),
        ).fetchall()]

    assert all(row["relkind"] == "r" and row["relpersistence"] == "p" for row in catalog())
    if relation == "ordinary":
        restarted = AuditTrustStore(network_sql_stores())
        assert restarted.save_checkpoint(values[2], signer.public_key_hex) == 2
        assert restarted.checkpoint_capacity()["used_records"] == 2
    else:
        # Disposable fixture namespace only. Inspect catalog persistence; never
        # restart or crash the shared PostgreSQL container to demonstrate loss.
        store._db.execute(sql.SQL("ALTER TABLE {} SET UNLOGGED").format(sql.Identifier(relation)))
        before = (catalog(), rows(store), [dict(row) for row in store._db.execute(
            "SELECT * FROM checkpoint_capacity_policy_v1").fetchall()], store.load_audit())
        assert next(row for row in before[0] if row["relname"] == relation)["relpersistence"] == "u"
        denied = False
        try:
            AuditTrustStore(network_sql_stores())
        except CheckpointCapacityDenied:
            denied = True
        after = (catalog(), rows(store), [dict(row) for row in store._db.execute(
            "SELECT * FROM checkpoint_capacity_policy_v1").fetchall()], store.load_audit())
        assert after == before
        assert denied, {"unsupported_relation": relation, "catalog": after[0],
                        "checkpoint_rows": len(after[1]), "library_bootstrap_accepted": True}
    assert trust.holds() == ["preserve-durability"]
    assert operations.get("durability-agent", "durability-operation")["state"] == "unknown"
    assert store.get_budget("durability-agent") == {"spent": 0, "reserved": {"held-durability": 2}}
