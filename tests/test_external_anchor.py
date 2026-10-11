"""Two independent signatures and a full audit history are required."""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.audit import AuditLog
from src.governance.external_anchor import (
    AnchorVerificationError, create_witness_statement, verify_anchored_audit,
)
from src.governance.identity import AgentIdentity


def pub(key):
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw).hex()


def test_independently_witnessed_audit_detects_forks_and_rollback():
    log = AuditLog()
    signer = AgentIdentity.generate("audit-signer")
    witness_key = Ed25519PrivateKey.generate()
    for i in range(3):
        log.record(actor="agent", action="route_call", source_protocol="mcp",
                   target_protocol="a2a", capability="read", decision="allow")
    checkpoint = log.checkpoint(signer.sign, signer.public_key_hex)
    witness = create_witness_statement(
        checkpoint, witness_id="test-witness",
        witnessed_at="2026-10-11T12:00:00Z", anchor_reference="immutable-test://anchor-1",
        sign=witness_key.sign)
    args = dict(checkpoint_key_hex=signer.public_key_hex, witness_key_hex=pub(witness_key))
    records = [vars(item).copy() for item in log.entries()]
    assert verify_anchored_audit(records, checkpoint, witness, **args)["verified"]
    with pytest.raises(AnchorVerificationError):
        verify_anchored_audit(records[:-1], checkpoint, witness, **args)
    with pytest.raises(AnchorVerificationError):
        verify_anchored_audit([{**records[0], "actor": "tampered"}, *records[1:]],
                              checkpoint, witness, **args)
    with pytest.raises(AnchorVerificationError):
        verify_anchored_audit(records, checkpoint,
                              {**witness, "anchor_reference": "rewritten"}, **args)
    with pytest.raises(AnchorVerificationError):
        verify_anchored_audit(records, checkpoint, witness,
                              checkpoint_key_hex=signer.public_key_hex,
                              witness_key_hex=signer.public_key_hex)
    with pytest.raises(AnchorVerificationError):
        verify_anchored_audit(records, checkpoint, witness,
                              checkpoint_key_hex="0"*64, witness_key_hex=pub(witness_key))
