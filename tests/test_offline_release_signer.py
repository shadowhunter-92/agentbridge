"""Release signing helper produces a manifest the independent verifier accepts."""
import hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from tools.sign_release_manifest import create_signed_manifest
from src.governance.release_verification import verify_release
import pytest


def test_offline_release_signer_matches_pinned_verifier(tmp_path):
    root=tmp_path/"dist"
    root.mkdir()
    (root/"agentbridge.whl").write_bytes(b"review-only wheel")
    key=Ed25519PrivateKey.generate()
    seed=key.private_bytes(
        serialization.Encoding.Raw,serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    path=tmp_path/"signing.key"
    path.write_bytes(seed)
    path.chmod(0o600)
    manifest,sig=create_signed_manifest(
        root,source_commit="a"*40,key_file=path)
    pub=key.public_key().public_bytes(
        serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
    assert verify_release(str(root),manifest,sig,pub,expected_source_commit="a"*40)
    (root/"agentbridge.whl").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify_release(str(root),manifest,sig,pub,expected_source_commit="a"*40)


def test_signer_refuses_unsafe_key_permissions_and_symlink(tmp_path):
    root=tmp_path/"dist";root.mkdir()
    (root/"file.whl").write_bytes(b"sample")
    key=tmp_path/"private.key";key.write_bytes(b"x"*32)
    key.chmod(0o644)
    with pytest.raises(ValueError,match="owner-only"):
        create_signed_manifest(root,source_commit="b"*40,key_file=key)
