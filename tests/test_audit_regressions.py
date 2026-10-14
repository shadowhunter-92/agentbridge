"""Cross-worker identity and HTTP metric regression boundaries."""

from fastapi.testclient import TestClient

from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.store import SqliteStore
from src.observability import HTTP_DURATION, HTTP_REQUESTS


def test_cross_worker_registration_and_revocation_use_durable_state(tmp_path):
    path = str(tmp_path / "identities.db")
    a, b = SqliteStore(path), SqliteStore(path)
    try:
        first, second = IdentityRegistry(a), IdentityRegistry(b)
        identity = AgentIdentity.generate("new-agent")
        first.register(identity)
        assert second.get("new-agent").did == identity.did
        assert second.did_of("new-agent") == identity.did
        assert second.revoke("new-agent")
        assert not first.verify_signature("new-agent", b"data", identity.sign(b"data"))
    finally:
        a.close()
        b.close()


def test_many_extension_http_methods_have_one_metric_label(monkeypatch):
    from src.api import control_plane as cp
    monkeypatch.setitem(cp._ready, "ok", True)
    client = TestClient(cp.app)
    before_requests, before_duration = len(HTTP_REQUESTS._metrics), len(HTTP_DURATION._metrics)
    for n in range(50):
        assert client.request("EXTENSION" + str(n), "/not-a-route").status_code in (404, 405)
    assert len(HTTP_REQUESTS._metrics) - before_requests <= 1
    assert len(HTTP_DURATION._metrics) - before_duration <= 1
