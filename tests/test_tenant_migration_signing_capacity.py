"""Real same-backend restore preserves signing history, policy and floors."""

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from examples.qualify_trust_evidence import public, signed_registry
from src.governance.audit_trust import AuditTrustStore
from src.governance.budget import Budget, BudgetManager
from src.governance.operation_ledger import OperationLedger
from src.governance.signing_journal_capacity import (
    _POSTGRES_FUNCTION_SQL,
    _POSTGRES_TRIGGERS,
    TABLE,
    _statements,
    verify_if_installed,
)
from src.governance.signing_trust_journal import SigningTrustJournal, TrustJournalDenied
from src.governance.store import PostgresStore
from src.governance.tenant_migration import TenantMigration, TenantMigrationDenied
from tests.test_authority import authority as authority
from tests.test_tenant_migration import backup_restore as backup_restore
from tests.test_tenant_store import namespaces as namespaces


@pytest.fixture
def source(authority, namespaces):
    store = namespaces("alpha", legacy=True)
    controllers = {domain: Ed25519PrivateKey.generate() for domain in ("destination", "readback")}
    pinned = {domain: public(key) for domain, key in controllers.items()}
    trust = SigningTrustJournal(store, controller_keys=pinned)
    heads = {}
    for domain in controllers:
        heads[domain] = signed_registry(controllers[domain], domain, 1, None,
                                       [dict(key_id="old", public_key_hex=public(Ed25519PrivateKey.generate()), state="active")])
        trust.publish(heads[domain])
    budgets = BudgetManager(store)
    budgets.set_budget("agent", Budget(spend_limit=10))
    reservation, _ = budgets.reserve("agent", 2)
    OperationLedger(store).claim("agent", "held-unknown-12345", "fingerprint", reservation_token=reservation)
    AuditTrustStore(store).set_hold("retained-case", True)
    return store, trust, controllers, pinned, heads


@pytest.fixture
def historical(source):
    # Reuse the existing independently restored pg_dump/SQLite backup fixture.
    # It requires only historical[0], which is the unchanged source store.
    return source


def actual(store):
    return verify_if_installed(store._db, postgres=isinstance(store, PostgresStore))


def state(store):
    return ([dict(row) for row in store._db.execute("SELECT * FROM signing_trust_revisions ORDER BY domain,revision")],
            [dict(row) for row in store._db.execute("SELECT * FROM " + TABLE)])


@pytest.mark.parametrize("mode", ["initialized", "lazy-upgrade", "over-limit"])
def test_real_restore_assignment_rollback_preserves_exact_signed_history(authority, namespaces, source, backup_restore, mode):
    store, trust, _, pinned, heads = source
    if mode == "lazy-upgrade":
        # Disposable upgrade setup: remove the complete new capacity unit, not
        # selected objects from a supposedly intact current installation.
        if isinstance(store, PostgresStore):
            for table, name in _POSTGRES_TRIGGERS:
                store._db.execute("DROP TRIGGER " + name + " ON " + table)
            for name in _POSTGRES_FUNCTION_SQL:
                store._db.execute("DROP FUNCTION " + name + "()")
        else:
            for statement in _statements():
                store._db.execute("DROP TRIGGER " + statement.split()[5])
        store._db.execute("DROP TABLE " + TABLE)
        trust = SigningTrustJournal(store, controller_keys=pinned)
    elif mode == "over-limit":
        trust.set_capacity(max_records=1, max_bytes=1, max_entry_bytes=1)
    else:
        trust.set_capacity(max_records=8, max_bytes=10000, max_entry_bytes=10000)
    expected = state(store)
    expected_usage = actual(store)
    before_budget = store.get_budget("agent")
    migration = TenantMigration(authority[0], store)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    assert state(restored) == expected and actual(restored) == expected_usage
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    scoped = namespaces("alpha")
    assert state(scoped) == expected
    assert scoped.get_budget("agent") == before_budget
    assert OperationLedger(scoped).get("agent", "held-unknown-12345")["state"] == "unknown"
    assert AuditTrustStore(scoped).holds() == ["retained-case"]
    journal = SigningTrustJournal(scoped, controller_keys=pinned, minimum_revisions={domain: 1 for domain in heads})
    with journal._transaction() as cur:
        for domain in heads:
            assert journal._load(cur, domain)[0] == heads[domain]
    ahead = SigningTrustJournal(scoped, controller_keys=pinned, minimum_revisions={"readback": 2})
    with pytest.raises(TrustJournalDenied, match="minimum revision"):
        with ahead._transaction() as cur:
            ahead._load(cur, "readback")
    assert migration.rollback(authority[1])["historical_rows_preserved"]
    assert state(store) == expected and actual(store) == expected_usage


@pytest.mark.parametrize("damage", ["missing-trigger", "missing-policy", "modified-trigger"])
def test_migration_refuses_partial_capacity_without_repair(authority, source, damage):
    store = source[0]
    before_history = state(store)[0]
    before_budget = store.get_budget("agent")
    before_operation = OperationLedger(store).get("agent", "held-unknown-12345")
    before_audit = store.load_audit()
    before_holds = [dict(row) for row in store._db.execute("SELECT * FROM audit_holds ORDER BY name")]
    if damage == "missing-policy":
        store._db.execute("DROP TABLE " + TABLE)
    else:
        store._db.execute("DROP TRIGGER signing_capacity_insert_v1" + (" ON signing_trust_revisions" if isinstance(store, PostgresStore) else ""))
        if damage == "modified-trigger":
            if isinstance(store, PostgresStore):
                store._db.execute("CREATE TRIGGER signing_capacity_insert_v1 AFTER INSERT ON signing_trust_revisions "
                                  "FOR EACH ROW WHEN (NEW.revision>1) EXECUTE FUNCTION agentbridge_signing_capacity_insert_v1()")
            else:
                store._db.execute("CREATE TRIGGER signing_capacity_insert_v1 AFTER INSERT ON signing_trust_revisions BEGIN SELECT 1; END")
    if isinstance(store, PostgresStore):
        schema_query = ("SELECT t.relname,g.tgname,pg_get_triggerdef(g.oid) AS definition FROM pg_trigger g "
                        "JOIN pg_class t ON t.oid=g.tgrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname=current_schema() ORDER BY t.relname,g.tgname")
    else:
        schema_query = "SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'"
    before = [dict(row) for row in store._db.execute(schema_query)]
    expected_message = ("unsupported schema objects require an explicit migration adapter"
                        if isinstance(store, PostgresStore) and damage == "missing-policy"
                        else "signing journal capacity snapshot")
    with pytest.raises(TenantMigrationDenied, match=expected_message):
        TenantMigration(authority[0], store).freeze(authority[1], "alpha")
    assert [dict(row) for row in store._db.execute(schema_query)] == before
    assert [json.loads(row["envelope"]) for row in before_history] == [
        json.loads(row["envelope"]) for row in store._db.execute("SELECT * FROM signing_trust_revisions ORDER BY domain,revision")]
    assert store.get_budget("agent") == before_budget
    assert OperationLedger(store).get("agent", "held-unknown-12345") == before_operation
    assert store.load_audit() == before_audit
    assert [dict(row) for row in store._db.execute("SELECT * FROM audit_holds ORDER BY name")] == before_holds
