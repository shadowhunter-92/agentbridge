"""Real signed-token revocation and bounded unauthenticated JWKS work."""

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from src.api.auth_oidc import OidcConfig, OidcError, OidcVerifier


@pytest.fixture
def keys():
    pairs = []
    for kid in ("old", "new"):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
        jwk["kid"] = kid
        pairs.append((private, jwk))
    return pairs


def token(private, kid):
    return jwt.encode({"sub": "operator", "role": "admin", "iss": "https://idp.test",
                       "aud": "agentbridge", "exp": int(time.time()) + 300},
                      private, algorithm="RS256", headers={"kid": kid})


def test_removed_signer_rejected_after_authoritative_refresh(monkeypatch, keys):
    clock = [1000.0]
    monkeypatch.setattr("src.api.auth_oidc.time.monotonic", lambda: clock[0])
    verifier = OidcVerifier(OidcConfig("https://idp.test", "agentbridge", jwks_ttl_seconds=10))
    published = [keys[0][1]]
    monkeypatch.setattr(verifier, "_fetch_jwks", lambda: {"keys": published})
    old = token(keys[0][0], "old")
    assert verifier.verify(old)["role"] == "admin"
    published[:] = [keys[1][1]]
    clock[0] += 11
    with pytest.raises(OidcError, match="no signing key"):
        verifier.verify(old)
    assert verifier.verify(token(keys[1][0], "new"))["role"] == "admin"


def test_unknown_kid_flood_is_bounded_and_preserves_healthy_cache(monkeypatch, keys):
    clock = [1000.0]
    monkeypatch.setattr("src.api.auth_oidc.time.monotonic", lambda: clock[0])
    verifier = OidcVerifier(OidcConfig("https://idp.test", "agentbridge"))
    fetches = []
    def fetch():
        fetches.append(clock[0])
        return {"keys": [keys[0][1]]}
    monkeypatch.setattr(verifier, "_fetch_jwks", fetch)
    known = token(keys[0][0], "old")
    verifier.verify(known)
    for i in range(50):
        with pytest.raises(OidcError):
            verifier.verify(token(keys[0][0], "missing-" + str(i)))
    assert len(fetches) == 1
    assert verifier.verify(known)["role"] == "admin"
    clock[0] += 6
    with pytest.raises(OidcError):
        verifier.verify(token(keys[0][0], "another-miss"))
    assert len(fetches) == 2


def test_fetch_failure_rejects_expired_key_and_is_rate_limited(monkeypatch, keys):
    clock = [1000.0]
    monkeypatch.setattr("src.api.auth_oidc.time.monotonic", lambda: clock[0])
    verifier = OidcVerifier(OidcConfig("https://idp.test", "agentbridge", jwks_ttl_seconds=10))
    monkeypatch.setattr(verifier, "_fetch_jwks", lambda: {"keys": [keys[0][1]]})
    known = token(keys[0][0], "old")
    verifier.verify(known)
    calls = []
    def unavailable():
        calls.append(1)
        raise OidcError("issuer unavailable")
    monkeypatch.setattr(verifier, "_fetch_jwks", unavailable)
    clock[0] += 11
    for _ in range(10):
        with pytest.raises(OidcError):
            verifier.verify(known)
    assert len(calls) == 1


async def test_operator_key_resolution_does_not_block_event_loop(monkeypatch):
    import asyncio
    import threading

    from starlette.requests import Request

    from src.api import control_plane as cp
    started, release = threading.Event(), threading.Event()
    class SlowVerifier:
        def authenticate(self, value):
            started.set()
            assert release.wait(2)
            return {}, "viewer"
    monkeypatch.setattr(cp, "oidc_verifier", SlowVerifier())
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer slow")]})
    pending = asyncio.create_task(cp.operator_guard("audit:read")(request))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        assert not pending.done()
    finally:
        release.set()
    assert await pending == "viewer"
