"""Persistent audit hold is enforced at the lowest store deletion boundary."""
import pytest
from src.governance.store import SqliteStore
from src.governance.audit import AuditLog
from src.governance.audit_trust import AuditTrustStore


def test_durable_hold_blocks_other_connection_and_direct_store(tmp_path, monkeypatch):
    a = SqliteStore(str(tmp_path / "audit.db"))
    b = SqliteStore(str(tmp_path / "audit.db"))
    try:
        log = AuditLog(a)
        for _ in range(3):
            log.record(actor="agent", action="test", source_protocol="mcp",
                       target_protocol="mcp", capability="read", decision="allow")
        trust = AuditTrustStore(a)
        trust.set_hold("case-1", True)
        with pytest.raises(PermissionError, match="durable legal hold"):
            b.truncate_audit_before(1)
        assert len(a.load_audit()) == 3
        monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
        trust.set_hold("case-1", False)
        with pytest.raises(PermissionError, match="production audit retention"):
            b.truncate_audit_before(1)
        assert len(b.load_audit()) == 3
    finally:
        a.close()
        b.close()


def test_no_hold_nonproduction_retention_keeps_existing_behavior(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTBRIDGE_ENV", raising=False)
    store = SqliteStore(str(tmp_path / "nonprod.db"))
    try:
        AuditTrustStore(store)
        for n in range(3):
            store.append_audit({"seq": n, "entry_hash": str(n)})
        assert store.truncate_audit_before(2) == 2
        assert [r["seq"] for r in store.load_audit()] == [2]
    finally:
        store.close()
