"""Bounded legacy probe/CLI contracts; no server, cloud or database failover."""
from types import SimpleNamespace

import pytest

from tests.test_production_readiness import _client_with_sqlite, _restore_env


def test_draining_refuses_new_traffic_without_failing_liveness(tmp_path, monkeypatch):
    client, cp = _client_with_sqlite(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setitem(cp._ready, "ok", False)
            ready = client.get("/ready")
            assert ready.status_code == 503
            assert ready.json() == {"status": "draining"}
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"
            assert health.json()["store"]["ok"] is True
    finally:
        client.close()
        cp.store.close()
        _restore_env()


def test_unhealthy_store_refuses_readiness_but_process_stays_live(tmp_path, monkeypatch):
    client, cp = _client_with_sqlite(tmp_path)
    try:
        unhealthy = {"ok": False, "backend": "synthetic-unavailable-store"}
        with monkeypatch.context() as patch:
            patch.setitem(cp._ready, "ok", True)
            patch.setattr(cp, "_store_health", lambda: unhealthy)
            ready = client.get("/ready")
            assert ready.status_code == 503
            assert ready.json() == {"status": "not_ready", "store": unhealthy}
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json()["store"] == unhealthy
    finally:
        client.close()
        cp.store.close()
        _restore_env()


@pytest.mark.parametrize("reload,workers", [(False, 5), (True, 1)])
def test_cli_uses_seconds_and_disallows_multiple_reload_workers(monkeypatch, reload, workers):
    import uvicorn
    from src.cli import _serve

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setenv("AGENTBRIDGE_SHUTDOWN_GRACE", "2.9")
    _serve(SimpleNamespace(host="127.0.0.1", port=8000, reload=reload, workers=5, log_level="warning"))
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("src.api.control_plane:app",)
    assert kwargs["workers"] == workers
    assert kwargs["reload"] is reload
    assert type(kwargs["timeout_graceful_shutdown"]) is int
    assert kwargs["timeout_graceful_shutdown"] == 2
