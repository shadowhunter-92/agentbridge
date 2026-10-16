"""Real SQL backup/restore, preserved bytes and conservative rollback."""

import os
import sqlite3
import subprocess
import time
import uuid

import pytest

from src.governance.audit import AuditLog
from src.governance.audit_trust import AuditTrustStore
from src.governance.budget import Budget, BudgetManager
from src.governance.durable_policy import DurableApprovalQueue, DurablePolicySet
from src.governance.durable_replay import claim_nonce
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.operation_ledger import OperationLedger
from src.governance.policy_rules import MaxCostPerCall
from src.governance.signing_trust_journal import SigningTrustJournal
from src.governance.store import PostgresStore, SqliteStore
from src.governance.tenant_migration import TenantMigration, TenantMigrationDenied
from src.governance.tenant_store import TenantStoreDenied
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.protocols.task_lifecycle import TaskLifecycle
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_store import namespaces as namespaces


@pytest.fixture
def historical(authority, namespaces):
    source = namespaces("alpha", legacy=True)
    identity = AgentIdentity.generate("historical-worker")
    IdentityRegistry(source).register(identity)
    budgets = BudgetManager(source)
    budgets.set_budget(identity.agent_id, Budget(spend_limit=20, rate_limit=100))
    reservation, _ = budgets.reserve(identity.agent_id, 3)
    OperationLedger(source).claim(
        identity.agent_id, "historical-unknown-12345", "old-fingerprint", reservation_token=reservation
    )
    approvals = DurableApprovalQueue(source)
    approvals.mark_sensitive("write")
    approval = approvals.request(identity.agent_id, "write", 3, "old-request-scope")
    DurablePolicySet(source).add(MaxCostPerCall(5))
    assert claim_nonce(source, identity.agent_id, f"{time.time()}:{uuid.uuid4().hex}", 300)
    audit = AuditLog(source)
    audit.record(
        actor=identity.agent_id,
        action="legacy-request",
        source_protocol="mcp",
        target_protocol="a2a",
        capability="write",
        decision="allow",
    )
    checkpoint = audit.checkpoint(identity.sign, identity.public_key_hex)
    trust = AuditTrustStore(source)
    trust.set_hold("historical-case", True)
    trust.save_checkpoint(checkpoint, identity.public_key_hex)
    from examples.qualify_trust_evidence import signed_registry

    controllers = {domain: AgentIdentity.generate(domain) for domain in ("destination", "readback")}
    journal = SigningTrustJournal(
        source, controller_keys={domain: key.public_key_hex for domain, key in controllers.items()}
    )
    for domain, controller in controllers.items():
        journal.publish(
            signed_registry(
                controller,
                domain,
                1,
                None,
                [
                    {
                        "key_id": domain + "-key",
                        "public_key_hex": AgentIdentity.generate(domain + "-signer").public_key_hex,
                        "state": "active",
                    }
                ],
            )
        )
    DurableTaskLifecycle(source).create(identity.agent_id, TaskLifecycle("historical-task", "context", "a2a"))
    before = {
        "budget": source.get_budget(identity.agent_id),
        "audit": source.load_audit(),
        "approval": source.get_approval(approval.id),
        "checkpoint": checkpoint,
    }
    return source, identity, approval, before


@pytest.fixture
def backup_restore(historical, tmp_path):
    source = historical[0]
    handles = []
    if isinstance(source, SqliteStore):

        def backup():
            archive = tmp_path / ("legacy-backup-" + uuid.uuid4().hex + ".sqlite")
            with sqlite3.connect(str(archive)) as destination:
                source._db.backup(destination)
            restored = SqliteStore(str(archive))
            handles.append(restored)
            return restored, archive

        yield backup
        for handle in handles:
            handle.close()
    else:
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        databases = []
        options = conninfo_to_dict(os.environ["AGENTBRIDGE_TEST_PG"])
        container = os.getenv("AGENTBRIDGE_TEST_PG_CONTAINER")
        schema = source._db.execute("SELECT current_schema() AS schema").fetchone()["schema"]

        def client(command, database, *, content=None):
            environment = os.environ.copy()
            if os.getenv("AGENTBRIDGE_TEST_PG_CLIENT") == "native":
                environment["PGPASSWORD"] = options["password"]
                args = [
                    command,
                    "-h",
                    options["host"],
                    "-p",
                    options.get("port", "5432"),
                    "-U",
                    options["user"],
                    "-d",
                    database,
                ]
            elif container:
                args = ["docker", "exec", "-i", container, command, "-U", options["user"], "-d", database]
            else:
                args = [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "--network",
                    "host",
                    "-e",
                    "PGPASSWORD=" + options["password"],
                    "postgres:16",
                    command,
                    "-h",
                    options["host"],
                    "-p",
                    options.get("port", "5432"),
                    "-U",
                    options["user"],
                    "-d",
                    database,
                ]
            args += (
                ["--format=custom", "--schema=" + schema]
                if command == "pg_dump"
                else ["--exit-on-error", "--single-transaction"]
            )
            args += ["--no-owner", "--no-acl"]
            process = subprocess.run(args, input=content, capture_output=True, timeout=60, env=environment)
            assert process.returncode == 0, process.stderr.decode(errors="replace")
            return process.stdout

        with psycopg.connect(os.environ["AGENTBRIDGE_TEST_PG"], autocommit=True) as admin:

            def backup():
                database = "ab_tenant_restore_" + uuid.uuid4().hex
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
                databases.append(database)
                content = client("pg_dump", options["dbname"])
                assert content.startswith(b"PGDMP")
                archive = tmp_path / (database + ".dump")
                archive.write_bytes(content)
                client("pg_restore", database, content=content)
                restored = PostgresStore(
                    make_conninfo(os.environ["AGENTBRIDGE_TEST_PG"], dbname=database, options="-csearch_path=" + schema)
                )
                handles.append(restored)
                return restored, archive

            try:
                yield backup
            finally:
                for handle in handles:
                    handle.close()
                for database in databases:
                    assert database.startswith("ab_tenant_restore_")
                    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def test_verified_migration_preserves_all_historical_state(authority, namespaces, historical, backup_restore):
    source, identity, approval, before = historical
    migration = TenantMigration(authority[0], source)
    frozen = migration.freeze(authority[1], "alpha")
    assert migration.freeze(authority[1], "alpha")["migration_id"] == frozen["migration_id"]
    with pytest.raises(Exception, match="frozen for tenant migration"):
        source.upsert_budget(identity.agent_id, {"spent": 999})
    restored, archive = backup_restore()
    migration.verify_backup(authority[1], restored, archive)
    assert migration.activate(authority[1], restored, archive)["phase"] == "active"
    scoped = namespaces("alpha")
    assert scoped.get_budget(identity.agent_id) == before["budget"]
    assert scoped.get_approval(approval.id) == before["approval"]
    assert scoped.load_audit() == before["audit"]
    assert AuditLog.verify_chain(scoped.load_audit(), require_genesis=True)
    assert AuditLog.verify_checkpoint(before["checkpoint"])
    assert AuditTrustStore(scoped).holds() == ["historical-case"]
    assert OperationLedger(scoped).get(identity.agent_id, "historical-unknown-12345")["state"] == "unknown"
    assert DurableTaskLifecycle(scoped).get(identity.agent_id, "historical-task").sequence == 0
    assert source.load_audit() == before["audit"]
    with pytest.raises(Exception, match="agentbridge_current_tenant|tenant write scope required"):
        source.upsert_budget(identity.agent_id, {"spent": 999})


def test_activation_requires_backup_and_rejects_same_namespace(authority, historical, tmp_path):
    source = historical[0]
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    archive = tmp_path / "invalid.dump"
    archive.write_bytes(b"invalid")
    with pytest.raises(TenantMigrationDenied, match="verified backup"):
        migration.activate(authority[1], source, archive)
    with pytest.raises(TenantMigrationDenied, match="independent namespace"):
        migration.verify_backup(authority[1], source, archive)


@pytest.mark.parametrize("failure_phase", ["binding_created", "guards_installed"])
def test_partial_activation_rolls_back_and_remains_frozen(
    authority, namespaces, historical, backup_restore, failure_phase
):
    source = historical[0]
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    migration.verify_backup(authority[1], restored, archive)

    def crash(phase):
        if phase == failure_phase:
            raise RuntimeError("injected partial migration failure")

    with pytest.raises(RuntimeError, match="partial migration failure"):
        migration.activate(authority[1], restored, archive, checkpoint=crash)
    with pytest.raises(TenantStoreDenied, match="legacy rows"):
        namespaces("alpha")
    with pytest.raises(Exception, match="frozen for tenant migration"):
        source.upsert_budget("new-writer", {"spent": 1})
    assert migration.activate(authority[1], restored, archive)["phase"] == "active"


def test_archive_and_restore_drift_are_rejected(authority, historical, backup_restore):
    migration = TenantMigration(authority[0], historical[0])
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    migration.verify_backup(authority[1], restored, archive)
    original = archive.read_bytes()
    archive.write_bytes(original + b"corrupted")
    with pytest.raises(TenantMigrationDenied, match="archive changed"):
        migration.activate(authority[1], restored, archive)
    archive.write_bytes(original)
    restored._db.execute("ALTER TABLE audit ADD COLUMN unexpected TEXT")
    with pytest.raises(TenantMigrationDenied, match="does not preserve"):
        migration.activate(authority[1], restored, archive)


def test_safe_rollback_preserves_legacy_state_and_restores_old_writer(
    authority, namespaces, historical, backup_restore
):
    source = historical[0]
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    scoped = namespaces("alpha")
    assert migration.rollback(authority[1])["historical_rows_preserved"]
    with pytest.raises(Exception):
        scoped.assert_scope()
    assert source.get_budget(historical[1].agent_id) == historical[3]["budget"]
    source.upsert_budget("old-writer-resumed", {"spent": 1})
    assert source.get_budget("old-writer-resumed")["spent"] == 1


def test_rollback_cannot_discard_tenant_era_writes(authority, namespaces, historical, backup_restore):
    migration = TenantMigration(authority[0], historical[0])
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    scoped = namespaces("alpha")
    scoped.upsert_budget("new-tenant-worker", {"spent": 1})
    with pytest.raises(TenantMigrationDenied, match="forward recovery required"):
        migration.rollback(authority[1])
    scoped.assert_scope()
    assert scoped.get_budget("new-tenant-worker")["spent"] == 1


def test_tenant_admin_cannot_assign_historical_store(authority, historical):
    directory, _, token, _, _ = authority
    admin = directory.authenticate_operator(ISSUER, token("administrator", tenant="alpha"), tenant_id="alpha")
    from src.governance.authority import AuthorityDenied

    with pytest.raises(AuthorityDenied):
        TenantMigration(directory, historical[0]).freeze(admin, "alpha")


def test_restored_copy_cannot_reuse_original_migration_authority(authority, historical, backup_restore):
    migration = TenantMigration(authority[0], historical[0])
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    copied = TenantMigration(authority[0], restored)
    with pytest.raises(TenantMigrationDenied, match="invalid or foreign migration marker"):
        copied.freeze(authority[1], "alpha")
    assert migration.verify_backup(authority[1], restored, archive)["phase"] == "backup_verified"


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"version": True},
        {"phase": "invented"},
        {"migration_id": "not-a-migration"},
        {"tenant_id": "*"},
        {"manifest": []},
        {"manifest": {"tables": [], "sequences": {}}},
        {"backup_sha256": "invalid"},
        {"phase": "active"},
        {"source_namespace": ["different-source"]},
        {"unexpected": "field"},
    ],
)
def test_corrupt_marker_never_activates_or_rolls_back(authority, historical, change):
    import json

    source = historical[0]
    migration = TenantMigration(authority[0], source)
    record = migration.freeze(authority[1], "alpha")
    record.update(change)
    placeholder = "%s" if isinstance(source, PostgresStore) else "?"
    source._db.execute("UPDATE agentbridge_tenant_migration SET record=" + placeholder, (json.dumps(record),))
    for action in (lambda: migration.freeze(authority[1], "alpha"), lambda: migration.rollback(authority[1])):
        with pytest.raises(TenantMigrationDenied, match="invalid or foreign migration marker"):
            action()
    with pytest.raises(Exception, match="frozen for tenant migration"):
        source.upsert_budget("old-writer", {"spent": 1})


def test_unqualified_view_is_rejected_without_freezing_source(authority, historical):
    source = historical[0]
    source._db.execute("CREATE VIEW historical_projection AS SELECT * FROM budgets")
    with pytest.raises(TenantMigrationDenied, match="unsupported schema objects"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")
    source.upsert_budget("writer-still-active", {"spent": 2})
    assert source.get_budget("writer-still-active")["spent"] == 2


def test_new_table_after_freeze_prevents_activation(authority, historical, backup_restore):
    source = historical[0]
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    migration.verify_backup(authority[1], restored, archive)
    source._db.execute("CREATE TABLE unexpected_writer (id INTEGER)")
    with pytest.raises(TenantMigrationDenied, match="historical state changed"):
        migration.activate(authority[1], restored, archive)


def test_freeze_waits_for_active_writer_and_preserves_committed_state(
    authority, namespaces, historical, backup_restore
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    source = historical[0]
    writer = namespaces("alpha", legacy=True)
    migration = TenantMigration(authority[0], source)
    entered, release = threading.Event(), threading.Event()

    def write():
        with writer._lock:
            if isinstance(writer, SqliteStore):
                writer._db.execute("BEGIN IMMEDIATE")
                try:
                    writer._db.execute("INSERT INTO budgets VALUES(?,?)", ("active-writer", '{"spent":7}'))
                    entered.set()
                    assert release.wait(5)
                    writer._db.execute("COMMIT")
                except BaseException:
                    writer._db.execute("ROLLBACK")
                    raise
            else:
                with writer._db.transaction():
                    writer._db.execute("INSERT INTO budgets VALUES(%s,%s)", ("active-writer", '{"spent":7}'))
                    entered.set()
                    assert release.wait(5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(write)
        try:
            assert entered.wait(5)
            freezing = pool.submit(migration.freeze, authority[1], "alpha")
            assert not threading.Event().wait(0.15)
            assert not freezing.done(), "freeze overtook an active legacy transaction"
        finally:
            release.set()
        writing.result(timeout=5)
        freezing.result(timeout=5)
    restored, archive = backup_restore()
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    assert namespaces("alpha").get_budget("active-writer") == {"spent": 7}
    with pytest.raises(Exception, match="agentbridge_current_tenant|tenant write scope required"):
        writer.upsert_budget("late-writer", {"spent": 99})


def test_partial_rollback_is_atomic_and_retryable(authority, namespaces, historical, backup_restore):
    source = historical[0]
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    migration.verify_backup(authority[1], restored, archive)
    migration.activate(authority[1], restored, archive)
    scoped = namespaces("alpha")

    def crash(phase):
        assert phase == "rollback_prepared"
        raise RuntimeError("injected rollback failure")

    with pytest.raises(RuntimeError, match="rollback failure"):
        migration.rollback(authority[1], checkpoint=crash)
    scoped.assert_scope()
    with pytest.raises(Exception, match="agentbridge_current_tenant|tenant write scope required"):
        source.upsert_budget("old-writer", {"spent": 99})
    assert migration.rollback(authority[1])["historical_rows_preserved"]
    source.upsert_budget("resumed-writer", {"spent": 1})


def test_rollback_waits_for_in_progress_authorized_session(authority, historical, backup_restore):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from src.governance.authority import AuthorityDirectory

    directory, owner, token, factory, _ = authority
    migration = TenantMigration(directory, historical[0])
    migration.freeze(owner, "alpha")
    restored, archive = backup_restore()
    migration.verify_backup(owner, restored, archive)
    migration.activate(owner, restored, archive)
    other = AuthorityDirectory(factory(), verifiers=directory.verifiers)
    other_owner = other.authenticate_operator(ISSUER, token("owner"))
    concurrent = TenantMigration(other, historical[0])
    started = threading.Event()

    def rollback():
        started.set()
        return concurrent.rollback(other_owner)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with directory.guard(owner):
            future = pool.submit(rollback)
            assert started.wait(5)
            assert not threading.Event().wait(0.2)
            assert not future.done(), "migration overtook a guarded tenant operation"
        assert future.result(timeout=5)["historical_rows_preserved"]


def test_restore_metadata_drift_is_rejected(authority, historical, backup_restore):
    import json

    source = historical[0]
    migration = TenantMigration(authority[0], source)
    migration.freeze(authority[1], "alpha")
    restored, archive = backup_restore()
    record = json.loads(restored._db.execute("SELECT record FROM agentbridge_tenant_migration").fetchone()["record"])
    record["migration_id"] = "0" * 32
    placeholder = "%s" if isinstance(restored, PostgresStore) else "?"
    restored._db.execute("UPDATE agentbridge_tenant_migration SET record=" + placeholder, (json.dumps(record),))
    with pytest.raises(TenantMigrationDenied, match="metadata differs"):
        migration.verify_backup(authority[1], restored, archive)


def test_reserved_legacy_objects_are_never_silently_replaced(authority, historical):
    source = historical[0]
    if isinstance(source, SqliteStore):
        source._db.execute("CREATE TRIGGER tenant_guard_legacy BEFORE INSERT ON budgets BEGIN SELECT 1; END")
    else:
        source._db.execute(
            "CREATE FUNCTION agentbridge_tenant_write_guard() RETURNS INTEGER LANGUAGE SQL AS 'SELECT 1'"
        )
    with pytest.raises(TenantMigrationDenied, match="reserved migration objects|unsupported schema objects"):
        TenantMigration(authority[0], source).freeze(authority[1], "alpha")
    source.upsert_budget("legacy-still-writable", {"spent": 2})
