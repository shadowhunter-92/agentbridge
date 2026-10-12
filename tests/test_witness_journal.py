"""Monotonic witness journal smoke and adversarial regressions."""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from src.governance.audit import AuditLog
from src.governance.identity import AgentIdentity
from src.governance.external_anchor import AnchorVerificationError, create_witness_statement
from src.governance.witness_journal import WitnessJournal
from cryptography.hazmat.primitives import serialization


def _pub(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def test_monotonic_witness_journal_across_restarts(tmp_path):
    log = AuditLog()
    checkpoint_signer = AgentIdentity.generate("auditor")
    verifier = Ed25519PrivateKey.generate()
    journal_path = str(tmp_path / "separate-witness.db")

    def add():
        log.record(actor="sandbox", action="route_call", source_protocol="mcp",
                   target_protocol="mcp", capability="read", decision="allow")

    def make_receipt():
        cp = log.checkpoint(checkpoint_signer.sign, checkpoint_signer.public_key_hex)
        receipt = create_witness_statement(
            cp, witness_id="remote-witness-1",
            witnessed_at="2026-10-12T00:00:00Z",
            anchor_reference="isolated-sandbox/witness",
            sign=verifier.sign)
        return cp, receipt

    kwargs = dict(checkpoint_key_hex=checkpoint_signer.public_key_hex,
                  witness_key_hex=_pub(verifier), witness_id="remote-witness-1")
    add()
    cp1, receipt1 = make_receipt()
    with WitnessJournal(journal_path, **kwargs) as journal:
        assert journal.accept([vars(i) for i in log.entries()], cp1, receipt1)["accepted"]
        assert journal.accept([vars(i) for i in log.entries()], cp1, receipt1)["duplicate"]
        assert journal.latest()["witness"] == receipt1
    add()
    cp2, receipt2 = make_receipt()
    with WitnessJournal(journal_path, **kwargs) as journal:
        assert journal.latest()["checkpoint"] == cp1
        assert journal.accept([vars(i) for i in log.entries()], cp2, receipt2)["seq"] == 2
        with pytest.raises(AnchorVerificationError, match="rollback"):
            journal.accept([vars(i) for i in log.entries()], cp1, receipt1)
        with pytest.raises(AnchorVerificationError):
            journal.accept([vars(i) for i in log.entries()][:-1], cp2, receipt2)
