"""Observer public key rotation and revocation fail closed."""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.observer_key_registry import (
    ObserverKey,ObserverTrustRegistry,ObserverKeyDenied)

def pub(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()

def test_staged_active_revoked_rotation():
    old,new=Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()
    first=ObserverTrustRegistry([
        ObserverKey("old",pub(old),"active"),ObserverKey("new",pub(new),"staged")])
    assert first.resolve_active("old")==pub(old)
    with pytest.raises(ObserverKeyDenied):
        first.resolve_active("new")
    rotated=ObserverTrustRegistry([
        ObserverKey("old",pub(old),"revoked"),ObserverKey("new",pub(new),"active")])
    assert rotated.resolve_active("new")==pub(new)
    with pytest.raises(ObserverKeyDenied):
        rotated.resolve_active("old")
    with pytest.raises(ObserverKeyDenied):
        rotated.resolve_active("untrusted")
    with pytest.raises(ObserverKeyDenied):
        ObserverTrustRegistry([
            ObserverKey("same",pub(old),"active"),ObserverKey("same",pub(new),"active")])


def test_sdk_registered_verifier_cannot_be_overridden_or_revoked():
    from src.governance.trust_sdk import verify_registered_action_evidence
    key=Ed25519PrivateKey.generate()
    active=ObserverTrustRegistry([ObserverKey("observer-1",pub(key),"active")])
    with pytest.raises(ValueError,match="cannot override"):
        verify_registered_action_evidence(
            observer_registry=active,observer_key_id="observer-1",
            readback_key_hex=pub(key))
    revoked=ObserverTrustRegistry([ObserverKey("observer-1",pub(key),"revoked")])
    with pytest.raises(ObserverKeyDenied):
        verify_registered_action_evidence(
            observer_registry=revoked,observer_key_id="observer-1")
