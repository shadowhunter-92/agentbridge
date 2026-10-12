"""Pinned independently managed observer-key lifecycle policy.

An operator supplies the trusted public-key registry. Keys may be staged,
active or revoked. Only active keys verify new settlement evidence. This
contains no private key material and is not an external HSM/key custodian.
"""
from dataclasses import dataclass
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

class ObserverKeyDenied(ValueError):
    pass

@dataclass(frozen=True)
class ObserverKey:
    key_id: str
    public_key_hex: str
    state: str

class ObserverTrustRegistry:
    def __init__(self, entries):
        self._keys={}
        if not isinstance(entries,(list,tuple)) or not entries:
            raise ObserverKeyDenied("explicit trusted observer keys required")
        for entry in entries:
            if not isinstance(entry,ObserverKey):
                raise ObserverKeyDenied("invalid observer key configuration")
            if (not entry.key_id or len(entry.key_id)>128 or entry.key_id in self._keys
                    or entry.state not in ("staged","active","revoked")):
                raise ObserverKeyDenied("invalid or duplicate observer key identity")
            try:
                raw=bytes.fromhex(entry.public_key_hex)
                if len(raw)!=32: raise ValueError("bad key length")
                Ed25519PublicKey.from_public_bytes(raw)
            except (ValueError,TypeError) as exc:
                raise ObserverKeyDenied("invalid observer public key") from exc
            self._keys[entry.key_id]=entry

    def resolve_active(self,key_id):
        item=self._keys.get(key_id)
        if item is None or item.state!="active":
            raise ObserverKeyDenied("observer key not active or has been revoked")
        return item.public_key_hex
