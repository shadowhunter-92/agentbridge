"""Independently administered, operation-bound state-readback attestations.

The readback attestor MUST query the authoritative destination state using its
own read-only credentials and signing key. This module verifies the attestation,
not the underlying remote state; a deployment must validate the attestor itself.
The destination receipt signer and readback signer must be separate trust roots.
"""
import hashlib
import json
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class UntrustedReadback(ValueError):
    pass


_FIELDS = ("agent_id", "operation_id", "fingerprint", "outcome",
           "external_reference", "observed_at", "source",
           "source_evidence_sha256", "destination_receipt_sha256")


def canonical_readback_payload(proof):
    return json.dumps({field: proof[field] for field in _FIELDS},
                      sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def verify_readback_attestation(
    proof, *, agent_id, operation_id, fingerprint, outcome,
    external_reference, destination_receipt_sha256, trusted_readback_key_hex,
    destination_key_hex, now=None, max_age_seconds=300,
):
    """Validate an independently keyed readback statement bound to one operation.

    The signer needs a separately administered key and independently sourced
    evidence. Freshness prevents unbounded reuse; operation identity and
    fingerprints prevent transferring an attestation to another request.
    """
    if not isinstance(proof, dict) or set(proof) != {*_FIELDS, "signature_hex"}:
        raise UntrustedReadback("missing or unrecognized readback fields")
    if any(not isinstance(proof[name], str) or not proof[name]
           or len(proof[name]) > 512
           for name in ("agent_id", "operation_id", "fingerprint",
                        "external_reference", "source")):
        raise UntrustedReadback("invalid readback identity/source")
    if proof["outcome"] not in ("succeeded", "failed"):
        raise UntrustedReadback("invalid readback outcome")
    if not isinstance(proof["observed_at"], int) or isinstance(proof["observed_at"], bool):
        raise UntrustedReadback("readback observation must have integer epoch seconds")
    if any(not isinstance(proof[field], str) or len(proof[field]) != 64
           or any(char not in "0123456789abcdef" for char in proof[field])
           for field in ("source_evidence_sha256", "destination_receipt_sha256")):
        raise UntrustedReadback("invalid readback evidence digest")
    if (not isinstance(proof["signature_hex"], str)
            or len(proof["signature_hex"]) != 128):
        raise UntrustedReadback("invalid readback signature encoding")
    if (proof["agent_id"] != agent_id or proof["operation_id"] != operation_id
            or proof["fingerprint"] != fingerprint
            or proof["outcome"] != outcome
            or proof["external_reference"] != external_reference
            or proof["destination_receipt_sha256"] != destination_receipt_sha256):
        raise UntrustedReadback("readback not bound to the exact destination receipt")
    if (not isinstance(trusted_readback_key_hex, str)
            or not isinstance(destination_key_hex, str)
            or trusted_readback_key_hex == destination_key_hex):
        raise UntrustedReadback("readback signer must be an independent trust root")
    now = int(time.time()) if now is None else now
    if not isinstance(now, int) or isinstance(now, bool) or max_age_seconds <= 0:
        raise UntrustedReadback("invalid verifier time configuration")
    if not now - max_age_seconds <= proof["observed_at"] <= now + 30:
        raise UntrustedReadback("readback attestation is stale or from the future")
    try:
        raw_key = bytes.fromhex(trusted_readback_key_hex)
        if len(raw_key) != 32:
            raise ValueError("wrong Ed25519 public key length")
        signature = bytes.fromhex(proof["signature_hex"])
        Ed25519PublicKey.from_public_bytes(raw_key).verify(
            signature, canonical_readback_payload(proof))
    except Exception as exc:
        raise UntrustedReadback("readback attestation signature invalid") from exc
    return hashlib.sha256(canonical_readback_payload(proof)).hexdigest()
