"""Reconciliation regression tests: immutable evidence, no duplicate decisions."""
import hashlib
import pytest
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger, OperationConflict
from src.governance.reconciliation import Reconciliation, ReconciliationError


def test_record_verified_by_operator_and_single_finalization(tmp_path):
    db = str(tmp_path/"ops.db")
    a,b=SqliteStore(db),SqliteStore(db)
    try:
        first=OperationLedger(a)
        first.claim("agent", "work-12345678912345", "fingerprint")
        rec=Reconciliation(b)
        proof=hashlib.sha256(b"staging target independently checked").hexdigest()
        with pytest.raises(ReconciliationError):
            rec.record(agent_id="agent",operation_id="work-12345678912345",
                       result="succeeded",external_reference="target:test:42",
                       evidence_sha256="invalid",reviewer="staging-operator")
        output=rec.record(agent_id="agent",operation_id="work-12345678912345",
                          result="succeeded",external_reference="target:test:42",
                          evidence_sha256=proof,reviewer="staging-operator")
        assert output["state"]=="succeeded"
        assert first.get("agent","work-12345678912345")["state"]=="succeeded"
        with pytest.raises(ReconciliationError):
            Reconciliation(a).record(agent_id="agent",operation_id="work-12345678912345",
                          result="failed",external_reference="target:test:43",
                          evidence_sha256=proof,reviewer="second-reviewer")
        with pytest.raises(OperationConflict):
            first.claim("agent","work-12345678912345","fingerprint")
    finally:
        a.close()
        b.close()


def test_unknown_remains_unknown_without_evidence(tmp_path):
    store=SqliteStore(str(tmp_path/"ops.db"))
    try:
        ledger=OperationLedger(store)
        ledger.claim("agent","op-99999999999999","scope")
        rec=Reconciliation(store)
        with pytest.raises(ReconciliationError):
            rec.record(agent_id="agent",operation_id="op-99999999999999",
                       result="failed",external_reference="",
                       evidence_sha256="0"*64,reviewer="admin")
        assert ledger.get("agent","op-99999999999999")["state"]=="unknown"
    finally:
        store.close()
