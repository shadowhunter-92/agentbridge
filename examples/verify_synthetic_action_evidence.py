"""Run a self-contained, synthetic action-evidence SDK evaluation.

Usage: python examples/verify_synthetic_action_evidence.py

Never use test-generated keys or local SQLite observations as production trust
roots. No network or customer integrations are performed.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.sandbox_readback import SandboxReadOnlyObserver, SandboxTarget
from src.governance.trust_sdk import verify_action_evidence


def public_hex(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def evaluate():
    destination_signer = Ed25519PrivateKey.generate()
    observer_signer = Ed25519PrivateKey.generate()
    agent, operation = "evaluation-agent", "synthetic-operation-1234567890"
    fingerprint = "synthetic-request-fingerprint"

    with tempfile.TemporaryDirectory(prefix="agentbridge-eval-") as root:
        path = str(Path(root) / "isolated-destination.sqlite3")
        with SandboxTarget(path, sign=destination_signer.sign) as target:
            committed = target.commit(
                agent_id=agent, operation_id=operation, fingerprint=fingerprint
            )
            with SandboxReadOnlyObserver(
                path,
                destination_public_key_hex=public_hex(destination_signer),
                sign=observer_signer.sign,
            ) as observer:
                receipt, attestation = observer.observe(
                    agent_id=agent, operation_id=operation,
                    fingerprint=fingerprint,
                )
                args = dict(
                    destination_receipt=receipt,
                    readback_attestation=attestation,
                    agent_id=agent, operation_id=operation,
                    fingerprint=fingerprint, outcome="succeeded",
                    external_reference=committed["external_reference"],
                    destination_key_hex=public_hex(destination_signer),
                    readback_key_hex=public_hex(observer_signer),
                )
                verified = verify_action_evidence(**args)
                assert verified.outcome == "succeeded"
                assert len(verified.readback_sha256) == 64

                # Do not accept a claimed outcome inconsistent with signed evidence.
                try:
                    verify_action_evidence(**{**args, "outcome": "failed"})
                except ValueError:
                    rejected = True
                else:
                    rejected = False
                assert rejected, "tampered result was accepted"
                return {
                    "scope": "local synthetic SQLite only",
                    "signed_receipt_verified": True,
                    "separately_signed_readback_verified": True,
                    "altered_outcome_rejected": True,
                    "external_production_truth_verified": False,
                }


if __name__ == "__main__":
    import json
    print(json.dumps(evaluate(), indent=2, sort_keys=True))
