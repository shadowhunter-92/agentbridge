"""
Tests for the production-readiness layer: observability, store-backed approvals,
audit retention / legal hold, /ready /metrics /version endpoints, structured logging,
config validation, retry/backoff resilience.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("redis", MagicMock())
sys.modules.setdefault("redis.asyncio", MagicMock())

from src.governance import (
    AgentIdentity, IdentityRegistry, AuditLog, Budget, BudgetManager,
    PolicyEngine, GovernanceGateway, ApprovalQueue, InMemoryStore, SqliteStore, make_store,
)
from src.governance.audit import AuditEntry
from src.protocols.canonical import CanonicalCall
from src.observability import (
    render_metrics, record_call, record_translate, update_audit_count,
    update_approvals_pending, update_budget_gauge,
)
from src.observability.logging import configure_logging, bind_request_id, new_request_id
from src.config import validate_config, ConfigError
from src.governance.resilience import retry_transient


# --- Store-backed ApprovalQueue ------------------------------------------------------

def test_approval_queue_persists_to_sqlite():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        s1 = SqliteStore(path)
        aq1 = ApprovalQueue(store=s1)
        aq1.mark_sensitive("delete_db")
        req = aq1.request("agent-x", "delete_db", 5.0)
        assert aq1.is_granted("agent-x", "delete_db") is False
        assert aq1.approve(req.id) is True
        assert aq1.is_granted("agent-x", "delete_db") is True

        # New store instance, same DB -> approvals survived
        s2 = SqliteStore(path)
        aq2 = ApprovalQueue(store=s2)
        assert aq2.is_granted("agent-x", "delete_db") is True  # approval is durable
        # The pending list is empty (it's now "approved", not "pending")
        assert aq2.pending() == []
        # Consume on the new instance
        aq2.consume("agent-x", "delete_db")
        assert aq2.is_granted("agent-x", "delete_db") is False
    finally:
        os.unlink(path)


def test_approval_consume_is_one_shot():
    aq = ApprovalQueue()
    aq.mark_sensitive("risky")
    req = aq.request("a", "risky", 1.0)
    aq.approve(req.id)
    assert aq.is_granted("a", "risky")
    aq.consume("a", "risky")
    assert not aq.is_granted("a", "risky")
    # Consume again is a safe no-op
    aq.consume("a", "risky")
    assert not aq.is_granted("a", "risky")


def test_approve_deny_idempotency():
    aq = ApprovalQueue()
    req = aq.request("a", "c", 1.0)
    assert aq.approve(req.id) is True
    assert aq.approve(req.id) is False  # already approved
    assert aq.deny(req.id) is False     # can't deny an approved one


# --- Audit retention + legal hold ----------------------------------------------------

def test_audit_truncate_removes_old_entries():
    log = AuditLog(InMemoryStore())
    for i in range(5):
        log.record(actor="a", action="route_call", source_protocol="mcp",
                   target_protocol="a2a", capability=f"cap_{i}", decision="allow", cost=1.0)
    assert len(log.entries()) == 5
    removed = log.truncate_before(3)
    assert removed == 3
    assert len(log.entries()) == 2
    assert log.entries()[0].seq == 3


def test_audit_legal_hold_blocks_truncation():
    log = AuditLog(InMemoryStore())
    for i in range(5):
        log.record(actor="a", action="route_call", source_protocol="mcp",
                   target_protocol="a2a", capability=f"cap_{i}", decision="allow", cost=1.0)
    log.set_legal_hold(True)
    assert log.is_legal_hold() is True
    removed = log.truncate_before(3)
    assert removed == 0
    assert len(log.entries()) == 5
    # Lift the hold -> truncation works
    log.set_legal_hold(False)
    removed = log.truncate_before(3)
    assert removed == 3


def test_audit_truncate_zero_seq_is_noop():
    log = AuditLog(InMemoryStore())
    log.record(actor="a", action="x", source_protocol="mcp",
               target_protocol="a2a", capability="c", decision="allow")
    assert log.truncate_before(0) == 0
    assert log.truncate_before(-1) == 0


def test_audit_checkpoint_signs_and_verifies():
    log = AuditLog(InMemoryStore())
    log.record(actor="a", action="x", source_protocol="mcp",
               target_protocol="a2a", capability="c", decision="allow")
    op = AgentIdentity.generate("operator")
    cp = log.checkpoint(op.sign, op.public_key_hex)
    assert AuditLog.verify_checkpoint(cp) is True
    # Tamper with the checkpoint -> signature invalid
    bad = dict(cp)
    bad["seq"] = cp["seq"] + 1
    assert AuditLog.verify_checkpoint(bad) is False


# --- Observability --------------------------------------------------------------------

def test_prometheus_metrics_render():
    # Exercise some metrics paths
    record_call("mcp", "a2a", "add", "allow", 0.001)
    record_call("mcp", "a2a", "add", "deny", 0.0005)
    record_translate("openai", "mcp", 0.00001)
    update_audit_count(42)
    update_approvals_pending(3)
    update_budget_gauge("agent-1", 5.0, 95.0)
    body, content_type = render_metrics()
    assert isinstance(body, bytes)
    assert "agentbridge_calls_total" in body.decode()
    assert "agentbridge_audit_entries" in body.decode()
    assert "agentbridge_budget_spent" in body.decode()
    assert "text/plain" in content_type


def test_structured_logging_emits_json():
    import io
    import logging
    # Force JSON mode
    os.environ["AGENTBRIDGE_LOG_JSON"] = "1"
    configure_logging()
    buf = io.StringIO()
    root = logging.getLogger()
    # Replace handler stream so we can capture
    for h in root.handlers:
        h.stream = buf
    bind_request_id("test-rid-12345")
    logging.getLogger("test").info("hello", extra={"k": "v"})
    line = buf.getvalue().strip()
    import json
    rec = json.loads(line)
    assert rec["msg"] == "hello"
    assert rec["request_id"] == "test-rid-12345"
    assert rec["k"] == "v"
    assert rec["level"] == "INFO"
    del os.environ["AGENTBRIDGE_LOG_JSON"]


def test_span_context_manager_is_safe_without_otel():
    from src.observability import span
    with span("test.span", {"k": "v"}) as s:
        assert s is None  # OTel not enabled in tests
    # No exception even if the body raises
    with pytest.raises(ValueError):
        with span("test.span"):
            raise ValueError("boom")


# --- Config validation ----------------------------------------------------------------

def test_config_validates_clean_dev_env():
    # Default env has no AGENTBRIDGE_ENV, so dev defaults apply — no errors.
    issues = validate_config(fail_fast=False)
    errors = [i for i in issues if i.severity == "error"]
    assert errors == [], f"unexpected config errors: {errors}"


def test_config_prod_requires_admin_key_and_db(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    monkeypatch.delenv("AGENTBRIDGE_ADMIN_KEY", raising=False)
    monkeypatch.delenv("AGENTBRIDGE_DB", raising=False)
    with pytest.raises(ConfigError):
        validate_config(fail_fast=True)


def test_config_prod_with_admin_key_and_sqlite_passes(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    monkeypatch.setenv("AGENTBRIDGE_ADMIN_KEY", "x" * 32)
    monkeypatch.setenv("AGENTBRIDGE_DB", "/tmp/ab_prod_test.db")
    issues = validate_config(fail_fast=True)
    # Should pass (maybe a warning about SQLite, but no errors)
    assert not any(i.severity == "error" for i in issues)


def test_config_rejects_bad_rate_limit(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_RATE_LIMIT", "not_a_number")
    with pytest.raises(ConfigError):
        validate_config(fail_fast=True)


def test_config_rejects_bad_oidc_issuer(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_OIDC_ISSUER", "not_a_url")
    with pytest.raises(ConfigError):
        validate_config(fail_fast=True)


# --- Resilience: retry_transient -----------------------------------------------------

def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    @retry_transient(max_attempts=4, base_delay=0.001, max_delay=0.01)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_gives_up_after_max_attempts():
    calls = {"n": 0}

    @retry_transient(max_attempts=2, base_delay=0.001, max_delay=0.01)
    def always_locked():
        calls["n"] += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        always_locked()
    assert calls["n"] == 2


def test_retry_does_not_swallow_permanent_errors():
    @retry_transient(max_attempts=4, base_delay=0.001, max_delay=0.01)
    def bad():
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        bad()


# --- Control-plane endpoints ---------------------------------------------------------

def _client_with_sqlite(tmp_path):
    """Build a fresh TestClient against a SQLite-backed app so /metrics reflects real state.

    Sets the env vars, reloads the control_plane module so it picks them up, and returns
    (client, cp_module). Tests using this MUST call `_restore_env()` at the end (or use
    try/finally) so other test files that imported the old module-level `client` aren't
    left pointing at a stale module with wiped state.
    """
    import importlib
    import src.api.control_plane as cp
    os.environ["AGENTBRIDGE_DB"] = str(tmp_path / "governance.db")
    os.environ["AGENTBRIDGE_ADMIN_KEY"] = "test-admin-key"
    importlib.reload(cp)
    from fastapi.testclient import TestClient
    return TestClient(cp.app), cp


def _restore_env():
    """Restore env to the pre-test state and reload control_plane so other tests work.

    Critical for test isolation: tests/test_control_plane.py imports `app` at module load
    time and binds a TestClient to it. We reload control_plane (which mutates the module
    in place, rebinding its globals), so we must restore the EXACT env that
    test_control_plane.py expects at its module load: `AGENTBRIDGE_ADMIN_KEY=test-admin-key`
    and no `AGENTBRIDGE_DB`. Otherwise the reloaded module's ADMIN_KEY won't match the
    `X-Admin-Key: test-admin-key` header that test_control_plane.py's `client` sends.
    """
    import importlib
    import src.api.control_plane as cp
    os.environ.pop("AGENTBRIDGE_DB", None)
    os.environ["AGENTBRIDGE_ADMIN_KEY"] = "test-admin-key"  # match test_control_plane.py
    importlib.reload(cp)


def test_endpoints_ready_health_version_metrics(tmp_path):
    c, _ = _client_with_sqlite(tmp_path)
    try:
        # /health always 200
        r = c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "store" in body
        assert body["store"]["ok"] is True

        # /ready 200 with store info
        r = c.get("/ready")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

        # /version returns build info
        r = c.get("/version")
        assert r.status_code == 200
        assert "version" in r.json()

        # /metrics renders Prometheus format
        r = c.get("/metrics")
        assert r.status_code == 200
        assert "agentbridge_info" in r.text
    finally:
        _restore_env()


def test_request_id_is_echoed_in_response_header(tmp_path):
    c, _ = _client_with_sqlite(tmp_path)
    try:
        r = c.get("/health", headers={"X-Request-ID": "abc-123"})
        assert r.headers.get("X-Request-ID") == "abc-123"
        # And one is generated if not provided
        r = c.get("/health")
        assert r.headers.get("X-Request-ID")
    finally:
        _restore_env()


def test_audit_retention_endpoint_round_trip(tmp_path):
    c, cp = _client_with_sqlite(tmp_path)
    admin = {"X-Admin-Key": "test-admin-key"}
    try:
        # Create a few audit entries by routing governed calls
        from src.governance import AgentIdentity
        ident = AgentIdentity.generate("caller")
        cp.identities.register(ident)
        cp.budgets.set_budget("caller", Budget(spend_limit=100.0, rate_limit=100))
        openai_call = cp.registry.get("openai").from_canonical_call(CanonicalCall("add", {"a": 1}))

        async def _invoke(w):
            return {"ok": True}

        for _ in range(3):
            asyncio.run(cp.gateway.route_call(agent_id="caller", src_proto="openai",
                                              dst_proto="mcp", src_wire=openai_call,
                                              invoke=_invoke, cost=1.0))
        assert len(cp.audit.entries()) == 3

        # Create a checkpoint
        r = c.post("/control/audit/checkpoint", headers=admin)
        assert r.status_code == 200
        cp_body = r.json()["checkpoint"]
        assert cp_body["seq"] == 3

        # Truncate the first 2 entries
        r = c.post("/control/audit/retention", headers=admin,
                   json={"action": "truncate", "seq": 2})
        assert r.status_code == 200
        assert r.json()["removed"] == 2
        assert len(cp.audit.entries()) == 1

        # Turn on legal hold -> truncate now refuses
        r = c.post("/control/audit/retention", headers=admin,
                   json={"action": "legal_hold", "on": True})
        assert r.status_code == 200
        r = c.post("/control/audit/retention", headers=admin,
                   json={"action": "truncate", "seq": 1})
        assert r.status_code == 409  # conflict — legal hold active

        # Turn off and retry
        c.post("/control/audit/retention", headers=admin,
               json={"action": "legal_hold", "on": False})
        r = c.post("/control/audit/retention", headers=admin,
                   json={"action": "truncate", "seq": 1})
        assert r.status_code == 200
    finally:
        _restore_env()
