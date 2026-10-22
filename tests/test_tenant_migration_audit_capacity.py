"""Exact routine migration adapter and preserved audit resource metadata."""
import pytest

from src.governance.audit import AuditLog
from src.governance.audit_capacity import TABLE, qualified_postgres_routines
from src.governance.audit_trust import AuditTrustStore
from src.governance.operation_ledger import OperationLedger
from src.governance.store import PostgresStore
from src.governance.tenant_migration import TenantMigration, TenantMigrationDenied
from tests.test_authority import authority as authority
from tests.test_tenant_migration import backup_restore as backup_restore
from tests.test_tenant_migration import historical as historical
from tests.test_tenant_store import namespaces as namespaces


def policy_rows(store):
    return [dict(row) for row in store._db.execute("SELECT * FROM " + TABLE).fetchall()]


def assert_physical_usage(store):
    rows = policy_rows(store)
    size = "octet_length(entry)" if isinstance(store, PostgresStore) else "length(CAST(entry AS BLOB))"
    actual = store._db.execute("SELECT count(*) AS n,coalesce(sum(" + size + "),0) AS b FROM audit").fetchone()
    if rows:
        assert rows[0]["used_records"] == actual["n"]
        assert rows[0]["used_bytes"] == actual["b"]


@pytest.mark.parametrize("mode", ["initialized", "lazy", "over-limit"])
def test_real_restore_assignment_and_rollback_preserve_audit_capacity(
        authority, namespaces, historical, backup_restore, mode):
    source, identity, _, before = historical
    cap = AuditTrustStore(source)
    if mode == "lazy":
        # Simulate upgrading historical rows before the new resource metadata
        # has ever been materialized. Destructive DDL is fixture setup only.
        source._db.execute("DROP TABLE " + TABLE)
        source._init_schema()
        assert policy_rows(source) == []
    elif mode == "over-limit":
        cap.set_capacity(max_records=1, max_bytes=1, max_entry_bytes=1)
    else:
        cap.set_capacity(max_records=9, max_bytes=8192, max_entry_bytes=2048)
    expected_policy = policy_rows(source)
    expected_audit = source.load_audit()
    assert_physical_usage(source)
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    assert policy_rows(restored) == expected_policy
    assert restored.load_audit() == expected_audit
    assert_physical_usage(restored)
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    scoped = namespaces("alpha")
    assert policy_rows(scoped) == expected_policy
    assert_physical_usage(scoped)
    assert scoped.load_audit() == before["audit"] == expected_audit
    assert AuditTrustStore(scoped).holds() == ["historical-case"]
    assert OperationLedger(scoped).get(identity.agent_id, "historical-unknown-12345")["state"] == "unknown"
    assert migration.rollback(authority[1])["historical_rows_preserved"]
    assert policy_rows(source) == expected_policy
    assert source.load_audit() == expected_audit
    assert_physical_usage(source)
    state = cap.capacity()
    if mode == "lazy":
        assert state["used_records"] == len(expected_audit)
        assert state["used_bytes"] > 0
    elif mode == "over-limit":
        assert state["max_bytes"] == 1 < state["used_bytes"]
        with pytest.raises(Exception, match="audit capacity"):
            AuditLog(source).record(actor="worker", action="attempt", source_protocol="mcp", target_protocol="mcp",
                                    capability="read", decision="allow")
        assert policy_rows(source) == expected_policy
    else:
        assert state["max_records"] == 9


@pytest.mark.parametrize("change", ["body", "security-definer", "stable", "search-path", "strict", "parallel",
                                   "overload", "unknown-routine"])
def test_migration_refuses_modified_or_unknown_postgres_routines(authority, historical, change):
    source = historical[0]
    if not isinstance(source, PostgresStore):
        pytest.skip("PostgreSQL routine attributes only")
    function = "agentbridge_audit_capacity_fence_v1"
    commands = {
        "body": "CREATE OR REPLACE FUNCTION " + function + "() RETURNS trigger LANGUAGE plpgsql "
                "SET search_path=pg_catalog AS $$ BEGIN RETURN NULL; END $$",
        "security-definer": "ALTER FUNCTION " + function + "() SECURITY DEFINER",
        "stable": "ALTER FUNCTION " + function + "() STABLE",
        "search-path": "ALTER FUNCTION " + function + "() SET search_path=public",
        "strict": "ALTER FUNCTION " + function + "() STRICT",
        "parallel": "ALTER FUNCTION " + function + "() PARALLEL SAFE",
        "overload": "CREATE FUNCTION " + function + "(integer) RETURNS integer LANGUAGE sql AS 'SELECT $1'",
        "unknown-routine": "CREATE FUNCTION unrelated_operator_hook() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
    }
    source._db.execute(commands[change])
    with pytest.raises(TenantMigrationDenied, match="unsupported"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")


def test_known_routine_source_contract_qualifies_live_postgres(authority, historical):
    source = historical[0]
    if not isinstance(source, PostgresStore):
        pytest.skip("PostgreSQL function contract only")
    with source._db.cursor() as cur:
        names = qualified_postgres_routines(cur)
    assert set(names) == {"agentbridge_audit_capacity_fence_v1", "agentbridge_audit_capacity_v1",
                          "agentbridge_audit_capacity_no_delete_v1"}


@pytest.mark.parametrize("counter", ["used_records", "used_bytes"])
def test_freeze_rejects_inconsistent_counters_without_preserving_bad_snapshot(authority, historical, counter):
    source = historical[0]
    source._db.execute("UPDATE " + TABLE + " SET " + counter + "=0")
    before = policy_rows(source)
    with pytest.raises(TenantMigrationDenied, match="counters.*history"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")
    assert policy_rows(source) == before
