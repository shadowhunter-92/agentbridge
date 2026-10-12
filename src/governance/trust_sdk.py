"""Small gateway-independent evidence-verification SDK facade.

Embedding applications can verify signed action claims without starting the
AgentBridge control plane. Validated signatures and readbacks are evidence under
the caller's pinned-key and observation-trust assumptions, not universal proof
of remote or physical execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from .destination_receipts import verify_destination_receipt
from .readback_attestations import verify_readback_attestation
from .external_anchor import verify_anchored_audit


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


__all__ = ["VerifiedActionEvidence", "verify_action_evidence", "verify_anchored_audit"]


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
