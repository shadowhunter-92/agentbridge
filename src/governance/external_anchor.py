"""Portable, two-party audit checkpoint witness envelopes.

A local signed checkpoint is not an externally anchored checkpoint. This
module provides a portable signed witness envelope and an offline verifier;
a separate trusted service must publish and retain the latest witness receipt.

Security invariants:
* Both checkpoint signer and witness public keys are pinned independently.
* The witness signs a hash of the entire canonical checkpoint, including its
  first-party signature and sequence, not merely an untrusted claimed head.
* An exported full audit chain is checked against the witnessed prefix.
* A stale but correctly signed witness cannot prove freshness by itself:
  callers MUST retrieve the latest witness directly from their trust domain.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .audit import AuditLog


class AnchorVerificationError(ValueError):
    pass


_WITNESS_FIELDS = ("version", "witness_id", "checkpoint_sha256", "seq",
                   "head_hash", "witnessed_at", "anchor_reference")


def _hex(value: Any, length: int) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(c in "0123456789abcdef" for c in value))


def checkpoint_digest(checkpoint: dict) -> str:
    if not isinstance(checkpoint, dict):
        raise AnchorVerificationError("checkpoint must be an object")
    try:
        payload = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AnchorVerificationError("checkpoint not canonicalizable") from exc
    return hashlib.sha256(payload).hexdigest()


def canonical_witness_payload(witness: dict) -> bytes:
    return json.dumps({field: witness[field] for field in _WITNESS_FIELDS},
                      sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def create_witness_statement(checkpoint: dict, *, witness_id: str,
                             witnessed_at: str, anchor_reference: str, sign):
    """Used only by an independently administered witness signing service.

    sign(bytes)->signature bytes. A signing service MUST independently validate
    checkpoint validity, monotonic history and storage before issuing this.
    This helper is not itself such a service or an external durable archive.
    """
    if not AuditLog.verify_checkpoint(checkpoint):
        raise AnchorVerificationError("checkpoint signature invalid")
    for value in (witness_id, witnessed_at, anchor_reference):
        if not isinstance(value, str) or not value or len(value) > 512:
            raise AnchorVerificationError("invalid witness metadata")
    witness = {
        "version": 1, "witness_id": witness_id,
        "checkpoint_sha256": checkpoint_digest(checkpoint),
        "seq": checkpoint["seq"], "head_hash": checkpoint["head_hash"],
        "witnessed_at": witnessed_at, "anchor_reference": anchor_reference,
    }
    signature = sign(canonical_witness_payload(witness))
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise AnchorVerificationError("witness signature must be Ed25519")
    return {**witness, "signature_hex": signature.hex()}


def verify_anchored_audit(records: list, checkpoint: dict, witness: dict, *,
                          checkpoint_key_hex: str, witness_key_hex: str) -> dict:
    """Verify retained full history and an independently signed witness receipt.

    The caller MUST source the witness (and trust roots) independently of the
    database or export being checked. A missing/forked/truncated history fails.
    """
    if not isinstance(checkpoint, dict) or not isinstance(witness, dict):
        raise AnchorVerificationError("invalid checkpoint or witness envelope")
    if set(witness) != {*_WITNESS_FIELDS, "signature_hex"}:
        raise AnchorVerificationError("unexpected or missing witness fields")
    if not isinstance(witness["version"], int) or witness["version"] != 1:
        raise AnchorVerificationError("unsupported witness version")
    for field in ("witness_id", "witnessed_at", "anchor_reference"):
        if not isinstance(witness[field], str) or not witness[field] or len(witness[field]) > 512:
            raise AnchorVerificationError("invalid witness metadata")
    if not isinstance(witness["seq"], int) or isinstance(witness["seq"], bool) or witness["seq"] < 0:
        raise AnchorVerificationError("invalid witness sequence")
    for field in ("checkpoint_sha256", "head_hash"):
        if not _hex(witness[field], 64):
            raise AnchorVerificationError("invalid witness digest")
    if not _hex(witness["signature_hex"], 128):
        raise AnchorVerificationError("invalid witness signature")
    if not _hex(checkpoint_key_hex, 64) or not _hex(witness_key_hex, 64):
        raise AnchorVerificationError("trusted keys must be canonical Ed25519 hex")
    if checkpoint_key_hex == witness_key_hex:
        raise AnchorVerificationError("independent witness key required")
    if (checkpoint.get("public_key_hex") != checkpoint_key_hex
            or not AuditLog.verify_checkpoint(checkpoint)):
        raise AnchorVerificationError("checkpoint not signed by pinned issuer")
    if (witness["checkpoint_sha256"] != checkpoint_digest(checkpoint)
            or witness["seq"] != checkpoint.get("seq")
            or witness["head_hash"] != checkpoint.get("head_hash")):
        raise AnchorVerificationError("witness does not match checkpoint")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(witness_key_hex)).verify(
            bytes.fromhex(witness["signature_hex"]), canonical_witness_payload(witness))
    except Exception as exc:
        raise AnchorVerificationError("invalid independent witness signature") from exc
    if not isinstance(records, list) or not AuditLog.verify_chain(records, require_genesis=True):
        raise AnchorVerificationError("audit chain invalid or not complete from genesis")
    seq = witness["seq"]
    if seq > len(records):
        raise AnchorVerificationError("audit was truncated or rolled back behind witness")
    expected = AuditLog.GENESIS if seq == 0 else records[seq - 1]["entry_hash"]
    if expected != witness["head_hash"]:
        raise AnchorVerificationError("audit history forked from witnessed checkpoint")
    return {"verified": True, "witness_id": witness["witness_id"],
            "witnessed_sequence": seq, "head_hash": expected,
            "audited_entries": len(records)}
