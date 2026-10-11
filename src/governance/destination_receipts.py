"""Operator-independent, request-bound signed destination receipt verification.

A receipt is a signed statement from a configured destination public key.
It is NOT proof of physical execution; operators must trust the destination's
measurement and its key distribution. No arbitrary caller-provided signer keys.
"""
import hashlib
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


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
