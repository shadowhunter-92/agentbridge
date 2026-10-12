"""Gateway-independent evidence SDK integration with sandbox state."""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.sandbox_readback import SandboxTarget, SandboxReadOnlyObserver
from src.governance.trust_sdk import verify_action_evidence


def _pub(key):
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw).hex()


def test_embedded_sdk_verifies_independent_sandbox_claims(tmp_path):
    destination = Ed25519PrivateKey.generate()
    readback = Ed25519PrivateKey.generate()
    path = str(tmp_path / "destination.db")
    with SandboxTarget(path, sign=destination.sign) as target:
        receipt = target.commit(agent_id="agent", operation_id="sdk-op-1234567890",
                                fingerprint="signed-request")
        with SandboxReadOnlyObserver(path, destination_public_key_hex=_pub(destination),
                                     sign=readback.sign) as observer:
            independently_read, proof = observer.observe(
                agent_id="agent", operation_id="sdk-op-1234567890",
                fingerprint="signed-request")
            result = verify_action_evidence(
                destination_receipt=independently_read, readback_attestation=proof,
                agent_id="agent", operation_id="sdk-op-1234567890",
                fingerprint="signed-request", outcome="succeeded",
                external_reference=receipt["external_reference"],
                destination_key_hex=_pub(destination), readback_key_hex=_pub(readback))
            assert result.outcome == "succeeded"
            assert len(result.readback_sha256) == 64
            with pytest.raises(ValueError):
                verify_action_evidence(
                    destination_receipt=independently_read, readback_attestation=proof,
                    agent_id="agent", operation_id="sdk-op-1234567890",
                    fingerprint="signed-request", outcome="failed",
                    external_reference=receipt["external_reference"],
                    destination_key_hex=_pub(destination), readback_key_hex=_pub(readback))
