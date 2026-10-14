import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.destination_receipts import (
    canonical_receipt_payload, verify_destination_receipt, UntrustedReceipt)


def test_destination_receipt_binds_operation_and_pinned_signer():
    private=Ed25519PrivateKey.generate()
    pub=private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw).hex()
    receipt=dict(agent_id="agent",operation_id="id-01234567890123",
                 fingerprint="requesthash",outcome="succeeded",
                 external_reference="remote:test:42")
    receipt["signature_hex"]=private.sign(canonical_receipt_payload(receipt)).hex()
    assert len(verify_destination_receipt(
        receipt,agent_id="agent",operation_id="id-01234567890123",
        fingerprint="requesthash",trusted_public_key_hex=pub))==64
    with pytest.raises(UntrustedReceipt):
        verify_destination_receipt(receipt,agent_id="agent",operation_id="other",
                                   fingerprint="requesthash",trusted_public_key_hex=pub)
    with pytest.raises(UntrustedReceipt):
        verify_destination_receipt(receipt,agent_id="agent",operation_id="id-01234567890123",
                                   fingerprint="other",trusted_public_key_hex=pub)
    fake=Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw).hex()
    with pytest.raises(UntrustedReceipt):
        verify_destination_receipt(receipt,agent_id="agent",operation_id="id-01234567890123",
                                   fingerprint="requesthash",trusted_public_key_hex=fake)
