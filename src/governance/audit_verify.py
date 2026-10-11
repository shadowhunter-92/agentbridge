"""Offline verification of AgentBridge audit evidence against an independently pinned signer.

A self-advertised public key in a checkpoint is NOT trust. Supply the public
key through an independent trust channel. A checkpoint authenticates the
asserted head, not that an external side effect actually happened.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from .audit import AuditLog


class AuditVerificationError(ValueError):
    pass


def verify_evidence_bundle(records: List[Dict[str, Any]],
                           checkpoint: Dict[str, Any],
                           trusted_public_key_hex: str) -> bool:
    """Verify a checkpoint from an independently trusted key and its matching chain.

    Supports the full log through checkpoint, including newer events after the
    signed checkpoint, and logs truncated *after* a checkpoint's head.
    For a truncated log, its first entry must refer to the signed head and begin
    at checkpoint.seq. If a longer untruncated history is present, the signed
    checkpoint must match the preceding entry.
    """
    if not isinstance(records, list) or not isinstance(checkpoint, dict):
        raise AuditVerificationError("invalid evidence bundle")
    if not isinstance(trusted_public_key_hex, str) or len(trusted_public_key_hex) != 64:
        raise AuditVerificationError("trusted signer key must be 32-byte hex")
    if checkpoint.get("public_key_hex") != trusted_public_key_hex:
        raise AuditVerificationError("checkpoint signer is not trusted")
    if not AuditLog.verify_checkpoint(checkpoint):
        raise AuditVerificationError("invalid checkpoint signature")

    seq = checkpoint.get("seq")
    head = checkpoint.get("head_hash")
    if not isinstance(seq, int) or seq < 0 or not isinstance(head, str):
        raise AuditVerificationError("invalid checkpoint position")

    ordered = sorted(records, key=lambda e: e["seq"])
    if not AuditLog.verify_chain(ordered, require_genesis=not ordered or ordered[0]["seq"] == 0):
        raise AuditVerificationError("broken audit chain")
    if not ordered:
        if seq != 0 or head != AuditLog.GENESIS:
            raise AuditVerificationError("non-empty checkpoint but no log")
        return True

    first = ordered[0]
    if first["seq"] > seq:
        raise AuditVerificationError("unanchored history gap before checkpoint")
    if first["seq"] == seq:
        if first["prev_hash"] != head:
            raise AuditVerificationError("truncated history fails checkpoint linkage")
        return True
    # There are entries before the checkpoint. Verify the observed head at seq - 1.
    if seq == 0:
        if head != AuditLog.GENESIS:
            raise AuditVerificationError("genesis checkpoint mismatch")
        return True
    preceding = next((entry for entry in ordered if entry["seq"] == seq - 1), None)
    if preceding is None or preceding["entry_hash"] != head:
        raise AuditVerificationError("signed checkpoint disagrees with chain")
    return True
