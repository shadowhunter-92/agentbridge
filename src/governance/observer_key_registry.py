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
        seen_public_keys=set()
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
            normalized=raw.hex()
            if normalized in seen_public_keys:
                raise ObserverKeyDenied('public key reused under another observer identity')
            seen_public_keys.add(normalized)
            self._keys[entry.key_id]=entry

    def resolve_active(self,key_id):
        item=self._keys.get(key_id)
        if item is None or item.state!="active":
            raise ObserverKeyDenied("observer key not active or has been revoked")
        return item.public_key_hex

def validate_rotation(previous: ObserverTrustRegistry, proposed: ObserverTrustRegistry):
    """Validate key transitions, not operator authorization or key custody.

    An independently authorized controller MUST authenticate, atomically
    publish, and journal each revision; in-process validation cannot establish
    HSM custody, distributed consensus, or production revocation.
    """
    if not isinstance(previous, ObserverTrustRegistry) or not isinstance(proposed, ObserverTrustRegistry):
        raise ObserverKeyDenied("two pinned registry snapshots required")
    old, new = previous._keys, proposed._keys
    for key_id, entry in old.items():
        replacement = new.get(key_id)
        if replacement is None:
            raise ObserverKeyDenied("observer key cannot disappear from trust history")
        if entry.public_key_hex.lower() != replacement.public_key_hex.lower():
            raise ObserverKeyDenied("observer key material cannot be reassigned")
        allowed = {"staged": {"staged", "active", "revoked"},
                   "active": {"active", "revoked"},
                   "revoked": {"revoked"}}
        if replacement.state not in allowed[entry.state]:
            raise ObserverKeyDenied("observer key lifecycle regression or resurrection")
    for key_id, entry in new.items():
        if key_id not in old and entry.state != "staged":
            raise ObserverKeyDenied("new keys require staging before activation")
    if any(entry.state == "active" for entry in old.values()):
        if not any(entry.state == "active" for entry in new.values()):
            raise ObserverKeyDenied("rotation cannot leave an active trust domain empty")
    return {
        "staged": sorted(k for k, v in new.items() if v.state == "staged"),
        "active": sorted(k for k, v in new.items() if v.state == "active"),
        "revoked": sorted(k for k, v in new.items() if v.state == "revoked"),
    }
