"""Preserve checkpoint bytes, policy and holds through real offline migration."""
from contextlib import closing

import pytest

from src.governance.audit import AuditLog
from src.governance.audit_trust import AuditTrustStore
from src.governance.checkpoint_capacity import TABLE, qualified_postgres_routines, verify_snapshot
from src.governance.operation_ledger import OperationLedger
from src.governance.store import PostgresStore
from src.governance.tenant_migration import TenantMigration, TenantMigrationDenied
from tests.test_authority import authority as authority
from tests.test_tenant_migration import backup_restore as backup_restore
from tests.test_tenant_migration import historical as historical
from tests.test_tenant_store import namespaces as namespaces


def state(store):
    return ([dict(row) for row in store._db.execute("SELECT seq,data FROM audit_checkpoints ORDER BY seq").fetchall()],
            [dict(row) for row in store._db.execute("SELECT * FROM " + TABLE).fetchall()])


def actual(store):
    with closing(store._db.cursor()) as cur:
        return verify_snapshot(cur, postgres=isinstance(store, PostgresStore))


@pytest.mark.parametrize("mode", ["initialized", "lazy", "over-limit"])
def test_real_checkpoint_restore_assignment_and_rollback(authority, namespaces, historical, backup_restore, mode):
    source, identity, _, before = historical
    trust = AuditTrustStore(source)
    if mode == "lazy":
        # Explicit disposable setup only: emulate a complete first upgrade,
        # removing every owned new object, not an unsupported selective restore.
        # The old metadata-only reset failure is preserved in the evidence.
        if isinstance(source, PostgresStore):
            assert source._db.execute("SELECT current_schema() AS schema").fetchone()["schema"].startswith("ab_tenant_")
            for table, names in ((TABLE, ("checkpoint_capacity_fence_v1", "checkpoint_immutable_v1")),
                                 ("audit_checkpoints", ("checkpoint_capacity_fence_v1", "checkpoint_immutable_v1", "checkpoint_capacity_insert_v1"))):
                for name in names:
                    source._db.execute("DROP TRIGGER " + name + " ON " + table)
            for name in ("agentbridge_checkpoint_capacity_v1", "agentbridge_checkpoint_immutable_v1"):
                source._db.execute("DROP FUNCTION " + name + "()")
        else:
            from src.governance.checkpoint_capacity import _sqlite_statements
            for statement in _sqlite_statements():
                source._db.execute("DROP TRIGGER " + statement.split()[5])
        source._db.execute("DROP TABLE " + TABLE)
        AuditTrustStore(source)
    elif mode == "over-limit":
        trust.set_checkpoint_capacity(max_records=1, max_bytes=1, max_entry_bytes=1)
    else:
        trust.set_checkpoint_capacity(max_records=7, max_bytes=8000, max_entry_bytes=1000)
    expected, expected_usage = state(source), actual(source)
    assert expected_usage["records"] == 1
    assert expected_usage["bytes"] == sum(len(row["data"].encode()) for row in expected[0])
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    assert state(restored) == expected and actual(restored) == expected_usage
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    scoped = namespaces("alpha")
    assert state(scoped) == expected and actual(scoped) == expected_usage
    assert scoped.load_audit() == before["audit"]
    assert AuditTrustStore(scoped).holds() == ["historical-case"]
    assert OperationLedger(scoped).get(identity.agent_id, "historical-unknown-12345")["state"] == "unknown"
    assert migration.rollback(authority[1])["historical_rows_preserved"]
    assert state(source) == expected and actual(source) == expected_usage
    if mode == "over-limit":
        candidate = {**before["checkpoint"], "seq": 0, "head_hash": AuditLog.GENESIS}
        candidate["signature_hex"] = identity.sign(AuditLog._checkpoint_payload(0, AuditLog.GENESIS)).hex()
        with pytest.raises(Exception, match="checkpoint capacity"):
            trust.save_checkpoint(candidate, identity.public_key_hex)
        assert state(source) == expected


def test_sqlite_missing_capacity_trigger_refuses_freeze_without_repair(authority, historical):
    source = historical[0]
    if isinstance(source, PostgresStore):
        pytest.skip("SQLite trigger statement contract")
    source._db.execute("DROP TRIGGER checkpoint_capacity_insert_v1")
    before = state(source)
    with pytest.raises(TenantMigrationDenied, match="checkpoint capacity snapshot"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")
    assert state(source) == before
    assert source._db.execute("SELECT name FROM sqlite_master WHERE name='checkpoint_capacity_insert_v1'").fetchone() is None


def test_sqlite_selective_metadata_restore_is_refused_without_initialization(authority, historical):
    source = historical[0]
    if isinstance(source, PostgresStore):
        pytest.skip("SQLite dangling trigger metadata boundary")
    before = [dict(row) for row in source._db.execute("SELECT seq,data FROM audit_checkpoints")]
    source._db.execute("DROP TABLE " + TABLE)
    with pytest.raises(TenantMigrationDenied, match="checkpoint capacity snapshot"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")
    assert [dict(row) for row in source._db.execute("SELECT seq,data FROM audit_checkpoints")] == before
    assert source._db.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None


@pytest.mark.parametrize("change", ["body", "security-definer", "stable", "search-path", "strict", "parallel", "overload", "unknown"])
def test_modified_or_unknown_checkpoint_routines_are_refused(authority, historical, change):
    source = historical[0]
    if not isinstance(source, PostgresStore):
        pytest.skip("PostgreSQL routine source/attributes")
    name = "agentbridge_checkpoint_capacity_v1"
    commands = {
        "body": "CREATE OR REPLACE FUNCTION " + name + "() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RETURN NULL; END $$",
        "security-definer": "ALTER FUNCTION " + name + "() SECURITY DEFINER",
        "stable": "ALTER FUNCTION " + name + "() STABLE",
        "search-path": "ALTER FUNCTION " + name + "() SET search_path=public",
        "strict": "ALTER FUNCTION " + name + "() STRICT",
        "parallel": "ALTER FUNCTION " + name + "() PARALLEL SAFE",
        "overload": "CREATE FUNCTION " + name + "(integer) RETURNS integer LANGUAGE sql AS 'SELECT $1'",
        "unknown": "CREATE FUNCTION unrelated_checkpoint_hook() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
    }
    source._db.execute(commands[change])
    with pytest.raises(TenantMigrationDenied, match="unsupported"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")


def test_exact_checkpoint_routines_qualify(authority, historical):
    source = historical[0]
    if not isinstance(source, PostgresStore):
        pytest.skip("PostgreSQL routine source/attributes")
    with source._db.cursor() as cur:
        assert set(qualified_postgres_routines(cur)) == {
            "agentbridge_checkpoint_capacity_v1", "agentbridge_checkpoint_immutable_v1",
        }
