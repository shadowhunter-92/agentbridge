"""Bounded HTTPS readback boundary tests (synthetic; no external HTTP calls)."""
import copy
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from src.governance.https_readback_adapter import (
    validated_origin, fetch_authoritative_receipt,
    observe_authoritative_receipt, ReadbackUnavailable,
)
from src.governance.destination_receipts import canonical_receipt_payload
from src.governance.readback_attestations import verify_readback_attestation


def pub(k):
    return k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def test_bounded_origin_denies_untrusted_targets():
    for origin in ("http://trusted.example", "https://localhost", "https://127.0.0.1",
                   "https://trusted.example:8443", "https://trusted.example/redirect",
                   "https://user:secret@trusted.example", "https://trusted.example.evil/anything"):
        with pytest.raises(ReadbackUnavailable):
            validated_origin(origin)
    assert validated_origin("https://observer.example/") == "https://observer.example"


def test_missing_readback_credentials_fail_closed_before_network():
    with pytest.raises(ReadbackUnavailable):
        fetch_authoritative_receipt("https://observer.example", "agent", "op",
                                    read_only_token="too-short")
    with pytest.raises(ReadbackUnavailable):
        fetch_authoritative_receipt("https://observer.example", "agent", "op",
                                    read_only_token="A" * 32, timeout=31)


def test_signed_remote_claim_and_tamper_detection():
    dest, observer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    receipt = dict(agent_id="agent", operation_id="op", fingerprint="intent-sha",
                   outcome="succeeded", external_reference="synthetic-id")
    receipt["signature_hex"] = dest.sign(canonical_receipt_payload(receipt)).hex()
    original, att = observe_authoritative_receipt(
        receipt=receipt, agent_id="agent", operation_id="op",
        fingerprint="intent-sha", destination_public_key_hex=pub(dest),
        source="https://observer.example", sign=observer.sign,
    )
    assert original == receipt
    assert verify_readback_attestation(
        att, agent_id="agent", operation_id="op", fingerprint="intent-sha",
        outcome="succeeded", external_reference="synthetic-id",
        destination_receipt_sha256=att["destination_receipt_sha256"],
        trusted_readback_key_hex=pub(observer), destination_key_hex=pub(dest),
    )
    changed = copy.deepcopy(receipt)
    changed["external_reference"] = "tampered"
    with pytest.raises(ReadbackUnavailable):
        observe_authoritative_receipt(
            receipt=changed, agent_id="agent", operation_id="op",
            fingerprint="intent-sha", destination_public_key_hex=pub(dest),
            source="https://observer.example", sign=observer.sign,
        )
