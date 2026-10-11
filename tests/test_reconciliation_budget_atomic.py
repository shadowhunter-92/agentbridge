"""Atomic settlement tests with real SQLite state; simulated evidence only."""
import hashlib
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger
from src.governance.reconciliation import Reconciliation


def test_success_settles_held_reservation(tmp_path):
    store=SqliteStore(str(tmp_path/"budget.db"))
    try:
        store.upsert_budget("a", {"spend_limit":10,"rate_limit":100,"window_seconds":3600,
                                 "spent":0.0,"calls":[],"reserved":{"tok1":3.0}})
        OperationLedger(store).claim("a","operation-123456789","scope",reservation_token="tok1")
        Reconciliation(store).record(agent_id="a",operation_id="operation-123456789",
            result="succeeded",external_reference="simulator-1",
            evidence_sha256=hashlib.sha256(b"synthetic").hexdigest(),reviewer="operator")
        state=store.get_budget("a")
        assert state["spent"]==3.0
        assert state["reserved"]=={}
        assert OperationLedger(store).get("a","operation-123456789")["state"]=="succeeded"
    finally:
        store.close()


def test_failed_action_releases_held_reservation(tmp_path):
    store=SqliteStore(str(tmp_path/"budget.db"))
    try:
        store.upsert_budget("a", {"spend_limit":10,"rate_limit":100,"window_seconds":3600,
                                 "spent":0.0,"calls":[],"reserved":{"tok2":3.0}})
        OperationLedger(store).claim("a","operation-123456790","scope",reservation_token="tok2")
        Reconciliation(store).record(agent_id="a",operation_id="operation-123456790",
            result="failed",external_reference="simulator-2",
            evidence_sha256=hashlib.sha256(b"synthetic failed").hexdigest(),reviewer="operator")
        state=store.get_budget("a")
        assert state["spent"]==0.0
        assert state["reserved"]=={}
    finally:
        store.close()
