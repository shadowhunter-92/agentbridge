import pytest
"""Regression tests for durable audit view and fail-closed production controls."""
from pathlib import Path
from fastapi.testclient import TestClient
from src.governance.audit import AuditLog
from src.governance.store import SqliteStore


def test_audit_view_refreshes_from_other_worker(tmp_path: Path):
    path = str(tmp_path / "audit.db")
    a, b = SqliteStore(path), SqliteStore(path)
    try:
        first, second = AuditLog(a), AuditLog(b)
        first.record(actor="a", action="route_call", source_protocol="mcp",
                     target_protocol="a2a", capability="add", decision="allow")
        second.record(actor="b", action="route_call", source_protocol="a2a",
                      target_protocol="mcp", capability="add", decision="allow")
        assert len(first.entries()) == 2
        assert len(second.entries()) == 2
        assert first.verify_integrity()
        assert len(first.export_jsonl().splitlines()) == 2
        signer = __import__("src.governance.identity", fromlist=["AgentIdentity"]).AgentIdentity.generate("audit-signer")
        assert first.checkpoint(signer.sign, signer.public_key_hex)["seq"] == 2
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize("environment", ["prod", "production"])
def test_production_disallows_ephemeral_audit_checkpoint_and_retention(monkeypatch, environment):
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    from src.api.control_plane import app, ADMIN_KEY
    client = TestClient(app)
    h = {"X-Admin-Key": ADMIN_KEY}
    assert client.post("/control/audit/checkpoint", headers=h).status_code == 503
    assert client.post("/control/audit/retention", headers=h,
                       json={"action": "truncate", "seq": 1}).status_code == 503


def test_production_detects_deleted_audit_prefix(tmp_path, monkeypatch):
    from src.governance.audit import AuditLog
    from src.governance.store import SqliteStore
    store=SqliteStore(str(tmp_path / "audit-prefix.db"))
    try:
        log=AuditLog(store)
        for i in range(4):
            log.record(actor="test", action="write", source_protocol="mcp",
                       target_protocol="a2a", capability="read", decision="allow")
        assert log.verify_durable()
        # Model malicious store operator deleting original history.
        store.truncate_audit_before(2)
        assert log.verify_durable()  # Legacy dev-only suffix validation.
        monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
        assert not log.verify_durable()
        assert not log.verify_integrity()
    finally:
        store.close()


def test_production_direct_library_truncation_is_forbidden(tmp_path, monkeypatch):
    from src.governance.audit import AuditLog
    from src.governance.store import SqliteStore
    store=SqliteStore(str(tmp_path / "audit-immutable.db"))
    try:
        log=AuditLog(store)
        log.record(actor="test", action="write", source_protocol="mcp",
                   target_protocol="a2a", capability="read", decision="allow")
        monkeypatch.setenv("AGENTBRIDGE_ENV", "prod")
        with pytest.raises(PermissionError, match="production audit deletion"):
            log.truncate_before(1)
        assert len(log.entries())==1
        assert log.verify_durable()
    finally:
        store.close()
