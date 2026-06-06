"""
Signed-request authentication for agents.

An agent proves control of its identity by signing a canonical string over the request
(agent_id + nonce + body hash) with its Ed25519 private key. The server verifies the
signature against the registered public key and rejects replayed nonces.

This makes identity *authentication* real (deep-review H1): being "registered" is no
longer enough — the caller must sign with the matching private key.
"""

import hashlib
import time
from typing import Dict, Tuple

from .identity import IdentityRegistry


def canonical_payload(agent_id: str, nonce: str, body: bytes) -> bytes:
    body_hash = hashlib.sha256(body or b"").hexdigest()
    return f"{agent_id}\n{nonce}\n{body_hash}".encode()


def sign_request(identity, nonce: str, body: bytes) -> str:
    """Agent-side: produce a hex signature for a request."""
    return identity.sign(canonical_payload(identity.agent_id, nonce, body)).hex()


class NonceCache:
    """Rejects replayed nonces within a TTL window."""
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._seen: Dict[str, float] = {}

    def check_and_store(self, nonce: str) -> bool:
        now = time.time()
        # prune
        for n, t in list(self._seen.items()):
            if now - t > self.ttl:
                del self._seen[n]
        if nonce in self._seen:
            return False
        self._seen[nonce] = now
        return True


class RequestAuthenticator:
    def __init__(self, identities: IdentityRegistry, nonce_ttl: int = 300):
        self.identities = identities
        self.nonces = NonceCache(nonce_ttl)

    def authenticate(self, agent_id: str, nonce: str, body: bytes,
                     signature_hex: str) -> Tuple[bool, str]:
        if not self.identities.is_registered(agent_id):
            return False, "unknown or revoked identity"
        if not nonce:
            return False, "missing nonce"
        if not self.nonces.check_and_store(nonce):
            return False, "nonce replay detected"
        try:
            sig = bytes.fromhex(signature_hex)
        except Exception:
            return False, "malformed signature"
        if not self.identities.verify_signature(agent_id, canonical_payload(agent_id, nonce, body), sig):
            return False, "signature verification failed"
        return True, "authenticated"
