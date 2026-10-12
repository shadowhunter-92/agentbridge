"""Detached release signatures reject artifact modification and identity swapping."""
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from src.governance.release_verification import (
    UntrustedRelease, canonical_manifest, verify_release,
)


def public(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def test_pinned_release_signature_and_archive_hash(tmp_path):
    signer, impostor = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    archive = tmp_path / "agentbridge-oss.whl"
    archive.write_bytes(b"review-only-wheel-content")
    source_sha = "a" * 40
    manifest = {
        "version": 1,
        "source_commit": source_sha,
        "artifacts": {archive.name: hashlib.sha256(archive.read_bytes()).hexdigest()},
    }
    signed = signer.sign(canonical_manifest(manifest)).hex()
    check = lambda **kw: verify_release(
        str(tmp_path), kw.pop("manifest", manifest), kw.pop("signature_hex", signed),
        kw.pop("trusted_public_key_hex", public(signer)),
        expected_source_commit=kw.pop("expected_source_commit", source_sha),
    )
    assert check()
    for changes in (
        {"expected_source_commit": "b" * 40},
        {"signature_hex": impostor.sign(canonical_manifest(manifest)).hex()},
        {"trusted_public_key_hex": public(impostor)},
        {"manifest": {**manifest, "source_commit": "b" * 40}},
    ):
        with pytest.raises(UntrustedRelease):
            check(**changes)
    archive.write_bytes(b"modified malicious payload")
    with pytest.raises(UntrustedRelease, match="checksum mismatch"):
        check()
