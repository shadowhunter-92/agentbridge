"""PostgreSQL integration for durable reservation reconciliation.

Uses AGENTBRIDGE_TEST_PG and a random agent ID; no destructive schema resets.
"""
import hashlib
import os
import uuid
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("AGENTBRIDGE_TEST_PG"), reason="set AGENTBRIDGE_TEST_PG for disposable PostgreSQL")


@pytest.mark.parametrize("outcome,charged", [("succeeded", 2.0), ("failed", 0.0)])
def test_postgres_reconciliation_settles_reservation_atomically(outcome, charged):
    from src.governance.store import PostgresStore
    from src.governance.budget import Budget, BudgetManager
    from src.governance.operation_ledger import OperationLedger, OperationConflict
    from src.governance.reconciliation import Reconciliation, ReconciliationError

    dsn = os.environ["AGENTBRIDGE_TEST_PG"]
    a, b = PostgresStore(dsn), PostgresStore(dsn)
    agent = "pg-test-" + uuid.uuid4().hex
    op = "op-" + uuid.uuid4().hex
    try:
        budgets = BudgetManager(a)
        budgets.set_budget(agent, Budget(spend_limit=5.0))
        token, why = budgets.reserve(agent, 2.0)
        assert token is not None, why
        OperationLedger(a).claim(agent, op, "fingerprint", reservation_token=token)
        proof = hashlib.sha256(b"externally verified simulated-only result").hexdigest()
        Reconciliation(b).record(agent_id=agent, operation_id=op,
                                 result=outcome, external_reference="mock-target/receipt/123",
                                 evidence_sha256=proof, reviewer="integration-test-operator")
        state = a.get_budget(agent)
        assert state["spent"] == charged
        assert not state["reserved"]
        assert OperationLedger(a).get(agent, op)["state"] == outcome
        with pytest.raises(ReconciliationError):
            Reconciliation(a).record(agent_id=agent, operation_id=op,
                                      result=outcome, external_reference="mock-target/receipt/123",
                                      evidence_sha256=proof, reviewer="integration-test-operator")
    finally:
        a.close()
        b.close()
