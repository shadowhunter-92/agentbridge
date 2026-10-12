"""Actual PostgreSQL custom-format backup, isolated restore, and rollback drill.

SAFETY: runs exclusively on the disposable localhost GitHub Actions test DB.
Creates two new randomly named databases and drops ONLY those new databases.
Never points pg_restore at the original database and never cuts production over.
Requires explicit env opt-in and Docker's official matching PostgreSQL client.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

from psycopg import connect, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from src.governance.audit import AuditLog
from src.governance.budget import Budget, BudgetManager
from src.governance.operation_ledger import OperationConflict, OperationLedger
from src.governance.store import PostgresStore


def _require_disposable_test_target():
    if os.getenv("AGENTBRIDGE_DISPOSABLE_PG_RESTORE_DRILL") != "1":
        raise RuntimeError("disposable-only PostgreSQL restore drill not enabled")
    dsn = os.getenv("AGENTBRIDGE_TEST_PG", "")
    opts = conninfo_to_dict(dsn)
    if (opts.get("host") not in ("127.0.0.1", "localhost")
            or opts.get("dbname") != "agentbridge_test"
            or opts.get("user") != "agentbridge"
            or not opts.get("password")):
        raise RuntimeError("drill permits only localhost agentbridge_test with test principal")
    return dsn, opts


def _pg_client(opts, command, *, source=None):
    args = [
        "docker", "run", "--rm", "-i", "--network", "host",
        "-e", "PGPASSWORD=" + opts["password"],
        "postgres:16", command, "-h", "127.0.0.1", "-p",
        str(opts.get("port", "5432")), "-U", "agentbridge",
    ]
    if command == "pg_dump":
        args += ["-d", opts["source_db"], "--format=custom",
                 "--no-owner", "--no-acl"]
    elif command == "pg_restore":
        args += ["-d", opts["restore_db"], "--exit-on-error",
                 "--single-transaction", "--no-owner", "--no-acl"]
    else:
        raise ValueError("unsupported client")
    result = subprocess.run(args, input=source, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{command} failed: {result.stderr.decode(errors='replace')[:1500]}")
    return result.stdout


def drill(report_path: str | None = None):
    dsn, options = _require_disposable_test_target()
    suffix = uuid.uuid4().hex[:16]
    source_db = "ab_drill_source_" + suffix
    restore_db = "ab_drill_restore_" + suffix
    agent_id = "drill-agent-" + suffix
    operation_id = "drill-action-" + suffix
    fingerprint = "request-" + suffix
    created = []
    admin = connect(dsn, autocommit=True)
    try:
        # CREATE DATABASE is intentionally outside a transaction. Do not
        # derive a database identifier from untrusted remote input.
        for name in (source_db, restore_db):
            with admin.cursor() as cur:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created.append(name)
        source_dsn = make_conninfo(dsn, dbname=source_db)
        first = PostgresStore(source_dsn)
        try:
            budget = BudgetManager(first)
            budget.set_budget(agent_id, Budget(spend_limit=10, rate_limit=10))
            token, reason = budget.reserve(agent_id, 2)
            if not token:
                raise AssertionError("cannot reserve synthetic operation: " + str(reason))
            ledger = OperationLedger(first)
            ledger.claim(agent_id, operation_id, fingerprint, reservation_token=token)
            audit = AuditLog(first)
            audit.record(actor=agent_id, action="route_call", source_protocol="mcp",
                         target_protocol="a2a", capability="read", decision="allow")
            assert ledger.get(agent_id, operation_id)["state"] == "unknown"
            assert AuditLog.verify_chain(first.load_audit(), require_genesis=True)
        finally:
            first.close()
        # This is a true PostgreSQL 16 pg_dump stream, not a JSON/table mock.
        archive = _pg_client({**options, "source_db": source_db}, "pg_dump")
        if len(archive) < 256 or not archive.startswith(b"PGDMP"):
            raise AssertionError("invalid PostgreSQL custom-format dump")
        archive_hash = hashlib.sha256(archive).hexdigest()

        # Simulate schema/data changes after the snapshot. Restore must return
        # to the old unknown/no-replay state, not silently record success.
        updated = PostgresStore(source_dsn)
        try:
            OperationLedger(updated).finish(agent_id, operation_id, "succeeded")
            AuditLog(updated).record(actor=agent_id, action="post_backup",
                                     source_protocol="mcp", target_protocol="a2a",
                                     capability="read", decision="allow")
            with updated._db.cursor() as cur:
                cur.execute("CREATE TABLE disposable_upgrade_marker(version INT PRIMARY KEY)")
                cur.execute("INSERT INTO disposable_upgrade_marker VALUES(2)")
        finally:
            updated.close()

        _pg_client({**options, "restore_db": restore_db}, "pg_restore", source=archive)
        restored = PostgresStore(make_conninfo(dsn, dbname=restore_db))
        try:
            rledger = OperationLedger(restored)
            assert rledger.get(agent_id, operation_id)["state"] == "unknown"
            try:
                rledger.claim(agent_id, operation_id, fingerprint)
                raise AssertionError("restored unknown operation unexpectedly replayable")
            except OperationConflict:
                pass
            assert len(restored.load_audit()) == 1
            assert AuditLog.verify_chain(restored.load_audit(), require_genesis=True)
            budget_state = restored.get_budget(agent_id)
            assert budget_state and budget_state.get("reserved"), "lost pending reservation"
            with restored._db.cursor() as cur:
                cur.execute("SELECT to_regclass('public.disposable_upgrade_marker') AS found")
                assert cur.fetchone()["found"] is None, "post-backup migration was not rolled back"
        finally:
            restored.close()
        report = {
            "kind": "disposable-local-postgres16-pg_dump-pg_restore",
            "archive_sha256": archive_hash,
            "archive_bytes": len(archive),
            "restored_operation": "unknown",
            "replay_prevented": True,
            "budget_reservation_preserved": True,
            "audit_chain_valid": True,
            "post_snapshot_schema_change_rolled_back": True,
            "limitations": "No managed HA/PITR, cross-host partitions, WORM witness or production cutover",
        }
        if report_path:
            Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        for name in reversed(created):
            if not name.startswith(("ab_drill_source_", "ab_drill_restore_")):
                raise RuntimeError("refusing unsafe test database drop")
            with admin.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)))
        admin.close()


if __name__ == "__main__":
    print(json.dumps(drill(os.getenv("AGENTBRIDGE_PG_DRILL_REPORT")), sort_keys=True, indent=2))
