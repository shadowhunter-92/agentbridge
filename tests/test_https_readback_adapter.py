"""Fail-closed HTTPS authoritative readback adapter regression tests.

All network responses are synthetic. This does NOT certify a real provider API,
independent credentials, production TLS isolation or external readback truth.
"""
import json
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.https_readback_adapter import (
    ReadbackUnavailable, fetch_authoritative_receipt,
    observe_authoritative_receipt, validated_origin,
)
from src.governance.destination_receipts import canonical_receipt_payload
from src.governance.readback_attestations import verify_readback_attestation


def pub(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


@pytest.mark.parametrize("origin", [
    "http://api.example.com", "https://127.0.0.1",
    "https://localhost", "https://user:pass@api.example.com",
    "https://api.example.com:8443", "https://api.example.com/bad",
    "https://api.example.com/?a=b", "https://api.example.com/#fragment",
    "https://[::1]", "https://api.example.com.",
])
def test_invalid_destination_origins_denied(origin):
    with pytest.raises(ReadbackUnavailable):
        validated_origin(origin)


def test_observer_produces_independently_verifiable_signed_claim():
    destination = Ed25519PrivateKey.generate()
    observer = Ed25519PrivateKey.generate()
    receipt = dict(agent_id="agent", operation_id="op-long-0123456789",
                   fingerprint="requested-action", outcome="succeeded",
                   external_reference="target/task/1")
    receipt["signature_hex"] = destination.sign(canonical_receipt_payload(receipt)).hex()
    returned, proof = observe_authoritative_receipt(
        receipt=receipt, agent_id="agent", operation_id="op-long-0123456789",
        fingerprint="requested-action", destination_public_key_hex=pub(destination),
        source="https://api.example.com", sign=observer.sign)
    assert returned == receipt
    assert len(verify_readback_attestation(
        proof, agent_id="agent", operation_id="op-long-0123456789",
        fingerprint="requested-action", outcome="succeeded",
        external_reference="target/task/1",
        destination_receipt_sha256=proof["destination_receipt_sha256"],
        trusted_readback_key_hex=pub(observer),
        destination_key_hex=pub(destination))) == 64
    with pytest.raises(ReadbackUnavailable):
        observe_authoritative_receipt(
            receipt={**receipt, "external_reference": "forged"},
            agent_id="agent", operation_id="op-long-0123456789",
            fingerprint="requested-action", destination_public_key_hex=pub(destination),
            source="https://api.example.com", sign=observer.sign)
    with pytest.raises(ReadbackUnavailable):
        observe_authoritative_receipt(
            receipt=receipt, agent_id="agent", operation_id="different",
            fingerprint="requested-action", destination_public_key_hex=pub(destination),
            source="https://api.example.com", sign=observer.sign)


def test_https_fetch_does_not_follow_redirect_and_bounds_payload():
    class Response:
        status = 200
        class headers:
            @staticmethod
            def get_content_type():
                return "application/json"
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def read(self, limit):
            assert limit == 32769
            return json.dumps({"receipt": {"outcome": "unknown"}}).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET"
            assert request.full_url == "https://api.example.com/v1/operations/agent/op-1"
            assert timeout == 8
            return Response()

    with patch("src.governance.https_readback_adapter.build_opener", return_value=Opener()):
        assert fetch_authoritative_receipt(
            "https://api.example.com", "agent", "op-1",
            read_only_token="x" * 40) == {"outcome": "unknown"}
    with pytest.raises(ReadbackUnavailable):
        fetch_authoritative_receipt(
            "https://api.example.com", "agent", "op-1",
            read_only_token="short")
