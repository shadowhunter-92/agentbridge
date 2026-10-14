"""Raw Ed25519 private key bytes must never be normalized by text helpers."""
import os
import stat

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from src.governance.sandbox_observer_service import _restricted_secret


def test_raw_private_key_preserves_leading_or_trailing_whitespace_octets(tmp_path):
    key_file = tmp_path / "key.raw"
    # Valid Ed25519 seeds may contain 0x20, 0x09 or 0x0a at either end.
    raw = b" " + bytes(range(1, 31)) + b"\n"
    assert len(raw) == 32
    key_file.write_bytes(raw)
    if os.name == "posix":
        key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert _restricted_secret(str(key_file)) == raw
    key = Ed25519PrivateKey.from_private_bytes(_restricted_secret(str(key_file)))
    assert len(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)) == 32
