"""Pinned-operator signed approval for settling an uncertain action.

A reviewer name alone is not authentication. The reviewer signs the exact
operation, destination/readback digests, and proposed outcome, and the key is
looked up in an administrator-owned allowlist. Revocation removes the key.
"""
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class UntrustedReviewer(ValueError):
    pass


_FIELDS = ("reviewer", "agent_id", "operation_id", "fingerprint", "outcome",
           "external_reference", "destination_receipt_sha256", "readback_sha256")


def canonical_review_payload(statement):
    return b"agentbridge-operator-review-v1:" + json.dumps(
        {key: statement[key] for key in _FIELDS},
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def verify_operator_review(*, reviewer, agent_id, operation_id, fingerprint,
                           outcome, external_reference, destination_receipt_sha256,
                           readback_sha256, signature_hex, trusted_operators_json):
    if not isinstance(trusted_operators_json, str):
        raise UntrustedReviewer("reconciliation operator registry required")
    try:
        allowed = json.loads(trusted_operators_json)
    except (ValueError, TypeError) as exc:
        raise UntrustedReviewer("operator registry invalid") from exc
    if not isinstance(allowed, dict) or not allowed:
        raise UntrustedReviewer("operator registry empty or invalid")
    key = allowed.get(reviewer)
    if not isinstance(key, str) or len(key) != 64 or not isinstance(signature_hex, str) or len(signature_hex) != 128:
        raise UntrustedReviewer("reviewer not enrolled or signature missing")
    statement = dict(reviewer=reviewer, agent_id=agent_id, operation_id=operation_id,
                     fingerprint=fingerprint, outcome=outcome,
                     external_reference=external_reference,
                     destination_receipt_sha256=destination_receipt_sha256,
                     readback_sha256=readback_sha256)
    try:
        public = bytes.fromhex(key)
        signature = bytes.fromhex(signature_hex)
        if len(public) != 32 or len(signature) != 64:
            raise ValueError("bad Ed25519 key encoding")
        Ed25519PublicKey.from_public_bytes(public).verify(
            signature, canonical_review_payload(statement))
    except Exception as exc:
        raise UntrustedReviewer("reviewer signature invalid") from exc
    return True
