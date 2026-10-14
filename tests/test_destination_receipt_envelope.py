"""Adversarial receipt-envelope regression checks.

Signed destination claims remain assertions by the key holder, not proof
of an independently observed remote side effect.
"""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.destination_receipts import (
    canonical_receipt_payload, verify_destination_receipt, UntrustedReceipt
)


def test_receipt_rejects_unsigned_fields_and_ambiguous_types():
    private = Ed25519PrivateKey.generate()
    key = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()
    receipt = {"agent_id": "agent", "operation_id": "id-01234567890123",
               "fingerprint": "fingerprint", "outcome": "succeeded",
               "external_reference": "ext-42"}
    receipt["signature_hex"] = private.sign(canonical_receipt_payload(receipt)).hex()
    def check(value):
        return verify_destination_receipt(
            value, agent_id="agent", operation_id="id-01234567890123",
            fingerprint="fingerprint", trusted_public_key_hex=key)
    assert len(check(receipt)) == 64
    for change in (
        {"reviewer_override": True},
        {"external_reference": ["ext-42"]},
        {"operation_id": 123},
        {"agent_id": "a" * 513},
        {"signature_hex": "bad"},
    ):
        candidate = {**receipt, **change}
        with pytest.raises(UntrustedReceipt):
            check(candidate)
    candidate = dict(receipt)
    del candidate["external_reference"]
    with pytest.raises(UntrustedReceipt):
        check(candidate)
