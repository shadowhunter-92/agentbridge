"""Synthetic Trust -> Evidence workflow, with explicit fail-closed transitions.

Use only disposable SQLite files. It illustrates the complete AgentBridge
control-flow contract, NOT an independently administered observer or
third-party destination enforcement.
Run: python -m examples.trust_evidence_end_to_end
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.approvals import ApprovalQueue
from src.governance.audit import AuditLog
from src.governance.audit_verify import verify_evidence_bundle
from src.governance.budget import Budget, BudgetManager
from src.governance.fenced_sqlite_destination import (
    FencedSqliteTarget, SqliteDuplicateEffect, SqliteFenceDenied,
)
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.observer_key_registry import ObserverKey, ObserverTrustRegistry
from src.governance.operation_ledger import OperationConflict, OperationLedger
from src.governance.policy import PolicyEngine
from src.governance.reconciliation import Reconciliation
from src.governance.sandbox_readback import SandboxReadOnlyObserver, ObservationUnavailable
from src.governance.store import SqliteStore
from src.governance.trust_sdk import verify_registered_action_evidence

AGENT = "synthetic-agent"
OPERATION = "synthetic-operation-001"
CAPABILITY = "synthetic.record"
TARGET = "sandbox://local-fenced-sqlite-v1"
SCOPE = "synthetic-bounded-actions"


def run_synthetic_flow(directory: str | Path, *, approve: bool = True,
                       allow_readback: bool = True) -> dict:
    """Produce a compact verified report with no secrets, networking or payouts.

    A missing independent readback leaves the durable operation UNKNOWN. This
    demo verifies evidence before calling Reconciliation.record, which itself
    requires stronger independent reviewer approval in actual production.
    """
    if os.environ.get("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
        raise RuntimeError("synthetic evaluator cannot run as production")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    control_path = str(root / "control.sqlite3")
    target_path = str(root / "target.sqlite3")

    agent = AgentIdentity.generate(AGENT)
    destination_key = Ed25519PrivateKey.generate()
    observer_key = Ed25519PrivateKey.generate()
    audit_key = Ed25519PrivateKey.generate()
    destination_pub = destination_key.public_key().public_bytes_raw().hex()
    observer_pub = observer_key.public_key().public_bytes_raw().hex()
    audit_pub = audit_key.public_key().public_bytes_raw().hex()

    # Exact operation, target and capability are bound into the fingerprint.
    import hashlib
    action = {"agent_id": AGENT, "operation_id": OPERATION,
              "capability": CAPABILITY, "target": TARGET, "payload": {"synthetic": True}}
    body = json.dumps(action, sort_keys=True, separators=(",", ":")).encode()
    fingerprint = hashlib.sha256(body).hexdigest()
    signature = agent.sign(body)

    store = SqliteStore(control_path)
    try:
        identities = IdentityRegistry(store)
        identities.register(agent.public_only())
        budgets = BudgetManager(store)
        budgets.set_budget(AGENT, Budget(spend_limit=10))
        approvals = ApprovalQueue(store)
        approvals.mark_sensitive(CAPABILITY)
        policy = PolicyEngine(identities, budgets, approvals=approvals)
        policy.allow_capability(AGENT, CAPABILITY)
        audit = AuditLog(store)
        ledger = OperationLedger(store)

        request = approvals.request(AGENT, CAPABILITY, 1.0, request_scope=fingerprint)
        denied = policy.authorize(agent_id=AGENT, capability=CAPABILITY,
                                  cost=1.0, signed_data=body, signature=signature,
                                  request_scope=fingerprint)
        if denied.allowed or not denied.needs_approval:
            raise AssertionError("unapproved consequential action was authorized")
        if not approve:
            if not approvals.deny(request.id):
                raise RuntimeError("approval denial failed")
            raise PermissionError("human approval denied; destination not contacted")
        if not approvals.approve(request.id):
            raise RuntimeError("human approval unavailable")
        allowed = policy.authorize(agent_id=AGENT, capability=CAPABILITY,
                                   cost=1.0, signed_data=body, signature=signature,
                                   request_scope=fingerprint)
        if not allowed.allowed or not approvals.consume(
                AGENT, CAPABILITY, request_scope=fingerprint):
            raise PermissionError("signed, scoped approval missing or already consumed")

        # Durable UNKNOWN is persisted BEFORE invoking the destination; no retry
        # can claim the same operation after this point.
        ledger.claim(AGENT, OPERATION, fingerprint)
        audit.record(actor=AGENT, action="synthetic_dispatch", source_protocol="local",
                     target_protocol="local", capability=CAPABILITY, decision="allow",
                     reason="signed identity and scoped approval consumed")
        with FencedSqliteTarget(target_path, sign=destination_key.sign) as destination:
            epoch = destination.acquire(scope=SCOPE, owner="synthetic-worker", ttl_seconds=60)
            try:
                destination.commit(scope=SCOPE, owner="synthetic-worker", epoch=epoch,
                                   agent_id=AGENT, operation_id=OPERATION,
                                   fingerprint=fingerprint, lose_ack=True)
            except TimeoutError:
                pass  # Unknown until independently read back.
            else:
                raise AssertionError("ACK fault injection failed")
            try:
                destination.commit(scope=SCOPE, owner="synthetic-worker", epoch=epoch,
                                   agent_id=AGENT, operation_id=OPERATION,
                                   fingerprint=fingerprint)
            except SqliteDuplicateEffect:
                duplicate_denied = True
            else:
                raise AssertionError("duplicate effect was accepted")
        if ledger.get(AGENT, OPERATION)["state"] != "unknown":
            raise AssertionError("lost ACK was incorrectly resolved")
        try:
            ledger.claim(AGENT, OPERATION, fingerprint)
        except OperationConflict:
            replay_denied = True
        else:
            raise AssertionError("unknown operation was replayed")

        if not allow_readback:
            raise ObservationUnavailable("authoritative observation deliberately unavailable")
        with SandboxReadOnlyObserver(target_path,
                                     destination_public_key_hex=destination_pub,
                                     sign=observer_key.sign) as observer:
            receipt, attestation = observer.observe(
                agent_id=AGENT, operation_id=OPERATION, fingerprint=fingerprint)
        trusted_observers = ObserverTrustRegistry([
            ObserverKey("independent-synthetic-observer", observer_pub, "active")
        ])
        verified = verify_registered_action_evidence(
            observer_registry=trusted_observers,
            observer_key_id="independent-synthetic-observer",
            destination_receipt=receipt, readback_attestation=attestation,
            agent_id=AGENT, operation_id=OPERATION, fingerprint=fingerprint,
            outcome="succeeded", external_reference=receipt["external_reference"],
            destination_key_hex=destination_pub,
        )
        # Verified evidence is a precondition for synthetic reviewer settlement.
        Reconciliation(store).record(agent_id=AGENT, operation_id=OPERATION,
                                     result="succeeded",
                                     external_reference=receipt["external_reference"],
                                     evidence_sha256=verified.destination_receipt_sha256,
                                     reviewer="synthetic-reviewer")
        audit.record(actor="synthetic-reviewer", action="evidence_reconciliation",
                     source_protocol="local", target_protocol="local",
                     capability=CAPABILITY, decision="allow",
                     reason="signed receipt + separate read-only observation verified")
        checkpoint = audit.checkpoint(audit_key.sign, audit_pub)
        if not verify_evidence_bundle([asdict(x) for x in audit.entries()],
                                      checkpoint, audit_pub):
            raise AssertionError("pinned audit checkpoint invalid")
        if ledger.get(AGENT, OPERATION)["state"] != "succeeded":
            raise AssertionError("verified operation was not reconciled")
        return {
            "scope": "synthetic SQLite only; operator independence not established",
            "approved_request_bound_to_target": True,
            "durable_unknown_before_reconciliation": True,
            "lost_ack_detected": True,
            "duplicate_destination_effect_denied": duplicate_denied,
            "duplicate_ledger_claim_denied": replay_denied,
            "signed_destination_receipt_valid": True,
            "registered_separate_observer_signature_valid": True,
            "reconciled_state": "succeeded",
            "verified_audit_checkpoint": True,
            "external_production_truth_verified": False,
            "operation_id": OPERATION,
            "destination_receipt_sha256": verified.destination_receipt_sha256,
            "readback_sha256": verified.readback_sha256,
            "audit_head": checkpoint["head_hash"],
        }
    finally:
        store.close()


def main():
    with tempfile.TemporaryDirectory(prefix="agentbridge-trust-evidence-") as path:
        report = run_synthetic_flow(path)
        print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
