"""Disposable logical backup/restore with externally pinned signing revisions.

Uses an explicitly named local qualification container as the PostgreSQL client.
Creates and drops only two uniquely named databases. No production DSN allowed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import uuid

import psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from examples.qualify_trust_evidence import public, signed_registry
from src.governance.audit import AuditLog
from src.governance.budget import Budget, BudgetManager
from src.governance.operation_ledger import OperationConflict, OperationLedger
from src.governance.signing_trust_journal import SigningTrustJournal, TrustJournalDenied
from src.governance.store import PostgresStore


def drill(dsn, container):
    options = conninfo_to_dict(dsn)
    if (
        os.getenv("AGENTBRIDGE_DISPOSABLE_TRUST_RESTORE") != "1"
        or options.get("host") not in ("127.0.0.1", "localhost")
        or options.get("dbname") != "agentbridge_test"
        or options.get("user") != "agentbridge"
        or not re.fullmatch(r"agentbridge-qualification-[A-Za-z0-9_.-]+", container)
    ):
        raise ValueError("explicit local disposable trust-restore configuration required")
    suffix = uuid.uuid4().hex
    source_name = "ab_trust_source_" + suffix
    restored_name = "ab_trust_restored_" + suffix
    created = []
    controllers = {name: Ed25519PrivateKey.generate() for name in ("destination", "readback")}
    keys = {name: Ed25519PrivateKey.generate() for name in controllers}
    roots = {name: public(key) for name, key in controllers.items()}
    stores = []
    with psycopg.connect(dsn, autocommit=True) as admin:
        try:
            for name in (source_name, restored_name):
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created.append(name)
            source = PostgresStore(make_conninfo(dsn, dbname=source_name))
            stores.append(source)
            journal = SigningTrustJournal(source, controller_keys=roots)
            revisions = {}
            for domain in controllers:
                revisions[domain] = signed_registry(
                    controllers[domain],
                    domain,
                    1,
                    None,
                    [dict(key_id="old", public_key_hex=public(keys[domain]), state="active")],
                )
                journal.publish(revisions[domain])
            budgets = BudgetManager(source)
            budgets.set_budget("restore-agent", Budget(spend_limit=10))
            token, _ = budgets.reserve("restore-agent", 2)
            OperationLedger(source).claim(
                "restore-agent", "restore-operation-00001", "approved", reservation_token=token
            )
            AuditLog(source).record(
                actor="restore-agent",
                action="synthetic_unknown",
                source_protocol="local",
                target_protocol="local",
                capability="synthetic",
                decision="unknown",
            )
            dump = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_dump",
                    "-U",
                    "agentbridge",
                    "-d",
                    source_name,
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                ],
                capture_output=True,
                check=True,
                timeout=60,
            ).stdout
            replacement = dict(
                key_id="replacement", public_key_hex=public(Ed25519PrivateKey.generate()), state="staged"
            )
            old = dict(revisions["readback"]["keys"][0])
            staged = signed_registry(controllers["readback"], "readback", 2, revisions["readback"], [old, replacement])
            journal.publish(staged)
            old["state"], replacement["state"] = "revoked", "active"
            journal.publish(signed_registry(controllers["readback"], "readback", 3, staged, [old, replacement]))
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "-U",
                    "agentbridge",
                    "-d",
                    restored_name,
                    "--single-transaction",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                ],
                input=dump,
                capture_output=True,
                check=True,
                timeout=60,
            )
            restored = PostgresStore(make_conninfo(dsn, dbname=restored_name))
            stores.append(restored)
            pinned = SigningTrustJournal(
                restored, controller_keys=roots, minimum_revisions={"destination": 1, "readback": 3}
            )
            checks = {}
            with pinned._transaction() as cur:
                try:
                    pinned.settlement_keys(cur, destination_key_id="old", observer_key_id="old")
                except TrustJournalDenied:
                    checks["restored_old_keys_denied_by_external_revision_pin"] = True
                else:
                    raise AssertionError("restored stale registry was trusted")
            operation = OperationLedger(restored)
            checks["unknown_operation_retained"] = (
                operation.get("restore-agent", "restore-operation-00001")["state"] == "unknown"
            )
            try:
                operation.claim("restore-agent", "restore-operation-00001", "approved")
            except OperationConflict:
                checks["replay_denied_after_restore"] = True
            state = restored.get_budget("restore-agent")
            checks["reservation_retained"] = sum(state["reserved"].values()) == 2 and state["spent"] == 0
            checks["restored_audit_chain_intact"] = AuditLog(restored).verify_durable()
            assert len(checks) == 5 and all(checks.values()), checks
            report = dict(
                accepted=True,
                scope="local-disposable-logical-backup-restore",
                checks=checks,
                backup_bytes=len(dump),
                latest_readback_revision=3,
                restored_readback_revision=1,
                production_qualified=False,
            )
        finally:
            for store in stores:
                store.close()
            for name in reversed(created):
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    report["temporary_databases_removed"] = True
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    print(json.dumps(drill(os.getenv("AGENTBRIDGE_TEST_PG", ""), args.container), indent=2, sort_keys=True))
