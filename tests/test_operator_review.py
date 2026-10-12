"""Operator signatures bind reconciliation approval to one exact operation and evidence pair."""
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from src.governance.operator_review import (
    UntrustedReviewer, canonical_review_payload, verify_operator_review,
)


def _pub(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def test_operator_review_rejects_spoofing_swapped_results_and_revocation():
    approved = Ed25519PrivateKey.generate()
    attacker = Ed25519PrivateKey.generate()
    statement = dict(reviewer="operator-a", agent_id="agent",
                     operation_id="operation-0000001", fingerprint="req-fingerprint",
                     outcome="succeeded", external_reference="destination:item:1",
                     destination_receipt_sha256="a" * 64, readback_sha256="b" * 64)
    signature = approved.sign(canonical_review_payload(statement)).hex()
    registry = json.dumps({"operator-a": _pub(approved)})
    def verify(**changes):
        args = dict(statement, signature_hex=signature, trusted_operators_json=registry)
        args.update(changes)
        return verify_operator_review(**args)
    assert verify()
    for changed in (
        {"outcome": "failed"},
        {"readback_sha256": "0" * 64},
        {"operation_id": "different"},
        {"reviewer": "operator-b"},
        {"signature_hex": attacker.sign(canonical_review_payload(statement)).hex()},
        {"trusted_operators_json": json.dumps({"operator-a": _pub(attacker)})},
        {"trusted_operators_json": "{}"},
    ):
        with pytest.raises(UntrustedReviewer):
            verify(**changed)
