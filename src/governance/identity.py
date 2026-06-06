"""
Agent identity & verification (the "is this agent who it claims to be?" layer).

ANP-style: each agent has a DID derived from an Ed25519 public key. Agents hold their
own private key and SIGN requests; the registry verifies signatures against the
registered public key. Real public-key cryptography (Ed25519).

Key lifecycle (fixed from the deep review): the *agent* owns the private key. You either
(a) register a client-generated public key, or (b) have the server generate a keypair and
return the private key ONCE so the agent can sign thereafter. Identities can be revoked.

This is where ANP-style decentralized identity plugs into the meta-bridge.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

from .store import GovernanceStore, InMemoryStore


def did_from_public_hex(public_hex: str) -> str:
    return f"did:key:ed25519:{public_hex}"


@dataclass
class AgentIdentity:
    """An agent's identity. Holds the public key always; the private key only for the owner."""
    agent_id: str
    public_key_hex: str
    _private_key: Optional[Ed25519PrivateKey] = None

    @classmethod
    def generate(cls, agent_id: str) -> "AgentIdentity":
        priv = Ed25519PrivateKey.generate()
        pub_hex = priv.public_key().public_bytes_raw().hex()
        return cls(agent_id=agent_id, public_key_hex=pub_hex, _private_key=priv)

    @classmethod
    def from_private_hex(cls, agent_id: str, private_hex: str) -> "AgentIdentity":
        priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
        return cls(agent_id=agent_id,
                   public_key_hex=priv.public_key().public_bytes_raw().hex(),
                   _private_key=priv)

    @property
    def did(self) -> str:
        return did_from_public_hex(self.public_key_hex)

    @property
    def private_key_hex(self) -> Optional[str]:
        if self._private_key is None:
            return None
        return self._private_key.private_bytes_raw().hex()

    def public_only(self) -> "AgentIdentity":
        return AgentIdentity(self.agent_id, self.public_key_hex, None)

    def sign(self, data: bytes) -> bytes:
        if self._private_key is None:
            raise ValueError("This identity has no private key; cannot sign.")
        return self._private_key.sign(data)

    def verify(self, data: bytes, signature: bytes) -> bool:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key_hex))
        try:
            pub.verify(signature, data)
            return True
        except InvalidSignature:
            return False


class IdentityRegistry:
    """Registry of known agent identities; verifies signed requests. Store-backed (durable)."""

    def __init__(self, store: Optional[GovernanceStore] = None):
        self.store = store or InMemoryStore()
        self._revoked: Dict[str, bool] = {}
        self._cache: Dict[str, AgentIdentity] = {}
        # warm cache from the store (durable restart).
        for rec in self.store.list_identities():
            self._cache[rec["agent_id"]] = AgentIdentity(rec["agent_id"], rec["public_key_hex"])
            self._revoked[rec["agent_id"]] = rec.get("revoked", False)

    def register(self, identity: AgentIdentity) -> None:
        self._cache[identity.agent_id] = identity.public_only()
        self._revoked[identity.agent_id] = False
        self.store.upsert_identity(identity.agent_id, identity.public_key_hex, revoked=False)

    def register_public_key(self, agent_id: str, public_key_hex: str) -> AgentIdentity:
        ident = AgentIdentity(agent_id, public_key_hex)
        self.register(ident)
        return ident

    def revoke(self, agent_id: str) -> bool:
        if agent_id not in self._cache:
            return False
        self._revoked[agent_id] = True
        rec = self._cache[agent_id]
        self.store.upsert_identity(agent_id, rec.public_key_hex, revoked=True)
        return True

    def is_revoked(self, agent_id: str) -> bool:
        return self._revoked.get(agent_id, False)

    def get(self, agent_id: str) -> Optional[AgentIdentity]:
        return self._cache.get(agent_id)

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self._cache and not self.is_revoked(agent_id)

    def verify_signature(self, agent_id: str, data: bytes, signature: bytes) -> bool:
        if self.is_revoked(agent_id):
            return False
        ident = self._cache.get(agent_id)
        return bool(ident and ident.verify(data, signature))

    def did_of(self, agent_id: str) -> Optional[str]:
        ident = self._cache.get(agent_id)
        return ident.did if ident else None
