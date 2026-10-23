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

from .destination_receipts import verify_queued_destination_receipt
from .queued_destination_contract import (
    MAX_READBACK_BYTES,
    canonical_queued_json,
    normalize_queued_descriptor,
    queued_hex,
    queued_seconds,
)


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
    if not isinstance(trusted_readback_key_hex, str) or not isinstance(destination_key_hex, str):
        raise UntrustedReadback("readback signer trust roots missing")
    try:
        readback_public = bytes.fromhex(trusted_readback_key_hex)
        destination_public = bytes.fromhex(destination_key_hex)
        if len(readback_public) != 32 or len(destination_public) != 32:
            raise ValueError("public key must be 32 bytes")
    except ValueError as exc:
        raise UntrustedReadback("malformed readback or destination public key") from exc
    if readback_public == destination_public:
        raise UntrustedReadback("readback signer must be an independent trust root")
    now = int(time.time()) if now is None else now
    if not isinstance(now, int) or isinstance(now, bool) or max_age_seconds <= 0:
        raise UntrustedReadback("invalid verifier time configuration")
    if not now - max_age_seconds <= proof["observed_at"] <= now + 30:
        raise UntrustedReadback("readback attestation is stale or from the future")
    try:
        raw_key = readback_public
        signature = bytes.fromhex(proof["signature_hex"])
        Ed25519PublicKey.from_public_bytes(raw_key).verify(
            signature, canonical_readback_payload(proof))
    except Exception as exc:
        raise UntrustedReadback("readback attestation signature invalid") from exc
    return hashlib.sha256(canonical_readback_payload(proof)).hexdigest()


_QUEUED_READBACK_FIELDS = (
    "domain", "authorization_sha256", "tenant_id", "agent_id", "operation_id", "fingerprint",
    "target_id", "destination_id", "attempt_id", "fence_epoch", "action_sha256", "outcome",
    "external_reference", "committed_at", "result_sha256", "destination_receipt_sha256",
    "observed_at", "source", "source_evidence_sha256", "observer_key_id",
)
QUEUED_READBACK_SOURCE = "queued-sqlite:read-only-authoritative-sql-v2"


def canonical_queued_readback_payload(proof):
    return canonical_queued_json({name: proof[name] for name in _QUEUED_READBACK_FIELDS})


def queued_source_evidence_sha256(*, authorization, action_bytes, result, destination_receipt):
    """Digest the exact independently fetched and verified committed values."""
    return hashlib.sha256(canonical_queued_json({
        "authorization": authorization, "action_hex": action_bytes.hex(), "result": result,
        "destination_receipt": destination_receipt,
    })).hexdigest()


def verify_queued_readback_attestation(
    proof, *, authorization, action_bytes, descriptor, result, destination_receipt,
    now=None, max_age_seconds=300,
):
    """Strict v2 readback over an already committed historical execution."""
    try:
        descriptor = normalize_queued_descriptor(descriptor)
        receipt_digest = verify_queued_destination_receipt(
            destination_receipt, authorization=authorization, action_bytes=action_bytes,
            descriptor=descriptor, result=result)
        if not isinstance(proof, dict) or set(proof) != {*_QUEUED_READBACK_FIELDS, "signature_hex"}:
            raise UntrustedReadback("unexpected or missing queued readback fields")
        if len(canonical_queued_json(proof)) > MAX_READBACK_BYTES:
            raise UntrustedReadback("queued readback exceeds byte limit")
        expected = {name: destination_receipt[name] for name in (
            "authorization_sha256", "tenant_id", "agent_id", "operation_id", "fingerprint", "target_id",
            "destination_id", "attempt_id", "fence_epoch", "action_sha256", "outcome", "external_reference",
            "committed_at", "result_sha256",
        )}
        expected.update({
            "domain": "agentbridge.queued-readback.v2", "destination_receipt_sha256": receipt_digest,
            "source": QUEUED_READBACK_SOURCE, "observer_key_id": descriptor["observer_key_id"],
            "source_evidence_sha256": queued_source_evidence_sha256(
                authorization=authorization, action_bytes=action_bytes, result=result,
                destination_receipt=destination_receipt),
        })
        if any(proof[name] != value or type(proof[name]) is not type(value) for name, value in expected.items()):
            raise UntrustedReadback("queued readback disagrees with exact committed evidence")
        observed = proof["observed_at"]
        now = int(time.time()) if now is None else now
        if (type(now) is not int or type(observed) is not int or type(max_age_seconds) is not int
                or max_age_seconds <= 0 or not queued_seconds(observed)
                or not now - max_age_seconds <= observed <= now + 30
                or proof["committed_at"] > observed + 30):
            raise UntrustedReadback("queued readback is stale or from the future")
        if not queued_hex(proof["signature_hex"], 128):
            raise UntrustedReadback("invalid queued readback signature encoding")
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(descriptor["observer_public_key_hex"])).verify(
            bytes.fromhex(proof["signature_hex"]), canonical_queued_readback_payload(proof))
    except Exception as exc:
        if isinstance(exc, UntrustedReadback):
            raise
        raise UntrustedReadback("untrusted queued readback evidence") from exc
    return hashlib.sha256(canonical_queued_json(proof)).hexdigest()
