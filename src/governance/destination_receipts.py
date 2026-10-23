"""Operator-independent, request-bound signed destination receipt verification.

A receipt is a signed statement from a configured destination public key.
It is NOT proof of physical execution; operators must trust the destination's
measurement and its key distribution. No arbitrary caller-provided signer keys.
"""
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .queued_destination_contract import (
    MAX_AUTHORIZATION_BYTES,
    MAX_RECEIPT_BYTES,
    MAX_RESULT_BYTES,
    canonical_queued_json,
    demo_result,
    normalize_queued_descriptor,
    parse_demo_action,
    queued_descriptor_sha256,
    queued_hex,
    queued_identifier,
    queued_seconds,
)


class UntrustedReceipt(ValueError):
    pass


def canonical_receipt_payload(receipt):
    allowed=("agent_id","operation_id","fingerprint","outcome","external_reference")
    return json.dumps({name: receipt[name] for name in allowed},
                      sort_keys=True,separators=(",",":")).encode()


def verify_destination_receipt(receipt, *, agent_id, operation_id, fingerprint,
                               trusted_public_key_hex):
    if not isinstance(receipt,dict) or not isinstance(trusted_public_key_hex,str):
        raise UntrustedReceipt("missing trusted destination configuration")
    # Refuse unsigned metadata and ambiguous envelopes: the signature covers
    # every accepted semantic field (except the signature itself).
    required = {"agent_id", "operation_id", "fingerprint", "outcome",
                "external_reference", "signature_hex"}
    if set(receipt) != required:
        raise UntrustedReceipt("unexpected or missing receipt fields")
    if any(not isinstance(receipt[name], str) or not receipt[name]
           or len(receipt[name]) > 512
           for name in ("agent_id", "operation_id", "fingerprint",
                        "external_reference")):
        raise UntrustedReceipt("invalid receipt identifiers")
    if (not isinstance(receipt["signature_hex"], str)
            or len(receipt["signature_hex"]) != 128):
        raise UntrustedReceipt("invalid signature encoding")
    if (receipt.get("agent_id") != agent_id
            or receipt.get("operation_id") != operation_id
            or receipt.get("fingerprint") != fingerprint
            or receipt.get("outcome") not in ("succeeded","failed")
            or not isinstance(receipt.get("external_reference"),str)
            or not receipt["external_reference"]):
        raise UntrustedReceipt("destination receipt does not match claimed operation")
    try:
        key=Ed25519PublicKey.from_public_bytes(bytes.fromhex(trusted_public_key_hex))
        key.verify(bytes.fromhex(receipt["signature_hex"]),canonical_receipt_payload(receipt))
    except (ValueError,KeyError,TypeError) as exc:
        raise UntrustedReceipt("malformed destination receipt") from exc
    except Exception as exc:
        raise UntrustedReceipt("invalid destination signature") from exc
    return hashlib.sha256(canonical_receipt_payload(receipt)).hexdigest()


# Strict v2 envelopes intentionally do not broaden the accepted v1 fields.
_AUTHORIZATION_FIELDS = (
    "domain", "tenant_id", "store_id", "owner_id", "agent_id", "authority_sha256",
    "task_id", "context_id", "intent_sha256", "admission_link_sha256", "fingerprint",
    "original_action_sha256", "target_id", "target_configuration_sha256", "destination_id",
    "operation_id", "action_sha256", "result_limit_bytes", "attempt_id", "fence_scope",
    "fence_owner", "fence_epoch", "issued_at", "expires_at", "authorizer_key_id",
)
_QUEUED_RECEIPT_FIELDS = (
    "domain", "authorization_sha256", "tenant_id", "agent_id", "operation_id", "fingerprint",
    "target_id", "destination_id", "attempt_id", "fence_epoch", "action_sha256", "outcome",
    "external_reference", "committed_at", "result_sha256", "destination_key_id",
)


def canonical_queued_authorization_payload(authorization):
    return canonical_queued_json({name: authorization[name] for name in _AUTHORIZATION_FIELDS})


def queued_authorization_sha256(authorization):
    """Bind both the exact authorization payload and its signature."""
    return hashlib.sha256(canonical_queued_json(authorization)).hexdigest()


def _verify_queued_signature(envelope, payload, public_key_hex, label):
    if not queued_hex(envelope.get("signature_hex"), 128):
        raise UntrustedReceipt("invalid " + label + " signature encoding")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(
            bytes.fromhex(envelope["signature_hex"]), payload)
    except Exception as exc:
        raise UntrustedReceipt("invalid " + label + " signature") from exc


def verify_queued_authorization(authorization, *, descriptor, action_bytes, now=None):
    """Check mint-time authority; execution MUST pass destination time after lock.

    ``now=None`` deliberately supports historical readback. It is never enough
    to authorize a new destination effect. The destination also checks its fence
    and signed expiry inside the same effect transaction.
    """
    try:
        descriptor = normalize_queued_descriptor(descriptor)
        parse_demo_action(action_bytes)
        if not isinstance(authorization, dict) or set(authorization) != {*_AUTHORIZATION_FIELDS, "signature_hex"}:
            raise UntrustedReceipt("unexpected or missing queued authorization fields")
        if len(canonical_queued_json(authorization)) > MAX_AUTHORIZATION_BYTES:
            raise UntrustedReceipt("queued authorization exceeds byte limit")
        identifiers = ("tenant_id", "store_id", "owner_id", "agent_id", "task_id", "context_id", "target_id",
                       "destination_id", "operation_id", "attempt_id", "fence_scope", "fence_owner", "authorizer_key_id")
        if any(not queued_identifier(authorization[name]) for name in identifiers):
            raise UntrustedReceipt("invalid queued authorization identifier")
        digests = ("authority_sha256", "intent_sha256", "admission_link_sha256", "fingerprint",
                   "original_action_sha256", "target_configuration_sha256", "action_sha256")
        if any(not queued_hex(authorization[name]) for name in digests):
            raise UntrustedReceipt("invalid queued authorization digest")
        if (authorization["domain"] != "agentbridge.queued-authorization.v2"
                or authorization["tenant_id"] != descriptor["tenant_id"]
                or authorization["target_id"] != descriptor["target_id"]
                or authorization["destination_id"] != descriptor["destination_id"]
                or authorization["authorizer_key_id"] != descriptor["authorizer_key_id"]
                or authorization["target_configuration_sha256"] != queued_descriptor_sha256(descriptor)
                or authorization["action_sha256"] != hashlib.sha256(action_bytes).hexdigest()):
            raise UntrustedReceipt("queued authorization disagrees with configured destination or action")
        if (type(authorization["fence_epoch"]) is not int or not 1 <= authorization["fence_epoch"] <= 9223372036854775807
                or type(authorization["result_limit_bytes"]) is not int
                or not 1 <= authorization["result_limit_bytes"] <= 1048576):
            raise UntrustedReceipt("invalid queued authorization epoch or result limit")
        issued, expires = authorization["issued_at"], authorization["expires_at"]
        if (not queued_seconds(issued) or not queued_seconds(expires) or not issued < expires
                or expires > issued + descriptor["call_timeout_seconds"]):
            raise UntrustedReceipt("invalid queued authorization window")
        if now is not None and (not queued_seconds(now) or not issued <= now < expires):
            raise UntrustedReceipt("queued execution authorization is expired or not yet valid")
        _verify_queued_signature(authorization, canonical_queued_authorization_payload(authorization),
                                 descriptor["authorizer_public_key_hex"], "queued authorization")
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, UntrustedReceipt):
            raise
        raise UntrustedReceipt("malformed queued authorization or destination configuration") from exc
    return queued_authorization_sha256(authorization)


def canonical_queued_receipt_payload(receipt):
    return canonical_queued_json({name: receipt[name] for name in _QUEUED_RECEIPT_FIELDS})


def verify_queued_destination_receipt(receipt, *, authorization, action_bytes, descriptor, result):
    """Verify one historical committed action/result; expiry does not erase it."""
    authorization_digest = verify_queued_authorization(
        authorization, descriptor=descriptor, action_bytes=action_bytes)
    try:
        descriptor = normalize_queued_descriptor(descriptor)
        if not isinstance(receipt, dict) or set(receipt) != {*_QUEUED_RECEIPT_FIELDS, "signature_hex"}:
            raise UntrustedReceipt("unexpected or missing queued receipt fields")
        if len(canonical_queued_json(receipt)) > MAX_RECEIPT_BYTES:
            raise UntrustedReceipt("queued receipt exceeds byte limit")
        if (not isinstance(result, dict)
                or canonical_queued_json(result) != canonical_queued_json(demo_result(action_bytes, authorization_digest))
                or len(canonical_queued_json(result)) > MAX_RESULT_BYTES):
            raise UntrustedReceipt("queued result is not the exact bounded demonstration effect")
        expected = {
            "domain": "agentbridge.queued-receipt.v2", "authorization_sha256": authorization_digest,
            **{name: authorization[name] for name in ("tenant_id", "agent_id", "operation_id", "fingerprint",
                                                     "target_id", "destination_id", "attempt_id", "fence_epoch", "action_sha256")},
            "outcome": "succeeded", "external_reference": result["effect_id"],
            "result_sha256": hashlib.sha256(canonical_queued_json(result)).hexdigest(),
            "destination_key_id": descriptor["destination_key_id"],
        }
        if any(receipt[name] != value or type(receipt[name]) is not type(value) for name, value in expected.items()):
            raise UntrustedReceipt("queued receipt does not match exact authorization and result")
        committed = receipt["committed_at"]
        if not queued_seconds(committed) or not authorization["issued_at"] <= committed < authorization["expires_at"]:
            raise UntrustedReceipt("queued receipt commit is outside signed execution window")
        _verify_queued_signature(receipt, canonical_queued_receipt_payload(receipt),
                                 descriptor["destination_public_key_hex"], "queued destination")
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, UntrustedReceipt):
            raise
        raise UntrustedReceipt("malformed queued destination receipt or result") from exc
    return hashlib.sha256(canonical_queued_json(receipt)).hexdigest()
