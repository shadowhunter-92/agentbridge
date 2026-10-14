"""Adversarial contract tests for the embedded AgentBridge Evidence SDK.

Scope: synthetic, local destination and read-only observation. These tests
cannot establish operator custody or independent source-of-truth in production.
"""
import copy
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.observer_key_registry import (
    ObserverKey, ObserverKeyDenied, ObserverTrustRegistry
)
from src.governance.readback_attestations import canonical_readback_payload
from src.governance.sandbox_readback import SandboxReadOnlyObserver, SandboxTarget
from src.governance.trust_sdk import (
    verify_action_evidence, verify_registered_action_evidence
)


def _pub(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def _evidence(tmp_path):
    signing_destination = Ed25519PrivateKey.generate()
    signing_observer = Ed25519PrivateKey.generate()
    destination_db = str(tmp_path / "destination.sqlite")
    agent, operation, fingerprint = "agent-A", "operation-A", "fingerprint-A"
    with SandboxTarget(destination_db, sign=signing_destination.sign) as target:
        target.commit(agent_id=agent, operation_id=operation,
                      fingerprint=fingerprint)
        with SandboxReadOnlyObserver(
            destination_db, destination_public_key_hex=_pub(signing_destination),
            sign=signing_observer.sign
        ) as observer:
            receipt, proof = observer.observe(
                agent_id=agent, operation_id=operation,
                fingerprint=fingerprint
            )
    return signing_destination, signing_observer, {
        "destination_receipt": receipt,
        "readback_attestation": proof,
        "agent_id": agent,
        "operation_id": operation,
        "fingerprint": fingerprint,
        "outcome": "succeeded",
        "external_reference": receipt["external_reference"],
        "destination_key_hex": _pub(signing_destination),
        "readback_key_hex": _pub(signing_observer),
    }


def test_pinned_roots_and_registered_key_rotation(tmp_path):
    destination, observer, kwargs = _evidence(tmp_path)
    assert verify_action_evidence(**kwargs).outcome == "succeeded"

    staged = ObserverTrustRegistry([
        ObserverKey("old", _pub(observer), "staged")
    ])
    with pytest.raises(ObserverKeyDenied):
        verify_registered_action_evidence(
            observer_registry=staged, observer_key_id="old",
            **{key: val for key, val in kwargs.items() if key != "readback_key_hex"}
        )

    active = ObserverTrustRegistry([
        ObserverKey("old", _pub(observer), "active")
    ])
    without_override = {key: val for key, val in kwargs.items()
                        if key != "readback_key_hex"}
    assert verify_registered_action_evidence(
        observer_registry=active, observer_key_id="old", **without_override
    ).outcome == "succeeded"

    rotated = ObserverTrustRegistry([
        ObserverKey("old", _pub(observer), "revoked"),
        ObserverKey("new", _pub(Ed25519PrivateKey.generate()), "active"),
    ])
    with pytest.raises(ObserverKeyDenied):
        verify_registered_action_evidence(
            observer_registry=rotated, observer_key_id="old", **without_override
        )
    with pytest.raises(ValueError):
        verify_registered_action_evidence(
            observer_registry=rotated, observer_key_id="new", **without_override
        )
    with pytest.raises(ValueError, match="cannot override"):
        verify_registered_action_evidence(
            observer_registry=active, observer_key_id="old", **kwargs
        )


def test_mismatch_and_tampering_never_settle(tmp_path):
    _destination, observer, kwargs = _evidence(tmp_path)
    cases = [
        {"agent_id": "other-agent"},
        {"operation_id": "other-operation"},
        {"fingerprint": "other-fingerprint"},
        {"outcome": "failed"},
        {"external_reference": "other-reference"},
        {"destination_key_hex": _pub(Ed25519PrivateKey.generate())},
        {"readback_key_hex": _pub(Ed25519PrivateKey.generate())},
        {"readback_key_hex": kwargs["destination_key_hex"]},
    ]
    for update in cases:
        with pytest.raises(ValueError):
            verify_action_evidence(**(kwargs | update))
    for name, value in [
        ("fingerprint", "injected"),
        ("outcome", "failed"),
        ("external_reference", "different"),
        ("signature_hex", "00" * 64),
    ]:
        changed = copy.deepcopy(kwargs)
        changed["destination_receipt"][name] = value
        with pytest.raises(ValueError):
            verify_action_evidence(**changed)
    for name, value in [
        ("source_evidence_sha256", "0" * 64),
        ("destination_receipt_sha256", "1" * 64),
        ("signature_hex", "00" * 64),
    ]:
        changed = copy.deepcopy(kwargs)
        changed["readback_attestation"][name] = value
        with pytest.raises(ValueError):
            verify_action_evidence(**changed)

    # A correctly signed but stale attestation is still not valid evidence.
    changed = copy.deepcopy(kwargs)
    changed["readback_attestation"]["observed_at"] = int(time.time()) - 600
    changed["readback_attestation"]["signature_hex"] = observer.sign(
        canonical_readback_payload(changed["readback_attestation"])
    ).hex()
    with pytest.raises(ValueError):
        verify_action_evidence(**changed)


def test_missing_or_unverifiable_readback_does_not_turn_unknown_into_failed(tmp_path):
    _destination, _observer, kwargs = _evidence(tmp_path)
    bad = copy.deepcopy(kwargs)
    bad["readback_attestation"] = {}
    with pytest.raises(ValueError):
        verify_action_evidence(**bad)

    bad = copy.deepcopy(kwargs)
    bad["destination_receipt"] = {"outcome": "failed"}
    with pytest.raises(ValueError):
        verify_action_evidence(**bad)
