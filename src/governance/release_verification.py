"""Offline, key-pinned release artifact manifest verification.

A release publisher must sign manifests externally with an independently
managed private key. This module never generates production signing keys or
treats hashes alone as release authentication.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class UntrustedRelease(ValueError):
    pass


def canonical_manifest(manifest: dict) -> bytes:
    if not isinstance(manifest, dict) or set(manifest) != {"version", "artifacts", "source_commit"}:
        raise UntrustedRelease("invalid release manifest fields")
    if manifest["version"] != 1:
        raise UntrustedRelease("unsupported release manifest version")
    commit = manifest["source_commit"]
    if not isinstance(commit, str) or len(commit) != 40 or any(x not in "0123456789abcdef" for x in commit):
        raise UntrustedRelease("invalid pinned source commit")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise UntrustedRelease("release must contain named artifacts")
    for name, digest in artifacts.items():
        if (not isinstance(name, str) or not name or len(name) > 256
                or "/" in name or "\\" in name or name in (".", "..")
                or not isinstance(digest, str) or len(digest) != 64
                or any(x not in "0123456789abcdef" for x in digest)):
            raise UntrustedRelease("invalid artifact filename or digest")
    return b"agentbridge-release-manifest-v1:" + json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def verify_release(directory: str, manifest: dict, signature_hex: str,
                   trusted_public_key_hex: str, *, expected_source_commit: str):
    if manifest.get("source_commit") != expected_source_commit:
        raise UntrustedRelease("release source commit mismatch")
    payload = canonical_manifest(manifest)
    try:
        key = bytes.fromhex(trusted_public_key_hex)
        sig = bytes.fromhex(signature_hex)
        if len(key) != 32 or len(sig) != 64:
            raise ValueError("invalid Ed25519 encoding")
        Ed25519PublicKey.from_public_bytes(key).verify(sig, payload)
    except (TypeError, ValueError, Exception) as exc:
        raise UntrustedRelease("manifest signature invalid") from exc
    root = Path(directory).resolve(strict=True)
    for name, digest in manifest["artifacts"].items():
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_file():
            raise UntrustedRelease("missing or linked artifact")
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            raise UntrustedRelease("artifact checksum mismatch")
    return True
