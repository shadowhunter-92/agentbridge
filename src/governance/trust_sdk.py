"""Small gateway-independent evidence-verification SDK facade.

Embedding applications can verify signed action claims without starting the
AgentBridge control plane. Validated signatures and readbacks are evidence under
the caller's pinned-key and observation-trust assumptions, not universal proof
of remote or physical execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from .destination_receipts import verify_destination_receipt, verify_queued_destination_receipt
from .external_anchor import verify_anchored_audit
from .queued_destination_contract import (
    QUEUED_RESULT_ENVELOPE_LIMIT_BYTES,
    normalize_queued_descriptor,
    queued_result_envelope_bytes,
)
from .readback_attestations import verify_queued_readback_attestation, verify_readback_attestation


@dataclass(frozen=True)
class VerifiedActionEvidence:
    agent_id: str
    operation_id: str
    fingerprint: str
    outcome: str
    external_reference: str
    destination_receipt_sha256: str
    readback_sha256: str


def verify_action_evidence(*, destination_receipt: dict, readback_attestation: dict,
                           agent_id: str, operation_id: str, fingerprint: str,
                           outcome: str, external_reference: str,
                           destination_key_hex: str, readback_key_hex: str,
                           now: int | None = None) -> VerifiedActionEvidence:
    """Check a statement and a separately signed authoritative-readback claim.

    The embedding host is responsible for key enrollment, revocation, the
    read-only observer's independence, and confirming its source of truth.
    """
    receipt_digest = verify_destination_receipt(
        destination_receipt, agent_id=agent_id, operation_id=operation_id,
        fingerprint=fingerprint, trusted_public_key_hex=destination_key_hex)
    if (destination_receipt["outcome"] != outcome
            or destination_receipt["external_reference"] != external_reference):
        raise ValueError("destination receipt disagrees with expected result")
    readback_digest = verify_readback_attestation(
        readback_attestation, agent_id=agent_id, operation_id=operation_id,
        fingerprint=fingerprint, outcome=outcome,
        external_reference=external_reference,
        destination_receipt_sha256=receipt_digest,
        trusted_readback_key_hex=readback_key_hex,
        destination_key_hex=destination_key_hex, now=now)
    return VerifiedActionEvidence(
        agent_id=agent_id, operation_id=operation_id, fingerprint=fingerprint,
        outcome=outcome, external_reference=external_reference,
        destination_receipt_sha256=receipt_digest,
        readback_sha256=readback_digest,
    )


__all__ = ["VerifiedActionEvidence", "verify_action_evidence", "verify_anchored_audit",
           "verify_registered_action_evidence", "verify_journaled_action_evidence"]


def verify_registered_action_evidence(*, observer_registry, observer_key_id: str,
                                      **kwargs) -> VerifiedActionEvidence:
    """Verify evidence only against an actively enrolled observer key.

    Caller must independently provision and refresh the operator-controlled
    registry. Revoked/staged keys cannot sign *new* production settlements.
    This does not retroactively erase previously accepted audit evidence.
    """
    from .observer_key_registry import ObserverTrustRegistry
    if not isinstance(observer_registry, ObserverTrustRegistry):
        raise TypeError("a pinned observer trust registry is required")
    if "readback_key_hex" in kwargs:
        raise ValueError("caller cannot override enrolled readback public key")
    return verify_action_evidence(
        readback_key_hex=observer_registry.resolve_active(observer_key_id),
        **kwargs)


def verify_journaled_action_evidence(*, trust_journal, destination_key_id: str,
                                    observer_key_id: str, **kwargs) -> VerifiedActionEvidence:
    """Verify against current controller-signed policies for BOTH signers.

    The journal and its pinned controller keys belong to the embedding operator.
    Verification loads the latest authenticated revisions under the rotation
    lock. This is an evidence check, not a settlement or durable acceptance.
    """
    from .signing_trust_journal import SigningTrustJournal
    if not isinstance(trust_journal, SigningTrustJournal):
        raise TypeError("operator-configured signing trust journal required")
    if {"destination_key_hex", "readback_key_hex"} & kwargs.keys():
        raise ValueError("caller cannot override enrolled signing keys")
    with trust_journal._transaction(write=False) as cur:
        keys = trust_journal.settlement_keys(cur, destination_key_id=destination_key_id,
                                            observer_key_id=observer_key_id)
        return verify_action_evidence(destination_key_hex=keys["destination_key_hex"],
                                      readback_key_hex=keys["readback_key_hex"], **kwargs)


@dataclass(frozen=True)
class VerifiedQueuedActionEvidence:
    tenant_id: str
    store_id: str
    owner_id: str
    agent_id: str
    task_id: str
    context_id: str
    operation_id: str
    fingerprint: str
    intent_sha256: str
    admission_link_sha256: str
    target_id: str
    destination_id: str
    attempt_id: str
    fence_epoch: int
    authorization_sha256: str
    action_sha256: str
    result_sha256: str
    destination_receipt_sha256: str
    readback_sha256: str
    outcome: str
    external_reference: str
    committed_at: float


def verify_queued_action_evidence(
    *, authorization, action_bytes, descriptor, result, destination_receipt, readback_attestation,
    now=None,
) -> VerifiedQueuedActionEvidence:
    """Verify exact independent queued evidence, including its immutable limit.

    Execution expiry is checked against signed commit time. Only observation
    freshness uses current time, so expired execution authority can be charged
    from fresh historical readback without regaining permission to execute.
    """
    receipt_digest = verify_queued_destination_receipt(
        destination_receipt, authorization=authorization, action_bytes=action_bytes,
        descriptor=descriptor, result=result)
    readback_digest = verify_queued_readback_attestation(
        readback_attestation, authorization=authorization, action_bytes=action_bytes,
        descriptor=descriptor, result=result, destination_receipt=destination_receipt, now=now)
    envelope = queued_result_envelope_bytes(
        authorization=authorization, result=result, destination_receipt=destination_receipt,
        readback_attestation=readback_attestation)
    if len(envelope) > min(authorization["result_limit_bytes"], QUEUED_RESULT_ENVELOPE_LIMIT_BYTES):
        raise ValueError("queued result and evidence exceed immutable result allowance")
    fields = {name: authorization[name] for name in (
        "tenant_id", "store_id", "owner_id", "agent_id", "task_id", "context_id", "operation_id", "fingerprint",
        "intent_sha256", "admission_link_sha256", "target_id", "destination_id", "attempt_id", "fence_epoch", "action_sha256",
    )}
    return VerifiedQueuedActionEvidence(
        **fields, authorization_sha256=destination_receipt["authorization_sha256"],
        result_sha256=destination_receipt["result_sha256"], destination_receipt_sha256=receipt_digest,
        readback_sha256=readback_digest, outcome="succeeded", external_reference=result["effect_id"],
        committed_at=destination_receipt["committed_at"],
    )


def verify_journaled_queued_action_evidence(*, trust_journal, descriptor, **kwargs) -> VerifiedQueuedActionEvidence:
    """Reuse current destination/observer policies without a second trust stack."""
    from .signing_trust_journal import SigningTrustJournal, TrustJournalDenied

    if not isinstance(trust_journal, SigningTrustJournal):
        raise TypeError("operator-configured signing trust journal required")
    descriptor = normalize_queued_descriptor(descriptor)
    with trust_journal._transaction(write=False) as cur:
        keys = trust_journal.settlement_keys(
            cur, destination_key_id=descriptor["destination_key_id"], observer_key_id=descriptor["observer_key_id"])
        if (keys["destination_key_hex"] != descriptor["destination_public_key_hex"]
                or keys["readback_key_hex"] != descriptor["observer_public_key_hex"]):
            raise TrustJournalDenied("current enrolled signing keys disagree with immutable queued descriptor")
        return verify_queued_action_evidence(descriptor=descriptor, **kwargs)


__all__ += ["VerifiedQueuedActionEvidence", "verify_queued_action_evidence", "verify_journaled_queued_action_evidence"]
