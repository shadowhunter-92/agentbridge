"""TEMP embedding cannot redirect the existing nonproduction retention API."""

import sqlite3

import pytest

from src.governance.audit import AuditLog
from src.governance.audit_trust import AuditTrustStore
from src.governance.checkpoint_capacity import CheckpointCapacityDenied
from src.governance.operation_ledger import OperationLedger
from src.governance.store import PostgresStore, SqliteStore, sql_atomic
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.protocols.task_lifecycle import TaskLifecycle
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import accepted
from tests.test_task_admission import admit
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


RETENTION_NAMES = (
    "audit", "audit_holds", "agent_operations", "task_operation_links_v1",
    "budgets", "task_lifecycle_snapshots",
)


def seed(store, name):
    """Real store APIs supply each blocker except the link-existence sentinel."""
    AuditTrustStore(store)
    for _ in range(3):
        AuditLog(store).record(actor="worker", action="test", source_protocol="mcp",
                              target_protocol="mcp", capability="read", decision="allow")
    if name == "audit_holds":
        AuditTrustStore(store).set_hold("case", True)
    elif name == "agent_operations":
        OperationLedger(store).claim("worker", "operation", "fingerprint")
    elif name == "budgets":
        store.upsert_budget("worker", {"spent": 0, "reserved": {"exact-token": 1}})
    elif name == "task_lifecycle_snapshots":
        DurableTaskLifecycle(store).create("owner", TaskLifecycle("task", "context", "agentbridge"))
    elif name == "task_operation_links_v1":
        # Retention's existing predicate protects ANY row, without interpreting
        # a receipt. This sentinel tests that predicate, not queued admission.
        store._db.execute("CREATE TABLE IF NOT EXISTS task_operation_links_v1(record TEXT NOT NULL)")
        store._db.execute("INSERT INTO task_operation_links_v1 VALUES('retained-link')")


def snapshot(store):
    """Read the durable namespace explicitly, never the TEMP mask."""
    if isinstance(store, PostgresStore):
        from psycopg import sql

        schema = store._db.execute("SELECT current_schema() AS schema").fetchone()["schema"]
        names = [row["tablename"] for row in store._db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (schema,)
        )]
        return {name: sorted((tuple(row.values()) for row in store._db.execute(
            sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(name))
        )), key=repr) for name in names}
    names = [row["name"] for row in store._db.execute(
        "SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    return {name: sorted((tuple(row) for row in store._db.execute(
        'SELECT * FROM main."' + name.replace('"', '""') + '"'
    )), key=repr) for name in names}


def shadow(store, name, spelling, kind):
    if isinstance(store, PostgresStore):
        from psycopg import sql

        schema = store._db.execute("SELECT current_schema() AS schema").fetchone()["schema"]
        store._db.execute(sql.SQL("CREATE TEMP " + ("TABLE" if kind == "table" else "VIEW") +
                                  " {} AS SELECT * FROM {}.{} WHERE false").format(
            sql.Identifier(spelling(name)), sql.Identifier(schema), sql.Identifier(name)
        ))
        return
    alias = '"' + spelling(name) + '"'
    if kind == "table":
        store._db.execute("CREATE TEMP TABLE " + alias + " AS SELECT * FROM main." + name + " WHERE 0")
    else:
        store._db.execute("CREATE TEMP VIEW " + alias + " AS SELECT * FROM main." + name + " WHERE 0")


@pytest.mark.parametrize("name", RETENTION_NAMES)
@pytest.mark.parametrize("spelling", [str.lower, str.upper, str.title], ids=["lower", "upper", "mixed"])
@pytest.mark.parametrize("kind", ["table", "view"])
def test_sqlite_retention_refuses_temp_masks_before_durable_reads(tmp_path, monkeypatch, name, spelling, kind):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    store = SqliteStore(str(tmp_path / "retention.sqlite"))
    try:
        seed(store, name)
        before = snapshot(store)
        if name != "audit":
            with pytest.raises(PermissionError, match="evidence|hold"):
                store.truncate_audit_before(2)
        shadow(store, name, spelling, kind)
        with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
            store.truncate_audit_before(2)
        assert snapshot(store) == before
        assert store._db.execute("SELECT count(*) AS n FROM temp." + spelling(name)).fetchone()["n"] == 0
    finally:
        store.close()


@pytest.mark.parametrize("environment", ["prod", "production"])
def test_production_refusal_precedes_temp_namespace_checks(tmp_path, monkeypatch, environment):
    store = SqliteStore(str(tmp_path / "production.sqlite"))
    try:
        seed(store, "audit_holds")
        before = snapshot(store)
        shadow(store, "audit_holds", str.upper, "table")
        monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
        with pytest.raises(PermissionError, match="production audit retention"):
            store.truncate_audit_before(2)
        assert snapshot(store) == before
    finally:
        store.close()


def test_namespace_denial_preserves_outer_transaction_and_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    store = SqliteStore(str(tmp_path / "outer.sqlite"))
    try:
        seed(store, "agent_operations")
        before = snapshot(store)
        shadow(store, "agent_operations", str.title, "view")
        with pytest.raises(RuntimeError, match="abort outer"):
            with sql_atomic(store):
                store.upsert_identity("marker", "before-denial")
                with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
                    store.truncate_audit_before(2)
                store.upsert_identity("marker", "after-denial")
                assert store.get_identity("marker")["public_key_hex"] == "after-denial"
                raise RuntimeError("abort outer")
        assert snapshot(store) == before
        assert store.get_identity("marker") is None
    finally:
        store.close()


@pytest.mark.parametrize("name", RETENTION_NAMES)
@pytest.mark.parametrize("spelling", [str.upper, str.title], ids=["upper", "mixed"])
def test_sqlite_retention_refuses_main_case_alias_before_reference_reads(tmp_path, monkeypatch, name, spelling):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    path = tmp_path / "main-alias.sqlite"
    shapes = {
        "audit": "(seq INTEGER PRIMARY KEY,entry TEXT NOT NULL)",
        "audit_holds": "(name TEXT PRIMARY KEY,enabled INTEGER NOT NULL)",
        "agent_operations": "(agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,"
                            "state TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(agent_id,operation_id))",
        "task_operation_links_v1": "(record TEXT NOT NULL)",
        "budgets": "(agent_id TEXT PRIMARY KEY,state TEXT NOT NULL)",
        "task_lifecycle_snapshots": "(owner_id TEXT NOT NULL,task_id TEXT NOT NULL,snapshot TEXT NOT NULL,"
                                    "terminal INTEGER NOT NULL,PRIMARY KEY(owner_id,task_id))",
    }
    # Emulate a preexisting case-variant namespace; do not rewrite a live
    # runtime table or disable its installed guards to arrange the test.
    with sqlite3.connect(path) as legacy:
        legacy.execute("CREATE TABLE " + spelling(name) + shapes[name])
    store = SqliteStore(str(path))
    try:
        seed(store, name)
        before = snapshot(store)
        assert len(before[spelling(name)]) > 0
        with pytest.raises(CheckpointCapacityDenied, match="noncanonical"):
            store.truncate_audit_before(2)
        assert snapshot(store) == before
        if name == "audit_holds":
            assert AuditTrustStore(store).holds() == ["case"]
        elif name == "agent_operations":
            assert OperationLedger(store).get("worker", "operation")["state"] == "unknown"
        elif name == "budgets":
            assert store.get_budget("worker")["reserved"] == {"exact-token": 1}
    finally:
        store.close()


@pytest.mark.parametrize("name", RETENTION_NAMES)
@pytest.mark.parametrize("kind", ["table", "view"])
def test_postgres_retention_refuses_temp_masks_before_durable_reads(network_sql_stores, monkeypatch, name, kind):
    store = network_sql_stores()
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL TEMP relation boundary; SQLite cases have a separate case-folding matrix")
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    seed(store, name)
    before = snapshot(store)
    if name != "audit":
        with pytest.raises(PermissionError, match="evidence|hold"):
            store.truncate_audit_before(2)
    shadow(store, name, str.lower, kind)
    with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
        store.truncate_audit_before(2)
    assert snapshot(store) == before
    assert store._db.execute("SELECT count(*) AS n FROM pg_temp." + name).fetchone()["n"] == 0


@pytest.mark.parametrize("kind", ["table", "view"])
def test_real_queued_admission_retention_denial_keeps_all_governance_state(queued_app, monkeypatch, kind):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    runtime = queued_app[0]._runtimes["alpha"]
    if isinstance(runtime.store, PostgresStore):
        pytest.skip("bound PostgreSQL tenant roles forbid TEMP; privileged embedding uses the separate matrix")
    session, record, _, _ = accepted(queued_app)
    receipt = admit(queued_app, session, record)
    store = runtime.store
    trust = AuditTrustStore(store)
    trust.set_hold("admitted-case", True)
    before = snapshot(store)
    shadow(store, "task_operation_links_v1", str.lower, kind)
    with pytest.raises(CheckpointCapacityDenied, match="TEMP"):
        store.truncate_audit_before(2)
    assert snapshot(store) == before
    assert runtime.operations.get("worker", receipt["operation_id"])["state"] == "unknown"
    assert store.get_budget("worker")["reserved"] == {receipt["reservation_token"]: 1.0}
    assert trust.holds() == ["admitted-case"]
    assert session.task("native-task").sequence == 1
