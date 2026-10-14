"""Externally pinned Evidence verifier adversarial tests."""
import copy
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from src.governance.sandbox_readback import SandboxTarget, SandboxReadOnlyObserver
from tools.verify_external_evidence import verify_bundle


def test_offline_external_verifier_and_fail_closed_cases(tmp_path):
    destination = Ed25519PrivateKey.generate()
    observer = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    def pub(key):
        return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    path = str(tmp_path / "destination.sqlite")
    with SandboxTarget(path, sign=destination.sign) as target:
        receipt = target.commit(agent_id="a", operation_id="op", fingerprint="fp")
    with SandboxReadOnlyObserver(path, destination_public_key_hex=pub(destination), sign=observer.sign) as reader:
        rec, readback = reader.observe(agent_id="a", operation_id="op", fingerprint="fp")
    assert rec == receipt
    bundle = {"receipt": receipt, "readback": readback, "observer_key_id": "observer-v1",
              "expected": {"agent_id": "a", "operation_id": "op", "fingerprint": "fp",
                           "outcome": "succeeded", "external_reference": receipt["external_reference"]}}
    trust = {"destination_public_key_hex": pub(destination), "observers": [
        {"key_id": "observer-v1", "public_key_hex": pub(observer), "state": "active"}]}
    assert verify_bundle(bundle, trust)["verdict"] == "signature_and_binding_verified"
    assert verify_bundle(bundle, trust, expected_action=bundle["expected"])["externally_expected_action_verified"]
    with pytest.raises(ValueError, match="independently expected"):
        verify_bundle(bundle, trust, expected_action={**bundle["expected"], "operation_id": "another-operation"})
    for mutation in [
        {"expected": {**bundle["expected"], "fingerprint": "other"}},
        {"receipt": {**receipt, "outcome": "failed"}},
        {"readback": {**readback, "signature_hex": "0" * 128}},
        {"observer_key_id": "missing"},
    ]:
        with pytest.raises((ValueError, KeyError)):
            verify_bundle({**bundle, **mutation}, trust)
    with pytest.raises(ValueError):
        verify_bundle(bundle, {**trust, "destination_public_key_hex": pub(Ed25519PrivateKey.generate())})
    bad = copy.deepcopy(trust)
    bad["observers"][0]["state"] = "revoked"
    with pytest.raises(ValueError):
        verify_bundle(bundle, bad)
    with pytest.raises(ValueError):
        verify_bundle(bundle, {})
