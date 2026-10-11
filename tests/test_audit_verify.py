"""External trust-anchor verification regression cases."""
import pytest
from src.governance.audit import AuditLog
from src.governance.audit_verify import verify_evidence_bundle, AuditVerificationError
from src.governance.identity import AgentIdentity


def test_signed_checkpoint_with_pinned_signer_and_real_log():
    log = AuditLog()
    for i in range(3):
        log.record(actor="agent", action="route_call", source_protocol="mcp",
                   target_protocol="a2a", capability="read", decision="allow",
                   reason=str(i))
    signer = AgentIdentity.generate("audit")
    checkpoint = log.checkpoint(signer.sign, signer.public_key_hex)
    records = [vars(e).copy() for e in log.entries()]
    assert verify_evidence_bundle(records, checkpoint, signer.public_key_hex)
    other = AgentIdentity.generate("forger")
    with pytest.raises(AuditVerificationError, match="not trusted"):
        verify_evidence_bundle(records, checkpoint, other.public_key_hex)
    tampered = [dict(rec) for rec in records]
    tampered[0]["reason"] = "changed"
    with pytest.raises(AuditVerificationError, match="broken"):
        verify_evidence_bundle(tampered, checkpoint, signer.public_key_hex)


def test_truncated_tail_requires_correct_predecessor_hash():
    log = AuditLog()
    for i in range(2):
        log.record(actor="agent", action="route_call", source_protocol="mcp",
                   target_protocol="a2a", capability="read", decision="allow")
    signer = AgentIdentity.generate("audit")
    cp = log.checkpoint(signer.sign, signer.public_key_hex)
    for i in range(3):
        log.record(actor="agent", action="route_call", source_protocol="mcp",
                   target_protocol="a2a", capability="read", decision="allow")
    records = [vars(e).copy() for e in log.entries()][2:]
    assert verify_evidence_bundle(records, cp, signer.public_key_hex)
    edited = [dict(e) for e in records]
    edited[0]["prev_hash"] = "0" * 64
    with pytest.raises(AuditVerificationError):
        verify_evidence_bundle(edited, cp, signer.public_key_hex)


def test_checkpoint_signature_validity_alone_is_not_a_trust_policy():
    log = AuditLog()
    signer = AgentIdentity.generate("attacker")
    cp = log.checkpoint(signer.sign, signer.public_key_hex)
    assert log.verify_checkpoint(cp)  # cryptographically valid
    other = AgentIdentity.generate("actual-operator")
    with pytest.raises(AuditVerificationError, match="not trusted"):
        verify_evidence_bundle([], cp, other.public_key_hex)
