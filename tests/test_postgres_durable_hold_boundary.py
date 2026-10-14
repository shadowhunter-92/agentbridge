"""PostgreSQL durable-hold and retention boundary integration test.

Disposable test database only. Uses isolated audit records with no DROP.
"""
import os
import pytest

@pytest.mark.skipif(not os.getenv("AGENTBRIDGE_TEST_PG"),
                    reason="requires disposable PostgreSQL test service")
@pytest.mark.parametrize("environment", ["prod", "production"])
def test_pg_hold_blocks_direct_retention_across_connections(monkeypatch, environment):
    from src.governance.store import PostgresStore
    from src.governance.audit_trust import AuditTrustStore
    from src.governance.audit import AuditLog
    import uuid
    monkeypatch.delenv("AGENTBRIDGE_ENV", raising=False)
    a = PostgresStore(os.environ["AGENTBRIDGE_TEST_PG"])
    b = PostgresStore(os.environ["AGENTBRIDGE_TEST_PG"])
    hold = "test-retention-" + uuid.uuid4().hex
    try:
        trusted = AuditTrustStore(a)
        # Do not mutate shared test data: assert a hold blocks before deleting.
        trusted.set_hold(hold, True)
        with pytest.raises(PermissionError, match="durable legal hold"):
            b.truncate_audit_before(1)
        monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
        with pytest.raises(PermissionError, match="production audit retention"):
            b.truncate_audit_before(1)
    finally:
        trusted.set_hold(hold, False)
        a.close()
        b.close()
