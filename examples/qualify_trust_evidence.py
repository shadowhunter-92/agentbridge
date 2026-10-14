"""Run the local synthetic Trust -> Evidence acceptance workflow.

python -m examples.qualify_trust_evidence
All keys are ephemeral in memory. No network, cloud, or real business mutation.
Separate local keys demonstrate technical separation, not independent custody.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.approvals import ApprovalQueue
from src.governance.audit import AuditLog
from src.governance.budget import Budget, BudgetManager
from src.governance.destination_receipts import canonical_receipt_payload
from src.governance.external_anchor import (
    create_witness_statement,
    verify_anchored_audit,
)
from src.governance.fenced_sqlite_destination import (
    FencedSqliteTarget,
    SqliteFenceDenied,
)
from src.governance.gateway import GovernanceError, GovernanceGateway
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.operation_ledger import OperationConflict, OperationLedger
from src.governance.operator_review import canonical_review_payload
from src.governance.readback_attestations import canonical_readback_payload
from src.governance.reconciliation import Reconciliation, ReconciliationError
from src.governance.request_auth import canonical_payload
from src.governance.sandbox_readback import SandboxReadOnlyObserver
from src.governance.signing_trust_journal import (
    SigningTrustJournal,
    canonical_registry_payload,
    registry_digest,
)
from src.governance.store import SqliteStore
from src.governance.witness_journal import WitnessJournal
from src.protocols.canonical import CanonicalCall


def public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def signed_registry(controller, domain, revision, previous, keys):
    envelope = dict(
        domain=domain,
        revision=revision,
        previous_sha256=registry_digest(previous) if previous else "0" * 64,
        keys=sorted([dict(row) for row in keys], key=lambda row: row["key_id"]),
    )
    envelope["signature_hex"] = controller.sign(canonical_registry_payload(envelope)).hex()
    return envelope


@contextmanager
def environment(values):
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_qualification():
    with tempfile.TemporaryDirectory(prefix="agentbridge-qualification-") as tmp:
        return _run(Path(tmp))


def _run(root):
    destination, observer, replacement, reviewer, witness = [Ed25519PrivateKey.generate() for _ in range(5)]
    dest_controller, obs_controller = (
        Ed25519PrivateKey.generate(),
        Ed25519PrivateKey.generate(),
    )
    checks = {}
    with environment(
        {
            "AGENTBRIDGE_ENV": "production",
            "AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON": '{"qualified-agent":["synthetic_write"]}',
            "AGENTBRIDGE_RECONCILIATION_OPERATOR_KEYS_JSON": json.dumps({"reviewer": public(reviewer)}),
        }
    ):
        store = SqliteStore(str(root / "governance.sqlite"))
        try:
            trust = SigningTrustJournal(
                store,
                controller_keys={
                    "destination": public(dest_controller),
                    "readback": public(obs_controller),
                },
            )
            dest_registry = signed_registry(
                dest_controller,
                "destination",
                1,
                None,
                [
                    dict(
                        key_id="destination-1",
                        public_key_hex=public(destination),
                        state="active",
                    )
                ],
            )
            obs_registry = signed_registry(
                obs_controller,
                "readback",
                1,
                None,
                [
                    dict(
                        key_id="observer-1",
                        public_key_hex=public(observer),
                        state="active",
                    ),
                    dict(
                        key_id="observer-2",
                        public_key_hex=public(replacement),
                        state="staged",
                    ),
                ],
            )
            trust.publish(dest_registry)
            trust.publish(obs_registry)
            agent = AgentIdentity.generate("qualified-agent")
            identities = IdentityRegistry(store)
            identities.register(agent)
            budgets = BudgetManager(store)
            budgets.set_budget(agent.agent_id, Budget(spend_limit=10))
            approvals = ApprovalQueue(store)
            approvals.mark_sensitive("synthetic_write")
            audit = AuditLog(store)
            gateway = GovernanceGateway(identities=identities, budgets=budgets, approvals=approvals, audit=audit)
            operation = "qualified-operation-00001"
            wire = gateway.registry.get("openai").from_canonical_call(CanonicalCall("synthetic_write", {"value": 1}))
            body = json.dumps(
                dict(
                    src="openai",
                    dst="mcp",
                    wire=wire,
                    target_id="synthetic-destination",
                    operation_id=operation,
                ),
                sort_keys=True,
            ).encode()
            signed_data = canonical_payload(agent.agent_id, "qualification-nonce", body)
            target_path = str(root / "destination.sqlite")
            with FencedSqliteTarget(target_path, sign=destination.sign) as target:
                epoch = target.acquire(scope="synthetic", owner="leader-1", ttl_seconds=3)

                async def invoke(_wire):
                    entry = OperationLedger(store).get(agent.agent_id, operation)
                    target.commit(
                        scope="synthetic",
                        owner="leader-1",
                        epoch=epoch,
                        agent_id=agent.agent_id,
                        operation_id=operation,
                        fingerprint=entry["fingerprint"],
                        lose_ack=True,
                    )

                request = dict(
                    agent_id=agent.agent_id,
                    src_proto="openai",
                    dst_proto="mcp",
                    src_wire=wire,
                    invoke=invoke,
                    cost=2,
                    operation_id=operation,
                    target_id="synthetic-destination",
                    signed_data=signed_data,
                    signature=agent.sign(signed_data),
                    signed_body=body,
                    signed_nonce="qualification-nonce",
                )
                try:
                    asyncio.run(gateway.route_call(**request))
                except GovernanceError as exc:
                    if not exc.approval_id:
                        raise
                    checks["approval_required_before_dispatch"] = True
                    assert approvals.approve(exc.approval_id)
                else:
                    raise AssertionError("unapproved action dispatched")
                try:
                    asyncio.run(gateway.route_call(**request))
                except TimeoutError:
                    checks["lost_ack_leaves_unknown_and_reservation"] = OperationLedger(store).get(
                        agent.agent_id, operation
                    )["state"] == "unknown" and bool(store.get_budget(agent.agent_id)["reserved"])
                else:
                    raise AssertionError("lost acknowledgement not injected")
                try:
                    asyncio.run(gateway.route_call(**request))
                except OperationConflict:
                    checks["automatic_replay_denied"] = True
                else:
                    raise AssertionError("duplicate dispatched")
                fingerprint = OperationLedger(store).get(agent.agent_id, operation)["fingerprint"]

                def observe(signer):
                    with SandboxReadOnlyObserver(
                        target_path,
                        destination_public_key_hex=public(destination),
                        sign=signer.sign,
                    ) as reader:
                        try:
                            reader._db.execute("DELETE FROM sandbox_effects")
                        except sqlite3.OperationalError:
                            checks["observer_write_denied"] = True
                        else:
                            raise AssertionError("observer can mutate destination")
                        return reader.observe(
                            agent_id=agent.agent_id,
                            operation_id=operation,
                            fingerprint=fingerprint,
                        )

                receipt, proof = observe(observer)
                digest = hashlib.sha256(canonical_receipt_payload(receipt)).hexdigest()

                def settlement(proof, key_id):
                    statement = dict(
                        reviewer="reviewer",
                        agent_id=agent.agent_id,
                        operation_id=operation,
                        fingerprint=fingerprint,
                        outcome="succeeded",
                        external_reference=receipt["external_reference"],
                        destination_receipt_sha256=digest,
                        readback_sha256=hashlib.sha256(canonical_readback_payload(proof)).hexdigest(),
                    )
                    return dict(
                        agent_id=agent.agent_id,
                        operation_id=operation,
                        result="succeeded",
                        external_reference=receipt["external_reference"],
                        evidence_sha256=digest,
                        reviewer="reviewer",
                        destination_receipt=receipt,
                        readback_attestation=proof,
                        reviewer_signature_hex=reviewer.sign(canonical_review_payload(statement)).hex(),
                        destination_key_id="destination-1",
                        observer_key_id=key_id,
                    )

                reconciliation = Reconciliation(store, trust_journal=trust)
                kwargs = settlement(proof, "observer-1")
                tampered = dict(kwargs, reviewer_signature_hex="00" * 64)
                try:
                    reconciliation.record(**tampered)
                except ReconciliationError:
                    checks["forged_reviewer_denied"] = True
                else:
                    raise AssertionError("forged review settled")
                rotated = signed_registry(
                    obs_controller,
                    "readback",
                    2,
                    obs_registry,
                    [
                        dict(
                            key_id="observer-1",
                            public_key_hex=public(observer),
                            state="revoked",
                        ),
                        dict(
                            key_id="observer-2",
                            public_key_hex=public(replacement),
                            state="active",
                        ),
                    ],
                )
                trust.publish(rotated)
                try:
                    reconciliation.record(**kwargs)
                except ReconciliationError:
                    checks["revoked_observer_cannot_settle"] = True
                else:
                    raise AssertionError("revoked signer settled")
                receipt, proof = observe(replacement)
                final = reconciliation.record(**settlement(proof, "observer-2"))
                checks["rotated_observer_settles_once"] = final["state"] == "succeeded"
                checks["budget_settled"] = (
                    store.get_budget(agent.agent_id)["spent"] == 2 and not store.get_budget(agent.agent_id)["reserved"]
                )
                time.sleep(3.1)
                new_epoch = target.acquire(scope="synthetic", owner="leader-2")
                assert new_epoch > epoch
                try:
                    target.commit(
                        scope="synthetic",
                        owner="leader-1",
                        epoch=epoch,
                        agent_id=agent.agent_id,
                        operation_id="stale-operation-00001",
                        fingerprint=fingerprint,
                    )
                except SqliteFenceDenied:
                    checks["stale_leader_denied_at_destination"] = True
                else:
                    raise AssertionError("stale leader caused an effect")
                checks["exactly_one_synthetic_effect"] = (
                    target.db.execute("SELECT count(*) FROM sandbox_effects").fetchone()[0] == 1
                )
            records = store.load_audit()
            checks["settlement_in_intact_audit_chain"] = (
                AuditLog.verify_chain(records) and records[-1]["action"] == "reconcile_operation"
            )
            checkpoint = audit.checkpoint(reviewer.sign, public(reviewer))
            witnessed = create_witness_statement(
                checkpoint,
                witness_id="local-witness",
                witnessed_at=records[-1]["timestamp"],
                anchor_reference="synthetic-local-journal",
                sign=witness.sign,
            )
            with WitnessJournal(
                str(root / "separate-witness.sqlite"),
                checkpoint_key_hex=public(reviewer),
                witness_key_hex=public(witness),
                witness_id="local-witness",
            ) as journal:
                assert journal.accept(records, checkpoint, witnessed)["accepted"]
                checks["separate_witness_verifies_audit"] = verify_anchored_audit(
                    records,
                    checkpoint,
                    witnessed,
                    checkpoint_key_hex=public(reviewer),
                    witness_key_hex=public(witness),
                )["verified"]
            assert len(checks) == 12 and all(checks.values()), checks
            return dict(
                scope="local-synthetic-single-authority",
                passed=True,
                checks=checks,
                independent_custody=False,
                production_qualified=False,
                receipt=receipt,
                readback=proof,
                checkpoint=checkpoint,
                witness=witnessed,
                registries=[dest_registry, obs_registry, rotated],
                audit=records,
            )
        finally:
            store.close()


if __name__ == "__main__":
    print(json.dumps(run_qualification(), sort_keys=True, indent=2))
