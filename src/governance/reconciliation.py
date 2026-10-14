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
from dataclasses import asdict

from .audit import AuditEntry, AuditLog, _now
from .destination_receipts import UntrustedReceipt, verify_destination_receipt
from .operation_ledger import OperationLedger
from .operator_review import UntrustedReviewer, verify_operator_review
from .readback_attestations import UntrustedReadback, verify_readback_attestation
from .signing_trust_journal import SigningTrustJournal, TrustJournalDenied
from .store import PostgresStore, SqliteStore


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
        if isinstance(store, SqliteStore):
            with store._lock:
                store._db.execute(
                    "CREATE TABLE IF NOT EXISTS operation_reconciliations "
                    "(agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                    "result TEXT NOT NULL, external_reference TEXT NOT NULL, "
                    "evidence_sha256 TEXT NOT NULL, reviewer TEXT NOT NULL, "
                    "created REAL NOT NULL, PRIMARY KEY(agent_id, operation_id))"
                )
        elif isinstance(store, PostgresStore):
            with store._lock, store._db.transaction(), store._db.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS operation_reconciliations "
                    "(agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                    "result TEXT NOT NULL, external_reference TEXT NOT NULL, "
                    "evidence_sha256 TEXT NOT NULL, reviewer TEXT NOT NULL, "
                    "created DOUBLE PRECISION NOT NULL, PRIMARY KEY(agent_id, operation_id))"
                )
        else:
            raise ReconciliationError("durable database required")

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
        if isinstance(store, SqliteStore):
            with store._lock:
                db = store._db
                db.execute("BEGIN IMMEDIATE")
                try:
                    row = db.execute(
                        "SELECT state FROM agent_operations WHERE agent_id=? AND operation_id=?",
                        (agent_id, operation_id),
                    ).fetchone()
                    if not row or row["state"] != "unknown":
                        raise ReconciliationError("operation missing or no longer unknown")
                    readback_digest, trust_context = self._verify_evidence(
                        db.cursor(),
                        agent_id=agent_id,
                        operation_id=operation_id,
                        result=result,
                        external_reference=external_reference,
                        evidence_sha256=evidence_sha256,
                        reviewer=reviewer,
                        destination_receipt=destination_receipt,
                        readback_attestation=readback_attestation,
                        reviewer_signature_hex=reviewer_signature_hex,
                        destination_key_id=destination_key_id,
                        observer_key_id=observer_key_id,
                    )
                    db.execute(
                        "INSERT INTO operation_reconciliations VALUES(?,?,?,?,?,?,?)",
                        (
                            agent_id,
                            operation_id,
                            result,
                            external_reference,
                            evidence_sha256,
                            reviewer,
                            time.time(),
                        ),
                    )
                    db.execute(
                        "UPDATE agent_operations SET state=?,updated=? WHERE agent_id=? AND operation_id=?",
                        (result, time.time(), agent_id, operation_id),
                    )
                    reservation = db.execute(
                        "SELECT token FROM operation_reservations WHERE agent_id=? AND operation_id=?",
                        (agent_id, operation_id),
                    ).fetchone()
                    if reservation:
                        budget_row = db.execute("SELECT state FROM budgets WHERE agent_id=?", (agent_id,)).fetchone()
                        if not budget_row:
                            raise ReconciliationError("budget missing; cannot settle")
                        state = json.loads(budget_row["state"])
                        token = reservation["token"]
                        amount = state.get("reserved", {}).pop(token, None)
                        if amount is None:
                            raise ReconciliationError("reserved budget token missing; cannot settle")
                        if result == "succeeded":
                            state["spent"] = state.get("spent", 0.0) + amount
                            state.setdefault("calls", []).append(time.time())
                        db.execute(
                            "UPDATE budgets SET state=? WHERE agent_id=?",
                            (json.dumps(state), agent_id),
                        )
                    if readback_digest:
                        db.execute(
                            "CREATE TABLE IF NOT EXISTS reconciliation_readbacks (agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(agent_id,operation_id))"
                        )
                        db.execute(
                            "INSERT INTO reconciliation_readbacks VALUES(?,?,?)",
                            (agent_id, operation_id, readback_digest),
                        )
                    self._append_settlement_evidence(
                        db.cursor(),
                        agent_id=agent_id,
                        operation_id=operation_id,
                        result=result,
                        external_reference=external_reference,
                        evidence_sha256=evidence_sha256,
                        reviewer=reviewer,
                        destination_receipt=destination_receipt,
                        readback_attestation=readback_attestation,
                        reviewer_signature_hex=reviewer_signature_hex,
                        readback_digest=readback_digest,
                        trust_context=trust_context,
                    )
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
        else:
            with store._lock, store._db.transaction(), store._db.cursor() as cur:
                cur.execute(
                    "SELECT state FROM agent_operations WHERE agent_id=%s AND operation_id=%s FOR UPDATE",
                    (agent_id, operation_id),
                )
                row = cur.fetchone()
                if not row or row["state"] != "unknown":
                    raise ReconciliationError("operation missing or no longer unknown")
                readback_digest, trust_context = self._verify_evidence(
                    cur,
                    agent_id=agent_id,
                    operation_id=operation_id,
                    result=result,
                    external_reference=external_reference,
                    evidence_sha256=evidence_sha256,
                    reviewer=reviewer,
                    destination_receipt=destination_receipt,
                    readback_attestation=readback_attestation,
                    reviewer_signature_hex=reviewer_signature_hex,
                    destination_key_id=destination_key_id,
                    observer_key_id=observer_key_id,
                )
                cur.execute(
                    "INSERT INTO operation_reconciliations VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        agent_id,
                        operation_id,
                        result,
                        external_reference,
                        evidence_sha256,
                        reviewer,
                        time.time(),
                    ),
                )
                cur.execute(
                    "UPDATE agent_operations SET state=%s,updated=%s WHERE agent_id=%s AND operation_id=%s",
                    (result, time.time(), agent_id, operation_id),
                )
                cur.execute(
                    "SELECT token FROM operation_reservations WHERE agent_id=%s AND operation_id=%s",
                    (agent_id, operation_id),
                )
                reservation = cur.fetchone()
                if reservation:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (f"budget:{agent_id}",),
                    )
                    cur.execute(
                        "SELECT state FROM budgets WHERE agent_id=%s FOR UPDATE",
                        (agent_id,),
                    )
                    budget_row = cur.fetchone()
                    if not budget_row:
                        raise ReconciliationError("budget missing; cannot settle")
                    state = json.loads(budget_row["state"])
                    token = reservation["token"]
                    amount = state.get("reserved", {}).pop(token, None)
                    if amount is None:
                        raise ReconciliationError("reserved budget token missing; cannot settle")
                    if result == "succeeded":
                        state["spent"] = state.get("spent", 0.0) + amount
                        state.setdefault("calls", []).append(time.time())
                    cur.execute(
                        "UPDATE budgets SET state=%s WHERE agent_id=%s",
                        (json.dumps(state), agent_id),
                    )
                if readback_digest:
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS reconciliation_readbacks (agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(agent_id,operation_id))"
                    )
                    cur.execute(
                        "INSERT INTO reconciliation_readbacks VALUES(%s,%s,%s)",
                        (agent_id, operation_id, readback_digest),
                    )
                self._append_settlement_evidence(
                    cur,
                    agent_id=agent_id,
                    operation_id=operation_id,
                    result=result,
                    external_reference=external_reference,
                    evidence_sha256=evidence_sha256,
                    reviewer=reviewer,
                    destination_receipt=destination_receipt,
                    readback_attestation=readback_attestation,
                    reviewer_signature_hex=reviewer_signature_hex,
                    readback_digest=readback_digest,
                    trust_context=trust_context,
                )
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
    ):
        trust_context = {}
        require_evidence = self.trust_journal is not None or os.getenv("AGENTBRIDGE_ENV", "").lower() in (
            "prod",
            "production",
        )
        if self.trust_journal is not None:
            try:
                trust_context = self.trust_journal.settlement_keys(
                    cur,
                    destination_key_id=destination_key_id,
                    observer_key_id=observer_key_id,
                )
            except TrustJournalDenied as exc:
                raise ReconciliationError("signing trust policy denied settlement") from exc
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
        cur.execute(
            "CREATE TABLE IF NOT EXISTS reconciliation_evidence ("
            "agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, bundle TEXT NOT NULL, "
            "PRIMARY KEY(agent_id, operation_id))"
        )
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
