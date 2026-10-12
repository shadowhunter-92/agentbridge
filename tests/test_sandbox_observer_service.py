"""Independent sandbox observer HTTP boundary tests."""
import os
import stat
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
import pytest

from src.governance.sandbox_readback import SandboxTarget
from src.governance.sandbox_observer_service import create_observer_app
from src.governance.trust_sdk import verify_action_evidence


def _pub(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def test_standalone_service_authenticated_readback(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTBRIDGE_ENV", raising=False)
    destination, observer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    db = str(tmp_path / "target.db")
    sk = tmp_path / "observer.key"
    sk.write_bytes(observer.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption()))
    token = tmp_path / "observer.token"
    token.write_bytes(b"standalone-observer-token-should-be-secret-999")
    if os.name == "posix":
        sk.chmod(stat.S_IRUSR | stat.S_IWUSR)
        token.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with SandboxTarget(db, sign=destination.sign) as target:
        target.commit(agent_id="agent",operation_id="sandbox-long-id-001",fingerprint="fp")
    app = create_observer_app(destination_db=db, destination_key_hex=_pub(destination),
                              observer_key_file=str(sk), bearer_token_file=str(token))
    client = TestClient(app)
    route = "/v1/sandbox/readback"
    body = dict(agent_id="agent",operation_id="sandbox-long-id-001",fingerprint="fp")
    assert client.post(route,json=body).status_code == 401
    headers = {"Authorization": "Bearer standalone-observer-token-should-be-secret-999"}
    assert client.post(route,json={**body,"unexpected":1},headers=headers).status_code == 422
    assert client.post(route,json={**body,"operation_id":"missing"},headers=headers).status_code == 409
    response = client.post(route,json=body,headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert verify_action_evidence(
        destination_receipt=result["destination_receipt"],
        readback_attestation=result["readback_attestation"],
        agent_id=body["agent_id"], operation_id=body["operation_id"],
        fingerprint=body["fingerprint"], outcome="succeeded",
        external_reference="sandbox-effect:"+body["operation_id"],
        destination_key_hex=_pub(destination), readback_key_hex=_pub(observer)).outcome == "succeeded"
    monkeypatch.setenv("AGENTBRIDGE_ENV","production")
    with pytest.raises(RuntimeError):
        create_observer_app(destination_db=db, destination_key_hex=_pub(destination),
                             observer_key_file=str(sk), bearer_token_file=str(token))
