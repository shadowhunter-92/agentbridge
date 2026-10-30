"""Durable manual reconciliation for unknown agent operations.

An operator must provide an external reference and evidence digest. This module
does not assert the evidence is truthful; the reviewer is responsible for checking
the destination system independently.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import closing
from dataclasses import asdict

from .audit import AuditEntry, AuditLog, _now
from .budget import BudgetManager
from .destination_receipts import UntrustedReceipt, verify_destination_receipt
from .operation_ledger import OperationConflict, OperationLedger
from .operator_review import UntrustedReviewer, verify_operator_review
from .owned_settlement import lock_unknown_operation, settle_owned_reservation
from .readback_attestations import UntrustedReadback, verify_readback_attestation
from .signing_trust_journal import SigningTrustJournal, TrustJournalDenied
from .store import PostgresStore, SqliteStore, sql_atomic


class ReconciliationError(ValueError):
    pass


class Reconciliation:
    def __init__(self, store, *, trust_journal=None):
        if trust_journal is not None and (
            not isinstance(trust_journal, SigningTrustJournal) or trust_journal.store is not store
        ):
            raise ReconciliationError("trust journal must share the settlement store")
        self.trust_journal = trust_journal
        self.store = store
        self.operations = OperationLedger(store)
        if not isinstance(store, (SqliteStore, PostgresStore)):
            raise ReconciliationError("durable database required")
        from .evidence_journal_capacity import (
            TABLE, assert_postgres_namespace, assert_sqlite_namespace,
            install_postgres, install_sqlite,
        )
        with sql_atomic(store):
            execute = store._db.execute
            postgres = isinstance(store, PostgresStore)
            with closing(store._db.cursor()) as cur:
                if postgres:
                    assert_postgres_namespace(cur)
                    execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
                    execute("SELECT pg_advisory_xact_lock(%s)", (store._AUDIT_LOCK_KEY,))
                else:
                    assert_sqlite_namespace(cur)
                stamp = "DOUBLE PRECISION" if postgres else "REAL"
                execute("CREATE TABLE IF NOT EXISTS operation_reconciliations ("
                        "agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,result TEXT NOT NULL,"
                        "external_reference TEXT NOT NULL,evidence_sha256 TEXT NOT NULL,reviewer TEXT NOT NULL,"
                        "created " + stamp + " NOT NULL,PRIMARY KEY(agent_id,operation_id))")
                execute("CREATE TABLE IF NOT EXISTS reconciliation_readbacks (agent_id TEXT NOT NULL,"
                        "operation_id TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(agent_id,operation_id))")
                execute("CREATE TABLE IF NOT EXISTS reconciliation_evidence (agent_id TEXT NOT NULL,"
                        "operation_id TEXT NOT NULL,bundle TEXT NOT NULL,PRIMARY KEY(agent_id,operation_id))")
                (install_postgres if postgres else install_sqlite)(cur)
                if getattr(store, "tenant_id", None):
                    from .tenant_store import _install_postgres_guards, _install_sqlite_guards
                    tables = ("operation_reconciliations", "reconciliation_readbacks", "reconciliation_evidence", TABLE)
                    if postgres:
                        _install_postgres_guards(cur, store.schema, tables)
                    else:
                        _install_sqlite_guards(cur, tables)

    def evidence_capacity(self):
        """Inspect retained bundle payload limits and actual SQL usage."""
        from .evidence_journal_capacity import policy
        return policy(self.store)

    def set_evidence_capacity(self, *, max_records, max_bytes, max_entry_bytes, audit=None):
        """Trusted operator configuration; never prunes or rewrites evidence."""
        from .evidence_journal_capacity import EvidenceLimits, policy
        return policy(self.store, limits=EvidenceLimits(max_records, max_bytes, max_entry_bytes), audit=audit)

    def _execute(self, query, values=()):
        return self.store._db.execute(query.replace("?", "%s") if isinstance(self.store, PostgresStore) else query, values)

    def record_task(self, kernel, completion, *, review, operator_session):
        """Task-aware settlement requires sealed RO evidence and signed review."""
        from .queued_task_dispatch import _finish_verified
        runtime = kernel._runtimes.get(completion.tenant_id)
        if runtime is None or runtime.store is not self.store or review is None:
            raise ReconciliationError("same-store task evidence and independent operator review required")
        return _finish_verified(kernel, completion, review=review, operator_session=operator_session)

    def _has_task_links(self):
        if isinstance(self.store, PostgresStore):
            return self._execute("SELECT to_regclass(current_schema()||'.task_operation_links_v1') AS name").fetchone()["name"] is not None
        return self._execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_operation_links_v1'").fetchone() is not None

    def _trust_before_operation(self, cur, destination_key_id, observer_key_id):
        # A trust writer can queue on the authority-compatibility fence. Acquire
        # it before operation/budget, and never while a separate execution guard
        # is retained by this worker during queued completion.
        if self.trust_journal is None:
            return {}
        try:
            return self.trust_journal.settlement_keys(cur, destination_key_id=destination_key_id,
                                                       observer_key_id=observer_key_id)
        except TrustJournalDenied as exc:
            raise ReconciliationError("signing trust policy denied settlement") from exc

    def record(
        self,
        *,
        agent_id,
        operation_id,
        result,
        external_reference,
        evidence_sha256,
        reviewer,
        destination_receipt=None,
        readback_attestation=None,
        reviewer_signature_hex=None,
        destination_key_id=None,
        observer_key_id=None,
    ):
        if result not in ("succeeded", "failed"):
            raise ReconciliationError("operator must determine succeeded or failed")
        if any(
            not isinstance(x, str) or not x.strip() or len(x) > 512
            for x in (agent_id, operation_id, external_reference, reviewer)
        ):
            raise ReconciliationError("missing reviewer or external reference")
        if (
            not isinstance(evidence_sha256, str)
            or len(evidence_sha256) != 64
            or any(c not in "0123456789abcdef" for c in evidence_sha256)
        ):
            raise ReconciliationError("independent evidence SHA256 digest required")
        store = self.store
        with sql_atomic(store):
            cur = store._db.cursor()
            try:
                trust_context = self._trust_before_operation(cur, destination_key_id, observer_key_id)
                try:
                    lock_unknown_operation(store, agent_id, operation_id)
                except OperationConflict as exc:
                    raise ReconciliationError("operation missing or no longer unknown") from exc
                # A task-linked operation needs its concrete result/history
                # participant, not this legacy manual digest-only path.
                if getattr(store, "tenant_id", None) and self._has_task_links():
                    row = self._execute("SELECT 1 FROM task_operation_links_v1 WHERE agent_id=? AND operation_id=? LIMIT 1",
                                        (agent_id, operation_id)).fetchone()
                    if row is not None:
                        raise ReconciliationError("task-linked operation requires task-aware verified reconciliation")
                readback_digest, trust_context = self._verify_evidence(
                    cur, agent_id=agent_id, operation_id=operation_id, result=result,
                    external_reference=external_reference, evidence_sha256=evidence_sha256, reviewer=reviewer,
                    destination_receipt=destination_receipt, readback_attestation=readback_attestation,
                    reviewer_signature_hex=reviewer_signature_hex, destination_key_id=destination_key_id,
                    observer_key_id=observer_key_id, trust_context=trust_context,
                )
                self._execute("INSERT INTO operation_reconciliations VALUES(?,?,?,?,?,?,?)",
                              (agent_id, operation_id, result, external_reference, evidence_sha256, reviewer, time.time()))
                reservation = self._execute("SELECT token FROM operation_reservations WHERE agent_id=? AND operation_id=?",
                                            (agent_id, operation_id)).fetchone()
                if reservation is not None:
                    try:
                        settle_owned_reservation(store, BudgetManager(store), self.operations,
                                                 agent_id=agent_id, operation_id=operation_id,
                                                 token=reservation["token"], outcome=result)
                    except (OperationConflict, ValueError) as exc:
                        raise ReconciliationError("reserved budget token missing; cannot settle") from exc
                else:
                    self.operations.finish(agent_id, operation_id, result)
                if readback_digest:
                    self._execute("INSERT INTO reconciliation_readbacks VALUES(?,?,?)", (agent_id, operation_id, readback_digest))
                self._append_settlement_evidence(
                    cur, agent_id=agent_id, operation_id=operation_id, result=result,
                    external_reference=external_reference, evidence_sha256=evidence_sha256, reviewer=reviewer,
                    destination_receipt=destination_receipt, readback_attestation=readback_attestation,
                    reviewer_signature_hex=reviewer_signature_hex, readback_digest=readback_digest,
                    trust_context=trust_context,
                )
            finally:
                cur.close()
        return {
            "agent_id": agent_id,
            "operation_id": operation_id,
            "state": result,
            "evidence_sha256": evidence_sha256,
            "external_reference": external_reference,
            "reviewer": reviewer,
            "readback_sha256": readback_digest,
        }

    def _verify_evidence(
        self,
        cur,
        *,
        agent_id,
        operation_id,
        result,
        external_reference,
        evidence_sha256,
        reviewer,
        destination_receipt,
        readback_attestation,
        reviewer_signature_hex,
        destination_key_id,
        observer_key_id,
        trust_context=None,
    ):
        require_evidence = self.trust_journal is not None or os.getenv("AGENTBRIDGE_ENV", "").lower() in (
            "prod", "production",
        )
        if trust_context is None:
            trust_context = self._trust_before_operation(cur, destination_key_id, observer_key_id)
        if require_evidence:
            key = trust_context.get("destination_key_hex") or os.getenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX")
            operation = self.operations.get(agent_id, operation_id)
            if not key or not operation or not isinstance(destination_receipt, dict):
                raise ReconciliationError("verified destination receipt required in production")
            try:
                digest = verify_destination_receipt(
                    destination_receipt,
                    agent_id=agent_id,
                    operation_id=operation_id,
                    fingerprint=operation["fingerprint"],
                    trusted_public_key_hex=key,
                )
            except UntrustedReceipt as exc:
                raise ReconciliationError("untrusted destination receipt") from exc
            if (
                destination_receipt["outcome"] != result
                or destination_receipt["external_reference"] != external_reference
                or evidence_sha256 != digest
            ):
                raise ReconciliationError("destination receipt does not match settlement")
        readback_digest = None
        if require_evidence:
            verifier_key = trust_context.get("readback_key_hex") or os.getenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX")
            if not verifier_key or not isinstance(readback_attestation, dict):
                raise ReconciliationError("independent state-readback attestation required in production")
            try:
                readback_digest = verify_readback_attestation(
                    readback_attestation,
                    agent_id=agent_id,
                    operation_id=operation_id,
                    fingerprint=operation["fingerprint"],
                    outcome=result,
                    external_reference=external_reference,
                    destination_receipt_sha256=digest,
                    trusted_readback_key_hex=verifier_key,
                    destination_key_hex=key,
                )
            except UntrustedReadback as exc:
                raise ReconciliationError("untrusted independent state readback") from exc
        if require_evidence:
            try:
                verify_operator_review(
                    reviewer=reviewer,
                    agent_id=agent_id,
                    operation_id=operation_id,
                    fingerprint=operation["fingerprint"],
                    outcome=result,
                    external_reference=external_reference,
                    destination_receipt_sha256=digest,
                    readback_sha256=readback_digest,
                    signature_hex=reviewer_signature_hex,
                    trusted_operators_json=os.getenv("AGENTBRIDGE_RECONCILIATION_OPERATOR_KEYS_JSON"),
                )
            except UntrustedReviewer as exc:
                raise ReconciliationError("authorized signed operator review required") from exc
        return readback_digest, trust_context

    def _append_settlement_evidence(
        self,
        cur,
        *,
        agent_id,
        operation_id,
        result,
        external_reference,
        evidence_sha256,
        reviewer,
        destination_receipt,
        readback_attestation,
        reviewer_signature_hex,
        readback_digest,
        trust_context,
    ):
        # Keys in trust_context are public. No signing key or secret is persisted.
        bundle = dict(
            destination_receipt=destination_receipt,
            readback_attestation=readback_attestation,
            reviewer_signature_hex=reviewer_signature_hex,
            trust_context=trust_context,
        )
        bundle_json = json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False)
        bundle_digest = hashlib.sha256(bundle_json.encode("utf-8")).hexdigest()
        p = "?" if isinstance(self.store, SqliteStore) else "%s"
        if isinstance(self.store, PostgresStore):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (self.store._AUDIT_LOCK_KEY,))
        from .evidence_journal_capacity import verify_snapshot
        verify_snapshot(cur, postgres=isinstance(self.store, PostgresStore))
        cur.execute(
            f"INSERT INTO reconciliation_evidence VALUES({p},{p},{p})",
            (agent_id, operation_id, bundle_json),
        )
        cur.execute("SELECT seq,entry FROM audit ORDER BY seq DESC LIMIT 1")
        row = cur.fetchone()
        last = json.loads(row["entry"]) if row else None
        entry = AuditEntry(
            seq=last["seq"] + 1 if last else 0,
            timestamp=_now(),
            actor=reviewer,
            action="reconcile_operation",
            source_protocol="operator",
            target_protocol="destination",
            capability="settle_unknown_operation",
            decision=result,
            cost=0.0,
            reason=json.dumps(
                dict(
                    agent_id=agent_id,
                    operation_id=operation_id,
                    external_reference=external_reference,
                    destination_receipt_sha256=evidence_sha256,
                    readback_sha256=readback_digest,
                    evidence_bundle_sha256=bundle_digest,
                    trust_context=trust_context,
                ),
                sort_keys=True,
            ),
            prev_hash=last["entry_hash"] if last else AuditLog.GENESIS,
        )
        entry.entry_hash = entry.compute_hash()
        cur.execute(
            f"INSERT INTO audit(seq,entry) VALUES({p},{p})",
            (entry.seq, json.dumps(asdict(entry), sort_keys=True)),
        )
