"""Actual offline restore must preserve exact retained evidence and policy."""
from contextlib import closing

import pytest

from src.governance.evidence_journal_capacity import TABLE, verify_snapshot
from src.governance.operation_ledger import OperationLedger
from src.governance.reconciliation import Reconciliation
from src.governance.signing_journal_capacity import (
    TABLE as SIGNING_TABLE,
    SigningJournalLimits,
    policy as signing_policy,
    verify_if_installed as verify_signing_capacity,
)
from src.governance.store import PostgresStore, sql_atomic
from src.governance.tenant_migration import TenantMigration, TenantMigrationDenied
from tests.test_authority import authority as authority
from tests.test_tenant_migration import backup_restore as backup_restore
from tests.test_tenant_migration import historical as historical
from tests.test_tenant_store import namespaces as namespaces


def state(store):
    return ([dict(row) for row in store._db.execute("SELECT * FROM reconciliation_evidence ORDER BY 1,2")],
            [dict(row) for row in store._db.execute("SELECT * FROM " + TABLE)])


def usage(store):
    with closing(store._db.cursor()) as cur:
        return verify_snapshot(cur, postgres=isinstance(store, PostgresStore))


def seed(source):
    rec = Reconciliation(source)
    placeholder = "%s" if isinstance(source, PostgresStore) else "?"
    source._db.execute("INSERT INTO reconciliation_evidence VALUES('old','exact-bytes'," + placeholder + ")",
                       ('{ "unicode": "\u00e9\U0001f642", "history": 1 }\n',))
    return rec


@pytest.mark.parametrize("mode", ["initialized", "over-limit"])
def test_real_evidence_backup_restore_activation_and_rollback(authority, namespaces, historical, backup_restore, mode):
    source, identity, _, before = historical
    rec = seed(source)
    if mode == "over-limit":
        rec.set_evidence_capacity(max_records=1, max_bytes=1, max_entry_bytes=1)
    else:
        rec.set_evidence_capacity(max_records=7, max_bytes=8000, max_entry_bytes=1000)
    expected, expected_usage = state(source), usage(source)
    size = len(expected[0][0]["bundle"].encode("utf-8"))
    assert expected_usage == {"records": 1, "bytes": size, "largest_entry_bytes": size}
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    assert state(restored) == expected and usage(restored) == expected_usage
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    scoped = namespaces("alpha")
    assert state(scoped) == expected and usage(scoped) == expected_usage
    assert scoped.load_audit() == before["audit"]
    assert OperationLedger(scoped).get(identity.agent_id, "historical-unknown-12345")["state"] == "unknown"
    assert scoped.get_budget(identity.agent_id) == before["budget"]
    assert migration.rollback(authority[1])["historical_rows_preserved"]
    assert state(source) == expected and usage(source) == expected_usage


def test_real_empty_lazy_policy_backup_does_not_initialize_metadata(authority, historical, backup_restore):
    source = historical[0]
    Reconciliation(source)
    expected = state(source)
    assert expected == ([], [])
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    assert state(restored) == expected
    assert usage(restored) == {"records": 0, "bytes": 0, "largest_entry_bytes": 0}
    assert state(restored) == expected
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    assert migration.rollback(authority[1])["historical_rows_preserved"]
    assert state(source) == expected


def test_real_restore_changed_bundle_text_is_not_accepted(authority, historical, backup_restore):
    source = historical[0]
    seed(source)
    expected, expected_usage = state(source), usage(source)
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    postgres = isinstance(restored, PostgresStore)
    if postgres:
        guards = [dict(row) for row in restored._db.execute(
            "SELECT tgname AS name,pg_get_triggerdef(oid) AS definition FROM pg_trigger "
            "WHERE tgrelid='reconciliation_evidence'::regclass AND NOT tgisinternal ORDER BY tgname")]
        affected = [row for row in guards if row["name"] in ("evidence_immutable_v1", "ab_migration_freeze")]
    else:
        guards = [dict(row) for row in restored._db.execute(
            "SELECT name,sql AS definition FROM sqlite_master WHERE type='trigger' AND tbl_name='reconciliation_evidence' ORDER BY name")]
        affected = [row for row in guards if row["name"] == "evidence_immutable_history_update_v1" or (
            row["name"].startswith("ab_migration_freeze_") and " BEFORE UPDATE " in row["definition"].upper())]
    assert len(affected) == 2
    altered = expected[0][0]["bundle"] + " "
    placeholder = "%s" if postgres else "?"
    # Trusted disposable-restore fault injection. Reinstate every saved guard
    # before asking the verifier; source and all other objects stay unchanged.
    with sql_atomic(restored):
        for guard in affected:
            name = '"' + guard["name"].replace('"', '""') + '"'
            restored._db.execute("DROP TRIGGER " + name + (" ON reconciliation_evidence" if postgres else ""))
        restored._db.execute("UPDATE reconciliation_evidence SET bundle=" + placeholder, (altered,))
        for guard in affected:
            restored._db.execute(guard["definition"])
    assert usage(restored) == {"records": 1, "bytes": expected_usage["bytes"] + 1,
                               "largest_entry_bytes": expected_usage["largest_entry_bytes"] + 1}
    with pytest.raises(TenantMigrationDenied, match="does not preserve all historical rows"):
        migration.verify_backup(authority[1], restored, archive)
    assert state(source) == expected and usage(source) == expected_usage
    assert state(restored)[0][0]["bundle"] == altered


@pytest.mark.parametrize("change", ["missing-trigger", "missing-policy", "modified-trigger"])
def test_sqlite_partial_or_modified_capacity_freeze_refused_without_repair(authority, historical, change):
    source = historical[0]
    if isinstance(source, PostgresStore):
        pytest.skip("SQLite catalog contract")
    seed(source)
    if change == "missing-policy":
        source._db.execute("DROP TABLE " + TABLE)
    else:
        source._db.execute("DROP TRIGGER evidence_capacity_insert_v1")
        if change == "modified-trigger":
            source._db.execute("CREATE TRIGGER evidence_capacity_insert_v1 AFTER INSERT ON reconciliation_evidence BEGIN SELECT 1; END")
    before = [tuple(row) for row in source._db.execute("SELECT name,sql FROM sqlite_master ORDER BY name")]
    with pytest.raises(TenantMigrationDenied, match="evidence capacity snapshot"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")
    assert [tuple(row) for row in source._db.execute("SELECT name,sql FROM sqlite_master ORDER BY name")] == before


@pytest.mark.parametrize("change", ["body", "security-definer", "stable", "search-path", "strict", "parallel", "overload", "unknown"])
def test_postgres_modified_or_unknown_evidence_routines_refused(authority, historical, change):
    source = historical[0]
    if not isinstance(source, PostgresStore):
        pytest.skip("PostgreSQL routine source and attributes")
    seed(source)
    name = "agentbridge_evidence_capacity_v1"
    commands = {
        "body": "CREATE OR REPLACE FUNCTION " + name + "() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RETURN NULL; END $$",
        "security-definer": "ALTER FUNCTION " + name + "() SECURITY DEFINER",
        "stable": "ALTER FUNCTION " + name + "() STABLE",
        "search-path": "ALTER FUNCTION " + name + "() SET search_path=public",
        "strict": "ALTER FUNCTION " + name + "() STRICT",
        "parallel": "ALTER FUNCTION " + name + "() PARALLEL SAFE",
        "overload": "CREATE FUNCTION " + name + "(integer) RETURNS integer LANGUAGE sql AS 'SELECT $1'",
        "unknown": "CREATE FUNCTION unrelated_evidence_hook() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
    }
    source._db.execute(commands[change])
    with pytest.raises(TenantMigrationDenied, match="unsupported"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")


def _joint_capacity_rows(store):
    evidence_rows, evidence_policy = state(store)
    return {
        "signing_history": [dict(row) for row in store._db.execute(
            "SELECT * FROM signing_trust_revisions ORDER BY domain,revision")],
        "signing_policy": [dict(row) for row in store._db.execute("SELECT * FROM " + SIGNING_TABLE)],
        "evidence_history": evidence_rows,
        "evidence_policy": evidence_policy,
    }


def _joint_capacity_usage(store):
    return {
        "signing": verify_signing_capacity(store._db, postgres=isinstance(store, PostgresStore)),
        "evidence": usage(store),
    }


def _joint_protected_state(store, agent_id):
    placeholder = "%s" if isinstance(store, PostgresStore) else "?"
    parameters = (agent_id, "historical-unknown-12345")
    operation = store._db.execute(
        "SELECT fingerprint,state,updated FROM agent_operations WHERE agent_id=" + placeholder
        + " AND operation_id=" + placeholder, parameters).fetchone()
    assert operation is not None
    return {
        "operation": dict(operation),
        "operation_reservations": [dict(row) for row in store._db.execute(
            "SELECT * FROM operation_reservations WHERE agent_id=" + placeholder
            + " AND operation_id=" + placeholder, parameters)],
        "budget": store.get_budget(agent_id),
        "audit": store.load_audit(),
        "holds": [dict(row) for row in store._db.execute("SELECT * FROM audit_holds ORDER BY name")],
        "checkpoints": [dict(row) for row in store._db.execute("SELECT * FROM audit_checkpoints ORDER BY 1,2")],
    }


def _joint_capacity_source(historical):
    source, identity, _, before = historical
    reconciliation = seed(source)
    reconciliation.set_evidence_capacity(max_records=7, max_bytes=8000, max_entry_bytes=1000)
    # The existing historical fixture publishes both signing domains. Give
    # each capacity an explicit, distinct policy before freezing the same store.
    signing_policy(source, limits=SigningJournalLimits(11, 20000, 10000))
    expected = _joint_capacity_rows(source)
    expected_usage = _joint_capacity_usage(source)
    protected = _joint_protected_state(source, identity.agent_id)
    assert expected["signing_history"] and expected["evidence_history"]
    assert len(expected["signing_policy"]) == len(expected["evidence_policy"]) == 1
    assert expected["signing_policy"][0]["max_records"] == 11
    assert expected["evidence_policy"][0]["max_records"] == 7
    assert expected_usage["signing"]["used_records"] > 0 and expected_usage["evidence"]["records"] > 0
    assert protected["operation"]["state"] == "unknown"
    assert len(protected["operation_reservations"]) == 1
    token = protected["operation_reservations"][0]["token"]
    assert protected["budget"]["reserved"][token] == 3
    assert protected["budget"] == before["budget"] and protected["audit"] == before["audit"]
    assert protected["holds"] and protected["checkpoints"]
    return source, identity, expected, expected_usage, protected


def _joint_trigger_catalog(store):
    if isinstance(store, PostgresStore):
        query = (
            "SELECT t.relname,g.tgname,pg_get_triggerdef(g.oid) AS definition FROM pg_trigger g "
            "JOIN pg_class t ON t.oid=g.tgrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
            "WHERE n.nspname=current_schema() AND NOT g.tgisinternal ORDER BY t.relname,g.tgname"
        )
    else:
        query = "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    return [dict(row) for row in store._db.execute(query)]


def test_joint_signing_and_evidence_real_restore_activation_rollback(
        authority, namespaces, historical, backup_restore):
    source, identity, expected, expected_usage, protected = _joint_capacity_source(historical)
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    assert _joint_capacity_rows(restored) == expected
    assert _joint_capacity_usage(restored) == expected_usage
    assert _joint_protected_state(restored, identity.agent_id) == protected
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    scoped = namespaces("alpha")
    assert _joint_capacity_rows(scoped) == expected
    assert _joint_capacity_usage(scoped) == expected_usage
    assert _joint_protected_state(scoped, identity.agent_id) == protected
    assert migration.rollback(authority[1])["historical_rows_preserved"]
    assert _joint_capacity_rows(source) == expected
    assert _joint_capacity_usage(source) == expected_usage
    assert _joint_protected_state(source, identity.agent_id) == protected


@pytest.mark.parametrize("family", ["signing", "evidence"])
def test_joint_capacity_missing_trigger_refused_without_repair(authority, historical, family):
    source, identity, expected, expected_usage, protected = _joint_capacity_source(historical)
    trigger, table = {
        "signing": ("signing_capacity_insert_v1", "signing_trust_revisions"),
        "evidence": ("evidence_capacity_insert_v1", "reconciliation_evidence"),
    }[family]
    # Trusted disposable source damage: leave the other complete capacity
    # installed, and verify the failed freeze neither repairs nor changes it.
    source._db.execute("DROP TRIGGER " + trigger
                       + (" ON " + table if isinstance(source, PostgresStore) else ""))
    damaged_catalog = _joint_trigger_catalog(source)
    intact_family = "evidence" if family == "signing" else "signing"
    intact_usage = (usage(source) if intact_family == "evidence" else
                    verify_signing_capacity(source._db, postgres=isinstance(source, PostgresStore)))
    assert intact_usage == expected_usage[intact_family]
    message = "unsupported " + ("signing journal" if family == "signing" else "evidence") + " capacity snapshot"
    with pytest.raises(TenantMigrationDenied, match=message):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")
    assert _joint_trigger_catalog(source) == damaged_catalog
    assert _joint_capacity_rows(source) == expected
    assert _joint_protected_state(source, identity.agent_id) == protected
    intact_after = (usage(source) if intact_family == "evidence" else
                    verify_signing_capacity(source._db, postgres=isinstance(source, PostgresStore)))
    assert intact_after == expected_usage[intact_family]
