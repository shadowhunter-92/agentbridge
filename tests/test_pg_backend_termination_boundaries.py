"""Disposable real PostgreSQL backend termination at commit boundaries.

This tests PostgreSQL transaction rollback, durable unknown-state preservation
and conservative no-replay after a worker connection is killed. It is NOT
managed database failover, cross-zone partition, or a measured RPO/RTO.
"""
import os
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("AGENTBRIDGE_TEST_PG"), reason="needs disposable postgres CI service"
)


def test_real_postgres_backend_termination_before_and_after_claim_commit():
    import psycopg

    from src.governance.operation_ledger import OperationConflict, OperationLedger
    from src.governance.store import PostgresStore

    dsn = os.environ["AGENTBRIDGE_TEST_PG"]
    suffix = uuid.uuid4().hex
    agent = "partition-agent-" + suffix
    op_uncommitted = "uncommitted-" + suffix
    op_committed = "committed-" + suffix
    admin = psycopg.connect(dsn, autocommit=True)
    worker = PostgresStore(dsn)
    try:
        OperationLedger(worker)  # ensure tables before the crash-window transaction
        with worker._db.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            worker_pid = cursor.fetchone()["pg_backend_pid"]
        with pytest.raises(psycopg.OperationalError):
            with worker._db.transaction():
                with worker._db.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO agent_operations "
                        "(agent_id, operation_id, fingerprint, state, updated) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (agent, op_uncommitted, "fp", "unknown", time.time()),
                    )
                with admin.cursor() as cursor:
                    cursor.execute("SELECT pg_terminate_backend(%s)", (worker_pid,))
                    assert cursor.fetchone()[0], "worker backend was not terminated"
        # Nothing from the uncommitted operation survived the database abort.
        restored = PostgresStore(dsn)
        try:
            ledger = OperationLedger(restored)
            assert ledger.get(agent, op_uncommitted) is None
            # Freshly claimed operation commits before another killed worker.
            ledger.claim(agent, op_committed, "immutable-fingerprint")
            assert ledger.get(agent, op_committed)["state"] == "unknown"
            with restored._db.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                committed_pid = cursor.fetchone()["pg_backend_pid"]
            with admin.cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(%s)", (committed_pid,))
                assert cursor.fetchone()[0]
        finally:
            try:
                restored.close()
            except psycopg.Error:
                pass
        restarted = PostgresStore(dsn)
        try:
            ledger = OperationLedger(restarted)
            assert ledger.get(agent, op_committed)["state"] == "unknown"
            with pytest.raises(OperationConflict, match="no automatic replay"):
                ledger.claim(agent, op_committed, "immutable-fingerprint")
            with pytest.raises(OperationConflict, match="different request"):
                ledger.claim(agent, op_committed, "other-fingerprint")
        finally:
            restarted.close()
    finally:
        try:
            worker.close()
        except psycopg.Error:
            pass
        admin.close()
