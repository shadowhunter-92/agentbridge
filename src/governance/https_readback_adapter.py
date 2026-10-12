"""Read-only HTTPS authoritative state adapter: integration building block.

An independent deployment configures a FIXED destination origin, a read-only
credential and a separately controlled observer signing key. It reads a signed
stored destination receipt, verifies that receipt and signs a bounded
operation-specific observation. It is not proof of independent operator
control or a finished third-party integration by itself.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import time
from urllib.parse import urlsplit, quote
from urllib.request import build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler, Request

from .destination_receipts import verify_destination_receipt, UntrustedReceipt
from .readback_attestations import canonical_readback_payload


class ReadbackUnavailable(ValueError):
    pass


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReadbackUnavailable("readback redirects are prohibited")


def validated_origin(url: str) -> str:
    if not isinstance(url, str) or len(url) > 512:
        raise ReadbackUnavailable("fixed HTTPS origin required")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ReadbackUnavailable("invalid readback origin") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ("", "/") or parsed.query
            or parsed.fragment or parsed.port not in (None, 443)
            or parsed.hostname.endswith(".") or not parsed.hostname.isascii()
            or any(c in parsed.hostname for c in "[]%")
            or parsed.hostname.lower() in ("localhost", "localhost.localdomain")):
        raise ReadbackUnavailable("readback requires a fixed public HTTPS host")
    # Disallow IP literals. DNS/network egress remains separately enforced.
    import ipaddress
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ReadbackUnavailable("IP-literal readback origin prohibited")
    if "." not in parsed.hostname:
        raise ReadbackUnavailable("readback hostname must be fully qualified")
    return "https://" + parsed.hostname.lower()


def fetch_authoritative_receipt(origin: str, agent_id: str, operation_id: str,
                                *, read_only_token: str, timeout: int = 8) -> dict:
    """GET only, exact path, no redirects or environment-selected HTTP proxy.

    The readback API MUST source its response from the destination system of
    record. Trust, certificate and network restrictions require deployment
    validation; a direct HTTPS call alone does not guarantee egress isolation.
    """
    base = validated_origin(origin)
    if not isinstance(read_only_token, str) or len(read_only_token) < 32 or "\r" in read_only_token or "\n" in read_only_token:
        raise ReadbackUnavailable("read-only observer credential missing or malformed")
    for val in (agent_id, operation_id):
        if not isinstance(val, str) or not val or len(val) > 256:
            raise ReadbackUnavailable("invalid readback operation reference")
    if not isinstance(timeout, int) or not 1 <= timeout <= 30:
        raise ReadbackUnavailable("timeout outside bounded limits")
    url = base + "/v1/operations/" + quote(agent_id, safe="") + "/" + quote(operation_id, safe="")
    req = Request(url, method="GET", headers={
        "Authorization": "Bearer " + read_only_token,
        "Accept": "application/json",
        "Cache-Control": "no-store",
    })
    context = ssl.create_default_context()
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), _RejectRedirects())
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise ReadbackUnavailable("authoritative readback response invalid")
            raw = response.read(32769)
    except ReadbackUnavailable:
        raise
    except Exception as exc:
        raise ReadbackUnavailable("readback unavailable; outcome remains unknown") from exc
    if len(raw) > 32768:
        raise ReadbackUnavailable("readback response too large")
    try:
        body = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ReadbackUnavailable("readback response not JSON") from exc
    if not isinstance(body, dict) or set(body) != {"receipt"} or not isinstance(body["receipt"], dict):
        raise ReadbackUnavailable("readback body must contain exactly one receipt")
    return body["receipt"]


def observe_authoritative_receipt(
    *, receipt: dict, agent_id: str, operation_id: str,
    fingerprint: str, destination_public_key_hex: str, source: str, sign
) -> tuple[dict, dict]:
    """Only sign independently fetched and destination-verified observed state.

    A missing receipt or a mismatched outcome does not establish 'failed':
    it remains UNKNOWN and must be escalated for manual inspection.
    """
    if not isinstance(source, str) or not source.startswith("https://") or len(source) > 512:
        raise ReadbackUnavailable("independent readback source identifier required")
    try:
        digest = verify_destination_receipt(
            receipt, agent_id=agent_id, operation_id=operation_id,
            fingerprint=fingerprint, trusted_public_key_hex=destination_public_key_hex)
    except (UntrustedReceipt, ValueError, TypeError) as exc:
        raise ReadbackUnavailable("destination receipt untrusted") from exc
    if receipt["outcome"] not in ("succeeded", "failed"):
        raise ReadbackUnavailable("destination has no final authoritative outcome")
    observation = {
        "agent_id": agent_id,
        "operation_id": operation_id,
        "fingerprint": fingerprint,
        "outcome": receipt["outcome"],
        "external_reference": receipt["external_reference"],
        "observed_at": int(time.time()),
        "source": source,
        "source_evidence_sha256": hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        "destination_receipt_sha256": digest,
    }
    if not callable(sign):
        raise ReadbackUnavailable("independently controlled observer signer required")
    signature = sign(canonical_readback_payload(observation))
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise ReadbackUnavailable("invalid observer signature")
    observation["signature_hex"] = signature.hex()
    return receipt, observation


def fetch_and_attest_authoritative_state(
    *, origin: str, agent_id: str, operation_id: str, fingerprint: str,
    read_only_token: str, destination_public_key_hex: str, sign,
    timeout: int = 8,
) -> tuple[dict, dict]:
    """Read from pinned destination origin before independently signing.

    This is the constrained integration entry point. Passing a caller-supplied
    receipt to observe_authoritative_receipt alone cannot prove independent
    observation. Caller MUST provision a separately administered read-only
    API credential and observer signer, and enforce an external egress policy.
    """
    source = validated_origin(origin)
    receipt = fetch_authoritative_receipt(
        source, agent_id, operation_id, read_only_token=read_only_token,
        timeout=timeout)
    return observe_authoritative_receipt(
        receipt=receipt, agent_id=agent_id, operation_id=operation_id,
        fingerprint=fingerprint, destination_public_key_hex=destination_public_key_hex,
        source=source, sign=sign)
