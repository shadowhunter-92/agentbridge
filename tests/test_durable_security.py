"""Security regression tests for shared-store replay and revocation."""
import time
from pathlib import Path
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.request_auth import RequestAuthenticator, sign_request
from src.governance.store import SqliteStore


def test_replay_across_independent_workers(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    path = str(tmp_path / "replay.db")
    a, b = SqliteStore(path), SqliteStore(path)
    try:
        identity = AgentIdentity.generate("agent1")
        IdentityRegistry(a).register(identity)
        auth_a = RequestAuthenticator(IdentityRegistry(a))
        auth_b = RequestAuthenticator(IdentityRegistry(b))
        nonce = f"{int(time.time())}:abcdefghijklmnopqrstuvwxyz"
        body = b'{"action":"demo"}'
        sig = sign_request(identity, nonce, body)
        assert auth_a.authenticate("agent1", nonce, body, sig)[0]
        assert not auth_b.authenticate("agent1", nonce, body, sig)[0]
    finally:
        a.close()
        b.close()


def test_cross_worker_revocation(tmp_path: Path):
    path = str(tmp_path / "revocation.db")
    a, b = SqliteStore(path), SqliteStore(path)
    try:
        identity = AgentIdentity.generate("agent1")
        reg1, reg2 = IdentityRegistry(a), IdentityRegistry(b)
        reg1.register(identity)
        assert reg2.is_registered("agent1")
        assert reg2.verify_signature("agent1", b"x", identity.sign(b"x"))
        assert reg1.revoke("agent1")
        assert not reg2.is_registered("agent1")
        assert not reg2.verify_signature("agent1", b"x", identity.sign(b"x"))
    finally:
        a.close()
        b.close()


def test_prod_alias_uses_shared_durable_replay_store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "prod")
    a = SqliteStore(str(tmp_path / "alias.db"))
    b = SqliteStore(str(tmp_path / "alias.db"))
    try:
        identity = AgentIdentity.generate("agent-alias")
        IdentityRegistry(a).register(identity)
        nonce = f"{int(time.time())}:strong-unique-production-nonce"
        body = b'{"action":"read"}'
        sig = sign_request(identity, nonce, body)
        assert RequestAuthenticator(IdentityRegistry(a)).authenticate(
            "agent-alias", nonce, body, sig)[0]
        ok, message = RequestAuthenticator(IdentityRegistry(b)).authenticate(
            "agent-alias", nonce, body, sig)
        assert not ok, message
    finally:
        a.close()
        b.close()
