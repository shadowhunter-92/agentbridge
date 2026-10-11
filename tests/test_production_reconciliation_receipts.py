"""Production settlement requires a pinned, action-bound destination receipt."""
import os
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger
from src.governance.reconciliation import Reconciliation, ReconciliationError
from src.governance.destination_receipts import canonical_receipt_payload
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
        rec=Reconciliation(store)
        kwargs=dict(agent_id="agent",operation_id="op-production-123456",
                    result="succeeded",external_reference="simulated-target:op/11",
                    evidence_sha256=digest,reviewer="operator")
        with pytest.raises(ReconciliationError, match="verified destination receipt"):
            rec.record(**kwargs)
        with pytest.raises(ReconciliationError, match="untrusted destination receipt"):
            rec.record(**kwargs,destination_receipt={**receipt,"outcome":"failed"})
        assert rec.record(**kwargs,destination_receipt=receipt)["state"]=="succeeded"
    finally:
        store.close()
