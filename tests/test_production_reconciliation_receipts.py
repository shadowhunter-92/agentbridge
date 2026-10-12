"""Production settlement requires a pinned, action-bound destination receipt."""
import os
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger
from src.governance.reconciliation import Reconciliation, ReconciliationError
from src.governance.destination_receipts import canonical_receipt_payload
from src.governance.readback_attestations import canonical_readback_payload
from src.governance.operator_review import canonical_review_payload
import json
import time
import hashlib


def test_production_reconciliation_rejects_untrusted_and_accepts_pinned(tmp_path, monkeypatch):
    store=SqliteStore(str(tmp_path/"verified.db"))
    try:
        OperationLedger(store).claim("agent","op-production-123456","fingerprint")
        private=Ed25519PrivateKey.generate()
        pub=private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw).hex()
        receipt=dict(agent_id="agent",operation_id="op-production-123456",
                     fingerprint="fingerprint",outcome="succeeded",
                     external_reference="simulated-target:op/11")
        receipt["signature_hex"]=private.sign(canonical_receipt_payload(receipt)).hex()
        digest=hashlib.sha256(canonical_receipt_payload(receipt)).hexdigest()
        monkeypatch.setenv("AGENTBRIDGE_ENV","production")
        monkeypatch.setenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX",pub)
        readback_private=Ed25519PrivateKey.generate()
        readback_key=readback_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw).hex()
        monkeypatch.setenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX",readback_key)
        proof=dict(agent_id="agent",operation_id="op-production-123456",
                   fingerprint="fingerprint",outcome="succeeded",
                   external_reference="simulated-target:op/11",
                   observed_at=int(time.time()),source="independent-readonly-test",
                   source_evidence_sha256=hashlib.sha256(b"readback").hexdigest(),
                   destination_receipt_sha256=digest)
        proof["signature_hex"]=readback_private.sign(canonical_readback_payload(proof)).hex()
        reviewer_private=Ed25519PrivateKey.generate()
        reviewer_key=reviewer_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw).hex()
        monkeypatch.setenv("AGENTBRIDGE_RECONCILIATION_OPERATOR_KEYS_JSON",
                           json.dumps({"operator": reviewer_key}))
        reviewer_statement=dict(
            reviewer="operator", agent_id="agent",
            operation_id="op-production-123456", fingerprint="fingerprint",
            outcome="succeeded", external_reference="simulated-target:op/11",
            destination_receipt_sha256=digest,
            readback_sha256=hashlib.sha256(canonical_readback_payload(proof)).hexdigest())
        reviewer_signature_hex=reviewer_private.sign(
            canonical_review_payload(reviewer_statement)).hex()
        rec=Reconciliation(store)
        kwargs=dict(agent_id="agent",operation_id="op-production-123456",
                    result="succeeded",external_reference="simulated-target:op/11",
                    evidence_sha256=digest,reviewer="operator")
        with pytest.raises(ReconciliationError, match="verified destination receipt"):
            rec.record(**kwargs)
        with pytest.raises(ReconciliationError, match="untrusted destination receipt"):
            rec.record(**kwargs,destination_receipt={**receipt,"outcome":"failed"})
        with pytest.raises(ReconciliationError, match="independent state-readback"):
            rec.record(**kwargs,destination_receipt=receipt)
        with pytest.raises(ReconciliationError, match="untrusted independent"):
            rec.record(**kwargs,destination_receipt=receipt,
                       readback_attestation={**proof,"outcome":"failed"})
        with pytest.raises(ReconciliationError, match="authorized signed operator"):
            rec.record(**kwargs,destination_receipt=receipt,readback_attestation=proof)
        assert rec.record(**kwargs,destination_receipt=receipt,
                          readback_attestation=proof,
                          reviewer_signature_hex=reviewer_signature_hex)["state"]=="succeeded"
    finally:
        store.close()
