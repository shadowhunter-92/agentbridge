"""Regression tests for persistent operation-to-budget reservation linkage."""
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger
import pytest


def test_reservation_token_persists_between_sql_workers(tmp_path):
    name = str(tmp_path / "reserve.db")
    a, b = SqliteStore(name), SqliteStore(name)
    try:
        x = OperationLedger(a)
        y = OperationLedger(b)
        x.claim("agent", "request-000000001", "sha256-fingerprint", reservation_token="reserved-opaque")
        with b._lock:
            row = b._db.execute(
                "SELECT token FROM operation_reservations WHERE agent_id=? AND operation_id=?",
                ("agent", "request-000000001")).fetchone()
        assert row["token"] == "reserved-opaque"
        assert y.get("agent", "request-000000001")["state"] == "unknown"
    finally:
        a.close()
        b.close()
