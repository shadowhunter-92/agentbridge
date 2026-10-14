"""Observer key lifecycle safety is only a configuration gate, not custody proof."""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.observer_key_registry import (
    ObserverKey, ObserverTrustRegistry, ObserverKeyDenied, validate_rotation
)

def pub():
    key = Ed25519PrivateKey.generate()
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()

def registry(*rows):
    return ObserverTrustRegistry([ObserverKey(*row) for row in rows])

def test_staging_activation_and_revocation():
    a, b = pub(), pub()
    first = registry(("a", a, "active"), ("b", b, "staged"))
    second = registry(("a", a, "active"), ("b", b, "active"))
    third = registry(("a", a, "revoked"), ("b", b, "active"))
    assert validate_rotation(first, second)["active"] == ["a", "b"]
    assert validate_rotation(second, third)["revoked"] == ["a"]
    with pytest.raises(ObserverKeyDenied):
        validate_rotation(third, second)

def test_rotation_denies_key_substitution_disappearing_keys_and_unstaged_additions():
    a, b = pub(), pub()
    initial = registry(("a", a, "active"))
    cases = [
        registry(("a", b, "active")),
        registry(("b", b, "staged")),
        registry(("a", a, "active"), ("b", b, "active")),
        registry(("a", a, "revoked")),
    ]
    for candidate in cases:
        with pytest.raises(ObserverKeyDenied):
            validate_rotation(initial, candidate)
    with pytest.raises(ObserverKeyDenied):
        registry(("a", a, "active"), ("b", a, "staged"))
