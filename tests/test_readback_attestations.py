"""Readback trust-boundary negative tests using inert cryptographic evidence."""
import hashlib
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.readback_attestations import (
    UntrustedReadback, canonical_readback_payload, verify_readback_attestation,
)


def test_readback_rejects_replay_and_corruption():
    destination = Ed25519PrivateKey.generate()
    verifier = Ed25519PrivateKey.generate()
    public = lambda key: key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw).hex()
    digest = hashlib.sha256(b"destination receipt").hexdigest()
    proof = dict(agent_id="agent", operation_id="op-12345678901234",
                 fingerprint="request-fingerprint", outcome="succeeded",
                 external_reference="remote/item/10", observed_at=1000,
                 source="independently queried destination API",
                 source_evidence_sha256=hashlib.sha256(b"state").hexdigest(),
                 destination_receipt_sha256=digest)
    def sign(value):
        return {**value, "signature_hex": verifier.sign(canonical_readback_payload(value)).hex()}
    def check(value, **overrides):
        return verify_readback_attestation(
            value, agent_id="agent", operation_id="op-12345678901234",
            fingerprint="request-fingerprint", outcome="succeeded",
            external_reference="remote/item/10", destination_receipt_sha256=digest,
            trusted_readback_key_hex=public(verifier),
            destination_key_hex=public(destination), now=1001,
            max_age_seconds=60, **overrides)
    signed = sign(proof)
    assert len(check(signed)) == 64
    for modified in (
        {**signed, "outcome": "failed"},
        {**signed, "operation_id": "other"},
        {**signed, "source_evidence_sha256": "0" * 64},
        {**signed, "extra": "unsigned metadata"},
        sign({**proof, "observed_at": 100}),
        sign({**proof, "observed_at": 2000}),
    ):
        with pytest.raises(UntrustedReadback):
            check(modified)
    with pytest.raises(UntrustedReadback, match="independent trust root"):
        verify_readback_attestation(
            signed, agent_id="agent", operation_id="op-12345678901234",
            fingerprint="request-fingerprint", outcome="succeeded",
            external_reference="remote/item/10", destination_receipt_sha256=digest,
            trusted_readback_key_hex=public(verifier), destination_key_hex=public(verifier),
            now=1001, max_age_seconds=60)
