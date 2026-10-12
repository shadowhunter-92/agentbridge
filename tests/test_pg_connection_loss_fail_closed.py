"""Fail-closed database loss and durable no-replay recovery, disposable PostgreSQL.

This kills only our own test connection; it is NOT a cluster failover or PITR
rehearsal. Confirms the prior claimed operation remains durable and repeat
attempts cannot dispatch a second action.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("AGENTBRIDGE_TEST_PG"),
                                reason="requires isolated Postgres test service")


def test_pg_connection_loss_does_not_reclaim_or_replay_an_operation():
    from src.governance.store import PostgresStore
    from src.governance.operation_ledger import OperationLedger, OperationConflict

    dsn = os.environ["AGENTBRIDGE_TEST_PG"]
    agent = "pg-connection-loss-" + uuid.uuid4().hex
    op = "op-" + uuid.uuid4().hex
    first = PostgresStore(dsn)
    try:
        OperationLedger(first).claim(agent, op, "exact-request-fingerprint")
        assert OperationLedger(first).get(agent, op)["state"] == "unknown"
        first._db.close()  # simulated connectivity loss for this test worker
        with pytest.raises(Exception):
            OperationLedger(first).claim(agent, op + "-second", "other")
    finally:
        try:
            first.close()
        except Exception:
            pass
    recovered = PostgresStore(dsn)
    try:
        ledger = OperationLedger(recovered)
        assert ledger.get(agent, op)["state"] == "unknown"
        assert ledger.get(agent, op + "-second") is None
        with pytest.raises(OperationConflict):
            ledger.claim(agent, op, "exact-request-fingerprint")
        assert ledger.get(agent, op)["state"] == "unknown"
    finally:
        recovered.close()
