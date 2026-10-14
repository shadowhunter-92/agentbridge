"""Fail-closed offline Evidence SDK verifier with externally supplied public roots.

This tool never acquires secret keys, performs outbound requests, or implies
that signature-valid statements prove real-world financial settlement.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.governance.observer_key_registry import ObserverKey, ObserverTrustRegistry
from src.governance.trust_sdk import verify_registered_action_evidence


def verify_bundle(bundle: dict, trust: dict, *, now: int | None = None, expected_action: dict | None = None) -> dict:
    if not isinstance(bundle, dict) or set(bundle) != {"receipt", "readback", "expected", "observer_key_id"}:
        raise ValueError("exact evidence bundle fields required")
    if not isinstance(trust, dict) or set(trust) != {"destination_public_key_hex", "observers"}:
        raise ValueError("externally supplied trust roots required")
    expected = bundle["expected"]
    if not isinstance(expected, dict) or set(expected) != {
        "agent_id", "operation_id", "fingerprint", "outcome", "external_reference"
    }:
        raise ValueError("exact independently expected action fields required")
    if expected_action is not None and expected_action != expected:
        raise ValueError("bundle does not match the independently expected action")
    observers = trust["observers"]
    if not isinstance(observers, list) or not observers:
        raise ValueError("no independently enrolled observer keys")
    registry = ObserverTrustRegistry([
        ObserverKey(key_id=x["key_id"], public_key_hex=x["public_key_hex"], state=x["state"])
        for x in observers
    ])
    verified = verify_registered_action_evidence(
        observer_registry=registry,
        observer_key_id=bundle["observer_key_id"],
        destination_receipt=bundle["receipt"],
        readback_attestation=bundle["readback"],
        destination_key_hex=trust["destination_public_key_hex"],
        now=now,
        **expected,
    )
    return {
        "verdict": "signature_and_binding_verified",
        "destination_receipt_sha256": verified.destination_receipt_sha256,
        "readback_sha256": verified.readback_sha256,
        "independent_custody_verified": False,
        "real_world_fulfillment_verified": False,
        "externally_expected_action_verified": expected_action is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--trust", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True,
                        help="independently retained expected action; never take this from the evidence producer")
    args = parser.parse_args()
    def read_json(path):
        with path.open("rb") as stream:
            content = stream.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise ValueError("evidence input exceeds size limit")
        return json.loads(content)
    try:
        bundle = read_json(args.bundle)
        trust = read_json(args.trust)
        expected = read_json(args.expected)
        if not isinstance(expected, dict):
            raise ValueError("independently expected action object required")
        print(json.dumps(verify_bundle(bundle, trust, expected_action=expected), indent=2, sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "DENY", "reason": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
