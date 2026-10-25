"""Fail-closed HTTPS authoritative readback adapter regression tests.

All network responses are synthetic. This does NOT certify a real provider API,
independent credentials, production TLS isolation or external readback truth.
"""
import io
import json
import socket
from email.message import Message
from unittest.mock import Mock, patch
from urllib.response import addinfourl

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.https_readback_adapter import (
    ReadbackUnavailable, fetch_authoritative_receipt,
    observe_authoritative_receipt, validated_origin, fetch_and_attest_authoritative_state,
)
from src.governance.destination_receipts import canonical_receipt_payload
from src.governance.readback_attestations import verify_readback_attestation


def pub(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


class _RecordingBody(io.BytesIO):
    def __init__(self, payload, read_error=None):
        super().__init__(payload)
        self.read_error = read_error
        self.read_limits = []
        self.returned_bytes = 0

    def read(self, limit=-1):
        self.read_limits.append(limit)
        if self.read_error is not None:
            raise self.read_error
        value = super().read(limit)
        self.returned_bytes += len(value)
        return value


class _SyntheticTransport:
    """Replace only wire I/O; retain urllib's real response/redirect handlers."""

    def __init__(self, payload, *, status=200, content_type="application/json",
                 location=None, open_error=None, read_error=None):
        self.status = status
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if location is not None:
            self.headers["Location"] = location
        self.open_error = open_error
        self.body = _RecordingBody(payload, read_error)
        self.requests = []

    def open(self, request):
        self.requests.append(request)
        if self.open_error is not None:
            raise self.open_error
        response = addinfourl(self.body, self.headers, request.full_url, self.status)
        response.msg = "synthetic response"
        return response


@pytest.fixture
def synthetic_https(monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("synthetic HTTPS test attempted real DNS or socket I/O")

    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    def install(payload, **kwargs):
        transport = _SyntheticTransport(payload, **kwargs)

        def do_open(handler, connection_class, request, **connection_options):
            return transport.open(request)

        monkeypatch.setattr("urllib.request.AbstractHTTPHandler.do_open", do_open)
        return transport

    return install


def _attest(sign):
    return fetch_and_attest_authoritative_state(
        origin="https://api.example.com", agent_id="agent", operation_id="op-1",
        fingerprint="requested-action", read_only_token="synthetic-token-" + "x" * 32,
        destination_public_key_hex="0" * 64, sign=sign)


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


def test_https_fetch_uses_get_and_exact_escaped_operation_path(synthetic_https):
    transport = synthetic_https(json.dumps({"receipt": {"outcome": "unknown"}}).encode())
    token = "synthetic-token-" + "x" * 32
    assert fetch_authoritative_receipt(
        "https://api.example.com", "agent/with ?", "op/1#two",
        read_only_token=token) == {"outcome": "unknown"}
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.get_method() == "GET"
    assert request.full_url == "https://api.example.com/v1/operations/agent%2Fwith%20%3F/op%2F1%23two"
    assert request.get_header("Authorization") == "Bearer " + token
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Cache-control") == "no-store"
    assert request.timeout == 8
    assert transport.body.read_limits == [32769]


def test_short_readback_credential_fails_before_opener_construction():
    with patch("src.governance.https_readback_adapter.build_opener") as built:
        with pytest.raises(ReadbackUnavailable, match="credential missing or malformed"):
            fetch_authoritative_receipt(
                "https://api.example.com", "agent", "op-1", read_only_token="short")
    built.assert_not_called()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("location", ["https://other.example.com/collect", "/elsewhere", "http://other.example.com/collect"])
def test_https_redirect_is_rejected_without_second_request_or_signing(synthetic_https, status, location):
    transport = synthetic_https(b'{"receipt":{}}', status=status, location=location)
    sign = Mock()
    with pytest.raises(ReadbackUnavailable, match="readback redirects are prohibited"):
        _attest(sign)
    assert len(transport.requests) == 1
    original = transport.requests[0]
    assert original.full_url == "https://api.example.com/v1/operations/agent/op-1"
    assert original.get_method() == "GET"
    assert original.get_header("Authorization") == "Bearer synthetic-token-" + "x" * 32
    assert transport.body.read_limits == []
    sign.assert_not_called()


@pytest.mark.parametrize("size", [32769, 65536])
def test_oversized_readback_stops_at_one_bounded_read_without_signing(synthetic_https, size):
    prefix = b'{"receipt":{}}'
    transport = synthetic_https(prefix + b" " * (size - len(prefix)))
    sign = Mock()
    with pytest.raises(ReadbackUnavailable, match="readback response too large"):
        _attest(sign)
    assert len(transport.requests) == 1
    assert transport.body.read_limits == [32769]
    assert transport.body.returned_bytes == 32769
    sign.assert_not_called()


def test_exact_readback_byte_limit_accepts_valid_json(synthetic_https):
    destination, observer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    receipt = dict(agent_id="agent", operation_id="op-1", fingerprint="requested-action",
                   outcome="succeeded", external_reference="target/task/1")
    receipt["signature_hex"] = destination.sign(canonical_receipt_payload(receipt)).hex()
    prefix = json.dumps({"receipt": receipt}).encode()
    transport = synthetic_https(prefix + b" " * (32768 - len(prefix)))
    sign = Mock(wraps=observer.sign)
    returned, proof = fetch_and_attest_authoritative_state(
        origin="https://api.example.com", agent_id="agent", operation_id="op-1",
        fingerprint="requested-action", read_only_token="x" * 40,
        destination_public_key_hex=pub(destination), sign=sign)
    assert returned == receipt
    assert len(transport.requests) == 1
    assert transport.body.read_limits == [32769]
    assert transport.body.returned_bytes == 32768
    sign.assert_called_once()
    assert len(verify_readback_attestation(
        proof, agent_id="agent", operation_id="op-1", fingerprint="requested-action", outcome="succeeded",
        external_reference="target/task/1", destination_receipt_sha256=proof["destination_receipt_sha256"],
        trusted_readback_key_hex=pub(observer), destination_key_hex=pub(destination))) == 64


@pytest.mark.parametrize("status, reason", [
    (201, "authoritative readback response invalid"),
    (204, "authoritative readback response invalid"),
    (404, "readback unavailable; outcome remains unknown"),
    (503, "readback unavailable; outcome remains unknown"),
])
def test_non_200_readback_never_signs(synthetic_https, status, reason):
    transport = synthetic_https(b'{"receipt":{}}', status=status)
    sign = Mock()
    with pytest.raises(ReadbackUnavailable, match=reason):
        _attest(sign)
    assert len(transport.requests) == 1
    assert transport.body.read_limits == []
    sign.assert_not_called()


@pytest.mark.parametrize("content_type", [None, "text/html", "application/octet-stream"])
def test_wrong_readback_content_type_is_rejected_before_body_read(synthetic_https, content_type):
    transport = synthetic_https(b'{"receipt":{}}', content_type=content_type)
    sign = Mock()
    with pytest.raises(ReadbackUnavailable, match="authoritative readback response invalid"):
        _attest(sign)
    assert len(transport.requests) == 1
    assert transport.body.read_limits == []
    sign.assert_not_called()


@pytest.mark.parametrize("payload", [b"", b"{", b"\xff"], ids=["empty", "broken-json", "invalid-utf8"])
def test_malformed_readback_json_never_signs(synthetic_https, payload):
    transport = synthetic_https(payload)
    sign = Mock()
    with pytest.raises(ReadbackUnavailable, match="readback response not JSON"):
        _attest(sign)
    assert len(transport.requests) == 1
    assert transport.body.read_limits == [32769]
    sign.assert_not_called()


@pytest.mark.parametrize("body", [
    [], None, {}, {"other": {}}, {"receipt": None}, {"receipt": []}, {"receipt": {}, "extra": True},
], ids=["array", "null", "missing", "wrong-field", "null-receipt", "array-receipt", "extra-field"])
def test_invalid_readback_wrapper_never_signs(synthetic_https, body):
    transport = synthetic_https(json.dumps(body).encode())
    sign = Mock()
    with pytest.raises(ReadbackUnavailable, match="readback body must contain exactly one receipt"):
        _attest(sign)
    assert len(transport.requests) == 1
    assert transport.body.read_limits == [32769]
    sign.assert_not_called()


@pytest.mark.parametrize("stage", ["open", "read"])
def test_transport_timeout_keeps_outcome_unavailable_without_signing(synthetic_https, stage):
    timeout = TimeoutError("synthetic readback timeout")
    transport = synthetic_https(b'{"receipt":{}}', **{stage + "_error": timeout})
    sign = Mock()
    with pytest.raises(ReadbackUnavailable, match="readback unavailable; outcome remains unknown") as failure:
        _attest(sign)
    assert failure.value.__cause__ is timeout
    assert len(transport.requests) == 1
    assert transport.body.read_limits == ([32769] if stage == "read" else [])
    sign.assert_not_called()


def test_environment_proxy_is_not_used_for_authenticated_readback(synthetic_https, monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://untrusted-proxy.example:8080")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    transport = synthetic_https(b'{"receipt":{}}')
    with patch("urllib.request.getproxies", return_value={"https": "http://untrusted-proxy.example:8080"}) as proxies:
        assert fetch_authoritative_receipt(
            "https://api.example.com", "agent", "op-1", read_only_token="x" * 40) == {}
    proxies.assert_not_called()
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.host == "api.example.com"
    assert request.type == "https"
    assert not request.has_proxy()
    assert request._tunnel_host is None
    assert request.get_header("Proxy-authorization") is None


def test_integrated_readback_entrypoint_binds_fetch_to_source_and_signed_observation(synthetic_https):
    destination = Ed25519PrivateKey.generate()
    observer = Ed25519PrivateKey.generate()
    receipt = dict(agent_id="agent", operation_id="op-long-0123456789",
                   fingerprint="requested-action", outcome="succeeded",
                   external_reference="target/task/1")
    receipt["signature_hex"] = destination.sign(canonical_receipt_payload(receipt)).hex()
    transport = synthetic_https(json.dumps({"receipt": receipt}).encode())
    sign = Mock(wraps=observer.sign)
    returned, proof = fetch_and_attest_authoritative_state(
        origin="https://api.example.com", agent_id="agent",
        operation_id="op-long-0123456789", fingerprint="requested-action",
        read_only_token="r" * 40, destination_public_key_hex=pub(destination), sign=sign)
    assert returned == receipt
    assert len(transport.requests) == 1
    assert transport.requests[0].full_url == "https://api.example.com/v1/operations/agent/op-long-0123456789"
    assert transport.requests[0].get_header("Authorization") == "Bearer " + "r" * 40
    assert transport.requests[0].timeout == 8
    assert proof["source"] == "https://api.example.com"
    assert len(verify_readback_attestation(
        proof, agent_id="agent", operation_id="op-long-0123456789",
        fingerprint="requested-action", outcome="succeeded", external_reference="target/task/1",
        destination_receipt_sha256=proof["destination_receipt_sha256"],
        trusted_readback_key_hex=pub(observer), destination_key_hex=pub(destination))) == 64
    sign.assert_called_once()
    sign.reset_mock()
    with patch("src.governance.https_readback_adapter.fetch_authoritative_receipt",
               side_effect=ReadbackUnavailable("no authoritative result")):
        with pytest.raises(ReadbackUnavailable, match="no authoritative result"):
            fetch_and_attest_authoritative_state(
                origin="https://api.example.com", agent_id="agent",
                operation_id="op-long-0123456789", fingerprint="requested-action",
                read_only_token="r" * 40, destination_public_key_hex=pub(destination), sign=sign)
    sign.assert_not_called()
