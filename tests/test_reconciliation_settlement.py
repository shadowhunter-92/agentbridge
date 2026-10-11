"""Budget settlement in the same SQL transaction as manual reconciliation."""
import hashlib
import pytest
from src.governance.store import SqliteStore
from src.governance.budget import BudgetManager, Budget
from src.governance.operation_ledger import OperationLedger
from src.governance.reconciliation import Reconciliation, ReconciliationError


@pytest.mark.parametrize("outcome,expected_spent", [("succeeded",2.0),("failed",0.0)])
def test_settlement_is_atomic_and_single_use(tmp_path, outcome, expected_spent):
    db=SqliteStore(str(tmp_path/"atomic.db"))
    try:
        budgets=BudgetManager(db)
        budgets.set_budget("agent",Budget(spend_limit=5))
        token,_=budgets.reserve("agent",2)
        OperationLedger(db).claim("agent","operation-123456789","scope",reservation_token=token)
        digest=hashlib.sha256(b"simulated destination receipt").hexdigest()
        result=Reconciliation(db).record(
            agent_id="agent", operation_id="operation-123456789",
            result=outcome, external_reference="simulated-target/receipt/1",
            evidence_sha256=digest, reviewer="authorized-staging-operator")
        assert result["state"]==outcome
        state=db.get_budget("agent")
        assert state["spent"]==expected_spent
        assert not state["reserved"]
        with pytest.raises(ReconciliationError):
            Reconciliation(db).record(
                agent_id="agent",operation_id="operation-123456789",result=outcome,
                external_reference="simulated-target/receipt/1",
                evidence_sha256=digest,reviewer="authorized-staging-operator")
    finally:
        db.close()
